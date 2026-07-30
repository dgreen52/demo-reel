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

## Why bother

- **Reproducible**: the demo is code. App changed? Re-run the scenario, fresh GIF.
- **CI-able**: a demo that breaks is a UI regression test that failed.
- **Reviewable**: extract frames with ffmpeg and *look* at them — humans or AI
  agents can verify what the demo actually shows. (That's how this tool's own
  demos were verified: an AI agent pulled frames and caught an empty Paint canvas
  and a photobombing window before any human watched the video.)

MIT licensed.
