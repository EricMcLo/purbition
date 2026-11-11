#!/usr/bin/env python3
"""Full-page mobile screenshot via Chrome DevTools Protocol (no clipping).

Usage: tmp/cdp_shot.py <url> <output.png> [width]

Launches headless Chrome on a debugging port, sets a mobile device emulation
viewport (width x full content height), then captures the ENTIRE page.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
# Use a profile dir under the current working directory so this script works
# on any laptop regardless of username (the previous hard-coded
# `/Users/eric.lo/...` path broke on machines where the home dir was different).
PROFILE_DIR = os.path.join(os.getcwd(), "tmp", "chrome-profile")


def main():
    url = sys.argv[1]
    out = sys.argv[2]
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 390

    os.makedirs(PROFILE_DIR, exist_ok=True)
    chrome = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE_DIR}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port()
        # open a new tab to the target url
        tab = _send_http("PUT", f"/json/new?{urllib.request.quote(url, safe='')}", body="")
        ws_url = tab["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        _cmd(ws, "Page.enable")
        _cmd(ws, "Runtime.enable")
        _cmd(ws, "Network.enable")
        # wait for page load
        time.sleep(1.5)
        # get full content size (informational only)
        metrics = _cmd(ws, "Page.getLayoutMetrics")
        css = metrics["result"]["cssContentSize"]
        full_height = int(css["height"])

        # mobile viewport: force mobile width; let captureBeyondViewport grab
        # the ENTIRE scrollable page height (no clipping at a fixed viewport)
        _cmd(ws, "Emulation.setDeviceMetricsOverride", {
            "width": width,
            "height": 640,
            "deviceScaleFactor": 1,
            "mobile": True,
            "screenWidth": width,
        })
        _cmd(ws, "Emulation.setEmulatedMedia", {"media": "screen"})
        time.sleep(0.5)
        shot = _cmd(ws, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        data = base64.b64decode(shot["result"]["data"])
        with open(out, "wb") as f:
            f.write(data)
        print(f"wrote {out} ({width}px wide, {full_height}css-px tall)")
        ws.close()
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.kill()


def _wait_port(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if _try_connect(PORT):
            return True
        time.sleep(0.2)
    raise RuntimeError("Chrome debugging port did not come up")


def _try_connect(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _send_http(method, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _cmd(ws, method, params=None):
    global _id
    _id = _id + 1
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg


_id = 0


if __name__ == "__main__":
    main()
