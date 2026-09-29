"""Start CAD Copilot on this computer and open it in the browser (used by run.bat / run.sh)."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["APP_MODE"] = "desktop"  # this launcher is the desktop copy, whatever .env says

import uvicorn  # noqa: E402


def free_port(start: int) -> int:
    """First free port from `start` - so a web copy already running on 8501 can't hijack the browser tab."""
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"No free port between {start} and {start + 49}.")


def open_when_ready(url: str):
    """Open the browser only once this server answers as the desktop copy."""
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as r:
                if b'"desktop":true' in r.read().replace(b" ", b""):
                    webbrowser.open(url)
                    return
        except OSError:
            pass
        time.sleep(0.5)
    print("The app did not start - see the messages above.")


if __name__ == "__main__":
    port = free_port(int(os.environ.get("PORT", "8501")))
    url = f"http://127.0.0.1:{port}"
    print(f"CAD Copilot (desktop, works offline) is starting at {url}")
    print("Keep this window open while you use it; close it to stop the app.")
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("app.server:app", host="127.0.0.1", port=port, log_level="warning")
