-- Memory-semantic records for agent/runtime-oriented memory APIs.

CREATE TABLE IF NOT EXISTS memory_decision_record (
  memory_decision_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id                   TEXT NOT NULL,
  run_id                    TEXT,
  decision_text             TEXT NOT NULL,
  rationale_text            TEXT NOT NULL,
  alternatives_considered   JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_evidence           JSONB NOT NULL DEFAULT '[]'::jsonb,
  entity_ids                JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence                DOUBLE PRECISION,
  author                    JSONB NOT NULL DEFAULT '{}'::jsonb,
  decision_timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  consequences              JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata                  JSONB NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key           TEXT,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (decision_text <> ''),
  CHECK (rationale_text <> ''),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_decision_idempotency
  ON memory_decision_record (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_decision_task_created
  ON memory_decision_record (task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_decision_run_created
  ON memory_decision_record (run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_episode_summary (
  episode_summary_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  episode_label             TEXT,
  task_id                   TEXT,
  run_id                    TEXT,
  session_id                TEXT,
  summary_text              TEXT NOT NULL,
  outcomes                  JSONB NOT NULL DEFAULT '[]'::jsonb,
  key_facts                 JSONB NOT NULL DEFAULT '[]'::jsonb,
  decisions                 JSONB NOT NULL DEFAULT '[]'::jsonb,
  unresolved_questions      JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_evidence           JSONB NOT NULL DEFAULT '[]'::jsonb,
  entity_ids                JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence                DOUBLE PRECISION,
  author                    JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary_timestamp         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata                  JSONB NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key           TEXT,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (summary_text <> ''),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_episode_summary_idempotency
  ON memory_episode_summary (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_episode_summary_task_created
  ON memory_episode_summary (task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_episode_summary_run_created
  ON memory_episode_summary (run_id, created_at DESC);
