-- 用户数据库
CREATE DATABASE user_management;

USE user_management;

-- 用户表
CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    phone_number VARCHAR(20),
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME,
    is_active BOOLEAN DEFAULT TRUE
);

-- 用户地址表
CREATE TABLE user_addresses (
    address_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    address_type ENUM('HOME', 'WORK', 'OTHER') DEFAULT 'HOME',
    recipient_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    province VARCHAR(50),
    city VARCHAR(50),
    district VARCHAR(50),
    detail_address TEXT NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 用户支付方式表
CREATE TABLE user_payment_methods (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    payment_type ENUM('CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'ALIPAY', 'WECHAT') NOT NULL,
    card_last_four VARCHAR(4),
    card_brand VARCHAR(20),
    is_default BOOLEAN DEFAULT FALSE,
    expiry_date DATE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 插入测试数据
INSERT INTO users (username, email, password_hash, full_name, phone_number) VALUES
('john_doe', 'john@example.com', 'hashed_password_1', 'John Doe', '13800138001'),
('jane_smith', 'jane@example.com', 'hashed_password_2', 'Jane Smith', '13800138002'),
('alice_wang', 'alice@example.com', 'hashed_password_3', 'Alice Wang', '13800138003'),
('bob_li', 'bob@example.com', 'hashed_password_4', 'Bob Li', '13800138004'),
('carol_zhao', 'carol@example.com', 'hashed_password_5', 'Carol Zhao', '13800138005');

INSERT INTO user_addresses (user_id, address_type, recipient_name, phone, province, city, district, detail_address, is_default) VALUES
(1, 'HOME', 'John Doe', '13800138001', '北京市', '北京市', '朝阳区', '建国门外大街1号国贸大厦A座', TRUE),
(1, 'WORK', 'John Doe', '13800138001', '上海市', '上海市', '浦东新区', '陆家嘴环路100号', FALSE),
(2, 'HOME', 'Jane Smith', '13800138002', '浙江省', '杭州市', '西湖区', '文三路478号华星时代广场', TRUE),
(3, 'HOME', 'Alice Wang', '13800138003', '广东省', '深圳市', '南山区', '科技园科技南路1号', TRUE),
(4, 'HOME', 'Bob Li', '13800138004', '江苏省', '南京市', '鼓楼区', '中山路321号', TRUE);

INSERT INTO user_payment_methods (user_id, payment_type, card_last_four, card_brand, is_default) VALUES
(1, 'CREDIT_CARD', '1234', 'VISA', TRUE),
(1, 'ALIPAY', NULL, NULL, FALSE),
(2, 'WECHAT', NULL, NULL, TRUE),
(3, 'CREDIT_CARD', '5678', 'MasterCard', TRUE),
(4, 'DEBIT_CARD', '9012', 'UnionPay', TRUE);










-- 商品数据库
CREATE DATABASE product_management;

USE product_management;

-- 商品分类表
CREATE TABLE categories (
    category_id INT PRIMARY KEY AUTO_INCREMENT,
    category_name VARCHAR(100) NOT NULL,
    parent_category_id INT DEFAULT NULL,
    description TEXT,
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_category_id) REFERENCES categories(category_id) ON DELETE SET NULL
);

-- 商品表
CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    sku VARCHAR(50) UNIQUE NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    description TEXT,
    category_id INT NOT NULL,
    brand VARCHAR(100),
    unit_price DECIMAL(10,2) NOT NULL,
    cost_price DECIMAL(10,2),
    stock_quantity INT DEFAULT 0,
    reserved_quantity INT DEFAULT 0,
    weight_kg DECIMAL(8,3),
    is_listed BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
);

-- 商品图片表
CREATE TABLE product_images (
    image_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    image_url VARCHAR(500) NOT NULL,
    image_type ENUM('MAIN', 'THUMBNAIL', 'DETAIL', 'GALLERY') DEFAULT 'GALLERY',
    display_order INT DEFAULT 0,
    alt_text VARCHAR(200),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- 商品库存变动记录表
CREATE TABLE inventory_logs (
    log_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    change_type ENUM('PURCHASE', 'SALE', 'RETURN', 'ADJUSTMENT', 'DAMAGE') NOT NULL,
    quantity_change INT NOT NULL,
    previous_quantity INT,
    new_quantity INT,
    reference_id VARCHAR(100),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- 插入测试数据
INSERT INTO categories (category_name, parent_category_id, description) VALUES
('电子产品', NULL, '各种电子设备和配件'),
('手机', 1, '智能手机和功能手机'),
('笔记本电脑', 1, '便携式电脑设备'),
('服装服饰', NULL, '服装鞋帽配饰'),
('男装', 4, '男性服装');

INSERT INTO products (sku, product_name, description, category_id, brand, unit_price, stock_quantity) VALUES
('IPHONE13-128', 'iPhone 13 128GB', '苹果最新款智能手机，A15芯片，超视网膜XDR显示屏', 2, 'Apple', 5999.00, 100),
('MACBOOK-AIR', 'MacBook Air M2', '苹果M2芯片笔记本电脑，轻薄便携，超长续航', 3, 'Apple', 8999.00, 50),
('SAMSUNG-S22', 'Samsung Galaxy S22', '三星旗舰智能手机，Dynamic AMOLED 2X屏幕', 2, 'Samsung', 4999.00, 80),
('LENOVO-LEGION', 'Lenovo Legion 5 Pro', '联想游戏笔记本电脑，RTX 3060显卡，165Hz刷新率', 3, 'Lenovo', 7999.00, 30),
('NIKE-TSHIRT', 'Nike男士运动T恤', '耐克经典款运动T恤，速干面料，舒适透气', 5, 'Nike', 299.00, 200);

INSERT INTO product_images (product_id, image_url, image_type, display_order) VALUES
(1, 'https://example.com/images/iphone13-main.jpg', 'MAIN', 1),
(1, 'https://example.com/images/iphone13-detail1.jpg', 'DETAIL', 2),
(2, 'https://example.com/images/macbook-air-main.jpg', 'MAIN', 1),
(3, 'https://example.com/images/samsung-s22-main.jpg', 'MAIN', 1),
(4, 'https://example.com/images/lenovo-legion-main.jpg', 'MAIN', 1);

INSERT INTO inventory_logs (product_id, change_type, quantity_change, previous_quantity, new_quantity, notes) VALUES
(1, 'PURCHASE', 100, 0, 100, '初始库存'),
(2, 'PURCHASE', 50, 0, 50, '初始库存'),
(1, 'SALE', -5, 100, 95, '客户订单#1001'),
(3, 'ADJUSTMENT', 10, 70, 80, '库存调整'),
(5, 'PURCHASE', 200, 0, 200, '初始库存');









-- 订单数据库
CREATE DATABASE order_management;

USE order_management;

-- 订单主表
CREATE TABLE orders (
    order_id INT PRIMARY KEY AUTO_INCREMENT,
    order_number VARCHAR(50) UNIQUE NOT NULL,
    user_id INT NOT NULL,  -- 关联用户管理数据库的users表
    total_amount DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(10,2) DEFAULT 0,
    shipping_fee DECIMAL(8,2) DEFAULT 0,
    final_amount DECIMAL(12,2) NOT NULL,
    order_status ENUM('PENDING', 'PAID', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED') DEFAULT 'PENDING',
    payment_status ENUM('UNPAID', 'PAID', 'REFUNDED', 'PARTIALLY_REFUNDED') DEFAULT 'UNPAID',
    shipping_address TEXT NOT NULL,
    payment_method VARCHAR(50),
    order_notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 订单项表
CREATE TABLE order_items (
    order_item_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联商品管理数据库的products表
    sku VARCHAR(50) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    quantity INT NOT NULL,
    subtotal DECIMAL(12,2) NOT NULL,
    snapshot_data JSON,  -- 商品快照信息
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

-- 订单物流表
CREATE TABLE order_shipping (
    shipping_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    tracking_number VARCHAR(100),
    shipping_carrier VARCHAR(50),
    shipping_method VARCHAR(50),
    estimated_delivery_date DATE,
    actual_delivery_date DATE,
    shipping_status ENUM('PREPARING', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'FAILED') DEFAULT 'PREPARING',
    receiver_name VARCHAR(100),
    receiver_phone VARCHAR(20),
    shipping_address TEXT,
    notes TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

-- 订单支付记录表
CREATE TABLE payment_records (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    payment_number VARCHAR(50) UNIQUE NOT NULL,
    payment_amount DECIMAL(12,2) NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    payment_status ENUM('SUCCESS', 'FAILED', 'PENDING', 'REFUNDED') DEFAULT 'PENDING',
    transaction_id VARCHAR(100),
    payer_info JSON,
    payment_time DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

-- 插入测试数据
INSERT INTO orders (order_number, user_id, total_amount, discount_amount, shipping_fee, final_amount, order_status, shipping_address) VALUES
('ORD20231001001', 1, 5999.00, 0, 0, 5999.00, 'DELIVERED', '北京市朝阳区建国门外大街1号国贸大厦A座'),
('ORD20231001002', 2, 299.00, 10.00, 15.00, 304.00, 'SHIPPED', '浙江省杭州市西湖区文三路478号华星时代广场'),
('ORD20231001003', 3, 8999.00, 200.00, 0, 8799.00, 'PAID', '广东省深圳市南山区科技园科技南路1号'),
('ORD20231001004', 1, 12998.00, 500.00, 30.00, 12528.00, 'PROCESSING', '上海市浦东新区陆家嘴环路100号'),
('ORD20231001005', 4, 4999.00, 0, 0, 4999.00, 'PENDING', '江苏省南京市鼓楼区中山路321号');

INSERT INTO order_items (order_id, product_id, sku, product_name, unit_price, quantity, subtotal) VALUES
(1, 1, 'IPHONE13-128', 'iPhone 13 128GB', 5999.00, 1, 5999.00),
(2, 5, 'NIKE-TSHIRT', 'Nike男士运动T恤', 299.00, 1, 299.00),
(3, 2, 'MACBOOK-AIR', 'MacBook Air M2', 8999.00, 1, 8999.00),
(4, 1, 'IPHONE13-128', 'iPhone 13 128GB', 5999.00, 2, 11998.00),
(5, 3, 'SAMSUNG-S22', 'Samsung Galaxy S22', 4999.00, 1, 4999.00);

INSERT INTO order_shipping (order_id, tracking_number, shipping_carrier, shipping_method, estimated_delivery_date, shipping_status) VALUES
(1, 'SF1234567890', '顺丰速运', '标准快递', '2023-10-03', 'DELIVERED'),
(2, 'YT9876543210', '圆通速递', '普通快递', '2023-10-05', 'IN_TRANSIT'),
(3, 'JD5678901234', '京东物流', '次日达', '2023-10-04', 'PREPARING'),
(4, 'SF2345678901', '顺丰速运', '标准快递', '2023-10-06', 'PREPARING'),
(5, NULL, NULL, NULL, NULL, 'PREPARING');

INSERT INTO payment_records (order_id, payment_number, payment_amount, payment_method, payment_status, transaction_id) VALUES
(1, 'PAY20231001001', 5999.00, 'ALIPAY', 'SUCCESS', '2023100122001444550501234567'),
(2, 'PAY20231001002', 304.00, 'WECHAT', 'SUCCESS', '4200001919202310011234567890'),
(3, 'PAY20231001003', 8799.00, 'CREDIT_CARD', 'SUCCESS', 'txn_3OJq6P2eZvKYlo2C1XjH4w6E'),
(4, 'PAY20231001004', 12528.00, 'ALIPAY', 'SUCCESS', '2023100122001444550501234568'),
(5, 'PAY20231001005', 4999.00, 'CREDIT_CARD', 'PENDING', NULL);











-- 图书馆数据库
CREATE DATABASE library_management;

USE library_management;

-- 图书表
CREATE TABLE books (
    book_id INT PRIMARY KEY AUTO_INCREMENT,
    isbn VARCHAR(13) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(200) NOT NULL,
    publisher VARCHAR(200),
    publication_year YEAR,
    category VARCHAR(100),
    total_copies INT DEFAULT 1,
    available_copies INT DEFAULT 1,
    location VARCHAR(100),
    description TEXT,
    cover_image_url VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 读者表
CREATE TABLE readers (
    reader_id INT PRIMARY KEY AUTO_INCREMENT,
    reader_number VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    id_card VARCHAR(18) UNIQUE,
    email VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    membership_type ENUM('STUDENT', 'TEACHER', 'STAFF', 'PUBLIC') DEFAULT 'PUBLIC',
    membership_expiry DATE,
    max_borrow_limit INT DEFAULT 5,
    is_active BOOLEAN DEFAULT TRUE,
    registered_date DATE DEFAULT (CURRENT_DATE)
);

-- 借阅记录表
CREATE TABLE borrow_records (
    record_id INT PRIMARY KEY AUTO_INCREMENT,
    reader_id INT NOT NULL,
    book_id INT NOT NULL,
    borrow_date DATE NOT NULL,
    due_date DATE NOT NULL,
    return_date DATE,
    renewal_count INT DEFAULT 0,
    status ENUM('BORROWED', 'RETURNED', 'OVERDUE', 'LOST') DEFAULT 'BORROWED',
    fine_amount DECIMAL(8,2) DEFAULT 0,
    notes TEXT,
    FOREIGN KEY (reader_id) REFERENCES readers(reader_id),
    FOREIGN KEY (book_id) REFERENCES books(book_id)
);

-- 图书馆员工表
CREATE TABLE library_staff (
    staff_id INT PRIMARY KEY AUTO_INCREMENT,
    staff_number VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    position VARCHAR(100),
    department VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    phone VARCHAR(20),
    hire_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    permissions JSON  -- 存储权限信息
);

-- 插入测试数据
INSERT INTO books (isbn, title, author, publisher, publication_year, category, total_copies, available_copies) VALUES
('9787108009824', '红楼梦', '曹雪芹', '人民文学出版社', 1996, '古典文学', 10, 8),
('9787020002207', '围城', '钱钟书', '人民文学出版社', 1991, '现代文学', 5, 3),
('9787301204689', '经济学原理', '曼昆', '北京大学出版社', 2015, '经济学', 8, 6),
('9787115351531', 'Python编程从入门到实践', 'Eric Matthes', '人民邮电出版社', 2020, '计算机科学', 15, 10),
('9787510841245', '人类简史', '尤瓦尔·赫拉利', '中信出版社', 2017, '历史', 12, 9);

INSERT INTO readers (reader_number, full_name, id_card, email, phone, membership_type) VALUES
('R2023001', '张三', '110101199001011234', 'zhangsan@example.com', '13800138006', 'STUDENT'),
('R2023002', '李四', '110101199002022345', 'lisi@example.com', '13800138007', 'TEACHER'),
('R2023003', '王五', '110101199003033456', 'wangwu@example.com', '13800138008', 'PUBLIC'),
('R2023004', '赵六', '110101199004044567', 'zhaoliu@example.com', '13800138009', 'STAFF'),
('R2023005', '孙七', '110101199005055678', 'sunqi@example.com', '13800138010', 'STUDENT');

INSERT INTO borrow_records (reader_id, book_id, borrow_date, due_date, return_date, status) VALUES
(1, 1, '2023-09-20', '2023-10-20', '2023-10-18', 'RETURNED'),
(1, 2, '2023-10-01', '2023-10-31', NULL, 'BORROWED'),
(2, 3, '2023-09-25', '2023-10-25', NULL, 'BORROWED'),
(3, 4, '2023-10-01', '2023-10-31', NULL, 'BORROWED'),
(4, 5, '2023-09-15', '2023-10-15', '2023-10-14', 'RETURNED');

INSERT INTO library_staff (staff_number, full_name, position, department, email, phone) VALUES
('S001', '王馆长', '馆长', '管理部', 'director@library.com', '13800138111'),
('S002', '李管理员', '图书管理员', '流通部', 'librarian1@library.com', '13800138112'),
('S003', '张技术员', '系统管理员', '技术部', 'tech@library.com', '13800138113'),
('S004', '刘采购', '采购专员', '采编部', 'purchase@library.com', '13800138114'),
('S005', '陈会计', '财务主管', '财务部', 'finance@library.com', '13800138115');






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
