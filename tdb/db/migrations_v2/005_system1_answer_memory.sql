-- System 1 answer-serving projections and validation ledger.

CREATE TABLE IF NOT EXISTS memory_answer_artifact (
  answer_artifact_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id                  TEXT NOT NULL,
  intent                     TEXT NOT NULL,
  normalized_question        TEXT NOT NULL,
  question_fingerprint       JSONB NOT NULL DEFAULT '{}'::jsonb,
  entity_ids                 JSONB NOT NULL DEFAULT '[]'::jsonb,
  answer_text                TEXT NOT NULL,
  answer_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_task_id             TEXT,
  source_run_id              TEXT,
  source_decision_id         UUID REFERENCES memory_decision_record(memory_decision_id) ON DELETE RESTRICT,
  source_episode_summary_id  UUID REFERENCES memory_episode_summary(episode_summary_id) ON DELETE RESTRICT,
  evidence_refs              JSONB NOT NULL DEFAULT '[]'::jsonb,
  provenance                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  freshness_policy           JSONB NOT NULL DEFAULT '{}'::jsonb,
  validation_contract        JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
  serving_status             TEXT NOT NULL DEFAULT 'active',
  superseded_by              UUID REFERENCES memory_answer_artifact(answer_artifact_id) ON DELETE RESTRICT,
  idempotency_key            TEXT,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (domain_id <> ''),
  CHECK (intent <> ''),
  CHECK (normalized_question <> ''),
  CHECK (answer_text <> ''),
  CHECK (jsonb_typeof(question_fingerprint) = 'object'),
  CHECK (jsonb_typeof(entity_ids) = 'array'),
  CHECK (jsonb_typeof(answer_payload) = 'object'),
  CHECK (jsonb_typeof(evidence_refs) = 'array'),
  CHECK (jsonb_typeof(provenance) = 'object'),
  CHECK (jsonb_typeof(freshness_policy) = 'object'),
  CHECK (jsonb_typeof(validation_contract) = 'object'),
  CHECK (jsonb_typeof(metadata) = 'object'),
  CHECK (serving_status IN ('active', 'stale', 'superseded', 'revoked'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_answer_artifact_idempotency
  ON memory_answer_artifact (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_domain_intent_created
  ON memory_answer_artifact (domain_id, intent, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_status_updated
  ON memory_answer_artifact (serving_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_source_decision
  ON memory_answer_artifact (source_decision_id)
  WHERE source_decision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_source_episode
  ON memory_answer_artifact (source_episode_summary_id)
  WHERE source_episode_summary_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_question_fingerprint_gin
  ON memory_answer_artifact USING GIN (question_fingerprint);

CREATE INDEX IF NOT EXISTS idx_memory_answer_artifact_entity_ids_gin
  ON memory_answer_artifact USING GIN (entity_ids);

CREATE TABLE IF NOT EXISTS memory_answer_validation (
  answer_validation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_artifact_id         UUID NOT NULL REFERENCES memory_answer_artifact(answer_artifact_id) ON DELETE RESTRICT,
  validator_type             TEXT NOT NULL DEFAULT 'runtime',
  check_spec                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_values            JSONB NOT NULL DEFAULT '{}'::jsonb,
  pass                       BOOLEAN NOT NULL,
  failure_reason             TEXT,
  latency_ms                 INTEGER,
  metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
  validated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (validator_type <> ''),
  CHECK (jsonb_typeof(check_spec) = 'object'),
  CHECK (jsonb_typeof(observed_values) = 'object'),
  CHECK (jsonb_typeof(metadata) = 'object'),
  CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_memory_answer_validation_artifact_validated
  ON memory_answer_validation (answer_artifact_id, validated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_answer_validation_pass_validated
  ON memory_answer_validation (pass, validated_at DESC);
