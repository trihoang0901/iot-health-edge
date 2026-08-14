const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { chromium } = require("playwright");

const baseUrl = process.env.DASHBOARD_URL || "http://127.0.0.1:8000";
const chromePath = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const outputDir = path.resolve(process.env.BROWSER_EVIDENCE_DIR || "evidence/ui");
const projectRoot = path.resolve(__dirname, "..");
const uiSourceFiles = [
  "edge/static/app.js",
  "edge/static/index.html",
  "edge/static/styles.css",
  "scripts/dashboard-browser-smoke.js",
];
const servedAssetFiles = [
  "edge/static/favicon.svg",
  "edge/static/styles.css",
  "edge/static/app.js",
];

function expectedServedAssetVersion() {
  const digest = crypto.createHash("sha256");
  for (const relative of servedAssetFiles) {
    digest.update(fs.readFileSync(path.join(projectRoot, ...relative.split("/"))));
  }
  return digest.digest("hex").slice(0, 12);
}

function uiSourceProvenance() {
  const digest = crypto.createHash("sha256");
  for (const relative of uiSourceFiles) {
    const absolute = path.join(projectRoot, ...relative.split("/"));
    digest.update(relative, "utf8");
    digest.update(Buffer.from([0]));
    digest.update(fs.readFileSync(absolute));
    digest.update(Buffer.from([0]));
  }
  return {
    scope: "dashboard_static_and_smoke_script",
    source_sha256: digest.digest("hex"),
    source_files: uiSourceFiles,
  };
}

function writeReport(report) {
  fs.writeFileSync(
    path.join(outputDir, "browser-smoke.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function inspectViewport(browser, name, width, height) {
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: "dark",
    reducedMotion: "reduce",
    locale: "vi-VN",
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const response = await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 20_000 });
  assert(response && response.ok(), `${name}: dashboard HTTP response failed`);
  await page.waitForSelector("main", { timeout: 10_000 });
  await page.waitForTimeout(800);
  const appScriptSource = await page.locator('script[src^="/static/app.js?v="]').getAttribute("src");
  const servedAssetVersion = appScriptSource ? new URL(appScriptSource, baseUrl).searchParams.get("v") : null;
  assert(
    servedAssetVersion === expectedServedAssetVersion(),
    `${name}: served dashboard assets do not match local source`,
  );

  const audit = await page.evaluate(() => {
    const interactiveSelector = "a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])";
    const interactives = [...document.querySelectorAll(interactiveSelector)].filter((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    });
    const duplicateIds = [...document.querySelectorAll("[id]")]
      .map((node) => node.id)
      .filter((id, index, ids) => ids.indexOf(id) !== index);
    const unlabeledControls = interactives
      .filter((node) => {
        if (node.matches("a") && node.textContent.trim()) return false;
        if (node.matches("button") && (node.textContent.trim() || node.getAttribute("aria-label"))) return false;
        if (node.getAttribute("aria-label") || node.getAttribute("aria-labelledby")) return false;
        if (node.closest("label")) return false;
        const id = node.getAttribute("id");
        return !id || !document.querySelector(`label[for="${CSS.escape(id)}"]`);
      })
      .map((node) => `${node.tagName.toLowerCase()}#${node.id || "(none)"}`);
    const main = document.querySelector("main");
    return {
      lang: document.documentElement.lang,
      title: document.title,
      hasSkipLink: Boolean(document.querySelector("a[href='#main-content'], a[href='#noi-dung-chinh']")),
      hasMain: Boolean(main),
      hasH1: Boolean(document.querySelector("h1")),
      duplicateIds,
      unlabeledControls,
      horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      interactiveCount: interactives.length,
      statusLiveRegions: document.querySelectorAll("[aria-live]").length,
    };
  });

  assert(audit.lang.toLowerCase().startsWith("vi"), `${name}: missing Vietnamese lang`);
  assert(audit.hasMain && audit.hasH1, `${name}: missing main landmark or h1`);
  assert(audit.hasSkipLink, `${name}: missing skip link`);
  assert(audit.duplicateIds.length === 0, `${name}: duplicate ids: ${audit.duplicateIds.join(",")}`);
  assert(audit.unlabeledControls.length === 0, `${name}: unlabeled controls: ${audit.unlabeledControls.join(",")}`);
  assert(audit.horizontalOverflowPx <= 1, `${name}: horizontal overflow ${audit.horizontalOverflowPx}px`);
  assert(pageErrors.length === 0, `${name}: page errors: ${pageErrors.join(" | ")}`);
  assert(consoleErrors.length === 0, `${name}: console errors: ${consoleErrors.join(" | ")}`);

  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => {
    const node = document.activeElement;
    if (!node) return null;
    const style = getComputedStyle(node);
    return {
      tag: node.tagName.toLowerCase(),
      text: node.textContent.trim().slice(0, 80),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });
  assert(focused && focused.tag !== "body", `${name}: Tab did not move focus`);

  const screenshot = path.join(outputDir, `dashboard-${name}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  const screenshotSha256 = crypto.createHash("sha256").update(fs.readFileSync(screenshot)).digest("hex");
  await context.close();
  // Store only the artifact basename. Absolute workstation paths are neither
  // useful to reviewers nor compatible with the redacted evidence contract.
  return {
    name,
    viewport: { width, height },
    ...audit,
    focused,
    screenshot: path.basename(screenshot),
    screenshot_sha256: screenshotSha256,
    served_asset_version: servedAssetVersion,
  };
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const sourceProvenance = uiSourceProvenance();
  writeReport({
    artifact_version: "1.1",
    generated_at: new Date().toISOString(),
    base_url: baseUrl,
    source_provenance: sourceProvenance,
    status: "running",
    checks: [],
  });
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  try {
    const viewports = [
      ["mobile-320", 320, 900],
      ["mobile-360", 360, 900],
      ["tablet-768", 768, 1000],
      ["desktop-1440", 1440, 1000],
    ];
    const results = [];
    for (const [name, width, height] of viewports) {
      results.push(await inspectViewport(browser, name, width, height));
    }
    const report = {
      artifact_version: "1.1",
      generated_at: new Date().toISOString(),
      base_url: baseUrl,
      browser: await browser.version(),
      served_asset_version: expectedServedAssetVersion(),
      source_provenance: sourceProvenance,
      status: "passed",
      checks: results,
      limitations: [
        "Automated semantic and visual smoke; not a full WCAG conformance claim.",
        "Manual screen-reader and 400% browser zoom remain separate human checks.",
      ],
    };
    writeReport(report);
    process.stdout.write(`${JSON.stringify({ status: report.status, viewports: results.length })}\n`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  fs.mkdirSync(outputDir, { recursive: true });
  writeReport({
    artifact_version: "1.1",
    generated_at: new Date().toISOString(),
    base_url: baseUrl,
    source_provenance: uiSourceProvenance(),
    status: "failed",
    error_code: error && error.name ? error.name : "Error",
    checks: [],
  });
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exit(1);
});
