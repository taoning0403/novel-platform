import { spawnSync } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const acceptanceDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(acceptanceDirectory, "..", "..");
const currentTarget = "v0100";

const targets = new Map([
  ["v010", { entry: "gates/v010.mjs", description: "historical v0.1.0 gate" }],
  ["v020", { entry: "gates/v020.mjs", description: "historical v0.2.0 gate" }],
  ["v030", { entry: "gates/v030.mjs", description: "historical v0.3.0 gate" }],
  ["v040", { entry: "gates/v040.mjs", description: "historical v0.4.0 gate" }],
  ["v050", { entry: "gates/v050.mjs", description: "parameterized 84-criterion core" }],
  ["v060", { entry: "gates/v060.mjs", description: "historical v0.6.0 gate" }],
  ["v070", { entry: "gates/v070.mjs", description: "historical v0.7.0 gate" }],
  ["v080", { entry: "gates/v080.mjs", description: "historical v0.8.0 hardening gate" }],
  ["v090", { entry: "gates/v090.mjs", description: "historical v0.9.0 translation gate" }],
  ["v0100", { entry: "gates/v0100.mjs", description: "current complete local gate" }],
  ["staging", { entry: "gates/staging-v020.mjs", description: "staging functional gate" }],
  [
    "staging-persistence",
    {
      entry: "staging-persistence.sh",
      description: "staging persistence fingerprint check",
      runtime: "bash",
    },
  ],
]);

function normalizeTarget(value) {
  const candidate = value.trim().toLowerCase();
  if (candidate === "current" || candidate === "latest") return currentTarget;
  if (targets.has(candidate)) return candidate;

  const semanticVersion = candidate.match(/^v?(\d+)\.(\d+)\.(\d+)$/);
  if (semanticVersion) {
    const [, major, minor, patch] = semanticVersion;
    return `v${major}${minor}${patch}`;
  }
  return candidate;
}

function targetPath(target) {
  return path.join(acceptanceDirectory, target.entry);
}

function assertTargetFiles() {
  if (!targets.has(currentTarget)) {
    throw new Error(`Current acceptance target "${currentTarget}" is not registered`);
  }
  for (const [name, target] of targets) {
    try {
      accessSync(targetPath(target), constants.R_OK);
    } catch {
      throw new Error(`Acceptance target "${name}" is missing: ${target.entry}`);
    }
  }
}

function printTargets() {
  process.stdout.write(`Current target: ${currentTarget}\n\n`);
  for (const [name, target] of targets) {
    const marker = name === currentTarget ? "*" : " ";
    process.stdout.write(`${marker} ${name.padEnd(20)} ${target.description}\n`);
  }
}

function printHelp(stream = process.stdout) {
  stream.write(
    [
      "Usage:",
      "  pnpm acceptance",
      "  pnpm acceptance -- <target> [target arguments...]",
      "  pnpm acceptance -- --list",
      "",
      `The default target is "${currentTarget}". Version aliases such as "v0.9.0" are accepted.`,
      'Use target "staging" for the staging functional gate and "staging-persistence" for',
      "the staging persistence check.",
      "",
    ].join("\n"),
  );
}

function main() {
  assertTargetFiles();
  const arguments_ = process.argv.slice(2);
  if (arguments_[0] === "--") arguments_.shift();

  const requested = arguments_.shift() ?? "current";
  if (requested === "--help" || requested === "-h" || requested === "help") {
    printHelp();
    return;
  }
  if (requested === "--list" || requested === "list") {
    printTargets();
    return;
  }

  const name = normalizeTarget(requested);
  const target = targets.get(name);
  if (!target) {
    process.stderr.write(`Unknown acceptance target: ${requested}\n\n`);
    printHelp(process.stderr);
    process.exitCode = 2;
    return;
  }

  const entry = targetPath(target);
  const executable = target.runtime === "bash" ? "bash" : process.execPath;
  process.stdout.write(`[acceptance] ${requested} -> ${name}\n`);
  const result = spawnSync(executable, [entry, ...arguments_], {
    cwd: repositoryRoot,
    env: process.env,
    stdio: "inherit",
  });

  if (result.error) {
    process.stderr.write(`Failed to start acceptance target "${name}": ${result.error.message}\n`);
    process.exitCode = 1;
    return;
  }
  if (result.signal) {
    process.stderr.write(`Acceptance target "${name}" stopped by signal ${result.signal}\n`);
    process.exitCode = 1;
    return;
  }
  process.exitCode = result.status ?? 1;
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
