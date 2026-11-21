"""Connect to a running server, optionally send one command, and print message rates.

    python scripts/ws_probe.py                       # rates for 3 s
    python scripts/ws_probe.py --cmd '{"action":"launch_jammer","jammer_type":"barrage","pos":[100,100]}'
"""
import argparse
import asyncio
import json
import time

import websockets


async def main(url: str, cmd: str | None, seconds: float) -> None:
    async with websockets.connect(url) as ws:
        hello = json.loads(await ws.recv())
        print(f"hello: session={hello['session_id']} world={hello.get('world_source')} schema={hello['schema_version']}")
        if cmd:
            await ws.send(json.dumps({"type": "cmd", "id": "probe", **json.loads(cmd)}))
        counts: dict[str, int] = {}
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            m = json.loads(await ws.recv())
            counts[m["type"]] = counts.get(m["type"], 0) + 1
            if m["type"] in ("event", "decision", "error", "security"):
                print(f"  {m['type']}: {m.get('text') or m.get('reason') or m.get('message')}")
        print({k: round(v / seconds, 1) for k, v in counts.items()}, "msgs/s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--cmd")
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    asyncio.run(main(a.url, a.cmd, a.seconds))
