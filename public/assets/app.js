const state = {
  overview: null,
  daily: null,
  dailyIndex: null,
  dailyArchive: [],
  selectedDaily: null,
  competitor: null,
  sourceStatus: null,
  xiaohongshu: null,
  xiaohongshuIndex: null,
  xiaohongshuArchive: [],
  dtDigestIndex: null,
  dtDigests: {
    ai: [],
    tg: [],
  },
  dtDigestFilters: {
    ai: { date: "", section: "all", source: "all", query: "" },
    tg: { date: "", section: "all", source: "all", query: "" },
  },
  dtDateRailScroll: { ai: 0, tg: 0 },
  platformExpandedDates: new Set(),
  platformTagFilter: "",
  allBrandFilter: "all",
  allTypeFilter: "all",
  allSearchQuery: "",
  allExpandedDates: new Set(),
  featuredFilter: "all",
  featuredExpandedDates: new Set(),
  navCollapsedGroups: new Set(),
  routeScrollPositions: {},
  lastRouteKey: "",
  conversationContexts: new Map(),
  ditingCommentThreads: new Map(),
  prefetchedMediaUrls: new Set(),
};

const USE_X_EMBED_FOR_VIDEO = false;
const X_WIDGET_SCRIPT_URL = "https://platform.twitter.com/widgets.js";
const DEFAULT_TIMELINE_EXPANDED_DAYS = 3;
const BACK_TO_TOP_THRESHOLD = 520;
const TG_MEDIA_PREFETCH_MAX_IMAGES = 32;
const TG_MEDIA_PREFETCH_MAX_VIDEOS = 2;
const TG_MEDIA_PREFETCH_MAX_VIDEO_BYTES = 30 * 1024 * 1024;
const TG_COMMENT_BLOCK_PATTERNS = [
  /打飞机|撸管|约炮|找炮友|炮友|裸聊|色情网|成人视频|情色|援交|招嫖|嫖娼|外围/i,
  /加(?:微信|薇|v|qq)|私聊.{0,12}(?:资源|福利|群)|点击.{0,10}(?:领取|下载)|博彩|网赌|现金网|返佣/i,
  /傻逼|脑残|滚蛋|去死|死全家/i,
  /买枪|卖枪|毒品|冰毒|K粉|代办身份证|洗钱/i,
];
const TG_COMMENT_LOW_SIGNAL_RE = /^(哈+|哈哈哈+|笑死|666+|顶|蹲|mark|收藏|学习了|\+1|牛+|牛逼|nb|ok|好)$/i;

const routeTitles = {
  overview: "舆情焦点",
  all: "全部舆情",
  daily: "舆情日报",
  settings: "设置",
  xiaohongshu: "小红书",
  aiDaily: "AI日报",
  tgDaily: "TG日报",
};

const DT_DIGEST_KIND_CONFIG = {
  ai: {
    routeName: "aiDaily",
    slug: "ai-daily",
    title: "AI日报",
    label: "AI 日报",
    eyebrow: "谛听-情报库",
    sourceLabel: "来源",
    emptyText: "还没有同步到 AI 日报内容。",
  },
  tg: {
    routeName: "tgDaily",
    slug: "tg-daily",
    title: "TG日报",
    label: "TG 日报",
    eyebrow: "谛听-情报库",
    sourceLabel: "频道",
    emptyText: "还没有同步到 TG 日报内容。",
  },
};

async function loadJson(path) {
  const key = path.replace(/^\.\//, "");
  if (window.__DASHBOARD_DATA__) {
    if (window.__DASHBOARD_DATA__[key]) return normalizeRuntimePayload(window.__DASHBOARD_DATA__[key]);
    if (window.__DASHBOARD_DATA__.clusters && window.__DASHBOARD_DATA__.clusters[key]) {
      return normalizeRuntimePayload(window.__DASHBOARD_DATA__.clusters[key]);
    }
  }
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return normalizeRuntimePayload(await response.json());
}

async function loadJsonOptional(path, fallback) {
  try {
    return await loadJson(path);
  } catch (error) {
    return fallback;
  }
}

function normalizeRuntimePayload(value) {
  if (Array.isArray(value)) {
    value.forEach(normalizeRuntimePayload);
    return value;
  }
  if (!value || typeof value !== "object") return value;

  if (value.brand === "primary") value.brand = "joybuy";
  if (value.brand === "competitor") value.brand = "temu";

  if (value.metrics) {
    aliasNumber(value.metrics, "joybuy_volume", "primary_volume");
    aliasNumber(value.metrics, "joybuy_candidate_volume", "primary_candidate_volume");
    aliasNumber(value.metrics, "temu_volume", "competitor_volume");
  }
  if (value.dashboard_metrics) {
    aliasNumber(value.dashboard_metrics, "joybuy_volume", "primary_volume");
    aliasNumber(value.dashboard_metrics, "joybuy_candidate_volume", "primary_candidate_volume");
    aliasNumber(value.dashboard_metrics, "temu_volume", "competitor_volume");
  }
  if (value.brand_breakdown) {
    aliasNumber(value.brand_breakdown, "joybuy_candidates", "primary_candidates");
    aliasNumber(value.brand_breakdown, "joybuy_effective", "primary_effective");
    aliasNumber(value.brand_breakdown, "temu_candidates", "competitor_candidates");
    aliasNumber(value.brand_breakdown, "temu_effective", "competitor_effective");
  }
  aliasNumber(value, "joybuy_effective", "primary_effective");
  aliasNumber(value, "temu_effective", "competitor_effective");
  aliasNumber(value, "joybuy_clusters", "primary_signals");

  Object.values(value).forEach(normalizeRuntimePayload);
  return value;
}

function aliasNumber(target, oldKey, newKey) {
  if (target[oldKey] == null && target[newKey] != null) target[oldKey] = target[newKey];
}

async function init() {
  state.overview = await loadJson("./dashboard-data/latest.json");
  state.daily = await loadJson("./dashboard-data/daily/latest.json");
  state.dailyIndex = await loadJson("./dashboard-data/daily/index.json");
  state.dailyArchive = await loadDailyArchive();
  if (!state.dailyArchive.length) state.dailyArchive = [state.daily];
  state.featuredExpandedDates = new Set(state.dailyArchive.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS).map((daily) => daily.date).filter(Boolean));
  state.allExpandedDates = new Set(state.dailyArchive.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS).map((daily) => daily.date).filter(Boolean));
  state.selectedDaily = state.daily;
  state.competitor = await loadJson("./dashboard-data/competitor.json");
  state.sourceStatus = await loadJson("./dashboard-data/source-status.json");
  state.xiaohongshu = await loadJsonOptional("./dashboard-data/platform-trends/xiaohongshu/latest.json", emptyPlatformTrendPayload());
  state.xiaohongshuIndex = await loadJsonOptional("./dashboard-data/platform-trends/xiaohongshu/index.json", emptyPlatformTrendIndex());
  state.xiaohongshuArchive = await loadPlatformTrendArchive("xiaohongshu");
  if (!state.xiaohongshuArchive.length && state.xiaohongshu?.date) state.xiaohongshuArchive = [state.xiaohongshu];
  state.platformExpandedDates = new Set(state.xiaohongshuArchive.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS).map((daily) => daily.date).filter(Boolean));
  state.dtDigestIndex = await loadJsonOptional("./dashboard-data/dt-digests/index.json", emptyDitingDigestIndex());
  state.dtDigests.ai = await loadInitialDitingDigest("ai");
  state.dtDigests.tg = await loadInitialDitingDigest("tg");
  Object.keys(DT_DIGEST_KIND_CONFIG).forEach((kind) => {
    if (!state.dtDigestFilters[kind].date) {
      state.dtDigestFilters[kind].date = state.dtDigests[kind]?.[0]?.date || state.dtDigestIndex?.latest?.[kind] || "";
    }
  });
  bindNavigation();
  setupBackToTop();
  window.addEventListener("hashchange", render);
  render();
}

async function loadDailyArchive() {
  const items = state.dailyIndex?.items || [];
  const records = await Promise.all(
    items.map(async (item) => {
      try {
        return await loadJson(`./dashboard-data/daily/${item.date}.json`);
      } catch (error) {
        return null;
      }
    })
  );
  return records.filter(Boolean).sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

async function loadPlatformTrendArchive(platformKey) {
  const items = state.xiaohongshuIndex?.items || [];
  const records = await Promise.all(
    items.map(async (item) => {
      try {
        return await loadJson(`./dashboard-data/platform-trends/${platformKey}/daily/${item.date}.json`);
      } catch (error) {
        return null;
      }
    })
  );
  return records.filter(Boolean).sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

async function loadInitialDitingDigest(kind) {
  const items = (state.dtDigestIndex?.items || [])
    .filter((item) => item.kind === kind && item.detail_available)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const latest = items[0];
  if (!latest) return [];
  const record = await loadDitingDigestDetail(latest);
  return record ? [record] : [];
}

async function loadDitingDigestDetail(entry) {
  if (!entry) return null;
  const detailPath = entry.detail_path || `dashboard-data/dt-digests/daily/${entry.kind}/${entry.date}.json`;
  try {
    return await loadJson(`./${detailPath}`);
  } catch (error) {
    return null;
  }
}

async function ensureDitingDigestDetail(kind, date) {
  const details = state.dtDigests[kind] || [];
  if (details.some((daily) => daily.date === date)) return;
  const entry = ditingDigestEntries(kind).find((item) => item.date === date);
  const detail = await loadDitingDigestDetail(entry);
  if (!detail) return;
  state.dtDigests[kind] = [...details, detail].sort((a, b) => String(b.date).localeCompare(String(a.date)));
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

function route() {
  const hash = window.location.hash || "#/";
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "platform" && parts[1] === "xiaohongshu") return { name: "xiaohongshu" };
  if (parts[0] === "diting" && parts[1] === "ai-daily") return { name: "aiDaily" };
  if (parts[0] === "diting" && parts[1] === "tg-daily") return { name: "tgDaily" };
  if (parts[0] === "intel") return { name: "overview" };
  if (parts[0] === "fermentation") return { name: "overview" };
  if (parts[0] === "source-status") return { name: "settings" };
  if (parts[0] === "competitor") return { name: "daily" };
  return { name: parts[0] || "overview" };
}

function render() {
  const current = route();
  const routeKey = current.name;
  const previousRouteKey = state.lastRouteKey;
  const content = document.getElementById("content");
  if (previousRouteKey && previousRouteKey !== routeKey && content) {
    state.routeScrollPositions[previousRouteKey] = content.scrollTop || 0;
  }
  const shouldRestoreScroll = previousRouteKey && previousRouteKey !== routeKey;
  document.getElementById("page-title").textContent = routeTitles[current.name] || "舆情焦点";
  document.getElementById("generated-at").textContent = generatedAtLabelForRoute(current.name);
  const health = document.getElementById("health-pill");
  const sampleMode = isSampleMode();
  health.textContent = sampleMode ? "Sample data" : state.overview.health === "normal" ? "Data healthy" : state.overview.health;
  health.className = `status-pill ${sampleMode ? "sample" : state.overview.health}`;
  document.querySelectorAll(".nav-list a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === current.name);
  });
  syncNavigationState(current.name);

  closeConversationDrawer();
  state.conversationContexts = new Map();
  state.ditingCommentThreads = new Map();
  if (current.name === "all") content.innerHTML = allIntelligencePage();
  else if (current.name === "daily") content.innerHTML = dailyPage();
  else if (current.name === "settings") content.innerHTML = settingsPage();
  else if (current.name === "xiaohongshu") content.innerHTML = xiaohongshuPage();
  else if (current.name === "aiDaily") content.innerHTML = ditingDigestPage("ai");
  else if (current.name === "tgDaily") content.innerHTML = ditingDigestPage("tg");
  else content.innerHTML = overviewPage();
  if (shouldRestoreScroll) restoreMainScroll(content, routeKey);
  state.lastRouteKey = routeKey;
  bindPageEvents();
  restoreDitingDateRailScroll();
  updateBackToTopVisibility();
  hydrateXVideoEmbeds();
}

function generatedAtLabelForRoute(routeName) {
  if (routeName === "xiaohongshu") return state.xiaohongshu?.generated_at_label || state.overview.generated_at_label;
  if (routeName === "aiDaily" || routeName === "tgDaily") {
    return state.dtDigestIndex?.generated_at_label || state.overview.generated_at_label;
  }
  return state.overview.generated_at_label;
}

function bindNavigation() {
  document.querySelectorAll("[data-nav-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.dataset.navToggle;
      if (!group) return;
      if (state.navCollapsedGroups.has(group)) state.navCollapsedGroups.delete(group);
      else state.navCollapsedGroups.add(group);
      syncNavigationState(route().name);
    });
  });
}

function syncNavigationState(currentRoute) {
  document.querySelectorAll("[data-nav-group]").forEach((group) => {
    const groupName = group.dataset.navGroup || "";
    const hasActiveRoute = [...group.querySelectorAll("[data-route]")].some((link) => link.dataset.route === currentRoute);
    const collapsed = state.navCollapsedGroups.has(groupName);
    group.classList.toggle("contains-active", hasActiveRoute);
    group.classList.toggle("is-collapsed", collapsed);
    const toggle = group.querySelector("[data-nav-toggle]");
    if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
  });
}

function resetMainScroll(content) {
  if (content) content.scrollTop = 0;
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  updateBackToTopVisibility();
}

function restoreMainScroll(content, routeKey) {
  if (!content) return;
  const target = Number(state.routeScrollPositions[routeKey] || 0);
  content.scrollTo({ top: Math.max(0, target), left: 0, behavior: "auto" });
  requestAnimationFrame(() => {
    content.scrollTo({ top: Math.max(0, target), left: 0, behavior: "auto" });
    updateBackToTopVisibility();
  });
}

function setupBackToTop() {
  const content = document.getElementById("content");
  const button = document.getElementById("back-to-top");
  if (!content || !button) return;
  content.addEventListener("scroll", () => {
    state.routeScrollPositions[route().name] = content.scrollTop || 0;
    updateBackToTopVisibility();
  }, { passive: true });
  button.addEventListener("click", () => {
    content.scrollTo({ top: 0, left: 0, behavior: "smooth" });
  });
}

function updateBackToTopVisibility() {
  const content = document.getElementById("content");
  const button = document.getElementById("back-to-top");
  if (!content || !button) return;
  const current = route();
  const visible =
    current.name !== "settings" &&
    !document.body.classList.contains("conversation-drawer-open") &&
    content.scrollTop > BACK_TO_TOP_THRESHOLD;
  button.classList.toggle("visible", visible);
}

function overviewPage() {
  const archive = state.dailyArchive.length ? state.dailyArchive : [state.daily];
  const latest = archive[0] || state.daily;
  const latestMetrics = latest.metrics || state.overview.metrics;
  const allFeaturedCount = archive.reduce((sum, daily) => sum + featuredItemsForDaily(daily, false).length, 0);
  const latestFeaturedItems = featuredItemsForDaily(latest, false);
  const visibleGroups = featuredVisibleGroups();
  const openDates = featuredOpenDates(visibleGroups);
  return `
    ${pageHero({
      eyebrow: "舆情雷达",
      title: "舆情焦点",
      subtitle: `${formatDateLong(latest.date)} · 按传播风险、品牌相关度、业务价值筛出的优先关注舆情`,
      stats: [
        [latestFeaturedItems.length, "今日焦点"],
        [allFeaturedCount, "归档焦点"],
        [topIps(latest), "最高 IPS"],
      ],
    })}
    ${sampleDataNotice(latest)}
    <div class="featured-status-row">
      <span>主品牌焦点 ${escapeHtml(String(latestFeaturedItems.filter((item) => item.brand !== "temu").length))}</span>
      <span>竞品焦点 ${escapeHtml(String(latestFeaturedItems.filter((item) => item.brand === "temu").length))}</span>
      <span>主品牌有效 ${escapeHtml(String(latestMetrics.joybuy_volume || 0))}</span>
      <span>竞品基线 ${escapeHtml(String(latestMetrics.temu_volume || 0))}</span>
      <span>${escapeHtml(latest.window_label || "Past 24 hours")}</span>
    </div>
    ${featuredFilterBar()}
    <section class="featured-feed">
      ${visibleGroups.length ? visibleGroups.map((group) => featuredDateGroup(group, openDates)).join("") : featuredEmptyState()}
    </section>
  `;
}

function pageHero({ eyebrow, subtitle, stats }) {
  return `
    <section class="page-hero">
      <div>
        <p class="eyebrow">${escapeHtml(eyebrow)}</p>
        <p class="muted">${escapeHtml(subtitle)}</p>
      </div>
      <div class="page-hero-stats">
        ${stats.map(([value, label]) => `<span><strong>${escapeHtml(String(value))}</strong><em>${escapeHtml(label)}</em></span>`).join("")}
      </div>
    </section>
  `;
}

function featuredFilterBar() {
  const filters = [
    ["all", "全部"],
    ["risk", "风险"],
    ["opportunity", "机会"],
    ["competitor", "竞品"],
    ["watch", "高潜传播"],
  ];
  return `
    <section class="filter-panel compact">
      <div>
        <div class="toolbar-label">视图</div>
        <div class="filter-chip-row">
          ${filters
            .map(
              ([value, label]) => `
                <button class="filter-chip ${state.featuredFilter === value ? "active" : ""}" type="button" data-featured-filter="${value}">
                  ${escapeHtml(label)} <span>${escapeHtml(String(featuredFilterCount(value)))}</span>
                </button>
              `
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function featuredFilterCount(filter) {
  const archive = state.dailyArchive.length ? state.dailyArchive : [state.daily];
  return archive.reduce((sum, daily) => {
    return sum + featuredItemsForDaily(daily, false).filter((item) => itemMatchesFeaturedFilter(item, filter)).length;
  }, 0);
}

function featuredVisibleGroups() {
  const archive = state.dailyArchive.length ? state.dailyArchive : [state.daily];
  const groups = archive.map((daily) => ({
    daily,
    items: featuredItemsForDaily(daily, true),
  }));
  if (state.featuredFilter === "all") return groups;
  return groups.filter((group) => group.items.length);
}

function featuredOpenDates(groups) {
  const dates = groups.map((group) => group.daily.date).filter(Boolean);
  const currentOpen = dates.filter((date) => state.featuredExpandedDates.has(date));
  if (currentOpen.length) return new Set(currentOpen);
  return new Set(dates.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS));
}

function syncFeaturedExpandedDatesForFilter() {
  const groups = featuredVisibleGroups();
  const dates = groups.map((group) => group.daily.date).filter(Boolean);
  state.featuredExpandedDates = new Set(dates.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS));
}

function featuredEmptyState() {
  const label = featuredFilterLabel(state.featuredFilter);
  return `
    <div class="featured-empty-state">
      <strong>${escapeHtml(label)}暂无焦点舆情</strong>
      <p>${escapeHtml(featuredEmptyCopy(state.featuredFilter))}</p>
      <button class="text-button primary" type="button" data-featured-filter="all">查看全部焦点</button>
    </div>
  `;
}

function featuredEmptyCopy(filter) {
  if (filter === "risk") return "当前归档中没有达到风险筛选条件的焦点内容，可以切回全部视图查看完整舆情。";
  if (filter === "opportunity") return "当前归档中没有明显机会信号，后续若出现正向传播或可借势内容会自动进入这里。";
  if (filter === "watch") return "当前没有达到高潜传播阈值的舆情，说明暂未识别到明显二次扩散风险。";
  if (filter === "competitor") return "当前没有竞品焦点内容，可以继续关注后续日报归档。";
  return "当前暂无焦点舆情，后续日报生成后会自动更新。";
}

function featuredFilterLabel(value) {
  const labels = {
    all: "全部",
    risk: "风险",
    opportunity: "机会",
    competitor: "竞品",
    watch: "高潜传播",
  };
  return labels[value] || "当前筛选";
}

function featuredDateGroup(group, openDates = state.featuredExpandedDates) {
  const daily = group.daily;
  const items = group.items;
  const open = openDates.has(daily.date);
  return `
    <article class="featured-date-group">
      ${timelineDateButton(daily.date, `${items.length} 条焦点`, open, "featured")}
      ${open ? featuredTimeline(daily, items) : ""}
    </article>
  `;
}

function featuredTimeline(daily, items) {
  if (!items.length) {
    return `<div class="featured-empty">${escapeHtml(daily.summary_only ? "该日为摘要级归档，暂无原帖级焦点卡片。" : "该日暂无达到焦点阈值的舆情。")}</div>`;
  }
  return `
    <div class="publish-timeline featured-timeline">
      ${items.sort(compareEvents).map(featuredTimelineCard).join("")}
    </div>
  `;
}

function featuredTimelineCard(item) {
  const translation = chineseSignalText(item);
  const media = item.media || [];
  const languageId = languageSwitchId(item, "featured");
  return `
    <div class="publish-item featured-item">
      <div class="publish-time">${escapeHtml(item.timeLabel || formatEventTime(item.time))}</div>
      <div class="publish-line"><span></span></div>
      <article class="opinion-card featured-card ${scoreClass(item)}">
        <div class="featured-card-top">
          <div class="source-identity">
            ${avatarNode(item)}
            <div>
              <div class="source-line">
                ${authorNameNode(item, item.author_name || item.source_name || "Unknown source")}
                ${item.author_handle ? `<em>@${escapeHtml(item.author_handle)}</em>` : ""}
                ${sourceBadge(item.brand === "temu" ? "竞品" : "焦点", item.brand === "temu" ? "competitor" : "focus")}
              </div>
              <div class="source-subline">${escapeHtml(sourceTypeLabel(item))}${item.author_followers ? ` · ${escapeHtml(formatCompactNumber(item.author_followers))} followers` : ""}</div>
            </div>
          </div>
          <div class="featured-score">
            <span>${escapeHtml(String(item.score_value ?? "n/a"))}</span>
            <em>${escapeHtml(item.score_label || "IPS")}</em>
          </div>
        </div>
        <section class="x-signal-block">
          <div class="post-language-toolbar">${languageToggleNode(item, languageId)}</div>
          ${postLanguageTextNode(item, translation, "featured-translation", languageId)}
          ${contextRelationNode(item)}
          ${mediaGridNode(media, item)}
          <div class="metric-inline card-metrics">
            ${metricInline("赞", item.post_metrics?.likes ?? item.metrics?.total_likes)}
            ${metricInline("评", item.post_metrics?.replies ?? item.metrics?.total_replies)}
            ${metricInline("转", item.post_metrics?.reposts ?? item.metrics?.total_reposts)}
            ${metricInline("引", item.post_metrics?.quotes ?? item.metrics?.total_quotes)}
            ${metricInline("浏览", item.post_metrics?.views ?? item.metrics?.total_views)}
          </div>
          <div class="tag-row">${(item.tags || []).slice(0, 8).map((tag) => `<span class="plain-tag">#${escapeHtml(tag)}</span>`).join("")}</div>
          ${reasonLine(item)}
        </section>
        <div class="featured-card-bottom">
          ${cardFootnote(item.brand === "temu" ? "竞品基线信号" : "主品牌相关舆情", item)}
          <div class="button-row">
            ${cardExternalAction(item.external_href, item)}
          </div>
        </div>
      </article>
    </div>
  `;
}

function xiaohongshuPage() {
  const archive = state.xiaohongshuArchive.length ? state.xiaohongshuArchive : [];
  const latest = archive[0] || state.xiaohongshu || emptyPlatformTrendPayload();
  const allItems = archive.flatMap((daily) => daily.items || []);
  const latestItems = latest.items || [];
  const summary = latest.summary || {};
  const tagStats = platformTagStats(archive);
  const filteredArchive = platformFilteredArchive(archive);
  return `
    ${pageHero({
      eyebrow: "谛听-情报库",
      title: "小红书",
      subtitle: `${latest.date ? formatDateLong(latest.date) : "等待首次采集"} · X 上关于小红书养号、起号、流量和变现的方法论内容`,
      stats: [
        [latestItems.length, "今日收录"],
        [allItems.length, "归档内容"],
        [summary.candidates_inspected || 0, "候选检查"],
      ],
    })}
    ${platformTagFilterBar(tagStats, allItems.length)}
    ${platformWarnings(latest)}
    <section class="featured-feed platform-feed">
      ${filteredArchive.length ? filteredArchive.map(platformDateGroup).join("") : empty("没有匹配当前标签的收录内容。")}
    </section>
  `;
}

function platformFilteredArchive(archive) {
  const activeTag = String(state.platformTagFilter || "").trim();
  if (!activeTag) return archive;
  return archive
    .map((daily) => ({
      ...daily,
      items: (daily.items || []).filter((item) => platformItemHasTag(item, activeTag)),
    }))
    .filter((daily) => (daily.items || []).length);
}

function platformTagStats(archive) {
  const counts = new Map();
  archive.forEach((daily) => {
    (daily.items || []).forEach((item) => {
      new Set(platformItemTags(item)).forEach((tag) => {
        counts.set(tag, (counts.get(tag) || 0) + 1);
      });
    });
  });
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "zh-Hans-CN"));
}

function platformItemTags(item) {
  return (item.tags || []).map((tag) => String(tag || "").trim()).filter(Boolean);
}

function platformItemHasTag(item, tag) {
  return platformItemTags(item).includes(tag);
}

function platformTagFilterBar(tagStats, total) {
  if (!tagStats.length) return "";
  const activeTag = String(state.platformTagFilter || "");
  const buttons = [
    `<button type="button" class="platform-tag-filter${activeTag ? "" : " active"}" data-platform-tag-filter="">
      <span>全部</span><em>${escapeHtml(String(total))}</em>
    </button>`,
    ...tagStats.map((tag) => `
      <button type="button" class="platform-tag-filter${activeTag === tag.label ? " active" : ""}" data-platform-tag-filter="${escapeHtml(tag.label)}">
        <span>#${escapeHtml(tag.label)}</span><em>${escapeHtml(String(tag.count))}</em>
      </button>
    `),
  ];
  return `
    <section class="platform-tag-filter-panel" aria-label="小红书内容标签筛选">
      <div class="platform-filter-heading">标签筛选</div>
      <div class="platform-tag-filter-row">${buttons.join("")}</div>
    </section>
  `;
}

function syncPlatformExpandedDatesForFilter() {
  const activeTag = String(state.platformTagFilter || "").trim();
  if (!activeTag) {
    state.platformExpandedDates = new Set(state.xiaohongshuArchive.slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS).map((daily) => daily.date).filter(Boolean));
    return;
  }
  state.platformExpandedDates = new Set(
    state.xiaohongshuArchive
      .filter((daily) => (daily.items || []).some((item) => platformItemHasTag(item, activeTag)))
      .slice(0, DEFAULT_TIMELINE_EXPANDED_DAYS)
      .map((daily) => daily.date)
      .filter(Boolean)
  );
}

function platformWarnings(daily) {
  const warnings = daily?.collection_status?.warnings || [];
  if (!warnings.length) return "";
  return `
    <section class="sample-data-notice">
      <strong>采集提示</strong>
      <span>${escapeHtml(warnings.join("；"))}</span>
    </section>
  `;
}

function platformDateGroup(daily) {
  const open = state.platformExpandedDates.has(daily.date);
  const items = [...(daily.items || [])].sort(comparePlatformItems);
  return `
    <article class="featured-date-group">
      ${timelineDateButton(daily.date, `${items.length} 条黄金内容`, open, "platform")}
      ${open ? platformTimeline(daily, items) : ""}
    </article>
  `;
}

function platformTimeline(daily, items) {
  if (!items.length) return `<div class="featured-empty">该日暂无符合收录条件的小红书黄金内容。</div>`;
  return `
    <div class="publish-timeline all-timeline">
      ${items.map(platformTimelineCard).join("")}
    </div>
  `;
}

function platformTimelineCard(item) {
  const body = firstSourceText(item.translation_zh, item.original_text, item.text, item.summary_zh);
  const followerLine = item.author_followers ? `${escapeHtml(formatCompactNumber(item.author_followers))} followers` : "";
  return `
    <div class="publish-item all-feed-item">
      <div class="publish-time">${escapeHtml(formatEventTime(item.created_at || item.time))}</div>
      <div class="publish-line"><span></span></div>
      <article class="opinion-card all-card ${scoreClass(item)}">
        <div class="all-card-top">
          <div class="source-identity">
            ${avatarNode(item)}
            <div>
              <div class="source-line">
                ${authorNameNode(item, item.author_name || item.source_name || "X Source")}
                ${item.author_handle ? `<em>@${escapeHtml(item.author_handle)}</em>` : ""}
              </div>
              ${followerLine ? `<div class="source-subline">${followerLine}</div>` : ""}
            </div>
          </div>
          <div class="all-score" aria-label="黄金内容评分 ${escapeHtml(String(item.quality_score ?? item.score_value ?? "n/a"))}">
            <span>${escapeHtml(String(item.quality_score ?? item.score_value ?? "n/a"))}</span>
            <em>GQS</em>
          </div>
        </div>
        <div class="all-card-body">
          ${postTextWithInlineLanguageToggle(item, body, "all-card-text", "platform")}
          ${contextRelationNode(item)}
          ${mediaGridNode(item.media, item)}
          <div class="metric-inline card-metrics">
            ${metricInline("赞", item.post_metrics?.likes ?? item.metrics?.likes)}
            ${metricInline("评", item.post_metrics?.replies ?? item.metrics?.replies)}
            ${metricInline("转", item.post_metrics?.reposts ?? item.metrics?.reposts)}
            ${metricInline("引", item.post_metrics?.quotes ?? item.metrics?.quotes)}
            ${metricInline("收藏", item.post_metrics?.bookmarks ?? item.metrics?.bookmarks)}
            ${metricInline("浏览", item.post_metrics?.views ?? item.metrics?.views)}
          </div>
        </div>
        <div class="tag-row">${(item.tags || []).slice(0, 8).map((tag) => `<span class="plain-tag">#${escapeHtml(tag)}</span>`).join("")}</div>
        <div class="all-card-bottom">
          <div class="button-row">
            ${cardExternalAction(item.external_href || item.url, item)}
          </div>
        </div>
      </article>
    </div>
  `;
}

function ditingDigestPage(kind) {
  const config = DT_DIGEST_KIND_CONFIG[kind];
  const entries = ditingDigestEntries(kind);
  const loadedDetails = state.dtDigests[kind] || [];
  const filters = state.dtDigestFilters[kind] || { date: "", section: "all", source: "all", query: "" };
  const selectedEntry = entries.find((daily) => daily.date === filters.date) || entries[0] || null;
  const selected = loadedDetails.find((daily) => daily.date === filters.date)
    || loadedDetails.find((daily) => selectedEntry && daily.date === selectedEntry.date)
    || emptyDitingDigestPayload(kind, selectedEntry);
  if (!filters.date && selected.date) filters.date = selected.date;
  const allItems = flattenDitingDigestItems(selected);
  const filteredSections = ditingFilteredSections(selected, config, filters);
  const filteredCount = filteredSections.reduce((sum, section) => sum + section.items.length, 0);
  const sectionOptions = ditingSectionOptions(selected);
  const sourceOptions = ditingSourceOptions(allItems, config);
  const latestDate = state.dtDigestIndex?.latest?.[kind] || selected.date;
  const todayDate = dashboardTodayDate();
  const todayEntry = entries.find((entry) => entry.date === todayDate);
  const structuralFilters = kind !== "tg";
  const secondaryStat = kind === "tg" ? sourceOptions.length : selected.section_count || sectionOptions.length;
  return `
    ${pageHero({
      eyebrow: config.eyebrow,
      title: config.title,
      subtitle: `${selected.date ? formatDateLong(selected.date) : "等待首次同步"} · ${config.label}归档`,
      stats: [
        [selected.item_count || allItems.length, "当日条目"],
        [secondaryStat, kind === "ai" ? "板块" : "频道"],
        [entries.length, "可读日期"],
        [latestDate || "--", "最新日期"],
      ],
    })}
    <section class="diting-toolbar" aria-label="${escapeHtml(config.title)}筛选">
      <div class="diting-toolbar-head">
        <div>
          <strong>${escapeHtml(selected.title || config.label)}</strong>
          <span>${escapeHtml(selected.hero_date || `${selected.date || "未同步"} · ${allItems.length} 条内容`)}</span>
        </div>
        <button
          class="text-button primary${todayEntry ? "" : " disabled"}"
          type="button"
          data-dt-today="${escapeHtml(kind)}"
          data-dt-today-date="${escapeHtml(todayDate)}"
          ${todayEntry ? "" : "disabled"}
          title="${todayEntry ? "切换到系统当前日期的站内日报" : "今日日报尚未同步"}"
        >查看今日日报</button>
      </div>
      ${ditingDateRail(kind, entries, selected.date, loadedDetails)}
      <div class="diting-filter-row${structuralFilters ? "" : " search-only"}">
        ${structuralFilters ? `
          <label>
            <span>板块</span>
            <select data-dt-section-filter="${escapeHtml(kind)}">
              <option value="all"${filters.section === "all" ? " selected" : ""}>全部板块</option>
              ${sectionOptions.map((section) => `<option value="${escapeHtml(section)}"${filters.section === section ? " selected" : ""}>${escapeHtml(section)}</option>`).join("")}
            </select>
          </label>
          <label>
            <span>${escapeHtml(config.sourceLabel)}</span>
            <select data-dt-source-filter="${escapeHtml(kind)}">
              <option value="all"${filters.source === "all" ? " selected" : ""}>全部${escapeHtml(config.sourceLabel)}</option>
              ${sourceOptions.map((source) => `<option value="${escapeHtml(source)}"${filters.source === source ? " selected" : ""}>${escapeHtml(source)}</option>`).join("")}
            </select>
          </label>
        ` : ""}
        <form class="diting-search-form" data-dt-search-form="${escapeHtml(kind)}">
          <label>
            <span>搜索</span>
            <input type="search" value="${escapeHtml(filters.query)}" placeholder="搜标题、正文、来源…" data-dt-search-input="${escapeHtml(kind)}" />
          </label>
          <button class="text-button" type="submit">搜索</button>
          ${(filters.section !== "all" || filters.source !== "all" || filters.query)
            ? `<button class="text-button" type="button" data-dt-clear-filter="${escapeHtml(kind)}">清空</button>`
            : ""}
        </form>
      </div>
      <div class="diting-result-line">
        <span>${escapeHtml(String(filteredCount))} / ${escapeHtml(String(allItems.length))} 条</span>
        <span>${escapeHtml(state.dtDigestIndex?.generated_at_label || "")}</span>
      </div>
    </section>
    <section class="diting-digest-feed">
      ${filteredSections.length ? filteredSections.map((section) => ditingSectionBlock(section, config)).join("") : empty(config.emptyText)}
    </section>
  `;
}

function emptyDitingDigestPayload(kind, entry = null) {
  return {
    kind,
    kind_label: DT_DIGEST_KIND_CONFIG[kind]?.label || "日报",
    date: entry?.date || "",
    title: DT_DIGEST_KIND_CONFIG[kind]?.label || "日报",
    hero_date: entry?.date ? `${entry.date} · ${entry.item_count || 0} 条内容` : "",
    source_url: entry?.source_url || "",
    item_count: entry?.item_count || 0,
    section_count: entry?.section_count || 0,
    sections: [],
  };
}

function ditingDigestEntries(kind) {
  return (state.dtDigestIndex?.items || [])
    .filter((item) => item.kind === kind && item.detail_available)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

function flattenDitingDigestItems(digest) {
  return (digest.sections || []).flatMap((section) =>
    (section.items || []).map((item) => ({
      ...item,
      section_title: section.title || "日报内容",
    }))
  );
}

function ditingFilteredSections(digest, config, filters) {
  return (digest.sections || [])
    .map((section) => {
      const sectionTitle = section.title || "日报内容";
      const items = (section.items || [])
        .map((item) => ({ ...item, section_title: sectionTitle }))
        .filter((item) => ditingItemMatchesFilters(item, config, filters));
      return { ...section, title: sectionTitle, items };
    })
    .filter((section) => section.items.length);
}

function ditingItemMatchesFilters(item, config, filters) {
  const section = item.section_title || "";
  const source = ditingItemSource(item, config);
  const query = String(filters.query || "").trim().toLowerCase();
  if (filters.section !== "all" && section !== filters.section) return false;
  if (filters.source !== "all" && source !== filters.source) return false;
  if (!query) return true;
  const haystack = [
    item.title,
    item.summary,
    item.source,
    item.channel,
    item.channel_name,
    item.time,
    section,
    ...(item.links || []).map((link) => link.label || link.href || ""),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function ditingSectionOptions(digest) {
  return [...new Set((digest.sections || []).map((section) => String(section.title || "日报内容").trim()).filter(Boolean))];
}

function ditingSourceOptions(items, config) {
  return [...new Set(items.map((item) => ditingItemSource(item, config)).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function ditingDateRail(kind, entries, selectedDate, loadedDetails = []) {
  if (!entries.length) return "";
  return `
    <div class="diting-date-rail" data-dt-date-rail="${escapeHtml(kind)}" aria-label="选择日报日期">
      ${entries.map((entry) => {
        const detail = loadedDetails.find((daily) => daily.date === entry.date);
        const count = detail?.item_count ?? entry.item_count ?? 0;
        return `
        <button type="button" class="diting-date-chip${entry.date === selectedDate ? " active" : ""}" data-dt-date="${escapeHtml(entry.date)}" data-dt-kind="${escapeHtml(kind)}">
          <strong>${escapeHtml(formatDateShort(entry.date))}</strong>
          <span>${escapeHtml(String(count))} 条</span>
        </button>
      `;
      }).join("")}
    </div>
  `;
}

function ditingSectionBlock(section, config) {
  return `
    <article class="diting-section-block">
      <div class="diting-section-head">
        <div>
          <h2>${escapeHtml(section.title || "日报内容")}</h2>
          <span>${escapeHtml(section.count_label || `${section.items.length} 条`)}</span>
        </div>
        <strong>${escapeHtml(String(section.items.length))}</strong>
      </div>
      <div class="diting-card-list">
        ${section.items.map((item) => ditingDigestCard(item, config)).join("")}
      </div>
    </article>
  `;
}

function ditingDigestCard(item, config) {
  const source = ditingItemSource(item, config);
  const tgChannelName = config.routeName === "tgDaily" ? compactDisplayText(item.channel_name || item.channelName || "") : "";
  const title = compactDisplayText(item.title || item.summary || "未命名条目");
  const url = safeExternalUrl(item.url || "");
  const summary = ditingBodySummary(item, title, config);
  const links = ditingUsefulLinks(item, url, config);
  const linkedSummary = ditingSummaryHtml(summary, links, config);
  const inlineLinks = config.routeName === "tgDaily"
    ? links.filter((link) => !linkedSummary.matchedHrefs.has(link.href))
    : [];
  const footerLinks = config.routeName === "tgDaily" ? [] : links;
  const media = mediaGridNode(ditingMediaItems(item), item);
  const commentAction = ditingCommentActionNode(item, config);
  const showSectionMeta = config.routeName !== "tgDaily";
  const showSourceMeta = config.routeName !== "tgDaily";
  return `
    <article class="diting-card${config.routeName === "tgDaily" ? " tg-digest-card" : ""}">
      <div class="diting-card-meta">
        ${showSectionMeta && item.section_title ? `<span>${escapeHtml(item.section_title)}</span>` : ""}
        ${showSourceMeta && source ? `<span>${escapeHtml(source)}</span>` : ""}
        ${item.time ? `<span>${escapeHtml(item.time)}</span>` : ""}
        ${tgChannelName ? `<span>${escapeHtml(tgChannelName)}</span>` : ""}
      </div>
      <h3>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title)}</h3>
      ${summary ? `<p>${linkedSummary.html}</p>` : ""}
      ${inlineLinks.length ? `<div class="diting-link-row">${inlineLinks.map((link) => `<a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>`).join("")}</div>` : ""}
      ${media}
      ${commentAction}
      ${footerLinks.length ? `<div class="diting-link-row">${footerLinks.map((link) => `<a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>`).join("")}</div>` : ""}
    </article>
  `;
}

function ditingBodySummary(item, title, config) {
  const summary = config.routeName === "tgDaily" ? multilineDisplayText(item.summary || "") : compactDisplayText(item.summary || "");
  if (config.routeName !== "tgDaily") return summary;
  return stripRepeatedDitingTitle(title, summary);
}

function stripRepeatedDitingTitle(title, summary) {
  const displayTitle = compactDisplayText(title || "");
  const body = multilineDisplayText(summary || "");
  if (!displayTitle || !body) return body;
  const lines = body.split("\n");
  const firstIndex = lines.findIndex((line) => compactDisplayText(line));
  if (firstIndex < 0) return body;
  const firstLine = compactDisplayText(lines[firstIndex]);
  if (!sameCompactTitleText(firstLine, displayTitle)) return body;
  lines.splice(firstIndex, 1);
  return lines.join("\n").replace(/^\n+/, "").trim();
}

function sameCompactTitleText(a, b) {
  const normalize = (value) => String(value || "").replace(/\s+/g, "").replace(/[，。,.!?！？:：；;]/g, "").toLowerCase();
  const left = normalize(a);
  const right = normalize(b);
  return Boolean(left && right && left === right);
}

function ditingMediaItems(item) {
  return validDitingMediaItems(item.media || []);
}

function validDitingMediaItems(mediaItems = []) {
  return (Array.isArray(mediaItems) ? mediaItems : []).filter((media) => {
    if (!media || typeof media !== "object") return false;
    if (String(media.publish_status || "").toLowerCase() === "failed") return false;
    if (isVideoMedia(media)) return Boolean(videoPosterUrl(media) || bestVideoUrl(media) || safeExternalUrl(media.fallback_url || media.fallbackUrl || ""));
    return Boolean(imageMediaUrl(media));
  });
}

function ditingCommentActionNode(item, config) {
  if (config.routeName !== "tgDaily") return "";
  const replies = visibleDitingReplies(item);
  if (replies.length) {
    const threadId = ditingCommentThreadId(item);
    state.ditingCommentThreads.set(threadId, { item, replies });
    return `
      <div class="diting-comment-action">
        <button type="button" class="diting-comment-link" data-diting-comments="${escapeHtml(threadId)}">评论(${escapeHtml(String(replies.length))})</button>
      </div>
    `;
  }
  const replyCount = Number(item.reply_count ?? item.replyCount ?? 0);
  const repliesFetched = Number(item.replies_fetched ?? item.repliesFetched ?? 0);
  if (replyCount > 0 && repliesFetched === 0 && ("reply_count" in item || "replyCount" in item)) {
    return `<div class="diting-comment-action"><span class="diting-comment-unavailable">评论加载失败</span></div>`;
  }
  return "";
}

function visibleDitingReplies(item) {
  const replies = Array.isArray(item?.replies) ? item.replies : [];
  return replies
    .map(normalizedDitingReply)
    .filter((reply) => reply && !ditingReplyFilterReason(reply));
}

function normalizedDitingReply(reply) {
  if (!reply || typeof reply !== "object") return null;
  const media = validDitingMediaItems(reply.media || []);
  return {
    id: compactDisplayText(reply.id || ""),
    text: multilineDisplayText(reply.text || ""),
    time: compactDisplayText(reply.time || ""),
    senderName: compactDisplayText(reply.sender_name || reply.senderName || ""),
    media,
  };
}

function ditingReplyFilterReason(reply) {
  const text = compactDisplayText(reply?.text || "");
  const sender = compactDisplayText(reply?.senderName || "");
  const media = Array.isArray(reply?.media) ? reply.media : [];
  if (!text && !media.length) return "empty";
  const compact = `${sender}${text}`.replace(/\s+/g, "");
  if (TG_COMMENT_BLOCK_PATTERNS.some((pattern) => pattern.test(compact))) return "blocked";
  if (!media.length) {
    const signalLength = signalCharCount(text);
    if (signalLength <= 1) return "low-signal";
    if (signalLength <= 8 && TG_COMMENT_LOW_SIGNAL_RE.test(compact)) return "low-signal";
  }
  return "";
}

function signalCharCount(value) {
  return (String(value || "").replace(/https?:\/\/\S+/gi, "").match(/[A-Za-z0-9\u3400-\u9fff]/g) || []).length;
}

function ditingCommentThreadId(item) {
  const seed = item?.id || item?.message_id || item?.messageId || item?.url || Math.random().toString(36).slice(2);
  return `diting-comments-${String(seed).replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 80)}`;
}

function ditingItemSource(item, config) {
  if (config.routeName === "tgDaily") return compactDisplayText(item.channel_name || item.channelName || item.channel || item.source || "");
  return compactDisplayText(item.source || item.channel || "");
}

const DITING_TG_RECOMMENDATION_LABELS = new Set([
  "AI探索",
  "AI探索站",
  "Hermes/OpenClaw",
  "优质资源",
  "优质信息",
  "优质内容",
  "优质「资源」",
  "优质「内容」",
  "出海赚美金",
  "内幕消息",
  "你不知道的内幕消息🌳",
  "副业搞钱",
  "在花频道",
  "茶馆水群",
  "投稿通道",
]);

function ditingUsefulLinks(item, primaryUrl, config) {
  const links = [];
  if (primaryUrl && config?.routeName !== "tgDaily") links.push({ href: primaryUrl, label: "打开原文" });
  (item.links || []).forEach((link) => {
    const href = safeExternalUrl(link.href || "");
    const label = compactDisplayText(link.label || "");
    if (!href || href === primaryUrl) return;
    if (config?.routeName === "tgDaily" && /^查看|^原文|^来源/.test(label)) return;
    if (config?.routeName === "tgDaily" && isDitingTgRecommendationLink(href, label)) return;
    if (label.length > 40 && !/^查看|^原文|^来源/.test(label)) return;
    links.push({ href, label: label || "相关链接" });
  });
  const seen = new Set();
  return links.filter((link) => {
    if (seen.has(link.href)) return false;
    seen.add(link.href);
    return true;
  }).slice(0, 5);
}

function ditingSummaryHtml(summary, links, config) {
  const text = config?.routeName === "tgDaily" ? multilineDisplayText(summary || "") : compactDisplayText(summary || "");
  const matchedHrefs = new Set();
  if (!text) return { html: "", matchedHrefs };
  if (config?.routeName !== "tgDaily" || !links.length) {
    return { html: escapeHtml(text), matchedHrefs };
  }
  const ranges = [];
  const candidates = links
    .map((link) => ({
      href: safeExternalUrl(link.href || ""),
      label: compactDisplayText(link.label || ""),
    }))
    .filter((link) => link.href && link.label && link.label.length <= 40)
    .sort((a, b) => b.label.length - a.label.length);
  candidates.forEach((link) => {
    let start = text.indexOf(link.label);
    while (start !== -1) {
      const end = start + link.label.length;
      const overlaps = ranges.some((range) => start < range.end && end > range.start);
      if (!overlaps) {
        ranges.push({ start, end, href: link.href });
        matchedHrefs.add(link.href);
        break;
      }
      start = text.indexOf(link.label, start + 1);
    }
  });
  if (!ranges.length) return { html: escapeHtml(text), matchedHrefs };
  ranges.sort((a, b) => a.start - b.start);
  let cursor = 0;
  let html = "";
  ranges.forEach((range) => {
    html += escapeHtml(text.slice(cursor, range.start));
    html += `<a href="${escapeHtml(range.href)}" target="_blank" rel="noreferrer">${escapeHtml(text.slice(range.start, range.end))}</a>`;
    cursor = range.end;
  });
  html += escapeHtml(text.slice(cursor));
  return { html, matchedHrefs };
}

function isDitingTgRecommendationLink(href, label) {
  if (!label || /^查看|^原文|^来源/.test(label)) return false;
  const normalizedHref = String(href || "").replace(/\/+$/, "");
  if (!/^https?:\/\/t\.me\//i.test(normalizedHref)) return false;
  if (DITING_TG_RECOMMENDATION_LABELS.has(label)) return true;
  return /^https?:\/\/t\.me\/[^/?#]+$/i.test(normalizedHref) && label.length <= 16;
}

function compactDisplayText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function multilineDisplayText(value) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function dashboardTodayDate() {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  } catch (error) {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
}

function restoreDitingDateRailScroll() {
  document.querySelectorAll("[data-dt-date-rail]").forEach((rail) => {
    const kind = rail.dataset.dtDateRail;
    const target = state.dtDateRailScroll[kind] || 0;
    rail.scrollLeft = target;
    requestAnimationFrame(() => {
      rail.scrollLeft = target;
    });
  });
}

function comparePlatformItems(a, b) {
  return String(b.created_at || b.time || "").localeCompare(String(a.created_at || a.time || ""));
}

function featuredItemsForDaily(daily, applyFilter = true) {
  const dailySample = isDailySample(daily);
  const nativeItems = daily.featured_items?.length ? finalizeFocusItems(daily.featured_items.map((item) => ({ ...normalizeFeaturedItem(item), is_sample: dailySample }))) : fallbackFeaturedItems(daily).map((item) => ({ ...item, is_sample: dailySample }));
  const filtered = applyFilter ? nativeItems.filter((item) => itemMatchesFeaturedFilter(item)) : nativeItems;
  return filtered.sort(compareEvents);
}

function normalizeFeaturedItem(item) {
  return {
    ...item,
    time: item.created_at,
    scoreValue: item.score_value,
    scoreLabel: item.score_label || "IPS",
    source: item.source_name || item.source_type || "公开舆情",
    summary: firstSourceText(item.translation_zh, item.original_text, item.body_zh, item.text, item.summary),
    reason: item.selected_reason,
  };
}

function chineseSignalText(item) {
  return firstSourceText(item.translation_zh, item.original_text, item.body_zh, item.text, item.summary, item.summary_zh);
}

function firstSourceText(...values) {
  return values.map((value) => String(value || "").trim()).find((value) => value && !isGeneratedSummaryText(value)) || "";
}

function isGeneratedSummaryText(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return [
    "用户在 X 上讨论与品牌相关的购物体验。",
    "用户讨论价格、优惠或正向购物体验。",
    "用户讨论物流、配送或包裹追踪体验。",
  ].includes(text);
}

function translationStatusKind(item) {
  const status = String(item?.translation_status || "").toLowerCase();
  if (["missing", "error"].includes(status)) return "fallback";
  if (["translated", "sample_dictionary", "provider_supplied"].includes(status)) return "translated";
  if (status === "source_chinese") return "source";
  return "";
}

function translationStateLabel(item) {
  const kind = translationStatusKind(item);
  if (kind === "fallback") return "原文展示";
  if (kind === "translated") return "中文译文";
  if (kind === "source") return "中文原帖";
  return "";
}

function translationStateBadge(item) {
  const label = translationStateLabel(item);
  if (!label) return "";
  return `<span class="translation-state ${escapeHtml(translationStatusKind(item))}">${escapeHtml(label)}</span>`;
}

function translationStateInline(item) {
  const badge = translationStateBadge(item);
  return badge ? ` · ${badge}` : "";
}

function languageSwitchId(item, prefix = "post") {
  const seed = String(item?.id || item?.post_id || item?.post_url || item?.external_href || item?.externalHref || item?.url || Math.random());
  return `${prefix}-${seed.replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 80)}`;
}

function postTextVariants(item, preferredText = "") {
  const zh = firstSourceText(item?.translation_zh, item?.body_zh, preferredText, item?.summary, item?.summary_zh);
  const original = firstSourceText(item?.original_text, item?.originalText, item?.text, item?.clean_text);
  const hasOriginal = Boolean(original && zh && !sameDisplayText(original, zh));
  return { zh: zh || original || "", original, hasOriginal };
}

function languageToggleNode(item, id) {
  const variants = postTextVariants(item);
  if (!variants.hasOriginal) return translationStateBadge(item);
  return `
    <span class="language-toggle" role="group" aria-label="正文语言切换">
      <button type="button" class="active" data-language-toggle="${escapeHtml(id)}" data-language="zh">中文译文</button>
      <button type="button" data-language-toggle="${escapeHtml(id)}" data-language="original">原文</button>
    </span>
  `;
}

function postLanguageTextNode(item, preferredText, className = "", id = languageSwitchId(item)) {
  const variants = postTextVariants(item, preferredText);
  if (!variants.hasOriginal) return richPostTextNode(item, variants.zh || preferredText, className);
  const extraClass = className ? ` ${escapeHtml(className)}` : "";
  return `
    <div class="post-language-content" data-language-content="${escapeHtml(id)}">
      <div class="post-language-panel active" data-language-panel="zh">
        ${richPostTextNode(item, variants.zh, className)}
      </div>
      <div class="post-language-panel" data-language-panel="original">
        ${richPostTextNode(item, variants.original, `${className} original-text`.trim())}
      </div>
    </div>
  `;
}

function postTextWithInlineLanguageToggle(item, preferredText, className = "", prefix = "post") {
  const id = languageSwitchId(item, prefix);
  const variants = postTextVariants(item, preferredText);
  if (!variants.hasOriginal) return richPostTextNode(item, variants.zh || preferredText, className);
  return `
    <div class="inline-language-switch">
      ${languageToggleNode(item, id)}
    </div>
    ${postLanguageTextNode(item, preferredText, className, id)}
  `;
}

function insightReason(item, fallback = "") {
  const generated = generatedInsightReason(item);
  const existing = String(item?.selected_reason || item?.reason || item?.score?.explanation || fallback || "").trim();
  if (existing && !isGenericInsightText(existing)) return existing;
  return generated;
}

function reasonLine(item, className = "", fallback = "") {
  const reason = insightReason(item, fallback);
  if (!reason) return "";
  const extraClass = className ? ` ${escapeHtml(className)}` : "";
  return `<div class="reason-line${extraClass}">关注原因：${escapeHtml(reason)}</div>`;
}

function generatedInsightReason(item) {
  if (item?.source_type === "摘要级归档" || item?.channel === "archive" || item?.type === "summary") return "";
  const text = firstSourceText(item?.translation_zh, item?.body_zh, item?.summary, item?.original_text, item?.originalText, item?.text);
  if (!text) return "";
  const topic = inferSignalTopic(text, item);
  const stats = signalStats(item);
  const sourceCount = Number(item?.source_count || item?.postCount || 0);
  const ips = item?.score_label === "IPS" || item?.score?.ips ? Number(item?.score?.ips || item?.score_value || 0) : 0;
  const competitorSignal = item?.brand === "temu";
  const competitorFocus = competitorSignal ? competitorFocusSignal(text, item) : null;
  if (competitorSignal && !competitorFocus.central) return "";
  const sensitiveEnough = topic.sensitive && (!competitorSignal || stats.views >= 50 || stats.interactions > 0);
  const topicHasEnoughEvidence = topic.useful && (!competitorSignal || stats.notable || sensitiveEnough || (stats.interactions > 0 && stats.views >= 50));
  const competitorHasBasis = competitorSignal
    ? (topicHasEnoughEvidence || (competitorFocus.strong && (stats.notable || stats.interactions >= 3 || stats.views >= 1000)) || sensitiveEnough)
    : false;
  const hasUsefulBasis = competitorSignal
    ? competitorHasBasis
    : topicHasEnoughEvidence || stats.notable || sourceCount > 1 || item?.tracking_eligible || ips >= 65;
  if (!hasUsefulBasis) return "";
  const impact = propagationPhrase(item, stats);
  const similarDiscussionPhrase = sourceCount > 1 ? `，同日相似讨论 ${sourceCount} 条` : "";
  return `内容指向${topic.name}：${topic.angle}；${impact}${similarDiscussionPhrase}；研判：${topic.implication}`;
}

function isGenericInsightText(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  return [
    "竞品基线内容，用于观察样例竞品当日讨论主题和互动强度。",
    "用于对照主品牌当日声量和风险语境。",
    "进入当日情报归档。",
    "该舆情达到焦点阈值，建议结合原帖证据持续观察。",
    "Backfilled from summary metrics only.",
  ].some((needle) => text.includes(needle)) || /^该情报与 Joybuy\/JD 海外购物相关，当前综合优先级/.test(text) || /^该情报偏正向机会，体现价格、配送或促销优势/.test(text);
}

function inferSignalTopic(text, item = {}) {
  const lower = String(text || "").toLowerCase();
  const brand = item.brand === "temu" ? "竞品侧" : "主品牌";
  const hasAny = (terms) => terms.some((term) => lower.includes(term.toLowerCase()) || String(text).includes(term));
  if (item.topic === "positive_experience" || hasAny(["helft van de prijs", "idioot snel", "voordeliger", "快得离谱", "最多一天", "更划算", "价格通常只有一半", "配送快", "推荐"])) {
    return {
      name: "正向购物体验",
      angle: "用户主动提到价格、配送或购买体验上的正向感受",
      implication: "可作为主品牌海外口碑和履约卖点的证据样本。",
      useful: true,
    };
  }
  if (item.topic === "competitor_comparison") {
    return {
      name: "竞品对照与替代选择",
      angle: "用户把主品牌与其他平台进行价格、配送或品类对比",
      implication: "适合观察主品牌在海外用户购物选择中的竞争位置。",
      useful: true,
    };
  }
  if (item.topic === "channel_activity") {
    return {
      name: "渠道合作与活动",
      angle: "内容涉及渠道接入、商家合作、直播活动或站点更新",
      implication: "可作为市场扩展和货架露出的背景信号。",
      useful: true,
    };
  }
  if (item.topic === "company_market") {
    return {
      name: "公司/资本市场信息",
      angle: "内容涉及公司战略、资本市场、行业报告或管理层动态",
      implication: "对品牌心智有间接影响，应与消费者体验类舆情分开阅读。",
      useful: true,
    };
  }
  if (["product_deal", "price_opportunity"].includes(item.topic)) {
    return {
      name: "价格促销与导购",
      angle: "内容强调优惠、低价、券包或导购入口",
      implication: item.brand === "temu" ? "有助于观察样例竞品拉新促销话术及可能的垃圾推广占比。" : "可评估是否存在可借势传播的价格/活动卖点。",
      useful: true,
    };
  }
  if (item.topic === "regulatory") {
    return {
      name: "监管/并购风险",
      angle: "内容涉及海外监管审查、并购交易或市场准入风险",
      implication: "这类舆情可能影响管理层判断、市场信任和欧洲业务推进，应从普通消费体验中单独拎出。",
      useful: true,
      sensitive: true,
    };
  }
  if (item.topic === "fulfillment_risk") {
    return {
      name: "履约/售后风险",
      angle: "内容涉及订单、退款、退货、配送或售后处理",
      implication: `${brand}的信任成本会被放大，需关注是否出现更多相似投诉。`,
      useful: true,
      sensitive: true,
    };
  }
  if (hasAny(["refund", "退款", "退货", "售后", "chargeback"])) {
    return {
      name: "退款/售后体验",
      angle: "用户明确提到退款、退货或售后处理",
      implication: `${brand}的信任成本会被放大，需关注是否出现更多相似投诉。`,
      useful: true,
      sensitive: true,
    };
  }
  if (hasAny(["delivery", "shipping", "parcel", "warehouse", "ships from", "发货", "配送", "物流", "包裹", "本地仓", "仓库", "transporteur", "commande"])) {
    return {
      name: "履约与物流心智",
      angle: "原帖围绕发货、仓库、配送或包裹进度展开",
      implication: item.brand === "temu" ? "可作为样例竞品履约卖点/槽点的竞品参照。" : "需要判断这是正向履约口碑还是潜在配送投诉。",
      useful: true,
    };
  }
  if (hasAny(["coupon", "discount", "promo", "deal", "save", "ultra-low", "优惠", "折扣", "券", "低价", "省钱", "促销"])) {
    return {
      name: "价格促销与导购",
      angle: "内容强调优惠、低价、券包或导购入口",
      implication: item.brand === "temu" ? "有助于观察样例竞品拉新促销话术及可能的垃圾推广占比。" : "可评估是否存在可借势传播的价格/活动卖点。",
      useful: true,
    };
  }
  if (hasAny(["regulator", "regulatory", "investigation", "foreign subsidies", "subsidy", "charge sheet", "european commission", "ceconomy", "takeover", "acquisition", "antitrust", "欧盟", "监管", "收购", "并购", "补贴", "反垄断"])) {
    return {
      name: "监管/并购风险",
      angle: "内容涉及海外监管审查、并购交易或市场准入风险",
      implication: "这类舆情可能影响管理层判断、市场信任和欧洲业务推进，应从普通消费体验中单独拎出。",
      useful: true,
      sensitive: true,
    };
  }
  if (hasAny(["amazon", "fnac", "cdiscount", "micromania", "shein", "jd.com", "京东"])) {
    return {
      name: "多平台比价/货架露出",
      angle: "原帖把品牌与其他电商平台并列展示",
      implication: "适合观察品牌在海外用户心智中的货架位置和竞品集合。",
      useful: true,
    };
  }
  if (item.brand === "temu" && hasAny(["cheap", "low quality", "knockoff", "lazy", "temu version", "temu-looking", "temu looking", "敷衍", "低质", "山寨", "乱七八糟"])) {
    return {
      name: "竞品低价/低质心智",
      angle: "原帖把样例竞品作为低价、低质或山寨感的表达符号",
      implication: "这类内容可作为竞品品牌心智参照，但只有出现较高传播时才需要进入焦点。",
      useful: true,
      sensitive: true,
    };
  }
  if (hasAny(["order", "cart", "shop", "buy", "下单", "订单", "购物车", "购买", "想试试"])) {
    return {
      name: "购买意向与日常购物",
      angle: "用户表达下单、加购或尝试购买意向",
      implication: item.brand === "temu" ? "可作为竞品自然需求与用户使用场景样本，需结合互动与浏览判断是否异常。" : "可用于判断主品牌是否被真实用户纳入购买选择。",
      useful: true,
    };
  }
  if (hasAny(["scam", "fake", "damaged", "stupid", "lazy", "nonsense", "蠢", "假", "坏了", "差", "敷衍", "乱七八糟"])) {
    return {
      name: "负向情绪/玩梗表达",
      angle: "文本带有吐槽、嘲讽或低信任表达",
      implication: "短期未必是正式投诉，但容易在高互动场景下转化为品牌负面语境。",
      useful: true,
      sensitive: true,
    };
  }
  if (hasAny(["😭", "😅", "😍", "cosplay", "baby", "meme"])) {
    return {
      name: "轻量玩梗/社交表达",
      angle: "内容更像日常调侃或情绪化表达",
      implication: "建议按话题热度样本观察，不宜直接升级为风险事件。",
      useful: false,
    };
  }
  return {
    name: item.brand === "temu" ? "竞品日常声量" : "品牌日常声量",
    angle: "原帖没有明显投诉或处置线索，主要体现日常提及",
    implication: "适合进入声量基线，用于和后续异常波动做对照。",
    useful: false,
  };
}

function propagationPhrase(item, stats = signalStats(item)) {
  const { replies, reposts, quotes, views, interactions, followers } = stats;
  const base = views ? `${formatCompactNumber(interactions)} 次赞评转引、${formatCompactNumber(views)} 浏览` : `${formatCompactNumber(interactions)} 次赞评转引`;
  if (followers >= 20000) return `作者具备较高影响力（${formatCompactNumber(followers)} followers），当前 ${base}`;
  if (quotes + reposts >= 5) return `转引信号相对突出，当前 ${base}`;
  if (replies >= 3) return `评论参与高于普通样本，当前 ${base}`;
  if (views >= 1000 && interactions <= 3) return `已有千级浏览但互动偏低，当前 ${base}`;
  if (interactions === 0) return views ? `当前传播仍弱，${formatCompactNumber(views)} 浏览且暂无赞评转引` : "当前尚未形成可见互动";
  return `当前 ${base}`;
}

function signalStats(item) {
  const metrics = item?.post_metrics || item?.metrics || {};
  const likes = metricNumber(metrics.likes ?? metrics.total_likes);
  const replies = metricNumber(metrics.replies ?? metrics.total_replies);
  const reposts = metricNumber(metrics.reposts ?? metrics.total_reposts);
  const quotes = metricNumber(metrics.quotes ?? metrics.total_quotes);
  const views = metricNumber(metrics.views ?? metrics.total_views);
  const interactions = likes + replies + reposts + quotes;
  const followers = metricNumber(item?.author_followers);
  return {
    likes,
    replies,
    reposts,
    quotes,
    views,
    interactions,
    followers,
    notable: followers >= 20000 || views >= 1000 || interactions >= 3 || replies >= 2 || reposts + quotes >= 2,
  };
}

function metricNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function detailBodyLabel(item, language) {
  if (language === "original") return "正文 · 原文";
  if (translationStatusKind(item) === "fallback") return "正文 · 原文展示";
  if (translationStatusKind(item) === "source") return "正文 · 中文原帖";
  return "正文 · 中文译文";
}

function localizedTitle(title, fallback, defaultText = "舆情信号") {
  const value = String(title || "").trim();
  if (value && /[\u3400-\u9fff]/.test(value)) return value;
  const next = String(fallback || "").trim();
  if (next) return truncateText(next, 42);
  return value || defaultText;
}

function truncateText(value, maxLength) {
  const text = String(value || "").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function sourceTypeLabel(item) {
  const raw = String(item.source_type || item.source_name || "公开舆情");
  if (raw.includes("摘要级归档")) return "历史摘要";
  return raw;
}

function isSampleMode(daily = state.selectedDaily || state.daily) {
  return daily?.collection_status?.status === "sample"
    || daily?.source_status?.status === "sample"
    || state.sourceStatus?.status === "sample"
    || state.overview?.source_status?.status === "sample";
}

function isDailySample(daily) {
  return daily?.collection_status?.status === "sample" || daily?.source_status?.status === "sample";
}

function sampleDataNotice(daily = state.selectedDaily || state.daily) {
  if (!isDailySample(daily)) return "";
  return `
    <section class="sample-data-notice">
      <strong>当前为样例数据预览</strong>
      <span>这些内容用于验证页面结构和交互，不代表真实舆情；样例内容会以状态标签标识，原帖入口不会跳转至外部站点。</span>
    </section>
  `;
}

function externalLinkButton(href, label, className = "", options = {}) {
  if (options.isSample) {
    return `<span class="text-button disabled ${escapeHtml(className)}" title="样例数据不提供真实 X 跳转">${escapeHtml(label)}已隐藏</span>`;
  }
  const url = safeExternalUrl(href);
  if (!url) return `<span class="text-button disabled ${escapeHtml(className)}">原帖不可用</span>`;
  return `<a class="text-button ${escapeHtml(className)}" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function cardFootnote(text, item) {
  return `
    <span class="card-footnote">
      <span>${escapeHtml(text)}</span>
      ${sampleInlineBadge(item)}
    </span>
  `;
}

function sampleInlineBadge(item) {
  if (!item?.is_sample) return "";
  return `<em class="sample-inline-badge">样例数据</em>`;
}

function cardExternalAction(href, item, label = "在 X 查看原帖") {
  if (!href || item?.is_sample) return "";
  const url = safeExternalUrl(href);
  if (!url) return "";
  return `<a class="text-button" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function leadPostFromCluster(cluster) {
  return cluster?.lead_post || {};
}

function sourcePostBody(post, fallback = "") {
  return firstSourceText(post?.translation_zh, post?.clean_text, post?.text, post?.original_text, fallback);
}

function leadPostText(cluster) {
  const post = leadPostFromCluster(cluster);
  return sourcePostBody(post, cluster?.summary_zh || cluster?.summary || "");
}

function leadPostSourceName(post, fallback = "主品牌") {
  const handle = post.author_handle || post.author?.handle || "";
  return handle ? `${fallback} · @${handle}` : fallback;
}

function leadPostAuthorName(post, fallback = "主品牌") {
  return post.author_name || post.author?.name || post.author_handle || post.author?.handle || fallback;
}

function safeExternalUrl(href) {
  const value = String(href || "").trim();
  if (!value) return "";
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) return "";
    return url.href;
  } catch (error) {
    return "";
  }
}

function fallbackFeaturedItems(daily) {
  if (daily.summary_only) return [];
  const clusterItems = (daily.clusters || [])
    .map((cluster) => {
      const score = cluster.score || {};
      const post = leadPostFromCluster(cluster);
      const text = leadPostText(cluster);
      const tags = [...(cluster.risk_types || []), ...(cluster.opportunity_types || []), cluster.topic].filter(Boolean);
      return normalizeFeaturedItem({
        id: `fallback-${cluster.cluster_id}`,
        brand: "joybuy",
        cluster_id: cluster.cluster_id,
        source_type: daily.summary_only ? "摘要级归档" : "公开原帖",
        source_name: leadPostSourceName(post, "主品牌"),
        author_name: leadPostAuthorName(post, "主品牌"),
        author_handle: post.author_handle || post.author?.handle || "",
        author_avatar_url: post.author_avatar_url || post.author?.avatar_url || "",
        author_followers: post.author_followers ?? post.author?.followers ?? 0,
        author_verified: post.author_verified ?? post.author?.verified ?? false,
        author_following: post.author_following ?? post.author?.following ?? 0,
        author_bio: post.author_bio || post.author_description || post.author?.bio || post.author?.description || "",
        author_location: post.author_location || post.author?.location || "",
        author_joined_at: post.author_joined_at || post.author?.joined_at || "",
        post_url: post.url || "",
        reply_to_post_id: post.reply_to_post_id || "",
        reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
        quoted_post_id: post.quoted_post_id || "",
        conversation_id: post.conversation_id || "",
        conversation_context: post.conversation_context || null,
        created_at: post.created_at || cluster.first_seen_at || cluster.last_seen_at,
        title: generatedOpinionTitle({ brand: "joybuy", tags, topic: cluster.topic, sentiment: score.sentiment || "neutral" }),
        display_title: "",
        original_text: post.text || post.clean_text || cluster.summary || "",
        translation_zh: text,
        translation_status: post.translation_status || "unknown",
        summary_zh: cluster.summary_zh || "",
        links: post.links || [],
        media: post.media || [],
        score,
        score_value: score.ips ?? "n/a",
        score_label: "IPS",
        tags,
        metrics: cluster.metrics || {},
        post_metrics: post.metrics || {},
        source_count: cluster.post_count || 1,
        related_sources: Math.max(0, Number(cluster.post_count || 1) - 1),
        selected_reason: score.explanation || cluster.tracking_reason || "摘要级归档保留了当日主题和指标，原帖级焦点舆情将在完整日报中展示。",
        recommended_action: score.recommended_action || "持续监测",
        href: "",
        external_href: post.url || "",
        sentiment: score.sentiment || "neutral",
        level: score.level || "low",
      });
    })
    .filter(isJoybuyFocusItem);
  const competitorItems = buildCompetitorEvents(daily)
    .filter((event) => event.brand === "temu")
    .map((event, index) =>
      normalizeFeaturedItem({
        id: `fallback-temu-${daily.date}-${index}`,
        brand: "temu",
        source_type: "竞品基线",
        source_name: event.source,
        author_name: event.author_name || "样例竞品来源",
        author_handle: event.author_handle || "",
        author_avatar_url: event.author_avatar_url || "",
        author_followers: event.author_followers || 0,
        author_following: event.author_following || 0,
        author_bio: event.author_bio || "",
        created_at: event.time,
        timeLabel: event.timeLabel,
        title: event.title,
        original_text: event.originalText || event.summary || "",
        translation_zh: event.summary,
        summary_zh: "",
        translation_status: event.translation_status || "unknown",
        links: event.links || [],
        media: event.media || [],
        score_value: event.scoreValue,
        score_label: event.scoreLabel,
        tags: event.tags || ["竞品"],
        metrics: {},
        post_metrics: event.metrics || {},
        source_count: 1,
        related_sources: 0,
        selected_reason: event.reason,
        recommended_action: "纳入竞品基线观察",
        href: "",
        external_href: event.href || "",
        reply_to_post_id: event.reply_to_post_id || "",
        reply_to_handle: event.reply_to_handle || "",
        quoted_post_id: event.quoted_post_id || "",
        conversation_id: event.conversation_id || "",
        conversation_context: event.conversation_context || null,
        sentiment: "neutral",
        level: "low",
      })
    )
    .filter(isCompetitorFocusItem);
  return finalizeFocusItems([...clusterItems, ...competitorItems]);
}

function finalizeFocusItems(items) {
  const sourceItems = items.filter((item) => {
    return item?.source_type !== "摘要级归档" && item?.channel !== "archive" && (item.external_href || item.post_url) && chineseSignalText(item);
  });
  const joybuy = sourceItems
    .filter((item) => item.brand !== "temu" && isJoybuyFocusItem(item))
    .sort(compareFocusPriority)
    .slice(0, 5);
  const competitorLimit = joybuy.length ? 2 : 3;
  const competitor = sourceItems
    .filter((item) => item.brand === "temu" && isCompetitorFocusItem(item))
    .sort(compareFocusPriority)
    .slice(0, competitorLimit);
  return [...joybuy, ...competitor].sort(compareFocusPriority).slice(0, 7);
}

function isJoybuyFocusItem(item) {
  if (!item || item.brand === "temu" || item.source_type === "摘要级归档") return false;
  if (!item.external_href && !item.post_url) return false;
  const text = chineseSignalText(item);
  if (!text) return false;
  const score = item.score || {};
  const stats = signalStats(item);
  const topic = inferSignalTopic(text, item);
  const sourceCount = Number(item.source_count || item.postCount || 0);
  return (
    ["urgent", "high", "medium"].includes(score.level) ||
    Number(score.ips || item.score_value || 0) >= 55 ||
    Number(score.future_potential || 0) >= 65 ||
    Number(score.current_impact || 0) >= 50 ||
    Number(item.author_followers || 0) >= 20000 ||
    sourceCount > 1 ||
    topic.useful ||
    item.sentiment === "positive" ||
    stats.notable
  );
}

function isCompetitorFocusItem(item) {
  if (!item || item.brand !== "temu") return false;
  if (!item.external_href && !item.post_url) return false;
  const text = chineseSignalText(item);
  if (!text) return false;
  const focus = competitorFocusSignal(text, item);
  if (!focus.central) return false;
  const topic = inferSignalTopic(text, item);
  const stats = signalStats(item);
  const reason = insightReason(item);
  if (!reason && !focus.strong) return false;
  return Boolean(
    (topic.sensitive && !focus.negativeTrope && (stats.views >= 50 || stats.interactions > 0)) ||
      (focus.negativeTrope && (stats.views >= 1000 || stats.interactions >= 5 || stats.followers >= 20000)) ||
      (focus.strong && (stats.views >= 1000 || stats.interactions >= 5 || stats.followers >= 20000)) ||
      stats.views >= 2000 ||
      stats.interactions >= 8
  );
}

function competitorFocusSignal(text, item = {}) {
  const raw = String(text || "");
  const lower = raw.toLowerCase();
  const tags = (item.tags || []).map((tag) => String(tag).toLowerCase());
  const hasTemu = /\btemu\b/i.test(raw);
  const hasAnyTerm = (terms) => terms.some((term) => lower.includes(term.toLowerCase()) || raw.includes(term));
  const platformPhrases =
    /\b(order(?:ed|ing)?|buy|bought|shop|shopping|cart|coupon|discount|deal|gift|delivery|shipping|warehouse|app|ads?|haul|refund|return)\b.{0,36}\btemu\b/i.test(raw) ||
    /\btemu\b.{0,36}\b(order(?:ed|ing)?|buy|bought|shop|shopping|cart|coupon|discount|deal|gift|delivery|shipping|warehouse|app|ads?|haul|refund|return)\b/i.test(raw) ||
    /\b(from|off|on|via|through)\s+temu\b/i.test(raw) ||
    hasAnyTerm(["Temu 上", "Temu下", "Temu 订单", "Temu订单", "Temu 快递", "Temu快递", "Temu 配送", "Temu配送", "Temu 优惠", "Temu优惠", "Temu 折扣", "Temu折扣", "Temu App", "Temu 广告", "Temu广告", "Temu 购物车", "Temu购物车", "本地仓", "来自 Temu", "从 Temu"]);
  const negativeBrandTrope = hasAnyTerm(["cheap", "low quality", "knockoff", "fake", "lazy", "stupid", "temu version", "temu-looking", "temu looking", "敷衍", "低质", "山寨", "假", "蠢", "乱七八糟"]);
  const matchedTopic = tags.some((tag) => ["delivery", "refund", "return", "scam", "fake", "damaged", "slow", "missing", "customer service"].includes(tag));
  return {
    central: hasTemu && (platformPhrases || matchedTopic || negativeBrandTrope),
    strong: hasTemu && (platformPhrases || matchedTopic || negativeBrandTrope),
    negativeTrope: hasTemu && negativeBrandTrope,
  };
}

function compareFocusPriority(a, b) {
  return focusPriorityScore(b) - focusPriorityScore(a);
}

function focusPriorityScore(item) {
  const stats = signalStats(item);
  const topic = inferSignalTopic(chineseSignalText(item), item);
  const score = item.score || {};
  const sourceCount = Number(item.source_count || item.postCount || 0);
  let value = 0;
  if (item.brand !== "temu") value += 40;
  if (topic.sensitive) value += 24;
  else if (topic.useful) value += 12;
  value += Math.min(40, Number(score.ips || 0));
  value += Math.min(20, sourceCount * 4);
  value += Math.min(24, stats.interactions * 3);
  value += Math.min(16, Math.log10(Math.max(1, stats.views)) * 5);
  value += Math.min(16, Math.log10(Math.max(1, stats.followers)) * 3);
  if (item.sentiment === "positive" && item.brand !== "temu") value += 8;
  return value;
}

function itemMatchesFeaturedFilter(item, filter = state.featuredFilter) {
  if (filter === "all") return true;
  if (filter === "competitor") return item.brand === "temu";
  if (filter === "opportunity") return item.brand !== "temu" && (item.sentiment === "positive" || (item.tags || []).some((tag) => String(tag).includes("opportunity") || String(tag).includes("机会")));
  if (filter === "watch") return Number(item.score?.future_potential || 0) >= 75 || Number(item.author_followers || 0) >= 20000 || (item.tags || []).includes("高潜传播");
  if (filter === "risk") return item.brand !== "temu" && item.sentiment !== "positive";
  return true;
}

function needsChineseTranslation(item) {
  const language = String(item.language || "").toLowerCase();
  const original = item.original_text || "";
  if (["zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant"].includes(language)) return false;
  if (language && language !== "und") return true;
  return original && !/[\u3400-\u9fff]/.test(original);
}

function avatarNode(item) {
  const avatarUrl = safeExternalUrl(item?.author_avatar_url);
  const name = item?.author_name || item?.author_handle || item?.source_name || "X Source";
  const avatar = avatarUrl
    ? `<img class="source-avatar" src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`
    : `<span class="source-avatar fallback">${escapeHtml(initials(name || "BX"))}</span>`;
  return `
    <span class="author-hover" tabindex="0">
      ${avatar}
      ${authorPopover(item)}
    </span>
  `;
}

function authorNameNode(item = {}, fallback = "X Source") {
  const name = String(fallback || item.author_name || item.author_handle || item.source_name || "X Source").trim();
  return `<span class="author-name">${escapeHtml(name)}${verifiedBadge(item)}</span>`;
}

function sourceBadge(label, kind = "") {
  const normalized = String(kind || label || "").toLowerCase();
  const className = normalized.includes("竞品") || normalized.includes("competitor") ? "competitor" : "focus";
  return `<strong class="source-badge ${escapeHtml(className)}">${escapeHtml(label || "舆情")}</strong>`;
}

function verifiedBadge(item = {}) {
  return item.author_verified || item.author?.verified
    ? `<span class="verified-badge" title="X 认证用户" aria-label="X 认证用户">✓</span>`
    : "";
}

function authorPopover(item = {}) {
  const handle = cleanHandle(item.author_handle || "");
  const name = item.author_name || handle || item.source_name || "X Source";
  const avatarUrl = safeExternalUrl(item.author_avatar_url);
  const profileUrl = handle ? `https://x.com/${handle}` : "";
  const bio = String(item.author_bio || item.author_description || "").trim();
  const location = String(item.author_location || item.authorLocation || "").trim();
  const joined = formatJoinedDate(item.author_joined_at || item.authorJoinedAt || item.author_created_at || item.authorCreatedAt || "");
  const followers = Number(item.author_followers || 0);
  const following = Number(item.author_following || 0);
  const hasProfileData = handle || bio || location || joined || followers || following || item.author_verified;
  if (!hasProfileData) return "";
  return `
    <span class="author-popover" role="tooltip">
      <span class="author-popover-head">
        ${avatarUrl ? `<img src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />` : `<span class="source-avatar fallback">${escapeHtml(initials(name))}</span>`}
        ${profileUrl ? `<a href="${escapeHtml(profileUrl)}" target="_blank" rel="noreferrer">查看主页</a>` : ""}
      </span>
      <strong>${escapeHtml(name)}${verifiedBadge(item)}</strong>
      ${handle ? `<span class="author-popover-handle">@${escapeHtml(handle)}</span>` : ""}
      ${bio ? `<p>${escapeHtml(bio)}</p>` : ""}
      ${(location || joined) ? `<span class="author-popover-profile-meta">
        ${location ? `<span>定位 ${escapeHtml(location)}</span>` : ""}
        ${joined ? `<span>加入 ${escapeHtml(joined)}</span>` : ""}
      </span>` : ""}
      <span class="author-popover-stats">
        ${following ? `<b>${escapeHtml(formatCompactNumber(following))}</b> Following` : ""}
        ${followers ? `<b>${escapeHtml(formatCompactNumber(followers))}</b> Followers` : ""}
      </span>
    </span>
  `;
}

function formatJoinedDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    timeZone: "Asia/Shanghai",
  });
}

function legacyAvatarNode(item) {
  const avatarUrl = safeExternalUrl(item.author_avatar_url);
  if (avatarUrl) {
    return `<img class="source-avatar" src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`;
  }
  return `<span class="source-avatar fallback">${escapeHtml(initials(item.author_name || item.author_handle || item.source_name || "BX"))}</span>`;
}

function initials(value) {
  const text = String(value || "").trim();
  if (!text) return "BX";
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return `${words[0][0]}${words[1][0]}`.toUpperCase();
  return text.slice(0, 2).toUpperCase();
}

function mediaGridNode(media = [], owner = {}) {
  const items = Array.isArray(media) ? media.filter(Boolean) : [];
  if (!items.length) return "";
  const hasVideo = items.some(isVideoMedia);
  const hasPortraitVideo = items.some(isPortraitVideoMedia);
  const xVideoEmbed = USE_X_EMBED_FOR_VIDEO && !owner?.is_sample && hasVideo ? xVideoEmbedNode(owner, items.find(isVideoMedia)) : "";
  const lightboxUrls = imageMediaUrls(items);
  const nodes = [];
  items.forEach((mediaItem, index) => {
    if (xVideoEmbed && isVideoMedia(mediaItem)) return;
    const node = mediaNode(mediaItem, owner, { mediaIndex: index + 1, lightboxUrls });
    if (node) nodes.push(node);
  });
  if (xVideoEmbed) nodes.push(xVideoEmbed);
  const classNames = [
    "featured-media-grid",
    hasVideo ? "has-video" : "",
    hasPortraitVideo ? "has-portrait-video" : "",
    nodes.length === 1 ? "single-media" : "",
    xVideoEmbed ? "has-x-embed" : "",
  ].filter(Boolean).join(" ");
  return nodes.length ? `<div class="${classNames}">${nodes.join("")}</div>` : "";
}

function mediaNode(item, owner = {}, options = {}) {
  if (typeof item === "string") {
    const safeUrl = safeExternalUrl(item);
    return safeUrl ? imageMediaNode(safeUrl, options) : "";
  }
  if (isVideoMedia(item)) {
    const posterUrl = videoPosterUrl(item) || imagePreviewMediaUrl(item);
    const videoUrl = bestVideoUrl(item);
    const tweetUrl = tweetVideoOpenUrl(owner, item, options.mediaIndex);
    const fallbackUrl = safeExternalUrl(item.fallback_url || item.fallbackUrl || "") || tweetOpenUrl(owner, item);
    const originalUrl = tweetUrl || fallbackUrl || videoUrl;
    if (!parseTweetUrl(tweetUrl) && videoUrl && !parseTweetUrl(videoUrl)) return htmlVideoNode(videoUrl, posterUrl, item);
    if (!originalUrl) return posterUrl ? imageMediaNode(posterUrl, { ...options, aspectRatio: mediaAspectRatio(item) }) : "";
    const aspectStyle = mediaAspectStyle(item);
    const shellClass = ["media-video-shell", mediaOrientationClass(item)].filter(Boolean).join(" ");
    const posterNode = posterUrl
      ? `<img class="media-video-thumb" src="${escapeHtml(posterUrl)}" alt="" loading="lazy" />`
      : `<span class="media-video-thumb fallback" aria-hidden="true"></span>`;
    return `
      <div class="${shellClass}"${aspectStyle}>
        <a class="media-video-link" href="${escapeHtml(originalUrl)}" target="_blank" rel="noreferrer" aria-label="打开视频">
          ${posterNode}
          <span class="media-play-button" aria-hidden="true"><span></span></span>
        </a>
      </div>
    `;
  }
  const imageUrl = imageMediaUrl(item);
  const previewUrl = imagePreviewMediaUrl(item) || imageUrl;
  return imageUrl ? imageMediaNode(imageUrl, { ...options, previewUrl, aspectRatio: mediaAspectRatio(item) }) : "";
}

function imageMediaUrl(item) {
  if (typeof item === "string") return safeExternalUrl(item);
  return safeExternalUrl(item?.media_url_https || item?.media_url || item?.preview_image_url || item?.previewImageUrl || item?.url || "");
}

function imagePreviewMediaUrl(item) {
  if (typeof item === "string") return safeExternalUrl(item);
  return safeExternalUrl(item?.thumb_url || item?.thumbUrl || item?.thumbnail_url || item?.thumbnailUrl || item?.preview_image_url || item?.previewImageUrl || "");
}

function videoPosterUrl(item) {
  return safeExternalUrl(
    item?.poster_url
      || item?.posterUrl
      || item?.preview_image_url
      || item?.previewImageUrl
      || item?.thumb_url
      || item?.thumbUrl
      || item?.media_url_https
      || item?.mediaUrlHttps
      || item?.media_url
      || item?.mediaUrl
      || ""
  );
}

function imageMediaUrls(items = []) {
  const urls = [];
  items.forEach((item) => {
    if (isVideoMedia(item)) return;
    const url = imageMediaUrl(item);
    if (url && !urls.includes(url)) urls.push(url);
  });
  return urls;
}

function mediaAspectRatio(item) {
  const dimensions = mediaAspectDimensions(item);
  return dimensions ? `${dimensions.width} / ${dimensions.height}` : "";
}

function mediaAspectDimensions(item) {
  const candidates = [
    item?.video_info?.aspect_ratio,
    item?.videoInfo?.aspectRatio,
    [item?.width, item?.height],
    item?.original_info && [item.original_info.width, item.original_info.height],
    item?.originalInfo && [item.originalInfo.width, item.originalInfo.height],
    item?.sizes?.large && [item.sizes.large.w || item.sizes.large.width, item.sizes.large.h || item.sizes.large.height],
  ];
  for (const candidate of candidates) {
    if (!Array.isArray(candidate) || candidate.length < 2) continue;
    const width = Number(candidate[0]);
    const height = Number(candidate[1]);
    if (width > 0 && height > 0) return { width, height };
  }
  return null;
}

function mediaAspectStyle(item, options = {}) {
  const dimensions = mediaAspectDimensions(item);
  if (!dimensions) return "";
  const styles = [`--media-aspect-ratio: ${dimensions.width} / ${dimensions.height}`];
  if (dimensions.height > dimensions.width) {
    const maxHeight = Number(options.portraitMaxHeight || 300);
    const minWidth = Number(options.portraitMinWidth || 160);
    const maxWidth = Number(options.portraitMaxWidth || 340);
    const portraitWidth = Math.round(Math.max(minWidth, Math.min(maxWidth, maxHeight * (dimensions.width / dimensions.height))));
    styles.push(`--media-portrait-max-width: ${portraitWidth}px`);
    styles.push(`--media-portrait-max-height: ${maxHeight}px`);
  }
  return ` style="${escapeHtml(styles.join("; "))}"`;
}

function mediaOrientationClass(item) {
  const dimensions = mediaAspectDimensions(item);
  if (!dimensions) return "";
  if (dimensions.height > dimensions.width) return "is-portrait";
  if (dimensions.width > dimensions.height) return "is-landscape";
  return "is-square";
}

function isPortraitVideoMedia(item) {
  if (!isVideoMedia(item)) return false;
  const dimensions = mediaAspectDimensions(item);
  return Boolean(dimensions && dimensions.height > dimensions.width);
}

function isVideoMedia(item) {
  if (!item || typeof item === "string") return false;
  const mediaType = String(item?.type || item?.media_type || "").toLowerCase();
  const variants = item?.video_info?.variants || item?.videoInfo?.variants || [];
  return mediaType.includes("video") || mediaType.includes("gif") || Boolean(variants.length);
}

function xVideoEmbedNode(owner = {}, mediaItem = {}) {
  const embedUrl = canonicalTweetEmbedUrl(owner, mediaItem);
  if (!embedUrl) return "";
  const openUrl = tweetOpenUrl(owner, mediaItem) || embedUrl;
  return `
    <div class="x-video-embed-card" data-x-video-embed="true">
      <blockquote class="twitter-tweet" data-dnt="true" data-theme="light" data-conversation="none">
        <a href="${escapeHtml(embedUrl)}">在 X 查看视频</a>
      </blockquote>
      <a class="x-video-fallback" href="${escapeHtml(openUrl)}" target="_blank" rel="noreferrer">播放器未加载时打开原帖</a>
    </div>
  `;
}

function canonicalTweetEmbedUrl(owner = {}, mediaItem = {}) {
  const directUrl = tweetOpenUrl(owner, mediaItem);
  const parsed = parseTweetUrl(directUrl);
  if (parsed) return `https://twitter.com/${encodeURIComponent(parsed.handle)}/status/${encodeURIComponent(parsed.id)}`;
  const handle = cleanHandle(firstTextValue(owner.author_handle, owner.handle, owner.username));
  const id = firstTextValue(owner.post_id, owner.postId, owner.status_id, owner.statusId);
  if (handle && id) return `https://twitter.com/${encodeURIComponent(handle)}/status/${encodeURIComponent(id)}`;
  return "";
}

function tweetOpenUrl(owner = {}, mediaItem = {}) {
  const candidates = [
    owner.external_href,
    owner.externalHref,
    owner.post_url,
    owner.postUrl,
    owner.url,
    owner.href,
    mediaItem.expanded_url,
    mediaItem.expandedUrl,
  ];
  return candidates.map(safeExternalUrl).find(Boolean) || "";
}

function tweetVideoOpenUrl(owner = {}, mediaItem = {}, mediaIndex = 1) {
  const statusUrl = tweetOwnerStatusUrl(owner) || tweetOpenUrl(owner, mediaItem);
  const parsed = parseTweetUrl(statusUrl);
  const index = Math.max(1, Number(mediaIndex) || 1);
  if (parsed) {
    return `https://x.com/${encodeURIComponent(parsed.handle)}/status/${encodeURIComponent(parsed.id)}/video/${index}`;
  }
  const expanded = safeExternalUrl(mediaItem.expanded_url || mediaItem.expandedUrl || "");
  if (expanded && /\/video\/\d+/i.test(expanded)) {
    return expanded.replace(/\/video\/\d+/i, `/video/${index}`);
  }
  return expanded || "";
}

function tweetOwnerStatusUrl(owner = {}) {
  const candidates = [owner.external_href, owner.externalHref, owner.post_url, owner.postUrl, owner.url, owner.href];
  return candidates.map(safeExternalUrl).find((url) => parseTweetUrl(url)) || "";
}

function parseTweetUrl(url) {
  const safeUrl = safeExternalUrl(url);
  if (!safeUrl) return null;
  const match = safeUrl.match(/^https:\/\/(?:www\.)?(?:x|twitter)\.com\/([^/?#]+)\/status\/(\d+)/i);
  if (!match) return null;
  return { handle: cleanHandle(match[1]), id: match[2] };
}

function imageMediaNode(url, options = {}) {
  const safeUrl = safeExternalUrl(url);
  if (!safeUrl) return "";
  const previewUrl = safeExternalUrl(options.previewUrl || "") || safeUrl;
  const lightboxUrls = Array.isArray(options.lightboxUrls) && options.lightboxUrls.length ? options.lightboxUrls : [safeUrl];
  const lightboxIndex = Math.max(0, lightboxUrls.indexOf(safeUrl));
  const aspectStyle = options.aspectRatio ? ` style="--media-aspect-ratio: ${escapeHtml(options.aspectRatio)}"` : "";
  return `
    <button type="button" class="media-image-button"${aspectStyle} data-media-lightbox="${escapeHtml(safeUrl)}" data-media-lightbox-group="${escapeHtml(JSON.stringify(lightboxUrls))}" data-media-lightbox-index="${escapeHtml(String(lightboxIndex))}" aria-label="查看大图">
      <img src="${escapeHtml(previewUrl)}" alt="" loading="lazy" />
    </button>
  `;
}

function bestVideoUrl(item) {
  const direct = safeExternalUrl(item?.url || item?.media_url || item?.mediaUrl || "");
  if (direct && /\.mp4(?:[?#].*)?$/i.test(new URL(direct).pathname)) return direct;
  const variants = item?.video_info?.variants || item?.videoInfo?.variants || [];
  const mp4 = variants
    .filter((variant) => String(variant?.content_type || variant?.contentType || "").includes("mp4") && safeExternalUrl(variant?.url || ""))
    .sort((a, b) => Number(b.bitrate || 0) - Number(a.bitrate || 0));
  return safeExternalUrl(mp4[0]?.url || "");
}

function htmlVideoNode(videoUrl, posterUrl, item = {}) {
  const safeVideoUrl = safeExternalUrl(videoUrl);
  if (!safeVideoUrl) return "";
  const safePosterUrl = safeExternalUrl(posterUrl || "");
  const aspectStyle = mediaAspectStyle(item, { portraitMaxHeight: 480, portraitMinWidth: 200 });
  const shellClass = ["media-video-shell", "playable", mediaOrientationClass(item)].filter(Boolean).join(" ");
  const sizeBytes = Number(item?.size_bytes || item?.sizeBytes || 0);
  const sizeAttr = sizeBytes > 0 ? ` data-media-size-bytes="${escapeHtml(String(sizeBytes))}"` : "";
  return `
    <div class="${shellClass}"${aspectStyle}>
      <video class="media-video" controls playsinline preload="metadata" data-media-video-src="${escapeHtml(safeVideoUrl)}"${sizeAttr}${safePosterUrl ? ` poster="${escapeHtml(safePosterUrl)}"` : ""}>
        <source src="${escapeHtml(safeVideoUrl)}" type="video/mp4" />
      </video>
    </div>
  `;
}

function warmDitingMediaAssets(root = document) {
  const imageButtons = scopedQueryAll(root, ".tg-digest-card [data-media-lightbox], .diting-comment-drawer [data-media-lightbox]");
  const imageUrls = uniqueMediaUrls(imageButtons.map((button) => button.dataset.mediaLightbox).filter(Boolean));
  imageButtons.forEach((button) => {
    const url = safeExternalUrl(button.dataset.mediaLightbox || "");
    if (!url || button.dataset.mediaWarmBound === "1") return;
    button.dataset.mediaWarmBound = "1";
    const warm = () => prefetchImageUrl(url);
    button.addEventListener("pointerenter", warm, { once: true, passive: true });
    button.addEventListener("focus", warm, { once: true });
  });

  scheduleMediaWarmup(() => {
    imageUrls.slice(0, TG_MEDIA_PREFETCH_MAX_IMAGES).forEach(prefetchImageUrl);
  });

  const videos = scopedQueryAll(root, ".tg-digest-card video.media-video, .diting-comment-drawer video.media-video");
  videos.forEach((video) => {
    if (video.dataset.mediaWarmBound === "1") return;
    video.dataset.mediaWarmBound = "1";
    const warm = () => {
      video.preload = "auto";
      video.load();
      prefetchVideoUrl(video.dataset.mediaVideoSrc || video.querySelector("source")?.src || "");
    };
    video.addEventListener("pointerenter", warm, { once: true, passive: true });
    video.addEventListener("focus", warm, { once: true });
  });

  scheduleMediaWarmup(() => {
    videos
      .map((video) => ({
        url: safeExternalUrl(video.dataset.mediaVideoSrc || video.querySelector("source")?.src || ""),
        size: Number(video.dataset.mediaSizeBytes || 0),
      }))
      .filter((item) => item.url && (!item.size || item.size <= TG_MEDIA_PREFETCH_MAX_VIDEO_BYTES))
      .slice(0, TG_MEDIA_PREFETCH_MAX_VIDEOS)
      .forEach((item) => prefetchVideoUrl(item.url));
  }, 900);
}

function scopedQueryAll(root, selector) {
  const scope = root || document;
  const results = [];
  if (scope.matches?.(selector)) results.push(scope);
  scope.querySelectorAll?.(selector).forEach((node) => results.push(node));
  return results;
}

function uniqueMediaUrls(urls = []) {
  const result = [];
  urls.forEach((url) => {
    const safeUrl = safeExternalUrl(url || "");
    if (safeUrl && !result.includes(safeUrl)) result.push(safeUrl);
  });
  return result;
}

function scheduleMediaWarmup(callback, delay = 0) {
  const run = () => {
    try {
      callback();
    } catch (error) {
      // Best-effort media warming should never block the dashboard.
    }
  };
  if (delay > 0) {
    window.setTimeout(() => scheduleMediaWarmup(callback), delay);
    return;
  }
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(run, { timeout: 1800 });
  } else {
    window.setTimeout(run, 300);
  }
}

function prefetchImageUrl(url) {
  const safeUrl = safeExternalUrl(url || "");
  if (!safeUrl || state.prefetchedMediaUrls.has(safeUrl)) return;
  state.prefetchedMediaUrls.add(safeUrl);
  addMediaOriginHints(safeUrl);
  const image = new Image();
  image.decoding = "async";
  image.loading = "eager";
  image.src = safeUrl;
}

function prefetchVideoUrl(url) {
  const safeUrl = safeExternalUrl(url || "");
  if (!safeUrl || state.prefetchedMediaUrls.has(safeUrl)) return;
  state.prefetchedMediaUrls.add(safeUrl);
  addMediaOriginHints(safeUrl);
  const link = document.createElement("link");
  link.rel = "prefetch";
  link.as = "video";
  link.href = safeUrl;
  link.crossOrigin = "anonymous";
  document.head.appendChild(link);
}

function addMediaOriginHints(url) {
  try {
    const origin = new URL(url).origin;
    if (!origin || document.querySelector(`link[data-media-origin="${cssAttributeValue(origin)}"]`)) return;
    ["preconnect", "dns-prefetch"].forEach((rel) => {
      const link = document.createElement("link");
      link.rel = rel;
      link.href = origin;
      link.dataset.mediaOrigin = origin;
      if (rel === "preconnect") link.crossOrigin = "anonymous";
      document.head.appendChild(link);
    });
  } catch (error) {
    // Ignore malformed URLs; safeExternalUrl already filters user-facing use.
  }
}

function hydrateXVideoEmbeds() {
  if (!USE_X_EMBED_FOR_VIDEO) return;
  if (!document.querySelector("[data-x-video-embed]")) return;
  const content = document.getElementById("content") || document.body;
  if (window.twttr?.widgets?.load) {
    window.twttr.widgets.load(content);
    return;
  }
  if (document.querySelector("script[data-x-widgets]")) return;
  const script = document.createElement("script");
  script.src = X_WIDGET_SCRIPT_URL;
  script.async = true;
  script.charset = "utf-8";
  script.dataset.xWidgets = "true";
  script.onload = () => window.twttr?.widgets?.load?.(content);
  document.head.appendChild(script);
}

function richPostTextNode(item, text, className = "") {
  const content = richPostTextHtml(item, text);
  if (!content) return "";
  const extraClass = className ? ` ${escapeHtml(className)}` : "";
  return `<div class="tweet-rich-text${extraClass}">${content}</div>`;
}

function richPostTextHtml(item, text) {
  const displayText = decodeHtmlEntities(text).trim();
  if (!displayText) return "";
  const links = normalizedLinks(item?.links || item?.source_links || item?.urls || []);
  const sourceLineLinks = sourceLineLinksForItem(item, links);
  const sourceHasLinks = sourceLineLinks.some((lineLinks) => lineLinks.length);
  const used = new Set();
  let inlineUrlCursor = 0;
  let fallbackCursor = 0;
  const lines = displayText.split(/\r?\n/);
  const rendered = lines
    .map((line, index) => {
      if (!line.trim()) return `<div class="tweet-rich-line blank" aria-hidden="true"></div>`;
      const { html, urls } = linkifiedLine(line, links, inlineUrlCursor);
      inlineUrlCursor += urls.length;
      urls.forEach((url) => used.add(url));
      let appendedLinks = [];
      if (!urls.length) {
        appendedLinks = sourceHasLinks ? sourceLineLinks[index] || [] : heuristicLineLinks(line, links, fallbackCursor);
        if (!sourceHasLinks && appendedLinks.length) fallbackCursor += appendedLinks.length;
        appendedLinks = appendedLinks.filter((url) => !used.has(url));
        appendedLinks.forEach((url) => used.add(url));
      }
      return `<div class="tweet-rich-line">${html}${inlineLinkGroup(appendedLinks)}</div>`;
    })
    .join("");
  const leftovers = links.filter((url) => !used.has(url));
  return `${rendered}${leftovers.length ? `<div class="tweet-link-list"><span>链接</span>${leftovers.map((url) => richLink(url)).join("")}</div>` : ""}`;
}

function normalizedLinks(value) {
  const source = Array.isArray(value) ? value : [];
  const result = [];
  source.forEach((item) => {
    const url =
      typeof item === "string"
        ? item
        : item?.expanded_url || item?.expandedUrl || item?.url || item?.display_url || item?.displayUrl || "";
    const safeUrl = safeExternalUrl(url);
    if (safeUrl && !result.includes(safeUrl)) result.push(safeUrl);
  });
  return result;
}

function sourceLineLinksForItem(item, links) {
  const source = String(item?.original_text || item?.originalText || item?.text || item?.clean_text || "");
  if (!source || !links.length) return [];
  let cursor = 0;
  return source.split(/\r?\n/).map((line) => {
    const urls = [...line.matchAll(/https?:\/\/\S+/g)].map(() => links[cursor++]).filter(Boolean);
    return urls;
  });
}

function linkifiedLine(line, links, cursorStart = 0) {
  const urls = [];
  let cursor = cursorStart;
  let lastIndex = 0;
  let html = "";
  const regex = /https?:\/\/\S+/g;
  let match;
  while ((match = regex.exec(line))) {
    html += escapeHtml(line.slice(lastIndex, match.index));
    const expanded = links[cursor] || safeExternalUrl(match[0]) || match[0];
    cursor += 1;
    urls.push(expanded);
    html += richLink(expanded);
    lastIndex = match.index + match[0].length;
  }
  html += escapeHtml(line.slice(lastIndex));
  return { html, urls };
}

function heuristicLineLinks(line, links, cursor = 0) {
  if (!links[cursor]) return [];
  const text = String(line || "").trim();
  const isLinkLine =
    /[:：]\s*$/.test(text) ||
    /^(amazon|fnac|joybuy|cdiscount|micromania|infos?|信息|亚马逊)\b/i.test(text);
  return isLinkLine ? [links[cursor]] : [];
}

function inlineLinkGroup(links) {
  if (!links.length) return "";
  return `<span class="tweet-inline-links">${links.map((url) => richLink(url)).join("")}</span>`;
}

function richLink(url) {
  const safeUrl = safeExternalUrl(url);
  if (!safeUrl) return "";
  return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noreferrer">${escapeHtml(shortUrlLabel(safeUrl))}</a>`;
}

function contextRelationNode(item) {
  const conversationContext = normalizedConversationContext(item);
  const contextUrl = safeExternalUrl(item?.external_href || item?.externalHref || item?.post_url || item?.url || item?.href);
  if (conversationContext) {
    const contextId = conversationContextId(item, conversationContext);
    state.conversationContexts.set(contextId, { item, context: conversationContext });
    const summary = conversationContext.summary_zh || "这段对话包含收录帖前后的公开讨论，可用于判断该舆情出现的语境。";
    return `
      <div class="context-relation context-relation-summary">
        <p>${escapeHtml(summary)}</p>
        <div class="button-row context-actions">
          <button class="text-button primary" type="button" data-conversation-context="${escapeHtml(contextId)}">查看上下文</button>
          ${contextUrl ? `<a class="text-button" href="${escapeHtml(contextUrl)}" target="_blank" rel="noreferrer">在 X 查看完整对话</a>` : ""}
        </div>
      </div>
    `;
  }
  const relation = contextRelation(item);
  if (!relation) return "";
  const target = relation.targetUrl ? richLink(relation.targetUrl) : "";
  const fallbackContextUrl = contextUrl;
  return `
    <div class="context-relation">
      <span>${escapeHtml(relation.label)}</span>
      <p>${escapeHtml(relation.text)}${target ? ` ${target}` : ""}</p>
      ${relation.note ? `<em>${escapeHtml(relation.note)}</em>` : ""}
      ${fallbackContextUrl ? `<a href="${escapeHtml(fallbackContextUrl)}" target="_blank" rel="noreferrer">在 X 查看完整上下文</a>` : ""}
    </div>
  `;
}

function normalizedConversationContext(item) {
  const context = item?.conversation_context || item?.conversationContext || null;
  if (!context || !Array.isArray(context.posts) || !context.posts.length) return null;
  const anchorId = String(context.anchor_post_id || item?.post_id || item?.id || "");
  return {
    ...context,
    anchor_post_id: anchorId,
    posts: context.posts.filter(Boolean).sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""))),
  };
}

function conversationContextId(item, context) {
  const seed = context.anchor_post_id || item?.post_id || item?.id || item?.external_href || item?.externalHref || Math.random().toString(36).slice(2);
  return `conversation-${String(seed).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function contextRelation(item) {
  const quoteId = firstTextValue(item?.quoted_post_id, item?.quotedPostId, item?.quoted_status_id_str);
  if (quoteId) {
    return {
      label: "引用",
      text: "这条原帖引用了另一条 X 内容：",
      targetUrl: postStatusUrl("", quoteId),
      note: "引用原帖正文未随本次采集返回时，只展示关系入口。",
    };
  }
  const replyId = firstTextValue(item?.reply_to_post_id, item?.replyToPostId, item?.in_reply_to_status_id);
  const replyHandle = cleanHandle(firstTextValue(item?.reply_to_handle, item?.in_reply_to_screen_name, item?.inReplyToScreenName));
  if (replyId || replyHandle) {
    return {
      label: "回复",
      text: replyHandle ? `这条原帖是对 @${replyHandle} 的回复。` : "这条原帖属于一段回复链。",
      targetUrl: replyId ? postStatusUrl(replyHandle, replyId) : "",
      note: "父帖正文是否展示，取决于数据源是否在本次采集中返回。",
    };
  }
  const mention = leadingMention(item);
  if (mention) {
    return {
      label: "疑似回复",
      text: `正文以 @${mention} 开头，通常表示它位于一段回复链中。`,
      targetUrl: "",
    };
  }
  return null;
}

function leadingMention(item) {
  const text = firstTextValue(item?.original_text, item?.originalText, item?.text, item?.translation_zh, item?.body_zh, item?.summary);
  const match = String(text || "").trim().match(/^@([A-Za-z0-9_]{1,20})\b/);
  return match ? match[1] : "";
}

function firstTextValue(...values) {
  return values.map((value) => String(value || "").trim()).find(Boolean) || "";
}

function cleanHandle(value) {
  return String(value || "").replace(/^@/, "").trim();
}

function postStatusUrl(handle, id) {
  const postId = String(id || "").trim();
  if (!postId) return "";
  const user = cleanHandle(handle);
  return user ? `https://x.com/${user}/status/${postId}` : `https://x.com/i/web/status/${postId}`;
}

function shortUrlLabel(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.host.replace(/^www\./, "");
    const path = `${parsed.pathname}${parsed.search}`.replace(/\/$/, "");
    const label = `${host}${path}`;
    return label.length > 42 ? `${label.slice(0, 39)}...` : label;
  } catch (error) {
    return url.length > 42 ? `${url.slice(0, 39)}...` : url;
  }
}

function metricInline(label, value) {
  if (value == null || value === "") return "";
  return `<span>${escapeHtml(label)} ${escapeHtml(formatCompactNumber(value))}</span>`;
}

function formatCompactNumber(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function scoreClass(item) {
  const level = item.level || item.score?.level || "low";
  if (item.sentiment === "positive") return "score-good";
  if (item.kind === "risk" && ["urgent", "high"].includes(level)) return "score-hot";
  if (item.kind === "risk" && level === "medium") return "score-warm";
  return "score-calm";
}

function allIntelligencePage() {
  const archive = state.dailyArchive.length ? state.dailyArchive : [state.daily];
  const rawGroups = archive.map((daily) => ({
    daily,
    items: allItemsForDaily(daily),
  }));
  const allItems = rawGroups.flatMap((group) => group.items);
  const filteredGroups = rawGroups.map((group) => ({
    daily: group.daily,
    items: group.items.filter(itemMatchesAllFilters).sort(compareEvents),
  }));
  const filteredItems = filteredGroups.flatMap((group) => group.items);
  const metrics = allPageMetrics(allItems, filteredItems);
  return `
    ${pageHero({
      eyebrow: "舆情雷达",
      title: "全部舆情",
      subtitle: `${formatDateLong(archive[0]?.date)} · 主品牌与样例竞品舆情全量信息流`,
      stats: [
        [metrics.filtered, "当前结果"],
        [metrics.total, "归档总量"],
        [metrics.risk, "风险舆情"],
        [metrics.archiveDays, "归档天数"],
      ],
    })}
    ${sampleDataNotice(archive[0])}
    <section class="filter-panel">
      <div>
        <div class="toolbar-label">来源</div>
        <div class="filter-chip-row">
          ${allSourceFilterButton("all", "全部")}
          ${allSourceFilterButton("joybuy", "主品牌")}
          ${allSourceFilterButton("temu", "样例竞品")}
          ${allSourceFilterButton("x", "原帖级")}
          ${allSourceFilterButton("archive", "摘要归档")}
        </div>
      </div>
      <form class="all-search-row" id="all-search-form">
        <label>
          <span>类型</span>
          <select id="all-type-filter" aria-label="类型筛选">
            <option value="all" ${state.allTypeFilter === "all" ? "selected" : ""}>全部</option>
            <option value="risk" ${state.allTypeFilter === "risk" ? "selected" : ""}>风险</option>
            <option value="opportunity" ${state.allTypeFilter === "opportunity" ? "selected" : ""}>机会</option>
            <option value="competitor" ${state.allTypeFilter === "competitor" ? "selected" : ""}>样例竞品</option>
            <option value="summary" ${state.allTypeFilter === "summary" ? "selected" : ""}>摘要归档</option>
          </select>
        </label>
        <label class="all-search-field">
          <span>搜索</span>
          <input id="all-search-input" type="search" value="${escapeHtml(state.allSearchQuery)}" placeholder="搜索标题、中文正文、标签、作者…" />
        </label>
        <button class="text-button primary" type="submit">搜索</button>
      </form>
    </section>
    <section class="all-feed">
      <div class="section-header">
        <div>
          <h2>信息流</h2>
          <p class="muted">按日期与发布时间倒序排列。每条舆情保留明确原帖入口。</p>
        </div>
        <span class="tag">${filteredItems.length} 条</span>
      </div>
      ${filteredItems.length ? filteredGroups.filter((group) => group.items.length).map(allDateGroup).join("") : empty("暂无匹配舆情，请调整来源、类型或搜索词。")}
    </section>
  `;
}

function allSourceFilterButton(value, label) {
  return `
    <button class="filter-chip ${state.allBrandFilter === value ? "active" : ""}" type="button" data-all-source-filter="${escapeHtml(value)}">
      ${escapeHtml(label)}
    </button>
  `;
}

function allPageMetrics(allItems, filteredItems) {
  return {
    total: allItems.length,
    filtered: filteredItems.length,
    risk: filteredItems.filter((item) => item.kind === "risk").length,
    archiveDays: state.dailyArchive.length || 1,
  };
}

function allDateGroup(group) {
  const open = state.allExpandedDates.has(group.daily.date);
  const countLabel = group.daily.summary_only ? `${group.items.length} 条摘要` : `${group.items.length} 条`;
  return `
    <article class="all-date-group">
      ${timelineDateButton(group.daily.date, countLabel, open, "all")}
      ${open ? allTimeline(group) : ""}
    </article>
  `;
}

function timelineDateButton(date, countLabel, open, scope) {
  const attr = scope === "all" ? "data-all-date" : scope === "platform" ? "data-platform-date" : "data-featured-date";
  return `
    <button class="timeline-date-button" type="button" ${attr}="${escapeHtml(date)}">
      <span>${escapeHtml(formatDateShort(date))}</span>
      <em>${open ? "⌄" : "›"}</em>
      <strong>${escapeHtml(weekdayLabel(date))} · ${escapeHtml(countLabel)}</strong>
    </button>
  `;
}

function allTimeline(group) {
  if (!group.items.length) {
    return `<div class="featured-empty">${escapeHtml(group.daily.summary_only ? "该日摘要归档暂无匹配结果。" : "该日暂无匹配舆情。")}</div>`;
  }
  return `
    <div class="publish-timeline all-timeline">
      ${group.items.map(allTimelineCard).join("")}
    </div>
  `;
}

function allTimelineCard(item) {
  const body = allBodyText(item);
  return `
    <div class="publish-item all-feed-item">
      <div class="publish-time">${escapeHtml(item.timeLabel || formatEventTime(item.time))}</div>
      <div class="publish-line"><span></span></div>
      <article class="opinion-card all-card ${scoreClass(item)}">
        <div class="all-card-top">
          <div class="source-identity">
            ${avatarNode(item)}
            <div>
              <div class="source-line">
                ${authorNameNode(item, item.author_name || item.source_name || "Unknown source")}
                ${item.author_handle ? `<em>@${escapeHtml(item.author_handle)}</em>` : ""}
                ${sourceBadge(item.badge, item.brand === "temu" ? "competitor" : "focus")}
              </div>
              <div class="source-subline">${escapeHtml(item.source_subline)}${item.author_followers ? ` · ${escapeHtml(formatCompactNumber(item.author_followers))} followers` : ""}</div>
            </div>
          </div>
          <div class="all-score" aria-label="${escapeHtml(item.score_label)} ${escapeHtml(String(item.score_value ?? "n/a"))}">
            <span>${escapeHtml(String(item.score_value ?? "n/a"))}</span>
            <em>${escapeHtml(item.score_label)}</em>
          </div>
        </div>
        <div class="all-card-body">
          ${item.type === "summary" ? allTitleNode(item) : ""}
          ${postTextWithInlineLanguageToggle(item, body, "all-card-text", "all")}
          ${contextRelationNode(item)}
          ${mediaGridNode(item.media, item)}
          <div class="metric-inline card-metrics">
            ${metricInline("赞", item.post_metrics?.likes ?? item.metrics?.total_likes)}
            ${metricInline("评", item.post_metrics?.replies ?? item.metrics?.total_replies)}
            ${metricInline("转", item.post_metrics?.reposts ?? item.metrics?.total_reposts)}
            ${metricInline("引", item.post_metrics?.quotes ?? item.metrics?.total_quotes)}
            ${metricInline("收藏", item.post_metrics?.bookmarks ?? item.metrics?.total_bookmarks)}
            ${metricInline("浏览", item.post_metrics?.views ?? item.metrics?.total_views)}
          </div>
        </div>
        <div class="tag-row">${(item.tags || []).slice(0, 8).map((tag) => `<span class="plain-tag">#${escapeHtml(tag)}</span>`).join("")}</div>
        ${reasonLine(item, "compact")}
        <div class="all-card-bottom">
          ${cardFootnote(item.source_count_label, item)}
          <div class="button-row">
            ${allExternalLinkButton(item)}
          </div>
        </div>
      </article>
    </div>
  `;
}

function allTitleNode(item) {
  const title = allDisplayTitle(item);
  const externalUrl = item.is_sample ? "" : safeExternalUrl(item.external_href);
  if (externalUrl) return `<h3><a href="${escapeHtml(externalUrl)}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a></h3>`;
  return `<h3>${escapeHtml(title)}</h3>`;
}

function allBodyText(item) {
  const body = firstSourceText(item.body_zh, item.original_text, item.text, item.summary);
  const title = allDisplayTitle(item);
  if (body && !sameDisplayText(body, title)) return body;
  const fallback = firstSourceText(item.summary, item.summary_zh);
  if (fallback && !sameDisplayText(fallback, title)) return fallback;
  return "暂无原帖内容";
}

function allDisplayTitle(item) {
  const rawTitle = String(item.title || "").trim();
  const body = String(item.body_zh || item.summary || "").trim();
  if (rawTitle && /[\u3400-\u9fff]/.test(rawTitle) && !sameDisplayText(rawTitle, body)) {
    return truncateText(rawTitle, 54);
  }
  return generatedOpinionTitle(item);
}

function sameDisplayText(a, b) {
  const normalize = (value) => String(value || "").replace(/\s+/g, "").replace(/[，。,.!?！？:：；;]/g, "").toLowerCase();
  const left = normalize(a);
  const right = normalize(b);
  if (!left || !right) return false;
  return left === right || left.startsWith(right) || right.startsWith(left);
}

function generatedOpinionTitle(item) {
  const topic = opinionTopicLabel(item);
  if (item.type === "summary" || item.channel === "archive") {
    return item.brand === "temu" ? `样例竞品${topic}摘要` : `主品牌${topic}摘要`;
  }
  if (item.brand === "temu") return `样例竞品${topic}舆情`;
  if (item.kind === "opportunity") return `主品牌${topic}机会信号`;
  return `主品牌${topic}舆情`;
}

function opinionTopicLabel(item) {
  const labels = {
    positive_experience: "正向体验",
    product_deal: "商品导购",
    fulfillment_risk: "履约售后",
    trust_safety: "信任安全",
    competitor_comparison: "竞品对照",
    channel_activity: "渠道活动",
    company_market: "公司市场",
    general_observation: "日常观察",
    refund: "退款",
    payment: "支付",
    customer_service: "客服",
    delivery: "物流",
    shipping: "物流",
    order: "订单",
    fake: "虚假折扣",
    price: "价格",
    pricing: "价格",
    discount: "折扣",
    product: "商品",
    quality: "质量",
    regulatory: "监管",
    market_access: "市场准入",
    acquisition: "并购",
    positive: "正向",
    negative: "负面",
    neutral: "常规",
  };
  const tags = (item.tags || []).map((tag) => String(tag).toLowerCase()).filter(Boolean);
  const topicTags = tags.filter((tag) => !["竞品", "positive", "negative", "neutral"].includes(tag));
  const matched = topicTags.map((tag) => labels[tag]).find(Boolean);
  if (matched) return matched;
  const text = `${item.title || ""} ${item.body_zh || ""} ${item.summary || ""}`.toLowerCase();
  if (/客服|customer service|support|响应/.test(text)) return "客服";
  if (/物流|配送|包裹|delivery|shipping|parcel/.test(text)) return "物流";
  if (/退款|退货|refund|return/.test(text)) return "退款";
  if (/支付|付款|payment|pay/.test(text)) return "支付";
  if (/折扣|优惠|discount|coupon/.test(text)) return "折扣";
  if (/监管|欧盟|并购|收购|补贴|反垄断|regulator|regulatory|investigation|acquisition|takeover|ceconomy|subsid/.test(text)) return "监管";
  if (/价格|price|pricing/.test(text)) return "价格";
  if (/质量|损坏|quality|damaged/.test(text)) return "质量";
  if (item.sentiment === "positive") return "正向";
  if (item.sentiment === "negative") return "负面";
  return item.brand === "temu" ? "讨论" : "常规";
}

function allExternalLinkButton(item) {
  return cardExternalAction(item.external_href, item);
}

function allItemsForDaily(daily) {
  if (Array.isArray(daily.effective_posts) && daily.effective_posts.length) {
    return daily.effective_posts.map((post) => allItemFromEffectivePost(post, daily)).sort(compareEvents);
  }
  return [...allJoybuyItemsForDaily(daily), ...allCompetitorItemsForDaily(daily)].sort(compareEvents);
}

function allJoybuyItemsForDaily(daily) {
  return (daily.clusters || []).map((cluster) => allItemFromCluster(cluster, daily));
}

function allCompetitorItemsForDaily(daily) {
  const posts = daily.competitor?.top_posts || [];
  if (!posts.length && daily.competitor?.volume) {
    return [
      {
        id: `all-temu-summary-${daily.date}`,
        brand: "temu",
        channel: "archive",
        type: "summary",
        kind: "competitor",
        badge: "竞品",
        source_name: "样例竞品基线",
        author_name: "Competitor Radar",
        author_handle: "",
        source_subline: "摘要级归档",
        timeLabel: "汇总",
        title: `样例竞品当日有效声量 ${daily.competitor.volume}`,
        body_zh: "该日仅保留样例竞品声量与情绪摘要，原帖级竞品内容从完整日报归档后开始展示。",
        summary: "Competitor baseline summary",
        score_label: "声量",
        score_value: daily.competitor.volume,
        score: {},
        metrics: {},
        post_metrics: {},
        tags: sentimentTags(daily.competitor.sentiment),
        reason: "",
        source_count_label: "竞品摘要",
        is_sample: isDailySample(daily),
      },
    ];
  }
  return posts.map((post) => allItemFromCompetitorPost(post, daily));
}

function allItemFromEffectivePost(post, daily) {
  const metrics = post.metrics || {};
  const interactions = Number(metrics.likes || 0) + Number(metrics.reposts || 0) + Number(metrics.replies || 0) + Number(metrics.quotes || 0);
  const brand = post.brand === "temu" ? "temu" : "joybuy";
  const sentiment = post.sentiment || "neutral";
  const kind = brand === "temu" ? "competitor" : sentiment === "positive" ? "opportunity" : sentiment === "negative" ? "risk" : "observation";
  const tags = [sentiment, ...(post.matched_terms || [])].filter(Boolean);
  return {
    id: `all-effective-${daily.date}-${post.post_id || post.url || post.created_at}`,
    brand,
    channel: "x",
    type: kind,
    kind,
    topic: post.topic || "",
    badge: brand === "temu" ? "竞品" : "主品牌",
    source_name: brand === "temu" ? "样例竞品" : leadPostSourceName(post, "主品牌"),
    author_name: post.author_name || (brand === "temu" ? "样例竞品来源" : "主品牌来源"),
    author_handle: post.author_handle || "",
    author_avatar_url: post.author_avatar_url || "",
    author_followers: post.author_followers || 0,
    author_verified: post.author_verified || false,
    author_following: post.author_following || 0,
    author_bio: post.author_bio || post.author_description || "",
    author_location: post.author_location || "",
    author_joined_at: post.author_joined_at || "",
    source_subline: "公开原帖",
    time: post.created_at,
    title: generatedOpinionTitle({ brand, tags, topic: post.topic, sentiment, kind }),
    body_zh: sourcePostBody(post, post.summary_zh || ""),
    original_text: post.original_text || post.text || "",
    translation_status: post.translation_status || "unknown",
    summary: post.text || "",
    score: { level: post.level || "low", sentiment },
    score_label: post.score_label || (post.score_value == null ? "互动" : "IPS"),
    score_value: post.score_value ?? interactions,
    metrics: {},
    post_metrics: metrics,
    media: post.media || [],
    links: post.links || [],
    reply_to_post_id: post.reply_to_post_id || "",
    reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
    quoted_post_id: post.quoted_post_id || "",
    conversation_id: post.conversation_id || "",
    conversation_context: post.conversation_context || null,
    tags,
    reason: "",
    href: "",
    external_href: post.url || "",
    source_count: 1,
    source_count_label: brand === "temu" ? "竞品原帖" : "主品牌原帖",
    is_sample: isDailySample(daily),
    level: post.level || "low",
    sentiment,
  };
}

function allItemFromCluster(cluster, daily) {
  const score = cluster.score || {};
  const metrics = cluster.metrics || {};
  const count = Number(cluster.post_count || 1);
  const summaryOnly = Boolean(daily.summary_only);
  const post = leadPostFromCluster(cluster);
  const tags = [...(cluster.risk_types || []), ...(cluster.opportunity_types || []), cluster.topic].filter(Boolean);
  return {
    id: `all-${daily.date}-${cluster.cluster_id}`,
    brand: "joybuy",
    channel: summaryOnly ? "archive" : "x",
    type: summaryOnly ? "summary" : score.sentiment === "positive" ? "opportunity" : score.sentiment === "negative" ? "risk" : "observation",
    kind: score.sentiment === "positive" ? "opportunity" : score.sentiment === "negative" ? "risk" : "observation",
    badge: summaryOnly ? "摘要" : "主品牌",
    source_name: leadPostSourceName(post, "主品牌"),
    author_name: leadPostAuthorName(post, "主品牌"),
    author_handle: post.author_handle || post.author?.handle || "",
    author_avatar_url: post.author_avatar_url || post.author?.avatar_url || "",
    author_followers: post.author_followers ?? post.author?.followers ?? 0,
    author_verified: post.author_verified ?? post.author?.verified ?? false,
    author_following: post.author_following ?? post.author?.following ?? 0,
    author_bio: post.author_bio || post.author_description || post.author?.bio || post.author?.description || "",
    author_location: post.author_location || post.author?.location || "",
    author_joined_at: post.author_joined_at || post.author?.joined_at || "",
    source_subline: summaryOnly ? "历史摘要" : "公开原帖",
    time: post.created_at || cluster.first_seen_at || cluster.last_seen_at,
    title: generatedOpinionTitle({ brand: "joybuy", tags, topic: cluster.topic, sentiment: score.sentiment || "neutral", kind: score.sentiment === "positive" ? "opportunity" : "risk" }),
    body_zh: leadPostText(cluster),
    original_text: post.original_text || post.text || post.clean_text || "",
    translation_status: post.translation_status || "unknown",
    summary: cluster.summary || "",
    score,
    score_label: "IPS",
    score_value: score.ips ?? "n/a",
    metrics,
    post_metrics: post.metrics || {},
    media: post.media || [],
    links: post.links || [],
    reply_to_post_id: post.reply_to_post_id || "",
    reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
    quoted_post_id: post.quoted_post_id || "",
    conversation_id: post.conversation_id || "",
    conversation_context: post.conversation_context || null,
    tags,
    reason: score.explanation || cluster.tracking_reason || "",
    href: "",
    external_href: post.url || "",
    source_count: count,
    source_count_label: count > 1 ? `${count} 条同日相似讨论` : "1 条原帖",
    is_sample: isDailySample(daily),
    level: score.level || "low",
    sentiment: score.sentiment || "neutral",
    tracking_eligible: cluster.tracking_eligible,
  };
}

function allItemFromCompetitorPost(post, daily) {
  const metrics = post.metrics || {};
  const interactions = Number(metrics.likes || 0) + Number(metrics.reposts || 0) + Number(metrics.replies || 0) + Number(metrics.quotes || 0);
  return {
    id: `all-temu-${daily.date}-${post.post_id || post.url || post.created_at}`,
    brand: "temu",
    channel: "x",
    type: "competitor",
    kind: "competitor",
    badge: "竞品",
    source_name: "样例竞品",
    author_name: post.author_name || "样例竞品来源",
    author_handle: post.author_handle || "",
    author_avatar_url: post.author_avatar_url || "",
    author_followers: post.author_followers || 0,
    author_verified: post.author_verified || false,
    author_following: post.author_following || 0,
    author_bio: post.author_bio || post.author_description || "",
    author_location: post.author_location || "",
    author_joined_at: post.author_joined_at || "",
    source_subline: "公开原帖",
    time: post.created_at,
    title: "",
    body_zh: sourcePostBody(post, post.summary_zh || ""),
    original_text: post.original_text || post.text || "",
    translation_status: post.translation_status || "unknown",
    summary: post.text || "",
    score: { level: "low", sentiment: post.sentiment || "neutral" },
    score_label: "互动",
    score_value: interactions,
    metrics: {},
    post_metrics: metrics,
    media: post.media || [],
    links: post.links || [],
    reply_to_post_id: post.reply_to_post_id || "",
    reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
    quoted_post_id: post.quoted_post_id || "",
    conversation_id: post.conversation_id || "",
    conversation_context: post.conversation_context || null,
    tags: ["竞品", post.sentiment, ...(post.matched_terms || [])].filter(Boolean),
    reason: "",
    href: "",
    external_href: post.url || "",
    source_count: 1,
    source_count_label: "竞品原帖",
    is_sample: isDailySample(daily),
    level: "low",
    sentiment: post.sentiment || "neutral",
  };
}

function itemMatchesAllFilters(item) {
  if (state.allBrandFilter === "joybuy" && item.brand !== "joybuy") return false;
  if (state.allBrandFilter === "temu" && item.brand !== "temu") return false;
  if (state.allBrandFilter === "x" && item.channel !== "x") return false;
  if (state.allBrandFilter === "archive" && item.channel !== "archive") return false;
  if (state.allTypeFilter === "risk" && item.kind !== "risk") return false;
  if (state.allTypeFilter === "opportunity" && item.kind !== "opportunity") return false;
  if (state.allTypeFilter === "competitor" && item.kind !== "competitor") return false;
  if (state.allTypeFilter === "summary" && item.type !== "summary") return false;
  const query = String(state.allSearchQuery || "").trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    item.title,
    item.body_zh,
    item.summary,
    item.author_name,
    item.author_handle,
    item.source_name,
    item.source_subline,
    ...(item.tags || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function dailyPage() {
  const daily = state.selectedDaily || state.daily;
  const metrics = daily.metrics || state.overview.metrics;
  const source = daily.source_status || state.sourceStatus;
  const collection = daily.collection_status || {};
  const translation = collection.translation || daily.source_status?.translation || {};
  const joybuyEvents = buildJoybuyEvents(daily);
  const competitorEvents = buildCompetitorEvents(daily);
  const storyCount = joybuyEvents.length + competitorEvents.length;
  return `
    <div class="daily-layout report-layout daily-newspaper-layout">
      ${historyRail()}
      <article class="daily-report daily-paper">
        <header class="daily-masthead">
          <div class="daily-rule"></div>
          <div class="daily-kicker">
            <span>VOL.${escapeHtml(String(daily.date || "").replace(/-/g, "."))}</span>
            <span>${escapeHtml(String(storyCount))} STORIES</span>
            <span>BRAND OPINION DAILY</span>
          </div>
          <h2><span>Brand</span> 舆情日报</h2>
          <p>${escapeHtml(formatDateLong(daily.date))} · 每早八时更新</p>
          <div class="daily-masthead-stats">
            <span><strong>${escapeHtml(String(metrics.joybuy_volume || 0))}</strong><em>主品牌有效</em></span>
            <span><strong>${escapeHtml(String(metrics.temu_volume || 0))}</strong><em>竞品基线</em></span>
            <span><strong>${escapeHtml(String(metrics.high_risk || 0))}</strong><em>高风险</em></span>
            <span><strong>${escapeHtml(translationCoverageLabel(translation))}</strong><em>中文处理</em></span>
          </div>
        </header>
        ${sampleDataNotice(daily)}
        ${daily.summary_only ? `<div class="notice">该日报为摘要级归档：可查看当日指标与主题，原帖级内容从历史归档功能上线后开始保留。</div>` : ""}
        ${dailyBriefPanel(daily, joybuyEvents, competitorEvents)}
        <nav class="daily-toc" aria-label="报告目录">
          <div class="daily-toc-head">
            <div>
              <strong>报告目录</strong>
              <span>${escapeHtml(String(storyCount))} 条支撑舆情 · ${escapeHtml(daily.window_label || "Past 24 hours")}</span>
            </div>
          </div>
          <div class="report-toc">
            ${reportTocItem("01", "主品牌舆情", dailyIssueSummary(daily), joybuyEvents.length)}
            ${reportTocItem("02", "竞品雷达", "样例竞品当日声量、情绪和高互动内容。", competitorEvents.length)}
          </div>
        </nav>
        ${dailyReportSection("01", "主品牌舆情", "Brand Radar", `${brandBreakdown(source, "joybuy_effective", metrics.joybuy_volume)} 条有效内容，${metrics.high_risk || 0} 个高风险。`, "primary-radar", joybuyEvents, "该日暂无主品牌有效舆情")}
        ${dailyReportSection("02", "竞品雷达", "Competitor", `样例竞品有效内容 ${brandBreakdown(source, "temu_effective", metrics.temu_volume)} 条。`, "competitor-radar", competitorEvents, "该日暂无竞品内容", competitorSummary(daily.competitor || state.competitor))}
      </article>
    </div>
  `;
}

function dailyBriefPanel(daily, joybuyEvents, competitorEvents) {
  const brief = dailyBrief(daily, joybuyEvents, competitorEvents);
  return `
    <section class="daily-brief" aria-label="日报简报">
      <div class="daily-verdict">
        <span>日报结论</span>
        <h3>${escapeHtml(brief.title)}</h3>
        <p>${escapeHtml(brief.body)}</p>
        <div class="daily-verdict-tags">
          ${brief.badges.map((badge) => `<em class="${escapeHtml(badge.className)}">${escapeHtml(badge.label)}</em>`).join("")}
        </div>
      </div>
      <div class="daily-change-grid">
        ${dailyChangeCard("主品牌有效", brief.current.joybuy, brief.previous?.joybuy, "条")}
        ${dailyChangeCard("最高 IPS", brief.current.ips, brief.previous?.ips, "分")}
        ${dailyChangeCard("竞品基线", brief.current.temu, brief.previous?.temu, "条")}
        ${dailyChangeCard("高风险", brief.current.highRisk, brief.previous?.highRisk, "条", true)}
      </div>
      <div class="daily-action-board">
        ${dailyActionCard("处置优先级", brief.actionLabel, brief.actionCopy)}
        ${dailyActionCard("复核任务", brief.reviewLabel, brief.reviewCopy)}
        ${dailyActionCard("竞品观察", brief.competitorLabel, brief.competitorCopy)}
      </div>
    </section>
  `;
}

function dailyBrief(daily, joybuyEvents, competitorEvents) {
  const metrics = daily.metrics || {};
  const collection = daily.collection_status || {};
  const translation = collection.translation || daily.source_status?.translation || {};
  const previous = previousDailyIndexItem(daily.date);
  const current = {
    joybuy: Number(metrics.joybuy_volume ?? brandBreakdown(daily.source_status, "joybuy_effective", 0) ?? 0),
    temu: Number(metrics.temu_volume ?? brandBreakdown(daily.source_status, "temu_effective", 0) ?? 0),
    highRisk: Number(metrics.high_risk || 0),
    needsReview: Number(metrics.needs_review || 0),
    ips: topIps(daily),
    storyCount: joybuyEvents.length + competitorEvents.length,
    translationMissing: Number(translation.missing_count || 0) + Number(translation.fallback_original_count || 0),
  };
  const previousValues = previous
    ? {
        joybuy: Number(previous.joybuy_effective || 0),
        temu: Number(previous.temu_effective || 0),
        highRisk: Number(previous.high_risk || 0),
        needsReview: Number(previous.needs_review || 0),
        ips: Number(previous.ips || 0),
      }
    : null;
  const title = dailyBriefTitle(current);
  const body = dailyBriefBody(current, previousValues, daily);
  const action = dailyActionAdvice(current);
  const review = dailyReviewAdvice(current, collection);
  const competitor = dailyCompetitorAdvice(current, previousValues);
  const badges = [
    { label: action.label, className: action.className },
    { label: collection.status === "complete" ? "采集完整" : `采集${collection.status || "未知"}`, className: collection.status === "complete" ? "good" : "warn" },
    { label: current.translationMissing ? `翻译兜底 ${current.translationMissing}` : "中文覆盖完整", className: current.translationMissing ? "warn" : "good" },
  ];
  return {
    title,
    body,
    badges,
    current,
    previous: previousValues,
    actionLabel: action.label,
    actionCopy: action.copy,
    reviewLabel: review.label,
    reviewCopy: review.copy,
    competitorLabel: competitor.label,
    competitorCopy: competitor.copy,
  };
}

function dailyBriefTitle(current) {
  if (current.highRisk > 0) return "今日存在需优先复盘的风险舆情";
  if (current.needsReview > 0) return "今日舆情整体可控，但存在待复核内容";
  if (current.joybuy === 0) return "今日暂未发现有效主品牌舆情";
  if (current.ips >= 70) return "今日舆情平稳，但最高 IPS 需要持续观察";
  return "今日主品牌舆情整体平稳";
}

function dailyBriefBody(current, previous, daily) {
  const windowLabel = daily.window_label || "过去 24 小时";
  const joybuyTrend = previous ? `，较昨日${deltaPhrase(current.joybuy, previous.joybuy, "条")}` : "";
  const ipsText = current.ips ? `最高 IPS ${current.ips}` : "暂无 IPS 信号";
  const riskText = current.highRisk > 0 ? `识别到 ${current.highRisk} 条高风险` : "未识别到高风险";
  return `${windowLabel} 内，主品牌有效舆情 ${current.joybuy} 条${joybuyTrend}；${ipsText}，${riskText}。竞品基线 ${current.temu} 条，用于判断外部讨论热度。`;
}

function dailyActionAdvice(current) {
  if (current.highRisk > 0) {
    return { label: "立即复盘", className: "bad", copy: "优先打开高风险原帖，核对真实性、传播链路和是否需要客服/公关介入。" };
  }
  if (current.needsReview > 0) {
    return { label: "人工复核", className: "warn", copy: "先复核待确认内容的真实性，再决定是否进入处置或继续观察。" };
  }
  if (current.ips >= 70) {
    return { label: "重点观察", className: "warn", copy: "暂无明显风险，但最高 IPS 偏高，建议保留到下一日继续看传播变化。" };
  }
  if (current.joybuy === 0) {
    return { label: "无需动作", className: "good", copy: "当日未发现有效主品牌舆情，可保持自动监测。" };
  }
  return { label: "常规观察", className: "good", copy: "未出现高风险信号，建议按日报归档，下一轮继续观察趋势。" };
}

function dailyReviewAdvice(current, collection) {
  if (current.translationMissing > 0) {
    return { label: "检查译文", copy: `有 ${current.translationMissing} 条内容使用原文兜底，建议人工看一眼是否影响判断。` };
  }
  if (collection.request_budget_exhausted) {
    return { label: "采集受限", copy: "采集触达了保护阈值，本日报可能是部分结果，建议谨慎解读声量变化。" };
  }
  if (current.needsReview > 0) {
    return { label: `${current.needsReview} 条待复核`, copy: "优先核对低置信或潜在误匹配内容，避免把噪声带入汇报。" };
  }
  return { label: "暂无复核", copy: "采集与翻译状态正常，当前日报可直接作为日常归档参考。" };
}

function dailyCompetitorAdvice(current, previous) {
  const delta = previous ? current.temu - previous.temu : 0;
  if (current.temu >= Math.max(10, current.joybuy * 2)) {
    return { label: "竞品偏高", copy: `样例竞品当日声量 ${current.temu} 条，高于主品牌，可用于观察竞品讨论热度和话题类型。` };
  }
  if (previous && delta > 0) {
    return { label: "竞品上升", copy: `样例竞品较昨日增加 ${delta} 条，建议关注是否有可借鉴或需警惕的传播点。` };
  }
  return { label: "常规基线", copy: "样例竞品暂未出现异常跃升，作为竞品背景参考即可。" };
}

function dailyChangeCard(label, value, previous, suffix = "", reverseRisk = false) {
  const hasPrevious = previous != null && !Number.isNaN(Number(previous));
  const delta = hasPrevious ? Number(value || 0) - Number(previous || 0) : null;
  const trendClass = !hasPrevious || delta === 0 ? "flat" : delta > 0 ? (reverseRisk ? "bad" : "up") : (reverseRisk ? "good" : "down");
  return `
    <div class="daily-change-card ${trendClass}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value ?? 0))}${escapeHtml(suffix)}</strong>
      <em>${escapeHtml(hasPrevious ? deltaPhrase(value, previous, suffix) : "无昨日基准")}</em>
    </div>
  `;
}

function dailyActionCard(label, value, copy) {
  return `
    <div class="daily-action-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(copy)}</p>
    </div>
  `;
}

function previousDailyIndexItem(date) {
  const items = state.dailyIndex?.items || [];
  const index = items.findIndex((item) => item.date === date);
  if (index < 0) return null;
  return items[index + 1] || null;
}

function deltaPhrase(value, previous, suffix = "") {
  const delta = Number(value || 0) - Number(previous || 0);
  if (delta === 0) return "持平";
  return `${delta > 0 ? "+" : ""}${delta}${suffix}`;
}

function dailyReportSection(index, title, englishLabel, subtitle, id, events, emptyText, extra = "") {
  return `
    <section id="${escapeHtml(id)}" class="daily-section report-section">
      <header class="daily-section-head">
        <span>${escapeHtml(index)}</span>
        <div>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(englishLabel)} · ${escapeHtml(subtitle)}</p>
        </div>
        <strong>${escapeHtml(String(events.length))}</strong>
      </header>
      ${extra}
      ${dailyStoryList(events, emptyText)}
    </section>
  `;
}

function dailyStoryList(events, emptyText) {
  const sorted = [...events].sort(compareEvents);
  if (!sorted.length) return empty(emptyText);
  return `<div class="daily-story-list">${sorted.map(dailyStoryCard).join("")}</div>`;
}

function dailyStoryCard(event) {
  const title = localizedTitle(event.title, event.summary, event.brand === "temu" ? "竞品原帖" : "主品牌舆情信号");
  const body = String(event.summary || "").trim() || title;
  const showTitle = Boolean(event.isSummary || (!event.externalHref && title && !sameDisplayText(title, body)));
  const metrics = event.metrics || {};
  const likes = metrics.likes ?? metrics.total_likes;
  const replies = metrics.replies ?? metrics.total_replies;
  const reposts = metrics.reposts ?? metrics.total_reposts;
  const quotes = metrics.quotes ?? metrics.total_quotes;
  const views = metrics.views ?? metrics.total_views;
  const hasMetrics = [likes, replies, reposts, quotes, views].some((value) => value != null);
  return `
    <article class="daily-story-card">
      <div class="daily-story-top">
        <div class="daily-story-meta">
          <span>${escapeHtml(event.source)}</span>
          <span>${escapeHtml(event.timeLabel || formatEventTime(event.time))}</span>
        </div>
        ${event.scoreValue !== "n/a" ? `<div class="daily-story-score"><strong>${escapeHtml(String(event.scoreValue))}</strong><em>${escapeHtml(event.scoreLabel)}</em></div>` : ""}
      </div>
      ${showTitle ? `<h3>${storyTitleLink(event, title)}</h3>` : ""}
      ${postTextWithInlineLanguageToggle(event, body, "daily-story-text", "daily")}
      ${contextRelationNode(event)}
      ${mediaGridNode(event.media, event)}
      ${hasMetrics ? `<div class="metric-inline card-metrics">
        ${metricInline("赞", likes)}
        ${metricInline("评", replies)}
        ${metricInline("转", reposts)}
        ${metricInline("引", quotes)}
        ${metricInline("浏览", views)}
      </div>` : ""}
      <div class="tag-row">${(event.tags || []).slice(0, 6).map((tag) => `<span class="plain-tag">#${escapeHtml(tag)}</span>`).join("")}</div>
      ${reasonLine(event, "compact")}
      <div class="button-row daily-story-actions">
        ${event.externalHref ? externalLinkButton(event.externalHref, "在 X 查看原帖", "", { isSample: event.is_sample }) : ""}
      </div>
    </article>
  `;
}

function storyTitleLink(event, title = event.title) {
  if (!event.href || (event.external && event.is_sample)) return escapeHtml(title);
  if (event.external) {
    const url = safeExternalUrl(event.href);
    return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title);
  }
  return `<a href="${escapeHtml(event.href)}">${escapeHtml(title)}</a>`;
}

function historyRail() {
  const history = state.dailyIndex?.items || [];
  const groups = dailyHistoryMonthGroups(history);
  return `
    <aside class="daily-history">
      <div class="daily-history-current">
        <span>当前日报</span>
        <strong>${escapeHtml(formatDateLong((state.selectedDaily || state.daily).date))}</strong>
      </div>
      <div class="daily-history-head">
        <h2>日报历史</h2>
        <span class="tag">${history.length} 天</span>
      </div>
      <div class="daily-history-list">
        ${groups.map(dailyHistoryMonthGroup).join("") || empty("暂无历史日报")}
      </div>
    </aside>
  `;
}

function dailyHistoryMonthGroups(history) {
  const groups = [];
  for (const item of history) {
    const key = dailyMonthKey(item.date);
    let group = groups.find((entry) => entry.key === key);
    if (!group) {
      group = { key, label: formatDateMonth(item.date), items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

function dailyHistoryMonthGroup(group) {
  return `
    <section class="daily-history-month">
      <div class="daily-history-month-head">
        <span aria-hidden="true">⌄</span>
        <strong>${escapeHtml(group.label)}</strong>
        <em>${escapeHtml(String(group.items.length))}</em>
      </div>
      <div class="daily-history-month-list">
        ${group.items.map(dailyHistoryItem).join("")}
      </div>
    </section>
  `;
}

function dailyMonthKey(date) {
  const parts = String(date || "").split("-");
  if (parts.length < 2) return "unknown";
  return `${parts[0]}-${parts[1]}`;
}

function dailyHistoryItem(item) {
  const active = item.date === (state.selectedDaily || state.daily).date;
  return `
    <button class="daily-history-item ${active ? "active" : ""}" data-daily-date="${escapeHtml(item.date)}">
      <span class="daily-date">${formatDateDay(item.date)} 日</span>
      <span class="daily-title">${escapeHtml(dailyHistoryTitle(item))}</span>
      <span class="daily-meta">${dailyHistoryMeta(item)}</span>
    </button>
  `;
}

function dailyHistoryMeta(item) {
  const parts = [
    `竞品 ${item.temu_effective ?? 0}`,
    collectionStateLabel(item.collection_status || "unknown"),
  ];
  if (item.summary_only) parts.push("摘要归档");
  return parts.map((part) => escapeHtml(String(part))).join(" · ");
}

function settingsPage() {
  const source = state.sourceStatus || {};
  const collection = state.daily?.collection_status || {};
  const brand = source.brand_breakdown || {};
  const translation = collection.translation || source.translation || {};
  return `
    ${pageHero({
      eyebrow: "系统状态",
      subtitle: "公开展示仅保留运行状态、数据质量与评分口径",
      stats: [
        [sourceModeLabel(source.status), "数据状态"],
        [collectionStateLabel(collection.status || state.overview.health), "采集状态"],
        [translationCoverageLabel(translation), "中文处理"],
        [source.effective_posts ?? 0, "有效内容"],
      ],
    })}
    ${sampleDataNotice(state.daily)}
    <section class="settings-layout">
      <div class="settings-main">
        <section class="settings-card">
          <div class="settings-card-head">
            <div>
              <h2>采集运行</h2>
              <p class="muted">最近一次数据更新与运行健康度。</p>
            </div>
            <span class="status-pill ${escapeHtml(source.status || "neutral")}">${escapeHtml(sourceModeLabel(source.status))}</span>
          </div>
          <div class="status-table">
            ${statusRow("最近生成", state.overview.generated_at_label || formatDateTime(state.overview.generated_at))}
            ${statusRow("统计窗口", "最近 24 小时")}
            ${statusRow("更新节奏", "每日自动更新")}
            ${statusRow("运行状态", collectionStateLabel(collection.status || state.overview.health))}
          </div>
        </section>
        <section class="settings-card">
          <div class="settings-card-head">
            <div>
              <h2>数据质量</h2>
              <p class="muted">本次进入清洗、去重、翻译和评分链路的数据量。</p>
            </div>
          </div>
          <div class="quality-grid">
            ${qualityTile("原始采集", source.raw_posts_collected ?? 0, "源端返回内容")}
            ${qualityTile("有效内容", source.effective_posts ?? 0, "过滤误匹配后")}
            ${qualityTile("主品牌", `${brand.joybuy_candidates ?? 0} → ${brand.joybuy_effective ?? 0}`, "候选到有效")}
            ${qualityTile("竞品基线", `${brand.temu_candidates ?? 0} → ${brand.temu_effective ?? 0}`, "候选到有效")}
          </div>
        </section>
        <section class="settings-card">
          <div class="settings-card-head">
            <div>
              <h2>评分体系</h2>
              <p class="muted">列表页只展示结果分，完整口径统一放在这里。</p>
            </div>
          </div>
          ${scoreSystemPanel()}
        </section>
      </div>
      <aside class="settings-side">
        <section class="settings-card">
          <div class="settings-card-head">
            <div>
              <h2>监控范围</h2>
              <p class="muted">公开页只展示能力范围，不展示具体监控配置。</p>
            </div>
          </div>
          <div class="scope-list">
            ${scopeRow("数据范围", "公开社媒内容")}
            ${scopeRow("主品牌", "主品牌词库")}
            ${scopeRow("区域策略", "多市场关键词组")}
            ${scopeRow("竞品", "竞品基线")}
          </div>
        </section>
        <section class="settings-card">
          <div class="settings-card-head">
            <div>
              <h2>安全边界</h2>
              <p class="muted">公开页只展示原则，不展示密钥、服务商或内部阈值。</p>
            </div>
          </div>
          <div class="rule-list">
            <span>敏感凭据仅保存在受控密钥环境，不进入公开仓库或静态页面</span>
            <span>公开页面只发布可展示的聚合结果，不暴露内部服务商与密钥字段</span>
            <span>自动任务设有运行保护阈值，具体阈值不在公开页面展示</span>
            ${(source.notes || []).map((note) => `<span>${escapeHtml(settingsNoteText(note))}</span>`).join("")}
          </div>
        </section>
      </aside>
    </section>
  `;
}

function scoreSystemPanel() {
  const dimensions = [
    ["品牌相关度", "是否真正与主品牌或指定竞品相关，过滤同名误伤与无关语境。"],
    ["风险/机会强度", "判断内容是投诉风险、传播机会，还是普通日常提及。"],
    ["当前传播影响", "基于赞、评、转、引、浏览、作者影响力等公开信号评估。"],
    ["未来传播潜力", "结合敏感主题、二次传播可能性、高影响力账号参与概率判断。"],
    ["真实性/可靠性", "看是否来自原始发帖、是否有具体事实、是否存在明显营销或误匹配。"],
    ["业务影响", "衡量对履约、售后、价格心智、品牌信任、竞品参照的业务价值。"],
    ["紧急程度", "判断是否需要当天人工复核、PR 准备、管理层同步或继续观察。"],
  ];
  return `
    <div class="score-system">
      <div class="score-formula">
        <strong>IPS</strong>
        <span>综合优先级分 = 各维度加权分 + 发酵加分，范围 0-100。</span>
      </div>
      <div class="score-formula">
        <strong>CSI</strong>
        <span>竞品信号分更偏观察价值，用于判断样例竞品内容是否值得进入焦点。</span>
      </div>
      <div class="score-dimension-grid">
        ${dimensions.map(([title, copy]) => `<div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></div>`).join("")}
      </div>
      <p class="muted">分数用于排序和筛选，不替代人工判断；高分内容应结合原帖、上下文和业务背景复核。</p>
    </div>
  `;
}

function topicDisplayName(topic) {
  const labels = {
    positive_experience: "正向购物体验",
    product_deal: "商品/促销/上架信息",
    fulfillment_risk: "履约与售后风险",
    trust_safety: "信任与安全",
    competitor_comparison: "竞品对照与替代选择",
    channel_activity: "品牌合作与渠道动态",
    company_market: "公司/资本市场信息",
    general_observation: "日常观察",
    refund: "退款与支付",
    delivery: "物流与包裹追踪",
    customer_service: "客服与售后",
    regulatory: "监管与并购审查",
    price_opportunity: "价格与配送优势",
    general: "品牌认知",
  };
  return labels[topic] || String(topic || "主品牌");
}

function sourceModeLabel(status) {
  if (status === "sample") return "样例";
  if (status === "normal") return "真实";
  if (status === "complete") return "真实";
  if (status === "partial") return "部分";
  if (status === "ok") return "正常";
  return status || "未知";
}

function collectionStateLabel(status) {
  if (status === "complete" || status === "normal") return "完整";
  if (status === "partial") return "部分";
  if (status === "sample") return "样例";
  if (status === "archived-summary") return "摘要归档";
  if (status === "ok") return "正常";
  return status || "未知";
}

function translationCoverageLabel(translation = {}) {
  const missing = Number(translation.missing_count || 0) + Number(translation.fallback_original_count || 0);
  if (missing > 0) return `兜底 ${missing}`;
  const counts = translation.counts || {};
  const translated = Number(counts.translated || 0) + Number(counts.provider_supplied || 0);
  const source = Number(counts.source_chinese || 0);
  if (translated || source) return "完整";
  return "未启用";
}

function formatCost(value) {
  const number = Number(value || 0);
  if (!number) return "0";
  return number.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function statusRow(label, value) {
  return `<div class="status-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value ?? "--"))}</strong></div>`;
}

function qualityTile(label, value, note) {
  return `
    <div class="quality-tile">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
      <em>${escapeHtml(note)}</em>
    </div>
  `;
}

function scopeRow(label, value) {
  return `<div class="scope-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function settingsNoteText(note) {
  const text = String(note || "");
  if (text.includes("Sample provider")) return "样例数据模式开启时，仅用于页面结构与交互预览";
  if (text.includes("Bookmarks")) return "收藏数仅在数据源提供时展示";
  if (text.includes("Quote")) return "引用数作为公开传播信号纳入发酵判断";
  if (text.includes("Public social data collection")) return "公开内容采集已启用，建议结合去重率和误匹配率解读声量";
  if (text.includes("Chinese translation coverage")) return "中文处理覆盖完整";
  if (text.includes("Chinese translation unavailable")) return "部分内容使用原文兜底，建议人工复核";
  return text;
}

async function renderDetail(clusterId) {
  window.location.hash = "#/";
}

function detailPage(detail) {
  const detailSample = isDetailSample(detail);
  const leadPost = representativeDetailPost(detail);
  const leadItem = itemFromDetailPost(leadPost, "公开舆情");
  const title = localizedTitle(detail.title, detail.summary_zh, "舆情事件");
  const posts = detail.posts || [];
  const tags = [...(detail.risk_types || []), ...(detail.opportunity_types || []), detail.topic].filter(Boolean);
  return `
    <article class="detail-page read-detail">
      ${sampleDataNotice()}
      <section class="readtop">
        <div class="readtop-main">
          <div class="source-identity">
            ${avatarNode(leadItem)}
            <div>
              <div class="source-line">
                ${authorNameNode(leadItem, leadItem.author_name || "X Source")}
                ${leadItem.author_handle ? `<em>@${escapeHtml(leadItem.author_handle)}</em>` : ""}
                ${sourceBadge(levelText(detail.score), "focus")}
              </div>
              <div class="source-subline">公开舆情${leadItem.author_followers ? ` · ${escapeHtml(formatCompactNumber(leadItem.author_followers))} followers` : ""}</div>
            </div>
          </div>
          <div class="readtop-meta">
            <span>${escapeHtml(formatDateTime(leadPost?.created_at || detail.first_seen_at))}</span>
            <span>${escapeHtml(relativeMonitorLabel(detail))}</span>
          </div>
          <div class="readtop-link-row">
            ${externalLinkButton(leadPost?.url, "在 X 看原帖", "", { isSample: detailSample })}
            <span class="muted">· ${escapeHtml(sourceHostLabel(leadPost?.url || "x.com"))}</span>
          </div>
        </div>
        <div class="readtop-actions">
          <span class="read-badge">${escapeHtml(detail.score.recommended_action || "持续监测")}</span>
          <div class="read-score"><span>${escapeHtml(String(detail.score.ips))}</span><em>IPS</em></div>
        </div>
      </section>

      ${detailReasonCard(detail, leadItem, leadPost)}

      <section class="read-card">
        <div class="read-card-label">舆情摘要</div>
        <p>${escapeHtml(detail.summary_zh || chineseSignalText(leadItem))}</p>
      </section>

      <section class="read-body">
        <div class="read-section-title">
          <span>${escapeHtml(detailBodyLabel(leadItem, state.detailLanguage))}</span>
          <div class="read-lang-toggle">
            <button class="${state.detailLanguage === "zh" ? "active" : ""}" type="button" data-detail-lang="zh">中文</button>
            <button class="${state.detailLanguage === "original" ? "active" : ""}" type="button" data-detail-lang="original">原文</button>
          </div>
        </div>
        ${detailPrimaryPostCard(leadPost, state.detailLanguage)}
        ${relatedPostStrip(detail, state.detailLanguage, detailSample)}
        <div class="read-tags">
          ${tags.slice(0, 8).map((tag) => `<span>#${escapeHtml(tag)}</span>`).join("")}
        </div>
        ${externalLinkButton(leadPost?.url, "在 X 查看原帖", "read-cta", { isSample: detailSample })}
      </section>

      <section class="read-card read-status-card">
        <div class="read-card-label">发酵状态</div>
        <div class="summary-stack compact">
          ${summaryLine("状态", detail.fermentation.status || "持续观察")}
          ${(detail.fermentation.signals || []).map((signal) => summaryLine("信号", signal)).join("") || empty("暂无升温信号")}
        </div>
      </section>

      <section class="read-card">
        <div class="read-card-label with-info">
          <span>评分拆解</span>
          <span class="info-dot" tabindex="0" aria-label="IPS 计算说明" data-tooltip="IPS = 各维度分 × 权重后求和，再叠加发酵加分">i</span>
        </div>
        ${scoreContributionPanel(detail)}
      </section>
    </article>
  `;
}

function detailInsightReason(detail, leadItem, leadPost) {
  const item = {
    ...leadItem,
    brand: "joybuy",
    body_zh: chineseSignalText(leadItem),
    summary: detail.summary_zh || detail.summary,
    score: detail.score,
    score_value: detail.score?.ips,
    metrics: detail.metrics || {},
    post_metrics: leadPost?.metrics || {},
    author_followers: leadItem.author_followers,
    source_count: detail.post_count || detail.posts?.length || 1,
    tags: [...(detail.risk_types || []), ...(detail.opportunity_types || []), detail.topic].filter(Boolean),
    reason: detail.score_explanation,
  };
  return insightReason(item, detail.score_explanation || detail.summary_zh || "");
}

function detailReasonCard(detail, leadItem, leadPost) {
  const reason = detailInsightReason(detail, leadItem, leadPost);
  if (!reason) return "";
  return `
      <section class="read-card">
        <div class="read-card-label">关注原因</div>
        <p>${escapeHtml(reason)}</p>
      </section>
  `;
}

function isDetailSample(detail) {
  if (typeof detail?.is_sample === "boolean") return detail.is_sample;
  const clusterId = detail?.cluster_id;
  if (clusterId) {
    for (const daily of state.dailyArchive || []) {
      const matched = (daily.clusters || []).some((cluster) => cluster.cluster_id === clusterId);
      if (matched) return isDailySample(daily);
    }
  }
  return isDailySample(state.selectedDaily || state.daily);
}

function formatDateTime(iso) {
  if (!iso) return "--";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "--";
  return value.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
}

function relativeMonitorLabel(detail) {
  const count = Number(detail.post_count || detail.posts?.length || 0);
  const status = detail.fermentation?.status || "观察中";
  return `${count} 条同日相似讨论 · ${status}`;
}

function sourceHostLabel(url) {
  const safeUrl = safeExternalUrl(url);
  if (!safeUrl) return "原帖链接不可用";
  try {
    return new URL(safeUrl).host.replace(/^www\./, "");
  } catch (error) {
    return "原帖链接不可用";
  }
}

function representativeDetailPost(detail) {
  const posts = detail.posts || [];
  if (!posts.length) return null;
  return [...posts].sort((a, b) => publicInteractionScore(b.metrics) - publicInteractionScore(a.metrics))[0];
}

function itemFromDetailPost(post, fallbackSource) {
  const author = post?.author || {};
  return {
    author_name: author.name || post?.author_name || post?.author_handle || fallbackSource,
    author_handle: author.handle || post?.author_handle || "",
    author_avatar_url: author.avatar_url || post?.author_avatar_url || "",
    author_followers: author.followers || post?.author_followers || 0,
    translation_zh: post?.translation_zh || post?.summary_zh || "",
    translation_status: post?.translation_status || "unknown",
    original_text: post?.text || post?.clean_text || "",
    links: post?.links || [],
    media: post?.media || [],
    url: post?.url || post?.post_url || "",
    post_url: post?.url || post?.post_url || "",
    post_id: post?.post_id || post?.id || "",
  };
}

function publicInteractionScore(metrics = {}) {
  return Number(metrics.likes || 0) + Number(metrics.reposts || 0) + Number(metrics.replies || 0) + Number(metrics.quotes || 0);
}

function levelText(score = {}) {
  return { urgent: "紧急", high: "高风险", medium: "中风险", low: "低风险" }[score.level] || "监测";
}

function detailPrimaryPostCard(post, language = state.detailLanguage) {
  if (!post) return empty("暂无可展示原帖");
  const metrics = post.metrics || {};
  return `
    <article class="read-source-content">
      ${richPostTextNode(itemFromDetailPost(post, "X Source"), postTextForLanguage(post, language), "detail-source-text")}
      ${mediaGridNode(post.media, itemFromDetailPost(post, "X Source"))}
      <div class="metric-inline read-metrics">
        ${metricInline("赞", metrics.likes)}
        ${metricInline("评", metrics.replies)}
        ${metricInline("转", metrics.reposts)}
        ${metricInline("引", metrics.quotes)}
        ${metricInline("收藏", metrics.bookmarks)}
        ${metricInline("浏览", metrics.views)}
      </div>
    </article>
  `;
}

function relatedPostStrip(detail, language = state.detailLanguage, isSample = isDetailSample(detail)) {
  const posts = (detail.posts || []).slice(0, 8);
  const labelsByPost = evidenceLabelsByPost(detail);
  const related = posts.slice(0, 6);
  if (!related.length) return "";
  return `
    <div class="related-source-strip">
      <div class="block-heading"><span>关联讨论</span><em>${escapeHtml(String(related.length))} 条展示</em></div>
      <div class="related-source-list">
        ${related.map((post) => relatedPostChip(post, labelsByPost[post.post_id || post.id] || [], language, isSample)).join("")}
      </div>
    </div>
  `;
}

function relatedPostChip(post, labels = [], language = state.detailLanguage, isSample = false) {
  const item = itemFromDetailPost(post, "X Source");
  const metrics = post.metrics || {};
  const text = postTextForLanguage(post, language);
  const content = `
    <div class="related-source-head">
      <div>
        <span>${escapeHtml(item.author_handle ? `@${item.author_handle}` : item.author_name)}</span>
        <em>${escapeHtml(formatDateTime(post.created_at))}</em>
      </div>
      <div class="related-source-actions">
        ${sourceLabelBadges(labels)}
        ${relatedPostLink(post.url, isSample)}
      </div>
    </div>
    ${richPostTextNode(item, text || "暂无正文", "related-source-text")}
    <div class="related-source-metrics">
      ${metricInline("赞", metrics.likes)}
      ${metricInline("评", metrics.replies)}
      ${metricInline("转", metrics.reposts)}
      ${metricInline("引", metrics.quotes)}
      ${metricInline("收藏", metrics.bookmarks)}
      ${metricInline("浏览", metrics.views)}
    </div>
  `;
  return `<article class="related-source-chip ${isSample ? "disabled" : ""}">${content}</article>`;
}

function relatedPostLink(href, isSample = false) {
  if (isSample) {
    return `<span class="related-source-link disabled" title="样例数据不提供真实 X 跳转">样本不跳转</span>`;
  }
  const url = safeExternalUrl(href);
  if (!url) {
    return `<span class="related-source-link disabled">无原帖链接</span>`;
  }
  return `<a class="related-source-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">在 X 查看</a>`;
}

function postTextForLanguage(post, language = state.detailLanguage) {
  const item = itemFromDetailPost(post, "X Source");
  if (language === "original") return item.original_text || item.translation_zh || "";
  return item.translation_zh || item.original_text || "";
}

function evidenceLabelsByPost(detail) {
  const labels = {};
  const labelOrder = {
    origin: "热源",
    stakeholders: "当事人",
    popular: "热门",
    amplifiers: "扩散源",
    latest: "最新",
  };
  Object.entries(labelOrder).forEach(([key, label]) => {
    (detail.evidence_chain?.[key] || []).forEach((item) => {
      if (!item.post_id) return;
      labels[item.post_id] ||= [];
      if (!labels[item.post_id].includes(label)) labels[item.post_id].push(label);
    });
  });
  return labels;
}

function sourceLabelBadges(labels) {
  if (!labels.length) return "";
  return `<div class="source-labels">${labels.slice(0, 3).map((label) => `<span>${escapeHtml(label)}</span>`).join("")}</div>`;
}

function buildDailyEvents(daily) {
  return [...buildJoybuyEvents(daily), ...buildCompetitorEvents(daily)].sort(compareEvents);
}

function buildJoybuyEvents(daily) {
  const dailySample = isDailySample(daily);
  return (daily.clusters || []).map((cluster) => clusterToEvent(cluster, "joybuy", "主品牌", dailySample));
}

function buildCompetitorEvents(daily) {
  const competitor = daily.competitor || state.competitor || {};
  const posts = competitor.top_posts || [];
  const dailySample = isDailySample(daily);
  if (!posts.length && competitor.volume) {
    return [
      {
        brand: "temu",
        source: "样例竞品基线",
        title: `样例竞品当日有效声量 ${competitor.volume}`,
        summary: "摘要级归档仅保留当日声量与情绪分布，原帖级竞品内容从历史归档功能上线后开始保留。",
        scoreLabel: "声量",
        scoreValue: competitor.volume,
        timeLabel: "汇总",
        tags: sentimentTags(competitor.sentiment),
        reason: "",
        is_sample: dailySample,
        isSummary: true,
      },
    ];
  }
  return posts.map((post) => {
    const interactions = Number(post.metrics?.likes || 0) + Number(post.metrics?.reposts || 0) + Number(post.metrics?.replies || 0) + Number(post.metrics?.quotes || 0);
    const body = sourcePostBody(post, post.summary_zh || "");
    return {
      brand: "temu",
      source: `样例竞品 · @${post.author_handle || "unknown"}`,
      author_name: post.author_name || "样例竞品来源",
      author_handle: post.author_handle || "",
      author_avatar_url: post.author_avatar_url || "",
      author_followers: post.author_followers || 0,
      author_verified: post.author_verified || false,
      author_following: post.author_following || 0,
      author_bio: post.author_bio || post.author_description || "",
      author_location: post.author_location || "",
      author_joined_at: post.author_joined_at || "",
      title: "",
      summary: body,
      originalText: post.original_text || post.text || "",
      translation_status: post.translation_status || "unknown",
      scoreLabel: "互动",
      scoreValue: interactions,
      time: post.created_at,
      tags: [post.sentiment, ...(post.matched_terms || [])].filter(Boolean),
      href: post.url,
      externalHref: post.url,
      external: true,
      reason: "",
      metrics: post.metrics,
      media: post.media || [],
      links: post.links || [],
      reply_to_post_id: post.reply_to_post_id || "",
      reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
      quoted_post_id: post.quoted_post_id || "",
      conversation_id: post.conversation_id || "",
      conversation_context: post.conversation_context || null,
      is_sample: dailySample,
    };
  });
}

function clusterToEvent(cluster, brand, source, isSample = false) {
  const post = leadPostFromCluster(cluster);
  const tags = [...(cluster.risk_types || []), ...(cluster.opportunity_types || []), cluster.topic].filter(Boolean);
  return {
    brand,
    source: leadPostSourceName(post, source),
    title: generatedOpinionTitle({ brand, tags, topic: cluster.topic, sentiment: cluster.score?.sentiment || "neutral" }),
    summary: leadPostText(cluster),
    originalText: post.original_text || post.text || post.clean_text || "",
    author_name: post.author_name || post.author?.name || "",
    author_handle: post.author_handle || post.author?.handle || "",
    author_avatar_url: post.author_avatar_url || post.author?.avatar_url || "",
    author_followers: post.author_followers ?? post.author?.followers ?? 0,
    author_following: post.author_following ?? post.author?.following ?? 0,
    author_bio: post.author_bio || post.author_description || post.author?.bio || post.author?.description || "",
    scoreLabel: "IPS",
    scoreValue: cluster.score?.ips ?? "n/a",
    time: post.created_at || cluster.first_seen_at || cluster.last_seen_at,
    tags,
    href: "",
    externalHref: post.url || "",
    links: post.links || [],
    reply_to_post_id: post.reply_to_post_id || "",
    reply_to_handle: post.reply_to_handle || post.in_reply_to_screen_name || "",
    quoted_post_id: post.quoted_post_id || "",
    conversation_id: post.conversation_id || "",
    conversation_context: post.conversation_context || null,
    reason: cluster.score?.explanation || cluster.tracking_reason || "",
    score: cluster.score,
    fermentation: cluster.fermentation,
    postCount: cluster.post_count,
    metrics: post.metrics || cluster.metrics,
    isSummary: !post.url,
    is_sample: isSample,
  };
}

function compareEvents(a, b) {
  const aTime = a.time ? new Date(a.time).getTime() : 0;
  const bTime = b.time ? new Date(b.time).getTime() : 0;
  return bTime - aTime;
}

function publishTimeline(date, events, emptyText) {
  const sorted = [...events].sort(compareEvents);
  if (!sorted.length) return empty(emptyText);
  return `
    <div class="timeline-date-heading">
      <h3>${formatDateShort(date)}</h3>
      <span class="muted">${weekdayLabel(date)} · ${sorted.length} 条</span>
    </div>
    <div class="publish-timeline">
      ${sorted.map(timelineCard).join("")}
    </div>
  `;
}

function timelineCard(event) {
  return `
    <div class="publish-item">
      <div class="publish-time">${escapeHtml(event.timeLabel || formatEventTime(event.time))}</div>
      <div class="publish-line"><span></span></div>
      <article class="publish-card">
        <div class="publish-source">
          <span>${escapeHtml(event.source)}</span>
          ${event.scoreValue !== "n/a" ? `<span class="tag">${escapeHtml(event.scoreLabel)} ${escapeHtml(String(event.scoreValue))}</span>` : ""}
        </div>
        <h3>${escapeHtml(event.title)}</h3>
        ${richPostTextNode(event, event.summary, "publish-card-text muted")}
        <div class="tag-row">${(event.tags || []).slice(0, 6).map((tag) => `<span class="plain-tag">#${escapeHtml(tag)}</span>`).join("")}</div>
        ${reasonLine(event)}
        ${event.href && event.external ? `<div class="button-row">${externalLinkButton(event.href, "查看原帖", "primary", { isSample: event.is_sample })}</div>` : ""}
      </article>
    </div>
  `;
}

function featureCard(event) {
  return `
    <article class="intel-card">
      <div class="card-top">
        <div class="card-title">
          <div class="publish-source"><span>${escapeHtml(event.source)}</span></div>
          <h3>${escapeHtml(event.title)}</h3>
          <p class="muted">${escapeHtml(event.summary)}</p>
        </div>
        <div class="score-badge"><div class="score-number">${escapeHtml(String(event.scoreValue))}</div><div class="score-label">${escapeHtml(event.scoreLabel)}</div></div>
      </div>
      <div class="tag-row">${(event.tags || []).slice(0, 5).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    </article>
  `;
}

function reportTocItem(index, title, summary, count) {
  const target = index === "01" ? "primary-radar" : "competitor-radar";
  return `
    <button class="toc-card" type="button" data-scroll-target="${target}">
      <span>${escapeHtml(index)}</span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(summary)}</p>
      <em>${escapeHtml(String(count))}</em>
    </button>
  `;
}

function competitorSummary(competitor) {
  const sentiment = competitor?.sentiment || {};
  return `
    <div class="metric-grid compact three">
      ${metric("竞品声量", competitor?.volume || 0, "竞品有效内容")}
      ${metric("负面", sentiment.negative || 0, "轻量情绪判断")}
      ${metric("正面", sentiment.positive || 0, "轻量情绪判断")}
    </div>
  `;
}

function dailyIssueSummary(daily) {
  const metrics = daily.metrics || {};
  const highRisk = Number(metrics.high_risk || 0);
  const needsReview = Number(metrics.needs_review || 0);
  const topIpsValue = topIps(daily);
  if (highRisk > 0) return `当日识别 ${highRisk} 条高风险舆情，最高 IPS ${topIpsValue}，建议优先复盘原帖证据。`;
  if (needsReview > 0) return `当日有 ${needsReview} 条舆情需要人工复核，建议关注真实性和潜在扩散。`;
  const joybuyVolume = Number(metrics.joybuy_volume || 0);
  if (joybuyVolume > 0) return `当日主品牌有效舆情 ${joybuyVolume} 条，整体以常规监测和历史归档为主。`;
  return "当日暂未发现达到有效阈值的主品牌舆情。";
}

function dailyHistoryTitle(item) {
  const highRisk = Number(item.high_risk || 0);
  const needsReview = Number(item.needs_review || 0);
  const joybuy = Number(item.joybuy_effective || 0);
  const ips = item.ips ? ` · IPS ${item.ips}` : "";
  if (highRisk > 0) return `高风险 ${highRisk} 条${ips}`;
  if (needsReview > 0) return `待复核 ${needsReview} 条${ips}`;
  if (joybuy > 0) return `主品牌 ${joybuy} 条${ips}`;
  return "暂无有效舆情";
}

function sentimentTags(sentiment = {}) {
  return Object.entries(sentiment)
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}:${value}`);
}

function topIps(daily) {
  const scores = (daily.clusters || []).map((cluster) => Number(cluster.score?.ips || 0));
  return Math.max(0, ...scores);
}

function formatDailyTitle(daily) {
  if (!daily?.date) return "过去 24 小时情报";
  return `${daily.date} 日报`;
}

function formatDateShort(date) {
  if (!date) return "--";
  const parts = String(date).split("-");
  if (parts.length !== 3) return date;
  return `${Number(parts[1])}月${Number(parts[2])}日`;
}

function formatDateMonth(date) {
  if (!date) return "--";
  const parts = String(date).split("-");
  if (parts.length !== 3) return date;
  return `${parts[0]} 年 ${Number(parts[1])} 月`;
}

function formatDateDay(date) {
  if (!date) return "--";
  const parts = String(date).split("-");
  if (parts.length !== 3) return date;
  return String(Number(parts[2]));
}

function formatDateLong(date) {
  if (!date) return "今日";
  const parts = String(date).split("-");
  if (parts.length !== 3) return date;
  return `${parts[0]}年${Number(parts[1])}月${Number(parts[2])}日${weekdayLabel(date) ? ` ${weekdayLabel(date)}` : ""}`;
}

function weekdayLabel(date) {
  if (!date) return "";
  const value = new Date(`${date}T00:00:00+08:00`);
  if (Number.isNaN(value.getTime())) return "";
  return value.toLocaleDateString("zh-CN", { weekday: "long", timeZone: "Asia/Shanghai" });
}

function formatEventTime(iso) {
  if (!iso) return "--:--";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "--:--";
  return value.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" });
}

function brandBreakdown(source, key, fallback = 0) {
  return source?.brand_breakdown?.[key] ?? fallback ?? 0;
}

async function selectDaily(date) {
  const previousDate = (state.selectedDaily || state.daily)?.date;
  try {
    state.selectedDaily = await loadJson(`./dashboard-data/daily/${date}.json`);
  } catch (error) {
    state.selectedDaily = state.daily;
  }
  const nextDate = (state.selectedDaily || state.daily)?.date;
  render();
  if (nextDate && nextDate !== previousDate) resetMainScroll(document.getElementById("content"));
}

function dailyArchiveClusterCount() {
  return (state.dailyIndex?.items || []).reduce((sum, item) => sum + Number(item.cluster_count || 0), 0);
}

function metric(label, value, note) {
  return `<div class="metric"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(String(value))}</div><div class="metric-note">${escapeHtml(note)}</div></div>`;
}

function summaryLine(label, text) {
  return `<div class="summary-line"><span class="meta">${escapeHtml(label)}</span><p>${escapeHtml(text)}</p></div>`;
}

function scoreBadge(score) {
  return `<div class="score-badge"><div class="score-number">${escapeHtml(String(score.ips))}</div><div class="score-label">IPS</div></div>`;
}

function levelPill(score) {
  const levelText = { urgent: "紧急", high: "高风险", medium: "中风险", low: "低风险" }[score.level] || score.level;
  const cls = score.sentiment === "positive" ? "positive" : score.level;
  return `<span class="level ${cls}">${levelText}</span>`;
}

function scoreContributionPanel(detail) {
  const score = detail.score || {};
  const rows = scoreContributionRows(score);
  const weighted = rows.reduce((sum, row) => sum + row.contribution, 0);
  const boost = scoreBoost(detail, weighted);
  return `
    <div class="score-explain-head">
      <div>
        <strong>${escapeHtml(String(score.ips ?? "n/a"))}</strong>
        <span>IPS</span>
      </div>
    </div>
    <div class="score-contribution-list">
      ${rows.map(scoreContributionRow).join("")}
      ${boost ? `<div class="score-contribution-row boost"><span>议题发酵加分</span><em>退款/物流且未来潜力高</em><strong>+${escapeHtml(String(boost))}</strong></div>` : ""}
    </div>
  `;
}

function scoreContributionRows(score) {
  const rows = [
    ["品牌相关度", score.brand_relevance, 0.2, "是否明确指向主品牌、别名或多语言关键词"],
    ["风险/机会强度", score.risk_or_opportunity_intensity, 0.18, "退款、物流、客服等议题的风险强度"],
    ["当前影响力", score.current_impact, 0.16, "互动量、浏览量和作者影响力"],
    ["未来发酵潜力", score.future_potential, 0.15, "引用、账号影响力、相似原帖密度"],
    ["可信度", score.credibility, 0.13, "多帖佐证、上下文证据和高影响力账号"],
    ["业务影响面", score.business_impact, 0.1, "对支付、履约、售后等业务链路的影响"],
    ["处置紧迫性", score.urgency, 0.08, "是否需要快速同步或处理"],
  ];
  return rows.map(([label, value, weight, note]) => ({
    label,
    value: Number(value || 0),
    weight,
    note,
    contribution: Number(value || 0) * weight,
  }));
}

function scoreContributionRow(row) {
  return `
    <div class="score-contribution-row">
      <span>${escapeHtml(row.label)}</span>
      <em>${escapeHtml(row.note)}</em>
      <strong>${escapeHtml(String(row.value))} × ${escapeHtml(String(Math.round(row.weight * 100)))}% = ${escapeHtml(row.contribution.toFixed(1))}</strong>
    </div>
  `;
}

function scoreBoost(detail, weighted) {
  const score = detail.score || {};
  if (["refund", "delivery", "fulfillment_risk"].includes(detail.topic) && Number(score.future_potential || 0) >= 80) return 3;
  return Math.max(0, Math.round(Number(score.ips || 0) - weighted));
}

function scoreBars(score) {
  const rows = [
    ["品牌相关度", score.brand_relevance, "green"],
    ["风险/机会强度", score.risk_or_opportunity_intensity, "red"],
    ["当前影响力", score.current_impact, "orange"],
    ["未来潜力", score.future_potential, "orange"],
    ["可信度", score.credibility, ""],
    ["业务影响面", score.business_impact, "red"],
    ["处置紧迫性", score.urgency, "red"],
  ];
  return rows.map(([label, value, color]) => bar(label, value, 100, color)).join("");
}

function bar(label, value, max, color = "") {
  const width = Math.max(4, Math.min(100, (Number(value) / Math.max(1, Number(max))) * 100));
  return `
    <div class="bar-line">
      <span>${escapeHtml(label)}</span>
      <div class="bar-track"><div class="bar-fill ${color}" style="--value:${width}%"></div></div>
      <span class="meta">${escapeHtml(String(value))}</span>
    </div>
  `;
}

function evidenceTabs(detail) {
  const labels = {
    origin: "热源",
    stakeholders: "当事人",
    popular: "热门",
    amplifiers: "扩散源",
    latest: "最新",
    supporting_evidence: "佐证",
    contradicting_evidence: "反证/存疑",
  };
  return `<div class="evidence-tabs">${Object.entries(labels)
    .map(([key, label]) => `<button class="evidence-tab ${key === state.currentEvidenceTab ? "active" : ""}" data-evidence="${key}" data-cluster="${detail.cluster_id}">${label} ${detail.evidence_counts[key] || 0}</button>`)
    .join("")}</div>`;
}

function evidenceList(detail, key) {
  const items = detail.evidence_chain[key] || [];
  if (!items.length) return empty("暂无对应证据");
  const detailSample = isDetailSample(detail);
  return `<div class="source-list">${items.map((item) => evidenceCard(item, detailSample)).join("")}</div>`;
}

function evidenceCard(item, isSample = false) {
  if (item.post_id) {
    const postItem = itemFromDetailPost(item, "X Source");
    const metrics = item.metrics || {};
    return `
      <article class="post-card evidence-post-card">
        <div class="source-identity">
          ${avatarNode(postItem)}
          <div>
            <div class="source-line">
              ${authorNameNode(postItem, postItem.author_name)}
              ${postItem.author_handle ? `<em>@${escapeHtml(postItem.author_handle)}</em>` : ""}
              ${sourceBadge(item.label, "focus")}
            </div>
            <div class="source-subline">${escapeHtml(formatEventTime(item.created_at))}${postItem.author_followers ? ` · ${escapeHtml(formatCompactNumber(postItem.author_followers))} followers` : ""}</div>
          </div>
        </div>
        ${richPostTextNode(postItem, item.translation_zh || item.summary_zh || item.text, "detail-source-text")}
        ${mediaGridNode(item.media, postItem)}
        <div class="card-meta">
          <span>赞 ${escapeHtml(formatCompactNumber(metrics.likes))}</span>
          <span>评 ${escapeHtml(formatCompactNumber(metrics.replies))}</span>
          <span>转 ${escapeHtml(formatCompactNumber(metrics.reposts))}</span>
          <span>引 ${escapeHtml(formatCompactNumber(metrics.quotes))}</span>
          <span>浏览 ${escapeHtml(formatCompactNumber(metrics.views))}</span>
        </div>
        ${externalLinkButton(item.url, "在 X 查看原帖", "primary", { isSample })}
      </article>
    `;
  }
  return `
    <article class="post-card">
      <div class="card-meta"><span class="tag">${escapeHtml(item.relationship || "source")}</span><span>${escapeHtml(item.source || "Source")}</span></div>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="muted">${escapeHtml(item.summary)}</p>
    </article>
  `;
}

function empty(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function bindPageEvents(detail = null) {
  document.querySelectorAll("[data-featured-date]").forEach((button) => {
    button.addEventListener("click", () => {
      const date = button.dataset.featuredDate;
      if (state.featuredExpandedDates.has(date)) state.featuredExpandedDates.delete(date);
      else state.featuredExpandedDates.add(date);
      render();
    });
  });

  document.querySelectorAll("[data-featured-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.featuredFilter = button.dataset.featuredFilter;
      syncFeaturedExpandedDatesForFilter();
      render();
    });
  });

  document.querySelectorAll("[data-all-source-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.allBrandFilter = button.dataset.allSourceFilter;
      render();
    });
  });

  const allTypeFilter = document.getElementById("all-type-filter");
  if (allTypeFilter) {
    allTypeFilter.addEventListener("change", () => {
      state.allTypeFilter = allTypeFilter.value;
      render();
    });
  }

  const allSearchForm = document.getElementById("all-search-form");
  if (allSearchForm) {
    allSearchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      state.allSearchQuery = document.getElementById("all-search-input")?.value || "";
      render();
    });
  }

  document.querySelectorAll("[data-all-date]").forEach((button) => {
    button.addEventListener("click", () => {
      const date = button.dataset.allDate;
      if (state.allExpandedDates.has(date)) state.allExpandedDates.delete(date);
      else state.allExpandedDates.add(date);
      render();
    });
  });

  document.querySelectorAll("[data-platform-date]").forEach((button) => {
    button.addEventListener("click", () => {
      const date = button.dataset.platformDate;
      if (state.platformExpandedDates.has(date)) state.platformExpandedDates.delete(date);
      else state.platformExpandedDates.add(date);
      render();
    });
  });

  document.querySelectorAll("[data-platform-tag-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.platformTagFilter = button.dataset.platformTagFilter || "";
      syncPlatformExpandedDatesForFilter();
      render();
    });
  });

  document.querySelectorAll("[data-dt-date]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.dtKind;
      if (!state.dtDigestFilters[kind]) return;
      const rail = button.closest("[data-dt-date-rail]");
      if (rail) state.dtDateRailScroll[kind] = rail.scrollLeft || 0;
      state.dtDigestFilters[kind].date = button.dataset.dtDate || "";
      state.dtDigestFilters[kind].section = "all";
      state.dtDigestFilters[kind].source = "all";
      await ensureDitingDigestDetail(kind, state.dtDigestFilters[kind].date);
      render();
    });
  });

  document.querySelectorAll("[data-dt-date-rail]").forEach((rail) => {
    rail.addEventListener("scroll", () => {
      const kind = rail.dataset.dtDateRail;
      if (state.dtDateRailScroll[kind] != null) state.dtDateRailScroll[kind] = rail.scrollLeft || 0;
    }, { passive: true });
  });

  document.querySelectorAll("[data-dt-today]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.dtToday;
      const today = button.dataset.dtTodayDate || dashboardTodayDate();
      if (!state.dtDigestFilters[kind] || button.disabled) return;
      state.dtDigestFilters[kind].date = today;
      state.dtDigestFilters[kind].section = "all";
      state.dtDigestFilters[kind].source = "all";
      state.dtDateRailScroll[kind] = 0;
      await ensureDitingDigestDetail(kind, today);
      render();
    });
  });

  document.querySelectorAll("[data-dt-section-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      const kind = select.dataset.dtSectionFilter;
      if (!state.dtDigestFilters[kind]) return;
      state.dtDigestFilters[kind].section = select.value || "all";
      render();
    });
  });

  document.querySelectorAll("[data-dt-source-filter]").forEach((select) => {
    select.addEventListener("change", () => {
      const kind = select.dataset.dtSourceFilter;
      if (!state.dtDigestFilters[kind]) return;
      state.dtDigestFilters[kind].source = select.value || "all";
      render();
    });
  });

  document.querySelectorAll("[data-dt-search-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const kind = form.dataset.dtSearchForm;
      if (!state.dtDigestFilters[kind]) return;
      state.dtDigestFilters[kind].query = document.querySelector(`[data-dt-search-input="${cssAttributeValue(kind)}"]`)?.value || "";
      render();
    });
  });

  document.querySelectorAll("[data-dt-clear-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.dtClearFilter;
      if (!state.dtDigestFilters[kind]) return;
      state.dtDigestFilters[kind].section = "all";
      state.dtDigestFilters[kind].source = "all";
      state.dtDigestFilters[kind].query = "";
      render();
    });
  });

  document.querySelectorAll("[data-daily-date]").forEach((button) => {
    button.addEventListener("click", () => selectDaily(button.dataset.dailyDate));
  });

  document.querySelectorAll("[data-scroll-target]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  document.querySelectorAll("[data-language-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.languageToggle;
      const language = button.dataset.language;
      const safeId = cssAttributeValue(id);
      document.querySelectorAll(`[data-language-toggle="${safeId}"]`).forEach((item) => {
        item.classList.toggle("active", item.dataset.language === language);
      });
      document.querySelectorAll(`[data-language-content="${safeId}"] [data-language-panel]`).forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.languagePanel === language);
      });
    });
  });

  document.querySelectorAll("[data-media-lightbox]").forEach((button) => {
    button.addEventListener("click", () => {
      prefetchImageUrl(button.dataset.mediaLightbox || "");
      openMediaLightbox(button.dataset.mediaLightbox, mediaLightboxOptions(button));
    });
  });

  document.querySelectorAll("[data-conversation-context]").forEach((button) => {
    button.addEventListener("click", () => openConversationDrawer(button.dataset.conversationContext));
  });

  document.querySelectorAll("[data-diting-comments]").forEach((button) => {
    button.addEventListener("click", () => openDitingCommentDrawer(button.dataset.ditingComments));
  });

  warmDitingMediaAssets();
}

function openDitingCommentDrawer(threadId) {
  const record = state.ditingCommentThreads.get(threadId);
  if (!record?.replies?.length) return;
  closeConversationDrawer();
  const { item, replies } = record;
  const channelName = compactDisplayText(item.channel_name || item.channelName || item.channel || "TG频道");
  const itemTime = compactDisplayText(item.time || "");
  const node = document.createElement("div");
  node.className = "conversation-drawer-shell";
  node.innerHTML = `
    <aside class="conversation-drawer diting-comment-drawer" role="dialog" aria-modal="true">
      <div class="conversation-drawer-tools">
        <div class="diting-comment-drawer-title">
          <strong>评论区</strong>
          <span>${escapeHtml([itemTime, channelName].filter(Boolean).join(" · "))}</span>
        </div>
        <button type="button" class="conversation-drawer-close" aria-label="关闭评论">×</button>
      </div>
      <div class="diting-comment-thread">
        <div class="diting-comment-count">评论 ${escapeHtml(String(replies.length))} 条</div>
        ${replies.map((reply) => ditingCommentNode(reply, item)).join("")}
      </div>
    </aside>
  `;
  node.addEventListener("click", (event) => {
    if (event.target === node || event.target.closest(".conversation-drawer-close")) closeConversationDrawer();
    const mediaButton = event.target.closest("[data-media-lightbox]");
    if (mediaButton) {
      prefetchImageUrl(mediaButton.dataset.mediaLightbox || "");
      openMediaLightbox(mediaButton.dataset.mediaLightbox, mediaLightboxOptions(mediaButton));
    }
  });
  const onKeydown = (event) => {
    if (event.key === "Escape") closeConversationDrawer();
  };
  node._onKeydown = onKeydown;
  window.addEventListener("keydown", onKeydown);
  document.body.appendChild(node);
  document.body.classList.add("conversation-drawer-open");
  warmDitingMediaAssets(node);
  updateBackToTopVisibility();
}

function ditingCommentNode(reply, owner) {
  const name = compactDisplayText(reply.senderName || "匿名用户") || "匿名用户";
  const time = compactDisplayText(reply.time || "");
  const text = multilineDisplayText(reply.text || "");
  const media = mediaGridNode(validDitingMediaItems(reply.media || []), owner);
  return `
    <article class="diting-comment-item">
      <div class="diting-comment-meta">
        <strong>${escapeHtml(name)}</strong>
        ${time ? `<span>${escapeHtml(time)}</span>` : ""}
      </div>
      ${text ? `<p>${escapeHtml(text)}</p>` : ""}
      ${media}
    </article>
  `;
}

function openConversationDrawer(contextId) {
  const record = state.conversationContexts.get(contextId);
  if (!record?.context) return;
  closeConversationDrawer();
  const context = record.context;
  const node = document.createElement("div");
  node.className = "conversation-drawer-shell";
  node.innerHTML = `
    <aside class="conversation-drawer" role="dialog" aria-modal="true">
      <div class="conversation-drawer-tools">
        <div class="conversation-drawer-primary-tools">
          <button type="button" class="text-button" data-conversation-top>最早</button>
          <span class="language-toggle conversation-language-toggle" role="group" aria-label="上下文语言切换">
            <button type="button" class="active" data-conversation-language="zh">中文译文</button>
            <button type="button" data-conversation-language="original">原文</button>
          </span>
        </div>
        <button type="button" class="conversation-drawer-close" aria-label="关闭上下文">×</button>
      </div>
      <div class="conversation-thread">
        ${context.posts.map((post) => conversationThreadPost(post, context.anchor_post_id)).join("")}
      </div>
    </aside>
  `;
  node.addEventListener("click", (event) => {
    if (event.target === node || event.target.closest(".conversation-drawer-close")) closeConversationDrawer();
    const mediaButton = event.target.closest("[data-media-lightbox]");
    if (mediaButton) {
      prefetchImageUrl(mediaButton.dataset.mediaLightbox || "");
      openMediaLightbox(mediaButton.dataset.mediaLightbox, mediaLightboxOptions(mediaButton));
    }
    if (event.target.closest("[data-conversation-top]")) {
      node.querySelector(".conversation-thread")?.scrollTo({ top: 0, behavior: "smooth" });
    }
    const languageButton = event.target.closest("[data-conversation-language]");
    if (languageButton) setConversationLanguage(node, languageButton.dataset.conversationLanguage);
  });
  const onKeydown = (event) => {
    if (event.key === "Escape") closeConversationDrawer();
  };
  node._onKeydown = onKeydown;
  window.addEventListener("keydown", onKeydown);
  document.body.appendChild(node);
  document.body.classList.add("conversation-drawer-open");
  updateBackToTopVisibility();
  requestAnimationFrame(() => {
    centerConversationAnchor(node);
  });
}

function centerConversationAnchor(node) {
  const thread = node.querySelector(".conversation-thread");
  const anchor = node.querySelector("[data-anchor-post='true']");
  if (!thread || !anchor) return;
  const anchorTop = anchor.offsetTop - thread.offsetTop;
  const targetTop = anchorTop - (thread.clientHeight - anchor.offsetHeight) / 2;
  thread.scrollTo({ top: Math.max(0, targetTop), behavior: "auto" });
}

function setConversationLanguage(node, language) {
  const selected = language === "original" ? "original" : "zh";
  node.querySelectorAll("[data-conversation-language]").forEach((button) => {
    button.classList.toggle("active", button.dataset.conversationLanguage === selected);
  });
  node.querySelectorAll("[data-conversation-language-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.conversationLanguagePanel === selected);
  });
}

function conversationThreadPost(post, anchorPostId) {
  const isAnchor = String(post.post_id || "") === String(anchorPostId || "");
  const variants = postTextVariants(post);
  const zhBody = variants.zh || variants.original || "";
  const originalBody = variants.original || variants.zh || "";
  return `
    <article class="conversation-post ${isAnchor ? "is-anchor" : ""}" ${isAnchor ? 'data-anchor-post="true"' : ""}>
      <div class="conversation-post-head">
        ${avatarNode(post)}
        <div class="conversation-post-meta">
          <div class="source-line">
            ${authorNameNode(post, post.author_name || post.author_handle || "X Source")}
            ${post.author_handle ? `<em>@${escapeHtml(post.author_handle)}</em>` : ""}
          </div>
          <div class="source-subline">${escapeHtml(formatDateTime(post.created_at || ""))}</div>
        </div>
      </div>
      <div class="post-language-content conversation-language-content">
        <div class="post-language-panel active" data-conversation-language-panel="zh">
          ${richPostTextNode(post, zhBody, "conversation-post-text")}
        </div>
        <div class="post-language-panel" data-conversation-language-panel="original">
          ${richPostTextNode(post, originalBody, "conversation-post-text original-text")}
        </div>
      </div>
      ${mediaGridNode(post.media || [], post)}
    </article>
  `;
}

function closeConversationDrawer() {
  const node = document.querySelector(".conversation-drawer-shell");
  if (!node) return;
  if (node._onKeydown) window.removeEventListener("keydown", node._onKeydown);
  node.remove();
  document.body.classList.remove("conversation-drawer-open");
  updateBackToTopVisibility();
}

function mediaLightboxOptions(button) {
  return {
    urls: parseMediaLightboxGroup(button?.dataset?.mediaLightboxGroup),
    index: Number(button?.dataset?.mediaLightboxIndex || 0),
  };
}

function parseMediaLightboxGroup(value) {
  if (!value) return [];
  try {
    const payload = JSON.parse(value);
    if (!Array.isArray(payload)) return [];
    return payload.map(safeExternalUrl).filter(Boolean);
  } catch (error) {
    return [];
  }
}

function openMediaLightbox(url, options = {}) {
  const safeUrl = safeExternalUrl(url);
  if (!safeUrl) return;
  closeMediaLightbox();
  const group = Array.isArray(options.urls) && options.urls.length ? options.urls : [safeUrl];
  let currentIndex = Number.isFinite(options.index) ? options.index : group.indexOf(safeUrl);
  if (currentIndex < 0 || currentIndex >= group.length) currentIndex = Math.max(0, group.indexOf(safeUrl));
  if (currentIndex < 0) currentIndex = 0;
  const hasMultiple = group.length > 1;
  const node = document.createElement("div");
  node.className = "media-lightbox";
  node.innerHTML = `
    <button type="button" class="media-lightbox-close" aria-label="关闭大图">×</button>
    ${hasMultiple ? `<button type="button" class="media-lightbox-nav prev" data-media-lightbox-prev aria-label="上一张图片"><span class="media-lightbox-chevron" aria-hidden="true"></span></button>` : ""}
    <figure class="media-lightbox-content">
      <img class="media-lightbox-image" src="${escapeHtml(group[currentIndex] || safeUrl)}" alt="" draggable="false" />
      ${hasMultiple ? `<figcaption class="media-lightbox-count">${escapeHtml(String(currentIndex + 1))} / ${escapeHtml(String(group.length))}</figcaption>` : ""}
    </figure>
    ${hasMultiple ? `<button type="button" class="media-lightbox-nav next" data-media-lightbox-next aria-label="下一张图片"><span class="media-lightbox-chevron" aria-hidden="true"></span></button>` : ""}
  `;
  const img = node.querySelector(".media-lightbox-image");
  const zoom = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0, originX: 0, originY: 0 };
  const clampPan = () => {
    if (!img || zoom.scale <= 1) {
      zoom.x = 0;
      zoom.y = 0;
      return;
    }
    const maxX = Math.max(0, ((img.offsetWidth || 0) * zoom.scale - window.innerWidth + 80) / 2);
    const maxY = Math.max(0, ((img.offsetHeight || 0) * zoom.scale - window.innerHeight + 80) / 2);
    zoom.x = Math.max(-maxX, Math.min(maxX, zoom.x));
    zoom.y = Math.max(-maxY, Math.min(maxY, zoom.y));
  };
  const applyZoom = () => {
    if (!img) return;
    clampPan();
    node.classList.toggle("is-zoomed", zoom.scale > 1.01);
    img.style.transform = `translate3d(${zoom.x}px, ${zoom.y}px, 0) scale(${zoom.scale})`;
  };
  const resetZoom = () => {
    zoom.scale = 1;
    zoom.x = 0;
    zoom.y = 0;
    zoom.dragging = false;
    applyZoom();
  };
  const showImage = (nextIndex) => {
    currentIndex = (nextIndex + group.length) % group.length;
    const count = node.querySelector(".media-lightbox-count");
    if (img) img.src = group[currentIndex];
    if (count) count.textContent = `${currentIndex + 1} / ${group.length}`;
    prefetchAdjacentLightboxImages(group, currentIndex);
    resetZoom();
  };
  node.addEventListener("wheel", (event) => {
    if (event.target.closest(".media-lightbox-close, .media-lightbox-nav")) return;
    if (!event.target.closest(".media-lightbox-content")) return;
    event.preventDefault();
    const delta = event.deltaY < 0 ? 1.12 : 0.88;
    zoom.scale = Math.max(1, Math.min(5, zoom.scale * delta));
    if (zoom.scale === 1) {
      zoom.x = 0;
      zoom.y = 0;
    }
    applyZoom();
  }, { passive: false });
  if (img) {
    img.addEventListener("pointerdown", (event) => {
      if (zoom.scale <= 1.01) return;
      zoom.dragging = true;
      zoom.startX = event.clientX;
      zoom.startY = event.clientY;
      zoom.originX = zoom.x;
      zoom.originY = zoom.y;
      img.setPointerCapture?.(event.pointerId);
    });
    img.addEventListener("pointermove", (event) => {
      if (!zoom.dragging) return;
      zoom.x = zoom.originX + event.clientX - zoom.startX;
      zoom.y = zoom.originY + event.clientY - zoom.startY;
      applyZoom();
    });
    img.addEventListener("pointerup", () => {
      zoom.dragging = false;
    });
    img.addEventListener("pointercancel", () => {
      zoom.dragging = false;
    });
    img.addEventListener("dblclick", resetZoom);
  }
  node.addEventListener("click", (event) => {
    if (event.target === node || event.target.closest(".media-lightbox-close")) closeMediaLightbox();
    if (event.target.closest("[data-media-lightbox-prev]")) showImage(currentIndex - 1);
    if (event.target.closest("[data-media-lightbox-next]")) showImage(currentIndex + 1);
  });
  document.body.appendChild(node);
  document.body.classList.add("lightbox-open");
  prefetchAdjacentLightboxImages(group, currentIndex);
  const onKeydown = (event) => {
    if (event.key === "Escape") closeMediaLightbox();
    if (hasMultiple && event.key === "ArrowLeft") showImage(currentIndex - 1);
    if (hasMultiple && event.key === "ArrowRight") showImage(currentIndex + 1);
    if (event.key === "0") resetZoom();
  };
  node._onKeydown = onKeydown;
  window.addEventListener("keydown", onKeydown);
}

function prefetchAdjacentLightboxImages(group, index) {
  if (!Array.isArray(group) || !group.length) return;
  [index, index - 1, index + 1].forEach((value) => {
    const nextIndex = (value + group.length) % group.length;
    prefetchImageUrl(group[nextIndex]);
  });
}

function closeMediaLightbox() {
  const node = document.querySelector(".media-lightbox");
  if (!node) return;
  if (node._onKeydown) window.removeEventListener("keydown", node._onKeydown);
  node.remove();
  document.body.classList.remove("lightbox-open");
}

function cssAttributeValue(value) {
  return String(value || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function decodeHtmlEntities(value) {
  return String(value ?? "")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&quot;/g, '"')
    .replace(/&#039;|&#39;|&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

init().catch((error) => {
  document.getElementById("content").innerHTML = `<section class="section">${empty(error.message)}</section>`;
});
