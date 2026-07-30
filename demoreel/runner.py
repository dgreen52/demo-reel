"""Scenario runner: loads a scenario file, records it, encodes the outputs.

A scenario is a Python file defining:

    SCENARIO = {
        "name": "my-demo",              # output basename
        "mode": "web" | "extension",
        "url": "http://...",            # web mode
        "extension_dir": r"C:\\path",   # extension mode (unpacked)
        "page": "newtab.html",          # extension mode: page to open
        "viewport": (1280, 800),        # optional
        "gif_width": 900,               # optional
    }

    def run(page, act):
        act.pause(1.0)
        page.click("#thing")
        ...

`act` provides human-feeling helpers: pause(), type_like_human(), move_click().
"""

import importlib.util
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .encode import to_gif, to_mp4


class Act:
    """Human-pacing helpers so recordings don't look like a robot sneezed."""

    def __init__(self, page):
        self.page = page

    def pause(self, seconds: float = 0.8) -> None:
        time.sleep(seconds)

    def type_like_human(self, selector: str, text: str, delay_ms: int = 55) -> None:
        self.page.click(selector)
        self.page.type(selector, text, delay=delay_ms)

    def move_click(self, selector: str, settle: float = 0.35) -> None:
        el = self.page.locator(selector).first
        el.scroll_into_view_if_needed()
        el.hover()
        time.sleep(settle)
        el.click()
        time.sleep(settle)


def _load_scenario(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "SCENARIO") or not hasattr(mod, "run"):
        raise ValueError(f"{path} must define SCENARIO and run(page, act)")
    return mod


def record(scenario_path: str, output_dir: str = "output") -> dict:
    mod = _load_scenario(Path(scenario_path))
    cfg = mod.SCENARIO
    name = cfg["name"]
    viewport = cfg.get("viewport", (1280, 800))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    videos = out / f"_{name}_raw"
    videos.mkdir(exist_ok=True)

    with sync_playwright() as p:
        record_opts = dict(
            record_video_dir=str(videos),
            record_video_size={"width": viewport[0], "height": viewport[1]},
            viewport={"width": viewport[0], "height": viewport[1]},
        )
        if cfg["mode"] == "extension":
            ext = str(Path(cfg["extension_dir"]).resolve())
            profile = out / f"_{name}_profile"
            shutil.rmtree(profile, ignore_errors=True)  # every run starts clean
            context = p.chromium.launch_persistent_context(
                str(profile),
                headless=False,  # extensions need a headed browser
                args=[
                    f"--disable-extensions-except={ext}",
                    f"--load-extension={ext}",
                    "--hide-crash-restore-bubble",
                    # oversize the OS window so the page area >= viewport and
                    # the recording has no letterbox bars
                    f"--window-size={viewport[0] + 20},{viewport[1] + 140}",
                ],
                **record_opts,
            )
            # Resolve the extension id from its service worker / background page.
            ext_id = None
            deadline = time.time() + 10
            while ext_id is None and time.time() < deadline:
                workers = context.service_workers
                bgs = context.background_pages
                origin = None
                if workers:
                    origin = workers[0].url
                elif bgs:
                    origin = bgs[0].url
                if origin and origin.startswith("chrome-extension://"):
                    ext_id = origin.split("/")[2]
                else:
                    time.sleep(0.25)
            page = context.pages[0] if context.pages else context.new_page()
            if cfg.get("page", "").startswith("chrome://"):
                # e.g. chrome://newtab for new-tab-override extensions,
                # which may have no service worker to resolve an id from
                page.goto(cfg["page"])
            elif cfg.get("page"):
                if ext_id is None:
                    raise RuntimeError(
                        "Could not resolve extension id (no service worker or "
                        "background page appeared). For MV3 extensions with no "
                        "background, set SCENARIO['ext_id'] explicitly."
                    )
                page.goto(f"chrome-extension://{ext_id}/{cfg['page']}")
        else:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(**record_opts)
            page = context.new_page()
            page.goto(cfg["url"])

        try:
            mod.run(page, Act(page))
        finally:
            video = page.video
            context.close()  # flushes the recording
            webm = Path(video.path())

    trim = cfg.get("trim_start", 0.0)
    mp4 = to_mp4(webm, out / f"{name}.mp4", trim_start=trim)
    gif = to_gif(webm, out / f"{name}.gif", width=cfg.get("gif_width", 900),
                 trim_start=trim)
    shutil.rmtree(videos, ignore_errors=True)
    return {"mp4": str(mp4), "gif": str(gif)}
