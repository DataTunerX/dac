-- DAC sandbox: 额外的 demo databases (dac_sandbox 由 entrypoint 自动建)
CREATE DATABASE relationship;
CREATE DATABASE pagila;
CREATE DATABASE chinook;

-- dac 账号 (沙盒用密码 dacpass)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dac') THEN
    CREATE ROLE dac LOGIN PASSWORD 'dacpass';
  END IF;
END $$;

GRANT ALL PRIVILEGES ON DATABASE dac_sandbox  TO dac;
GRANT ALL PRIVILEGES ON DATABASE relationship TO dac;
GRANT ALL PRIVILEGES ON DATABASE pagila       TO dac;
GRANT ALL PRIVILEGES ON DATABASE chinook      TO dac;
