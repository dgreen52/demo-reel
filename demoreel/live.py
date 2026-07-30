"""demoreel.live - persistent live viewer: eyes for AI coding agents.

A daemon holds one long-lived Playwright session on the app you're building.
An agent (or you) then asks for instant screenshots and console output:

    python -m demoreel.live serve --url http://127.0.0.1:5757 [--setup login.py]
    python -m demoreel.live snap                 # screenshot current page
    python -m demoreel.live snap /requisitions   # navigate + screenshot
    python -m demoreel.live snap -s ".navbar"    # screenshot one element
    python -m demoreel.live console              # recent console msgs + JS errors
    python -m demoreel.live stop

Why a daemon: the session persists, so login happens once and every check
after that is ~1s. Screenshots land in .liveview/ as PNGs — an AI agent just
reads the file and *sees* the app.

The control API binds to 127.0.0.1 only.
"""

import argparse
import importlib.util
import json
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CONTROL_PORT = 7788
SNAP_DIR = Path(".liveview")


# ----------------------------- daemon side -----------------------------

def serve(url: str, setup: str | None, viewport: tuple[int, int],
          port: int) -> None:
    from playwright.sync_api import sync_playwright

    SNAP_DIR.mkdir(exist_ok=True)
    console_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        ).new_page()

        page.on("console", lambda m: console_log.append(
            {"t": time.strftime("%H:%M:%S"), "type": m.type, "text": m.text}))
        page.on("pageerror", lambda e: console_log.append(
            {"t": time.strftime("%H:%M:%S"), "type": "pageerror", "text": str(e)}))

        page.goto(url)
        if setup:
            spec = importlib.util.spec_from_file_location("setup", setup)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run(page)  # e.g. log in; session persists from here on

        base = url
        counter = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):  # quiet
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                try:
                    if u.path == "/snap":
                        path = q.get("path", [None])[0]
                        sel = q.get("sel", [None])[0]
                        full = q.get("full", ["0"])[0] == "1"
                        if path:
                            page.goto(urllib.parse.urljoin(base, path))
                            page.wait_for_load_state("networkidle", timeout=8000)
                        counter["n"] += 1
                        out = SNAP_DIR / f"snap-{counter['n']:03d}.png"
                        if sel:
                            page.locator(sel).first.screenshot(path=str(out))
                        else:
                            page.screenshot(path=str(out), full_page=full)
                        self._json({"file": str(out.resolve()),
                                    "url": page.url, "title": page.title()})
                    elif u.path == "/console":
                        n = int(q.get("n", ["30"])[0])
                        out = console_log[-n:]
                        if q.get("clear", ["0"])[0] == "1":
                            console_log.clear()
                        self._json({"messages": out})
                    elif u.path == "/goto":
                        page.goto(urllib.parse.urljoin(
                            base, q.get("path", ["/"])[0]))
                        self._json({"url": page.url, "title": page.title()})
                    elif u.path == "/state":
                        self._json({"url": page.url, "title": page.title()})
                    elif u.path == "/stop":
                        self._json({"bye": True})
                        raise KeyboardInterrupt
                    else:
                        self._json({"error": "unknown endpoint"}, 404)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._json({"error": str(e)}, 500)

        httpd = HTTPServer(("127.0.0.1", port), Handler)
        print(f"liveview: watching {url}  (control on 127.0.0.1:{port})")
        try:
            httpd.serve_forever()  # single-threaded: handlers share the page
        except KeyboardInterrupt:
            pass
        finally:
            browser.close()


# ----------------------------- client side -----------------------------

def _call(endpoint: str, port: int, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/{endpoint}?{qs}", timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser(prog="demoreel.live")
    ap.add_argument("--port", type=int, default=CONTROL_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the live-view daemon")
    s.add_argument("--url", required=True)
    s.add_argument("--setup", help="python file with run(page), e.g. a login")
    s.add_argument("--viewport", default="1360x850")

    snap = sub.add_parser("snap", help="screenshot the live session")
    snap.add_argument("path", nargs="?", help="navigate to this path first")
    snap.add_argument("-s", "--sel", help="CSS selector: shoot one element")
    snap.add_argument("--full", action="store_true", help="full-page shot")

    c = sub.add_parser("console", help="recent console messages + JS errors")
    c.add_argument("-n", type=int, default=30)
    c.add_argument("--clear", action="store_true")

    g = sub.add_parser("goto", help="navigate the live session")
    g.add_argument("path")

    sub.add_parser("state", help="current url + title")
    sub.add_parser("stop", help="stop the daemon")

    a = ap.parse_args()
    if a.cmd == "serve":
        w, h = (int(x) for x in a.viewport.split("x"))
        serve(a.url, a.setup, (w, h), a.port)
        return

    try:
        if a.cmd == "snap":
            r = _call("snap", a.port, path=a.path, sel=a.sel,
                      full="1" if a.full else "")
        elif a.cmd == "console":
            r = _call("console", a.port, n=a.n, clear="1" if a.clear else "")
        elif a.cmd == "goto":
            r = _call("goto", a.port, path=a.path)
        else:
            r = _call(a.cmd, a.port)
    except urllib.error.URLError:
        sys.exit("liveview daemon not running - start it with: "
                 "python -m demoreel.live serve --url <app-url>")
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
