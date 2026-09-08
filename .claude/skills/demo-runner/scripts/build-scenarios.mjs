#!/usr/bin/env node
/**
 * Extract DEMO_SCENARIOS from frontend/src/lib/demo-scenarios.ts into plain JSON.
 *
 * The demo window is deliberately a standalone HTML page (no Next.js, no DAC
 * components), so it cannot import the TypeScript module. This strips the
 * type-only syntax and evaluates the remaining object literal.
 *
 * Usage: node build-scenarios.mjs <repo-root> <out-dir>
 */
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"

const repoRoot = process.argv[2] || process.cwd()
const outDir = process.argv[3]
if (!outDir) {
  console.error("usage: build-scenarios.mjs <repo-root> <out-dir>")
  process.exit(1)
}

const srcPath = path.join(repoRoot, "frontend/src/lib/demo-scenarios.ts")
let src = fs.readFileSync(srcPath, "utf8")

src = src
  .replace(/export type[^\n]*\n/g, "")
  .replace(/export interface[\s\S]*?\n}\n/g, "")
  .replace(/: readonly [A-Za-z<>\[\]]+/g, "")
  .replace(/export const/g, "const")
  .replace(/as const/g, "")

const start = src.indexOf("const DEMO_SCENARIOS")
if (start === -1) throw new Error("DEMO_SCENARIOS not found in " + srcPath)
const head = src.slice(0, start)
let tail = src.slice(start)
const end = tail.indexOf("\n]\n")
if (end === -1) throw new Error("could not find end of DEMO_SCENARIOS array")
tail = tail.slice(0, end + 3)

fs.mkdirSync(outDir, { recursive: true })
const tmp = path.join(outDir, ".scenarios.cjs")
fs.writeFileSync(tmp, head + tail + "; module.exports = DEMO_SCENARIOS;")

const require = createRequire(import.meta.url)
const data = require(tmp)
fs.rmSync(tmp)

fs.writeFileSync(path.join(outDir, "scenarios.json"), JSON.stringify(data, null, 2))
const steps = data.reduce((n, s) => n + s.steps.length, 0)
console.log(`scenarios: ${data.length}  steps: ${steps}  ->  ${path.join(outDir, "scenarios.json")}`)
