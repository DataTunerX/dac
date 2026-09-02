-- Enterprise frontend semantic read model (PR2)
-- This layer sits above the core event/state/artifact kernel and stores
-- UI-facing business object projections, exceptions, recommendations,
-- and page context snapshots.

CREATE TABLE IF NOT EXISTS business_object (
  object_id       TEXT PRIMARY KEY,
  object_type     TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  source_system   TEXT,
  external_ref    TEXT,
  status          TEXT NOT NULL DEFAULT 'unknown',
  health          TEXT NOT NULL DEFAULT 'healthy',
  stage           TEXT NOT NULL DEFAULT '',
  owner           TEXT NOT NULL DEFAULT '',
  summary         TEXT NOT NULL DEFAULT '',
  current_state   JSONB NOT NULL DEFAULT '{}'::jsonb,
  key_facts       JSONB NOT NULL DEFAULT '[]'::jsonb,
  metrics         JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (health IN ('healthy', 'watch', 'at_risk', 'blocked')),
  CHECK (jsonb_typeof(current_state) = 'object'),
  CHECK (jsonb_typeof(key_facts) = 'array'),
  CHECK (jsonb_typeof(metrics) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_business_object_type_updated
  ON business_object (object_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_object_owner_updated
  ON business_object (owner, updated_at DESC);

CREATE TABLE IF NOT EXISTS business_object_link (
  link_id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  src_object_id   TEXT NOT NULL REFERENCES business_object (object_id) ON DELETE CASCADE,
  relation        TEXT NOT NULL,
  dst_object_id   TEXT NOT NULL REFERENCES business_object (object_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT '',
  detail_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (jsonb_typeof(detail_json) = 'object'),
  UNIQUE (src_object_id, relation, dst_object_id)
);

CREATE INDEX IF NOT EXISTS idx_business_object_link_src
  ON business_object_link (src_object_id, relation, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_object_link_dst
  ON business_object_link (dst_object_id, relation, updated_at DESC);

CREATE TABLE IF NOT EXISTS business_exception (
  exception_id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  object_id                  TEXT REFERENCES business_object (object_id) ON DELETE CASCADE,
  queue_context              TEXT NOT NULL DEFAULT '',
  code                       TEXT NOT NULL,
  title                      TEXT NOT NULL,
  severity                   TEXT NOT NULL,
  status                     TEXT NOT NULL DEFAULT 'open',
  summary                    TEXT NOT NULL DEFAULT '',
  due_at                     TIMESTAMPTZ,
  owner                      TEXT NOT NULL DEFAULT '',
  recommended_action_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_json              JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
  CHECK (status IN ('open', 'acked', 'resolved', 'dismissed')),
  CHECK (jsonb_typeof(recommended_action_json) = 'object'),
  CHECK (jsonb_typeof(evidence_json) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_business_exception_feed
  ON business_exception (status, severity, due_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_exception_object
  ON business_exception (object_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_exception_queue
  ON business_exception (queue_context, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS business_recommendation (
  recommendation_id        TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  object_id                TEXT REFERENCES business_object (object_id) ON DELETE CASCADE,
  page_type                TEXT NOT NULL DEFAULT '',
  queue_context            TEXT NOT NULL DEFAULT '',
  action_key               TEXT NOT NULL,
  label                    TEXT NOT NULL,
  style                    TEXT NOT NULL DEFAULT 'secondary',
  reason                   TEXT NOT NULL DEFAULT '',
  confidence               DOUBLE PRECISION,
  requires_confirmation    BOOLEAN NOT NULL DEFAULT FALSE,
  required_permissions     JSONB NOT NULL DEFAULT '[]'::jsonb,
  args_hint                JSONB NOT NULL DEFAULT '{}'::jsonb,
  priority                 INTEGER NOT NULL DEFAULT 50,
  status                   TEXT NOT NULL DEFAULT 'active',
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (style IN ('primary', 'secondary', 'danger', 'ghost')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  CHECK (status IN ('active', 'inactive')),
  CHECK (priority BETWEEN 0 AND 100),
  CHECK (jsonb_typeof(required_permissions) = 'array'),
  CHECK (jsonb_typeof(args_hint) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_business_recommendation_object
  ON business_recommendation (object_id, status, priority DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_business_recommendation_queue
  ON business_recommendation (queue_context, status, priority DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS page_context_snapshot (
  context_snapshot_id      TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id                  TEXT NOT NULL,
  role                     TEXT NOT NULL,
  page_type                TEXT NOT NULL,
  object_id                TEXT REFERENCES business_object (object_id) ON DELETE SET NULL,
  goal                     TEXT NOT NULL DEFAULT '',
  queue_context            TEXT NOT NULL DEFAULT '',
  summary_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  current_state_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
  key_facts_json           JSONB NOT NULL DEFAULT '[]'::jsonb,
  recent_changes_json      JSONB NOT NULL DEFAULT '[]'::jsonb,
  exceptions_json          JSONB NOT NULL DEFAULT '[]'::jsonb,
  recommended_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  ui_blocks_json           JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_json            JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (jsonb_typeof(summary_json) = 'object'),
  CHECK (jsonb_typeof(current_state_json) = 'object'),
  CHECK (jsonb_typeof(key_facts_json) = 'array'),
  CHECK (jsonb_typeof(recent_changes_json) = 'array'),
  CHECK (jsonb_typeof(exceptions_json) = 'array'),
  CHECK (jsonb_typeof(recommended_actions_json) = 'array'),
  CHECK (jsonb_typeof(ui_blocks_json) = 'array'),
  CHECK (jsonb_typeof(evidence_json) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_page_context_snapshot_lookup
  ON page_context_snapshot (user_id, role, page_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_page_context_snapshot_object
  ON page_context_snapshot (object_id, created_at DESC)
  WHERE object_id IS NOT NULL;
