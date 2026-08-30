# TDB Pipeline Integration

DAC Data Management submits TDB ingestion runs to the **TDB Pipeline Controller**, an
asynchronous job API that runs outside DAC (namespace `tdb-pipeline` on the `fw-worker`
cluster). The controller creates the Kubernetes pipeline jobs, watches them, uploads
artifacts and status to S3, and exposes status/pause/resume/cancel/retry APIs.

The controller's own contract is documented in the EIS repo at
`tdb/docs/tdb_pipeline_controller_runbook.md` (branch `stable/v0.4.0-rc`), section
"Part 2: Use The Controller API". This document covers only the DAC side.

## Shape

```
frontend /tdb-pipeline
        │  /api/v1/tdb-pipeline/*
        ▼
dac-apiserver
        │  internal/infrastructure/tdbpipeline
        ├──────────────► tdb-pipeline-controller:8080   (run execution)
        └──────────────► MySQL tdb_pipeline_runs        (which runs DAC submitted)
```

DAC records every submitted run in its own `tdb_pipeline_runs` table because the
controller has **no list endpoint** — only `GET /v1/pipeline-runs/{runId}`. Without the
table a run ID would be unrecoverable once the submitting session ended. Status and
counters in that table are a cache: the run list and detail re-read the controller for
any run that is not yet terminal.

### Files

| Layer | Path |
| --- | --- |
| Domain types + idempotency key | `dac-apiserver/internal/domain/tdb_pipeline.go` |
| Controller HTTP client | `dac-apiserver/internal/infrastructure/tdbpipeline/client.go` |
| Run store (MySQL) | `dac-apiserver/internal/infrastructure/tdbpipeline/store.go` |
| Config → form options | `dac-apiserver/internal/infrastructure/tdbpipeline/options.go` |
| Usecase (validation, defaults, refresh) | `dac-apiserver/internal/usecase/tdb_pipeline_usecase.go` |
| HTTP handler | `dac-apiserver/internal/handler/tdb_pipeline_handler.go` |
| Frontend API client | `frontend/src/lib/tdb-pipeline-api.ts` |
| Run list page | `frontend/src/app/(dashboard)/tdb-pipeline/page.tsx` |
| Create-run dialog | `frontend/src/components/tdb-pipeline-create-dialog.tsx` |

## DAC API

All paths are under `/api/v1`. Reads are open to `user`; every mutation is `admin`-only
(`configs/authz/policy.csv`).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/tdb-pipeline/options` | Targets, images, LLM profiles and defaults for the form |
| `POST` | `/tdb-pipeline/runs` | Submit a run (202 Accepted) |
| `GET` | `/tdb-pipeline/runs` | List submitted runs (`limit`, `offset`, `domain`, `status`) |
| `GET` | `/tdb-pipeline/runs/{runId}` | One run, with a freshly read controller summary |
| `POST` | `/tdb-pipeline/runs/{runId}/pause` | Stop dispatching queued jobs |
| `POST` | `/tdb-pipeline/runs/{runId}/resume` | Resume dispatching |
| `POST` | `/tdb-pipeline/runs/{runId}/cancel` | Cancel and delete active worker jobs |
| `POST` | `/tdb-pipeline/runs/{runId}/retry-failed` | Requeue failed jobs, optional `failed_stage` |
| `POST` | `/tdb-pipeline/runs/{runId}/retry-s3-upload` | Retry artifact upload only |

DAC's API is snake_case; the controller's camelCase contract is confined to
`internal/infrastructure/tdbpipeline/types.go`.

### Minimal create body

Picking a target and a source is enough — the gateway, profile, image, collection, LLM
profile and artifact prefixes come from configuration:

```json
{
  "source": {"type": "s3", "uri": "s3://archaeology-source/papers/ActaAnthropologicaSinica/"},
  "target": {"target_id": "archeology"}
}
```

### Idempotency

The controller requires an `Idempotency-Key` on create and stores it per
`(caller_id, key)`. DAC derives it as
`<dataset_id>:<source_version>:<domain>:<collection>`, defaulting `dataset_id` to the
source location and `source_version` to `v0`.

The key is deterministic on purpose: submitting the same source at the same target twice
returns the original run instead of ingesting it again. **Set `source_version` (an object
ETag or a dataset revision) when the source content changes**, or pass an explicit
`idempotency_key` to force a fresh run. Reusing a key with a different body is a `409`.

## Configuration

`apiserver.config.tdbPipeline` in `installer/dac/values.yaml`, rendered into the
apiserver ConfigMap. Local development uses `dac-apiserver/configs/config.yaml`.

| Key | Meaning |
| --- | --- |
| `baseUrl` | Controller service URL |
| `callerId` | Caller ID the controller allowlists (`dac`) |
| `tokenSecret.name` / `.key` | Secret holding the bearer token, injected as `DAC_TDB_PIPELINE_TOKEN` |
| `images`, `llmProfiles` | Allowlisted worker images and LLM profiles |
| `defaults` | Pre-filled collection, image, profile and S3 prefixes |
| `targets` | Selectable TDB targets |

Create the token Secret before installing:

```bash
kubectl -n dac create secret generic tdb-pipeline-controller-token \
  --from-literal=token='<controller api token>'
```

### Targets must mirror the controller

`targets` is **DAC's copy** of the controller's `domain-config` allowlist; the controller
exposes no endpoint for it. DAC validates a submission against this list first so an
operator gets a message naming the field to fix, rather than a bare `403`. A target
missing here cannot be selected in DAC even if the controller would accept it; a target
listed here that the controller rejects fails at submit time with the controller's own
message. When the controller's `domain-config.yaml` changes, update these values too.

### Targets are the skill agents' gateways

Each target's `gateway_url` is the **same TDB gateway the named `skill_agent` queries**,
so material ingested through this page becomes answerable by that skill:

| Target | Gateway | Skill |
| --- | --- | --- |
| `archeology` | `:8989` | `tdb-archeology-qa` |
| `history` | `:8990` | `tdb-history-qa` |
| `art_history` | `:8991` | `tdb-art-history-qa` |
| `anthropology_sociology` | `:8992` | `tdb-anthropology-sociology-qa` |
| `philosophy_theory` | `:8993` | `tdb-philosophy-theory-qa` |
| `geo_environment` | `:8994` | `tdb-geo-environment-qa` |
| `literature_humanities` | `:8995` | `tdb-literature-humanities-qa` |
| `wwybsj` | `:8997` | `tdb-wwybsj-answering` |
| `archeology_papers_test` | `:8996` | — (isolated test DB, `test: true`) |

`archeology_papers_test` is the isolated academic-paper database used for controller
integration testing. It is marked `test` in the UI and no skill reads it.

## The archaeology skill

`skill-hub/skills-src/tdb-archeology-qa/` is the skill that answers over the
`archeology` target's gateway (`:8989`) — the same TDB the pipeline writes to. It is
packaged as `skill-hub/skills/tdb-archeology-qa-1.0.0.zip` (`<name>/SKILL.md`,
`<name>/_meta.json`, `<name>/references/gateway_api_doc.md`).

`_meta.json` is required by the upload endpoint and skill-hub does **not** generate it.

Publish it into the `default` namespace:

```bash
curl -sS -X POST "http://<skill-hub>:8000/namespaces/default/skills" \
  -F "file=@skill-hub/skills/tdb-archeology-qa-1.0.0.zip"
```

Rebuild the zip after editing the source:

```bash
cd skill-hub/skills-src && zip -q -r ../skills/tdb-archeology-qa-1.0.0.zip tdb-archeology-qa
```

Bump `version` in `_meta.json` and the zip filename together — skill-hub keys a skill by
`(namespace, name, version)` and overwrites on an exact match.

## End-to-end check

1. Data Management → **TDB 入库** → 新建入库任务.
2. Target `考古学` (gateway `:8989`), source
   `s3://archaeology-source/papers/ActaAnthropologicaSinica/`, LLM profile `openai`.
3. Submit; the row shows `accepted` → `running` with per-job counters, refreshing every
   15s while any run is live.
4. On `s3_upload` failures use **仅重试产物上传** — the controller answers `400` if such a
   job is sent to `retry-failed`.
5. When the run succeeds, ask the archaeology agent a question about the ingested
   material; it reads the same gateway through `tdb-archeology-qa`.

## Known limits

- `max_concurrent`, `start_stagger_*` and `artifact_upload.strict` are accepted and
  stored by the controller but **not yet enforced**. Real caps are controller-side:
  4 cluster-wide, 2 per domain, 2 per run.
- The controller's `GET /v1/pipeline-runs/{runId}` is unauthenticated; anything that can
  reach the Service can read run summaries.
- There is no hard-delete for run history, in the controller or in DAC.
- Cancel does not roll back TDB writes already made by completed stages.
- Callbacks are fail-closed on the controller. DAC polls instead; to switch to callbacks,
  DAC's host must be added to the controller's `allowed-callback-hosts.json`.
