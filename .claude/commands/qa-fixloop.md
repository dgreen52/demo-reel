---
description: Batch-find UI issues with a QA sweep, then fix one-by-one with pixel verification after each fix
---

Run the QA fix-loop against the app the user names (ask for --url/--setup if
not obvious from context). Follow this protocol exactly:

## Phase 0 — know the humans (30 seconds, changes everything)

Before sweeping, establish from the user or project docs: who actually uses
this app, on what device, in what physical situation, arriving from where?
(e.g. "maintenance techs, phones, standing at a shelf mid-task, often
arriving via a QR label scan; admins on desktops doing purchasing.") Every
usability judgment in Phase 1 is made AS those people in that situation —
one-handed phone use, interrupted constantly, no patience for scrolling —
not as a developer admiring a layout.

## Phase 1 — batch diagnosis (the expensive pass; do it ONCE)

1. Make sure the target app is running (start it in the background if needed).
2. Full sweep: `python -m demoreel.qa --url <url> --setup <login> --discover
   --max 30 -o qa-fixloop/baseline`
3. Read REPORT.md, then READ EVERY SCREENSHOT (mobile especially) and write
   `qa-fixloop/FINDINGS.md`: severity-ranked (high/medium/low), each with
   route, evidence screenshot, and a concrete proposed fix. Include console
   and network evidence. Judge USABILITY, not just rendering: for each
   screen, name the user and the job they came to finish, then ask — is the
   primary action obvious, how many taps to the common task, is key info
   above the fold, are targets finger-sized, would a first-week employee
   get it without training? Workflow friction is a finding with the same
   rigor as a visual bug (but mark usability items as `[UX]` — the human
   decides product changes; don't auto-"fix" workflow design in Phase 2
   without explicit approval). If a RECOMMENDATIONS.md already exists from a
   --judge run, start from it and verify each item against the screenshots
   instead of re-judging.

## Phase 2 — fix loop (one finding at a time, verify by pixels)

For each finding, highest severity first:
1. Implement the smallest correct fix in the app's code.
2. Targeted re-sweep of ONLY the affected route(s): write them to a routes
   file and run with `--routes`, output to `qa-fixloop/check-<n>`.
   Do NOT re-run full sweeps or the AI judge mid-loop — targeted sweeps
   cost no tokens and take seconds.
3. Read the new screenshot(s). Fixed = the pixels prove it. Mark ✅ in
   FINDINGS.md with the verifying screenshot path.
4. Not fixed? One retry with a different approach. Still not? Mark ⚠️ with
   what you learned and move on — do not rabbit-hole.
5. Findings that are wrong or by-design: mark ❌ with one line of reasoning.

Rules:
- Verify with a RELOAD at each viewport (the tool does this) — never trust
  a resize alone for responsive-JS behavior.
- Multiple findings in one file may share a fix commit, but each still gets
  its own pixel verification.
- Never weaken auth, delete data, or change behavior beyond the finding.

### Delegating to subagents (optional, for larger finding lists)

Deal independent findings out to parallel subagent workers — you are the
lead; they are the line engineers:

- **Partition by FILE, not by finding.** Two findings touching the same
  file go to the same worker (or run serially) — parallel edits to one
  file collide.
- Each worker's brief: the finding, the evidence screenshot path, the
  proposed fix, and the exact targeted-sweep command to verify. The worker
  fixes, re-sweeps its route to its own output dir, READS the screenshot,
  and reports fixed/not with evidence.
- Use a cheaper/faster model for mechanical fixes (CSS tweaks, copy
  changes); keep the strongest model for gnarly layout or JS-behavior
  findings and for your own lead review.
- Batch trivial same-file nits into one worker rather than one-per-finding
  — subagents cost tokens; don't spawn five workers for five one-liners.
- The lead ALWAYS does Phase 3 personally: workers verify their own fix;
  only the lead verifies the whole.

## Phase 3 — regression pass (once, at the end)

1. Full sweep again → `qa-fixloop/final`.
2. Compare against baseline: every fixed finding still fixed, console still
   clean, no NEW breakage introduced by the fixes. Spot-read screenshots of
   every route you touched plus 2-3 you didn't.
3. Append a summary table to FINDINGS.md: finding / severity / status /
   evidence. Report: fixed, skipped, flagged — and what the human should
   review before shipping.

Token discipline: ONE diagnosis pass, ONE regression pass, targeted
no-token sweeps in between. If the user has usage concerns, skip --judge
and do the Phase 1 judgment yourself by reading the screenshots.
