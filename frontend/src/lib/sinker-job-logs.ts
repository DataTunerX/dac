export const SINKER_JOB_LOG_PERMISSION = "descriptor:job-logs:read"

const FINISHED_STATUSES = new Set(["ready", "active", "succeeded", "deleting"])

/** True while the sinker deployment can still be running. Ready means it has been cleaned up. */
export function canViewSinkerJobLogs(status?: string | null): boolean {
  const key = (status ?? "").trim().toLowerCase()
  if (!key || key === "-" || key === "unknown") return true
  return !FINISHED_STATUSES.has(key)
}

export type JobLogSseEvent = { event: string; data: string }

/** Parse a text/event-stream body into discrete events. Blank lines flush one event. */
export async function consumeJobLogSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: JobLogSseEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  let event = "message"
  let dataLines: string[] = []

  const flush = () => {
    if (dataLines.length === 0) {
      event = "message"
      return
    }
    onEvent({ event, data: dataLines.join("\n") })
    event = "message"
    dataLines = []
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split(/\r?\n/)
    buf = parts.pop() ?? ""
    for (const line of parts) {
      if (line === "") {
        flush()
        continue
      }
      if (line.startsWith(":")) continue
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim()
        continue
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).replace(/^ /, ""))
      }
    }
  }
  buf += decoder.decode()
  if (buf.length > 0) {
    if (buf.startsWith("data:")) dataLines.push(buf.slice("data:".length).replace(/^ /, ""))
    flush()
  }
}
