CREATE TABLE IF NOT EXISTS ontology_case_decision (
  case_decision_id              BIGSERIAL PRIMARY KEY,
  case_id                       BIGINT NOT NULL,
  decision_kind                 TEXT NOT NULL,
  verdict                       TEXT NOT NULL,
  summary                       TEXT NOT NULL DEFAULT '',
  rationale                     TEXT NOT NULL DEFAULT '',
  as_of_system_time             TIMESTAMPTZ NOT NULL,
  as_of_effective_time          TIMESTAMPTZ NOT NULL,
  snapshot_id                   TEXT NOT NULL DEFAULT '',
  source_evidence_json          JSONB NOT NULL DEFAULT '[]'::jsonb,
  supersedes_case_decision_id   BIGINT,
  created_by                    TEXT NOT NULL DEFAULT '',
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (case_id) REFERENCES ontology_case (case_id) ON DELETE CASCADE,
  FOREIGN KEY (supersedes_case_decision_id) REFERENCES ontology_case_decision (case_decision_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ontology_case_decision_case_created
  ON ontology_case_decision (case_id, created_at DESC, case_decision_id DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_case_decision_snapshot
  ON ontology_case_decision (snapshot_id);
