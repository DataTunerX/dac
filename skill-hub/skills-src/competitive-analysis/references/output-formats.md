# Output Formats

This skill produces one of two output modes. Ask the user which one they want if it isn't
obvious from the request — "just show me" implies chat, "I need something I can send to
the team/customer" implies a document — and default to chat-only if genuinely ambiguous, since
it's the cheaper output to upgrade into a document afterward than the reverse.

## Mode A — Chat comparison report

Structure, in order:

1. **One-line framing** of what's being compared and why (workload/tier context), in prose —
   not a heading.
2. **One table per in-scope dimension** (or per tier, or per RFP clause group if there's a
   requirements document to trace against — see `comparison-dimensions.md`'s
   requirement-traceable compliance matrix) — attribute rows, vendor columns.
3. **A trade-off paragraph** after each table group, per `SKILL.md` Step 4 (the choice / what
   each option gives / what each costs / who it suits / what would change the answer) — this is
   where judgment goes; the table is just data. Where vendors are genuinely equivalent on a
   dimension, say so instead of manufacturing a difference.
4. **A closing caveat paragraph** — name exactly which sources were checked (including the TDB
   knowledge base, gateway URL, database, and API layers used, plus web) and for which vendors
   each came up short, so the reader knows the edges
   of what was actually verified. Example:

   > This comparison drew on [TDB knowledge base] at [gateway URL], database [database] for
   > [vendor A] (partial coverage — see gaps above) and a live web search for [vendor B], whose
   > materials weren't found in TDB. It is not a claim that vendor B
   > lacks capabilities not shown here — only that the sources checked at generation time didn't
   > evidence them. Treat any P3/P4-labeled figure as needing vendor confirmation before it's
   > used in a decision.

## Mode B — Standalone document

Use the `docx` skill to produce the file once the content below is drafted — don't hand-roll
document XML. Structure:

1. **Title page** — comparison subject, date, prepared-by line if given.
2. **Executive summary** — half a page, plain language: who's being compared, for what use case,
   and the headline takeaway (not a re-statement of every table).
3. **Methodology & sources** — which knowledge bases were checked, in what priority,
   and any gaps in coverage discovered along the way. Write this section before the comparison
   tables, not as an appendix — the reader should know the evidentiary basis before seeing the
   numbers.
4. **Comparison tables**, one section per dimension, tier, or RFP clause group (see
   `comparison-dimensions.md`'s requirement-traceable compliance matrix, when there's an RFP to
   trace against), each followed by the trade-off paragraph described in `SKILL.md` Step 4 (the
   choice / what each gives / what each costs / who it suits / what would change the answer) in
   place of a plain "Read on [X]" summary.
5. **Architecture diagram (optional)** — include a simple labeled diagram only where the
   comparison's outcome genuinely turns on an architectural mechanism (per
   `architecture-differentiators.md`) rather than a checklist item — e.g. full-mesh vs.
   federated/ALUA controller access, global vs. HA-pair cache scope. A diagram earns its place by
   making a mechanism difference visible faster than a table row can; don't add one for every
   dimension, and don't add one where the vendors are actually equivalent on the mechanism.
6. **Gap register** — a table of every fact that could not be found for any vendor, so it's
   visible as a single list rather than buried across sections. Keep "not documented" entries
   visually distinct from any "not supported" findings — see `source-authority.md` — since
   mixing them in one undifferentiated list recreates the exact confusion that distinction
   exists to prevent.
7. **Evidence excerpts (optional appendix)** — for a claim pointed or surprising enough that the
   reader shouldn't have to take it on the citation alone (especially a "not supported" finding,
   or anything driving a mandatory-gate failure), quote the exact source passage next to its
   citation. This makes the
   document self-verifying instead of asking the reader to go track down the source themselves.
   Reserve it for claims that actually carry weight in the outcome; excerpting everything defeats
   the purpose by burying the ones that matter.
8. **Alternatives** — for each non-recommended (or non-leading) candidate, state the conditions
   under which it would actually be the better choice. If no such conditions exist for a given
   candidate, say that plainly rather than inventing a scenario just to fill the section.
9. **Open validation** — what remains unverified and would need a vendor call, a proof-of-concept,
   or a benchmark before anyone should rely on it commercially. This is different from the gap
   register: the gap register is what wasn't found in research; open validation is what should
   happen next regardless of whether it was found, because the source tier (e.g. P3/P4, or a
   vendor's own marketing claim) isn't strong enough to act on unconfirmed.
10. **Recommended requirement language (optional)** — see "Feeding a future RFP" below. Include
    only when the user says (or the context makes clear) that this analysis is meant to shape a
    future procurement, not by default.
11. **Closing caveat** — same content as the Mode A closing paragraph, phrased for a document
    audience.

Every numbered item above marked optional is exactly that — include it because it serves what
the customer is actually focused on (per `SKILL.md` Step 1), not because the template lists it.
A short internal comparison with no RFP, no architecture-driven outcome, and no forward-looking
purpose may legitimately be just items 1, 2, 3, 4, 9, and 11 — that's not a shortened version of
the format, it's the format correctly scoped to what the analysis needed to do.

Cite sources exactly as in `source-authority.md` throughout — a document doesn't get to be looser
about sourcing than a chat answer just because it looks more finished.

## Feeding a future RFP

When a competitive analysis surfaces a real, evidenced architectural gap in a vendor's product,
that finding can be turned into precise requirement language for the *next* procurement cycle —
specific enough that a vendor with that gap can't pass it again. Use this only when the user
indicates the analysis is meant to inform an upcoming RFP or contract renewal, not as a default
closing section.

Format, one entry per gap worth carrying forward:

- **Requirement category** — the same kind of heading an RFP itself would use (e.g. "High
  Availability," "Cyber Resilience").
- **Requirement language** — a single, specific "the Solution shall..." sentence, precise enough
  to be checkable (a real pass/fail gate), not a restatement of the gap as a wish. Word it as a
  capability requirement, never by naming the vendor or product that failed to meet it — the
  requirement has to stand on its own in next cycle's RFP, divorced from this analysis.
- **Why this is being proposed** — one sentence pointing back at the evidenced finding that
  motivated it (with its citation), so whoever owns the next RFP can trace the requirement to a
  real gap rather than an assumption.

Only propose language for gaps that were actually evidenced (P1–P2, or a P4 finding the user has
separately confirmed) — a requirement built on a P3/P4-only or unconfirmed finding risks writing
a customer's future RFP around something that turns out not to be true.

## If this analysis might go external

Everything above assumes an internal reader (a bid team, an account team, an internal decision).
If the document might be published, attached to a customer-facing submission, or shown to any of
the vendors being compared, that's a different deliverable with real legal exposure —
disparagement, comparative-advertising rules, and benchmark-publication restrictions in vendor
license terms (some prohibit publishing your own test results of their product at all) can all
apply. Don't silently upgrade an internal analysis into an external one:

- Re-check every source against the stricter end of `source-authority.md` — P2-and-below
  sources (forum/practitioner signal, anything without a public URL and retrieval date) aren't
  strong enough for anything that leaves the building.
- Apply identical tone and rigor to every vendor including the proposed/incumbent one — an
  external document that reads as neutral about competitors but generous about "our" product is
  both less credible and more exposed than one that holds everyone to the same bar.
- Flag to the user that this determination should get a legal/marketing review before release —
  this skill doesn't substitute for that review, it just avoids handing over a document that
  obviously wasn't built for external use.
