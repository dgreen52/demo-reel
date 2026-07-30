"""Setup for demoreel.live: log into the parts demo once; session persists."""


def run(page):
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "admin123")
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
