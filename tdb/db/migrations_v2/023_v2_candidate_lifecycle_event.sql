-- Rev 7 fast-path candidate lifecycle event log.
-- Artifact candidate_uid is authoritative; db_table/db_pk are optional pointers
-- populated later by loaders/promoters when a candidate is materialized.

CREATE TABLE IF NOT EXISTS candidate_lifecycle_event (
  event_id           BIGSERIAL PRIMARY KEY,
  candidate_uid      TEXT NOT NULL,
  candidate_kind     TEXT NOT NULL,
  artifact_oid       TEXT NOT NULL,
  db_table           TEXT,
  db_pk              TEXT,
  event_kind         TEXT NOT NULL,
  from_state         TEXT,
  to_state           TEXT,
  marker             TEXT,
  reason_code        TEXT NOT NULL,
  reason_detail      TEXT NOT NULL DEFAULT '',
  actor              TEXT NOT NULL DEFAULT 'system',
  evidence_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (candidate_uid <> ''),
  CHECK (candidate_kind <> ''),
  CHECK (artifact_oid <> ''),
  CHECK (reason_code <> ''),
  CHECK (event_kind IN ('state_transition','marker_added','marker_removed')),
  CHECK (to_state IS NULL OR to_state IN ('produced','weak','needs_review','promoted','rejected','superseded')),
  CHECK (from_state IS NULL OR from_state IN ('produced','weak','needs_review','promoted','rejected','superseded')),
  CHECK (
    (event_kind = 'state_transition' AND to_state IS NOT NULL AND marker IS NULL)
    OR
    (event_kind IN ('marker_added','marker_removed') AND marker IS NOT NULL AND to_state IS NULL AND from_state IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle_lookup
  ON candidate_lifecycle_event (candidate_uid, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle_artifact
  ON candidate_lifecycle_event (artifact_oid, candidate_kind, candidate_uid);

CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle_db_ref
  ON candidate_lifecycle_event (db_table, db_pk, created_at DESC, event_id DESC)
  WHERE db_table IS NOT NULL AND db_pk IS NOT NULL;
