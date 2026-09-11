# Architecture Differentiators

A short list of named architectural patterns where vendors routinely use the same marketing
label for materially different mechanisms. Consult this when controller architecture, cache
design, backend/media access, or scaling claims are actually driving the comparison — not as a
checklist to run on every dimension every time. Each entry names what to investigate and a
guardrail against overclaiming from the label alone. Treat every entry as a hypothesis to test
with sourced facts, not a predetermined conclusion — the pattern tells you what question to ask,
not what the answer is for any given vendor.

This list is expected to grow. It currently covers eight patterns in controller/cache/backend
architecture and a couple of adjacent areas (NDU scope, guarantee programs); protocol semantics,
security/compliance architecture, data-reduction architecture, and others are natural additions
as they come up in real comparisons. Add a new entry in the same shape (pattern name, what to
check, a don't-overclaim guardrail) whenever a comparison surfaces a marketing label that's
hiding a real mechanism difference worth naming for next time — that's a better trigger for
adding one than trying to anticipate the full list up front.

And regardless of how long this list gets: if two vendors turn out equivalent on a given
pattern, that's a valid finding to report briefly, not a cue to keep digging for a difference
that isn't there. See `SKILL.md` Step 4 on how much space equivalent points should get in the
output.

## Controller access model: symmetric active-active vs. ALUA

Both get marketed as "active-active." The distinction: a symmetric active-active array serves
I/O for a given volume through any controller with no performance penalty; an ALUA array has a
preferred/owning controller per volume and serves non-owner I/O through a penalized or
redirected path. **Check**: does the vendor's own documentation describe per-path performance
states, a "preferred path," or a trespass/failover event for non-optimized access? If so, it's
ALUA-style regardless of what the marketing page calls it. **Don't overclaim**: a system that
avoids ALUA's classic asymmetry through fast internal forwarding may still perform very well —
the point isn't that ALUA is worse, it's that the two mechanisms have different failure and
performance profiles that matter for specific workloads (e.g., multipathing behavior under a
controller failure).

## Cache scope: global vs. HA-pair (or per-node) cache

"Global cache" sometimes means genuinely pooled across every controller in the system, and
sometimes means each HA pair (or node) has its own cache with no sharing beyond that pair.
**Check**: can a write be cached and protected by any controller regardless of which one owns
the underlying volume, and does the documentation describe a global write-protection domain, or
a per-pair one? **Don't overclaim**: a per-pair cache design isn't a defect — it bounds the
blast radius of a cache failure to that pair, which is itself a resilience property. Report the
mechanism and let the trade-off paragraph carry the "which matters more here" judgment.

## Backend access: shared vs. owned backend

Whether every controller in the system can reach every drive/enclosure directly, or whether
drives are owned by a specific controller/pair and accessed by others only through forwarding.
**Check**: look for language about backend fabric topology, drive ownership, or "non-owner"
I/O paths in admin/architecture guides. **Don't overclaim**: an owned-backend design can still
scale well for many workloads — the relevant question is whether rebalancing, rebuild, or
failover in this specific architecture requires data movement or forwarding hops that an
owned-backend design doesn't.

## Media/transport path: is "NVMe" end-to-end?

A system can legitimately say "NVMe" while meaning NVMe host connectivity only, NVMe drives
behind a SAS expander, or true end-to-end NVMe (host → controller → backend → media). **Check**:
trace the full path in the vendor's own architecture documentation — host transport, controller
interconnect, backend transport, and media — and score each hop, since "NVMe" as a single word
doesn't tell you which hops actually use it. **Don't overclaim**: a hybrid path isn't
automatically inferior for every workload, but a comparison that doesn't check all four hops
is comparing labels, not architectures.

## Cache vs. tier semantics

"Cache" and "tier" get used interchangeably in marketing but describe different failure
behavior: a cache holds a copy of data whose authoritative copy lives elsewhere; a tier holds
the only copy of the data placed on it. **Check**: what happens to data on the fast media if
that media fails — is there always another copy elsewhere (cache) or not (tier)? **Don't
overclaim**: neither model is inherently better; the distinction matters most for data-loss risk
and cost, and should be stated explicitly rather than assumed from the word used.

## Scale-out claims and existing workloads

A "scale-out" system may add capacity/performance smoothly for *new* volumes or filesystems
while an *existing* volume remains bound to the controller(s) it was created on, with a real
per-node ceiling. **Check**: does the vendor's documentation describe non-disruptive migration
or rebalancing of existing LUNs/volumes across newly added nodes, or only new-object placement?
**Don't overclaim**: this doesn't make a scale-out claim false — it makes it narrower than the
word implies, and that narrowness is exactly what to state in the comparison.

## Non-disruptive upgrade (NDU) scope

"Non-disruptive" or "rolling" upgrade claims vary in what's actually non-disruptive: whether it
covers every supported upgrade path (major version jumps, not just patch releases), whether
performance is materially degraded during the rolling upgrade, and whether all protocols/paths
stay available throughout. **Check**: release notes and upgrade guides usually state the actual
scope more precisely than the marketing page. **Don't overclaim**: partial non-disruptiveness
(e.g. patch-level only) is a real and common finding, not a failure to investigate further.

## Guarantee programs (data-reduction, availability)

A capacity or availability guarantee is only as meaningful as its exclusions and remedy.
**Check**: what specifically is excluded (encrypted data, pre-compressed data, particular
workload types), and is the remedy additional capacity, a credit, or something else? **Don't
overclaim**: the existence of a guarantee isn't itself a differentiator — two vendors' "4:1
guarantees" with different exclusion lists aren't the same commitment, and that's the finding
worth stating.
