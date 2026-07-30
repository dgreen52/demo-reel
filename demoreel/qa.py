"""demoreel.qa - agentic QA sweep: collect the evidence, let an agent judge it.

Walks your app's routes and captures, per route:
  - a desktop AND a mobile screenshot
  - console messages and uncaught page errors
  - failed network requests and non-2xx document responses

Output: a folder of screenshots + report.json + REPORT.md (evidence tables).
The judgment layer is deliberately NOT automated: hand the folder to an AI
agent (or a human) to read the screenshots and write findings. Pixels don't
lie, and a vision-capable agent catches "that dropdown is clipped" better
than any assertion library.

Usage:
    python -m demoreel.qa --url http://127.0.0.1:5757 --setup login.py \
        [--routes routes.txt] [--discover] [-o qa-out] [--max 25]

--routes    file with one path per line (# comments ok)
--discover  also crawl same-origin links found on the seed pages
Both may be combined; --discover alone starts from "/".
Destructive-looking paths (logout, delete, restore, ...) are skipped.
"""

import argparse
import importlib.util
import json
import re
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP = {"width": 1360, "height": 850}
MOBILE = {"width": 390, "height": 844}
SKIP = re.compile(
    r"logout|signout|delete|remove|restore|restart|shutdown|reset|"
    r"\.(zpl|pdf|csv|xlsx|zip|png|jpg)$", re.I)


def _slug(path: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")
    return s or "root"


def _load_routes(routes_file: str | None) -> list[str]:
    if not routes_file:
        return []
    # utf-8-sig: tolerate the BOM that Windows editors and PowerShell
    # Set-Content love to prepend
    lines = Path(routes_file).read_text(encoding="utf-8-sig").splitlines()
    return [ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith("#")]


def sweep(base: str, routes: list[str], setup: str | None, out: Path,
          discover: bool, max_routes: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    origin = f"{urllib.parse.urlparse(base).scheme}://{urllib.parse.urlparse(base).netloc}"
    queue = list(dict.fromkeys(routes or ["/"]))
    visited: list[str] = []
    results: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport=dict(DESKTOP)).new_page()

        console: list[dict] = []
        netfail: list[dict] = []
        page.on("console", lambda m: console.append(
            {"type": m.type, "text": m.text[:500]}))
        page.on("pageerror", lambda e: console.append(
            {"type": "pageerror", "text": str(e)[:500]}))
        page.on("requestfailed", lambda r: netfail.append(
            {"url": r.url[:300], "failure": str(r.failure)[:200]}))

        page.goto(base)
        if setup:
            spec = importlib.util.spec_from_file_location("setup", setup)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run(page)

        while queue and len(visited) < max_routes:
            path = queue.pop(0)
            if path in visited or SKIP.search(path):
                continue
            visited.append(path)
            console.clear()
            netfail.clear()
            slug = _slug(path)
            entry = {"path": path, "slug": slug}
            try:
                resp = page.goto(urllib.parse.urljoin(origin, path),
                                 timeout=15000)
                page.wait_for_load_state("networkidle", timeout=8000)
                time.sleep(0.3)
                entry["status"] = resp.status if resp else None
                entry["title"] = page.title()

                page.set_viewport_size(DESKTOP)
                page.screenshot(path=str(out / f"{slug}--desktop.png"),
                                full_page=True)
                page.set_viewport_size(MOBILE)
                time.sleep(0.4)  # let responsive layout settle
                page.screenshot(path=str(out / f"{slug}--mobile.png"),
                                full_page=True)
                page.set_viewport_size(DESKTOP)

                entry["console"] = [c for c in console
                                    if c["type"] in ("error", "warning",
                                                     "pageerror")]
                entry["failed_requests"] = list(netfail)

                if discover:
                    for href in page.eval_on_selector_all(
                            "a[href]", "els => els.map(e => e.href)"):
                        u = urllib.parse.urlparse(href)
                        if f"{u.scheme}://{u.netloc}" == origin:
                            rel = u.path + (f"?{u.query}" if u.query else "")
                            if rel not in visited and rel not in queue \
                                    and not SKIP.search(rel):
                                queue.append(rel)
            except Exception as e:
                entry["error"] = str(e)[:300]
            results.append(entry)
            print(f"  [{len(visited):>2}] {path}  "
                  f"({entry.get('status', 'ERR')})")

        browser.close()

    report = {"base": base, "swept": len(results), "results": results}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    _write_md(report, out)
    return report


def _write_md(report: dict, out: Path) -> None:
    lines = [
        "# QA Sweep — evidence report", "",
        f"Base: `{report['base']}` — {report['swept']} routes swept.", "",
        "This file is the *evidence*. The findings pass — an agent or human",
        "reading every screenshot and judging what's wrong — comes next and",
        "belongs in `FINDINGS.md`.", "",
        "| Route | Status | Console errors | Failed requests | Screenshots |",
        "|---|---|---|---|---|",
    ]
    for r in report["results"]:
        if "error" in r:
            lines.append(f"| `{r['path']}` | NAV ERROR | — | — | {r['error']} |")
            continue
        ncon = len(r.get("console", []))
        nnet = len(r.get("failed_requests", []))
        con = f"⚠️ {ncon}" if ncon else "0"
        net = f"⚠️ {nnet}" if nnet else "0"
        lines.append(
            f"| `{r['path']}` | {r['status']} | {con} | {net} | "
            f"[desktop]({r['slug']}--desktop.png) · "
            f"[mobile]({r['slug']}--mobile.png) |")
    detail = [r for r in report["results"]
              if r.get("console") or r.get("failed_requests")]
    if detail:
        lines += ["", "## Console / network detail", ""]
        for r in detail:
            lines.append(f"### `{r['path']}`")
            for c in r.get("console", []):
                lines.append(f"- **{c['type']}**: {c['text']}")
            for f in r.get("failed_requests", []):
                lines.append(f"- **request failed**: {f['url']} — {f['failure']}")
            lines.append("")
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(prog="demoreel.qa")
    ap.add_argument("--url", required=True, help="base URL (login page ok)")
    ap.add_argument("--setup", help="python file with run(page), e.g. login")
    ap.add_argument("--routes", help="file of paths, one per line")
    ap.add_argument("--discover", action="store_true",
                    help="crawl same-origin links from swept pages")
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("-o", "--out", default="qa-out")
    a = ap.parse_args()
    routes = _load_routes(a.routes)
    if not routes and not a.discover:
        ap.error("give --routes and/or --discover")
    report = sweep(a.url, routes, a.setup, Path(a.out), a.discover, a.max)
    print(f"\nreport: {Path(a.out) / 'REPORT.md'}")
    errs = sum(len(r.get('console', [])) for r in report['results'])
    print(f"routes: {report['swept']}   console errors/warnings: {errs}")


if __name__ == "__main__":
    main()
