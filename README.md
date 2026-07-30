# demo-reel 🎬

Scripted, reproducible demo videos for your apps. Write a ~40-line scenario file,
get a polished `.mp4` and a README-ready `.gif`. No screen recorder, no editing,
no re-doing the take because you sneezed.

Built because I had eleven repos that needed demo GIFs and zero interest in
recording them by hand. The RetrOS demo below was produced by
[`scenarios/retros.py`](scenarios/retros.py) — boot screen, Minesweeper,
a sine wave doodled in Paint, and a window drag, identical on every run:

![RetrOS demo](https://raw.githubusercontent.com/dgreen52/RetrOS/main/screenshots/demo.gif)

## How it works

| Mode | Backend |
|---|---|
| `web` | Playwright Chromium (headless), records the browser context |
| `extension` | Headed Chromium with `--load-extension`, fresh profile every run |

Playwright records `.webm`; ffmpeg post-processes to `.mp4` (x264) and `.gif`
(two-pass palette encode — small files that don't look like a fax).

## Usage

```
pip install playwright && playwright install chromium
python -m demoreel scenarios/my_demo.py -o output
```

A scenario is a plain Python file:

```python
SCENARIO = {
    "name": "my-demo",
    "mode": "web",
    "url": "http://localhost:5757",
    "viewport": (1280, 800),
    "trim_start": 1.0,       # cut page-load blankness from the output
}

def run(page, act):
    act.pause(1.0)
    act.type_like_human("#username", "demo")
    act.move_click("button[type=submit]")
    ...
```

`page` is a normal Playwright page — anything Playwright can do, your demo can do.
`act` adds human pacing (`pause`, `type_like_human`, `move_click`) so recordings
don't look like a robot sneezed on the keyboard.

## Live mode: eyes for AI coding agents 👁️

`demoreel.live` turns the same machinery into a **live viewer** an AI agent can use
while it builds: a daemon holds one persistent Playwright session on your app
(log in once via `--setup`), and every check after that is ~1 second:

```
python -m demoreel.live serve --url http://127.0.0.1:5757/login --setup scenarios/parts_login.py
python -m demoreel.live snap /dashboard        # → .liveview/snap-001.png
python -m demoreel.live snap -s ".navbar"      # screenshot one element
python -m demoreel.live console                # console messages + JS errors
```

The agent reads the PNG and *sees exactly what you'd see* — then reads `console`
and catches the JS errors nobody pasted. Build → snap → look → fix, in seconds,
no human screenshotting anything. (This README's demos were QA'd exactly that way.)
The control API binds to localhost only.

## QA mode: an agent-powered QA department 🔍

`demoreel.qa` sweeps your app and collects the evidence a QA pass needs:

```
python -m demoreel.qa --url http://127.0.0.1:5757/login --setup scenarios/parts_login.py --discover --max 25
```

Per route: a **desktop and a mobile screenshot**, console messages and JS
errors, failed network requests, and HTTP status — emitted as `report.json` +
`REPORT.md`. The judgment layer is deliberately not automated: hand the folder
to a vision-capable AI agent to read every screenshot and write `FINDINGS.md`.

The loop this enables: **sweep → agent reads pixels → findings → agent fixes
the code → re-sweep the route → fix verified by pixels.** First real run (18
routes of a Flask inventory system) caught a navbar wordmark clipping at
390px; the fix was applied and pixel-verified without a human screenshotting
anything. See [qa-out/FINDINGS.md](qa-out/FINDINGS.md) for what a findings
pass looks like.

## Why bother

- **Reproducible**: the demo is code. App changed? Re-run the scenario, fresh GIF.
- **CI-able**: a demo that breaks is a UI regression test that failed.
- **Reviewable**: extract frames with ffmpeg and *look* at them — humans or AI
  agents can verify what the demo actually shows. (That's how this tool's own
  demos were verified: an AI agent pulled frames and caught an empty Paint canvas
  and a photobombing window before any human watched the video.)

MIT licensed.
