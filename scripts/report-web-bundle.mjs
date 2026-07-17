import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";

const root = process.cwd();
const dist = path.join(root, "apps", "web", "dist");
const assetsDirectory = path.join(dist, "assets");
const artifacts = path.join(root, "artifacts");
const jsonPath = path.join(artifacts, "bundle-v070.json");
const markdownPath = path.join(artifacts, "bundle-v070.md");
const baseline = {
  initial_js: { raw_bytes: 266_760, gzip_bytes: 83_120 },
  initial_css: { raw_bytes: 30_270, gzip_bytes: 7_020 },
};

function kilobytes(bytes) {
  return Number((bytes / 1000).toFixed(2));
}

function matchesScope(name, patterns) {
  return patterns.some((pattern) => name.includes(pattern));
}

async function main() {
  const indexHtml = await readFile(path.join(dist, "index.html"), "utf8");
  const entryMatch = indexHtml.match(/src="\/assets\/([^"]+\.js)"/);
  if (!entryMatch) throw new Error("Unable to identify the Vite entry chunk.");
  const entryName = entryMatch[1];
  const names = (await readdir(assetsDirectory))
    .filter((name) => name.endsWith(".js") || name.endsWith(".css"))
    .sort();
  const chunks = [];
  for (const name of names) {
    const contents = await readFile(path.join(assetsDirectory, name));
    chunks.push({
      name,
      type: name.endsWith(".js") ? "js" : "css",
      raw_bytes: contents.byteLength,
      gzip_bytes: gzipSync(contents).byteLength,
    });
  }

  const entry = chunks.find((chunk) => chunk.name === entryName);
  if (!entry) throw new Error("Vite entry chunk is missing from dist/assets.");
  const initialCss = chunks.find(
    (chunk) => chunk.type === "css" && chunk.name.startsWith("index-"),
  );
  const scopes = {
    login: chunks.filter((chunk) =>
      matchesScope(chunk.name, ["LoginPage", "AuthPages"])),
    library: chunks.filter((chunk) =>
      matchesScope(chunk.name, ["LibraryPage", "LibraryPages", "BookDetailPage"])),
    reader: chunks.filter((chunk) => chunk.name.includes("ReaderPage")),
    upload: chunks.filter((chunk) =>
      matchesScope(chunk.name, ["UploadPage", "UploadPages", "SeriesUploadPage"])),
    admin: chunks.filter((chunk) =>
      matchesScope(chunk.name, ["AdminDashboard", "AdminReaders", "AdminSecurity", "AdminSite", "AdminAudit", "AdminPages"])),
  };
  const report = {
    version: "0.7.0",
    generated_at: new Date().toISOString(),
    baseline,
    entry,
    initial_css: initialCss ?? null,
    entry_budget: {
      max_gzip_bytes: 200_000,
      status: entry.gzip_bytes <= 200_000 ? "PASS" : "FAIL",
    },
    scopes,
    chunks,
  };

  await mkdir(artifacts, { recursive: true });
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });

  const scopeLines = Object.entries(scopes).flatMap(([scope, items]) => [
    `### ${scope}`,
    "",
    ...(items.length === 0
      ? ["- No dedicated chunk identified."]
      : items.map(
          (item) =>
            `- \`${item.name}\`: ${kilobytes(item.raw_bytes)} kB raw / ${kilobytes(item.gzip_bytes)} kB gzip`,
        )),
    "",
  ]);
  const markdown = [
    "# 漫读 v0.7.0 Web bundle report",
    "",
    `- Initial JS baseline: ${kilobytes(baseline.initial_js.raw_bytes)} kB raw / ${kilobytes(baseline.initial_js.gzip_bytes)} kB gzip`,
    `- Initial JS current: ${kilobytes(entry.raw_bytes)} kB raw / ${kilobytes(entry.gzip_bytes)} kB gzip`,
    `- Initial JS 200 kB gzip budget: **${report.entry_budget.status}**`,
    `- Initial CSS baseline: ${kilobytes(baseline.initial_css.raw_bytes)} kB raw / ${kilobytes(baseline.initial_css.gzip_bytes)} kB gzip`,
    `- Initial CSS current: ${initialCss ? `${kilobytes(initialCss.raw_bytes)} kB raw / ${kilobytes(initialCss.gzip_bytes)} kB gzip` : "not identified"}`,
    "",
    "The entry increase is the shared React, Router, Ant Design provider, App Shell, and common UI foundation. Heavy pages remain route-level dynamic imports.",
    "",
    "## Route scopes",
    "",
    ...scopeLines,
    "## All emitted chunks",
    "",
    "| Asset | Type | Raw kB | Gzip kB |",
    "| --- | --- | ---: | ---: |",
    ...chunks.map(
      (item) =>
        `| \`${item.name}\` | ${item.type} | ${kilobytes(item.raw_bytes)} | ${kilobytes(item.gzip_bytes)} |`,
    ),
    "",
  ].join("\n");
  await writeFile(markdownPath, markdown, { mode: 0o600 });
  process.stdout.write(`${markdownPath}\n`);
}

await main();
