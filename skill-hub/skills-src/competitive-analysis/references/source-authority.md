# Product Knowledge Source Authority (P1 → P4)

Every factual claim about a vendor's product in a competitive analysis must carry one of these
four authority labels. The ladder exists so that a reader can tell, at a glance, how much to
trust each number — a spec pulled from a reviewed knowledge base is not the same kind of fact as
a marketing claim on a datasheet, and both are different again from something found on the open
web. Never strip a label to make the document look more authoritative than the underlying source
actually is.

## P1 — TDB Ontology Fact (highest authority)

- **What it is**: a structured fact from TDB's knowledge graph, extracted from ingested vendor
  documents but not independently reviewed.
- **Tools**: `tdb_fact_list`, `tdb_fact_search`, `tdb_concept_neighbors`, `tdb_concept_search`.
- **Cite as**: `[TDB-fact: <knowledge base>/<concept>/<predicate>; gateway=<URL>; db=<database>]`

## P2 — TDB RAG Chunk

- **What it is**: a passage of vendor-document text retrieved from TDB's RAG search. Treat it as
  vendor-published text that hasn't been independently verified.
- **Cite as**: `[TDB-RAG: <knowledge base>/<stream>, chunk <n>; gateway=<URL>; db=<database>]` —
  go one level more specific whenever the source makes it possible, such as a section/chapter
  title or figure/table number.
- **Caveat to attach**: values extracted from prose may carry implicit conditions (a specific
  configuration, a footnote, a "*ask your rep" asterisk) — carry those conditions into the
  citation rather than smoothing them away.

## P3 — Domain Knowledge

- **What it is**: something you know from training rather than something retrieved live. Useful
  for context and framing, risky for specific numbers on recently-released products.
- **Mark as**: `(domain knowledge)` — never present this as equivalent to a retrieved fact.

## P4 — Live Web Search

- **What it is**: a fact found via web search during the engagement — press
  releases, third-party reviews, public spec pages.
- **Cite as**: `[web: <url>, accessed <date>]`
- **When to reach for it**: only after TDB has been checked and comes up short for a specific
  vendor or fact. Don't default to web search first just because it's fast — search for the
  vendor's own current datasheet/spec page before third-party summaries.
- **Mandatory caveat**: flag P4-sourced facts as needing vendor confirmation before anyone relies
  on them commercially.

---

## The core discipline: cite everything, guess nothing

1. Every comparable fact in the output carries one of the four labels above.
2. If a fact cannot be found at any tier for a given vendor, say so explicitly in the table cell
   ("not published in reviewed materials" or similar) — never fill the gap with an assumption or
   a competitor's number. A visible gap is useful information; a silent guess is not.
3. When two sources disagree, cite the higher-authority one for the comparison and note the
   disagreement in a footnote rather than picking silently.
4. Close every analysis with a caveat paragraph naming exactly which sources were checked and
   which weren't, so the reader knows the boundaries of what was actually verified — see
   `output-formats.md` for the template.

## "Not documented" is not "not supported"

These are two different findings and the output must never blur them:

- **Not supported** — a source (a datasheet, admin guide, release note) explicitly states the
  vendor's product does not do the thing. Cite the statement that says so.
- **Not documented** — none of P1–P4 turned up anything either way. This says nothing about the
  product; it says the research didn't find published material on this point. It's exactly as
  likely to mean "the vendor doesn't publish this figure" as "nobody's ingested their materials
  yet" as "it exists but isn't written down anywhere public."

Turning a "not documented" into a "not supported" — even by accident, even just by the way a
sentence is phrased in the write-up — converts a research gap into a false claim about a vendor's
product. If you're not sure which one applies to a given cell, it's "not documented."

## Flag evidence-depth asymmetry

Before treating a cross-vendor comparison on a given point as settled, check that the vendors
being compared actually have comparable evidence for it — not just that a fact was found for
each. If the proposed/incumbent product has several TDB facts for a point where a competitor has
only a thin web page (or vice versa), that's an asymmetry, not a like-for-like comparison. Name it
in the write-up rather than letting the better-sourced entry read as more capable purely because
more was written about it. This cuts both ways — apply it to your own product's evidence with the
same suspicion you'd apply to a competitor's.
