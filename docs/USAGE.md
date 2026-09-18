# Usage Guide

## Local Preview

Run the static preview server from the project root:

```bash
npm run serve
```

Then open `http://localhost:4173`. Do not open `public/index.html` directly because on-demand JSON requests require HTTP.

## Navigation

The site opens on `小红书` by default.

- `谛听-情报库`: `小红书`, `AI日报`, `TG日报`.
- `品牌-舆情监控`: `舆情焦点`, `全部舆情`, `舆情日报`, `设置`.

The app remembers the selected date and reading position for each page during the current browser session.

## Loading And Recovery

- Opening a page loads only that page's index and latest detail.
- Selecting another date loads only that date.
- Opening a conversation or Telegram comment drawer loads its separate detail file.
- A failed request retries twice automatically.
- After three failures, use the visible `重新加载` action; other pages remain usable.

## Scheduled Runs

- `08:00`: brand and Xiaohongshu daily run.
- `08:30`: AI and Telegram digest synchronization.
- `09:00`: primary public freshness check and bounded repair.
- `11:00`: conditional follow-up only when the primary check found an issue, could not complete, or performed a repair.

When all four modules are already current at the primary check, the secondary launch reads the local success marker and exits without another public request. A primary network failure, stale module or repair leaves no marker, so the secondary check still runs. A network failure never triggers repair. A stale module is retried at most twice per day. Brand data reuses the exact-date checkpoint when available; Xiaohongshu source collection runs again only when its own public date is stale. AI/TG repair does not consume X source quota. Set `BRAND_RADAR_HEALTH_FORCE_CHECK=1` for an intentional manual recheck.

Install or remove the repair check with:

```bash
npm run local:health:install
npm run local:health:uninstall
```

## Manual Validation

```bash
python3 scripts/security_check.py
python3 scripts/check_dashboard_data.py
python3 scripts/verify_data.py
node --check public/assets/app.js
npm run verify:browser
```

These checks use committed/local artifacts only and do not perform real social collection.
