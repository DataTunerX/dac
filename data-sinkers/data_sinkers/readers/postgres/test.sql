-- Create test database (run this first if needed)
CREATE DATABASE vectorsdk;

-- Connect to vectorsdk database and create test tables

-- Create a test_data table with various data types
CREATE TABLE test_data (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price NUMERIC(10, 2),
    quantity INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB
);

COMMENT ON TABLE test_data IS 'Test table for PostgresReader functionality';
COMMENT ON COLUMN test_data.id IS 'Unique identifier for the record';
COMMENT ON COLUMN test_data.name IS 'Name of the item';
COMMENT ON COLUMN test_data.description IS 'Detailed description of the item';

-- 创建第二个表
CREATE TABLE customer_data (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE,
    registration_date DATE NOT NULL,
    loyalty_points INTEGER DEFAULT 0,
    preferences JSONB
);

COMMENT ON TABLE customer_data IS 'Customer information table';
COMMENT ON COLUMN customer_data.customer_id IS 'Auto-incrementing customer ID';
COMMENT ON COLUMN customer_data.email IS 'Customer email address (must be unique)';

-- 创建视图
CREATE VIEW active_items AS
SELECT id, name, price 
FROM test_data 
WHERE is_active = true;

-- 插入测试数据到 test_data (使用有效的UUID格式)
INSERT INTO test_data (id, name, description, price, quantity, is_active, updated_at, metadata) VALUES
('354df8da-c80a-4979-bb41-37cda8431436', 'Test Item 1', 'Primary test item for verification', 19.99, 100, true, NOW(), '{"color": "blue", "weight": 1.5}'),
('5a2e3b4c-6d7e-8f9a-b1c2-d3e4f5a6b7c8', 'Test Item 2', 'Secondary test item for validation', 29.50, 50, true, NOW(), '{"color": "red", "dimensions": {"width": 10, "height": 20}}'),
('9a8b7c6d-5e4f-3a2b-1c0d-e9f8a7b6c5d4', 'Inactive Item', 'Disabled test item', 5.99, 0, false, NOW(), '{"color": "gray", "discontinued": true}');

-- 插入测试数据到 customer_data
INSERT INTO customer_data (first_name, last_name, email, registration_date, loyalty_points, preferences) VALUES
('John', 'Doe', 'john.doe@example.com', '2023-01-15', 500, '{"newsletter": true, "theme": "dark"}'),
('Jane', 'Smith', 'jane.smith@example.com', '2023-02-20', 750, '{"newsletter": false, "language": "fr"}'),
('Robert', 'Johnson', 'robert.j@example.com', '2023-03-10', 250, '{"newsletter": true, "notifications": {"email": true, "sms": false}}');