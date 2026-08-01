"""Journey: create a requisition, receive it to inventory (same pattern as
Cycle 30's receive_to_inventory.py), then exercise the app's real "issue /
return" flow -- which isn't a separate route, it's the Move action on
/check/<id> targeting a *user's own username* as the destination location
(app.py's assigned_user_for_location()/apply_inventory_action() comments:
"This replaces the retired 'Checked Out' workflow: possession is shown simply
by moving an item to someone's location"). Moves the QA part to the admin
account's personal location (issue), asserts it flips to Unavailable, moves it
back to its original shelf location (return), asserts it flips back to
Available, then force-deletes the part and the requisition so the run leaves
inventory.db exactly as it found it (standing task #2, PARTS-PROPOSALS.md --
the "issue/return a QA-created part" journey in the task's own sequencing,
after login and create/receive).

Uses an admin-tier QA account throughout: receive-to-inventory, the
requisition delete, and the part force-delete are all admin-gated. Tags every
created record ('QA-journey-<pid>' vendor, 'QA-JOURNEY-<pid>' part number) so
a skipped cleanup step stays trivially identifiable and never collides with
real data.
"""
import os
import re
from urllib.parse import urlparse, parse_qs

# base.html's custom-dropdown widget hides real <select>/loc-combo hidden
# inputs behind CSS, so Playwright's own select_option()/fill() can time out
# waiting for visibility -- set the underlying value directly and dispatch the
# same 'change' event the widget's own JS fires on a real selection (same
# trick receive_to_inventory.py uses for the status <select>).
_SET_VALUE_JS = "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }"


def run(page, base_url, check):
    username = os.environ.get("QA_ADMIN_USER", "qa-admin")
    password = os.environ.get("QA_ADMIN_PASS", "qa-admin-local-only")
    pid = os.getpid()
    vendor_tag = f"QA-journey-{pid}"
    pn_tag = f"QA-JOURNEY-{pid}"

    # Delete/force-delete are gated behind native confirm() dialogs; auto-accept
    # every one this journey triggers.
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
              "Night-shift issue/return journey test line")
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
    modal.locator("select[name=status]").evaluate(_SET_VALUE_JS, "Received")
    page.click(f'button[form="edit-form-{req_id}"][type=submit]')
    page.wait_for_load_state("networkidle")

    check("redirected to receive-to-inventory prompt",
          f"/requisitions/{req_id}/receive-to-inventory" in page.url, f"url={page.url}")
    if f"/requisitions/{req_id}/receive-to-inventory" not in page.url:
        return

    # 4. Fill the pending line's location with an EXISTING location (reuse, don't
    # invent a new one) and push to inventory. Remember it -- it's where the
    # part returns to at the end of the issue/return cycle below.
    existing_location = ""
    if page.locator("#all-locations option").count():
        existing_location = page.eval_on_selector("#all-locations option", "el => el.value")
    existing_location = existing_location or "Main"
    page.locator("input.location-input").first.fill(existing_location)
    page.click('button:has-text("Push to Inventory")')
    page.wait_for_load_state("networkidle")
    qs = parse_qs(urlparse(page.url).query)
    check("redirected to label-print page with a pushed part id",
          "ids" in qs, f"url={page.url}")

    ids_param = qs.get("ids", [""])[0]
    part_id = ids_param.split(",")[0] if ids_param else ""
    check("new inventory part id captured from redirect", part_id.isdigit(), f"url={page.url}")
    if not part_id.isdigit():
        return

    # 5. ISSUE: on /check/<id>, the Move action targeting a user's own username
    # as the destination is the real "issue to a person" flow (app.py has no
    # separate checkout route -- possession = location is a username). Default
    # action is already 'move' (first entry in every asset class's action list).
    page.goto(f"{base_url}/check/{part_id}")
    page.wait_for_load_state("networkidle")
    check("Move is the default action on a fresh part",
          page.locator("#inventoryActionSelect").input_value() == "move")
    page.locator('#locationCombo input[name=location]').evaluate(_SET_VALUE_JS, username)
    page.click("button:has-text('Save Action')")
    page.wait_for_load_state("networkidle")
    check("issue (move-to-person) flash shown",
          page.get_by_text("Inventory status updated.").count() > 0)

    page.goto(f"{base_url}/check/{part_id}")
    page.wait_for_load_state("networkidle")
    badge_class = page.locator(".status-badge").first.get_attribute("class") or ""
    check("part shows Unavailable after being issued to a person",
          "status-badge--unavailable" in badge_class, f"class={badge_class}")

    # 6. RETURN: move it back to the real shelf location it was received to.
    page.locator('#locationCombo input[name=location]').evaluate(_SET_VALUE_JS, existing_location)
    page.click("button:has-text('Save Action')")
    page.wait_for_load_state("networkidle")
    check("return (move-back) flash shown",
          page.get_by_text("Inventory status updated.").count() > 0)

    page.goto(f"{base_url}/check/{part_id}")
    page.wait_for_load_state("networkidle")
    badge_class_after = page.locator(".status-badge").first.get_attribute("class") or ""
    check("part shows Available again after being returned",
          "status-badge--available" in badge_class_after, f"class={badge_class_after}")

    # 7. Verify the part, then walk the app's own built-in test-data cleanup
    # flow: Delete Item -> (blocked by its own received-transaction row) ->
    # Force Delete (same as receive_to_inventory.py's cleanup).
    page.goto(f"{base_url}/parts/{part_id}")
    page.wait_for_load_state("networkidle")
    check("part page shows the QA part number", page.get_by_text(pn_tag).count() > 0)

    page.goto(f"{base_url}/edit/{part_id}")
    page.wait_for_load_state("networkidle")
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

    # 8. Clean up the requisition itself.
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
