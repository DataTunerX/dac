# Standard Comparison Dimensions

These are the default attributes to compare for an enterprise storage competitive analysis.
Not every dimension applies to every workload — pick the ones relevant to what's actually being
evaluated (a Tier 0/1 mission-critical block comparison and a scale-out AI/ML file comparison
need different subsets) rather than mechanically filling in all of them. Treat this as a menu,
not a checklist that must be fully populated every time.

## Mandatory requirements are not a dimension

If the user has stated hard requirements (a required certification, a minimum capacity, a
pass/fail RFP gate), check those first per `SKILL.md` Step 3, before working through the
dimensions below. A vendor failing a stated mandatory requirement is excluded from the
dimension-by-dimension comparison and reported separately — don't let it also occupy a column in
the tables below as if it were still a candidate.

## When architecture is the actual differentiator

Dimensions 1, 2, 4, and 5 below are often where vendors describe genuinely different mechanisms
using the same marketing words ("active-active," "scale-out," "global cache"). When one of these
looks like it's actually driving the comparison rather than just being background context, check
`references/architecture-differentiators.md` for the specific pattern before writing the row —
it names the traps and what to check for, so the comparison tests the mechanism rather than
repeating the label.

## Requirement-traceable compliance matrix

When the user has an actual RFP or requirements document, build the primary comparison table
from *its* requirement or clause numbers instead of (or as well as) the dimensions below. This
is the format a customer's own evaluation actually checks against, and it's more useful to the
reader than a generic-dimension table because they can jump straight to "does this meet clause
3.1.7" rather than translate between the RFP's language and a dimension menu.

Row and column shape:

- One row per requirement/clause, quoted or closely paraphrased from the source document,
  identified by its own number.
- One column per vendor/model, the proposed/incumbent product first.
- Each cell holds a status, not free text: **Fully Compliant**, **Partially Compliant** (state
  the limitation), **Not Compliant**, or **Not Documented** (per `source-authority.md` — never
  interchangeable with Not Compliant). Adopt the RFP's own status vocabulary if it defines one
  (some use FC/PC/NC or similar abbreviations); otherwise use the labels above.
- Group rows under the RFP's own section headings if it has them, rather than re-sorting
  everything into this skill's dimension categories — preserving the customer's own structure is
  part of what makes the matrix traceable.

This doesn't replace the dimension-level tables below where the RFP is silent on something that
still matters for the workload (see Step 1's "what the customer is actually focused on" — the
RFP's own emphasis is usually the strongest signal for which of the dimensions below still
deserve a table of their own). Use both when both add something; don't force every finding into
one format if the RFP only covers part of the comparison.

## 1. Capacity & Efficiency
- Max raw / effective / usable capacity (per node, per system, at scale)
- Data reduction method and ratio (dedup, compression, erasure coding, RAID efficiency) —
  distinguish a **guaranteed** ratio from a **marketing/"up to"** ratio; they are not the same
  claim and should never be presented as equivalent
- Minimum/base configuration and scaling increments

## 2. Performance
- IOPS, latency, throughput/bandwidth — always note the test configuration if stated (block size,
  read/write mix, protocol) since these numbers are not comparable across vendors without it
- Cache architecture (size, tiering)

## 3. Data Protection & Replication
- Synchronous replication technology and RPO/RTO characteristics
- Asynchronous replication technology and typical distance/bandwidth constraints
- Snapshot, clone, and immutability (WORM) capabilities
- Ransomware/anomaly detection — native vs. requires a separate appliance

## 4. Protocol & Architecture Convergence
- Supported protocols (FC, iSCSI, NVMe-oF variants, NFS, SMB, S3, HDFS, etc.)
- Whether block, file, and object are served from one unified platform/OS or require separate
  products — this matters a lot for total-cost-of-ownership and management-plane comparisons,
  so call it out explicitly rather than letting it disappear into a protocol list

## 5. Availability & Resilience
- Published availability claim (e.g. "six nines") — always note whether it's a design target, a
  measured SLA, or an unqualified marketing statement
- Failure-domain tolerance (controller/node/enclosure failures tolerated)
- Non-disruptive upgrade / scale-out claims

## 6. Security & Compliance
- Encryption (at-rest algorithms, in-flight, key management)
- Relevant certifications (FIPS 140-2/3, Common Criteria, regional certifications)
- Access control / multi-tenancy model

## 7. Management & Automation
- Unified control plane across product lines, or separate consoles per product
- AIOps / predictive capabilities, API/automation maturity

## 8. Commercial (only if materials actually cover it)
- Licensing model (perpetual, subscription, consumption-based)
- Publicly known list pricing or TCO studies — this is the dimension most likely to be missing
  from public vendor materials; don't estimate a number that isn't published anywhere, just say
  pricing wasn't available in reviewed materials

---

## Presentation pattern

For each dimension actually in scope, build one attribute-rows × vendor-columns table (the
proposed/incumbent product plus each competitor as a column). After the table(s) for a given
workload tier or product category, add a short "Read on [tier/category]" paragraph that says in
plain language who's actually ahead on what, and where the comparison is limited by what materials
were available — see `output-formats.md` for the exact structure and a worked example.
