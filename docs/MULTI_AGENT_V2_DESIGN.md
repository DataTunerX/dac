# DAC Multi-Agent V2 Design and Implementation Plan

Status: Draft for review, revised after empirical review
Branch baseline: `demo-ready-2026-09-11` (`ce44277`)
Development branch: `dev-multi-agent-v2`
Main branch reviewed: `origin/main` (`b39b6c2`)
Last updated: 2026-09-12

Reviewer entry point: [Multi-Agent V2 Decision Summary](MULTI_AGENT_V2_DECISION_SUMMARY.md)

## 1. Decision Summary

DAC Multi-Agent V2 will use a lead-and-participant collaboration model.

The routing agent remains a control-plane component. It interprets explicit
routing intent, discovers healthy candidates, collects structured capability
feedback, selects one lead skill agent, and grants that lead a bounded pool of
contributor agents. It does not create or execute the task DAG.

The selected lead skill agent owns the execution lifecycle:

1. Understand the complete user request.
2. Define the answer and evidence contract.
3. Create and validate a task DAG.
4. Assign DAG nodes to itself or approved participant agents.
5. Execute, validate, recover, and replan within explicit budgets.
6. Produce the final answer.

Participant skill agents execute only the task assigned by the lead. They may
use their local skills and tools, but they do not reinterpret the complete user
request, discover peers, delegate work, or produce the final multi-agent answer.

The core responsibility split is:

```text
Routing decides who should lead and who may contribute.
The lead decides what work must be done and owns the DAG.
Participants execute assigned work and report results, evidence, and gaps.
```

## 2. Motivation

The current and main-branch implementations contain useful collaboration
building blocks, but routing quality and execution quality are coupled in ways
that make failures difficult to prevent.

Observed failure patterns include:

- Simple routing ignores an explicit user-selected agent.
- Capability checks overclaim and return inconsistent confidence scores.
- A candidate wins because it proposes an attractive collaborative plan, but
  routing forwards the request through a single-root path that cannot execute
  that plan.
- A contributor can be treated as a complete handler.
- One mutable hop counter is consumed across sibling delegations, making
  execution order affect remaining collaboration capacity.
- Skill-agent retries can repeat the same ineffective work or discard a useful
  draft.
- Execution Flow records useful completed results but omits blocked, skipped,
  dependency-failed, and hop-exhausted work.
- Capability and Execution Flow code is duplicated between skill-agent and
  orchestrator-agent and has already begun to drift.
- Capability fan-out is unbounded, repeated inside candidate planning and lead
  execution, and grows toward `O(N^2)` model calls as the registry grows.
- Completed participant output can be overwritten by later tasks that were never
  dispatched, so paid-for evidence disappears before final synthesis.

Multi-Agent V2 addresses these problems without turning the routing agent into
a centralized workflow engine.

### 2.1 Measured baseline and provenance

The following live observations make this a performance project as well as a
correctness project. They are directional baselines from different cluster,
model, image, and workload combinations; Phase 0 must reproduce them under a
controlled replay before they become final SLOs.

Capability-check latency per agent, where routing waits for the slowest response:

| Environment | Samples | p50 | p90 | Maximum |
|---|---:|---:|---:|---:|
| Current-tag image on `test-cluster` | 51 | 4.9 s | 7.5 s | 12.1 s |
| `fw-worker` runtime image | 225 | 16.4 s | 43.9 s | 69.6 s |

Observed routing and end-to-end latency:

| Flow | Observed latency |
|---|---:|
| Current-tag, multiple candidates | 49.7 s and 51.2 s before lead work |
| Current-tag, one candidate | 8.6 s and 9.5 s before lead work |
| `fw-worker`, 15 agents | 45 s p50 and 116 s maximum before lead work |
| Same two-domain question, current tag | approximately 5.5 minutes end to end |
| Same two-domain question, `fw-worker` | 8 minutes 37 seconds end to end |

One current-tag request generated approximately 65 to 70 model calls. About 60
were concerned with deciding who should answer: 13 initial capability checks,
three candidate rebroadcasts over the same 13 agents, three pre-plans, one plan
comparison, and additional lead-side probes and replanning. The resulting fan-out
is the dominant routing cost and trends toward `O(N^2)`.

The live `fw-worker` routing image also exposes a release-provenance problem. Its
runtime source contains a weighted pre-plan selector using 67 percent capability
confidence and 33 percent plan quality. That implementation is not present in
the reviewed `origin/main` commit `b39b6c2`, and no reviewed Git commit contains
the runtime symbol. Therefore this document distinguishes:

- Git-verified behavior in `ce44277` and `b39b6c2`.
- Measured behavior in the deployed `fw-worker` routing image.

The desired image-tag convention already exists on `test-cluster`, whose routing
image is tagged `demo-ready-2026-09-11-ce44277-amd64`. `fw-worker` instead runs
the opaque `21-amd64` tag. Requiring source-bearing immutable tags is enforcement
of an existing practice, not a new build-system design.

No causal claim should be made that main's `capability_chain` caused the observed
4.9-second to 16.4-second p50 difference. The runtime log shape is consistent
with that implementation, but the source mismatch and uncontrolled environment
make attribution an inference. Phase 0 must reproduce the delta from traceable
images before treating it as established.

Every Phase 0 image must carry a Git SHA and dirty-state label and log them at
startup. An untraceable image cannot be used as the authoritative source-code
baseline even when its runtime logs remain valid operational evidence.

### 2.2 Why this work is necessary

The current problems are not isolated prompt-quality issues. They come from an
ambiguous division of responsibility across routing and execution.

Today, the routing agent asks candidate agents whether they can handle a query,
may ask them to create competing plans, and then selects one root. The selected
root independently plans again and may attempt to discover or delegate to other
agents. As a result, the plan used to choose the root is not necessarily the
plan that is executed, and the agents assumed by the winning plan are not
necessarily available in the selected root's execution context.

This was visible in the reviewed routing run:

- `Wwybsj-TDB-Agent` had the strongest direct ownership of the museum records.
- `Art-history-TDB-Agent` was selected because its pre-plan described a cleaner
  division of work among several specialists.
- The request was then forwarded through a single-root execution path.
- The selected agent's planned delegations were blocked by collaboration/hop
  conditions, so the reason it won the routing decision could not be executed.

That is a contract failure between routing and execution. Adjusting a confidence
threshold or rewriting the selection prompt may change which agent fails, but
it does not make the selected plan executable.

A second live run demonstrated direct result loss. The lead planned three tasks
for `Paper-Answering-TDB-Agent`. The first invocation spent 176 seconds and
returned 3,104 characters. The next two tasks hit the shared hop limit and each
wrote the 37-character `No available agent can do this task` placeholder into a
dictionary keyed by agent name. The last write replaced the validated result;
final synthesis received 37 characters instead of 3,104. The skipped tasks
produced no task record or progress event.

This is not merely an observability defect. Task results must be append-only and
keyed by `task_id`; a task that did not run must never overwrite another task's
result. Every planned task, including one blocked before dispatch, must reach a
visible terminal ledger state.

Capability feedback is also internally inconsistent. In observed runtime output,
Geo-environment returned `can_handle=true` at `0.70` while its explanation said
it could neither complete the request nor provide a useful contribution.
Anthropology-sociology returned `0.85` with the same contradiction, and
Philosophy-theory returned `0.87` while saying it could not complete the request.
The main-branch arithmetic mean allows a mandatory zero data-coverage score to be
averaged up to the threshold. Its module header documents a different,
multiplicative rule from the implementation below it.

Rephrasing the capability request changes the answer as well. In one current-tag
run, Architecture changed from `can_handle=false` in the routing probe to `0.98`
in the mid-execution probe; SkillAgent changed from `0.44` to `0.93`. V2 removes
this disagreement by reusing one versioned report for assignment and by sending a
task contract, not another capability question, to a participant.

Reviewed source anchors:

- `ce44277`: `skill-agent/agent/skill_agent.py`,
  `_dispatch_mid_exec_delegation`, keys results by agent and silently writes the
  hop-exhausted placeholder.
- `ce44277`: `skill-agent/agent/skill_agent.py`,
  `_execute_plan_and_mid_exec`, consumes one mutable hop value across siblings.
- `ce44277`: `skill-agent/agent/skill_agent_turn.py`, `execute`, restores that
  value for the entry agent at the next turn boundary.
- `b39b6c2`: `skill-agent/agent/capability_chain.py`, `step_score` and
  `aggregate`, implement arithmetic means despite the multiplicative module
  contract.

### 2.3 User impact

Without this redesign, users can observe:

- Explicit agent choices being ignored.
- A domain specialist losing to a less appropriate agent with a more confident
  capability response or more polished plan.
- Answers that omit required domains even though appropriate agents exist.
- A selected agent claiming that no agent can perform work that the router had
  already identified as available.
- Long waits caused by repeated planning, capability checks, and failed
  delegations.
- Final answers that hide missing evidence or present incomplete work as
  complete.
- Inconsistent results when the same request is run more than once.

These behaviors make the platform difficult to trust for evidence-sensitive
work. A user cannot tell whether an answer is weak because the data is absent,
the wrong lead was selected, a participant failed, or collaboration was never
actually possible.

### 2.4 Engineering and operational impact

The current role overlap also creates ongoing engineering cost:

- Routing, skill-agent, and orchestrator-agent each contain overlapping
  selection, planning, capability, retry, and collaboration logic.
- A fix in one execution path does not consistently apply to the others.
- Recursive delegation makes limits difficult to define: the current hop value
  acts partly as depth, partly as a total delegation count, and partly as a
  switch that disables collaboration.
- Capability feedback does not provide a stable executable contract, so routing
  has to infer too much from prose and uncalibrated scores.
- Free-form result propagation increases prompt size and makes retries repeat
  completed work.
- Missing failure events make production diagnosis dependent on manually
  correlating logs from several pods.
- Model, tool, timeout, and registry failures can look like genuine lack of
  domain capability.

Adding more planner prompts to this structure would increase latency and cost
while preserving the same ownership ambiguity.

### 2.5 Why the lead-and-participant model addresses it

The proposed model creates one owner for each decision:

- Routing owns admission, lead selection, and the allowed collaboration scope.
- The lead owns task decomposition, the DAG, recovery, and the final answer.
- A participant owns only the correctness of its assigned task result.

This makes the routing decision executable by construction. The lead receives
the contributor agents at handoff, plans only against that scope, and validates
the full DAG before work begins. Participants cannot create hidden recursive
plans or redirect the request to additional agents.

It also preserves domain autonomy. The router does not become a long-running
workflow engine and does not need to understand how every skill should solve a
problem. The lead can adapt its plan after seeing real domain results, while the
router stays comparatively fast, stateless, and operationally simple.

The expected outcomes are:

- More predictable lead selection.
- Executable collaboration plans.
- Lower planning and capability-check duplication.
- Clearer task and failure ownership.
- Better use of specialists without uncontrolled recursive delegation.
- Generic support for new skills and domains.
- Auditable answers whose missing evidence can be traced to a specific task or
  capability gap.

## 3. Goals

### 3.1 Functional goals

- Honor explicit user agent selection as a routing constraint.
- Select a lead based on ownership, lead eligibility, specificity, health, and
  demonstrated reliability rather than raw self-reported confidence.
- Give the lead an explicit, bounded contributor pool.
- Let the lead create and own an executable DAG.
- Give participants a simple, deterministic execution contract.
- Support local execution, information gathering, TDB querying, summarization,
  extraction, transformation, and other generic skill tasks.
- Support iterative lead-to-participant work such as Lead -> A -> Lead -> B ->
  Lead -> A without participant-to-participant recursion.
- Preserve useful partial work and expose unsupported conclusions.
- Make routing, assignment, execution, evidence, failure, and retry decisions
  auditable.

### 3.2 Quality goals

- Accepted plans are executable before their first remote task is dispatched.
- Required capabilities cannot be averaged away by unrelated strong scores.
- Participants cannot silently expand the collaboration graph.
- Failure and budget semantics are deterministic.
- The architecture works for generic skills, not only TDB-oriented skills.
- Existing A2A agents can be supported through a versioned compatibility path.

### 3.3 Operational goals

- Permit shadow comparison with the current routing implementation.
- Allow independent rollback of capability V2, lead selection, participant
  mode, lead mode, and Execution Flow V2.
- Keep secrets out of rendered manifests, pod arguments, logs, and traces.
- Surface registry, vector-index, model, tool, and agent health to routing.

### 3.4 Performance and efficiency goals

These are provisional rollout targets, anchored to the live measurements above.
Phase 0 must confirm the workload definitions and replace them only through an
explicit design review:

- Routing overhead, from query receipt until lead work starts: p50 at most 8
  seconds and p95 at most 15 seconds for the agreed golden workload.
- Capability model calls per query: at most `K`, where the initial configurable
  candidate limit is 5; registry, manifest, health, and vector checks do not
  require model calls.
- Capability, pre-plan, and participant requests cause zero nested capability
  rebroadcasts.
- Validated participant-result retention: 100 percent. No accepted output may be
  overwritten, dropped during replanning, or replaced by a blocked task.
- Planned but undispatched tasks represented in the ledger: 100 percent.
- Two-domain end-to-end latency: provisional p50 at most 3 minutes on the
  controlled workload.
- Solo routing must not regress more than 10 percent from its controlled V1
  baseline and must skip multi-agent DAG planning when no contributor is needed.
- Per-run model calls, total tokens, A2A calls, and latency are measured and
  bounded; adding agents must not reintroduce quadratic fan-out.
- Routing-decision model tokens and cost are at most 25 percent of the controlled
  V1 multi-candidate baseline.
- At fixed hardware, registry size, and request concurrency, steady-state routing
  throughput does not regress from the controlled V1 baseline.

## 4. Non-Goals

- The routing agent will not own or execute the collaboration DAG.
- Participant agents will not perform unrestricted recursive delegation.
- V2 will not assume that an LLM confidence number is a calibrated probability.
- V2 will not hardcode TDB-specific planning rules into the generic
  skill-agent runtime.
- V2 will not require all existing agents to upgrade atomically.
- V2 will not make every participant see the full conversation or all other
  participant outputs.
- V2 will not use embeddings as proof that an agent can execute a task.

## 5. Architecture

### 5.1 Component responsibilities

| Component | Responsibilities | Explicitly does not do |
|---|---|---|
| Routing agent | Parse routing intent, discover candidates, validate health, collect capability reports, select lead, construct contributor scope, forward the assignment | Create DAG nodes, schedule tasks, aggregate participant results |
| Lead skill agent | Define answer contract, create DAG, validate assignments, schedule work, replan, enforce budgets, synthesize final answer | Select contributors outside its granted scope without approval |
| Participant skill agent | Validate one task, execute local skills/tools, validate output, return a structured result | Replan the user request, discover peers, delegate, synthesize global final answer |
| Skill runtime | Load the exact configured skills, expose available tools, execute a local task, track attempts | Claim skills or tools that are unavailable at runtime |
| Skill package | Declare inputs, outputs, operations, data scope, limitations, evidence behavior, and local procedure | Encode cross-agent topology or routing policy |
| Agent registry | Store agent cards, protocol version, runtime health, indexing health, and endpoints | Infer executable capability from embedding similarity alone |

### 5.2 High-level flow

```text
User
  |
  v
Routing Agent
  |  1. Resolve explicit agent intent
  |  2. Retrieve candidate cards
  |  3. Collect CapabilityReportV2
  |  4. Select lead and contributor scope
  v
Lead Skill Agent
  |  5. Build and validate DAG
  |  6. Execute local nodes and dispatch participant nodes
  |
  +------> Participant A ---- TaskResult ----+
  |                                         |
  +------> Participant B ---- TaskResult ----+--> Lead validation/replan
  |                                         |
  +------> Participant A ---- TaskResult ----+
  |
  v
Final answer and Execution Flow
```

### 5.3 Required invariants

1. Exactly one lead owns one collaboration run.
2. Only the lead may add, remove, or reassign DAG nodes.
3. A participant receives one task contract per invocation.
4. A participant cannot delegate to another agent.
5. Every remote task target must be present in the lead's contributor scope.
6. Every accepted dependency must reference a real output from an earlier node.
7. Every required final output must have an assigned producer.
8. A failed mandatory dependency blocks its downstream nodes until the lead
   repairs or replaces it.
9. Routing selection and execution assignment are versioned, structured, and
   traceable.
10. The final answer is returned by the lead, not by the router or a participant.
11. Task results are append-only, keyed by `task_id`, and never keyed only by
    agent name. A blocked or undispatched task cannot replace another result.
12. Consumptive budgets decrease monotonically within a run and are never reset
    at a turn or round boundary. Every rejected dispatch emits a terminal event.

## 6. Execution Modes

Lead and participant behavior are runtime modes of skill-agent. They are not
separate versions of each skill package.

### 6.1 Lead mode

Selected with request metadata:

```json
{
  "execution_mode": "lead",
  "protocol_version": "multi-agent-v2"
}
```

Lead mode enables:

- Full-query interpretation.
- Answer-contract creation.
- DAG planning and validation.
- Local task execution.
- Participant task dispatch.
- Result validation and evidence tracking.
- Bounded recovery and replanning.
- Final synthesis.

Lead mode does not permit unrestricted registry discovery. It plans against the
contributor scope granted by routing.

### 6.2 Participant mode

Selected with request metadata:

```json
{
  "execution_mode": "participant",
  "protocol_version": "multi-agent-v2"
}
```

Participant mode enables:

- Assigned-task and input validation.
- Local skill selection.
- Local tool use.
- Bounded local retries.
- Output-contract validation.
- Structured success, partial, blocked, or failure reporting.

Participant mode disables:

- Full-query planning.
- Capability rebroadcast.
- Peer discovery.
- Cross-agent delegation.
- Mid-execution contributor selection.
- Global answer synthesis.
- Conversation-history or long-term-memory writes. A participant may return
  task-scoped artifacts, but persistence is owned outside participant mode.

### 6.3 Solo execution

A query that needs only one agent still uses lead mode with an empty contributor
scope, but takes a solo fast path. It skips multi-agent DAG generation, remote
orchestration, and contributor validation. Deterministic user constraints and
required output checks still apply; a trivial solo request must not incur extra
model calls merely to recreate a one-node DAG.

## 7. Shared Protocol Package

Create a small, versioned Python package for multi-agent contracts, tentatively
named `agent_contracts`. It should be consumed by routing-agent, skill-agent,
orchestrator-agent, and test fixtures.

The package should contain only schemas, validation helpers, enums, and
serialization logic. It must not contain routing policy, LLM prompts, network
clients, or execution logic.

Initial schema set:

- `CapabilityCheckRequestV2`
- `CapabilityReportV2`
- `LeadAssignment`
- `ContributorDescriptor`
- `TaskNode`
- `ParticipantTask`
- `TaskResult`
- `ContributorExpansionRequest`
- `ContributorExpansionResponse`
- `ExecutionEventV2`
- `ExecutionBudget`
- `AnswerContract`
- `ArtifactReference`
- `EvidenceReference`
- `SchemaDescriptor`
- `InputBinding`
- `AgentRuntimeStatus`

All messages must include `protocol_version`. Consumers must reject unsupported
major versions and may ignore unknown optional fields within a supported major
version.

Task input and output typing uses a versioned JSON Schema registry. It is
extensible rather than a closed enumeration:

- DAC owns a small core envelope and common schema IDs.
- Skill packages may advertise immutable, namespaced schema IDs and versions.
- A planner may select only schemas advertised by a scoped agent; it cannot
  invent an output type.
- The runtime resolves the schema ID and validates structured results.
- An unknown type may be carried as an opaque artifact, but it cannot satisfy a
  typed downstream dependency without a declared adapter.

The first common output type is `dac.claim-evidence/v1`. It contains a claim,
`source_id`, optional `statement_id`, optional character span, evidence status,
supporting and conflicting evidence, and unresolved limitations. This matches
the evidence shape already required by the live TDB workloads without making
the generic runtime TDB-specific.

Core schemas are shipped in `agent_contracts`. The agent-registry service stores
immutable namespaced `SchemaDescriptor` records keyed by schema ID, version, and
content digest. Skill upload validates and registers package-authored schemas;
runtime AgentCards advertise only successfully registered descriptors. Schema
content is never accepted directly from an LLM plan.

## 8. Capability Feedback V2

### 8.1 Purpose

Capability feedback answers two separate questions:

1. Can this agent lead the complete request?
2. What concrete work can this agent perform as a participant?

It must not compress both questions into one confidence number.

### 8.2 Request

```json
{
  "protocol_version": "multi-agent-v2",
  "message_type": "capability_check",
  "query": "...",
  "explicit_target": null,
  "requirements": [
    {
      "requirement_id": "req-1",
      "description": "Retrieve museum registration facts",
      "required_output_schemas": ["dac.claim-evidence/v1"]
    }
  ],
  "attachments": [],
  "constraints": {
    "language": "zh",
    "evidence_required": true
  }
}
```

Routing may omit `requirements` during the first compatibility phase. In that
case, the agent returns requirement descriptions with stable local IDs and the
router normalizes them before comparison.

### 8.3 Response

```json
{
  "protocol_version": "multi-agent-v2",
  "agent_id": "agent-wwybsj",
  "agent_name": "Wwybsj-TDB-Agent",
  "capability_manifest_version": "sha256:...",
  "runtime_status_ref": {
    "readiness_generation": 42
  },
  "lead": {
    "eligible": true,
    "ownership": "primary",
    "owned_requirements": ["req-1"],
    "missing_requirements": ["req-2", "req-3"],
    "reason": "Owns the primary collection records and can synthesize contributed evidence."
  },
  "contributions": [
    {
      "contribution_id": "contrib-1",
      "requirement_ids": ["req-1"],
      "operations": ["retrieve", "summarize"],
      "required_inputs": ["artifact names or identifiers"],
      "produced_output_schemas": ["dac.claim-evidence/v1"],
      "data_domains": ["wwybsj"],
      "constraints": [],
      "evidence": ["skill:tdb-wwybsj-answering"]
    }
  ],
  "limitations": [],
  "runtime_metrics": {
    "recent_success_rate": null,
    "recent_p95_latency_ms": null
  }
}
```

### 8.4 Capability rules

- `lead.eligible=true` requires a loaded lead-capable runtime and ownership of
  the primary request or an explicit user selection.
- Health is a gate, not a ranking bonus.
- Every contribution declares concrete required inputs and produced outputs.
- A contribution is useful only when it satisfies a final requirement or
  produces an input required by another known requirement.
- Missing mandatory data, operations, output forms, or constraints cannot be
  averaged away.
- Negative declarations such as unsupported operations or unavailable data are
  preserved as limitations.
- Agent names and embedding similarity are not evidence of capability.
- If the response contradicts itself, routing rejects it as invalid rather than
  normalizing it into a positive result.
- Eligibility is derived deterministically from structured fields after schema
  validation. Routing must not infer the verdict by searching free-form reason
  text for multilingual phrases such as "cannot".
- Routing resolves the report's exact `capability_manifest_version` and intersects
  every claimed data domain, operation, input type, output schema, required tool,
  and side-effect class with that manifest in code.
- A report that claims an undeclared capability is contradictory and rejected;
  the candidate LLM cannot expand its authority by asserting a larger match.
- The manifest is authoritative for what an agent is permitted to claim, not
  proof that execution will succeed. Runtime readiness and observed reliability
  remain independent gates and ranking evidence.

### 8.5 Fit scores

V2 may include a `fit_score` for ordering otherwise valid candidates, but it is
not a probability and does not determine executability.

Executability uses hard gates:

```text
required inputs available or producible
AND required data/resources available
AND required operation supported
AND required output producible
AND mandatory constraints satisfied
```

Only candidates passing those gates may be ranked. Initial ranking should be
lexicographic rather than an opaque weighted sum:

```text
explicit target
> healthy lead eligibility
> primary ownership
> required-output coverage
> domain specificity
> observed reliability
> lower cost/latency
> deterministic name tie-break
```

If a numeric score is later displayed as confidence, it must first be calibrated
against an annotated evaluation corpus.

The product formula documented by the main-branch capability module must not be
adopted blindly. A mandatory zero is a hard-gate failure, but multiplying all
dimensions and then multiplying all step scores introduces severe query-length
bias and does not produce a calibrated probability. Executability is Boolean;
`fit_score` ranks only the candidates that passed every mandatory gate.

## 9. Routing Design

### 9.1 Routing lifecycle

```text
Parse intent
-> Resolve explicit target
-> Retrieve candidates
-> Apply health gates
-> Collect capability feedback
-> Validate feedback
-> Select lead
-> Build contributor scope
-> Create LeadAssignment
-> Forward to lead
-> Stream lead output unchanged
```

### 9.2 Explicit user selection

Routing must recognize an explicit request such as:

```text
Must use All-in-One-TDB-Agent to answer this question.
```

Rules:

1. Resolve exact names and configured aliases, not fuzzy substring matches.
2. If the selected agent exists, is healthy, and supports lead mode, select it.
3. If it exists but is unhealthy, fail clearly and do not silently reroute.
4. If it cannot lead, explain the limitation and do not silently substitute an
   unrelated lead.
5. The explicitly selected lead may still receive contributors unless the user
   prohibited collaboration.
6. The routing trace records the parsed directive and resolution result.

### 9.3 Candidate discovery

Candidate discovery should use multiple sources:

- Exact agent-name or alias match.
- Declared skill capability metadata.
- Declared data domains and operations.
- Registry filtering by protocol support and health.
- Vector retrieval for recall only.

Embedding similarity only proposes candidates. It never establishes ownership
or executability.

Routing performs model-based capability checks only for a bounded candidate set,
initially `K=5`. Deterministic agent/skill/domain/operation matches and
highest-recall vector results are ranked into those slots after health filtering.
An exact user target occupies a guaranteed slot and cannot be removed by the cap;
normally it is the only lead candidate checked. Top-K vector retrieval alone is
insufficient because an index can be stale or incomplete; the fallback policy
must be measured against the golden corpus.

Validated capability reports are reusable within a freshness window. Cache keys
include canonical agent ID, capability-manifest version, normalized requirement
signature, and runtime-readiness generation. Ordinary heartbeat refresh does not
invalidate the report unless readiness changes. An exact raw-query hash is not the
primary key because semantically equivalent requests would rarely hit it.
Capability checks, pre-plan requests, and participant tasks carry a control flag
that forbids peer discovery or nested rebroadcast.

The cached report is reusable only for requirement IDs present in its request. If
the lead discovers a genuinely new requirement, it uses the bounded contributor
expansion protocol in §13. It must not issue an ad hoc mid-execution capability
probe with a differently worded sub-task.

### 9.4 Lead selection

A good lead generally owns the central object, data source, or business intent
of the request and can integrate participant results.

For a query about museum collection objects plus historical and anthropological
interpretation:

- The collection agent is the expected lead because it owns the primary objects
  and source records.
- History and anthropology agents are contributors.
- An art-history agent is a contributor only if a concrete art-history output is
  required.
- A generalist may lead when explicitly selected or when no specialist owns the
  primary request and its lead capability is demonstrated.

Routing must not select a lead because that candidate generated a more detailed
or more ambitious pre-plan. If an optional lead proposal is retained, it is
checked only for feasibility and cannot override explicit intent, ownership, or
health.

The deployed `fw-worker` image demonstrates why. For one live request,
Paper-Answering, Wwybsj, and Art-history all reported confidence `1.0`; weighted
final scores were `0.9769`, `0.9604`, and `0.9835`. The 67/33 confidence/plan
formula therefore selected Art-history entirely on plan presentation among the
tied candidates. This behavior belongs to the deployed runtime image, not the
reviewed `b39b6c2` source tree.

Pre-make-plan is retired when V2 lead selection becomes active in Phase 4 and is
deleted with the legacy routing path in Phase 8. During migration it must not
trigger capability rebroadcast from candidate agents.

### 9.5 Contributor scope

The router gives the lead a set of eligible contributors, not a task plan.

Each contributor descriptor includes:

- Canonical agent ID and display name.
- Protocol version.
- Concrete contributions.
- Required inputs and produced outputs.
- Runtime health.
- Known limitations.
- Timeout and payload constraints.

The contributor scope includes an immutable `scope_revision`. The lead addresses
contributors by canonical agent ID, and the runtime resolves endpoints from the
registry rather than trusting an LLM-provided endpoint. Cryptographic signing is
not required for the initial same-trust-boundary rollout; if scope crosses a
trust boundary, signer, key distribution, and verification require a separate
security design.

### 9.6 No-match and degraded behavior

- No healthy lead: return a clear routing failure.
- Healthy lead but no useful contributors: send an empty pool; the lead decides
  whether it can answer alone or return unsupported requirements.
- Legacy-only lead: use the legacy single-agent adapter and mark the run as
  degraded; do not imply V2 collaboration.
- Registry/vector outage: use cached cards only when freshness policy permits,
  and expose the degraded discovery state.
- Capability timeout: do not treat timeout as `can_handle=false`; record
  `unknown` and exclude from automatic selection unless explicitly requested.

## 10. Lead Assignment

```json
{
  "protocol_version": "multi-agent-v2",
  "execution_mode": "lead",
  "collaboration_id": "uuid",
  "query": "...",
  "routing_intent": {
    "explicit_agent": null,
    "collaboration_allowed": true
  },
  "lead": {
    "name": "Wwybsj-TDB-Agent",
    "selection_reason": "Primary owner of the museum collection objects."
  },
  "contributors": [],
  "answer_contract": {
    "required_sections": [],
    "required_fields": [],
    "evidence_required": true,
    "citation_requirements": []
  },
  "budget": {
    "deadline_ms": 600000,
    "max_tasks": 10,
    "max_rounds": 3,
    "max_concurrency": 3,
    "max_attempts_per_task": 2,
    "max_pool_expansions": 1,
    "max_model_calls": 20,
    "max_total_tokens": 120000,
    "max_a2a_calls": 20
  },
  "trace": {
    "run_id": "...",
    "trace_id": "...",
    "user_id": "..."
  }
}
```

Routing provides any answer-contract fields that can be extracted
deterministically from the request. The lead completes and validates the
contract before planning.

## 11. Lead-Agent Loop

### 11.1 State machine

```text
RECEIVED
  -> CONTRACT_DEFINED
  -> DAG_PLANNED
  -> DAG_VALIDATED
  -> EXECUTING
  -> VALIDATING_RESULTS
  -> REPLANNING (bounded, optional)
  -> SYNTHESIZING
  -> FINAL_VALIDATION
  -> COMPLETED | PARTIAL | FAILED | CANCELLED
```

Every state transition emits an `ExecutionEventV2`. State transitions are
validated in code; they are not inferred later from log text.

### 11.2 Answer contract

The lead derives an answer contract from the query before creating tasks. The
contract identifies:

- Required answer components.
- Required structure or fields.
- Evidence and provenance requirements.
- Language and formatting constraints.
- Required distinctions, such as observation versus inference.
- Prohibited unsupported claims.
- Completion rules.

The answer contract remains generic. A skill may contribute optional validators
for domain-specific formats, but the runtime owns contract enforcement.

### 11.3 DAG planning

Each `TaskNode` contains:

```json
{
  "task_id": "task-1",
  "objective": "Retrieve museum registration facts for the named objects",
  "assigned_agent": "Wwybsj-TDB-Agent",
  "execution_target": "local",
  "depends_on": [],
  "required_inputs": [],
  "expected_outputs": [
    {
      "name": "object_claims",
      "schema_id": "dac.claim-evidence/v1"
    }
  ],
  "evidence_requirements": ["primary source identifiers"],
  "mandatory": true,
  "status": "planned",
  "attempt": 0
}
```

The lead planner may use an LLM to propose the DAG. Code validates the proposal
before execution.

### 11.4 DAG validation

Validation must confirm:

- Task IDs are unique.
- The graph is acyclic.
- Every dependency references an existing node.
- Every required input comes from the user, an attachment, or a named upstream
  output.
- Output-to-input compatibility is based on artifact IDs and resolved versioned
  schemas, not free-text names or the existence of any earlier step.
- Every participant is in the granted contributor scope.
- The assigned participant declared the required operation and output.
- All mandatory final-answer components have producers.
- The graph fits task, concurrency, round, attempt, and deadline budgets.
- No participant task asks the participant to delegate or select another agent.

An invalid plan is returned to the lead planner with machine-readable validation
errors. It is never partially executed.

### 11.5 Scheduling

The scheduler is deterministic:

1. Mark nodes with satisfied dependencies as ready.
2. Start ready nodes up to `max_concurrency`.
3. Pass only required upstream artifacts and the participant task contract.
4. Record each result and validate it against expected outputs.
5. Unblock dependent nodes only after mandatory outputs validate.
6. On failure, apply the task's retry or reassignment policy.
7. Stop dispatching new work after cancellation or deadline expiration.

Independent sibling tasks should run concurrently and must not consume each
other's depth or retry allowance.

### 11.6 Recovery and replanning

Recovery is driven by structured result fields:

- `missing_inputs`
- `missing_capabilities`
- `invalid_outputs`
- `limitations`
- `error_code`
- `retryable`

Allowed recovery actions:

- Retry the same participant with corrected inputs.
- Assign an alternate approved participant.
- Split an oversized task.
- Add a new task using an existing contributor.
- Remove an optional task.
- Request one additional contributor from routing.
- Finish with an explicitly partial answer.

The lead must not repeat an identical failed invocation. An invocation
fingerprint should include agent, objective, normalized inputs, expected outputs,
and relevant skill/tool selection.

### 11.7 Final synthesis

The lead synthesizer receives validated outputs and compact evidence references,
not arbitrary full agent transcripts.

Before completion, the lead verifies:

- Every mandatory answer-contract item is present or explicitly marked
  unsupported.
- Claims link to the evidence returned by participants.
- Conflicting participant results are identified rather than silently merged.
- Observations, interpretations, and unestablished claims remain distinct when
  the request requires it.
- The final response contains substantive content rather than orchestration
  commentary.

## 12. Participant Task and Result

### 12.1 ParticipantTask

```json
{
  "protocol_version": "multi-agent-v2",
  "execution_mode": "participant",
  "collaboration_id": "uuid",
  "task_id": "task-2",
  "objective": "Retrieve comparable Han tomb jade evidence",
  "inputs": {
    "object_types": ["jade cicada", "jade suit pieces", "jade bi"]
  },
  "expected_outputs": [
    {
      "name": "historical_claims",
      "schema_id": "dac.claim-evidence/v1"
    }
  ],
  "evidence_requirements": [
    "source_id",
    "statement_id when available",
    "source span when available"
  ],
  "constraints": {
    "do_not_delegate": true,
    "deadline_ms": 120000,
    "max_local_steps": 12
  },
  "trace": {
    "parent_task_id": "task-1",
    "run_id": "...",
    "trace_id": "..."
  }
}
```

### 12.2 TaskResult

```json
{
  "protocol_version": "multi-agent-v2",
  "collaboration_id": "uuid",
  "task_id": "task-2",
  "agent_name": "History-TDB-Agent",
  "status": "success",
  "outputs": [
    {
      "name": "historical_claims",
      "schema_id": "dac.claim-evidence/v1",
      "schema_digest": "sha256:...",
      "data": []
    }
  ],
  "artifacts": [],
  "evidence": [],
  "missing_inputs": [],
  "missing_capabilities": [],
  "limitations": [],
  "error": null,
  "retryable": false,
  "metrics": {
    "duration_ms": 0,
    "tool_calls": 0,
    "local_steps": 0
  }
}
```

Allowed statuses:

- `success`: expected mandatory outputs validated.
- `partial`: useful outputs exist, but one or more expected outputs are missing.
- `blocked`: required input is missing or invalid.
- `failed`: execution failed and no valid required output was produced.
- `cancelled`: lead or platform cancelled the task.

### 12.3 Participant local loop

```text
Validate task
-> Select local skill(s)
-> Plan bounded local operations
-> Execute tools
-> Validate outputs
-> Return TaskResult
```

The participant may use multiple local tool calls and, when necessary, multiple
local skills. It may not change the assigned objective or create remote tasks.

When the participant cannot complete the task, it reports what is missing. It
must not return `No available agent can do this task` because peer selection is
the lead's responsibility.

## 13. Contributor Expansion

A fixed initial pool may omit a needed capability. V2 supports a bounded
control-plane request from the lead to routing.

```json
{
  "protocol_version": "multi-agent-v2",
  "message_type": "contributor_request",
  "collaboration_id": "uuid",
  "missing_capability": "retrieve dated inscription evidence",
  "required_inputs": ["cave identifier"],
  "expected_output_schemas": ["dac.claim-evidence/v1"],
  "excluded_agents": ["agents already attempted"],
  "reason": "No current contributor can produce the required primary evidence."
}
```

Routing may return zero or more approved contributors. It does not add DAG
nodes, choose task dependencies, or execute the new contributor.

Expansion rules:

- Disabled during the first implementation milestone.
- Bounded by `max_pool_expansions`.
- Subject to the same health and capability validation as initial routing.
- Recorded in routing and execution traces.
- Never initiated by a participant.

## 14. Collaboration Topology and Budgets

### 14.1 Default topology

V2 initially uses a star topology:

```text
Lead -> Participant
Lead -> Participant
Lead -> Participant
```

Participants return to the lead. They do not call each other. Iterative
collaboration is represented as multiple lead-owned DAG nodes, not a recursive
delegation chain.

This topology removes the need for cross-participant hop accounting in the
initial V2 implementation.

### 14.2 Separate budgets

Do not use one mutable `current_hop` value as a proxy for all resource limits.

Use separate fields:

| Budget | Meaning |
|---|---|
| `deadline_ms` | Wall-clock deadline for the collaboration |
| `max_tasks` | Maximum DAG nodes created by the lead |
| `max_rounds` | Maximum plan/validate/replan rounds |
| `max_concurrency` | Maximum simultaneously running tasks |
| `max_attempts_per_task` | Retry and alternate-assignment attempts for one node |
| `max_pool_expansions` | Maximum requests for additional contributors |
| `max_local_steps` | Participant local tool/skill steps |
| `max_result_bytes` | Participant result and artifact metadata limit |
| `max_model_calls` | Maximum lead and participant model round-trips combined |
| `max_total_tokens` | Maximum input and output tokens across the run |
| `max_a2a_calls` | Maximum remote agent invocations across all tasks and retries |

Consumptive budgets such as deadline, tasks, rounds, attempts, model calls,
tokens, and A2A calls are monotonic for one collaboration run and are never
restored at a turn boundary. `max_concurrency` is an instantaneous capacity, not
a consumptive counter; capacity is released when a task finishes. Exhaustion is
recorded before execution is skipped.

If nested leads are introduced later, depth is immutable per path:

```text
child_depth_remaining = parent_depth_remaining - 1
```

Siblings receive the same depth value. One sibling never consumes another
sibling's depth.

## 15. Execution Flow V2

Execution Flow V2 is a typed execution ledger used by the lead, observability
systems, and debugging tools.

### 15.1 Event fields

```text
event_id
event_type
collaboration_id
run_id
trace_id
task_id
parent_task_id
agent_name
execution_mode
status
attempt
timestamp
duration_ms
input_artifacts
output_artifacts
evidence
error_code
message
budget_snapshot
```

### 15.2 Required event types

- `routing_intent_resolved`
- `lead_selected`
- `contributor_scope_created`
- `answer_contract_defined`
- `dag_proposed`
- `dag_validation_failed`
- `dag_validated`
- `task_ready`
- `task_started`
- `task_succeeded`
- `task_partial`
- `task_blocked`
- `task_skipped`
- `task_failed`
- `task_cancelled`
- `task_reassigned`
- `replan_started`
- `contributor_expansion_requested`
- `contributor_expansion_resolved`
- `budget_exhausted`
- `final_validation_failed`
- `final_answer_created`
- `run_completed`
- `run_failed`
- `run_cancelled`

Blocked, skipped, dependency-failed, invalid-upstream, timeout, and
budget-exhausted events must be retained. They are essential inputs to recovery
and must not be omitted because no tool execution occurred.

### 15.3 Storage and transport

- Use A2A structured artifacts or metadata when supported.
- Retain line-frame compatibility only for legacy streaming clients.
- Use globally unique IDs, not IDs derived only from turn and local task number.
- Deduplicate by `event_id`.
- Store full results as artifacts and pass references through the ledger.
- Keep large results out of logs and planner prompts.

### 15.4 Planner context

The lead planner receives a compact projection:

- Completed output summaries and artifact references.
- Unresolved answer-contract requirements.
- Failed invocation fingerprints.
- Missing inputs and capabilities.
- Remaining budgets.

It does not receive the complete raw event ledger or repeated full participant
responses on every round.

## 16. Skill Capability Metadata

The runtime should derive capability reports from the exact loaded skill
inventory and live tool availability.

Skill packages should gradually add structured declarations for:

- Supported operations.
- Required input types.
- Produced output types.
- Data domains and data ownership.
- Evidence and provenance support.
- Read/write side effects.
- Runtime tool requirements.
- Known exclusions and limitations.
- Whether results are snapshots or current data.

During migration, the runtime may derive these fields from `SKILL.md`, but the
derived result must be visible and testable. An LLM-derived declaration should
not be treated as equivalent to a package-authored declaration.

For V2 contributor eligibility, supported operation, required input shape,
produced output schema, required tools, and side-effect class are mandatory. A
reviewed generated manifest may temporarily satisfy migration, but a free-form
capability response cannot. Data ownership, evidence behavior, and limitations
remain required for automatic lead eligibility when relevant to the request.

The current skill-agent already generates part of its AgentCard from successfully
loaded skills. V2 extends and makes this behavior authoritative rather than
rebuilding it as a greenfield feature. Configured but failed skills and tools
must not be advertised, and every card carries a capability-manifest hash so a
cached report can be invalidated when the loaded inventory changes.

## 17. Health Model

Routing requires a consolidated health view:

```text
agent_ready
heartbeat_fresh
protocol_supported
skills_loaded
required_tools_ready
model_ready
registry_index_status
recent_execution_health
```

Health states are `ready`, `degraded`, `unavailable`, and `unknown`.

- `unavailable` candidates cannot be selected automatically.
- `unknown` candidates are excluded unless explicitly selected or policy allows
  a clearly marked degraded attempt.
- `degraded` candidates may be selected only when the affected capability is not
  required by the task.
- Vector indexing failure affects discovery but does not necessarily mean the
  agent execution endpoint is unhealthy; these states remain distinct.

This health model requires a delivery substrate; it cannot be inferred from the
current AgentCard or liveness timestamp alone:

1. Each agent publishes an `AgentRuntimeStatus` heartbeat keyed by canonical
   agent ID and containing card revision, capability-manifest hash, supported
   protocol versions, skill/tool/model readiness, and observation timestamps.
2. The registry stores the latest status separately from the static AgentCard
   and joins or exposes it through its agent-discovery API.
3. The registry/indexing service publishes index generation and per-card index
   state independently from endpoint liveness.
4. Routing evaluates freshness and requirement-specific readiness before it
   requests model-based capability feedback.
5. Recent execution health is produced from normalized terminal task outcomes,
   not self-reported by the candidate in a capability response.

## 18. Failure Handling

| Failure | Owner | Required behavior |
|---|---|---|
| Explicit agent not found | Routing | Fail clearly; do not silently substitute |
| Lead capability response invalid | Routing | Exclude response and record validation error |
| Contributor omitted from scope | Lead | Do not dispatch; replan or request expansion |
| DAG dependency invalid | Lead validator | Reject entire proposed DAG before execution |
| Participant missing input | Participant then lead | Return `blocked`; lead supplies input, reassigns, or marks unsupported |
| Tool unavailable | Participant | Return structured failure; never advertise success |
| Participant timeout | Lead scheduler | Cancel invocation; retry/reassign within budget |
| Participant partial result | Lead | Preserve valid artifacts; plan only missing work |
| Mandatory task exhausted | Lead | Produce partial final answer or fail according to answer contract |
| Lead failure | Platform/routing | Do not let routing synthesize an answer; optionally restart from checkpoint with approved fallback lead in a later milestone |
| Deadline exceeded | Lead/platform | Cancel active tasks and return best validated partial result |
| Registry/index outage | Routing | Use allowed cache policy or return degraded discovery error |

## 19. Security and Isolation

- Move LLM API keys from command arguments and literal Deployment environment
  values to Kubernetes Secrets referenced with `valueFrom.secretKeyRef` or,
  preferably, mounted secret files.
- No rendered Helm manifest, Deployment `args`, or literal environment `value`
  may contain an API key.
- A key found in a live manifest or process argument is treated as exposed and
  rotated through a separate incident action before canary.
- Do not include secret values in capability reports, AgentCards, Execution
  Flow, errors, or Langfuse metadata.
- Treat participant output as untrusted input to the lead.
- Validate and size-limit artifacts before injecting content into prompts.
- Pass only task-relevant context to participants.
- Enforce contributor scope by canonical agent ID and trusted endpoint, not by
  an LLM-generated name.
- Preserve namespace and authorization boundaries during contributor discovery.
- Record side-effect intent and require explicit policy before running write or
  destructive skills.

## 20. Backward Compatibility

### 20.1 Legacy capability responses

Routing may adapt legacy `can_handle`, `can_contribute`, and `confidence`
responses into a degraded `CapabilityReportV2`, but legacy feedback cannot
claim verified inputs, outputs, or lead eligibility.

Legacy candidates may be used for solo execution. A legacy contributor may enter
a V2 scope only through an explicit adapter with a successful protocol handshake
and contract-conformance test; unknown legacy behavior is excluded.

All currently observed workload agents on `test-cluster` and `fw-worker` use the
same skill-agent image within each cluster, so V2 protocol support can be shipped
to the active fleet together. Compatibility remains necessary for rolling
updates, external agents, and future mixed versions, but it should not force the
initial pool to remain empty once the common image supports V2.

### 20.2 Legacy execution

If the selected agent does not support `multi-agent-v2`:

- Forward through the existing single-agent path.
- Do not send participant tasks.
- Mark the trace `execution_protocol=legacy`.
- Preserve current progress and final-answer streaming behavior.

### 20.3 Feature flags

Initial flags:

```text
MULTI_AGENT_V2_ENABLED=false
CAPABILITY_REPORT_V2_ENABLED=false
ROUTING_LEAD_SELECTION_ENABLED=false
SKILL_AGENT_LEAD_MODE_ENABLED=false
SKILL_AGENT_PARTICIPANT_MODE_ENABLED=false
CONTRIBUTOR_EXPANSION_ENABLED=false
EXECUTION_FLOW_V2_ENABLED=false
```

Flags must be configurable in Helm values and visible in startup logs. Main must
not silently fall back to a code default because a Helm setting was removed.

### 20.4 Conversation, memory, and multi-turn ownership

- The routing boundary persists the user/assistant conversation exactly once
  after receiving the lead's terminal result. The lead returns history metadata
  but does not race the router to write the same turn.
- The lead may read the approved conversation context and write lead-owned
  execution memory after final validation. Participants receive only task-scoped
  context and do not write long-term or group memory by default.
- `collaboration_id` identifies one user turn and execution run. A follow-up turn
  receives a new ID and links to `parent_collaboration_id`; history and artifacts
  are propagated explicitly rather than by silently reusing a mutable DAG.
- Execution hints, capability reports, and contributor scopes carry expiry and
  version fields. A follow-up cannot reuse them after their manifest, health, or
  scope revision is stale.

## 21. Code-Level Design

### 21.1 New shared package

Tentative structure:

```text
agent-contracts/
  pyproject.toml
  agent_contracts/
    capability.py
    collaboration.py
    execution.py
    artifacts.py
    schemas.py
    health.py
    validation.py
```

Build one versioned wheel and consume the same wheel from routing-agent,
skill-agent, and orchestrator-agent. Do not copy schema modules between
components.

### 21.2 Routing agent

Primary file:

```text
routing-agent/routing_agent/server.py
```

Extract responsibilities into focused modules:

```text
routing_agent/intent.py
routing_agent/candidate_discovery.py
routing_agent/capability_client.py
routing_agent/lead_selection.py
routing_agent/contributor_scope.py
routing_agent/lead_handoff.py
```

The existing simple and broadcast implementations remain available behind
legacy routing modes during rollout.

### 21.3 Skill agent

Primary files:

```text
skill-agent/agent/skill_agent.py
skill-agent/agent/skill_agent_turn.py
```

Split the current mixed executor into:

```text
skill_agent/lead_executor.py
skill_agent/participant_executor.py
skill_agent/local_task_executor.py
skill_agent/dag.py
skill_agent/scheduler.py
skill_agent/result_validation.py
skill_agent/recovery.py
```

- `LeadExecutor` owns the full-query state machine.
- `ParticipantExecutor` handles one `ParticipantTask`.
- `LocalTaskExecutor` wraps SkillRunner and is shared by both.
- `DagValidator` contains deterministic graph and assignment checks.
- `Scheduler` contains concurrency, cancellation, deadline, and retry handling.

### 21.4 Agent registry and skill upload

The registry stores canonical agent IDs, aliases, cards, schema descriptors, and
the latest `AgentRuntimeStatus` as separate versioned records. Its discovery API
returns a consistent card/status view and exposes heartbeat freshness and index
generation without requiring routing to join hidden Redis structures.

Skill upload validates package-authored schemas, rejects a changed schema body
under an existing immutable version, and records the resulting schema digest in
the loaded-skill manifest. Agent heartbeat producers publish readiness changes;
ordinary heartbeat renewal does not change the readiness generation.

### 21.5 Orchestrator agent

The orchestrator-agent currently contains overlapping collaboration and
capability logic. It should consume the shared contracts and either:

1. Act as a lead-compatible adapter for semantic-group agents, or
2. Remain on the legacy protocol until a separate migration is approved.

Do not independently implement another version of capability aggregation,
Execution Flow, or participant task schemas.

The initial V2 release targets skill-agent only. Both reviewed clusters currently
run workload agents as skill agents and no orchestrator-agent workload pods were
observed, so this covers 100 percent of measured live agent traffic. The
orchestrator adapter is a later compatibility milestone and does not block the
skill-agent canary.

### 21.6 Skill SDK

SkillRunner should expose a task-oriented API in addition to the existing query
API:

```python
async def execute_task(
    task: ParticipantTask,
    *,
    deadline: Deadline,
    progress_callback: ProgressCallback | None = None,
) -> TaskResult:
    ...
```

It should preserve the best valid draft, expose attempted skills and tools,
return normalized reason codes, and support bounded alternate-skill recovery.

## 22. Testing Strategy

### 22.1 Golden routing corpus

Create an annotated corpus from real observed runs and synthetic edge cases.

Each case records:

- Query and relevant history.
- Explicit agent directive, if any.
- Expected lead.
- Allowed contributors.
- Forbidden selections.
- Required answer components.
- Expected task ownership.
- Required evidence.
- Expected degraded or failure behavior.

Initial real cases should include:

- Explicit All-in-One agent request.
- Wwybsj, Art History, and History lead-selection case.
- Contributor-only multi-domain query.
- Agent with unrelated skills loaded through watch-all.
- Unavailable Tavily tool.
- Model tool-call incompatibility.
- Empty tool-call nudge after a useful draft.
- Skill timeout shorter than its evidence request.
- Registry vector-index failure.
- Three tasks assigned to one participant where the first returns a valid result
  and the later two are blocked before dispatch. The valid result must remain and
  all three task IDs must reach terminal ledger states.
- Shared-hop exhaustion across siblings and a new lead turn. No consumptive
  budget may reset or be silently skipped.
- The same versioned capability report reused by routing and lead assignment,
  with no differently worded participant capability probe.
- A capability report whose prose explanation conflicts with its structured
  fields.

### 22.2 Unit tests

- Protocol parsing and version negotiation.
- Capability contradiction validation.
- Manifest/report intersection rejects undeclared domains, operations, schemas,
  tools, and side-effect classes.
- Exact output-to-input dependency matching.
- Lead-selection precedence.
- Explicit user-selection behavior.
- Contributor-scope filtering.
- DAG cycle and missing-dependency rejection.
- Scheduler readiness and concurrency.
- Retry fingerprint deduplication.
- Result-contract validation.
- Budget and deadline enforcement.
- Execution event state transitions.
- Append-only TaskResult retention keyed by `task_id`.
- Monotonic consumptive budgets across turn and replan boundaries.
- Output schema resolution, unknown-schema handling, and adapter validation.
- Capability cache invalidation by manifest and health generation.
- A newly discovered requirement requests contributor expansion and never starts
  an ad hoc participant capability probe.

Remove or correct tests that assert an agent with zero required data coverage can
handle the complete query.

### 22.3 Contract tests

Run routing-agent and skill-agent against a fake A2A peer that can return:

- V2 success.
- V2 partial result.
- V2 invalid schema.
- Legacy response.
- Timeout.
- Stream interruption.
- Duplicate events.
- Oversized artifacts.

### 22.4 Local integration tests

Provide a local harness that starts:

- An in-memory or containerized registry.
- One routing agent.
- One lead agent.
- Two participant agents.
- Stub skills and tools with deterministic outputs.

The harness must test lead selection, DAG creation, concurrent tasks,
dependency passing, participant failure, reassignment, final synthesis, and
cancel/deadline behavior without requiring Kubernetes.

It must also replay the result-clobbering case: one 3,104-character successful
result followed by two undispatched tasks for the same agent. The summary input
must retain the full successful result and two explicit blocked results.

### 22.5 Cluster tests

Deploy behind feature flags on `test-cluster`:

- Shadow routing decisions without changing the active result.
- Compare legacy selected root with V2 selected lead and contributors.
- Run an opt-in namespace or agent set through V2 execution.
- Verify traces, cancellation, resource limits, and pod restart behavior.
- Canary a small percentage of non-destructive queries.
- Refuse baseline attribution when an image lacks Git SHA and dirty-state labels
  or when runtime source does not match the recorded revision.

## 23. Acceptance Criteria

### 23.1 Routing

- Explicit valid agent selection is honored in 100 percent of golden cases.
- An unavailable explicit agent produces a clear error and zero silent
  substitutions.
- Specialist lead precision is at least 95 percent on the annotated corpus.
- Candidate generation includes the annotated expected lead in at least 99
  percent of non-explicit golden cases and 100 percent of explicit-target cases.
- Candidate limiting remains shadow-only until those recall thresholds pass on
  the required observation window; excluded shadow candidates cannot change the
  active route.
- Contributor-only agents are never selected as complete handlers.
- Unhealthy agents are never automatically selected.
- Every lead handoff contains the decision evidence and complete contributor
  scope.

### 23.2 Capability

- Missing a mandatory data source, operation, output, or constraint prevents a
  complete-handler result.
- Every contribution has concrete inputs and outputs.
- Orphan outputs do not qualify an agent as a contributor.
- Contradictory capability reports are rejected.
- Advertised skills and tools match the runtime-loaded inventory.
- Every accepted capability claim is a subset of the exact versioned manifest;
  an undeclared domain, operation, schema, tool, or side effect is rejected.
- Routing and lead assignment reuse the same versioned report for the same
  requirement set; participant execution performs no second capability probe.
- Deliberate repeated evaluations of the same fixture produce zero contradictory
  structured `eligible`/`can_contribute` verdicts after deterministic validation.

### 23.3 Collaboration

- Every accepted DAG passes deterministic pre-execution validation.
- Every remote task targets an approved contributor.
- Participants perform zero peer delegations.
- Independent siblings execute without sharing a mutable depth budget.
- Identical failed invocations are not repeated.
- Partial participant outputs survive retries and replanning.
- Validated task output is retained in 100 percent of runs and cannot be
  overwritten by another task for the same agent.
- Mandatory output gaps appear in the final answer rather than being silently
  filled by the LLM.

### 23.4 Observability and operations

- Every task reaches a terminal ledger status.
- Blocked, skipped, failed, cancelled, and budget-exhausted tasks are visible.
- Route, lead, contributor, assignment, retry, and final-validation decisions
  can be reconstructed from one collaboration ID.
- No API key appears in Kubernetes command arguments, literal Deployment
  environment values, rendered Helm manifests, process listings, logs, or traces.
- Registry indexing health is separately visible from endpoint health.
- Every deployed image reports a Git SHA and dirty state that match its runtime
  source.

### 23.5 Performance and efficiency

- Controlled routing overhead is p50 at most 8 seconds and p95 at most 15
  seconds from query receipt until lead work begins.
- A query performs at most `K` model-based capability checks, initially `K=5`,
  and performs zero nested capability rebroadcasts.
- Planned but undispatched tasks appear in the ledger in 100 percent of runs.
- The controlled two-domain workload completes at p50 at most 3 minutes.
- Solo execution stays within 10 percent of its controlled V1 baseline.
- Model calls, tokens, A2A calls, and dollar cost remain within configured run
  budgets at p50 and p95.
- Routing-decision tokens and cost are at most 25 percent of the controlled V1
  multi-candidate baseline.
- Steady-state routing throughput does not regress under the controlled
  concurrency workload.
- Registry growth from `N` to `2N` does not produce quadratic model-call growth.

## 24. Implementation Plan

Implementation should use small reviewable pull requests. Each PR must include
tests and keep its feature disabled by default until the rollout phase.

### Phase 0: Baseline and design approval

Deliverables:

- Approve this architecture and protocol ownership.
- Capture current-tag, Git-verified main, and exact deployed-image behavior for
  the golden corpus; do not treat an untraceable image as main-branch source.
- Record baseline routing accuracy, collaboration completion, latency, retries,
  model calls, tokens, A2A calls, cost, throughput, and tool failures.
- Record both the deployed `CROSS_SG_MAX_HOP=2` behavior and a diagnostic replay
  at hop at least 3. The diagnostic run occurs in a controlled environment and
  does not require changing production cluster configuration.
- Enable Langfuse or an equivalent structured local trace sink for the controlled
  replay; `test-cluster` currently has no active Langfuse backend.
- Add image Git SHA and dirty-state labels plus startup logging before collecting
  authoritative baselines.
- Agree the provisional §3.4 and §23.5 targets or replace them with reviewed
  workload-specific targets.
- Correct documentation that contradicts current implementation.
- Decide the ownership and release process for `agent_contracts`.

Exit criteria:

- Reviewers agree that routing selects scope and the lead owns execution.
- Golden cases have expected lead and contributor annotations.
- Baseline reports include p50/p95 latency, call counts, tokens, cost, result
  retention, and planned-task visibility.
- No routing or execution behavior changes.

### Phase 0.5: Immediate legacy correctness fixes

Deliverables, as separate small pull requests:

- Key delegation results by `task_id`, preserve every non-empty validated result,
  and prevent blocked tasks from overwriting completed output.
- Emit progress and terminal events on every pre-dispatch hop or budget skip.
- Persist a known-unavailable SkillSync state with bounded backoff so a skill such
  as `tavily-search` with a missing required key is not redownloaded every 30
  seconds indefinitely.

Exit criteria:

- The result-clobbering and hop-exhaustion golden cases pass on the legacy path.
- All skipped tasks are visible without parsing free-form logs.
- The fixes do not change candidate selection or lead routing behavior.

### Phase 0.6: Fan-out shadow and guarded enforcement

Deliverables:

- Compute and log the proposed top-K set, ordering evidence, and would-be
  exclusions while the full legacy candidate set continues to determine the
  active route.
- Run shadow collection for at least 24 hours and 200 eligible non-explicit
  queries; supplement low-volume traffic with the golden replay corpus.
- Measure expected-lead inclusion, explicit-target inclusion, domain coverage,
  route disagreement, model calls, latency, and nested rebroadcasts.
- After the recall gate passes, enforce candidate limiting behind a dedicated
  rollback flag in a separate pull request.
- Suppress nested capability/pre-plan rebroadcast behind an independent flag and
  replay it before enforcement because it can change candidate plan content.

Exit criteria:

- Expected-lead inclusion is at least 99 percent for non-explicit cases and 100
  percent for explicit targets before candidate exclusion is enabled.
- Shadow logs show the correct lead's rank and exclusion reason for every
  disagreement.
- Enforced model-based capability checks are capped at `K`, and each behavior
  change can be disabled independently.

### Phase 1: Shared contracts and validation

Deliverables:

- Add `agent_contracts` package.
- Implement V2 schemas and version negotiation.
- Define the extensible output-schema registry, publish
  `dac.claim-evidence/v1`, and prohibit planner-invented schema IDs.
- Define `AgentRuntimeStatus`, registry storage/join behavior, heartbeat payload,
  freshness, and index-generation contracts.
- Implement registry storage and discovery joins for synthetic schema and runtime
  status records, plus heartbeat transport for readiness generations.
- Add deterministic capability, DAG, TaskResult, and event validators.
- Add compatibility adapters for legacy capability responses.
- Add contract tests to routing-agent and skill-agent.

Exit criteria:

- Routing and skill-agent consume the same schema package.
- Unsupported versions and contradictory messages fail predictably.
- No schema implementation is copied between components.
- Core and namespaced schemas register, resolve, and reject immutable-version
  conflicts; synthetic runtime health is visible through discovery.

### Phase 2: Participant mode

Deliverables:

- Add execution-mode dispatch to skill-agent.
- Implement `ParticipantExecutor` and `LocalTaskExecutor`.
- Disable broadcast, peer discovery, delegation, and global synthesis in
  participant mode.
- Add TaskResult validation, normalized reason codes, deadline propagation, and
  best-draft preservation.
- Remove unavailable tools from the local runtime inventory.

Exit criteria:

- Participant mode completes deterministic lookup, TDB query, summarization,
  extraction, and transformation fixtures.
- Participant mode cannot perform remote delegation.
- Partial and blocked results preserve useful evidence.

### Phase 3: Capability feedback V2

Deliverables:

- Generate capability reports from loaded skills and live tools.
- Separate lead eligibility from participant contributions.
- Replace arithmetic confidence gating with hard executability rules.
- Implement concrete input/output and ownership declarations.
- Publish health from loaded skills, live tools, model checks, and normalized
  execution outcomes; add contradiction validation.
- Correct main-branch capability tests that currently bless false handlers.

Exit criteria:

- Agents missing a required data domain are not complete handlers.
- Contribution outputs map to real requirements or downstream inputs.
- Eligibility is derived by hard gates; numeric fit never rescues a mandatory
  zero. Scores are not multiplied across all steps as a proxy probability.
- Routing reuses a report for the same versioned requirement set and participant
  execution performs no independent capability probe.

### Phase 4: Routing lead selection and handoff

Deliverables:

- Add explicit agent-intent parsing and canonical alias resolution.
- Add V2 candidate discovery and health gates.
- Limit model-based capability checks to the bounded, recall-protected candidate
  set and reuse valid cached reports.
- Implement deterministic lead selection.
- Build contributor scopes from concrete contribution reports.
- Create and forward `LeadAssignment`.
- Preserve full root-candidate and rejection evidence in the trace.
- Retire pre-make-plan selection when V2 selection is enabled and prevent legacy
  pre-plan requests from causing nested broadcasts during transition.
- Keep legacy routing available behind a feature flag.

Exit criteria:

- Explicit-selection and specialist-ownership cases pass the golden corpus.
- Routing creates no DAG and executes no task nodes.
- Every V2 lead receives an auditable contributor scope.

### Phase 5: Lead mode and DAG execution

Deliverables:

- Implement `LeadExecutor`, answer-contract builder, and DAG planner.
- Implement deterministic DAG validation.
- Implement scheduler, concurrency, deadlines, cancellation, and task retries.
- Dispatch `ParticipantTask` only to scoped contributors.
- Validate TaskResult outputs and evidence.
- Implement bounded replan and alternate assignment.
- Implement final answer-contract validation and synthesis.

Exit criteria:

- Multi-agent local integration suite passes.
- The known Art History selection/execution mismatch cannot be reproduced.
- Participants never create recursive collaboration chains.

### Phase 6: Execution Flow V2

Deliverables:

- Implement typed event emission and state validation.
- Add globally unique IDs and artifact references.
- Record failures that existing Execution Flow omits.
- Add compact planner-context projection.
- Connect routing and lead events under one collaboration ID.
- Preserve legacy progress streaming for the UI.

Exit criteria:

- A complete run can be reconstructed without parsing free-form logs.
- Planner context stays within configured size limits.
- Duplicate or replayed events are idempotently handled.

### Phase 7: Fixed-pool shadow and canary

Deliverables:

- Add Helm values for every V2 feature flag and budget.
- Run shadow lead selection on `test-cluster`.
- Run opt-in V2 execution with a fixed contributor pool and expansion disabled.
- Compare current-tag, Git-verified main, exact deployed-image, and V2 metrics.
- Canary a small percentage of non-destructive requests.
- Publish rollback instructions and operational dashboards.

Exit criteria:

- Fixed-pool routing and execution pass all applicable acceptance criteria.
- §23.5 performance and efficiency gates pass on the controlled corpus; improved
  reasoning quality alone is not sufficient for rollout.
- V2 can be disabled without redeploying legacy agent code.

### Phase 8: Contributor expansion and default rollout

Deliverables:

- Implement lead-to-router `ContributorExpansionRequest` after the fixed-pool
  canary passes.
- Apply health, capability, namespace, and budget policy.
- Add newly approved contributors to an immutable scope revision.
- Record scope revisions in Execution Flow.
- Canary expansion independently before enabling it by default.
- Promote fixed-pool V2 first; expansion may remain disabled if its gate fails.

Exit criteria:

- Only the lead can request expansion.
- Routing supplies candidates but never edits the DAG.
- Expansion is bounded and can be disabled independently.
- All acceptance criteria pass.
- No open release-blocking compatibility, timeout, tool, indexing, or secret
  issue remains.

## 25. Pull Request Sequence

Recommended PR boundaries:

1. Golden corpus, replay harness, and baseline report.
2. Legacy result retention keyed by task ID.
3. Hop/budget skip events and terminal task states.
4. SkillSync known-unavailable state and backoff.
5. Top-K shadow instrumentation with no routing behavior change.
6. Candidate-limit enforcement after the recall gate.
7. Nested-broadcast suppression behind an independent flag after replay.
8. Shared `agent_contracts` package, output schemas, and health contracts.
9. Participant mode and local task execution.
10. CapabilityReportV2, manifest intersection, and capability correctness.
11. Routing intent, lead selection, contributor scope, and LeadAssignment.
12. Lead DAG planner, validator, and scheduler.
13. Recovery, alternate assignment, and final validation.
14. Execution Flow V2 and trace integration.
15. Helm configuration, fixed-pool shadow/canary, and rollback documentation.
16. Contributor expansion and default-rollout gate.

Do not combine capability scoring, routing policy, and DAG execution in one PR.
They require independent review, metrics, and rollback.

## 26. Existing Issue Mapping

| Issue | V2 phase |
|---|---|
| [#2 SkillSync loads unrelated skills](https://github.com/DataTunerX/dac/issues/2) | Phase 2 and Phase 3: exact runtime inventory and truthful AgentCard |
| [#3 Simple routing ignores explicit agent](https://github.com/DataTunerX/dac/issues/3) | Phase 4: explicit intent is the first routing constraint |
| [#4 Capability checks overclaim](https://github.com/DataTunerX/dac/issues/4) | Phase 3: hard executability rules and contradiction validation |
| [#5 Rank by ownership and specificity](https://github.com/DataTunerX/dac/issues/5) | Phase 4: deterministic lead selection |
| [#6 Model tool-call incompatibility](https://github.com/DataTunerX/dac/issues/6) | Phase 0/2 release prerequisite and shared model compatibility |
| [#7 Embedding token-array incompatibility](https://github.com/DataTunerX/dac/issues/7) | Phase 0/4 discovery prerequisite; embeddings remain recall-only |
| [#8 Tavily advertised without key](https://github.com/DataTunerX/dac/issues/8) | Phase 2/3 runtime tool inventory and truthful capability |
| [#9 SkillRunner discards useful draft](https://github.com/DataTunerX/dac/issues/9) | Phase 2 and Phase 5: best-result retention |
| [#10 Registry indexing visibility](https://github.com/DataTunerX/dac/issues/10) | Phase 3/4 health model and routing trace |
| [#11 Centralized LLM compatibility](https://github.com/DataTunerX/dac/issues/11) | Phase 0/1 prerequisite for consistent capability and execution calls |
| [#12 Timeout hierarchy](https://github.com/DataTunerX/dac/issues/12) | Phase 2/5 deadline propagation and separate budgets |
| [#13 Alternate skill retry](https://github.com/DataTunerX/dac/issues/13) | Phase 2/5 structured missing requirements and bounded recovery |
| [#14 API keys in command arguments](https://github.com/DataTunerX/dac/issues/14) | Phase 0 security release blocker |

Additional issues should be opened for:

- Delegated results keyed by agent name overwrite earlier task results.
- Hop- or budget-blocked tasks are silently skipped without terminal events.
- Capability/pre-plan rebroadcast creates unbounded quadratic fan-out.
- SkillSync retries known-unavailable skills indefinitely when a required secret
  is absent.
- Capability design, implementation, and test contradiction on main.
- False upstream dependency satisfaction based on any earlier step.
- Mutable hop budget shared by sibling delegations.
- Simple routing selecting contributor-only agents as a complete root.
- Main Helm configuration silently defaulting to simple routing.
- Execution Flow ID collisions and missing failure events.

## 27. Reuse From Main and Current Tag

### 27.1 Reuse from main selectively

Useful concepts from `171ba5a` and `b39b6c2`:

- Structured per-step capability evidence.
- Separate `can_handle` and `can_contribute` concepts.
- Contributor-only collaboration awareness.
- Execution Flow transport and cross-agent result visibility.
- Structured summary evaluation.
- DAG cycle detection and route-plan validation helpers.

Do not port without redesign:

- Arithmetic averaging that allows mandatory zeroes to disappear.
- Dependency satisfaction based only on an earlier step existing.
- Any-above-threshold step becoming a contributor.
- Empty contribution descriptions being treated as valid contribution contracts.
- Simple-mode pre-plan competition as the final lead selector.
- Duplicated capability and Execution Flow modules.

The main-branch `skill-agent/agent/capability_chain.py` documents multiplicative
step and chain scoring near the module header but implements arithmetic means in
the scoring functions, and its tests explicitly permit a handler with zero data
coverage. The two capability-chain copies have also diverged. This is direct
evidence for hard gates and one shared contract, not a reason to adopt either
formula unchanged.

`origin/main` is not a wholesale merge prerequisite for this branch. The current
tag is the deployed integration baseline and main includes behavior that this
design intentionally replaces. Useful fixtures, tests, and transport concepts
should be ported selectively with provenance, while the shared package is created
once on this branch. Maintain a reconciliation checklist and merge V2 back to
main through reviewed pull requests after the integration behavior is proven.

### 27.2 Preserve from the current tag

- Operational deployment and image changes used by the current test cluster.
- Root-candidate decision evidence.
- Existing skill packages and test cases.
- Model and embedding compatibility fixes, after regression verification.
- Configurable routing mode during the migration period.
- Current demo and TDB integration assets used by the evaluation corpus.

## 28. Alternatives Considered

### 28.1 Routing agent owns the DAG

Rejected for V2.

It centralizes execution knowledge in routing, turns routing into the primary
workflow engine, couples routing availability to long-running execution, and
weakens the selected skill agent's ability to adapt based on domain results.

### 28.2 Fully recursive peer delegation

Rejected for the initial V2 implementation.

It creates ambiguous DAG ownership, recursive capability broadcasts, cycle and
hop complexity, fragmented recovery state, and unpredictable context growth.

The lead-owned star topology supports iterative collaboration without allowing
participants to delegate.

### 28.3 Highest confidence wins

Rejected.

Current confidence is self-reported or based on uncalibrated LLM-derived ratios.
It is not sufficient evidence of ownership, health, or executability.

### 28.4 Select the agent with the best pre-plan

Rejected as the primary selection method.

It rewards plan presentation and delegation ambition. It does not prove that
the candidate owns the primary task or can execute the proposed collaborators.

### 28.5 Multiplicative capability confidence

Rejected as the default ranking formula.

Conjunctive hard gates are required for mandatory capability dimensions, but a
product across every dimension and every query step penalizes longer requests
and is not a calibrated probability. V2 separates Boolean executability from an
optional fit ranking among already valid candidates.

Multiplication also gives the candidate evaluator an incentive to under-decompose
the request: fewer steps mechanically produce a larger chain score. A capability
method that rewards vaguer decomposition would preserve the plan-presentation
failure V2 is intended to remove.

## 29. Review Decisions and Open Questions

The empirical review resolves the following decisions:

1. Initial runtime: skill-agent first. Orchestrator-agent does not block canary.
2. Explicit target health failure: fail immediately and clearly; do not silently
   substitute another agent.
3. Output typing: use an extensible versioned JSON Schema registry, beginning
   with `dac.claim-evidence/v1`.
4. Contributor expansion: after the initial fixed-pool canary.
5. Default rollout: requires both correctness criteria and §23.5 performance
   criteria; routing accuracy alone is insufficient.
6. Candidate planning: pre-make-plan is retired by V2 lead selection.

The following questions remain and must be settled in Phase 1:

1. Whether the existing registry service owns canonical aliases directly or
   consumes an authoritative alias source maintained elsewhere.
2. The maximum inline context, result, and artifact sizes before content must be
   stored by reference.
3. The persistence backend, retention, and redaction policy for Execution Flow,
   participant evidence, and artifacts. The lead emits task events; the trace
   sink persists them, and routing does not become the execution-ledger owner.
4. The minimum package-authored capability metadata required for canary versus
   fields temporarily derived from `SKILL.md`.

## 30. Review Checklist

- [ ] Routing remains a selector and policy boundary, not the DAG executor.
- [ ] Exactly one lead owns the DAG and final answer.
- [ ] Participant mode cannot delegate.
- [ ] Contributor scope is explicit and enforceable.
- [ ] Capability feedback separates lead eligibility from contribution.
- [ ] Mandatory capability gaps fail closed.
- [ ] DAG dependencies use registered versioned output-to-input schemas.
- [ ] Budgets have separate meanings and deterministic enforcement.
- [ ] Partial work and evidence survive retries.
- [ ] Task results are append-only and keyed by task ID.
- [ ] Execution Flow contains failures and terminal states.
- [ ] Conversation, memory, and multi-turn persistence have one owner each.
- [ ] Shared contracts are not copied between components.
- [ ] Existing agents have a documented compatibility path.
- [ ] Feature flags and rollback are present in Helm.
- [ ] Images have verifiable source provenance and contain no literal secrets.
- [ ] Capability fan-out is bounded and cannot rebroadcast recursively.
- [ ] Performance, cost, and result-retention targets are agreed and measured.
- [ ] Golden corpus and acceptance metrics are agreed before rollout.
