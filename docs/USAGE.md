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
- `08:45`: read-only freshness audit and notification.

The 08:45 audit does not rerun collection and does not call source or language-model services. If it reports an issue, first use the reported category:

- `上游未更新`: confirm the upstream digest has produced today's files.
- `本地同步失败`: inspect the latest module run log and scheduler state.
- `发布未生效`: compare local dates with the public JSON dates and inspect the publication workflow.

## Manual Validation

```bash
python3 scripts/security_check.py
python3 scripts/check_dashboard_data.py
python3 scripts/verify_data.py
node --check public/assets/app.js
npm run verify:browser
```

These checks use committed/local artifacts only and do not perform real social collection.
