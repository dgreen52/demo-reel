"""RetrOS demo: desktop -> Minesweeper -> Paint doodle -> window drag."""

import math

SCENARIO = {
    "name": "retros",
    "mode": "extension",
    "extension_dir": r"C:\Dillon\resume\publish\extensions\retros",
    "page": "chrome://newtab",
    "viewport": (1280, 800),
    "gif_width": 900,
    "trim_start": 3.5,  # skip page-load blank + most of the boot screen
}


def _try(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def run(page, act):
    # let the boot screen play, then close the welcome "Read Me" window
    act.pause(4.5)
    _try(lambda: page.locator(".win", has_text="Read Me")
         .locator(".win-ctrl.close").click(timeout=2000))
    act.pause(0.8)

    # Start menu -> Minesweeper
    act.move_click("#startBtn")
    act.pause(0.9)
    act.move_click("#startList >> text=Minesweeper")
    act.pause(1.2)

    # sweep some actual mines (.ms-cell only — not the difficulty buttons)
    cells = page.locator(".ms-cell")
    n = cells.count()
    for frac in (0.28, 0.44, 0.61, 0.77):
        _try(lambda i=int(n * frac): cells.nth(i).click())
        act.pause(0.8)
    act.pause(0.8)

    # Start menu -> Paint; pick a color and doodle INSIDE the canvas
    act.move_click("#startBtn")
    act.pause(0.9)
    act.move_click("#startList >> text=Paint")
    act.pause(1.2)
    _try(lambda: page.locator(".paint-sw").nth(4).click())  # a nice green
    canvas = page.locator(".paint-canvas").last
    box = canvas.bounding_box()
    if box:
        # margins keep the whole sine wave inside the canvas
        x0 = box["x"] + 14
        x1 = box["x"] + box["width"] - 14
        ymid = box["y"] + box["height"] * 0.55
        amp = box["height"] * 0.18
        page.mouse.move(x0, ymid)
        page.mouse.down()
        for i in range(48):
            t = i / 47
            page.mouse.move(x0 + t * (x1 - x0),
                            ymid + math.sin(t * math.pi * 3) * amp, steps=2)
        page.mouse.up()
    act.pause(1.0)

    # drag the Paint window by its titlebar for a little window-manager flex
    bar = page.locator(".win", has_text="Paint").locator(".win-titlebar")
    bb = bar.bounding_box()
    if bb:
        sx, sy = bb["x"] + bb["width"] * 0.4, bb["y"] + bb["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + 320, sy + 130, steps=25)
        page.mouse.up()
    act.pause(2.0)
