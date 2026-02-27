-- Sandbox DB initialization: ERP-like schemas with PII-ish fields
-- This is intentionally simplified for discovery/profiling/PII detection demos.

CREATE SCHEMA IF NOT EXISTS erp;
CREATE SCHEMA IF NOT EXISTS appcfg;

CREATE TABLE IF NOT EXISTS erp.customers (
  customer_id      UUID PRIMARY KEY,
  full_name        TEXT NOT NULL,
  email            TEXT,
  phone            TEXT,
  national_id      TEXT,         -- PII-ish
  address          TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS erp.orders (
  order_id         UUID PRIMARY KEY,
  customer_id      UUID NOT NULL REFERENCES erp.customers(customer_id),
  order_ts         TIMESTAMPTZ NOT NULL,
  status           TEXT NOT NULL,
  amount_usd       NUMERIC(12,2) NOT NULL,
  payment_card_last4 TEXT,       -- PII-ish
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS erp.employees (
  employee_id      UUID PRIMARY KEY,
  full_name        TEXT NOT NULL,
  email            TEXT,
  department       TEXT,
  salary_usd       NUMERIC(12,2),
  ssn              TEXT,         -- PII-ish
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- App/runtime-ish config samples (for config discovery)
CREATE TABLE IF NOT EXISTS appcfg.applications (
  app_id           TEXT PRIMARY KEY,
  owner_team       TEXT,
  repo_url         TEXT,
  runtime          TEXT,
  ci_system        TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

INSERT INTO appcfg.applications (app_id, owner_team, repo_url, runtime, ci_system)
VALUES
  ('o365-mock', 'it-platform', 'file:///sandbox/data/source-repos/sample-app', 'docker', 'github-actions'),
  ('erp-mock', 'finance-tech', 'file:///sandbox/data/source-repos/erp-service', 'docker', 'jenkins'),
  ('vertical-mock', 'industry-ai', 'file:///sandbox/data/source-repos/vertical-app', 'docker', 'gitlab-ci')
ON CONFLICT (app_id) DO NOTHING;

-- Seed sample data
INSERT INTO erp.customers (customer_id, full_name, email, phone, national_id, address)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'Alice Zhang', 'alice@example.com', '+1-415-555-0101', 'ID-ALICE-0001', '1 Market St, SF'),
  ('22222222-2222-2222-2222-222222222222', 'Bob Li', 'bob@example.com', '+1-415-555-0202', 'ID-BOB-0002', '2 Market St, SF'),
  ('33333333-3333-3333-3333-333333333333', 'Carol Wang', 'carol@example.com', '+1-415-555-0303', 'ID-CAROL-0003', '3 Market St, SF')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO erp.orders (order_id, customer_id, order_ts, status, amount_usd, payment_card_last4, notes)
VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', now() - interval '10 days', 'PAID', 120.50, '1234', 'first order'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', now() - interval '3 days', 'PENDING', 88.00, '9876', 'needs review'),
  ('cccccccc-cccc-cccc-cccc-cccccccccccc', '33333333-3333-3333-3333-333333333333', now() - interval '1 day', 'PAID', 15.99, '5555', 'promo applied')
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO erp.employees (employee_id, full_name, email, department, salary_usd, ssn)
VALUES
  ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'Eve Chen', 'eve@corp.example', 'Finance', 180000.00, '111-22-3333'),
  ('ffffffff-ffff-ffff-ffff-ffffffffffff', 'Frank Zhao', 'frank@corp.example', 'IT', 150000.00, '222-33-4444')
ON CONFLICT (employee_id) DO NOTHING;

