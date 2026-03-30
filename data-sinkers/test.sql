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














-- 营销推广数据库
CREATE DATABASE marketing_promotion;

USE marketing_promotion;

-- 优惠券表
CREATE TABLE coupons (
    coupon_id INT PRIMARY KEY AUTO_INCREMENT,
    coupon_code VARCHAR(50) UNIQUE NOT NULL,
    coupon_name VARCHAR(100) NOT NULL,
    coupon_type ENUM('FIXED_DISCOUNT', 'PERCENTAGE_DISCOUNT', 'SHIPPING_FREE') NOT NULL,
    discount_value DECIMAL(10,2),
    min_order_amount DECIMAL(10,2) DEFAULT 0,
    max_discount_amount DECIMAL(10,2),
    valid_from DATETIME NOT NULL,
    valid_to DATETIME NOT NULL,
    total_quantity INT,
    remaining_quantity INT,
    per_user_limit INT DEFAULT 1,
    scope_type ENUM('ALL', 'CATEGORY', 'PRODUCT') DEFAULT 'ALL',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- 用户优惠券领取表
CREATE TABLE user_coupons (
    user_coupon_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,  -- 关联users表
    coupon_id INT NOT NULL,
    status ENUM('UNUSED', 'USED', 'EXPIRED') DEFAULT 'UNUSED',
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    used_at DATETIME,
    order_id INT,  -- 关联orders表
    FOREIGN KEY (coupon_id) REFERENCES coupons(coupon_id)
);

-- 秒杀活动表
CREATE TABLE flash_sales (
    flash_sale_id INT PRIMARY KEY AUTO_INCREMENT,
    activity_name VARCHAR(100) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    status ENUM('UPCOMING', 'ACTIVE', 'ENDED') DEFAULT 'UPCOMING',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 秒杀商品表
CREATE TABLE flash_sale_products (
    flash_sale_product_id INT PRIMARY KEY AUTO_INCREMENT,
    flash_sale_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联products表
    flash_sale_price DECIMAL(10,2) NOT NULL,
    flash_sale_quantity INT NOT NULL,
    sold_quantity INT DEFAULT 0,
    per_user_limit INT DEFAULT 1,
    FOREIGN KEY (flash_sale_id) REFERENCES flash_sales(flash_sale_id)
);

-- 积分表
CREATE TABLE points (
    point_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,  -- 关联users表
    total_points INT DEFAULT 0,
    used_points INT DEFAULT 0,
    expired_points INT DEFAULT 0,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 积分流水表
CREATE TABLE point_transactions (
    transaction_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,  -- 关联users表
    point_id INT NOT NULL,
    points_change INT NOT NULL,
    transaction_type ENUM('EARN', 'REDEEM', 'EXPIRE', 'ADJUST') NOT NULL,
    source_type ENUM('ORDER', 'REVIEW', 'SIGN_IN', 'ACTIVITY') NOT NULL,
    source_id VARCHAR(100),
    description VARCHAR(200),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (point_id) REFERENCES points(point_id)
);

-- 插入营销推广数据（与现有数据联动）
INSERT INTO coupons (coupon_code, coupon_name, coupon_type, discount_value, min_order_amount, valid_from, valid_to, total_quantity, remaining_quantity) VALUES
('NEWUSER50', '新用户50元券', 'FIXED_DISCOUNT', 50.00, 200.00, '2023-10-01 00:00:00', '2023-12-31 23:59:59', 1000, 997),
('SUMMER10', '夏季88折', 'PERCENTAGE_DISCOUNT', 0.88, 500.00, '2023-06-01 00:00:00', '2023-08-31 23:59:59', 500, 350),
('FREESHIP', '免邮券', 'SHIPPING_FREE', NULL, 100.00, '2023-10-01 00:00:00', '2023-10-31 23:59:59', 200, 150);

-- 用户领取优惠券（user_id 1-5 来自用户管理）
INSERT INTO user_coupons (user_id, coupon_id, status, used_at, order_id) VALUES
(1, 1, 'USED', '2023-10-01 10:30:00', 1),
(1, 2, 'UNUSED', NULL, NULL),
(2, 3, 'USED', '2023-10-02 14:20:00', 2),
(3, 1, 'UNUSED', NULL, NULL),
(4, 2, 'UNUSED', NULL, NULL);

-- 秒杀活动
INSERT INTO flash_sales (activity_name, start_time, end_time, status) VALUES
('双11预售秒杀', '2023-11-10 20:00:00', '2023-11-11 02:00:00', 'UPCOMING'),
('周末狂欢', '2023-10-14 10:00:00', '2023-10-15 22:00:00', 'ACTIVE');

-- 秒杀商品（product_id 1-5 来自商品管理）
INSERT INTO flash_sale_products (flash_sale_id, product_id, flash_sale_price, flash_sale_quantity, sold_quantity) VALUES
(1, 1, 4999.00, 10, 0),
(1, 2, 7999.00, 5, 0),
(2, 5, 199.00, 100, 35),
(2, 3, 4299.00, 20, 8);

-- 初始化用户积分（user_id 1-5 来自用户管理）
INSERT INTO points (user_id, total_points, used_points) VALUES
(1, 1500, 200),
(2, 800, 0),
(3, 2200, 500),
(4, 300, 100),
(5, 50, 0);

-- 积分流水
INSERT INTO point_transactions (user_id, point_id, points_change, transaction_type, source_type, source_id, description) VALUES
(1, 1, 500, 'EARN', 'ORDER', 'ORD20231001001', '订单完成赠送积分'),
(1, 1, -200, 'REDEEM', 'ORDER', 'ORD20231001004', '积分抵扣'),
(2, 2, 300, 'EARN', 'REVIEW', 'REV001', '评价商品赠送积分'),
(3, 3, 1000, 'EARN', 'ORDER', 'ORD20231001003', '订单完成赠送积分'),
(3, 3, -500, 'REDEEM', 'ORDER', 'ORD20231001003', '积分抵扣');















-- 库存仓储数据库
CREATE DATABASE inventory_warehouse;

USE inventory_warehouse;

-- 仓库表
CREATE TABLE warehouses (
    warehouse_id INT PRIMARY KEY AUTO_INCREMENT,
    warehouse_code VARCHAR(50) UNIQUE NOT NULL,
    warehouse_name VARCHAR(100) NOT NULL,
    region VARCHAR(50),
    address TEXT NOT NULL,
    contact_person VARCHAR(50),
    contact_phone VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE
);

-- 库存表（多仓库库存）
CREATE TABLE inventory (
    inventory_id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,  -- 关联products表
    warehouse_id INT NOT NULL,
    sku VARCHAR(50) NOT NULL,
    quantity INT DEFAULT 0,
    locked_quantity INT DEFAULT 0,  -- 已锁定（待发货）
    available_quantity INT GENERATED ALWAYS AS (quantity - locked_quantity) STORED,
    min_stock_level INT DEFAULT 10,
    max_stock_level INT DEFAULT 1000,
    last_count_date DATETIME,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
    UNIQUE KEY unique_product_warehouse (product_id, warehouse_id)
);

-- 入库单表
CREATE TABLE inbound_orders (
    inbound_id INT PRIMARY KEY AUTO_INCREMENT,
    inbound_number VARCHAR(50) UNIQUE NOT NULL,
    warehouse_id INT NOT NULL,
    supplier VARCHAR(100),
    inbound_type ENUM('PURCHASE', 'RETURN', 'TRANSFER') NOT NULL,
    reference_order VARCHAR(100),
    status ENUM('PENDING', 'RECEIVING', 'COMPLETED', 'CANCELLED') DEFAULT 'PENDING',
    expected_date DATE,
    received_date DATETIME,
    created_by VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);

-- 入库单明细表
CREATE TABLE inbound_items (
    inbound_item_id INT PRIMARY KEY AUTO_INCREMENT,
    inbound_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联products表
    sku VARCHAR(50) NOT NULL,
    expected_quantity INT NOT NULL,
    received_quantity INT DEFAULT 0,
    unit_price DECIMAL(10,2),
    batch_number VARCHAR(50),
    expiry_date DATE,
    FOREIGN KEY (inbound_id) REFERENCES inbound_orders(inbound_id),
    FOREIGN KEY (product_id) REFERENCES inventory(product_id)  -- 这里需要注意，实际应该关联product_management.products
);

-- 出库单表（关联订单）
CREATE TABLE outbound_orders (
    outbound_id INT PRIMARY KEY AUTO_INCREMENT,
    outbound_number VARCHAR(50) UNIQUE NOT NULL,
    order_id INT NOT NULL,  -- 关联orders表
    warehouse_id INT NOT NULL,
    outbound_type ENUM('SALE', 'RETURN_TO_SUPPLIER', 'TRANSFER') DEFAULT 'SALE',
    status ENUM('PENDING', 'PICKING', 'PACKED', 'SHIPPED', 'CANCELLED') DEFAULT 'PENDING',
    shipping_company VARCHAR(50),
    tracking_number VARCHAR(100),
    outbound_date DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);

-- 出库单明细表
CREATE TABLE outbound_items (
    outbound_item_id INT PRIMARY KEY AUTO_INCREMENT,
    outbound_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联products表
    sku VARCHAR(50) NOT NULL,
    expected_quantity INT NOT NULL,
    picked_quantity INT DEFAULT 0,
    actual_quantity INT,
    FOREIGN KEY (outbound_id) REFERENCES outbound_orders(outbound_id)
);

-- 库存盘点表
CREATE TABLE stock_counts (
    count_id INT PRIMARY KEY AUTO_INCREMENT,
    warehouse_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联products表
    sku VARCHAR(50) NOT NULL,
    system_quantity INT NOT NULL,
    physical_quantity INT NOT NULL,
    difference_quantity INT GENERATED ALWAYS AS (physical_quantity - system_quantity) STORED,
    count_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    counted_by VARCHAR(100),
    notes TEXT,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);

-- 插入仓库数据
INSERT INTO warehouses (warehouse_code, warehouse_name, region, address, contact_person, contact_phone) VALUES
('WH001', '北京华北仓', '华北', '北京市大兴区物流园8号', '张经理', '13900112233'),
('WH002', '上海华东仓', '华东', '上海市青浦区物流园区15号', '李经理', '13900112244'),
('WH003', '广州华南仓', '华南', '广州市番禺区物流大道3号', '王经理', '13900112255');

-- 初始化各仓库库存（product_id 1-5 来自商品管理）
-- 注意：product_management.products表中的库存总量要相应更新
INSERT INTO inventory (product_id, warehouse_id, sku, quantity, locked_quantity, min_stock_level) VALUES
(1, 1, 'IPHONE13-128', 30, 0, 10),
(1, 2, 'IPHONE13-128', 40, 2, 10),
(1, 3, 'IPHONE13-128', 30, 0, 10),
(2, 1, 'MACBOOK-AIR', 20, 1, 5),
(2, 2, 'MACBOOK-AIR', 20, 0, 5),
(2, 3, 'MACBOOK-AIR', 10, 0, 5),
(3, 1, 'SAMSUNG-S22', 25, 0, 8),
(3, 2, 'SAMSUNG-S22', 35, 0, 8),
(3, 3, 'SAMSUNG-S22', 20, 1, 8),
(4, 1, 'LENOVO-LEGION', 10, 0, 5),
(4, 2, 'LENOVO-LEGION', 15, 0, 5),
(5, 1, 'NIKE-TSHIRT', 80, 0, 20),
(5, 2, 'NIKE-TSHIRT', 70, 0, 20),
(5, 3, 'NIKE-TSHIRT', 50, 1, 20);

-- 根据订单创建出库单（关联order_management.orders表）
INSERT INTO outbound_orders (outbound_number, order_id, warehouse_id, status, shipping_company, tracking_number) VALUES
('OUT20231001001', 1, 2, 'SHIPPED', '顺丰速运', 'SF1234567890'),
('OUT20231001002', 2, 1, 'SHIPPED', '圆通速递', 'YT9876543210'),
('OUT20231001003', 3, 2, 'PACKED', '京东物流', 'JD5678901234'),
('OUT20231001004', 4, 2, 'PICKING', NULL, NULL),
('OUT20231001005', 5, 3, 'PENDING', NULL, NULL);

-- 出库单明细
INSERT INTO outbound_items (outbound_id, product_id, sku, expected_quantity, picked_quantity) VALUES
(1, 1, 'IPHONE13-128', 1, 1),
(2, 5, 'NIKE-TSHIRT', 1, 1),
(3, 2, 'MACBOOK-AIR', 1, 1),
(4, 1, 'IPHONE13-128', 2, 2),
(5, 3, 'SAMSUNG-S22', 1, 0);

-- 入库单（补货）
INSERT INTO inbound_orders (inbound_number, warehouse_id, supplier, inbound_type, status, expected_date) VALUES
('IN20231001001', 1, 'Apple中国', 'PURCHASE', 'COMPLETED', '2023-10-05'),
('IN20231001002', 2, '三星电子', 'PURCHASE', 'COMPLETED', '2023-10-06'),
('IN20231001003', 1, 'Nike体育', 'PURCHASE', 'RECEIVING', '2023-10-10'),
('IN20231001004', 3, '联想集团', 'PURCHASE', 'PENDING', '2023-10-15');

INSERT INTO inbound_items (inbound_id, product_id, sku, expected_quantity, received_quantity) VALUES
(1, 1, 'IPHONE13-128', 50, 50),
(1, 2, 'MACBOOK-AIR', 20, 20),
(2, 3, 'SAMSUNG-S22', 30, 30),
(3, 5, 'NIKE-TSHIRT', 100, 60),
(4, 4, 'LENOVO-LEGION', 15, 0);

-- 盘点记录
INSERT INTO stock_counts (warehouse_id, product_id, sku, system_quantity, physical_quantity, counted_by, notes) VALUES
(1, 1, 'IPHONE13-128', 30, 30, '张小明', '盘点一致'),
(1, 5, 'NIKE-TSHIRT', 80, 78, '张小明', '损耗2件'),
(2, 2, 'MACBOOK-AIR', 20, 20, '李华', '盘点一致'),
(3, 3, 'SAMSUNG-S22', 20, 19, '王芳', '一件破损');











-- 客户服务数据库
CREATE DATABASE customer_service;

USE customer_service;

-- 售后申请/退换货表
CREATE TABLE returns_requests (
    return_id INT PRIMARY KEY AUTO_INCREMENT,
    return_number VARCHAR(50) UNIQUE NOT NULL,
    order_id INT NOT NULL,  -- 关联orders表
    user_id INT NOT NULL,  -- 关联users表
    product_id INT NOT NULL,  -- 关联products表
    return_type ENUM('REFUND', 'EXCHANGE', 'REPAIR') NOT NULL,
    reason_code VARCHAR(50),
    reason_description TEXT,
    quantity INT NOT NULL,
    return_amount DECIMAL(10,2),
    status ENUM('PENDING', 'APPROVED', 'REJECTED', 'COMPLETED', 'CLOSED') DEFAULT 'PENDING',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 售后流程跟踪表
CREATE TABLE return_process (
    process_id INT PRIMARY KEY AUTO_INCREMENT,
    return_id INT NOT NULL,
    step ENUM('APPLY', 'APPROVE', 'RECEIVE', 'INSPECT', 'REFUND', 'EXCHANGE', 'COMPLETE') NOT NULL,
    status ENUM('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED') DEFAULT 'PENDING',
    operator VARCHAR(100),
    operation_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (return_id) REFERENCES returns_requests(return_id)
);

-- 商品评价表
CREATE TABLE reviews (
    review_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,  -- 关联users表
    product_id INT NOT NULL,  -- 关联products表
    order_id INT NOT NULL,  -- 关联orders表
    order_item_id INT,  -- 关联order_items表
    rating TINYINT CHECK (rating >= 1 AND rating <= 5),
    title VARCHAR(200),
    content TEXT,
    is_anonymous BOOLEAN DEFAULT FALSE,
    is_verified_purchase BOOLEAN DEFAULT TRUE,
    likes_count INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 评价图片表
CREATE TABLE review_images (
    image_id INT PRIMARY KEY AUTO_INCREMENT,
    review_id INT NOT NULL,
    image_url VARCHAR(500) NOT NULL,
    display_order INT DEFAULT 0,
    FOREIGN KEY (review_id) REFERENCES reviews(review_id) ON DELETE CASCADE
);

-- 客服对话/咨询表
CREATE TABLE support_tickets (
    ticket_id INT PRIMARY KEY AUTO_INCREMENT,
    ticket_number VARCHAR(50) UNIQUE NOT NULL,
    user_id INT NOT NULL,  -- 关联users表
    order_id INT,  -- 关联orders表
    category ENUM('ORDER_ISSUE', 'PRODUCT_QUESTION', 'PAYMENT', 'SHIPPING', 'RETURN', 'OTHER') NOT NULL,
    subject VARCHAR(200) NOT NULL,
    description TEXT,
    priority ENUM('LOW', 'MEDIUM', 'HIGH', 'URGENT') DEFAULT 'MEDIUM',
    status ENUM('OPEN', 'PROCESSING', 'WAITING', 'RESOLVED', 'CLOSED') DEFAULT 'OPEN',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 客服对话记录表
CREATE TABLE ticket_messages (
    message_id INT PRIMARY KEY AUTO_INCREMENT,
    ticket_id INT NOT NULL,
    sender_type ENUM('CUSTOMER', 'SUPPORT') NOT NULL,
    message TEXT NOT NULL,
    attachments JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(ticket_id) ON DELETE CASCADE
);

-- 用户反馈/建议表
CREATE TABLE feedback (
    feedback_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,  -- 关联users表
    feedback_type ENUM('SUGGESTION', 'COMPLAINT', 'PRAISE', 'QUESTION') NOT NULL,
    content TEXT NOT NULL,
    rating TINYINT,
    status ENUM('PENDING', 'PROCESSED', 'REPLIED') DEFAULT 'PENDING',
    reply_content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME
);

-- 插入售后申请数据（关联现有订单）
INSERT INTO returns_requests (return_number, order_id, user_id, product_id, return_type, reason_code, reason_description, quantity, return_amount, status) VALUES
('R20231001001', 2, 2, 5, 'EXCHANGE', 'SIZE_ISSUE', '尺码偏大，需要换小一码', 1, 299.00, 'COMPLETED'),
('R20231001002', 4, 1, 1, 'REFUND', 'QUALITY_ISSUE', '手机屏幕有划痕', 1, 5999.00, 'APPROVED'),
('R20231001003', 1, 1, 1, 'REFUND', 'WRONG_ITEM', '颜色发错', 1, 5999.00, 'PENDING'),
('R20231001004', 5, 4, 3, 'REFUND', 'NOT_AS_DESCRIBED', '与描述不符', 1, 4999.00, 'REJECTED');

-- 售后流程跟踪
INSERT INTO return_process (return_id, step, status, operator, notes) VALUES
(1, 'APPLY', 'COMPLETED', '系统', '用户提交换货申请'),
(1, 'APPROVE', 'COMPLETED', '客服李娜', '审核通过，同意换货'),
(1, 'RECEIVE', 'COMPLETED', '仓库王强', '收到退货商品'),
(1, 'INSPECT', 'COMPLETED', '质检张伟', '商品完好，同意换货'),
(1, 'EXCHANGE', 'COMPLETED', '仓库王强', '已发出新商品'),
(2, 'APPLY', 'COMPLETED', '系统', '用户提交退款申请'),
(2, 'APPROVE', 'COMPLETED', '客服李娜', '审核通过，同意退款');

-- 插入商品评价数据（关联订单）
INSERT INTO reviews (user_id, product_id, order_id, order_item_id, rating, title, content, is_anonymous) VALUES
(1, 1, 1, 1, 5, 'iPhone 13真不错', '手机很好用，系统流畅，拍照清晰，非常满意！', FALSE),
(1, 5, 2, 2, 4, 'T恤质量不错', '面料舒适，就是尺码稍微偏大', FALSE),
(3, 2, 3, 3, 5, 'MacBook Air M2太强了', '轻薄便携，续航给力，M2芯片性能强劲', FALSE),
(2, 5, 2, 2, 3, '一般般', '感觉价格有点贵', TRUE),
(4, 3, 5, 5, 4, 'S22不错', '屏幕效果很好，就是电池续航一般', FALSE);

-- 评价图片
INSERT INTO review_images (review_id, image_url, display_order) VALUES
(1, 'https://example.com/review/iphone13-1.jpg', 1),
(1, 'https://example.com/review/iphone13-2.jpg', 2),
(3, 'https://example.com/review/macbook-1.jpg', 1),
(5, 'https://example.com/review/s22-1.jpg', 1);

-- 插入客服工单
INSERT INTO support_tickets (ticket_number, user_id, order_id, category, subject, description, priority, status) VALUES
('TK20231001001', 2, 2, 'SHIPPING', '物流太慢了', '我的订单ORD20231001002显示已发货好几天了，物流一直没有更新', 'MEDIUM', 'PROCESSING'),
('TK20231001002', 1, 4, 'PAYMENT', '支付重复扣款', '我支付订单ORD20231001004时，支付宝扣了两次款', 'HIGH', 'OPEN'),
('TK20231001003', 5, NULL, 'PRODUCT_QUESTION', 'S22是否有赠品', '想咨询一下购买Samsung S22有没有送充电器', 'LOW', 'RESOLVED'),
('TK20231001004', 3, 3, 'ORDER_ISSUE', '修改收货地址', '订单ORD20231001003还没发货，可以修改地址吗', 'MEDIUM', 'WAITING');

-- 工单对话记录
INSERT INTO ticket_messages (ticket_id, sender_type, message) VALUES
(1, 'CUSTOMER', '物流好几天没更新了，能帮忙查查吗'),
(1, 'SUPPORT', '您好，我帮您查询一下，请稍等'),
(1, 'SUPPORT', '查到了，包裹已到达杭州中转站，预计明天送达'),
(2, 'CUSTOMER', '支付宝扣了两次款，但是订单只显示支付一次'),
(2, 'SUPPORT', '您好，请提供一下支付宝交易号'),
(3, 'CUSTOMER', 'S22现在购买有赠品吗？'),
(3, 'SUPPORT', '您好，现在购买S22赠送25W充电器一个'),
(4, 'CUSTOMER', '刚下单，地址写错了，能改吗'),
(4, 'SUPPORT', '可以的，请提供正确地址');

-- 用户反馈
INSERT INTO feedback (user_id, feedback_type, content, rating, status) VALUES
(1, 'PRAISE', '发货速度快，包装完好', 5, 'PROCESSED'),
(3, 'SUGGESTION', '希望能增加更多支付方式', NULL, 'PENDING'),
(2, 'COMPLAINT', '客服响应速度太慢了', 2, 'PENDING'),
(4, 'QUESTION', '什么时候有新品手机上市', NULL, 'REPLIED');


















-- 供应链管理系统数据库
CREATE DATABASE supply_chain;

USE supply_chain;

-- =====================================================
-- 第一子域：采购域 (Purchase Domain)
-- =====================================================

-- 供应商表
CREATE TABLE suppliers (
    supplier_id INT PRIMARY KEY AUTO_INCREMENT,
    supplier_code VARCHAR(50) UNIQUE NOT NULL,
    supplier_name VARCHAR(200) NOT NULL,
    supplier_type ENUM('MANUFACTURER', 'DISTRIBUTOR', 'AGENT') NOT NULL,
    contact_person VARCHAR(100),
    contact_phone VARCHAR(20),
    email VARCHAR(100),
    address TEXT,
    payment_terms VARCHAR(100),
    cooperation_start_date DATE,
    credit_rating ENUM('A', 'B', 'C', 'D') DEFAULT 'B',
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 采购订单表
CREATE TABLE purchase_orders (
    purchase_id INT PRIMARY KEY AUTO_INCREMENT,
    purchase_number VARCHAR(50) UNIQUE NOT NULL,
    supplier_id INT NOT NULL,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    expected_delivery_date DATE,
    actual_delivery_date DATE,
    total_amount DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(10,2) DEFAULT 0,
    final_amount DECIMAL(12,2) NOT NULL,
    status ENUM('DRAFT', 'SUBMITTED', 'CONFIRMED', 'SHIPPED', 'RECEIVED', 'CANCELLED') DEFAULT 'DRAFT',
    payment_status ENUM('UNPAID', 'PARTIAL', 'PAID') DEFAULT 'UNPAID',
    payment_due_date DATE,
    created_by VARCHAR(100),
    notes TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
);

-- 采购订单明细表
CREATE TABLE purchase_items (
    purchase_item_id INT PRIMARY KEY AUTO_INCREMENT,
    purchase_id INT NOT NULL,
    product_id INT NOT NULL,  -- 关联电商系统的商品表
    sku VARCHAR(50) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    quantity INT NOT NULL,
    received_quantity INT DEFAULT 0,
    rejected_quantity INT DEFAULT 0,
    subtotal DECIMAL(12,2) NOT NULL,
    tax_rate DECIMAL(5,2) DEFAULT 13.00,
    FOREIGN KEY (purchase_id) REFERENCES purchase_orders(purchase_id)
);

-- 采购合同表
CREATE TABLE purchase_contracts (
    contract_id INT PRIMARY KEY AUTO_INCREMENT,
    contract_number VARCHAR(50) UNIQUE NOT NULL,
    supplier_id INT NOT NULL,
    contract_name VARCHAR(200) NOT NULL,
    contract_type ENUM('FRAMEWORK', 'ONE_TIME', 'LONG_TERM') NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_value DECIMAL(15,2),
    payment_terms TEXT,
    delivery_terms TEXT,
    quality_requirements TEXT,
    file_url VARCHAR(500),
    status ENUM('DRAFT', 'ACTIVE', 'EXPIRED', 'TERMINATED') DEFAULT 'DRAFT',
    signed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
);

-- 采购入库质检表
CREATE TABLE quality_inspections (
    inspection_id INT PRIMARY KEY AUTO_INCREMENT,
    purchase_id INT NOT NULL,
    purchase_item_id INT NOT NULL,
    inspection_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    inspector VARCHAR(100),
    sample_size INT NOT NULL,
    qualified_quantity INT NOT NULL,
    defective_quantity INT NOT NULL,
    defect_rate DECIMAL(5,2) GENERATED ALWAYS AS (
        ROUND(CAST(defective_quantity AS DECIMAL(10,2)) / NULLIF(sample_size, 0) * 100, 2)
    ) STORED,
    inspection_result ENUM('PASS', 'FAIL', 'PARTIAL') NOT NULL,
    defect_details JSON,
    remarks TEXT,
    FOREIGN KEY (purchase_id) REFERENCES purchase_orders(purchase_id),
    FOREIGN KEY (purchase_item_id) REFERENCES purchase_items(purchase_item_id)
);

-- =====================================================
-- 第二子域：物流域 (Logistics Domain)
-- =====================================================

-- 承运商表
CREATE TABLE carriers (
    carrier_id INT PRIMARY KEY AUTO_INCREMENT,
    carrier_code VARCHAR(50) UNIQUE NOT NULL,
    carrier_name VARCHAR(100) NOT NULL,
    carrier_type ENUM('EXPRESS', 'FREIGHT', 'COLD_CHAIN', 'INTERNATIONAL') NOT NULL,
    contact_person VARCHAR(100),
    contact_phone VARCHAR(20),
    service_areas TEXT,
    price_model VARCHAR(100),
    cooperation_level ENUM('STRATEGIC', 'PREFERRED', 'GENERAL') DEFAULT 'GENERAL',
    is_active BOOLEAN DEFAULT TRUE
);

-- 运输订单表
CREATE TABLE transport_orders (
    transport_id INT PRIMARY KEY AUTO_INCREMENT,
    transport_number VARCHAR(50) UNIQUE NOT NULL,
    source_type ENUM('SALE_ORDER', 'PURCHASE_ORDER', 'TRANSFER') NOT NULL,
    source_id VARCHAR(50) NOT NULL,  -- 可以关联电商订单号或采购订单号
    carrier_id INT NOT NULL,
    carrier_contact VARCHAR(100),
    carrier_phone VARCHAR(20),
    
    -- 发货信息
    sender_name VARCHAR(100) NOT NULL,
    sender_phone VARCHAR(20) NOT NULL,
    sender_address TEXT NOT NULL,
    sender_warehouse_id INT,  -- 关联库存系统的仓库
    
    -- 收货信息
    receiver_name VARCHAR(100) NOT NULL,
    receiver_phone VARCHAR(20) NOT NULL,
    receiver_address TEXT NOT NULL,
    
    -- 货物信息
    total_weight_kg DECIMAL(10,2),
    total_volume_m3 DECIMAL(10,2),
    package_count INT,
    goods_value DECIMAL(12,2),
    insurance_amount DECIMAL(12,2) DEFAULT 0,
    
    -- 物流状态
    tracking_number VARCHAR(100),
    shipping_date DATETIME,
    estimated_delivery DATE,
    actual_delivery DATETIME,
    transport_status ENUM('PENDING', 'PICKED_UP', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'EXCEPTION', 'CANCELLED') DEFAULT 'PENDING',
    exception_reason TEXT,
    
    -- 费用信息
    shipping_fee DECIMAL(10,2) DEFAULT 0,
    fuel_surcharge DECIMAL(10,2) DEFAULT 0,
    insurance_fee DECIMAL(10,2) DEFAULT 0,
    total_fee DECIMAL(12,2) GENERATED ALWAYS AS (shipping_fee + fuel_surcharge + insurance_fee) STORED,
    payment_status ENUM('UNPAID', 'PAID') DEFAULT 'UNPAID',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (carrier_id) REFERENCES carriers(carrier_id)
);

-- 物流轨迹表
CREATE TABLE transport_tracking (
    tracking_id INT PRIMARY KEY AUTO_INCREMENT,
    transport_id INT NOT NULL,
    tracking_number VARCHAR(100) NOT NULL,
    status_code VARCHAR(50),
    status_description VARCHAR(200),
    location VARCHAR(200),
    operator VARCHAR(100),
    operation_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    remarks TEXT,
    FOREIGN KEY (transport_id) REFERENCES transport_orders(transport_id)
);

-- 车辆管理表
CREATE TABLE fleet_vehicles (
    vehicle_id INT PRIMARY KEY AUTO_INCREMENT,
    plate_number VARCHAR(20) UNIQUE NOT NULL,
    vehicle_type ENUM('VAN', 'TRUCK', 'REFRIGERATED', 'MOTORCYCLE') NOT NULL,
    brand VARCHAR(50),
    model VARCHAR(50),
    capacity_kg DECIMAL(8,2),
    capacity_m3 DECIMAL(8,2),
    owner_type ENUM('SELF', 'LEASED', 'THIRD_PARTY') DEFAULT 'SELF',
    owner_company VARCHAR(100),
    driver_name VARCHAR(100),
    driver_phone VARCHAR(20),
    status ENUM('AVAILABLE', 'IN_USE', 'MAINTENANCE', 'OFFLINE') DEFAULT 'AVAILABLE',
    insurance_expiry DATE,
    inspection_expiry DATE,
    last_maintenance_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 配送路线表
CREATE TABLE delivery_routes (
    route_id INT PRIMARY KEY AUTO_INCREMENT,
    route_code VARCHAR(50) UNIQUE NOT NULL,
    route_name VARCHAR(200) NOT NULL,
    start_location VARCHAR(200) NOT NULL,
    end_location VARCHAR(200) NOT NULL,
    waypoints JSON,  -- 途经点
    estimated_distance_km DECIMAL(8,2),
    estimated_duration_hours DECIMAL(5,2),
    fuel_consumption_est DECIMAL(8,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 配送任务表
CREATE TABLE delivery_tasks (
    task_id INT PRIMARY KEY AUTO_INCREMENT,
    task_number VARCHAR(50) UNIQUE NOT NULL,
    route_id INT,
    vehicle_id INT,
    driver_name VARCHAR(100),
    driver_phone VARCHAR(20),
    transport_ids JSON,  -- 包含的运输订单ID列表
    departure_time DATETIME,
    estimated_return_time DATETIME,
    actual_return_time DATETIME,
    task_status ENUM('ASSIGNED', 'DEPARTED', 'DELIVERING', 'COMPLETED', 'DELAYED') DEFAULT 'ASSIGNED',
    mileage_recorded DECIMAL(8,2),
    fuel_used DECIMAL(8,2),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (route_id) REFERENCES delivery_routes(route_id),
    FOREIGN KEY (vehicle_id) REFERENCES fleet_vehicles(vehicle_id)
);


-- 插入供应商数据
INSERT INTO suppliers (supplier_code, supplier_name, supplier_type, contact_person, contact_phone, email, address, payment_terms, credit_rating) VALUES
('SUP001', '苹果中国有限公司', 'MANUFACTURER', '王建国', '13912345678', 'wang@apple.com.cn', '上海市浦东新区', '月结30天', 'A'),
('SUP002', '三星电子中国', 'MANUFACTURER', '李成俊', '13912345679', 'li@samsung.com', '北京市朝阳区', '预付50%', 'B'),
('SUP003', '联想集团', 'MANUFACTURER', '张伟', '13912345680', 'zhang@lenovo.com', '北京市海淀区', '月结15天', 'A'),
('SUP004', '耐克体育用品', 'MANUFACTURER', '陈娜', '13912345681', 'chen@nike.com', '上海市静安区', '月结30天', 'A'),
('SUP005', '京东物流供应链', 'DISTRIBUTOR', '刘强', '13912345682', 'liu@jd.com', '北京市大兴区', '周结', 'A');

-- 为电商系统商品创建采购订单
-- 商品ID 1 (iPhone 13) 向苹果采购
INSERT INTO purchase_orders (purchase_number, supplier_id, order_date, expected_delivery_date, total_amount, final_amount, status) VALUES
('PO202310001', 1, '2023-10-01 09:00:00', '2023-10-15', 500000.00, 500000.00, 'RECEIVED'),
('PO202310002', 2, '2023-10-02 10:30:00', '2023-10-20', 250000.00, 247500.00, 'SHIPPED'),
('PO202310003', 3, '2023-10-03 14:15:00', '2023-10-25', 240000.00, 240000.00, 'CONFIRMED'),
('PO202310004', 4, '2023-10-04 11:00:00', '2023-10-18', 60000.00, 58800.00, 'RECEIVED'),
('PO202310005', 1, '2023-10-05 16:20:00', '2023-10-30', 300000.00, 300000.00, 'SUBMITTED');

-- 采购明细（对应电商系统的商品）
INSERT INTO purchase_items (purchase_id, product_id, sku, product_name, unit_price, quantity, received_quantity, subtotal) VALUES
(1, 1, 'IPHONE13-128', 'iPhone 13 128GB', 5000.00, 100, 100, 500000.00),
(2, 3, 'SAMSUNG-S22', 'Samsung Galaxy S22', 4000.00, 50, 30, 200000.00),
(2, 2, 'MACBOOK-AIR', 'MacBook Air M2', 7500.00, 6, 6, 45000.00),
(3, 4, 'LENOVO-LEGION', 'Lenovo Legion 5 Pro', 7000.00, 30, 0, 210000.00),
(4, 5, 'NIKE-TSHIRT', 'Nike男士运动T恤', 250.00, 200, 200, 50000.00),
(4, 5, 'NIKE-TSHIRT', 'Nike男士运动T恤', 250.00, 40, 40, 10000.00),  -- 追加采购
(5, 1, 'IPHONE13-128', 'iPhone 13 128GB', 4950.00, 60, 0, 297000.00);

-- 质检记录
INSERT INTO quality_inspections (
    purchase_id, 
    purchase_item_id, 
    inspection_date, 
    inspector, 
    sample_size, 
    qualified_quantity, 
    defective_quantity, 
    inspection_result,
    remarks
) VALUES 
(1, 1, '2023-10-16 10:00:00', '质检员赵刚', 20, 20, 0, 'PASS', 'iPhone 13 批量质检全部合格'),

(2, 2, '2023-10-12 14:30:00', '质检员李敏', 10, 9, 1, 'PARTIAL', 'Samsung S22 发现1台屏幕有亮点'),

(4, 5, '2023-10-19 09:15:00', '质检员王芳', 30, 28, 2, 'PARTIAL', 'Nike T恤 2件有污渍');


-- 插入承运商
INSERT INTO carriers (carrier_code, carrier_name, carrier_type, contact_person, contact_phone, service_areas, cooperation_level) VALUES
('SF001', '顺丰速运', 'EXPRESS', '张经理', '4008111111', '全国', 'STRATEGIC'),
('JD002', '京东物流', 'EXPRESS', '李经理', '4006566000', '全国', 'STRATEGIC'),
('YT003', '圆通速递', 'EXPRESS', '王经理', '9555400', '全国', 'PREFERRED'),
('ZT004', '中通快递', 'EXPRESS', '陈经理', '95311', '全国', 'GENERAL'),
('HY005', '海运国际物流', 'INTERNATIONAL', '赵经理', '4008855888', '沿海港口', 'GENERAL');

-- 为电商订单创建运输订单（与订单管理系统的订单对应）
-- 订单1 ORD20231001001 -> 用户1 John Doe
INSERT INTO transport_orders (transport_number, source_type, source_id, carrier_id, sender_name, sender_phone, sender_address, receiver_name, receiver_phone, receiver_address, tracking_number, shipping_date, estimated_delivery, transport_status) VALUES
('T202310001', 'SALE_ORDER', 'ORD20231001001', 1, '华东仓', '021-67890123', '上海市青浦区物流园区15号', 'John Doe', '13800138001', '北京市朝阳区建国门外大街1号国贸大厦A座', 'SF1234567890', '2023-10-01 15:30:00', '2023-10-03', 'DELIVERED'),

('T202310002', 'SALE_ORDER', 'ORD20231001002', 3, '华北仓', '010-67890123', '北京市大兴区物流园8号', 'Jane Smith', '13800138002', '浙江省杭州市西湖区文三路478号华星时代广场', 'YT9876543210', '2023-10-02 14:20:00', '2023-10-05', 'DELIVERED'),

('T202310003', 'SALE_ORDER', 'ORD20231001003', 2, '华东仓', '021-67890123', '上海市青浦区物流园区15号', 'Alice Wang', '13800138003', '广东省深圳市南山区科技园科技南路1号', 'JD5678901234', '2023-10-02 09:10:00', '2023-10-04', 'IN_TRANSIT'),

('T202310004', 'SALE_ORDER', 'ORD20231001004', 1, '华东仓', '021-67890123', '上海市青浦区物流园区15号', 'John Doe', '13800138001', '上海市浦东新区陆家嘴环路100号', 'SF2345678901', '2023-10-03 11:45:00', '2023-10-06', 'IN_TRANSIT'),

-- 采购订单的运输
('T202310005', 'PURCHASE_ORDER', 'PO202310002', 5, '三星电子', '0755-12345678', '深圳市南山区科技园', '华东仓', '021-67890123', '上海市青浦区物流园区15号', 'HY202310001', '2023-10-05 08:00:00', '2023-10-18', 'IN_TRANSIT');

-- 物流轨迹
INSERT INTO transport_tracking (transport_id, tracking_number, status_code, status_description, location, operation_time) VALUES
(1, 'SF1234567890', 'SIGNED', '已签收', '北京市朝阳区', '2023-10-03 14:25:00'),
(2, 'YT9876543210', 'IN_TRANSIT', '运输中', '南京市中转站', '2023-10-04 09:30:00'),
(3, 'JD5678901234', 'ARRIVED', '已到达', '广州中转场', '2023-10-03 22:15:00'),
(4, 'SF2345678901', 'PICKED_UP', '已揽收', '上海青浦', '2023-10-03 13:20:00'),
(5, 'HY202310001', 'DEPARTED', '已离港', '上海港', '2023-10-06 18:00:00');

-- 车辆管理
INSERT INTO fleet_vehicles (plate_number, vehicle_type, brand, model, capacity_kg, capacity_m3, driver_name, driver_phone, status) VALUES
('沪A12345', 'VAN', '福特', '全顺', 1.5, 8, '张师傅', '13812340001', 'AVAILABLE'),
('京B67890', 'TRUCK', '解放', 'J6', 10.0, 40, '李师傅', '13812340002', 'IN_USE'),
('粤C11223', 'REFRIGERATED', '依维柯', 'Daily', 3.0, 15, '王师傅', '13812340003', 'AVAILABLE'),
('浙D33445', 'VAN', '江淮', '星锐', 1.8, 10, '赵师傅', '13812340004', 'MAINTENANCE');

-- 配送路线
INSERT INTO delivery_routes (route_code, route_name, start_location, end_location, waypoints, estimated_distance_km, estimated_duration_hours) VALUES
('R001', '上海-北京线', '上海青浦仓', '北京大兴仓', '["苏州", "无锡", "济南"]', 1200, 18),
('R002', '上海-深圳线', '上海青浦仓', '深圳宝安仓', '["杭州", "福州", "汕头"]', 1500, 24),
('R003', '北京-杭州线', '北京大兴仓', '杭州萧山仓', '["天津", "济南", "南京"]', 1300, 20),
('R004', '市内配送线', '上海青浦仓', '上海市区', '["徐汇", "静安", "浦东"]', 80, 4);


