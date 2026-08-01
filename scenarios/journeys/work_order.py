"""Journey: create a Work Order (Maintenance Request), walk it through its
full status pipeline, and clean up via the admin-only hard-delete -- the last
unbuilt leg of standing task #2's own sequencing (login [Cycle 28] -> create/
delete requisition [29] -> receive-to-inventory [30] -> issue/return a part
[31] -> **WO create -> status walk -> return-notify** [this cycle]).

"return-notify" maps to 'Return to Stores', the terminal status in
PART_REQUEST_STATUSES (app.py) that closes a work order (stamps
closed_at/closed_by). There is no separate notification-send route in this
app to assert against -- checked app.py first (grepped for
notify_maintenance/notify_checkin): those are user-profile toggle columns
with no consumer anywhere, so "notify" here just means "the request actually
closes", the one real observable effect. This journey asserts that, via the
audit-trail entry the close action writes (app.py's
summarize_part_request_update_changes()), not the closed_at date input --
that input pre-fills with today's date even on an open request
(part_request.html's `{{ (part_request.closed_at or today_iso or '')[:10] }}`),
so it can't tell "closed" from "not yet closed".

The status <select> here (like the requisition-modal one Cycle 30 hit) is
hijacked by base.html's global custom-dropdown widget (`cs-done` class hides
the real element), so Playwright's own select_option() times out waiting for
visibility -- same fix as Cycles 30/31: set `.value` directly and dispatch
the `change` event the widget's own JS fires on a real selection.
"""
import os
import re

# base.html's custom-dropdown widget hides the real <select> behind CSS;
# Playwright's select_option()/fill() can time out waiting for visibility --
# set the underlying value directly and dispatch the same 'change' event the
# widget's own JS fires on a real selection (same trick as Cycles 30/31).
_SET_VALUE_JS = "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }"


def run(page, base_url, check):
    username = os.environ.get("QA_ADMIN_USER", "qa-admin")
    password = os.environ.get("QA_ADMIN_PASS", "qa-admin-local-only")
    pid = os.getpid()
    pn_tag = f"QA-JOURNEY-{pid}"

    # Admin delete is gated behind a native confirm() dialog; auto-accept it.
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{base_url}/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
    check("admin login succeeded", "/login" not in page.url, f"url={page.url}")

    # 1. Create the Work Order.
    page.goto(f"{base_url}/maintenance-requests")
    page.wait_for_load_state("networkidle")
    page.click('button[data-overlay-open="#createMrModal"]')
    page.wait_for_selector("#createMrForm", state="visible")
    page.fill("#createMrForm textarea[name=part_name]", "Night-shift WO journey test")
    page.fill("#createMrForm input[name=part_pn]", pn_tag)
    page.click("button[form=createMrForm][type=submit]")
    page.wait_for_load_state("networkidle")
    check("creation redirected to the WO detail page",
          re.search(r"/part-requests/\d+", page.url) is not None, f"url={page.url}")

    id_match = re.search(r"/part-requests/(\d+)", page.url)
    if not id_match:
        return
    wo_id = id_match.group(1)
    detail_url = f"{base_url}/part-requests/{wo_id}"

    def current_status():
        return page.locator(".doc-idbox tr", has_text="Status").locator(".v").inner_text().strip()

    check("new WO starts Open", current_status() == "Open", f"status={current_status()}")

    # 2. Status walk: Open -> In Progress -> Waiting Parts -> Return to Stores.
    for step_status in ("In Progress", "Waiting Parts", "Return to Stores"):
        page.locator("select[name=status]").evaluate(_SET_VALUE_JS, step_status)
        page.click("#saveBtn")
        page.wait_for_load_state("networkidle")
        check(f"save redirected back to the WO ({step_status})",
              detail_url in page.url, f"url={page.url}")
        page.goto(detail_url)
        page.wait_for_load_state("networkidle")
        check(f"WO shows {step_status} after save",
              current_status() == step_status, f"status={current_status()}")

    # 3. "return-notify": confirm the close actually happened via the audit
    # trail entry the close action writes (the real observable effect).
    check("audit trail records the closing transition",
          page.get_by_text(re.compile(r"Status: Waiting Parts -> Return to Stores")).count() > 0)

    # 4. Verify it's findable via the list page's own search, then admin-delete
    # it so inventory.db ends exactly as it started.
    page.goto(f"{base_url}/maintenance-requests?search={pn_tag}")
    page.wait_for_load_state("networkidle")
    row = page.locator(".mr-table-wrap tbody tr[data-update-target]", has_text=pn_tag)
    row_count = row.count()
    check("closed WO found by search", row_count == 1, f"count={row_count}")
    if row_count != 1:
        return

    delete_btn = row.first.locator('form[action$="/delete"] button[type=submit]')
    check("admin delete button present", delete_btn.count() == 1)
    if delete_btn.count() != 1:
        return
    delete_btn.click()
    page.wait_for_load_state("networkidle")
    check("delete flash shown", page.get_by_text("deleted.", exact=False).count() > 0)

    page.goto(f"{base_url}/maintenance-requests?search={pn_tag}")
    page.wait_for_load_state("networkidle")
    final_count = page.locator(".mr-table-wrap tbody tr[data-update-target]", has_text=pn_tag).count()
    check("test WO cleaned up (no longer in list)", final_count == 0, f"count={final_count}")
