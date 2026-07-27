---
name: expense-report
description: Drive Huawei/Futurewei Workday in the browser via the Playwright MCP server to check expense report statuses AND create/edit expense reports. TRIGGER when the user asks to check expenses, expense status, reimbursements, "open the expense hub", or to create/start/edit an expense report in Workday.
---

# Expense Report (Workday via Playwright MCP)

Drives the browser with the **Playwright MCP server** to open the user's Workday Expenses Hub and read expense report statuses.

## Prerequisites
- Playwright/browser automation tools connected (for example `mcp__playwright__browser_*`).
- If browser automation tools are unavailable, tell the user this workflow requires a Playwright/browser connector before continuing.
- The user logs in manually (Microsoft SSO + MFA). Codex must pause and wait — never attempt to type credentials.

## Steps

1. **Navigate** to the Workday home:
   `https://www.myworkday.com/vhr_huawei/d/pex/home.htmld`
   This redirects to Microsoft SSO (`login.microsoftonline.com`, tenant `0fee8ff2-a3b2-4018-9c75-3a1d5591fedc`).

2. **Pause for login.** Take a snapshot, tell the user to enter email/password and complete MFA in the browser, and wait for them to confirm.

3. **Handle the "Remember this device?" trust page** if it appears: check the "Remember this device" checkbox, then click **Submit** so future sessions skip the Microsoft login.

4. **Open the Expenses Hub.** On the home page, click the **Search Workday** combobox, type `Expenses Hub`, and select the **"Expenses Hub Overview"** result from the suggestions. (Direct task URL once known: `/vhr_huawei/d/task/2998$43855.htmld`.)

5. **Open Expense Reports.** In the left Navigation Pane, click **Expense Reports**. (Direct task URL: `/vhr_huawei/d/task/2997$728.htmld`.)

6. **Read the statuses.** The "My Expense Reports" snapshot is large (~1,000+ lines) and will exceed the tool's token limit — it gets saved to a file instead. Do NOT try to read it inline. Instead:
   - Grep the saved snapshot file for the report rows:
     `rg -n '^\s*- row "ER-' <saved-snapshot-file>`
   - Each row contains: Expense Report number, date, **Status** (Paid / Canceled / In Progress / Awaiting Approval), memo, and amounts.
   - Optionally take a full-page screenshot for a visual confirmation.

7. **Summarize** the statuses in a table for the user (report #, date, status, memo, amount), and call out anything that is NOT Paid/Canceled (i.e. still pending or awaiting action).

## Creating a new expense report

**NEVER click Submit unless the user explicitly says to.** When the user wants to stop, use **Save for Later** (saves as Draft) — then **Edit Expense Report** to re-open.

### Step A — open the create form
Click the **Create Expense Report** button. Available in several places:
- The Expenses Hub Overview "Tasks" list ("Create Expense Report").
- The "My Expense Reports" page (top button: "Create Expense Report Hongliang Tang (411685)").
- The home page Quick Actions ("Create Expense Report").

### Step B — fill the header form (the "Create Expense Report" dialog)
Required fields (★) and the user's usual defaults — **ask the user to confirm each, don't assume**:
- **Creation Options:** "Create New Expense Report" (default checked). Alternatives: Copy Previous, From Spend Authorization.
- **Memo:** default `Customer Support`. ⚠️ A **TR number is required in the memo for travel-related expenses**.
- **Company:** `7071 Futurewei Technologies, Inc.` (pre-filled).
- **Expense Report Date:** defaults to today (M/D/Y spinbuttons).
- **Business Purpose:** default `Business Travel` (options: Business Travel, Entertainment for Business, Self-Purchase).
- **Cost Center:** `037710 Silicon Valley Storage Lab` (pre-filled).
- **Project:** default `Proj-2021-002 Storage TMT Go to Market (GTM) Project` (user calls it "Storage GTM").
- Optional: Budget Category, Additional Worktags.

Then click **OK** to proceed to the Expense Lines page.

### Step C — IMPORTANT: how Workday searchable dropdowns behave
The prompt-style fields (Project, Business Purpose, Cost Center, etc.) do **NOT** live-filter as you type, and `fill()` does not trigger the search reliably (and can concatenate with prior text). To pick a value:
1. Click the field's textbox.
2. Clear any existing text: `Ctrl/Cmd+A` then `Delete` (`browser_press_key`).
3. Type the term (a short distinctive word like `Storage` works best).
4. **Press `Enter`** to execute the search — results only appear after Enter.
5. Click the matching option (refs are nested under a "Search Results" listbox).

Business Purpose is the exception — its short option list shows immediately on typing.

### Step D — Expense Lines page
After OK, you land on Expense Lines (tabs: Header · Attachments · Expense Lines). Status shows **Draft**, Total 0.00 USD.
- **Add** button → add a line item.
- Bottom buttons: **Submit**, **Save for Later**, **Close**.
- After "Save for Later" the confirmation page shows **"Expense Report has been Saved"** and an **Edit Expense Report** button to resume.

### Step E — fill an expense line
Click **Add**. Each line has a receipt drop zone ("Drop files here / Select files") at the top, then fields:
- **Expense Date** ★ (defaults to today).
- **Expense Item** ★ — searchable prompt (type term + **Enter**, see Step C). e.g. "books" → **No matches**; the right category for book/PDF purchases is **"Office/breakroom supplies (exclude foods, beverage)"** (search `office`). Selecting an item can reveal more required fields and auto-fill **Budget Category** (e.g. "Office Expenses").
- **Quantity** ★ and **Per Unit Amount** ★ → **Total Amount** auto-computes (Qty × Unit).
- **Currency** ★ — defaults USD. To change: the USD pill blocks the input, so open the field, type the new code (e.g. `CNY`) into the dropdown search, Enter, select it. **Foreign currency auto-converts**: picking CNY adds **Currency Rate**, **Converted Amount** (USD), **Converted Currency** — Workday fills the USD amount automatically (keep CNY, don't pre-convert).
- **Memo** ★ (line-level, required) — describe the purchase.
- **Cost Center** ★ / **Project** — pre-filled from the header.

### Step F — receipts / attachments (REQUIRED)
Futurewei requires a **report-level attachment** ("a scanned/PDF version of all invoices…"). Line-level receipts alone do NOT satisfy it — submitting without a report attachment throws **"An attachment is required for all expense reports"**.
- Add receipts on the **Attachments tab** → **Edit** → Select files / drop zone → upload → **Save**. (Also fine to add them on the line's drop zone, but the report-level one is what clears the error.)
- Upload from disk via the Playwright file chooser: click **Select files**, then `mcp__playwright__browser_file_upload` with absolute paths. Multiple files in one call works.

### Getting receipt images out of Outlook → disk
Receipts often arrive as **inline images** emailed to the user (e.g. sender display name "lb lb" = hongliang.tang@gmail.com; Taobao order screenshots). **Next time the receipts will live in a dedicated Outlook folder named "in progress"** — search/open that folder first.
- The Microsoft 365 mail connector only returns a **rendered preview**, not raw bytes — you can read amounts from it but can't save the file.
- To get the actual file on disk: open the email in **Outlook Web** (outlook.office365.com — SSO usually carries over from the Workday login, no separate sign-in), click **"Show blocked content"** if the inline image is blocked, then fetch the bytes with `browser_evaluate` (find largest `<img>`, `fetch(src)` → blob → base64) and decode to a PNG with a quick `python3 base64.b64decode`.

### Submitting
Only click **Submit** when the user explicitly says to (e.g. "submit now"). After submit, status becomes **"Waiting on Expense Partner"** and the Business Process tab shows the approver (Expense Partner, e.g. Xiaoxia Tang) with a due date.

## Coming next time — TRAVEL expense report
The user plans to create a **travel expense report** with multiple line items: **taxi, meal, hotel, and other** expenses — more complex (per-diem rules, multiple receipts, possibly itemization for hotels). Run it WITH the user step by step, learn each expense item's required fields and any travel-specific rules (e.g. the **TR number in the header memo** required for travel-related expense), and append those details to this skill.

## Notes
- Columns in the report grid: Expense Report, Expense Report Date, Status, Memo, Total Amount, Reimbursement Amount, Worker Paid, Personal Amount, Currency, Company.
- Company is `7071 Futurewei Technologies, Inc.`
- Employee: Hongliang Tang (411685).
- To inspect one report, click its row's link (or use Related Actions).
- Prefer screenshots over snapshots on the create/lines pages — the accessibility snapshot can exceed the token limit and gets saved to a file.
- Defaults the user has used: Project **Storage GTM** (Proj-2021-002); Cost Center 037710 Silicon Valley Storage Lab; Company 7071 Futurewei.
- History: **ER-112535 "Customer Support"** is an empty Draft left untouched on purpose. **ER-112536 "Book purchase for project"** (Self-Purchase, ¥680 CNY = $100.41, 2 Taobao receipts attached) was **submitted 06/07/2026** and is awaiting the Expense Partner's approval — example of a completed end-to-end run.
