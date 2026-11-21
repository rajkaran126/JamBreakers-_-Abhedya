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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
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
                    # in a worker thread, so WebSocket I/O (phones, screens) keeps flowing while the slots run
                    msgs = await asyncio.to_thread(self.world.step, min(dt, 0.25))
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
    return sorted((ip for ip in ips if not ip.startswith(("127.", "169.254."))), key=_lan_rank)


def _lan_rank(ip: str) -> tuple[int, str]:
    """Order addresses so the QR code shows the one phones can most likely reach first:
    the Windows mobile hotspot, then home/office Wi-Fi ranges, and virtual adapters (WSL, Docker,
    Hyper-V, VirtualBox usually sit in 172.16-31 or 192.168.56) last."""
    a, b = (int(x) for x in ip.split(".")[:2])
    if ip.startswith("192.168.137."):
        return 0, ip
    if ip.startswith("192.168.56."):
        return 4, ip
    if a == 192 and b == 168:
        return 1, ip
    if a == 10:
        return 2, ip
    if a == 172 and 16 <= b <= 31:
        return 3, ip
    return 2, ip


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

    @app.middleware("http")
    async def no_stale_screens(request, call_next):
        # screens must never run a stale cached copy after an update (revalidate; 304 when unchanged)
        response = await call_next(request)
        if request.url.path.startswith(("/viewer", "/app", "/console", "/demo", "/intro")) or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": SERVER_VERSION, "world": cfg.world, "clients": len(hub.clients),
                "ticks": hub.ticks, "uptime_s": round(time.time() - hub.started, 1), "session_id": hub.session_id,
                "overrun_ticks": getattr(hub.world, "overrun_ticks", 0),
                "tick_cpu_ms": round(1000 * getattr(hub.world, "_cost_ema", 0.0), 1)}

    @app.get("/api/schema")
    async def schema() -> JSONResponse:
        return JSONResponse(load_schema())

    @app.get("/api/lan")
    async def lan() -> dict[str, Any]:
        ips = lan_addresses()
        return {"port": cfg.port, "ips": ips,
                "app_urls": [f"http://{ip}:{cfg.port}/app/" for ip in ips],
                "ws_urls": [f"ws://{ip}:{cfg.port}/ws" for ip in ips]}

    @app.get("/api/scenarios")
    async def scenarios() -> JSONResponse:
        return JSONResponse(json.loads((ROOT / "shared" / "scenarios.json").read_text(encoding="utf-8")))

    results_dir = ROOT / "results"

    @app.get("/api/benchmark/latest")
    async def bench_latest() -> JSONResponse:
        f = results_dir / "benchmark_latest.json"
        if not f.exists():
            f = ROOT / "docs" / "benchmark_results.json"   # the published run ships with the repo
        if not f.exists():
            return JSONResponse({"detail": "No benchmark yet: press Benchmark or run python -m sim.benchmark"}, 404)
        return JSONResponse(json.loads(f.read_text()))

    @app.get("/api/recordings")
    async def recordings() -> JSONResponse:
        """Spectrum recordings the CNN panel can replay (recordings/*.npz, see ai/sources.py)."""
        from ai.sources import list_recordings
        return JSONResponse(list_recordings())

    @app.get("/api/mission-log")
    async def mission_log(format: str = "csv"):
        """The current run's audit trail: every AI decision and its reason, safety-guard corrections,
        events, security tests and a per-second score snapshot. ?format=csv (download) or json."""
        lg = getattr(hub.world, "log", None)
        if lg is None:
            return JSONResponse({"detail": "This world keeps no mission log."}, 404)
        if format == "json":
            return JSONResponse(lg.to_json())
        name = "aegis_mission_log_" + time.strftime("%Y%m%d_%H%M%S") + ".csv"
        return Response(lg.to_csv(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/report")
    async def mission_report(download: int = 1):
        """The last finished mission as one self-contained HTML report (chart, AI OFF vs AI ON table, AI decisions,
        raw log as CSV inside). ?download=0 opens it in the browser instead of saving it."""
        snap = getattr(hub.world, "last_report", None)
        if not snap:
            return JSONResponse({"detail": "No finished mission yet: run a scenario to the end, then download its report."}, 404)
        from sim.report_html import build_report_html
        body = build_report_html(snap)
        stamp = time.strftime("%Y%m%d_%H%M", time.localtime(snap.get("finished_wall", time.time())))
        name = f"ABHEDYA_{snap['msg'].get('scenario', 'mission')}_{stamp}.html"
        disp = "attachment" if download else "inline"
        return Response(body, media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'{disp}; filename="{name}"', "Cache-Control": "no-store"})

    @app.get("/results/{name}")
    async def result_file(name: str):
        f = (results_dir / name).resolve()
        if f.parent != results_dir.resolve() or f.suffix not in (".json", ".csv") or not f.exists():
            return JSONResponse({"detail": "not found"}, 404)
        return FileResponse(f, filename=f.name)

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
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        icon = ROOT / "mobile" / "dist" / "icons" / "icon-192.png"
        return FileResponse(icon, media_type="image/png") if icon.exists() else JSONResponse({}, 404)

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
        @app.get("/demo")
        @app.get("/demo/")
        async def demo_redirect() -> RedirectResponse:
            return RedirectResponse("/viewer/demo.html")
        app.mount("/viewer", StaticFiles(directory=viewer, html=True), name="viewer")

    intro_dist = ROOT / "intro" / "dist"          # the mission deck (React + Framer Motion + 3D), the way in
    if (intro_dist / "index.html").exists():
        @app.get("/intro")
        @app.get("/start")
        @app.get("/missions")
        async def intro_redirect() -> RedirectResponse:
            return RedirectResponse("/intro/")
        app.mount("/intro", StaticFiles(directory=intro_dist, html=True), name="intro")

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
