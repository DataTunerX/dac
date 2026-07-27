---
name: domain-knowledge-builder
description: >-
  Build a university undergraduate curriculum for an academic field, then find the textbook
  (name, author, publisher, edition, year, ISBN, source URL) for every course. TRIGGER when the
  user names an academic field (archaeology, math, CS, etc.) and wants its course list and/or the
  textbooks used. Handles university selection (asks, or surveys top schools if the user defers),
  curriculum discovery from official handbooks / 培养方案 / department sites, parallel textbook
  research, ISBN verification, and a clean CSV output.
---

# Domain Knowledge Builder

Given an **academic field**, produce (1) a structured **undergraduate curriculum** for that
field at a chosen university, and (2) the **textbook** for each course — name, author, publisher,
edition, year, ISBN, a verifiable source URL, and a confidence flag. Output a clean CSV.

This generalizes a real workflow run for Peking University (北京大学) Archaeology: 149 courses,
117 textbooks researched and ISBN-verified across parallel agents.

## Inputs you need before starting

1. **Field** — given by the user (e.g. archaeology, mathematics, computer science).
2. **University** — ask the user, or choose a defensible default if they defer:
   - If they name one (or a few), use those.
   - If they say "you choose" / "any" / "top school", **pick the single best-known university for
     that field** (by reputation/ranking) and tell them which one you chose and why. Offer to
     survey several if they want a comparison — but default to one unless they ask for more.
3. **Book-name language** — ask whether textbook titles should be kept in the **original language**
   (e.g. Chinese for a Chinese university) or translated to English. Default: **original language**,
   because that is what's searchable on local bookstores. (The PKU run kept Chinese titles.)
4. **Scope** — confirm how far to go. Three valid stopping points:
   - **Curriculum only** — Phase 1 → Phase 4 (course list, no textbooks). A complete, useful deliverable on its own.
   - **Small slice** — Phases 1–4 but textbooks only for the core required courses (~10), to exercise every phase cheaply.
   - **Full run** — all phases for every course.
   Default to asking; if the user just says "go", default to **Full run** for a small program and
   **confirm before fanning out** for a large one (50+ courses).

Don't over-ask. Field is required; for the rest, pick sensible defaults and state them. Bundle
these into one concise question when needed (university + scope, and language only if non-obvious).

## Phase 1 — Discover the curriculum

Goal: the official, structured course list for the undergraduate program.

Sources, in priority order:
- Official **培养方案 / 教学计划 / program handbook** (most authoritative — has course numbers,
  credits, hours, term, required/elective status).
- The **department / school website** course catalog or "本科生培养" page.
- The university **course-selection system** (e.g. PKU `elective.pku.edu.cn`) for per-course detail.
- Program **brochure** or accreditation/curriculum PDFs.

Extract per course: `category` (e.g. Professional Required / Elective), `subcategory`,
`course_no`, `course_name` (original language), a **workload** value, `term`, and any `requirement`
notes (prereqs, "choose N credits", replacement options, department offering the course).

**Adapt the schema to how the institution actually counts** — don't force one model:
- Chinese universities (PKU等) use **credits + 学时 (total/practice hours)**.
- US universities vary: **credit-hours**, or MIT-style **units** (e.g. `12`, `5-0-7`), or a count of
  **subjects/courses**. Use whatever the catalog uses; name the column accordingly (`credits`,
  `units`, etc.) and keep it consistent within one file.

**Capture structure faithfully — these patterns recur and the MIT run proved they're easy to get wrong:**
- **Category-level requirements** (e.g. MIT GIRs: Science Core, REST, Lab, HASS, Communication; or
  "choose ≥12 credits across 5 departments"). Record these as their **own rows** with a descriptive
  `course_name`, blank `course_no`, and the count in workload (`"8 subjects"`, `"≥12 credits"`).
  **Do NOT invent specific classes to fill a category** — if the catalog names representative
  options (5.111/5.112/3.091), put them in the note, don't fabricate a definitive pick.
- **Degree options / tracks / concentrations** (e.g. MIT 8-Flex vs 8-Focused; a "theory track" vs
  "applied track"). Put the option name in `subcategory` so rows are filterable by track.
- **"Choose one of A / B / C" groups** — keep as a single row listing the choices (in `course_no`
  and/or note), not as separate fabricated required entries.
- **Capstone / thesis / seminar** requirements — include as rows even when they have no textbook.

Also capture the **source URL(s)** you discovered the curriculum from — put them in the `notes` of
relevant rows or a short provenance note in your summary, so the curriculum is traceable.

Use browser/search tools for the discovery sweep. If multi-agent tooling is available and the
discovery spans many pages, load it and delegate independent source-gathering work to subagents.
If you can't find an official handbook, say so and assemble the best available list, flagging it as
unofficial.

## Phase 2 — Research textbooks (fan out in parallel)

For each course, find the assigned/standard textbook. **This is the bulk of the work — parallelize
it when tooling allows.** Split the course list into batches (~12–15 courses each). If multi-agent
tools are available, launch one research subagent per batch in parallel. If they are not available,
work batch-by-batch with browser/search tools and keep intermediate results structured.

Each research agent should, per course:
- Prioritize the **actual textbook used in that course** (search "<university> <course name> 教材/
  syllabus", instructor pages), then fall back to the **standard/most-used textbook** for the
  subject.
- Verify on an authoritative bookseller/catalog: **Douban (book.douban.com)** for Chinese books;
  publisher pages, WorldCat, Google Books, Amazon for others.
- Return: `textbook_name` (original language), `author`, `publisher`, `year`, `isbn` (full 13-digit
  as a STRING), `confidence`, and a short `note`.
- If a course genuinely has **no fixed textbook** (seminars, theses, practica, discussion/topic
  courses), return `无` / "none" and explain in the note (list key readings if known).

Have agents return a **JSON array** keyed by an index or exact course name so results write back
cleanly. Tell them: "Output ONLY the JSON array, no prose."

## Phase 3 — Verify ISBNs & attach source URLs

Run a second parallel pass over the books that have a title. Each verifier:
- Confirms the 13-digit ISBN and year **on a real book page** — a specific book-detail URL, NOT a
  search URL. Pick the catalog that fits the language: **Douban `/subject/NNNN/`** for Chinese books;
  **publisher page / WorldCat / Google Books / Open Library / Amazon** for English and others.
- Corrects wrong ISBNs/years (the first pass commonly gets a few wrong — in the PKU run, 13 ISBNs
  were corrected here).
- Sets `confidence`:
  - `verified` — ISBN confirmed on a real book page.
  - `likely` — standard text identified, exact edition not pinned down.
  - `unknown` — couldn't confirm the book/ISBN.
- Returns the `source_url`.

Log every correction in the `notes` column (e.g. `【核对】ISBN已更正：原X→Y`) so changes are traceable.

## Phase 4 — Write the CSV

Columns (suggested — adapt to the scope and the institution's workload model):
`category, subcategory, course_no, course_name, <workload cols>, term, requirement,
textbook_name, author, publisher, edition, year, isbn, source_url, confidence, notes`
- `<workload cols>` = `credits, total_hours, practice_hours` for Chinese-style programs, or a single
  `units` / `credit_hours` column for US-style. Match the catalog.
- **Curriculum-only scope:** drop the textbook columns (`textbook_name`…`confidence`) entirely —
  output just the course list. (The MIT physics test produced a clean 7-column curriculum file.)
- Name the file descriptively, e.g. `<university>_<field>_undergraduate_curriculum[_with_textbooks].csv`.

### CRITICAL — avoid the Excel ISBN-corruption trap
ISBNs are 13-digit numbers that Excel will silently mangle into scientific notation
(`9.7875E+12`), destroying the digits. To prevent this:
- **Always write the CSV with Python's `csv` module**, ISBN values as **strings**.
- Use UTF-8 **with BOM** (`encoding="utf-8-sig"`) so Excel renders Chinese/non-ASCII correctly.
- Warn the user: if they re-save from Excel as CSV, format the `isbn` column as **Text** first, or
  keep the file as `.xlsx`. Offer to also emit an `.xlsx` where `isbn` is text-typed.
- When editing an existing CSV, read it back and assert **no `E+` strings** remain in `isbn`.

Do all column insertions / fills with a small Python script via the terminal (read → transform → write),
not by hand-editing rows — it preserves quoting and is far less error-prone.

## Quality bar & reporting

- At the end, report counts by confidence: **verified / likely / no-textbook** — and total courses.
- Be honest about gaps: name any course whose textbook is unverified or missing, rather than
  implying full coverage.
- Confidence flags are not decoration — only mark `verified` when an ISBN was confirmed on a real
  page.

## Worked precedent (PKU Archaeology)

- 149 courses across Required / Elective / cross-disciplinary categories, pulled from the PKU
  培养方案 + 选课系统 + 院系网站.
- 117 textbooks researched (89 verified, 28 likely); 32 courses correctly marked 无 (no fixed text).
- Book titles kept in **Chinese**; ISBNs stored as text; sources mostly Douban subject pages.
- Output: `pku_archaeology_undergraduate_curriculum_courses_with_textbooks.csv`.

## Worked precedent (MIT Physics, Course 8 — curriculum-only)

- User gave field=Physics, deferred the school → picked **MIT Course 8** (justified by ranking +
  machine-readable official catalog). Scope = curriculum only.
- One discovery agent pulled the structure from `catalog.mit.edu/degree-charts/physics-course-8/`
  + `physics.mit.edu`. 29 rows, US-style **units** (not credits).
- Correctly modeled: **GIRs as category rows** (Science Core / REST / Lab / HASS / Communication),
  **8-Flex vs 8-Focused** options in `subcategory`, **"choose one of"** groups as single rows, and
  the **8.THU thesis** capstone — without inventing classes to fill GIR categories.
- Output: `mit_physics_course8_undergraduate_curriculum.csv` (7 columns, no textbook columns).
