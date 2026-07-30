# QA Findings — parts-inventory demo (2026-07-30)

Sweep: 18 routes, desktop + mobile (390px), console + network monitored.
Judgment pass: AI agent (Claude) reading every screenshot.

## Health summary

- **0 console errors / warnings across all 18 routes** — exceptional
- 0 failed network requests
- All routes 200
- Desktop layouts: clean across the board
- Mobile: 3 findings below

## Findings

### 1. ✅ FIXED — navbar subtitle clips at viewport edge (mobile)
**Route:** all (base template) · **Severity:** low · **Evidence:** `root--mobile.png`
"Parts & Requisitions" subtitle overflowed the 390px viewport next to the
two-airline wordmark. **Fix applied:** hide `.brand-subtitle` below 576px
(templates/base.html). **Verified:** re-swept `/`; navbar renders clean.

### 2. OPEN — requisitions board unusable at phone width
**Route:** `/requisitions` · **Severity:** medium · **Evidence:**
`requisitions--mobile.png` (17,688px tall — that IS the finding)
The kanban board stacks every column full-width into an endless vertical
strip. Suggest: horizontal scroll-snap container for columns below 768px,
or a list view fallback.

### 3. OPEN — filter panel defaults to expanded on mobile
**Route:** `/` · **Severity:** low · **Evidence:** `root--mobile.png`
The full filter stack (11 controls) occupies ~3 screens before the first
inventory row. The collapse control exists — default it to collapsed below
768px.

### 4. NOTE — floating Feedback button can cover form controls (mobile)
**Evidence:** `root--mobile.png` shows it over the Status select. Partly a
full-page-screenshot artifact (fixed-position elements render at their
viewport spot), but at 390px the FAB genuinely overlaps controls at some
scroll positions. Consider shrinking to an icon-only FAB below 576px.

## Tool finding (meta)
Route files written by PowerShell carry a UTF-8 BOM which broke route
parsing (404 on `﻿/`). Fixed in `demoreel/qa.py` (`utf-8-sig`).
