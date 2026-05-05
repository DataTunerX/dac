-- 企业人力资源管理系统（Corporate HR Management System）

CREATE DATABASE IF NOT EXISTS corporate_hr;
USE corporate_hr;

-- 1. 部门表（包含自关联：上级部门）
CREATE TABLE departments (
    dept_id INT PRIMARY KEY AUTO_INCREMENT,
    dept_name VARCHAR(100) NOT NULL,
    manager_id INT, -- 部门负责人
    parent_dept_id INT, -- 上级部门ID
    location VARCHAR(255),
    FOREIGN KEY (parent_dept_id) REFERENCES departments(dept_id)
);

-- 2. 员工表（包含职级和入职时间）
CREATE TABLE employees (
    emp_id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE,
    hire_date DATE NOT NULL,
    job_level VARCHAR(20), -- 'Junior', 'Senior', 'Lead', 'Director'
    salary DECIMAL(12, 2),
    dept_id INT,
    status ENUM('active', 'on_leave', 'terminated') DEFAULT 'active',
    FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
);

-- 3. 项目表
CREATE TABLE projects (
    proj_id INT PRIMARY KEY AUTO_INCREMENT,
    proj_name VARCHAR(200) NOT NULL,
    budget DECIMAL(15, 2),
    start_date DATE,
    end_date DATE,
    priority ENUM('Low', 'Medium', 'High', 'Urgent'),
    lead_emp_id INT, -- 项目负责人
    FOREIGN KEY (lead_emp_id) REFERENCES employees(emp_id)
);

-- 4. 员工-项目关联表（多对多，包含工时）
CREATE TABLE project_assignments (
    assignment_id INT PRIMARY KEY AUTO_INCREMENT,
    emp_id INT,
    proj_id INT,
    role_in_project VARCHAR(100), -- 例如 'Developer', 'Designer', 'QA'
    hours_allocated INT,
    FOREIGN KEY (emp_id) REFERENCES employees(emp_id),
    FOREIGN KEY (proj_id) REFERENCES projects(proj_id)
);

USE corporate_hr;

-- 第一步：清空表（如果里面有脏数据的话）
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE project_assignments;
TRUNCATE TABLE projects;
TRUNCATE TABLE employees;
TRUNCATE TABLE departments;
SET FOREIGN_KEY_CHECKS = 1;

-- 第二步：先插入已知存在的顶级部门（ID 1, 2, 3, 4）
-- 注意：确保自增 ID 从 1 开始
INSERT INTO departments (dept_id, dept_name, parent_dept_id, location) VALUES 
(1, '总部', NULL, '上海'),
(2, '研发部', 1, '上海'),
(3, '市场部', 1, '北京'),
(4, 'AI实验室', 2, '杭州');

-- 第三步：插入其他依赖于上述 ID 的部门
INSERT INTO departments (dept_name, parent_dept_id, location) VALUES 
('华南分公司', 1, '广州'),       -- 会自动获得 ID 5
('财务部', 1, '上海'),           -- ID 6
('人力资源部', 1, '上海'),        -- ID 7
('法务合规部', 1, '北京'),        -- ID 8
('海外事业部', 1, '新加坡'),      -- ID 9
('供应链管理部', 1, '天津');      -- ID 10

-- 第四步：插入二级/三级子部门（依赖 ID 2, 3, 5, 7 等）
INSERT INTO departments (dept_name, parent_dept_id, location) VALUES 
('深研中心', 5, '深圳'),         -- 依赖华南分公司 (ID 5)
('电商运营部', 3, '北京'),       -- 依赖市场部 (ID 3)
('品牌公关部', 3, '北京'),       -- 依赖市场部 (ID 3)
('大数据组', 2, '上海'),         -- 依赖研发部 (ID 2)
('云架构组', 2, '上海'),         -- 依赖研发部 (ID 2)
('视觉设计中心', 2, '杭州'),     -- 依赖研发部 (ID 2)
('质量保证部', 2, '苏州'),       -- 依赖研发部 (ID 2)
('客服中心', 5, '广州'),         -- 依赖华南分公司 (ID 5)
('投资部', 7, '上海'),           -- 依赖人力资源部 (ID 7)
('视觉实验室', 4, '杭州');       -- 依赖AI实验室 (ID 4)



USE corporate_hr;

-- 为employees表生成20条数据
INSERT INTO employees (first_name, last_name, email, hire_date, job_level, salary, dept_id, status) VALUES
('张', '明', 'zhang.ming@company.com', '2020-03-15', 'Senior', 85000.00, 2, 'active'),
('李', '华', 'li.hua@company.com', '2021-06-20', 'Junior', 50000.00, 2, 'active'),
('王', '伟', 'wang.wei@company.com', '2019-11-10', 'Lead', 120000.00, 3, 'active'),
('赵', '敏', 'zhao.min@company.com', '2022-01-15', 'Junior', 48000.00, 3, 'active'),
('刘', '涛', 'liu.tao@company.com', '2018-05-22', 'Director', 150000.00, 4, 'active'),
('陈', '静', 'chen.jing@company.com', '2023-03-10', 'Junior', 45000.00, 4, 'active'),
('杨', '光', 'yang.guang@company.com', '2020-09-05', 'Senior', 95000.00, 5, 'active'),
('周', '芳', 'zhou.fang@company.com', '2021-11-30', 'Junior', 52000.00, 5, 'active'),
('吴', '刚', 'wu.gang@company.com', '2017-07-12', 'Director', 180000.00, 6, 'active'),
('黄', '丽', 'huang.li@company.com', '2022-04-18', 'Junior', 47000.00, 6, 'active'),
('孙', '浩', 'sun.hao@company.com', '2019-02-28', 'Lead', 110000.00, 7, 'active'),
('朱', '婷', 'zhu.ting@company.com', '2023-01-10', 'Junior', 46000.00, 7, 'on_leave'),
('马', '强', 'ma.qiang@company.com', '2020-08-15', 'Senior', 88000.00, 8, 'active'),
('林', '琳', 'lin.lin@company.com', '2021-05-20', 'Junior', 49000.00, 8, 'active'),
('郭', '伟', 'guo.wei@company.com', '2016-12-01', 'Director', 200000.00, 9, 'active'),
('何', '洁', 'he.jie@company.com', '2022-09-15', 'Junior', 51000.00, 9, 'active'),
('罗', '军', 'luo.jun@company.com', '2018-04-10', 'Lead', 125000.00, 10, 'active'),
('梁', '艳', 'liang.yan@company.com', '2023-02-28', 'Junior', 44000.00, 10, 'active'),
('郑', '波', 'zheng.bo@company.com', '2019-07-20', 'Senior', 92000.00, 11, 'active'),
('谢', '娜', 'xie.na@company.com', '2022-06-10', 'Junior', 53000.00, 11, 'active');

-- 更新departments表的manager_id
UPDATE departments SET manager_id = 5 WHERE dept_id = 4;
UPDATE departments SET manager_id = 9 WHERE dept_id = 6;
UPDATE departments SET manager_id = 11 WHERE dept_id = 7;
UPDATE departments SET manager_id = 13 WHERE dept_id = 8;
UPDATE departments SET manager_id = 15 WHERE dept_id = 9;
UPDATE departments SET manager_id = 17 WHERE dept_id = 10;



-- 重新插入projects表，确保lead_emp_id在1-20范围内
INSERT INTO projects (proj_name, budget, start_date, end_date, priority, lead_emp_id) VALUES
('智能客服系统升级', 500000.00, '2024-01-15', '2024-06-30', 'High', 1),      -- 张明(Senior)
('移动支付安全优化', 300000.00, '2024-02-01', '2024-08-31', 'Urgent', 2),  -- 李华(Junior)
('新一代ERP系统', 1500000.00, '2024-03-01', '2024-12-31', 'Medium', 3),   -- 王伟(Lead)
('AI图像识别平台', 800000.00, '2024-01-20', '2024-09-30', 'High', 4),     -- 赵敏(Junior)
('跨境电商平台开发', 1200000.00, '2024-02-15', '2025-01-31', 'Medium', 5),-- 刘涛(Director)
('智能仓储管理系统', 450000.00, '2024-03-10', '2024-10-15', 'High', 6),   -- 陈静(Junior)
('公司门户网站改版', 200000.00, '2024-04-01', '2024-07-31', 'Low', 7),    -- 杨光(Senior)
('大数据分析平台', 750000.00, '2024-01-25', '2024-11-30', 'High', 8),     -- 周芳(Junior)
('云原生架构迁移', 900000.00, '2024-02-20', '2025-02-28', 'Urgent', 9),  -- 吴刚(Director)
('智能营销系统', 350000.00, '2024-03-05', '2024-08-15', 'Medium', 10),   -- 黄丽(Junior)
('员工培训平台', 150000.00, '2024-04-10', '2024-09-30', 'Low', 11),      -- 孙浩(Lead)
('财务风控系统', 400000.00, '2024-02-01', '2024-07-31', 'High', 12),     -- 朱婷(Junior)
('供应链可视化平台', 550000.00, '2024-01-30', '2024-10-31', 'Medium', 13),-- 马强(Senior)
('移动办公应用开发', 250000.00, '2024-03-15', '2024-08-31', 'High', 14),  -- 林琳(Junior)
('客户关系管理系统', 600000.00, '2024-04-05', '2024-12-15', 'Medium', 15),-- 郭伟(Director)
('AI法律文档审查', 350000.00, '2024-02-10', '2024-09-30', 'High', 16),   -- 何洁(Junior)
('品牌官网重构', 180000.00, '2024-03-20', '2024-07-15', 'Low', 17),      -- 罗军(Lead)
('智慧办公平台', 420000.00, '2024-01-18', '2024-11-30', 'Medium', 18),   -- 梁艳(Junior)
('数据中台建设', 1100000.00, '2024-02-25', '2025-03-31', 'Urgent', 19),  -- 郑波(Senior)
('智能硬件集成项目', 280000.00, '2024-04-08', '2024-09-15', 'High', 20); -- 谢娜(Junior)

-- 然后插入project_assignments表
INSERT INTO project_assignments (emp_id, proj_id, role_in_project, hours_allocated) VALUES
(1, 1, 'Technical Lead', 200),
(2, 2, 'Security Analyst', 160),
(3, 3, 'Project Manager', 180),
(4, 4, 'AI Engineer', 140),
(5, 5, 'Architect', 220),
(6, 6, 'QA Engineer', 200),
(7, 7, 'Frontend Developer', 150),
(8, 8, 'Data Analyst', 120),
(9, 9, 'Cloud Architect', 160),
(10, 10, 'Marketing Specialist', 130),
(11, 11, 'HR Specialist', 100),
(12, 12, 'Finance Analyst', 110),
(13, 13, 'Supply Chain Expert', 90),
(14, 14, 'Mobile Developer', 80),
(15, 15, 'CRM Consultant', 170),
(16, 16, 'Legal AI Specialist', 140),
(17, 17, 'UI/UX Designer', 200),
(18, 18, 'Office Automation Expert', 160),
(19, 19, 'Data Architect', 180),
(20, 20, 'Hardware Engineer', 150);
