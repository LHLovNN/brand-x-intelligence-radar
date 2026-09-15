# Implementation Notes

## Runtime Architecture

The product remains a static site, but archive data is no longer embedded into one growing page payload.

- `public/index.html` contains the shell and content-hashed asset references.
- `public/dashboard-data-bundle.js` is intentionally minimal.
- Page indexes contain lightweight date metadata and detail paths.
- Daily details live under their module-specific `daily/` directory.
- X conversation threads live under `dashboard-data/lazy/conversations/`.
- Telegram reply threads live under `dashboard-data/lazy/tg-replies/`.

The browser retries JSON loads three times in total. Route, date and drawer failures each have a visible local retry state.

## Content Policy

`src/pipeline/content_policy.py` is the shared deterministic policy layer for brand source posts, X conversation context, Xiaohongshu items, Telegram digest entries and Telegram replies.

Xiaohongshu candidates must meet metric gates and demonstrate substantive platform methodology. Target domains include account growth, monetization, risk control, account acquisition, platform rules, matrices, reverse engineering and device modification. A bounded semantic review then checks centrality, domain relevance, substance and low-value content. Stable reason codes are stored for diagnostics; free-form model explanations are not exposed publicly.

## Publication Isolation

The 08:00 and 08:30 jobs generate and commit only their own module artifacts. Shared assets are rebuilt only inside the publication stage.

- A shared lock serializes publication.
- Each publisher rebases before rebuilding shared assets.
- Push races retry the publication stage only, never collection.
- Post-push verification polls public JSON until expected dates appear or times out.
- Long-running collection, source synchronization and network publication commands have hard time limits.
- Run and publication locks record their owner process and recover automatically after a crash.
- Interrupted runs may leave module-owned lazy files; those files are allowed during the next recovery run and are staged with their owning module.
- The shared rebuild removes lazy JSON files that are no longer referenced by any public detail payload.

The Diting synchronization uses an isolated clean checkout by default so upstream synchronization cannot be blocked by unrelated edits in the primary checkout.

## Schedule

- `08:00`: brand and Xiaohongshu collection and publication.
- `08:30`: Diting AI/TG synchronization and publication.
- `10:00` and `14:00`: public freshness checks with bounded module repair.

The repair job skips all mutation when the public site is unreachable. When a module is reachable but stale, it records a per-day attempt before repair and stops after two attempts. An exact-date checkpoint prevents a brand repair from repeating primary collection; Xiaohongshu collection is refreshed only when that module is stale.

## Verification

```bash
python3 scripts/security_check.py
python3 scripts/check_dashboard_data.py
python3 scripts/verify_data.py
python3 scripts/report_run_summary.py
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall scripts src
node --check public/assets/app.js
node --check public/dashboard-data-bundle.js
npm run verify:browser
```

CI pins Playwright `1.62.1`, serves `public/` over HTTP, verifies the default Xiaohongshu route does not eagerly load brand data, exercises date-level loading, checks background refresh state preservation and stale-cache messaging, and checks lazy context/comment drawers and retry behavior.
