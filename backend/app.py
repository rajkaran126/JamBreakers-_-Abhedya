"""AEGIS-LINK server: one WebSocket at /ws broadcasting at ~20 Hz, plus a few HTTP endpoints.

Run:  uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .commands import parse_command
from .config import Settings, settings as default_settings
from .protocol import SERVER_VERSION, envelope, load_schema
from .world_api import Message, World

log = logging.getLogger("aegis")
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"


def default_world_factory(cfg: Settings) -> World:
    if cfg.world == "sim":
        try:
            from sim.world import SimArena  # Phase 1
        except ImportError as exc:  # pragma: no cover - until Phase 1 lands
            raise RuntimeError("AEGIS_WORLD=sim but sim.world is not built yet") from exc
        return SimArena(cfg)
    from .fake_world import FakeArena
    return FakeArena(seed=cfg.seed)


class Client:
    """One connected screen. Messages queue per client so a slow phone never stalls the others."""

    def __init__(self, ws: WebSocket, maxsize: int):
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, text: str) -> None:
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.dropped += 1
        self.queue.put_nowait(text)


class Hub:
    def __init__(self, world: World, cfg: Settings):
        self.world = world
        self.cfg = cfg
        self.clients: set[Client] = set()
        self.session_id = uuid.uuid4().hex[:12]
        self.lock = asyncio.Lock()  # world is touched by the tick loop and by commands
        self.ticks = 0
        self.started = time.time()

    def broadcast(self, msgs: list[Message]) -> None:
        for m in msgs:
            text = json.dumps(m, separators=(",", ":"))
            for c in list(self.clients):
                c.offer(text)

    def hello(self) -> Message:
        return envelope("hello", "server", session_id=self.session_id, tick_hz=self.cfg.tick_hz,
                        slot_ms=self.cfg.slot_ms, **self.world.hello_info())

    async def tick_loop(self) -> None:
        period = 1.0 / self.cfg.tick_hz
        next_t = time.perf_counter()
        last = next_t
        while True:
            now = time.perf_counter()
            dt = now - last
            last = now
            try:
                async with self.lock:
                    msgs = self.world.step(min(dt, 0.25))
                self.broadcast(msgs)
            except Exception:  # never let one bad tick kill the broadcast
                log.exception("world.step failed")
                self.broadcast([envelope("error", "server", code="internal", message="Simulation tick failed; see server log.")])
            self.ticks += 1
            next_t += period
            delay = next_t - time.perf_counter()
            if delay < -period:  # fell far behind (laptop busy): resync instead of bursting
                next_t = time.perf_counter()
                delay = 0
            await asyncio.sleep(max(0.0, delay))

    async def handle_text(self, client: Client, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            client.offer(json.dumps(envelope("error", "server", code="bad_json", message="Message is not valid JSON.")))
            return
        req_id = data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), str) else None
        rid = {"req_id": req_id} if req_id else {}
        try:
            cmd = parse_command(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ()))
            msg = f"Invalid command: {where}: {first.get('msg')}" if where else f"Invalid command: {first.get('msg')}"
            client.offer(json.dumps(envelope("error", "server", code="invalid_command", message=msg, **rid)))
            return
        try:
            async with self.lock:
                out = self.world.handle(cmd)
        except Exception:
            log.exception("command failed: %s", cmd.action)
            out = [envelope("error", "server", code="internal", message=f"'{cmd.action}' failed; see server log.", **rid)]
        # errors go only to the sender; everything else is shared so every screen stays in sync
        errors = [m for m in out if m.get("type") == "error"]
        for m in errors:
            client.offer(json.dumps(m))
        self.broadcast([m for m in out if m.get("type") != "error"])


def lan_addresses() -> list[str]:
    ips: set[str] = set()
    with contextlib.suppress(OSError):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outbound interface
        ips.add(s.getsockname()[0])
        s.close()
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    return sorted(ip for ip in ips if not ip.startswith("127."))


def create_app(cfg: Settings | None = None, world_factory: Callable[[Settings], World] | None = None) -> FastAPI:
    cfg = cfg or default_settings
    world = (world_factory or default_world_factory)(cfg)
    hub = Hub(world, cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(hub.tick_loop())
        log.info("AEGIS-LINK %s up, world=%s, %g Hz", SERVER_VERSION, cfg.world, cfg.tick_hz)
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="AEGIS-LINK", version=SERVER_VERSION, lifespan=lifespan)
    app.state.hub = hub

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": SERVER_VERSION, "world": cfg.world, "clients": len(hub.clients),
                "ticks": hub.ticks, "uptime_s": round(time.time() - hub.started, 1), "session_id": hub.session_id}

    @app.get("/api/schema")
    async def schema() -> JSONResponse:
        return JSONResponse(load_schema())

    @app.get("/api/lan")
    async def lan() -> dict[str, Any]:
        ips = lan_addresses()
        return {"port": cfg.port, "ips": ips,
                "app_urls": [f"http://{ip}:{cfg.port}/app/" for ip in ips],
                "ws_urls": [f"ws://{ip}:{cfg.port}/ws" for ip in ips]}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        client = Client(ws, cfg.client_queue)
        client.offer(json.dumps(hub.hello()))
        hub.clients.add(client)

        async def sender() -> None:
            while True:
                text = await client.queue.get()
                await ws.send_text(text)

        send_task = asyncio.create_task(sender())
        try:
            while True:
                text = await ws.receive_text()
                await hub.handle_text(client, text)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("websocket error")
        finally:
            hub.clients.discard(client)
            send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await send_task

    # ---- static screens ----
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "console.html")

    viewer = ROOT / "viewer3d"
    if (viewer / "index.html").exists():
        @app.get("/view")
        @app.get("/view/")
        @app.get("/viewer")
        async def view_redirect() -> RedirectResponse:
            return RedirectResponse("/viewer/")
        app.mount("/viewer", StaticFiles(directory=viewer, html=True), name="viewer")

    mobile_dist = ROOT / "mobile" / "dist"
    if (mobile_dist / "index.html").exists():
        app.mount("/app", StaticFiles(directory=mobile_dist, html=True), name="app")
    else:
        @app.get("/app/")
        async def app_missing() -> JSONResponse:
            return JSONResponse({"detail": "Mobile app not built yet: cd mobile && npm install && npm run build"}, 404)

    @app.get("/app")
    async def app_slash() -> RedirectResponse:
        return RedirectResponse("/app/")

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
