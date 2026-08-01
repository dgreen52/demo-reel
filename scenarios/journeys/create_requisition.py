"""Journey: create a requisition through the real UI, confirm it lands in the
list, then delete it so the run leaves inventory.db exactly as it found it.
Uses an admin-tier QA account because requisition creation is open to any
logged-in role but the cleanup delete is admin-only (app.py delete_requisition
is @admin_required). Tags the vendor field with 'QA-journey-<pid>' so a
skipped cleanup step stays trivially identifiable and never collides with a
real vendor name (standing task #2, PARTS-PROPOSALS.md).
"""
import os
import re


def run(page, base_url, check):
    username = os.environ.get("QA_ADMIN_USER", "qa-admin")
    password = os.environ.get("QA_ADMIN_PASS", "qa-admin-local-only")
    tag = f"QA-journey-{os.getpid()}"

    # Delete is gated behind a native confirm() dialog; auto-accept it for
    # every dialog this journey triggers (there's only ever the one).
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{base_url}/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
    check("admin login succeeded", "/login" not in page.url, f"url={page.url}")

    page.goto(f"{base_url}/requisitions")
    page.wait_for_load_state("networkidle")
    page.click('button[data-overlay-open="#createRequisitionModal"]')
    page.wait_for_selector("#createRequisitionForm", state="visible")
    page.fill("#createRequisitionForm input[name=vendor]", tag)
    page.fill("#createRequisitionForm input[name=line_part_number]", "QA-TEST-PN")
    page.fill("#createRequisitionForm input[name=line_description]", "Night-shift journey test line item")
    page.click("button[form=createRequisitionForm][type=submit]")
    page.wait_for_load_state("networkidle")

    check("creation flash shown",
          page.get_by_text(re.compile(r"Requisition .* created\.")).count() > 0)

    page.goto(f"{base_url}/requisitions?search={tag}&search_field=vendor")
    page.wait_for_load_state("networkidle")
    row = page.locator("table.requisitions-table tbody tr", has_text=tag)
    row_count = row.count()
    check("created requisition found by vendor search", row_count == 1, f"count={row_count}")

    if row_count != 1:
        return  # nothing safe to clean up if the create/find step didn't land cleanly

    delete_btn = row.first.locator('form[action$="/delete"] button[type=submit]')
    check("delete control present for admin", delete_btn.count() == 1)
    if delete_btn.count() != 1:
        return

    delete_btn.click()
    page.wait_for_load_state("networkidle")
    check("delete confirmation flash shown",
          page.get_by_text("Requisition deleted.").count() > 0)

    page.goto(f"{base_url}/requisitions?search={tag}&search_field=vendor")
    page.wait_for_load_state("networkidle")
    row_after_count = page.locator("table.requisitions-table tbody tr", has_text=tag).count()
    check("test requisition cleaned up (no longer in list)", row_after_count == 0,
          f"count={row_after_count}")
