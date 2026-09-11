---
name: competitive-analysis
description: >
  Research and produce a vendor/product competitive analysis for enterprise storage — compares
  a proposed or incumbent product against named competitors across capacity, performance,
  replication/availability, protocol convergence, security, and management, citing every fact
  to its source and flagging anything unverified rather than guessing. Works for any vendor,
  including ones with no TDB coverage — searches TDB and the web to fill
  gaps. Use whenever the user wants a "competitive analysis," "battle card," "vendor comparison,"
  "positioning against competitors," "how does X stack up against Y," or is evaluating options
  for an RFP/RFI/HLD and needs to know how a solution compares to alternatives — even without
  the word "competitive" (e.g. "is Pure actually cheaper than NetApp for this workload").
metadata:
  version: "1.0"
---

# Enterprise Storage Competitive Analysis

## Why this skill exists

A competitive analysis is only useful if the reader can tell which claims are solid and which
are marketing. The whole point of this skill is discipline about sourcing, not cleverness about
storage — any storage vendor's public materials will make every product sound best-in-class, and
your job is to find what's actually documented, say plainly when something isn't, and never let a
gap in the research quietly become a gap in the customer's understanding of the tradeoffs.

## TDB access and evidence capture

Use TDB through its HTTP gateway APIs. Do not connect directly to a database or invent a
connection string. Select the gateway from the vendor/product being researched and record the
knowledge-base label, gateway URL, and database in the evidence trail. The database name is a
configured backend identifier, not a credential or direct-connect target.

### Gateway routing

| Knowledge base | Gateway URL | Database |
|---|---|---|
| Huawei combined — all Huawei information | `http://10.124.48.91:8999` | `tdb_huawei_a` |
| Huawei Dorado | `http://10.124.48.91:9000` | `tdb_huawei_dorado` |
| Huawei Pacific | `http://10.124.48.91:9001` | `tdb_huawei_pacific` |
| Huawei OceanProtect | `http://10.124.48.91:9002` | `tdb_huawei_oceanprotect` |
| Huawei OceanDisk | `http://10.124.48.91:9003` | `tdb_huawei_oceandisk` |
| Huawei DCS | `http://10.124.48.91:9004` | `tdb_huawei_dcs` |
| Dell | `http://10.124.48.91:9005` | `tdb_dell` |
| NetApp | `http://10.124.48.91:9006` | `tdb_netapp` |
| IBM | `http://10.124.48.91:9007` | `tdb_ibm` |
| Everpure | `http://10.124.48.91:9008` | `tdb_everpure` |
| HPE | `http://10.124.48.91:9009` | `tdb_hpe` |
| Hitachi | `http://10.124.48.91:9010` | `tdb_hitachi` |
| Combined vendor knowledge | `http://10.124.48.91:9011` | `tdb_hld` |

For Huawei, use the combined gateway when the product family is not yet known; use a
product-specific gateway when that split is useful. For cross-vendor comparisons, use
`tdb_hld` or query the relevant vendor-specific gateways separately and preserve each source's
metadata.

### TDB query sequence

For each vendor/product, follow this sequence and URL-encode query terms and slugs:

1. Health: `GET <gateway>/v2/health`; fall back to `GET <gateway>/health`.
2. Scope: `GET <gateway>/v2/search/domain-stream/list?domain=<domain>` when the domain or
   stream binding needs confirmation.
3. Structured concepts: `GET <gateway>/v2/ontology/concept/search?domain=<domain>&q=<term>&limit=20`.
4. Explicit facts/relations: `GET <gateway>/v2/ontology/statement/list?subject_id=<subject_id>&limit=50`.
5. Vendor-document passages: `POST <gateway>/v2/search/query` with a JSON body containing the
   query, selected `domain`, and a suitable mode such as `lexical` for exact terms.
6. Wiki material when exposed: `GET <gateway>/v2/wiki/search?domain=<domain>&q=<term>` and
   `GET <gateway>/v2/wiki/page?domain=<domain>&slug=<slug>`.

### Network-permission diagnostic before interpreting connection errors

Private TDB gateways may be reachable from an approved network context but blocked by the
default command sandbox. If `curl` reports `Couldn't connect to server`, `Connection refused`,
or a TCP probe reports `Operation not permitted`, do not conclude that the gateway or API is
down. First distinguish local egress policy from a remote service failure:

1. Run a read-only health check against the selected gateway, preferably with an explicit
   connect and request timeout: `curl --connect-timeout 3 --max-time 8 -fsS
   <gateway>/v2/health`.
2. If the error is `Operation not permitted` or the same failure occurs across multiple TDB
   ports, treat it as a likely sandbox/network-permission failure and request the approved
   network context for the read-only retry. Do not change TDB configuration or retry blindly.
3. After network access is granted, repeat health checks for every gateway in scope and run the
   actual read-only query. A successful `HTTP 200` health response and stable repeated checks
   establish that the gateway is healthy; only then diagnose query scope, indexing, payload, or
   API behavior.
4. Record the distinction in the evidence trail: “default sandbox blocked TCP egress; gateway
   and query API succeeded in the approved network context,” rather than “TDB was transiently
   unavailable.”

This is separate from search-scope diagnosis. Once connectivity is established, still inspect
`resolved_stream_ids`: a valid non-empty stream list with zero hits is a scoped retrieval miss,
not a connection failure. For product comparisons, prefer an explicit `stream_ids` list from
`domain-stream/list` so a broad domain query does not resolve to thousands of unrelated streams.

### Storage TDB inventory and wiki access

The storage deployment exposes these useful routes: `8999` Huawei combined, `9000` Huawei
Dorado, `9001` Huawei Pacific, `9002` Huawei OceanProtect, `9003` Huawei OceanDisk, `9004`
Huawei DCS, `9005` Dell, `9006` NetApp, `9007` IBM, `9008` Everpure/Pure Storage, `9009` HPE,
`9010` Hitachi, and `9011` the cross-vendor HLD aggregate. Check the live binding count rather
than hard-coding coverage; a `limit=500` response is a lower bound when the returned count equals
500.

The wiki layer is available through:

```text
GET <gateway>/v2/wiki/search?domain=enterprise_storage&q=<term>
GET <gateway>/v2/wiki/page?domain=enterprise_storage&slug=<slug-from-search-result>
```

`wiki/search` returns page metadata such as `page_id`, `slug`, `page_type`, confidence, and
`authority_kind`; use the returned complete `slug` to fetch the page. Wiki pages are often shared
`enterprise_storage` `source_summary` pages containing concepts and relationships, so a
vendor-specific gateway does not guarantee a vendor-only wiki page. Treat wiki material as
knowledge-layer context and retain its page metadata; use scoped RAG or structured statements
for a product-specific claim.

An explicit stream name is not required for a normal search if `domain=enterprise_storage` is
provided: the gateway can resolve active streams automatically. It is nevertheless recommended,
and effectively required for deterministic vendor/product evidence, to discover complete
`stream_id` values from `domain-stream/list` and pass them in `stream_ids`. Never invent a short
stream name. Use this decision rule:

- `domain` only: acceptable for discovery and broad recall; inspect `resolved_stream_ids` and
  expect mixed vendor/generic material.
- explicit `stream_ids`: preferred for a comparison, citation, or model-specific fact.
- neither `domain` nor `stream_ids`: unscoped; do not cite the hits.

The gateway route is a routing convenience, not a hard evidence boundary. The shared
`enterprise_storage` domain can still cause a product gateway to resolve many unrelated streams;
explicit stream IDs are the reliable isolation mechanism.

After every `/v2/search/query`, inspect `resolved_stream_ids`. Non-empty hits with an empty
`resolved_stream_ids` list indicate an unscoped query; do not use those hits until the domain
binding is corrected. A non-empty stream list with zero hits indicates valid scope but a missed
query; retry with shorter product/model/protocol terms or `mode: "lexical"`.

### Scope-resolution pitfalls and recovery

`resolved_stream_ids: []` is not by itself proof that the corpus has no bindings. It also occurs
by design when the request omits `domain`, `stream_id`, and `stream_ids`; such a broad query may
return hits but is still unscoped. A second common cause is using a vendor name as the domain when
the deployment uses a shared domain. For the enterprise-storage deployment, the configured domain
is `enterprise_storage`, not `huawei`, `enterprise_storage_huawei_dorado`, or
`enterprise-storage`.

When scope is unclear, inspect the binding table before accepting search hits:

```bash
curl -fsS --get '<gateway>/v2/search/domain-stream/list' \
  --data-urlencode 'domain=enterprise_storage' \
  --data-urlencode 'status=active' \
  --data-urlencode 'limit=500' \
| jq -r '.bindings[].stream_id'
```

The endpoint returns objects in `bindings[]`; use each object's complete `stream_id` unchanged.
For a shared domain, filter the returned IDs locally by product/vendor terms (for example,
`oceanstor`, `dorado`, or `pacific`) and pass the selected IDs explicitly in `stream_ids` when
vendor-specific evidence is required. Do not confuse an empty result for a guessed domain with an
empty result for the actual configured domain. `domain-stream/list` is for discovering bindings;
the search response's `resolved_stream_ids` is the final proof of the scope used for that query.

Correctly scoped search example:

```json
{
  "query": "OceanStor Dorado HyperMetro",
  "domain": "enterprise_storage",
  "mode": "lexical",
  "limit": 5
}
```

If a product-specific query needs a deterministic scope, prefer:

```json
{
  "query": "HyperMetro active-active",
  "stream_ids": ["<complete stream_id from bindings[]>"],
  "mode": "lexical",
  "limit": 5
}
```

Do not cite hits from a request with empty `resolved_stream_ids` as domain-grounded TDB evidence.
Report the distinction precisely: “the request used an invalid/unbound domain” or “the request
was unscoped,” rather than claiming “the vendor has no valid stream.”

For every TDB fact retained, record the knowledge-base label, gateway URL, database, endpoint,
query term, returned stream/concept/statement/page/chunk identifier when available, and any
configuration, license, version, or test-condition qualifiers. Cite structured facts as
`[TDB-fact: <knowledge base>/<concept>/<predicate>; gateway=<URL>; db=<database>]` and retrieved
document passages as `[TDB-RAG: <knowledge base>/<stream>, chunk <n>; gateway=<URL>; db=<database>]`.

## Step 1 — Scope the comparison

Before researching anything, pin down:

- **The proposed/incumbent product** (if there is one) and the **competitor(s)** to compare it
  against — the user may name specific models, or just vendors ("Dell vs NetApp"), or a use case
  without naming anyone ("what should we use for a Tier 0 OLTP refresh") in which case ask which
  vendors are actually in scope before researching blindly.
- **The workload/tier context** — mission-critical block, scale-out file/object, backup, AI/ML
  data lake, etc. This determines which dimensions in `references/comparison-dimensions.md`
  actually matter; don't run every dimension against every vendor regardless of relevance.
- **Output mode** — chat report or a standalone document. See `references/output-formats.md`.
  If ambiguous, ask; default to chat if you truly can't tell, since it's cheaper to upgrade a
  chat answer into a document afterward than the reverse.
- **Whether this analysis might end up external.** If there's any chance this comparison gets
  attached to a customer submission, published, or shown to the vendors being compared, say so
  now and hold every source to the stricter public/dated/retrievable bar in
  `references/source-authority.md` from the start — re-checking a comparison built for internal
  use only, right before it goes external, is where sourcing gaps get missed. Internal bid
  strategy and anything that could go external are not the same deliverable; don't silently
  reuse one as the other.
- **What the customer is actually focused on.** If there's an RFP, requirements doc, or even just
  a few sentences from the user about what matters most, read it for that before doing anything
  else — specifically, which requirements are stated as mandatory, which get repeated or dwelt on,
  and which functional areas the workload context makes load-bearing. This is the single biggest
  lever on how the rest of this skill runs: it's what decides whether a dimension gets a full
  table or a one-line equivalence note (Step 4), whether the primary table should be built from
  the RFP's own clause numbers instead of generic dimensions, whether an architecture diagram
  earns its space, whether any claim is pointed enough to need a source excerpt, and whether a
  "recommended requirement language" section belongs in the output at all (Step 5). Every
  optional element described below exists to serve a customer's actual focus, not to be produced
  by default — when in doubt about whether one is worth including, this is the thing to check
  against.

## Step 2 — Research each vendor/product, in priority order

Work through this order for **every** vendor in scope, including the proposed/incumbent one —
don't skip sourcing discipline for "your own" product just because it's the one being pitched.

1. **TDB** — route the vendor/product using the embedded **TDB access and evidence capture**
   section above. Check health, use ontology/wiki/search APIs, verify domain/stream scope, and
   inspect `resolved_stream_ids` before accepting search hits. TDB coverage varies and is worth
   checking directly rather than assuming — some vendors that seem obvious competitors may
   simply not be ingested yet.
2. **Live web search** — only after TDB has been checked and come up short
   for a specific vendor or fact. This is expected to happen often for vendors nobody has loaded
   into TDB yet — that's exactly the case this step exists for. Search for the vendor's own current
   datasheet/spec page first, not third-party summaries.

Label every fact per `references/source-authority.md` and record the gateway/database metadata
from the embedded TDB access section as you go — don't defer sourcing to the end, since it's
much easier to lose track of where a number came from after the fact than to label it the moment
you find it.

Apply the same evidence bar to the proposed/incumbent product as to every competitor. If you
notice you have visibly deeper or higher-tier evidence for one vendor than another on the same
point, that's an asymmetry worth flagging in the write-up (e.g. "X's figure comes from richer TDB
evidence; Y's is the only public datasheet we could find") rather than letting the richer-looking
entry read as more capable by accident of research depth.

For workloads where controller architecture, cache design, or backend/media architecture is
actually load-bearing to the comparison, skim `references/architecture-differentiators.md` for
named patterns worth investigating specifically (e.g. symmetric active-active vs. ALUA, global
vs. HA-pair cache) — these catch marketing claims that sound equivalent but describe materially
different mechanisms. Load it on demand, not for every comparison; most dimension-level research
in Step 2 won't need it.

## Step 3 — Check mandatory requirements first, if any exist

If the user has stated hard requirements — a certification, a minimum capacity, a required
protocol, a pass/fail evaluation gate from an RFP — check every vendor against those *before*
building comparison tables for anything else. A vendor that fails a stated mandatory requirement
is excluded from the ranked comparison and reported separately with the requirement it failed;
don't let a strong showing on unrelated dimensions soften a hard failure into a middling score.
If a mandatory requirement's status is genuinely unknown (not failed, just unverified), say so
and keep the vendor provisionally in scope pending that confirmation — an unknown is not a pass.

Skip this step cleanly (don't force it) when the user hasn't stated any hard requirements — most
open-ended "how does X compare to Y" questions won't have any, and that's fine.

## Step 4 — Build the comparison

**If the user has an actual RFP or requirements document**, build the primary table from its own
requirement/clause numbers, not from the generic dimension list — see
`references/comparison-dimensions.md`'s "Requirement-traceable compliance matrix" section for the
row/status format. This is more useful to the reader than a generic-dimension table because it
lets them find "does this meet clause 3.1.7" directly, and it's what the customer's own
evaluation will actually check against. Use the generic dimensions from
`references/comparison-dimensions.md` to fill in anything the RFP doesn't cover, or as the whole
basis for the comparison when there's no RFP to trace against.

Otherwise, use `references/comparison-dimensions.md` to pick the dimensions that matter for this
workload, and build one table per dimension (or per tier, if multiple product categories are in
scope) — attribute rows, vendor columns, proposed/incumbent product as the first column.

For each cell, use one of these statuses rather than free-form prose, borrowed from
`references/source-authority.md`'s discipline of never overstating what was found:

- **Delivered** — documented as meeting the point being compared, with the source cited.
- **Partial / Conditional** — delivered, but with a real limitation, narrower scope, or an extra
  license/hardware/service requirement — state which.
- **Different mechanism** — the outcome is achieved a materially different way; describe the
  mechanism rather than just asserting equivalence.
- **Not supported** — a source explicitly states the capability is absent. Cite the statement.
- **Not documented** — nothing was found for this vendor at any research tier. This is never the
  same finding as "not supported" and must never be worded as if it were — the vendor may simply
  not publish that figure, or nobody's loaded their materials into TDB yet. Write it plainly
  (e.g. "not published in reviewed materials"), never left blank and never inferred.

Before stating any cross-vendor numeric difference, check it against
`references/normalization-rules.md` — most "differences" in vendor-published numbers turn out to
be different test conditions, different counting methodologies, or different product
generations, not real differences. An unnormalized numeric comparison is a false claim even if
every individual number is accurate.

After each table (or group of tables for one tier/category), write a short trade-off paragraph
rather than a plain summary — this is the part that requires judgment; the table is just the data
behind it:

1. **The choice**, stated neutrally as something the reader decides, not a conclusion.
2. **What each option gives**, specific and evidenced.
3. **What each option costs** — every real option costs something (capability given up,
   complexity, price, lock-in); if one side of the comparison looks costless, the analysis is
   incomplete, not the product.
4. **Who it suits** — the circumstances under which each choice is the right one.
5. **What would change the answer** — the specific fact or test result that would flip it. This
   is usually the single most useful sentence in the paragraph.

Where vendors are genuinely equivalent on a dimension or a specific architecture-differentiator
pattern, say that plainly instead of manufacturing a difference — a comparison that finds a
winner on every single dimension is advocacy, not research. Equivalence is also a signal about
how much space that point deserves in the output: give it a single compressed line ("both
vendors support X with no material difference found") rather than a full table-plus-trade-off
treatment, and put the space you saved toward the dimensions and patterns that actually
differentiate. The reader's attention is a resource too — don't spend it on ground that isn't
contested.

## Step 5 — Produce the output

Follow `references/output-formats.md` for the mode chosen in Step 1. Both modes end with a
closing caveat naming exactly which sources were checked and where they came up short — this is
not boilerplate, it's the reader's guide to how much independent confirmation they still need
before relying on any given figure commercially.

## A note on using this alongside other skills

This skill is currently standalone — it doesn't assume it's being called from anywhere else, and
you can invoke it directly for a one-off comparison with no other document in play. If you're
also working on an HLD, RFI response, or similar deliverable that needs a competitive-positioning
section, run this skill's methodology for that section and paste the result in, rather than
duplicating the research logic inline — the sourcing discipline here is the same either way.
