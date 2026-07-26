#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const repositoryRoot = process.env.STAGING_SCAN_REPOSITORY_ROOT ?? process.cwd();
const reportDirectory = process.env.STAGING_SCAN_REPORT_DIR;
if (!reportDirectory) {
  throw new Error("STAGING_SCAN_REPORT_DIR is required");
}

const sourceEntries = [
  ".env.staging.example",
  "README.md",
  "compose.staging.yml",
  "apps/server/Dockerfile",
  "apps/server/src/novel_platform/config.py",
  "apps/server/src/novel_platform/main.py",
  "apps/web/Dockerfile.staging",
  "apps/web/nginx.staging.conf",
  "docs/adr/0009-single-host-staging-topology.md",
  "docs/staging-deployment.md",
  "scripts",
];

const excludedNames = new Set([
  ".env.staging",
  "staging-acceptance-state.json",
  "leak-scan-v050.json",
]);
const excludedExtensions = new Set([".dump", ".sha256"]);

function collectFiles(entry, files) {
  if (!fs.existsSync(entry)) return;
  const stat = fs.statSync(entry);
  if (stat.isDirectory()) {
    for (const child of fs.readdirSync(entry)) {
      if (child === "node_modules" || child === ".git") continue;
      collectFiles(path.join(entry, child), files);
    }
    return;
  }
  if (excludedNames.has(path.basename(entry))) return;
  if (excludedExtensions.has(path.extname(entry))) return;
  files.push(entry);
}

const sourceFiles = [];
for (const entry of sourceEntries) {
  collectFiles(path.join(repositoryRoot, entry), sourceFiles);
}
const reportFiles = [];
collectFiles(reportDirectory, reportFiles);
const allFiles = [...new Set([...sourceFiles, ...reportFiles])];

const sensitiveValues = [
  "POSTGRES_PASSWORD",
  "AUTH_JWT_SECRET",
  "AUTH_HASH_SECRET",
  "AUTH_CREDENTIAL_HASH_SECRET",
  "PROVIDER_CREDENTIAL_MASTER_KEY",
  "PROVIDER_RELAY_SERVICE_SECRET",
]
  .map((name) => ({ name, value: process.env[name] ?? "" }))
  .filter(({ value }) => value.length >= 8);

const reportPatterns = [
  ["private key", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["authorization credential", /Authorization\s*:\s*(?:Bearer|Basic)\s+\S+/i],
  ["JWT-shaped token", /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/],
  ["Cookie header value", /(?:Set-Cookie|Cookie)\s*:\s*[^\r\n]+=[^;\s]{8,}/i],
  ["database URL password", /postgres(?:ql)?(?:\+\w+)?:\/\/[^:\s/]+:[^@\s/]+@/i],
  ["raw access or recovery credential", /\bnpa_[A-Za-z0-9_-]{32,}\b/],
];

const findings = [];
for (const file of allFiles) {
  const content = fs.readFileSync(file);
  if (content.includes(0)) continue;
  const text = content.toString("utf8");
  for (const { name, value } of sensitiveValues) {
    if (text.includes(value)) {
      findings.push({ file, finding: `value of ${name}` });
    }
  }
  if (file.startsWith(path.resolve(reportDirectory))) {
    for (const [finding, pattern] of reportPatterns) {
      if (pattern.test(text)) findings.push({ file, finding });
    }
  }
}

const result = {
  completed_at: new Date().toISOString(),
  status: findings.length === 0 ? "PASS" : "FAIL",
  scanned_files: allFiles.length,
  actual_environment_file_scanned: false,
  database_backups_scanned: false,
  findings: findings.map(({ file, finding }) => ({
    file: path.relative(repositoryRoot, file),
    finding,
  })),
};
const outputPath = path.join(reportDirectory, "leak-scan-v050.json");
fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 });

console.log(`staging artifact leak scan ${result.status}`);
if (findings.length > 0) process.exitCode = 1;
