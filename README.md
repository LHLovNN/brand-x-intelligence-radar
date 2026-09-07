# Brand X Intelligence Radar

Brand X Intelligence Radar is a static, Chinese-first intelligence dashboard.
It combines platform-change research, AI and Telegram digests, and brand public-opinion monitoring in one reading experience.

## Product Surface

The default page is `小红书` under `谛听-情报库`.

- `谛听-情报库`: `小红书`, `AI日报`, and `TG日报`.
- `品牌-舆情监控`: `舆情焦点`, `全部舆情`, `舆情日报`, and `设置`.

Xiaohongshu monitoring covers account growth, monetization, platform rules, risk control, account matrices, reverse engineering, and device modification.

## Loading Model

The site uses three levels of on-demand loading so archive growth does not slow the first screen:

1. Only data for the active page is requested.
2. Daily detail is requested only when its date is opened.
3. Conversation context and Telegram replies are stored separately and requested only when their drawer opens.

Failed JSON requests retry twice automatically. A visible retry action is shown if all three attempts fail.

## Local Preview

Use an HTTP server because the dashboard loads JSON files on demand:

```bash
npm run serve
```

Open `http://localhost:4173`. Opening `public/index.html` directly with `file://` is not supported.

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

The browser check uses a real local HTTP server and fails if Playwright is unavailable or page QA does not complete.
