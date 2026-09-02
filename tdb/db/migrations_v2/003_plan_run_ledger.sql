CREATE TABLE IF NOT EXISTS plan_run_ledger (
  plan_id             UUID PRIMARY KEY,
  execution_kind      TEXT NOT NULL CHECK (execution_kind IN ('execute', 'dry_run', 'replay')),
  replay_of_plan_id   UUID REFERENCES plan_run_ledger (plan_id) ON DELETE SET NULL,
  goal                TEXT NOT NULL DEFAULT '',
  execution_mode      TEXT NOT NULL CHECK (execution_mode IN ('safe', 'best_effort')),
  success             BOOLEAN NOT NULL DEFAULT false,
  request_json        JSONB NOT NULL,
  response_json       JSONB NOT NULL,
  trace_json          JSONB NOT NULL DEFAULT '[]'::jsonb,
  started_at          TIMESTAMPTZ NOT NULL,
  finished_at         TIMESTAMPTZ NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_run_ledger_created
  ON plan_run_ledger (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_plan_run_ledger_replay_of
  ON plan_run_ledger (replay_of_plan_id);
