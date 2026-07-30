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


def _path_pattern(path: str) -> str:
    # collapse numeric path segments (record IDs) so /requisitions/58654/print
    # and /requisitions/58655/print count as the same pattern for capping
    # (found by automated QA review)
    return "/".join("#" if seg.isdigit() else seg for seg in path.split("/"))


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
    # sort-permutation links (?sort=x&dir=y) on the same page are visually
    # near-identical; cap how many query variants of one path we'll queue
    # (found by automated QA review)
    QUERY_VARIANT_CAP = 2
    query_variants: dict[str, int] = {}
    # same problem, different shape: distinct detail-page paths (e.g. a
    # /requisitions/<id>/print link per row on a list page) explode the
    # route budget just like query variants did; cap instances per
    # numeric-collapsed path pattern (found by automated QA review)
    PATH_PATTERN_CAP = 2
    path_patterns: dict[str, int] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport=dict(DESKTOP)).new_page()
        # The mobile pass emulates a REAL phone (mobile user-agent, touch,
        # device scale) - many apps branch on user-agent server-side, so a
        # desktop UA in a skinny window shows a layout no real user sees.
        mdev = p.devices.get("iPhone 13", {})
        # scale 1: evidence screenshots in logical px, not 3x retina monsters
        mpage = browser.new_context(**{**mdev, "viewport": dict(MOBILE),
                                       "device_scale_factor": 1}).new_page()

        console: list[dict] = []
        netfail: list[dict] = []
        for vp, pg in (("desktop", page), ("mobile", mpage)):
            pg.on("console", lambda m, v=vp: console.append(
                {"vp": v, "type": m.type, "text": m.text[:500]}))
            pg.on("pageerror", lambda e, v=vp: console.append(
                {"vp": v, "type": "pageerror", "text": str(e)[:500]}))
            pg.on("requestfailed", lambda r, v=vp: netfail.append(
                {"vp": v, "url": r.url[:300], "failure": str(r.failure)[:200]}))

        if setup:
            spec = importlib.util.spec_from_file_location("setup", setup)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        for pg in (page, mpage):
            pg.goto(base)
            if setup:
                mod.run(pg)  # login once per context; sessions persist

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
                page.screenshot(path=str(out / f"{slug}--desktop.png"),
                                full_page=True)

                mpage.goto(urllib.parse.urljoin(origin, path), timeout=15000)
                mpage.wait_for_load_state("networkidle", timeout=8000)
                time.sleep(0.3)
                mpage.screenshot(path=str(out / f"{slug}--mobile.png"),
                                 full_page=True)

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
                            if rel in visited or rel in queue \
                                    or SKIP.search(rel):
                                continue
                            if u.query:
                                seen = query_variants.get(u.path, 0)
                                if seen >= QUERY_VARIANT_CAP:
                                    continue
                                query_variants[u.path] = seen + 1
                            pattern = _path_pattern(u.path)
                            if pattern != u.path:
                                seen = path_patterns.get(pattern, 0)
                                if seen >= PATH_PATTERN_CAP:
                                    continue
                                path_patterns[pattern] = seen + 1
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


JUDGE_PROMPT = """\
You are a meticulous QA engineer reviewing a web app. This folder contains a \
QA sweep: REPORT.md (route/status/console/network evidence) and full-page \
screenshots named <route>--desktop.png and <route>--mobile.png.

Read REPORT.md, then LOOK at every screenshot. Desktop is the PRIMARY \
surface - judge it first and hardest; the mobile pass (captured with real \
phone emulation) is secondary but still required. Judge two layers:

1. VISUAL DEFECTS: layout breakage, clipped/overflowing text, overlapping \
elements, unusable responsive layouts, missing empty-states, inconsistent \
styling, and anything in the console/network detail.

2. PRODUCT USABILITY - for each screen, first ask: who comes here and what \
job are they trying to finish? Then judge it as that user: Is the primary \
action obvious and above the fold? How many taps/keystrokes to complete the \
most common task, and could it be fewer? Is the most important information \
visible without scrolling or horizontal panning? Are tap targets finger- \
sized on mobile and forms ergonomic (right input types, sane defaults)? \
Would a first-week employee understand this page without training? Flag \
workflow friction (dead ends, redundant confirmations, data the user must \
remember across pages) as findings with the same rigor as visual bugs.

Screenshots are full-page captures, so fixed-position elements render at \
their initial viewport spot - do not report that as overlap unless it would \
also occur live.

Write RECOMMENDATIONS.md: a severity-ranked (high/medium/low) list. Each \
item: route, what is wrong, the screenshot that shows it, and a concrete \
suggested fix. RECOMMEND ONLY - do not modify any application code. \
End with a one-paragraph overall health summary."""


def judge(out: Path, judge_cmd: str) -> bool:
    """Run a headless AI judgment pass over the sweep evidence."""
    import subprocess
    print(f"\njudging with: {judge_cmd} (this reads every screenshot; "
          f"it can take a few minutes)")
    try:
        r = subprocess.run(
            [judge_cmd, "-p", JUDGE_PROMPT,
             "--allowedTools", "Read", "Glob", "Grep", "Write"],
            cwd=str(out), timeout=1200)
        ok = r.returncode == 0 and (out / "RECOMMENDATIONS.md").exists()
    except FileNotFoundError:
        print(f"judge command not found: {judge_cmd}\n"
              "install the Claude CLI:  irm https://claude.ai/install.ps1 | iex\n"
              "(evidence is still in the output folder - judge it manually)")
        return False
    except subprocess.TimeoutExpired:
        print("judge timed out; evidence folder is still usable")
        return False
    if ok:
        print(f"recommendations: {out / 'RECOMMENDATIONS.md'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(prog="demoreel.qa")
    ap.add_argument("--url", required=True, help="base URL (login page ok)")
    ap.add_argument("--setup", help="python file with run(page), e.g. login")
    ap.add_argument("--routes", help="file of paths, one per line")
    ap.add_argument("--discover", action="store_true",
                    help="crawl same-origin links from swept pages")
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("-o", "--out", default="qa-out")
    ap.add_argument("--judge", action="store_true",
                    help="after the sweep, run a headless AI judgment pass "
                         "that writes RECOMMENDATIONS.md")
    ap.add_argument("--judge-cmd", default="claude",
                    help="command for the judge (default: claude)")
    a = ap.parse_args()
    routes = _load_routes(a.routes)
    if not routes and not a.discover:
        ap.error("give --routes and/or --discover")
    report = sweep(a.url, routes, a.setup, Path(a.out), a.discover, a.max)
    print(f"\nreport: {Path(a.out) / 'REPORT.md'}")
    errs = sum(len(r.get('console', [])) for r in report['results'])
    print(f"routes: {report['swept']}   console errors/warnings: {errs}")
    if a.judge:
        judge(Path(a.out), a.judge_cmd)


if __name__ == "__main__":
    main()
