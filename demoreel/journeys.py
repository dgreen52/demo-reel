"""demoreel.journeys - interaction test runner: drives a real browser through
critical user journeys and ASSERTS outcomes, unlike demoreel.qa which only
captures screenshots for a human/agent to judge. Exit 0 = every check across
every journey passed, 1 = at least one failed (same convention as
tests/test_concurrency.py).

Usage:
    python -m demoreel.journeys --url http://127.0.0.1:5757 [--journey login]

Each scenarios/journeys/<name>.py must expose:
    def run(page, base_url, check) -> None
where check(name, ok, detail="") records one pass/fail assertion. Journeys
that create records must tag them with a 'QA-' prefix so they stay
identifiable and cleanable (standing task #2, PARTS-PROPOSALS.md).
"""

import argparse
import importlib.util
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

JOURNEYS_DIR = Path(__file__).resolve().parent.parent / "scenarios" / "journeys"


def _load(name: str):
    path = JOURNEYS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"journey_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _discover() -> list[str]:
    return sorted(p.stem for p in JOURNEYS_DIR.glob("*.py") if not p.stem.startswith("_"))


def main() -> int:
    ap = argparse.ArgumentParser(prog="demoreel.journeys")
    ap.add_argument("--url", required=True, help="app base URL, e.g. http://127.0.0.1:5757")
    ap.add_argument("--journey", action="append",
                     help="journey name (repeatable); default: every file in scenarios/journeys/")
    args = ap.parse_args()

    names = args.journey or _discover()
    if not names:
        print("No journeys found in", JOURNEYS_DIR)
        return 1

    all_checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name in names:
            page = browser.new_context(viewport={"width": 1360, "height": 850}).new_page()
            mod = _load(name)
            checks: list[tuple] = []

            def check(cname, ok, detail="", _checks=checks):
                _checks.append((cname, ok, detail))

            try:
                mod.run(page, args.url.rstrip("/"), check)
            except Exception as exc:
                checks.append((f"{name}: journey raised", False, str(exc)))
            page.close()
            all_checks.append((name, checks))
        browser.close()

    failed = 0
    for name, checks in all_checks:
        print(f"[{name}]")
        for cname, ok, detail in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {cname}" + (f"  ({detail})" if detail and not ok else ""))
            failed += 0 if ok else 1
    total = sum(len(c) for _, c in all_checks)
    print("-" * 64)
    if failed:
        print(f"RESULT: {failed}/{total} journey check(s) FAILED")
        return 1
    print(f"RESULT: all {total} journey checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
