"""demoreel.live - persistent live viewer + DRIVER: eyes AND hands for agents.

A daemon holds one long-lived Playwright session on the app you're building, so
an agent can not only SEE the app but actually USE it — click, fill, submit —
and walk entire workflows the way a real human would, judging friction at each
step.

    python -m demoreel.live serve --url http://127.0.0.1:5757 [--setup login.py]

Look:
    python -m demoreel.live snap [/path]        # screenshot (optionally navigate first)
    python -m demoreel.live snap -s ".navbar"   # screenshot one element
    python -m demoreel.live console             # recent console msgs + JS errors
    python -m demoreel.live state               # current url + title
    python -m demoreel.live goto /requisitions  # navigate

Act (each auto-snaps the result + reports any JS error the action triggered —
this is the drive-and-observe loop for workflow QA):
    python -m demoreel.live click --text "Add New Part"   # click by VISIBLE TEXT (human-like)
    python -m demoreel.live click --sel "#submit"         # or by CSS selector
    python -m demoreel.live fill  --sel "input[name=qty]" --value "3"
    python -m demoreel.live fill  --label "Vendor" --value "Acme"   # by field label
    python -m demoreel.live select --sel "select[name=status]" --value "Open"
    python -m demoreel.live press --key Enter
    python -m demoreel.live stop

Targeting by --text / --label mirrors how a human scans a page ("click the button
that SAYS Submit"), which is exactly what the first-week / intuitiveness test needs.
Control API binds to 127.0.0.1 only. Use QA-prefixed test data — you are driving a
REAL app against a REAL (local, disposable) DB.
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

        def _snap(sel=None, full=False):
            counter["n"] += 1
            out = SNAP_DIR / f"snap-{counter['n']:03d}.png"
            if sel:
                page.locator(sel).first.screenshot(path=str(out))
            else:
                page.screenshot(path=str(out), full_page=full)
            return str(out.resolve())

        def _settle():
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            time.sleep(0.25)

        def _locator(q):
            """Resolve a target from query params the way a human would find it:
            visible text first, then label, then raw CSS selector."""
            text = q.get("text", [None])[0]
            label = q.get("label", [None])[0]
            sel = q.get("sel", [None])[0]
            if text:
                # a button/link/control that SAYS this (what a human clicks)
                return page.get_by_role(
                    "button", name=text, exact=False).or_(
                    page.get_by_role("link", name=text, exact=False)).or_(
                    page.get_by_text(text, exact=False)).first
            if label:
                return page.get_by_label(label, exact=False).first
            if sel:
                return page.locator(sel).first
            raise ValueError("need --text, --label, or --sel")

        def _act(fn, q):
            """Run an interaction, then auto-snap + report JS errors it caused."""
            before = len(console_log)
            fn()
            _settle()
            new_msgs = [m for m in console_log[before:]
                        if m["type"] in ("error", "pageerror", "warning")]
            return {"snap": _snap(), "url": page.url, "title": page.title(),
                    "new_console": new_msgs}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
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
                            _settle()
                        self._json({"file": _snap(sel=sel, full=full),
                                    "url": page.url, "title": page.title()})
                    elif u.path == "/click":
                        self._json(_act(lambda: _locator(q).click(timeout=8000), q))
                    elif u.path == "/fill":
                        val = q.get("value", [""])[0]
                        self._json(_act(lambda: _locator(q).fill(val, timeout=8000), q))
                    elif u.path == "/select":
                        val = q.get("value", [None])[0]
                        lbl = q.get("optlabel", [None])[0]
                        def _sel_opt():
                            loc = page.locator(q.get("sel", [""])[0]).first
                            loc.select_option(label=lbl) if lbl else loc.select_option(val)
                        self._json(_act(_sel_opt, q))
                    elif u.path == "/press":
                        key = q.get("key", ["Enter"])[0]
                        self._json(_act(lambda: page.keyboard.press(key), q))
                    elif u.path == "/console":
                        n = int(q.get("n", ["30"])[0])
                        out = console_log[-n:]
                        if q.get("clear", ["0"])[0] == "1":
                            console_log.clear()
                        self._json({"messages": out})
                    elif u.path == "/goto":
                        page.goto(urllib.parse.urljoin(base, q.get("path", ["/"])[0]))
                        _settle()
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
                    # a failed interaction is itself a finding (element not found,
                    # not clickable, ambiguous) — return it, don't crash the daemon
                    self._json({"error": str(e)[:400], "url": page.url,
                                "title": page.title()}, 500)

        httpd = HTTPServer(("127.0.0.1", port), Handler)
        print(f"liveview: driving {url}  (control on 127.0.0.1:{port})")
        try:
            httpd.serve_forever()  # single-threaded: handlers share the page
        except KeyboardInterrupt:
            pass
        finally:
            browser.close()


# ----------------------------- client side -----------------------------

def _call(endpoint: str, port: int, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
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

    cl = sub.add_parser("click", help="click by --text (human-like), --label, or --sel")
    cl.add_argument("--text"); cl.add_argument("--label"); cl.add_argument("--sel")

    fi = sub.add_parser("fill", help="type into a field by --sel, --label, or --text")
    fi.add_argument("--value", required=True)
    fi.add_argument("--sel"); fi.add_argument("--label"); fi.add_argument("--text")

    se = sub.add_parser("select", help="pick a dropdown option (--sel + --value/--optlabel)")
    se.add_argument("--sel", required=True)
    se.add_argument("--value"); se.add_argument("--optlabel")

    pr = sub.add_parser("press", help="press a keyboard key (default Enter)")
    pr.add_argument("--key", default="Enter")

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
        elif a.cmd == "click":
            r = _call("click", a.port, text=a.text, label=a.label, sel=a.sel)
        elif a.cmd == "fill":
            r = _call("fill", a.port, value=a.value, sel=a.sel, label=a.label, text=a.text)
        elif a.cmd == "select":
            r = _call("select", a.port, sel=a.sel, value=a.value, optlabel=a.optlabel)
        elif a.cmd == "press":
            r = _call("press", a.port, key=a.key)
        elif a.cmd == "console":
            r = _call("console", a.port, n=a.n, clear="1" if a.clear else "")
        elif a.cmd == "goto":
            r = _call("goto", a.port, path=a.path)
        else:
            r = _call(a.cmd, a.port)
    except urllib.error.URLError:
        sys.exit("liveview daemon not running - start it with: "
                 "python -m demoreel.live serve --url <app-url> --setup <login.py>")
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
