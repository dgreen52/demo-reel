"""Parts inventory demo: login -> dashboard -> parts -> requisitions -> Bin Bingo."""

SCENARIO = {
    "name": "parts-inventory",
    "mode": "web",
    "url": "http://127.0.0.1:5757/login",
    "viewport": (1360, 850),
    "gif_width": 960,
    "trim_start": 0.6,
}


def _try(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def _tour(page, act, path, dwell=2.2, scroll=520):
    page.goto(f"http://127.0.0.1:5757{path}")
    act.pause(dwell * 0.55)
    _try(lambda: page.mouse.wheel(0, scroll))
    act.pause(dwell * 0.45)


def run(page, act):
    # login like a human
    act.pause(1.0)
    act.type_like_human("input[name=username]", "admin")
    act.pause(0.3)
    act.type_like_human("input[name=password]", "admin123")
    act.pause(0.5)
    act.move_click("button[type=submit], input[type=submit]")
    act.pause(2.0)

    # the grand tour
    _tour(page, act, "/", dwell=2.8)
    _tour(page, act, "/overview", dwell=2.6)
    _tour(page, act, "/requisitions", dwell=2.8)
    _tour(page, act, "/reports", dwell=2.2)
    _tour(page, act, "/labels", dwell=2.2)
    _tour(page, act, "/bingo", dwell=3.0, scroll=300)
    act.pause(1.2)
