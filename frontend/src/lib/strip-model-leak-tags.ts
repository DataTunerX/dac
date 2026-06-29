const LEAK_TAG_NAMES = ["think", "redacted_thinking", "thinking"] as const

function stripTaggedBlocks(input: string): string {
  let out = input
  for (const name of LEAK_TAG_NAMES) {
    const re = new RegExp(`<${name}\\b[^>]*>[\\s\\S]*?<\\/${name}\\s*>`, "gi")
    out = out.replace(re, "")
  }
  return out
}

function stripOrphanTags(input: string): string {
  let out = input
  for (const name of LEAK_TAG_NAMES) {
    out = out.replace(new RegExp(`<\\/?${name}\\b[^>]*>`, "gi"), "")
  }
  return out
}

/** Remove model-internal reasoning tags that sometimes leak into visible chat output. */
export function stripModelLeakTags(input: string): string {
  if (!input) return input
  return stripOrphanTags(stripTaggedBlocks(input))
}

/** Remove model-internal markers (e.g. "reason:…") that sometimes leak into the visible answer. */
export function stripModelLeakLines(input: string): string {
  if (!input) return input
  return input
    .split("\n")
    .filter((line) => !/^\s*reason\s*:/i.test(line))
    .join("\n")
}
