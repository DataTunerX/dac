ALTER TABLE assertion_evidence_link
  ADD COLUMN IF NOT EXISTS evidence_id UUID REFERENCES evidence_record (evidence_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_assertion_evidence_evidence
  ON assertion_evidence_link (evidence_id)
  WHERE evidence_id IS NOT NULL;

ALTER TABLE assertion_evidence_link
  DROP CONSTRAINT IF EXISTS assertion_evidence_link_check;

ALTER TABLE assertion_evidence_link
  ADD CONSTRAINT assertion_evidence_link_check
  CHECK (
    evidence_id IS NOT NULL
    OR artifact_version_id IS NOT NULL
    OR event_id IS NOT NULL
    OR memory_decision_id IS NOT NULL
  );
