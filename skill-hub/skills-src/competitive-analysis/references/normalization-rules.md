# Normalization Rules

A comparison is only honest after normalization. Two individually-accurate numbers placed
side by side can still add up to a false claim, if they weren't measured the same way. Check a
cross-vendor numeric or capability statement against the relevant rule below before writing it
as a difference — if normalization isn't possible with what was found, report each vendor's
figure on its own and say explicitly that they aren't comparable, rather than computing a delta
that doesn't mean anything.

**Configuration.** Compare configurations that meet the same stated requirement, not
configurations at the same price point or the same model tier. If one vendor needs more nodes or
shelves than another to meet the same capacity/performance ask, that's itself a finding worth
reporting — say so, don't normalize it away.

**Performance.** Never place two performance figures side by side unless the test conditions
match: block size, read/write mix, access pattern, queue depth, dataset size, data-reduction
state, and latency ceiling. If any of these differ or weren't stated, the figures aren't
comparable — say that plainly instead of implying a winner.

**Capacity.** Raw and usable-after-protection capacity are the default basis for comparison.
Only compare "effective" (post-reduction) capacity when every vendor's reduction ratio is either
customer-supplied and applied uniformly, or stated with its counting methodology and the
methodologies are actually equivalent — vendors don't all count the same things (some fold in
thin provisioning, snapshots, and clones; some count only compression and dedup). Where
methodologies differ or aren't stated, report each vendor's effective-capacity figure with its
own methodology and skip the delta.

**Protection overhead.** Usable-capacity comparisons are only meaningful at equivalent protection
level and equivalent failure-domain guarantee. A RAID 6 usable figure and an erasure-coded 8+2
usable figure covering different failure domains are not the same product decision, even if the
raw percentages look close.

**Recency.** Compare current generally-available releases across all vendors. Don't compare a
proposed/incumbent product's current release against a competitor's superseded one (or vice
versa) — record each vendor's version and publication date so a reader can check the comparison
is actually apples-to-apples.

**Configuration maxima.** Compare limits that apply to the configuration actually being
evaluated, not a vendor's family-wide maximum. A published ceiling that requires a configuration
incompatible with something else in scope (a specific node count, a specific fabric) isn't the
number that applies here — note the conflict if you find one.

**Degraded-state figures.** If the workload or requirement cares about performance/availability
under failure, compare degraded-mode figures specifically, not healthy-state figures. If a
vendor doesn't publish a degraded-mode number, that's "not documented" for that comparison, not
automatically a loss against a vendor that does publish one — a published number and an absent
one aren't yet a finding about which product actually performs better degraded.

**Constraint-adjusted capability.** Score a capability as it would actually function under any
constraints the customer or workload has stated (no vendor telemetry, air-gapped operation, data
residency, network segregation) — not as marketed in an unconstrained environment. A
headline analytics or automation feature that requires vendor-cloud connectivity is a different
finding when the deployment can't have that connectivity.
