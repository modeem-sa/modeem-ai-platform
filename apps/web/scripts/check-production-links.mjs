#!/usr/bin/env node

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BLOCKED_HOST =
  /(?:package-firewall\.replit\.local|(?:[a-z0-9-]+\.)*replit\.local|(?:[a-z0-9-]+\.)+replit\.dev|(?:[a-z0-9-]+\.)+repl\.co)/gi;

function walk(directory) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

function findWorkspaceRoot(startDirectory) {
  let directory = resolve(startDirectory);

  while (true) {
    if (existsSync(join(directory, "apps/web/package.json"))) return directory;

    const parent = dirname(directory);
    if (parent === directory) return resolve(startDirectory);
    directory = parent;
  }
}

function resolveBuildOutput(root, buildOutput) {
  if (!buildOutput) return undefined;
  if (buildOutput.startsWith("apps/web/")) {
    return resolve(root, buildOutput);
  }

  const isWorkspaceRoot = existsSync(resolve(root, "apps/web/package.json"));
  return isWorkspaceRoot
    ? resolve(root, "apps/web", buildOutput)
    : resolve(root, buildOutput);
}

export function productionFiles(root, buildOutput) {
  const candidates = [
    "package-lock.json",
    "apps/web/package-lock.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
  ].map((path) => resolve(root, path));

  candidates.push(...walk(resolve(root, "infrastructure/docker")));
  if (buildOutput) {
    candidates.push(resolve(root, buildOutput, "required-server-files.json"));
  }

  for (const path of walk(root)) {
    const rel = relative(root, path);
    if (rel.split(/[\\/]/).some((part) => [".git", "node_modules", ".next", "docs"].includes(part))) {
      continue;
    }
    const name = path.split(/[\\/]/).at(-1).toLowerCase();
    if (
      name.startsWith(".env.production") ||
      name.startsWith("production.") ||
      name.includes(".production.")
    ) {
      candidates.push(path);
    }
  }

  return [...new Set(candidates)]
    .filter((path) => existsSync(path) && statSync(path).isFile())
    .sort();
}

function activeLines(path) {
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line, index) => [index + 1, line])
    .filter(([, line]) => {
      const content = line.trimStart();
      return content && !content.startsWith("#") && !content.startsWith("//");
    })
    .map(([number, line]) => [
      number,
      path.endsWith("package-lock.json") ? line : line.split("#", 1)[0],
    ]);
}

export function findViolations(root, buildOutput) {
  const violations = [];
  for (const path of productionFiles(root, buildOutput)) {
    for (const [lineNumber, line] of activeLines(path)) {
      BLOCKED_HOST.lastIndex = 0;
      const match = BLOCKED_HOST.exec(line);
      if (match) {
        violations.push({
          path: relative(root, path),
          lineNumber,
          hostname: match[0],
        });
      }
    }
  }
  return violations;
}

export function runProductionLinkCheck({
  root = findWorkspaceRoot(process.cwd()),
  buildOutput,
} = {}) {
  const resolvedBuildOutput = resolveBuildOutput(root, buildOutput);
  const violations = findViolations(root, resolvedBuildOutput);

  if (violations.length) {
    console.error("ERROR: Replit-only hostname(s) found in production build inputs:");
    for (const violation of violations) {
      console.error(`  ${violation.path}:${violation.lineNumber}: ${violation.hostname}`);
    }
    console.error("Replace these URLs with public/package-registry URLs before building.");
    return false;
  }

  console.log(
    `Production link check passed (${productionFiles(root, resolvedBuildOutput).length} files scanned).`,
  );
  return true;
}

function main() {
  const rootIndex = process.argv.indexOf("--root");
  const outputIndex = process.argv.indexOf("--build-output");
  const root = resolve(
    rootIndex >= 0 ? process.argv[rootIndex + 1] : findWorkspaceRoot(process.cwd()),
  );
  const buildOutput = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;

  if (!runProductionLinkCheck({ root, buildOutput })) {
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}