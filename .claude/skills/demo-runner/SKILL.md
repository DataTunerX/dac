---
name: demo-runner
description: Run the DAC demo as two separate browser windows - a standalone test-case window (no DAC components) and the real DAC GUI. The operator clicks a case; Playwright types that prompt into the real GUI. TRIGGER when asked to run the DAC demo, run a test case, open the demo windows, or "next" while a demo session is active.
---

# DAC demo runner (two windows)

Two windows, strictly separated:

| Window | URL | Role |
| --- | --- | --- |
| **Demo cases** (left) | `http://127.0.0.1:8777/index.html` | Standalone HTML. Lists all cases with prompt + acceptance criteria. **Contains no DAC GUI components.** |
| **Real GUI** (right) | `http://10.124.48.126:32002/` | The actual DAC frontend. Playwright types prompts here. |

The operator clicks **运行此用例** in the demo window. A blocking Playwright
watcher picks that up and submits the prompt in the real GUI window. The
operator reads the answer in the real GUI themselves.

## Why it is built this way

Earlier attempts failed for reasons worth not rediscovering:

- **The in-app `/demo` page (`frontend/src/app/(dashboard)/demo/`) is not usable
  for this.** It lives inside the dashboard layout, so it drags in the sidebar,
  chat history and nav — the operator explicitly wants a case list with none of
  that.
- **Never run the query through a local `next dev` server.** Next.js's dev-mode
  `rewrites()` proxy drops long-lived SSE streams at roughly 60 s
  (`failed to write progress event: connection has been closed when flush` in
  the apiserver log), so answers never appear. In production nginx proxies
  `/api/v1/*` and `/v1/*` before Next.js sees them, which is why the deployed
  frontend is unaffected. Always execute against the deployed GUI.
- `kubectl port-forward` is **not** the cause of that drop — it was ruled out by
  reproducing over a direct NodePort. Don't re-litigate it.

## Start a session

1. Regenerate the case list from the source of truth (keeps it in sync with
   `frontend/src/lib/demo-scenarios.ts`) and stage the page:

   ```bash
   D=/tmp/dac-demo-runner
   mkdir -p "$D"
   cp .claude/skills/demo-runner/assets/index.html "$D/"
   node .claude/skills/demo-runner/scripts/build-scenarios.mjs "$PWD" "$D"
   ```

2. Serve it (skip if `curl -s -o /dev/null http://127.0.0.1:8777/index.html`
   already returns 200):

   ```bash
   cd /tmp/dac-demo-runner && nohup python3 -m http.server 8777 > /tmp/demo-http.log 2>&1 &
   ```

3. Open the demo window, then pop the real GUI as a genuinely separate window
   (`window.open` with explicit size — `context.newPage()` only makes a tab):

   - `browser_navigate` to `http://127.0.0.1:8777/index.html`
   - then `browser_run_code_unsafe`:

   ```js
   async (page) => {
     await page.evaluate(() => { window.moveTo(0, 40); window.resizeTo(860, 1000) })
     const [gui] = await Promise.all([
       page.waitForEvent('popup'),
       page.evaluate(() => {
         window.open('http://10.124.48.126:32002/', 'dac_real_gui',
           'popup=yes,width=1000,height=1000,left=880,top=40')
       }),
     ])
     await gui.waitForLoadState('domcontentloaded')
     return gui.url()
   }
   ```

   If the GUI shows a login form: `admin` / `changeme`.

## Arm the bridge (one case per arming)

Run this and it blocks until the operator clicks a case, then submits it:

```js
async (page) => {
  const demo = page.context().pages().find(p => p.url().includes('8777'));
  const gui  = page.context().pages().find(p => p.url().includes('32002'));
  if (!demo || !gui) return { error: 'missing window', urls: page.context().pages().map(p => p.url()) };

  await demo.waitForFunction(() => window.__DEMO_PENDING !== null, null, { timeout: 600000 });
  const job = await demo.evaluate(() => {
    const j = window.__DEMO_PENDING;
    window.__DEMO_PENDING = null;
    window.__DEMO_LAST_SENT = j;
    return j;
  });

  await gui.bringToFront();
  await gui.goto('http://10.124.48.126:32002/');   // fresh chat
  const box = gui.getByRole('textbox', { name: '给 DAC 发送消息' });
  await box.waitFor({ timeout: 30000 });
  await box.fill(job.prompt);
  await box.press('Enter');
  await gui.waitForTimeout(1500);
  return { ran: job.title, id: job.id, url: gui.url() };
}
```

Report only: which case ran and its `run_id`. The operator watches the answer in
the real GUI window. **Re-arm when the operator says "next"** — the watcher is
one-shot by design, so a stray click can never fire an unexpected query.

## Rules

- **One case per arming.** Never batch.
- **Never navigate or reload the real GUI while an answer is streaming** — an
  interrupted run is lost entirely and never reaches history.
- Paste prompts **verbatim** from the case data; never paraphrase or fix typos.
- Blocked cases render a disabled button and cannot be fired.
- Case 3 (`场景 3`, wwybsj-build) permanently inserts its registration number.
  Before rehearsing it, check the number is still free — 466-468, 470-471, 472,
  480, 490, 500, 520 are burned; clean baseline is 1-465. Probe with:
  `POST 10.124.48.91:8997/v2/search/query {"query":"藏品总登记号 0<n>","mode":"lexical"}`
- Answers take 40 s - 4 min. That silence is normal.

## Files

- `assets/index.html` — the standalone demo page. Click handler sets
  `window.__DEMO_PENDING = {id, title, prompt}`; progress persists in
  `localStorage` under `dac_demo_runner_state_v1`. The 重置 button clears it.
- `scripts/build-scenarios.mjs` — strips the TS types from
  `frontend/src/lib/demo-scenarios.ts` and emits `scenarios.json` next to the
  HTML. Re-run whenever the scenario list changes.

## Related

`.claude/commands/demo.md` is the older single-window `/demo` slash command that
drives cases from `demo/cases/*.md`. This skill supersedes it for live demos;
the markdown cases still carry the talk tracks and fallback run_ids.
