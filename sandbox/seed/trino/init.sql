CREATE SCHEMA IF NOT EXISTS hive.demo WITH (location = 's3://lake/warehouse/demo.db');

DROP TABLE IF EXISTS hive.demo.orders;
CREATE TABLE hive.demo.orders (
  order_id VARCHAR,
  customer_id VARCHAR,
  order_ts VARCHAR,
  status VARCHAR,
  amount_usd VARCHAR,
  payment_card_last4 VARCHAR,
  notes VARCHAR
) WITH (
  external_location = 's3://lake/warehouse/demo.db/orders/',
  format = 'CSV',
  skip_header_line_count = 1
);

