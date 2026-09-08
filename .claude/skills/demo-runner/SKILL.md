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

2. Serve it. **Do not decide to skip this because port 8777 answers 200** — a
   server left over from an earlier session may be serving a different
   directory, so a regenerated case list silently never reaches the page. Check
   what is actually being served, and restart if it disagrees with disk:

   ```bash
   served=$(curl -s http://127.0.0.1:8777/scenarios.json | python3 -c \
     "import json,sys; print(sum(len(s['steps']) for s in json.load(sys.stdin)))" 2>/dev/null)
   ondisk=$(python3 -c \
     "import json; print(sum(len(s['steps']) for s in json.load(open('/tmp/dac-demo-runner/scenarios.json'))))")
   echo "served=$served ondisk=$ondisk"
   if [ "$served" != "$ondisk" ]; then
     pkill -f "http.server 8777"
     cd /tmp/dac-demo-runner && nohup python3 -m http.server 8777 > /tmp/demo-http.log 2>&1 &
   fi
   ```

3. Open the demo window, then pop the real GUI as a genuinely separate window
   (`window.open` with explicit size — `context.newPage()` only makes a tab):

   - `browser_navigate` to `http://127.0.0.1:8777/index.html?r=<timestamp>`.
     **Always include the query string** — the browser caches the HTML itself,
     and a cached copy will render a stale case list (this bites every time a
     case is added or removed).
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

## Arm the bridge (serves clicks in a loop)

This blocks and keeps serving every click for ~9 minutes, so the operator can
run case after case without anyone re-arming between them. It returns when the
budget expires with no further click — just run it again to continue.

Do **not** use a single-shot `waitForFunction`: only the operator's first click
would reach the GUI and every later click would silently do nothing.

```js
async (page) => {
  const ctx = page.context();
  const demo = ctx.pages().find(p => p.url().includes('8777'));
  const gui  = ctx.pages().find(p => p.url().includes('32002'));
  if (!demo || !gui) return { error: 'missing window', urls: ctx.pages().map(p => p.url()) };

  const BUDGET_MS = 9 * 60 * 1000;
  const started = Date.now();
  const fired = [];

  while (true) {
    const left = BUDGET_MS - (Date.now() - started);
    if (left < 5000) break;
    try {
      await demo.waitForFunction(() => window.__DEMO_PENDING !== null, null, { timeout: left });
    } catch { break; }                  // budget expired with no further click

    const job = await demo.evaluate(() => {
      const j = window.__DEMO_PENDING;
      window.__DEMO_PENDING = null;
      window.__DEMO_LAST_SENT = j;
      return j;
    });
    if (!job || !job.prompt) continue;

    await gui.bringToFront();
    await gui.goto('http://10.124.48.126:32002/');   // fresh chat
    const box = gui.getByRole('textbox', { name: '给 DAC 发送消息' });
    await box.waitFor({ timeout: 30000 });
    await box.fill(job.prompt);
    await box.press('Enter');
    await gui.waitForTimeout(1200);
    fired.push({ id: job.id, title: job.title, url: gui.url() });
  }
  return { servedFor: `${Math.round((Date.now()-started)/1000)}s`, count: fired.length, fired };
}
```

Report each case that fired and its `run_id`. The operator reads the answers in
the real GUI window themselves — don't poll logs and narrate.

Re-run the block when it returns (or when the operator says **next**) to keep
serving.

## Rules

- **Let an answer finish before the next click, and never navigate or reload the
  real GUI while one is streaming.** Each submission navigates the GUI to a
  fresh chat, so firing early abandons the running answer — an interrupted run
  is lost entirely and never reaches history.
- Paste prompts **verbatim** from the case data; never paraphrase or fix typos.
- Blocked cases render a disabled button and cannot be fired.
- Case 3 (`场景 3`, wwybsj-build) permanently inserts its registration number.
  Before rehearsing it, check the number is still free — 466-468, 470-471, 472,
  480, 490, 500, 520 are burned; clean baseline is 1-465. Probe with:
  `POST 10.124.48.91:8997/v2/search/query {"query":"藏品总登记号 0<n>","mode":"lexical"}`
- Answers take 40 s - 4 min. That silence is normal.

## Changing the case list

Cases live in `frontend/src/lib/demo-scenarios.ts` — that is the source of
truth. To add or remove one, edit there, then re-run `build-scenarios.mjs` and
reload the demo window with a fresh query string
(`http://127.0.0.1:8777/index.html?r=<timestamp>`).

Caching bites at **two** levels, and both must be defeated or the page silently
renders the old case list:

1. `scenarios.json` — the page already requests it as `scenarios.json?v=<Date.now()>`
   with `cache: no-store`. Don't remove that.
2. `index.html` itself — always open/reload it as `index.html?r=<timestamp>`.
   `location.reload()` is not enough.

After any change, verify rather than assume:
`await demo.evaluate(() => document.querySelectorAll('.step').length)` should
match the step count `build-scenarios.mjs` printed.

## Files

- `assets/index.html` — the standalone demo page. Click handler sets
  `window.__DEMO_PENDING = {id, title, prompt}`; progress persists in
  `localStorage` under `dac_demo_runner_state_v1`. The 重置 button clears it.
  Note the localStorage progress counter is keyed by step id, so removing a
  case can leave the counter reading e.g. `4/23` from earlier runs — 重置
  clears it.
- `scripts/build-scenarios.mjs` — strips the TS types from
  `frontend/src/lib/demo-scenarios.ts` and emits `scenarios.json` next to the
  HTML. Re-run whenever the scenario list changes.

## Related

`.claude/commands/demo.md` is the older single-window `/demo` slash command that
drives cases from `demo/cases/*.md`. This skill supersedes it for live demos;
the markdown cases still carry the talk tracks and fallback run_ids.
