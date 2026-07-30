"""Env-driven login setup for demoreel.live / demoreel.qa.

Credentials come from QA_USER / QA_PASS environment variables so nothing
sensitive lives in a file. Defaults target the local demo seed.

For a production sweep, use a dedicated LOW-PRIVILEGE read-only account,
never an admin.
"""

import os


def run(page):
    page.fill("input[name=username]", os.environ.get("QA_USER", "demo"))
    page.fill("input[name=password]", os.environ.get("QA_PASS", "demo123"))
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
