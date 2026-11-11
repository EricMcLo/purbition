#!/usr/bin/env python3
"""Full-page mobile audit: screenshots at iPhone 15 + iPhone 15 Pro Max sizes.

Usage: bin/phone_audit.py [--open] [--server]

Runs headless Chrome via CDP, visits every key page at two device widths,
and saves full-page PNGs to tmp/phone_audit/.

Flags:
  --open     Open each screenshot after saving (default: open all at end)
  --server   Start a local gunicorn on :8080 first (kills any existing)
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9334  # avoid collide with any manual cdp_shot.py instance
PROFILE_DIR = os.path.join(os.getcwd(), "tmp", "chrome-phone-audit")
OUT_DIR = os.path.join(os.getcwd(), "tmp", "phone_audit")

# Device definitions: (label, css_width, device_scale_factor)
DEVICES = [
    ("iphone15",     393, 3),
    ("iphone15pro",  430, 3),
]

# Pages to audit: (label, path)
# Adventure view/edit need a real share_id — we pull from the local DB.
def _get_local_share_ids():
    """Pull up to 2 share_ids from the local SQLite DB for live-page screenshots."""
    try:
        import sqlite3
        conn = sqlite3.connect(os.path.join(os.getcwd(), "database.db"))
        rows = conn.execute(
            "SELECT share_id FROM adventures WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 2"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _build_pages():
    share_ids = _get_local_share_ids()
    pages = [
        ("home",            "/"),
        ("create",          "/create"),
        ("manage",          "/manage"),
    ]
    if share_ids:
        pages.append(("adventure", f"/adventure/{share_ids[0]}"))
        pages.append(("edit",      f"/adventure/{share_ids[0]}/edit"))
    if len(share_ids) > 1:
        pages.append(("adventure2", f"/adventure/{share_ids[1]}"))
    return pages


def main():
    do_open = "--open" in sys.argv
    start_server = "--server" in sys.argv

    if start_server:
        _start_server()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)

    pages = _build_pages()
    manifest = []  # (filename, page_label, device_label, width, height)

    chrome = _start_chrome()
    try:
        _wait_port()
        for device_label, css_width, scale in DEVICES:
            device_dir = os.path.join(OUT_DIR, device_label)
            os.makedirs(device_dir, exist_ok=True)
            for page_label, path in pages:
                url = f"http://127.0.0.1:8080{path}"
                fname = f"{page_label}_{device_label}.png"
                out_path = os.path.join(device_dir, fname)
                try:
                    height = _screenshot(url, out_path, css_width, scale)
                    manifest.append((fname, page_label, device_label, css_width, height))
                    print(f"  {device_label:12s} {page_label:12s} {css_width}x{height}px -> {fname}")
                except Exception as e:
                    print(f"  {device_label:12s} {page_label:12s} FAILED: {e}")
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.kill()

    # Summary
    print(f"\n{'='*60}")
    print(f"Phone audit complete: {len(manifest)} screenshots")
    print(f"Output: {OUT_DIR}/")
    print(f"{'='*60}")
    for fname, page, device, w, h in manifest:
        print(f"  {device:12s} {page:12s} {w}x{h}px  {fname}")

    if do_open:
        for fname, _, _, _, _ in manifest:
            # open from both device dirs
            for d in DEVICES:
                p = os.path.join(OUT_DIR, d[0], fname)
                if os.path.exists(p):
                    subprocess.Popen(["open", p])


def _screenshot(url, out_path, width, scale_factor):
    """Open a new tab, emulate a mobile viewport, capture full-page screenshot."""
    tab = _send_http("PUT", f"/json/new?{urllib.request.quote(url, safe='')}")
    ws_url = tab["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    try:
        _cmd(ws, "Page.enable")
        _cmd(ws, "Runtime.enable")
        _cmd(ws, "Network.enable")
        # Set mobile viewport BEFORE waiting for page load so the page renders
        # at the correct width from the start (avoids layout reflow artifacts).
        _cmd(ws, "Emulation.setDeviceMetricsOverride", {
            "width": width,
            "height": 640,
            "deviceScaleFactor": scale_factor,
            "mobile": True,
            "screenWidth": width,
        })
        _cmd(ws, "Emulation.setEmulatedMedia", {"media": "screen"})
        # Wait for page load + JS (theme/font init, wizard, etc.)
        time.sleep(2.0)

        # Get full content height
        metrics = _cmd(ws, "Page.getLayoutMetrics")
        cssContentSize = metrics["result"]["cssContentSize"]
        full_height = int(cssContentSize["height"])

        shot = _cmd(ws, "Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
        })
        data = base64.b64decode(shot["result"]["data"])
        with open(out_path, "wb") as f:
            f.write(data)

        # Close the tab to free memory (best-effort — Chrome may already be closing it)
        try:
            _send_http("GET", f"/json/close/{tab['id']}")
        except Exception:
            pass
        return full_height
    finally:
        ws.close()


def _start_chrome():
    # Kill any stale Chrome on this port from a previous run
    subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], capture_output=True)
    time.sleep(0.3)
    # Wipe stale profile — cached state can cause viewport width artifacts
    if os.path.exists(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    return subprocess.Popen(
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


def _start_server():
    """Kill any existing gunicorn on 8080, then start fresh."""
    try:
        subprocess.run(["pkill", "-f", "gunicorn.*8080"], capture_output=True)
        time.sleep(1)
    except Exception:
        pass
    subprocess.Popen(
        [os.path.join(os.getcwd(), "venv", "bin", "gunicorn"),
         "-b", "127.0.0.1:8080", "app:app"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server
    for _ in range(30):
        try:
            s = socket.create_connection(("127.0.0.1", 8080), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("gunicorn did not start on :8080")


def _wait_port(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Chrome debugging port did not come up")


def _send_http(method, path, body=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.data = body.encode() if isinstance(body, str) else body
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code} from {method} {path}: {body_text[:200]}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bad JSON from {method} {path}: {raw[:200]}") from e


_id = 0

def _cmd(ws, method, params=None):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg


if __name__ == "__main__":
    main()
