from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import uvicorn  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from traffic_platform.api.app import create_app  # noqa: E402


def build_app():
    web_root = ROOT / "web"
    if not (web_root / "index.html").is_file():
        raise RuntimeError(f"Missing web build: {web_root}")
    app = create_app(ROOT)
    app.mount("/", StaticFiles(directory=web_root, html=True), name="web-dashboard")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5177)
    args = parser.parse_args()
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="info")
