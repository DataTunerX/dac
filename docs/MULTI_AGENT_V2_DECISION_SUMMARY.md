# DAC Multi-Agent V2 Decision Summary

Status: Draft for architecture approval
Branch baseline: `dev-multi-agent-v2` at `ce44277`
Full reference: [MULTI_AGENT_V2_DESIGN.md](MULTI_AGENT_V2_DESIGN.md)

## Decision

Adopt a lead-and-participant model without making routing the workflow engine.

```text
Routing selects one lead and a bounded contributor scope.
The lead owns the answer contract, DAG, execution, recovery, and final answer.
Each participant executes one assigned task and cannot discover or delegate.
```

An explicit, healthy user-selected agent is the lead. Otherwise routing chooses
the healthy agent with primary ownership of the request, then grants concrete
contributors. Routing does not compare candidate-authored DAGs or execute task
nodes. The lead plans only against the granted scope.

Initial V2 rollout is skill-agent only. Both reviewed clusters currently run all
observed workload agents through skill-agent images; orchestrator-agent support
does not block the first canary.

## Why Change

The current problem is both correctness and performance. Routing and execution
make overlapping decisions, so the plan that wins selection may not be the plan
that runs. Repeated capability broadcasts and candidate planning also spend most
model calls deciding who should answer rather than answering.

Directional live measurements:

| Metric | Current-tag/test | `fw-worker` runtime |
|---|---:|---:|
| Capability latency per agent, p50 | 4.9 s | 16.4 s |
| Capability latency per agent, p90 | 7.5 s | 43.9 s |
| Routing overhead, multi-candidate | about 50 s | 45 s p50, 116 s max |
| Same two-domain question, end to end | about 5.5 min | 8 min 37 s |

One current-tag request made approximately 65 to 70 model calls. About 60 were
routing, capability, rebroadcast, or plan-selection work. The current shape
trends toward `O(N^2)` as registered agents grow.

These clusters are not controlled equivalents. In particular, the
`fw-worker` image is not traceable to reviewed main source, so the latency delta
must not be attributed to main's capability-chain implementation until Phase 0
reproduces it from immutable source-bearing images.

## Five Defects Driving V2

### 1. Completed results are overwritten

In a live run, three tasks targeted `Paper-Answering-TDB-Agent`. The first spent
176 seconds and returned 3,104 characters. Two later tasks were blocked by the
hop limit and each wrote a 37-character failure placeholder into a dictionary
keyed by agent name. Final synthesis received 37 characters.

Required invariant: results are append-only and keyed by `task_id`. Every planned
task, including one blocked before dispatch, reaches a visible terminal state.

Evidence: `ce44277`, `skill-agent/agent/skill_agent.py:3921-3923`, followed by
the real-result write in the same `_dispatch_mid_exec_delegation` path.

### 2. The hop counter is not a coherent budget

One mutable value is consumed across sibling tasks, so iteration order decides
which delegation runs. The entry agent then restores it at the next turn. It is
neither a depth limit nor a total-run limit.

Required invariant: deadline, tasks, rounds, attempts, model calls, tokens, and
A2A calls have separate monotonic run budgets. Concurrency is independent
instantaneous capacity. Budget exhaustion always emits an event.

Evidence: `ce44277`, `skill-agent/agent/skill_agent.py:5620-5638` consumes the
shared value; `skill-agent/agent/skill_agent_turn.py:375-414` restores it.

### 3. Capability claims are self-asserted and internally inconsistent

Arithmetic averaging allows a zero mandatory dimension to disappear. Live
reasons have said an agent cannot complete or contribute while the structured
verdict still says it can handle the request. Multiplication is not the answer:
products across steps penalize longer decompositions and reward under-decomposing
the query.

V2 uses Boolean executability gates followed by a separate fit ranking. Routing
also intersects every claimed domain, operation, schema, tool, and side-effect
class with the exact versioned loaded-skill manifest. An undeclared claim is
rejected. The manifest limits what an agent may claim; runtime health and observed
reliability still determine whether declared capability works in practice.

Evidence: `b39b6c2`, `skill-agent/agent/capability_chain.py:13-18` documents the
product while lines 165-180 and 249-290 implement averaging and permissive
contribution mapping.

### 4. Repeated probes and broadcasts dominate latency

Routing asks all agents, top candidates rebroadcast to all agents, and the lead
asks again with differently worded sub-tasks. The same agent can return opposite
answers to those probes.

V2 performs model-based capability checks for a recall-protected bounded set,
initially `K=5`, and reuses reports by requirement ID and manifest/readiness
version. A new lead-discovered requirement uses contributor expansion after
canary; it does not trigger an ad hoc participant probe.

Evidence: one observed current-tag request performed 13 initial checks plus three
13-agent candidate rebroadcasts before lead-side probes and replanning.

Candidate limiting is a routing behavior change. It must first run in shadow for
at least 24 hours and 200 eligible non-explicit queries. Enforcement requires at
least 99 percent expected-lead recall and 100 percent explicit-target recall.

### 5. Lead selection rewards an unexecutable presentation

The deployed weighted selector gave three candidates confidence `1.0`, then
selected Art-history because its plan-quality score was highest. That plan relied
on collaborators the selected execution path could not use. Pre-make-plan quality
therefore determined the root without proving ownership or executability.

V2 ranks explicit intent, health, primary ownership, required-output coverage,
domain specificity, observed reliability, then cost/latency. Pre-make-plan is
retired when V2 lead selection is enabled.

Evidence: the `fw-worker` 21:58:54-22:00:08 run tied three confidence values at
`1.0`, then selected by plan quality `0.93`, `0.88`, and `0.95`.

## Contracts

Participants receive one versioned `ParticipantTask` with objective, typed input
bindings, expected output schemas, evidence requirements, deadline, and local
limits. They return one `TaskResult` containing status, typed outputs, artifacts,
evidence, limitations, normalized errors, and metrics.

Output typing uses an extensible JSON Schema registry, not a closed list. DAC
ships core types; skills may register immutable namespaced schemas. The first
common type is `dac.claim-evidence/v1`, covering a claim, source ID, optional
statement ID/span, evidence status, conflicting evidence, and limitations. An LLM
may select advertised schema IDs but cannot invent one.

The registry must expose a joined view of canonical identity, aliases, AgentCard,
capability-manifest version, heartbeat freshness, skill/tool/model readiness, and
independent vector-index status.

## Rollout Gates

| Phase | Gate |
|---|---|
| 0 | Controlled baseline, trace backend, and source-bearing images for new builds |
| 0.5 | Ship task-result retention, skip events, and SkillSync backoff without changing routing selection |
| 0.6 | Shadow top-K and nested-broadcast changes; enforce only after recall gates pass |
| 1-4 | Shared contracts, schema/health substrate, participant mode, capability gates, and lead handoff |
| 5-6 | Lead-owned DAG execution and complete typed execution ledger |
| 7 | Fixed-pool V2 shadow and canary with contributor expansion disabled |
| 8 | Add expansion after fixed-pool canary, canary it independently, then consider default rollout |

Provisional default-rollout targets:

- Routing overhead p50 at most 8 seconds and p95 at most 15 seconds.
- At most `K` model-based capability checks and zero nested rebroadcasts.
- Validated participant-result retention and planned-task visibility: 100 percent.
- Two-domain end-to-end p50 at most 3 minutes on the controlled workload.
- Solo latency no more than 10 percent worse than controlled V1.
- Routing-decision model tokens and cost at most 25 percent of controlled V1.
- No routing-throughput regression under controlled concurrency.

Targets remain provisional until Phase 0 controls image, model, workload, cluster,
and tracing differences. Better reasoning without meeting the performance gates
is not sufficient to make V2 the default.

## Operational Blockers

- `test-cluster` already uses a source-bearing image tag:
  `demo-ready-2026-09-11-ce44277-amd64`. Enforce that convention everywhere.
- API keys must not appear in arguments, literal Deployment environment values,
  rendered manifests, logs, or traces. Any exposed live key requires rotation.
- `test-cluster` currently has no active Langfuse backend; Phase 0 needs Langfuse
  or an equivalent structured trace sink.

## Approval Requested

Approve the responsibility split and phased implementation. Do not approve
default rollout until the golden correctness cases, candidate-recall gate,
result-retention invariant, source provenance, security checks, and provisional
performance targets pass on controlled, traceable builds.
