-- Methodology layer v1 schema
-- Goal:
-- 1) Add a first-class governance-backed methodology layer.
-- 2) Separate methodology configuration from ontology core and term mapping registry.
-- 3) Make framework / scheme / policy objects queryable via Gateway RPC and REST.

CREATE TABLE IF NOT EXISTS methodology_framework (
  framework_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain             TEXT NOT NULL,
  framework_name     TEXT NOT NULL,
  version_label      TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'draft',
  description        TEXT NOT NULL DEFAULT '',
  owner              TEXT NOT NULL DEFAULT '',
  question_types     JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (domain <> ''),
  CHECK (framework_name <> ''),
  CHECK (version_label <> ''),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_methodology_framework_domain_name_version
  ON methodology_framework (domain, framework_name, version_label);

CREATE INDEX IF NOT EXISTS idx_methodology_framework_domain_status
  ON methodology_framework (domain, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS taxonomy_scheme (
  scheme_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  framework_id        UUID NOT NULL REFERENCES methodology_framework (framework_id) ON DELETE CASCADE,
  scheme_name         TEXT NOT NULL,
  scheme_type         TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'draft',
  description         TEXT NOT NULL DEFAULT '',
  canonical_source    TEXT NOT NULL DEFAULT '',
  scheme_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (scheme_name <> ''),
  CHECK (scheme_type IN ('classification', 'controlled_vocabulary', 'relation_taxonomy', 'other')),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_scheme_framework_name
  ON taxonomy_scheme (framework_id, scheme_name);

CREATE INDEX IF NOT EXISTS idx_taxonomy_scheme_framework_status
  ON taxonomy_scheme (framework_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS evidence_policy_rule (
  evidence_policy_rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  framework_id            UUID NOT NULL REFERENCES methodology_framework (framework_id) ON DELETE CASCADE,
  rule_key                TEXT NOT NULL,
  question_type           TEXT NOT NULL DEFAULT '',
  evidence_kind           TEXT NOT NULL DEFAULT '',
  source_tier             TEXT NOT NULL DEFAULT '',
  status                  TEXT NOT NULL DEFAULT 'draft',
  priority                INTEGER NOT NULL DEFAULT 100,
  review_required         BOOLEAN NOT NULL DEFAULT FALSE,
  applicability_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  effect_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  description             TEXT NOT NULL DEFAULT '',
  metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (rule_key <> ''),
  CHECK (priority >= 0),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_policy_rule_framework_key
  ON evidence_policy_rule (framework_id, rule_key);

CREATE INDEX IF NOT EXISTS idx_evidence_policy_rule_framework_question
  ON evidence_policy_rule (framework_id, question_type, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS assertion_policy_rule (
  assertion_policy_rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  framework_id             UUID NOT NULL REFERENCES methodology_framework (framework_id) ON DELETE CASCADE,
  rule_key                 TEXT NOT NULL,
  assertion_type           TEXT NOT NULL,
  question_type            TEXT NOT NULL DEFAULT '',
  status                   TEXT NOT NULL DEFAULT 'draft',
  priority                 INTEGER NOT NULL DEFAULT 100,
  review_required          BOOLEAN NOT NULL DEFAULT FALSE,
  required_evidence_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
  outcome_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  description              TEXT NOT NULL DEFAULT '',
  metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (rule_key <> ''),
  CHECK (assertion_type <> ''),
  CHECK (priority >= 0),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_assertion_policy_rule_framework_key
  ON assertion_policy_rule (framework_id, rule_key);

CREATE INDEX IF NOT EXISTS idx_assertion_policy_rule_framework_type
  ON assertion_policy_rule (framework_id, assertion_type, question_type, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS review_policy (
  review_policy_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  framework_id          UUID NOT NULL REFERENCES methodology_framework (framework_id) ON DELETE CASCADE,
  policy_key            TEXT NOT NULL,
  question_type         TEXT NOT NULL DEFAULT '',
  trigger_kind          TEXT NOT NULL,
  action                TEXT NOT NULL DEFAULT 'human_review',
  status                TEXT NOT NULL DEFAULT 'draft',
  priority              INTEGER NOT NULL DEFAULT 100,
  trigger_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  description           TEXT NOT NULL DEFAULT '',
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (policy_key <> ''),
  CHECK (trigger_kind <> ''),
  CHECK (action <> ''),
  CHECK (priority >= 0),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_policy_framework_key
  ON review_policy (framework_id, policy_key);

CREATE INDEX IF NOT EXISTS idx_review_policy_framework_trigger
  ON review_policy (framework_id, question_type, trigger_kind, status, updated_at DESC);
