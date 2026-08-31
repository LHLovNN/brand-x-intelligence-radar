const fs = require("fs");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (error) {
  console.error("Playwright is not installed. Install it before running browser verification.");
  process.exit(1);
}

const root = path.resolve(__dirname, "..");
const publicDir = path.join(root, "public");
const outDir = path.join(root, "qa-artifacts", "screenshots");
const localBrowserCandidates = [
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
].filter(Boolean);

function isIgnorableConsoleError(text) {
  return /^Failed to load resource: the server responded with a status of 404/i.test(String(text || ""));
}

function localBrowserExecutable() {
  return localBrowserCandidates.find((candidate) => fs.existsSync(candidate));
}

function readText(relativePath) {
  return fs.readFileSync(path.join(publicDir, relativePath), "utf8");
}

function readJson(relativePath) {
  return JSON.parse(readText(relativePath));
}

function readDataBundle() {
  const text = readText("dashboard-data-bundle.js").trim();
  const prefix = "window.__DASHBOARD_DATA__ = ";
  if (!text.startsWith(prefix)) return {};
  return JSON.parse(text.slice(prefix.length).replace(/;$/, ""));
}

function emptyPlatformTrendPayload() {
  return {
    platform: "xiaohongshu",
    display_name: "小红书",
    topic_label: "小红书增长方法",
    date: "",
    generated_at: "",
    generated_at_label: "",
    window_label: "",
    items: [],
    collection_status: {
      status: "empty",
      warnings: [],
      accepted_count: 0,
      candidates_inspected: 0,
      metric_filtered: 0,
      max_items: 20,
      max_candidates: 200,
      min_views: 500,
      min_likes: 10,
    },
    summary: {
      accepted: 0,
      candidates_inspected: 0,
      metric_filtered: 0,
      max_items: 20,
      max_candidates: 200,
      min_views: 500,
      min_likes: 10,
    },
  };
}

function emptyPlatformTrendIndex() {
  return {
    latest_date: "",
    generated_at: "",
    items: [],
  };
}

function emptyDitingDigestIndex() {
  return {
    generated_at: "",
    generated_at_label: "",
    source: "codew1028/dt",
    source_base_url: "https://codew1028.github.io/dt",
    detail_days: 0,
    latest: { ai: "", tg: "" },
    latest_date: "",
    counts: { ai: 0, tg: 0 },
    items: [],
  };
}

function buildDataMap() {
  const bundled = readDataBundle();
  const map = {
    ...bundled,
    "dashboard-data/latest.json": readJson("dashboard-data/latest.json"),
    "dashboard-data/daily/latest.json": readJson("dashboard-data/daily/latest.json"),
    "dashboard-data/daily/index.json": readJson("dashboard-data/daily/index.json"),
    "dashboard-data/competitor.json": readJson("dashboard-data/competitor.json"),
    "dashboard-data/source-status.json": readJson("dashboard-data/source-status.json"),
  };
  const dailyDir = path.join(publicDir, "dashboard-data", "daily");
  for (const file of fs.readdirSync(dailyDir)) {
    if (file.endsWith(".json") && file !== "latest.json" && file !== "index.json") {
      map[`dashboard-data/daily/${file}`] = JSON.parse(fs.readFileSync(path.join(dailyDir, file), "utf8"));
    }
  }
  const platformDir = path.join(publicDir, "dashboard-data", "platform-trends", "xiaohongshu");
  if (fs.existsSync(platformDir)) {
    for (const file of ["latest.json", "index.json"]) {
      const filePath = path.join(platformDir, file);
      if (fs.existsSync(filePath)) {
        map[`dashboard-data/platform-trends/xiaohongshu/${file}`] = JSON.parse(fs.readFileSync(filePath, "utf8"));
      }
    }
    const platformDailyDir = path.join(platformDir, "daily");
    if (fs.existsSync(platformDailyDir)) {
      for (const file of fs.readdirSync(platformDailyDir)) {
        if (file.endsWith(".json")) {
          map[`dashboard-data/platform-trends/xiaohongshu/daily/${file}`] = JSON.parse(fs.readFileSync(path.join(platformDailyDir, file), "utf8"));
        }
      }
    }
  }
  map["dashboard-data/platform-trends/xiaohongshu/latest.json"] ||= emptyPlatformTrendPayload();
  map["dashboard-data/platform-trends/xiaohongshu/index.json"] ||= emptyPlatformTrendIndex();
  const dtDir = path.join(publicDir, "dashboard-data", "dt-digests");
  if (fs.existsSync(dtDir)) {
    const indexPath = path.join(dtDir, "index.json");
    if (fs.existsSync(indexPath)) {
      map["dashboard-data/dt-digests/index.json"] = JSON.parse(fs.readFileSync(indexPath, "utf8"));
    }
    const dtDailyDir = path.join(dtDir, "daily");
    if (fs.existsSync(dtDailyDir)) {
      for (const kind of fs.readdirSync(dtDailyDir)) {
        const kindDir = path.join(dtDailyDir, kind);
        if (!fs.statSync(kindDir).isDirectory()) continue;
        for (const file of fs.readdirSync(kindDir)) {
          if (file.endsWith(".json")) {
            map[`dashboard-data/dt-digests/daily/${kind}/${file}`] = JSON.parse(fs.readFileSync(path.join(kindDir, file), "utf8"));
          }
        }
      }
    }
  }
  map["dashboard-data/dt-digests/index.json"] ||= emptyDitingDigestIndex();
  return map;
}

function shellHtml() {
  const css = readText("assets/styles.css");
  const js = readText("assets/app.js");
  const dataMap = JSON.stringify(buildDataMap()).replace(/</g, "\\u003c");
  return `
    <style>${css}</style>
    <div id="app" class="app-shell">
      <aside class="sidebar" aria-label="Main navigation">
        <div class="brand-block">
          <div class="brand-mark">BX</div>
          <div>
            <div class="brand-title">Brand X</div>
            <div class="brand-subtitle">Intelligence Radar</div>
          </div>
        </div>
        <nav class="nav-list" aria-label="产品导航">
          <div class="nav-group" data-nav-group="platform">
            <button class="nav-group-toggle" type="button" data-nav-toggle="platform" aria-expanded="true">
              <span class="nav-group-label">谛听-情报库</span>
              <span class="nav-chevron" aria-hidden="true"></span>
            </button>
            <div class="nav-children">
              <a href="#/platform/xiaohongshu" data-route="xiaohongshu"><span class="nav-item-dot" aria-hidden="true"></span><span>小红书</span></a>
              <a href="#/diting/ai-daily" data-route="aiDaily"><span class="nav-item-dot" aria-hidden="true"></span><span>AI日报</span></a>
              <a href="#/diting/tg-daily" data-route="tgDaily"><span class="nav-item-dot" aria-hidden="true"></span><span>TG日报</span></a>
            </div>
          </div>
          <div class="nav-group" data-nav-group="monitor">
            <button class="nav-group-toggle" type="button" data-nav-toggle="monitor" aria-expanded="true">
              <span class="nav-group-label">品牌-舆情监控</span>
              <span class="nav-chevron" aria-hidden="true"></span>
            </button>
            <div class="nav-children">
              <a href="#/" data-route="overview"><span class="nav-item-dot" aria-hidden="true"></span><span>舆情焦点</span></a>
              <a href="#/all" data-route="all"><span class="nav-item-dot" aria-hidden="true"></span><span>全部舆情</span></a>
              <a href="#/daily" data-route="daily"><span class="nav-item-dot" aria-hidden="true"></span><span>舆情日报</span></a>
              <a href="#/settings" data-route="settings"><span class="nav-item-dot" aria-hidden="true"></span><span>设置</span></a>
            </div>
          </div>
        </nav>
      </aside>
      <main class="main-panel">
        <header class="topbar">
          <div>
            <p class="eyebrow">BRAND X 舆情中心</p>
            <h1 id="page-title">舆情焦点</h1>
          </div>
          <div class="topbar-meta">
            <span id="generated-at">Loading</span>
            <span id="health-pill" class="status-pill neutral">Loading</span>
          </div>
        </header>
        <section id="content" class="content-area" aria-live="polite"></section>
      </main>
    </div>
    <script>
      const __dashboardData = ${dataMap};
      window.fetch = async function(input) {
        const raw = String(input);
        const key = raw.replace(/^\\.\\//, "");
        if (!__dashboardData[key]) {
          return new Response("{}", { status: 404 });
        }
        return new Response(JSON.stringify(__dashboardData[key]), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      };
    </script>
    <script>${js}</script>
  `;
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const executablePath = localBrowserExecutable();
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && !isIgnorableConsoleError(text)) errors.push(text);
  });

  await page.setContent(shellHtml(), { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".page-hero", { timeout: 5000 });
  await page.waitForSelector(".featured-date-group", { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "overview.png"), fullPage: true });

  await page.click('a[href="#/daily"]');
  await page.waitForSelector(".daily-masthead", { timeout: 5000 });
  await page.waitForSelector(".daily-history-item", { timeout: 5000 });
  await page.waitForSelector(".daily-section", { timeout: 5000 });
  await page.waitForSelector(".daily-story-card", { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "daily.png"), fullPage: true });

  await page.click('a[href="#/all"]');
  await page.waitForSelector(".all-feed", { timeout: 5000 });
  await page.waitForSelector('[data-all-source-filter="joybuy"]', { timeout: 5000 });
  await page.click('[data-all-source-filter="joybuy"]');
  await page.waitForSelector(".all-date-group", { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "all.png"), fullPage: true });

  await page.click('a[href="#/settings"]');
  await page.waitForSelector(".settings-layout", { timeout: 5000 });
  await page.waitForSelector(".settings-card", { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "settings.png"), fullPage: true });

  await page.click('a[href="#/platform/xiaohongshu"]');
  await page.waitForSelector(".platform-feed", { timeout: 5000 });
  await page.waitForSelector('[data-nav-group="platform"].contains-active', { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "xiaohongshu.png"), fullPage: true });

  await page.click('a[href="#/diting/ai-daily"]');
  await page.waitForSelector(".diting-digest-feed", { timeout: 5000 });
  await page.waitForSelector(".diting-card", { timeout: 5000 });
  await page.waitForSelector('[data-route="aiDaily"].active', { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "ai-daily.png"), fullPage: true });

  await page.click('a[href="#/diting/tg-daily"]');
  await page.waitForSelector(".diting-digest-feed", { timeout: 5000 });
  await page.waitForSelector(".diting-card", { timeout: 5000 });
  await page.waitForSelector('[data-route="tgDaily"].active', { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "tg-daily.png"), fullPage: true });

  await page.click('a[href="#/daily"]');
  await page.waitForSelector(".daily-story-card", { timeout: 5000 });
  const detailLink = await page.$('.daily-story-card a[href^="#/intel/"]');
  if (detailLink) {
    const detailHref = await detailLink.evaluate((node) => node.getAttribute("href"));
    await page.click(`.daily-story-card a[href="${detailHref}"]`);
    await page.waitForSelector(".read-detail", { timeout: 5000 });
    await page.waitForSelector(".related-source-chip", { timeout: 5000 });
    await page.click('[data-detail-lang="original"]');
    await page.waitForSelector(".score-contribution-list", { timeout: 5000 });
    await page.screenshot({ path: path.join(outDir, "detail.png"), fullPage: true });
  }

  await browser.close();
  if (errors.length) {
    console.error(errors.join("\\n"));
    process.exit(1);
  }
  console.log("Dashboard browser verification passed.");
  console.log(`Screenshots: ${path.relative(root, outDir)}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
