"""Journey: sign in with a QA account, land on an authenticated page, sign
out again, confirm a protected page bounces back to /login afterward.
Read-only -- creates no records, so no 'QA-' tagging/cleanup is needed here
(unlike journeys that create requisitions/parts/work orders).
"""
import os


def run(page, base_url, check):
    page.goto(f"{base_url}/login")
    page.fill("input[name=username]", os.environ.get("QA_USER", "qa-local"))
    page.fill("input[name=password]", os.environ.get("QA_PASS", "qa-local-only"))
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")

    check("login redirected off /login", "/login" not in page.url, f"url={page.url}")
    check("no invalid-credentials flash shown",
          page.get_by_text("Invalid username or password").count() == 0)

    page.locator("#accountStatusTrigger").click()
    page.locator("button.dropdown-item.text-danger", has_text="Logout").click()
    page.wait_for_load_state("networkidle")
    check("logout landed back on /login", "/login" in page.url, f"url={page.url}")

    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    check("visiting a protected page after logout bounces to /login",
          "/login" in page.url, f"url={page.url}")
