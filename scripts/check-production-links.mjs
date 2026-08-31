#!/usr/bin/env node

export {
  findViolations,
  productionFiles,
  runProductionLinkCheck,
} from "../apps/web/scripts/check-production-links.mjs";

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runProductionLinkCheck } from "../apps/web/scripts/check-production-links.mjs";

function main() {
  const rootIndex = process.argv.indexOf("--root");
  const outputIndex = process.argv.indexOf("--build-output");
  const root = resolve(rootIndex >= 0 ? process.argv[rootIndex + 1] : process.cwd());
  const buildOutput = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;

  if (!runProductionLinkCheck({ root, buildOutput })) {
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}