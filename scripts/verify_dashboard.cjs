const fs = require("fs");
const http = require("http");
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
  return /^Failed to load resource: the server responded with a status of (?:404|503)/i.test(String(text || ""));
}

function localBrowserExecutable() {
  return localBrowserCandidates.find((candidate) => fs.existsSync(candidate));
}

function startStaticServer() {
  const contentTypes = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
  };
  const server = http.createServer((request, response) => {
    const requestUrl = new URL(request.url || "/", "http://127.0.0.1");
    const relative = decodeURIComponent(requestUrl.pathname === "/" ? "index.html" : requestUrl.pathname.slice(1));
    const filePath = path.resolve(publicDir, relative);
    if (filePath !== publicDir && !filePath.startsWith(`${publicDir}${path.sep}`)) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      response.writeHead(404).end("Not found");
      return;
    }
    response.writeHead(200, {
      "content-type": contentTypes[path.extname(filePath).toLowerCase()] || "application/octet-stream",
      "cache-control": "no-store",
    });
    fs.createReadStream(filePath).pipe(response);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({ server, origin: `http://127.0.0.1:${address.port}` });
    });
  });
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  let server = null;
  let browser = null;
  try {
    const started = await startStaticServer();
    server = started.server;
    const origin = started.origin;
    const executablePath = localBrowserExecutable();
    browser = await chromium.launch(executablePath ? { executablePath } : {});
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    const requestedPaths = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => requestedPaths.push(new URL(request.url()).pathname));
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && !isIgnorableConsoleError(text)) errors.push(text);
  });

  let xiaohongshuIndexAttempts = 0;
  await page.route("**/dashboard-data/platform-trends/xiaohongshu/index.json", async (route) => {
    xiaohongshuIndexAttempts += 1;
    if (xiaohongshuIndexAttempts <= 2) {
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
      return;
    }
    await route.continue();
  });

  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".page-hero", { timeout: 5000 });
  await page.waitForSelector(".featured-date-group", { timeout: 5000 });
  if (xiaohongshuIndexAttempts !== 3) throw new Error(`Expected 3 Xiaohongshu index attempts, got ${xiaohongshuIndexAttempts}`);
  if (requestedPaths.some((value) => /dashboard-data\/(?:daily\/latest|latest|competitor|source-status)\.json$/.test(value))) {
    throw new Error("Default Xiaohongshu route loaded brand-monitoring data eagerly");
  }
  await page.screenshot({ path: path.join(outDir, "xiaohongshu-default.png"), fullPage: true });
  await page.unroute("**/dashboard-data/platform-trends/xiaohongshu/index.json");

  const contextButton = page.locator("[data-conversation-context]").first();
  if (!(await contextButton.count())) throw new Error("No Xiaohongshu conversation context found for lazy-load QA");
  let failContextLoads = true;
  let contextRequests = 0;
  await page.route("**/dashboard-data/lazy/conversations/*.json", async (route) => {
    contextRequests += 1;
    if (failContextLoads) {
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
      return;
    }
    await route.continue();
  });
  await contextButton.click();
  await page.waitForSelector("[data-drawer-retry]", { timeout: 5000 });
  if (contextRequests !== 3) throw new Error(`Expected 3 failed context attempts, got ${contextRequests}`);
  failContextLoads = false;
  await page.click("[data-drawer-retry]");
  await page.waitForSelector(".conversation-post", { timeout: 5000 });
  await page.click(".conversation-drawer-close");

  await page.click('a[href="#/overview"]');
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

  await page.click('a[href="#/diting/ai-daily"]');
  await page.waitForSelector(".diting-digest-feed", { timeout: 5000 });
  await page.waitForSelector(".diting-card", { timeout: 5000 });
  await page.waitForSelector('[data-route="aiDaily"].active', { timeout: 5000 });
  await page.screenshot({ path: path.join(outDir, "ai-daily.png"), fullPage: true });

  await page.click('a[href="#/diting/tg-daily"]');
  await page.waitForSelector(".diting-digest-feed", { timeout: 5000 });
  await page.waitForSelector('[data-route="tgDaily"].active', { timeout: 5000 });
  await page.waitForSelector("[data-diting-comments]", { timeout: 5000 });
  const commentButton = page.locator("[data-diting-comments]").first();
  const beforeCommentRequests = requestedPaths.filter((value) => value.includes("/dashboard-data/lazy/tg-replies/")).length;
  await commentButton.click();
  await page.waitForSelector(".diting-comment-item", { timeout: 5000 });
  const afterCommentRequests = requestedPaths.filter((value) => value.includes("/dashboard-data/lazy/tg-replies/")).length;
  if (afterCommentRequests <= beforeCommentRequests) throw new Error("TG comments were not loaded lazily from a separate payload");
  await page.click(".conversation-drawer-close");
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

    if (errors.length) throw new Error(errors.join("\\n"));
    console.log("Dashboard browser verification passed.");
    console.log(`Screenshots: ${path.relative(root, outDir)}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
