CREATE TABLE IF NOT EXISTS domain_stream_binding (
  binding_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain          TEXT NOT NULL,
  stream_id       TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',
  binding_kind    TEXT NOT NULL DEFAULT 'primary',
  source          TEXT NOT NULL DEFAULT 'manual',
  priority        INTEGER NOT NULL DEFAULT 100,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (status IN ('active', 'inactive')),
  CHECK (binding_kind IN ('primary', 'auxiliary', 'eval', 'debug')),
  UNIQUE (domain, stream_id)
);

CREATE INDEX IF NOT EXISTS idx_domain_stream_binding_domain_status_priority
  ON domain_stream_binding (domain, status, priority ASC, stream_id ASC);

CREATE INDEX IF NOT EXISTS idx_domain_stream_binding_stream
  ON domain_stream_binding (stream_id, status, domain);
