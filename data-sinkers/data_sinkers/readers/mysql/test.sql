-- Create a test database (if it doesn't exist)
CREATE DATABASE IF NOT EXISTS vectorsdk;

USE vectorsdk;

-- Create a test table with various data types
CREATE TABLE IF NOT EXISTS test_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL COMMENT 'User full name',
    email VARCHAR(255) UNIQUE COMMENT 'User email address',
    age INT COMMENT 'User age',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Account status',
    salary DECIMAL(10, 2) COMMENT 'Annual salary',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
    metadata JSON COMMENT 'Additional user data in JSON format',
    profile_text TEXT COMMENT 'User profile description'
) ENGINE=InnoDB COMMENT='Test table for MySQLReader';

-- Insert some sample data
INSERT INTO test_data (name, email, age, is_active, salary, metadata, profile_text)
VALUES 
    ('John Doe', 'john@example.com', 30, TRUE, 75000.50, '{"department": "IT", "skills": ["Python", "SQL"]}', 'Senior developer with 5 years experience'),
    ('Jane Smith', 'jane@example.com', 28, TRUE, 80000.00, '{"department": "Marketing", "projects": 3}', 'Marketing specialist'),
    ('Bob Johnson', 'bob@example.com', 35, FALSE, 90000.75, '{"department": "Finance", "clearance": "high"}', 'Former finance manager'),
    ('Alice Brown', 'alice@example.com', 25, TRUE, 60000.00, NULL, 'Junior developer'),
    ('Charlie Wilson', 'charlie@example.com', 40, TRUE, 95000.25, '{"department": "Management", "direct_reports": 5}', 'Department head');

-- Create a second table for testing joins and schema inspection
CREATE TABLE IF NOT EXISTS departments (
    dept_id INT AUTO_INCREMENT PRIMARY KEY,
    dept_name VARCHAR(100) NOT NULL COMMENT 'Department name',
    location VARCHAR(100) COMMENT 'Physical location',
    budget DECIMAL(15, 2) COMMENT 'Annual budget'
) ENGINE=InnoDB COMMENT='Department information';

INSERT INTO departments (dept_name, location, budget)
VALUES
    ('IT', 'Floor 3', 500000.00),
    ('Marketing', 'Floor 2', 300000.00),
    ('Finance', 'Floor 4', 450000.00),
    ('Management', 'Floor 5', 600000.00);