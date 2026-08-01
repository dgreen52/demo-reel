"""Journey: create a requisition, mark its line received, walk through the real
Receive-to-Inventory prompt, verify the pushed part lands in inventory, then
force-delete the part and the requisition so the run leaves inventory.db exactly
as it found it. This is the natural next step after Cycle 29's create/delete-only
requisition journey -- it exercises the actual "green path" purchasing exists
for: buy something, receive it, it shows up on the shelf (standing task #2,
PARTS-PROPOSALS.md).

Uses an admin-tier QA account throughout: receive-to-inventory, the requisition
delete, and the part force-delete are all admin-gated. Tags every created
record ('QA-journey-<pid>' vendor, 'QA-JOURNEY-<pid>' part number) so a
skipped cleanup step stays trivially identifiable and never collides with real
data.
"""
import os
import re
from urllib.parse import urlparse, parse_qs


def run(page, base_url, check):
    username = os.environ.get("QA_ADMIN_USER", "qa-admin")
    password = os.environ.get("QA_ADMIN_PASS", "qa-admin-local-only")
    pid = os.getpid()
    vendor_tag = f"QA-journey-{pid}"
    pn_tag = f"QA-JOURNEY-{pid}"

    # Delete is gated behind native confirm() dialogs (requisition delete, part
    # delete, part force-delete); auto-accept every one this journey triggers.
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{base_url}/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle")
    check("admin login succeeded", "/login" not in page.url, f"url={page.url}")

    # 1. Create the requisition (same pattern as create_requisition.py).
    page.goto(f"{base_url}/requisitions")
    page.wait_for_load_state("networkidle")
    page.click('button[data-overlay-open="#createRequisitionModal"]')
    page.wait_for_selector("#createRequisitionForm", state="visible")
    page.fill("#createRequisitionForm input[name=vendor]", vendor_tag)
    page.fill("#createRequisitionForm input[name=line_part_number]", pn_tag)
    page.fill("#createRequisitionForm input[name=line_description]",
              "Night-shift receive-to-inventory journey test line")
    page.click("button[form=createRequisitionForm][type=submit]")
    page.wait_for_load_state("networkidle")
    check("creation flash shown",
          page.get_by_text(re.compile(r"Requisition .* created\.")).count() > 0)

    # 2. Find the row, pull its requisition id, open its View modal.
    page.goto(f"{base_url}/requisitions?search={vendor_tag}&search_field=vendor")
    page.wait_for_load_state("networkidle")
    row = page.locator("table.requisitions-table tbody tr", has_text=vendor_tag)
    row_count = row.count()
    check("created requisition found by vendor search", row_count == 1, f"count={row_count}")
    if row_count != 1:
        return

    modal_target = row.first.get_attribute("data-modal-target") or ""
    id_match = re.search(r"(\d+)$", modal_target)
    check("requisition id parsed from row", bool(id_match), f"data-modal-target={modal_target}")
    if not id_match:
        return
    req_id = id_match.group(1)

    row.first.locator("button[data-overlay-open]").click()
    page.wait_for_selector(f"#edit-form-{req_id}", state="visible")
    modal = page.locator(f"#reqModal{req_id}")

    # 3. Mark the manual line fully received and flip status to Received.
    modal.locator("input[name=line_received]").first.fill("1")
    # base.html replaces every <select> with a custom dropdown widget (hides the
    # real element behind class "cs-done"), so a plain select_option() times out
    # waiting for visibility -- set the underlying value directly instead, same
    # as the widget's own JS does on selection.
    modal.locator("select[name=status]").evaluate(
        "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }",
        "Received",
    )
    page.click(f'button[form="edit-form-{req_id}"][type=submit]')
    page.wait_for_load_state("networkidle")

    # update_requisition() auto-redirects here when a status transition leaves a
    # pending received>received_to_inventory delta (app.py ~line 15199).
    check("redirected to receive-to-inventory prompt",
          f"/requisitions/{req_id}/receive-to-inventory" in page.url, f"url={page.url}")
    if f"/requisitions/{req_id}/receive-to-inventory" not in page.url:
        return

    # 4. Fill the pending line's location with an EXISTING location (reuse, don't
    # invent a new one -- avoids leaving a stray row in the locations table) and
    # push to inventory.
    existing_location = ""
    if page.locator("#all-locations option").count():
        existing_location = page.eval_on_selector("#all-locations option", "el => el.value")
    page.locator("input.location-input").first.fill(existing_location or "Main")
    page.click('button:has-text("Push to Inventory")')
    page.wait_for_load_state("networkidle")
    # The "Pushed N line item(s)" flash is set on the receive-to-inventory submit
    # response, but that response immediately redirects to the chromeless label-
    # print page (no base-layout flash rendering there) -- so the real signal
    # this step worked is the redirect target itself, checked next.
    qs = parse_qs(urlparse(page.url).query)
    check("redirected to label-print page with a pushed part id",
          "ids" in qs, f"url={page.url}")

    # 5. The route redirects straight to the label-print page with the new
    # part id(s) in the query string -- read it from there instead of a fresh
    # inventory search.
    ids_param = qs.get("ids", [""])[0]
    part_id = ids_param.split(",")[0] if ids_param else ""
    check("new inventory part id captured from redirect", part_id.isdigit(), f"url={page.url}")

    if part_id.isdigit():
        # 6. Verify the pushed part is real, then walk the app's own built-in
        # test-data cleanup flow: Delete Item -> (blocked by its own
        # received-transaction row) -> Force Delete.
        page.goto(f"{base_url}/parts/{part_id}")
        page.wait_for_load_state("networkidle")
        check("received part page shows the QA part number",
              page.get_by_text(pn_tag).count() > 0)

        page.goto(f"{base_url}/edit/{part_id}")
        page.wait_for_load_state("networkidle")
        # Delete Item lives under the Edit tab (asset-tab-panel, hidden until
        # its tab is clicked -- Details is the default active pane).
        page.click('button.asset-tab[data-tab="edit"]')
        page.click("button:has-text('Delete Item')")
        page.wait_for_load_state("networkidle")
        check("force-delete confirmation page shown",
              page.get_by_text("related records exist").count() > 0)
        page.click("button:has-text('Force Delete')")
        page.wait_for_load_state("networkidle")
        check("part force-delete flash shown",
              page.get_by_text("Inventory item deleted.").count() > 0)

        page.goto(f"{base_url}/parts/{part_id}")
        page.wait_for_load_state("networkidle")
        check("deleted part no longer resolves",
              page.get_by_text("not found", exact=False).count() > 0 or "/parts/" not in page.url,
              f"url={page.url}")

    # 7. Clean up the requisition itself (same delete path as create_requisition.py).
    page.goto(f"{base_url}/requisitions?search={vendor_tag}&search_field=vendor")
    page.wait_for_load_state("networkidle")
    row_after = page.locator("table.requisitions-table tbody tr", has_text=vendor_tag)
    if row_after.count() == 1:
        delete_btn = row_after.first.locator('form[action$="/delete"] button[type=submit]')
        if delete_btn.count() == 1:
            delete_btn.click()
            page.wait_for_load_state("networkidle")
            check("requisition delete confirmation flash shown",
                  page.get_by_text("Requisition deleted.").count() > 0)

    page.goto(f"{base_url}/requisitions?search={vendor_tag}&search_field=vendor")
    page.wait_for_load_state("networkidle")
    final_count = page.locator("table.requisitions-table tbody tr", has_text=vendor_tag).count()
    check("test requisition cleaned up (no longer in list)", final_count == 0, f"count={final_count}")
