-- DAC sandbox: 额外的 demo databases (dac_sandbox 由 entrypoint 自动建)
CREATE DATABASE relationship;
CREATE DATABASE pagila;
CREATE DATABASE chinook;
CREATE DATABASE northwind;
-- Shared by STS-hosted Odoo / Saleor (no separate DB Deployments)
CREATE DATABASE odoo_demo;
CREATE DATABASE saleor;

-- dac 账号 (沙盒用密码 dacpass)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dac') THEN
    CREATE ROLE dac LOGIN PASSWORD 'dacpass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'odoo') THEN
    CREATE ROLE odoo LOGIN PASSWORD 'odopass';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'saleor') THEN
    CREATE ROLE saleor LOGIN PASSWORD 'saleor';
  END IF;
END $$;

GRANT ALL PRIVILEGES ON DATABASE dac_sandbox  TO dac;
GRANT ALL PRIVILEGES ON DATABASE relationship TO dac;
GRANT ALL PRIVILEGES ON DATABASE pagila       TO dac;
GRANT ALL PRIVILEGES ON DATABASE chinook      TO dac;
GRANT ALL PRIVILEGES ON DATABASE northwind   TO dac;
GRANT ALL PRIVILEGES ON DATABASE odoo_demo   TO odoo;
GRANT ALL PRIVILEGES ON DATABASE saleor      TO saleor;

\c odoo_demo
GRANT ALL ON SCHEMA public TO odoo;
ALTER DATABASE odoo_demo OWNER TO odoo;

\c saleor
GRANT ALL ON SCHEMA public TO saleor;
ALTER DATABASE saleor OWNER TO saleor;
