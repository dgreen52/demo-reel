# Deploying nightly QA against a live internal system

The one-command flow: sweep the live app read-only, then have a headless AI
judge write `RECOMMENDATIONS.md` — waiting for you every morning.

```powershell
python -m demoreel.qa --url http://<server>:5757/login `
    --setup scenarios\login_env.py --discover --max 30 `
    -o "qa-runs\$(Get-Date -Format yyyy-MM-dd)" --judge
```

## Setup (once)

1. `pip install playwright && playwright install chromium`
2. Install the Claude CLI: `irm https://claude.ai/install.ps1 | iex`
   (the `--judge` step invokes `claude -p` headless; it shares your login)
3. **Create a dedicated low-privilege QA account in the app** — the sweep
   should authenticate as a plain read-only user, never an admin. If your
   app has roles, this is what they're for.
4. Set credentials as environment variables (never in files):
   `setx QA_USER qa-viewer` / `setx QA_PASS <its password>`

## Safety notes for production targets

- The sweep only *navigates* (GET requests) and never submits forms; paths
  matching logout/delete/restore/restart/etc. are skipped by a blocklist
  (see `SKIP` in `demoreel/qa.py` — extend it for app-specific routes).
- Defense in depth: the low-privilege account means even an unexpected GET
  can't reach destructive admin routes.
- Schedule it off-hours. The sweep is light (one browser, sequential), but
  there is no reason to crawl during peak use.
- The judge only gets Read/Glob/Grep/Write tools and runs *in the output
  folder* — it reads evidence and writes recommendations; it never touches
  application code.

## Nightly schedule (Windows Task Scheduler)

```powershell
$act = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -Command "cd C:\path\to\demo-reel; python -m demoreel.qa --url http://<server>:5757/login --setup scenarios\login_env.py --discover --max 30 -o qa-runs\$(Get-Date -Format yyyy-MM-dd) --judge"'
$trig = New-ScheduledTaskTrigger -Daily -At 3am
Register-ScheduledTask -TaskName "parts-nightly-qa" -Action $act -Trigger $trig
```

Each run lands in a dated folder: screenshots, `REPORT.md` (evidence),
`RECOMMENDATIONS.md` (the AI's severity-ranked read on how things *actually
look*). Skim it with coffee; fix what's worth fixing.
