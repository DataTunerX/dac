use test1;

CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '用户唯一标识ID，主键，自增长',
    username VARCHAR(50) UNIQUE NOT NULL COMMENT '用户名，唯一且不能为空，用于登录',
    email VARCHAR(100) UNIQUE NOT NULL COMMENT '邮箱地址，唯一且不能为空，用于登录和通知',
    password VARCHAR(255) NOT NULL COMMENT '加密后的密码，使用哈希算法存储',
    full_name VARCHAR(100) COMMENT '用户全名，可选填',
    phone VARCHAR(20) COMMENT '手机号码，可选填',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间，默认为当前时间戳',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录最后更新时间，默认为当前时间戳并在更新时自动更新'
) COMMENT = '用户信息表，存储系统所有注册用户的基本信息';

INSERT INTO users (username, email, password, full_name, phone) VALUES
('zhangsan', 'zhangsan@email.com', 'hashed_password_1', '张三', '13800138001'),
('lisi', 'lisi@email.com', 'hashed_password_2', '李四', '13800138002'),
('wangwu', 'wangwu@email.com', 'hashed_password_3', '王五', '13800138003'),
('zhaoliu', 'zhaoliu@email.com', 'hashed_password_4', '赵六', '13800138004'),
('liuxia', 'liuxia@email.com', 'hashed_password_5', '刘霞', '13800138005'),
('chenming', 'chenming@email.com', 'hashed_password_6', '陈明', '13800138006'),
('yanglan', 'yanglan@email.com', 'hashed_password_7', '杨岚', '13800138007'),
('zhouhong', 'zhouhong@email.com', 'hashed_password_8', '周红', '13800138008'),
('wufeng', 'wufeng@email.com', 'hashed_password_9', '吴峰', '13800138009'),
('zhengtao', 'zhengtao@email.com', 'hashed_password_10', '郑涛', '13800138010'),
('sunli', 'sunli@email.com', 'hashed_password_11', '孙丽', '13800138011'),
('qianjun', 'qianjun@email.com', 'hashed_password_12', '钱军', '13800138012'),
('fengyan', 'fengyan@email.com', 'hashed_password_13', '冯艳', '13800138013'),
('chenwei', 'chenwei@email.com', 'hashed_password_14', '陈伟', '13800138014'),
('huyan', 'huyan@email.com', 'hashed_password_15', '胡燕', '13800138015'),
('linhui', 'linhui@email.com', 'hashed_password_16', '林慧', '13800138016'),
('guobin', 'guobin@email.com', 'hashed_password_17', '郭斌', '13800138017'),
('mawei', 'mawei@email.com', 'hashed_password_18', '马威', '13800138018'),
('lucywang', 'lucywang@email.com', 'hashed_password_19', '王露西', '13800138019'),
('davidli', 'davidli@email.com', 'hashed_password_20', '李大卫', '13800138020');

CREATE TABLE categories (
    category_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '分类唯一标识ID，主键，自增长',
    category_name VARCHAR(100) NOT NULL COMMENT '分类名称，不能为空',
    parent_id INT NULL COMMENT '父分类ID，指向当前表的category_id，用于构建多级分类结构。NULL表示一级分类',
    description TEXT COMMENT '分类详细描述，可选填',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '分类创建时间，默认为当前时间戳',
    FOREIGN KEY (parent_id) REFERENCES categories(category_id) ON DELETE SET NULL
) COMMENT = '商品分类表，支持无限级分类结构，用于组织和管理商品分类体系';

INSERT INTO categories (category_name, parent_id, description) VALUES
-- 一级分类
('电子产品', NULL, '各类电子设备和配件'),
('服装鞋帽', NULL, '服装、鞋类和配饰'),
('家居用品', NULL, '家庭生活用品'),
('图书文具', NULL, '图书和文具用品'),
-- 电子产品的子分类
('手机', 1, '智能手机和功能手机'),
('笔记本电脑', 1, '各类笔记本电脑'),
('平板电脑', 1, '平板电脑和设备'),
('智能手表', 1, '智能手表和手环'),
('耳机', 1, '各类耳机产品'),
-- 服装鞋帽的子分类
('男装', 2, '男士服装'),
('女装', 2, '女士服装'),
('童装', 2, '儿童服装'),
('运动鞋', 2, '运动鞋类'),
('休闲鞋', 2, '休闲鞋类'),
-- 家居用品的子分类
('厨房用品', 3, '厨房用具和电器'),
('卧室用品', 3, '卧室家具和用品'),
('客厅用品', 3, '客厅家具和装饰'),
('卫浴用品', 3, '卫生间用品'),
-- 图书文具的子分类
('文学小说', 4, '文学和小说类图书'),
('科技图书', 4, '科学技术类图书'),
('文具用品', 4, '文具和办公用品');


CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '商品唯一标识ID，主键，自增长',
    product_name VARCHAR(200) NOT NULL COMMENT '商品名称，不能为空',
    description TEXT COMMENT '商品详细描述，支持长文本，可选填',
    price DECIMAL(10,2) NOT NULL COMMENT '商品价格，十进制数，整数位8位小数位2位，不能为空',
    stock_quantity INT DEFAULT 0 COMMENT '库存数量，默认为0',
    category_id INT NOT NULL COMMENT '所属分类ID，外键关联categories表，不能为空',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '商品创建时间，默认为当前时间戳',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '商品最后更新时间，默认为当前时间戳并在更新时自动更新',
    FOREIGN KEY (category_id) REFERENCES categories(category_id) ON DELETE RESTRICT
) COMMENT = '商品信息表，存储所有商品的基本信息、价格和库存数据';

INSERT INTO products (product_name, description, price, stock_quantity, category_id) VALUES
('iPhone 16 Pro', '苹果最新A18芯片，钛金属机身', 9999.00, 45, 5),
('三星Galaxy Z Flip6', '折叠屏智能手机', 8999.00, 25, 5),
('OPPO Find X8', '超光影影像系统', 5499.00, 65, 5),
('vivo X100 Pro', '蔡司全焦段影像', 5999.00, 55, 5),

('联想拯救者Y9000P', '游戏笔记本电脑', 12999.00, 20, 6),
('华硕ROG枪神7', '电竞游戏本', 14999.00, 15, 6),
('惠普暗影精灵10', '高性能游戏本', 10999.00, 25, 6),

('iPad Pro 13寸', 'M3芯片，超视网膜XDR显示屏', 9299.00, 30, 7),
('三星Tab S9 Ultra', '14.6英寸大屏平板', 7999.00, 35, 7),
('小米平板6 Pro', '2.8K超清屏', 3299.00, 60, 7),

('华为Watch GT4', '运动健康智能手表', 1488.00, 80, 8),
('佳明Forerunner265', '专业运动手表', 3280.00, 40, 8),

('Bose QuietComfort消噪耳机', '顶级降噪头戴耳机', 2299.00, 50, 9),
('森海塞尔MOMENTUM真无线', '高保真音质', 1799.00, 70, 9),

('男士冬季羽绒服', '90%白鸭绒保暖', 899.00, 85, 10),
('女士羊毛大衣', '100%羊毛材质', 1299.00, 60, 11),
('儿童冬季外套', '防风保暖童装', 299.00, 120, 12),

('阿迪达斯Ultraboost', 'boost缓震跑鞋', 1299.00, 75, 13),
('匡威经典帆布鞋', '复古休闲鞋', 439.00, 150, 14),

('电饭煲智能款', '4L容量IH加热', 599.00, 90, 15),
('记忆棉床垫', '护脊弹簧床垫', 2599.00, 25, 16);



CREATE TABLE orders (
    order_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '订单唯一标识ID，主键，自增长',
    user_id INT NOT NULL COMMENT '用户ID，外键关联users表，标识订单所属用户',
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '订单日期，默认为当前时间戳，表示下单时间',
    total_amount DECIMAL(10,2) NOT NULL COMMENT '订单总金额，十进制数，整数位8位小数位2位，不能为空',
    status ENUM('pending', 'confirmed', 'shipped', 'delivered', 'cancelled') DEFAULT 'pending' COMMENT '订单状态：pending-待处理, confirmed-已确认, shipped-已发货, delivered-已送达, cancelled-已取消',
    shipping_address TEXT NOT NULL COMMENT '收货地址，详细配送信息，不能为空',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '订单记录创建时间，默认为当前时间戳',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) COMMENT = '订单主表，存储订单的基本信息、状态和配送地址';

INSERT INTO orders (user_id, total_amount, status, shipping_address) VALUES
(1, 8999.00, 'delivered', '北京市朝阳区建国路100号'),
(2, 5999.00, 'shipped', '上海市浦东新区陆家嘴金融中心'),
(3, 4399.00, 'confirmed', '广州市天河区体育西路'),
(1, 2999.00, 'pending', '北京市朝阳区建国路100号'),
(4, 1899.00, 'delivered', '深圳市南山区科技园'),
(5, 7999.00, 'shipped', '杭州市西湖区文三路'),
(6, 199.00, 'delivered', '南京市鼓楼区中山路'),
(7, 599.00, 'confirmed', '成都市锦江区春熙路'),
(8, 299.00, 'pending', '武汉市江汉区解放大道'),
(9, 399.00, 'delivered', '西安市雁塔区科技路'),
(10, 699.00, 'shipped', '重庆市渝中区解放碑'),
(2, 249.00, 'delivered', '上海市浦东新区陆家嘴金融中心'),
(3, 2299.00, 'confirmed', '广州市天河区体育西路'),
(11, 9999.00, 'pending', '长沙市芙蓉区五一大道'),
(12, 18999.00, 'shipped', '郑州市金水区花园路'),
(13, 3999.00, 'delivered', '天津市和平区南京路'),
(14, 2999.00, 'confirmed', '苏州市工业园区星湖街'),
(15, 89.00, 'delivered', '宁波市海曙区中山西路'),
(16, 199.00, 'pending', '无锡市梁溪区中山路'),
(17, 599.00, 'shipped', '佛山市南海区桂城');

CREATE TABLE order_items (
    order_item_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '订单项唯一标识ID，主键，自增长',
    order_id INT NOT NULL COMMENT '订单ID，外键关联orders表，标识所属订单',
    product_id INT NOT NULL COMMENT '商品ID，外键关联products表，标识购买的商品',
    quantity INT NOT NULL COMMENT '购买数量，不能为空',
    unit_price DECIMAL(10,2) NOT NULL COMMENT '下单时的商品单价，十进制数，整数位8位小数位2位，不能为空',
    subtotal DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED COMMENT '小计金额，计算字段，自动生成（数量 × 单价），存储类型',
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT
) COMMENT = '订单详情表，存储订单中每个商品的具体信息，支持一个订单包含多个商品';

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
-- 订单1的商品
(1, 1, 1, 8999.00),
-- 订单2的商品
(2, 3, 1, 5999.00),
-- 订单3的商品
(3, 8, 1, 4399.00),
-- 订单4的商品
(4, 9, 1, 2999.00),
-- 订单5的商品
(5, 12, 1, 1899.00),
-- 订单6的商品
(6, 7, 1, 7999.00),
-- 订单7的商品
(7, 14, 1, 199.00),
-- 订单8的商品
(8, 17, 1, 599.00),
-- 订单9的商品
(9, 15, 1, 299.00),
-- 订单10的商品
(10, 19, 1, 399.00),
-- 订单11的商品
(11, 20, 1, 699.00),
-- 订单12的商品
(12, 11, 1, 249.00),
-- 订单13的商品
(13, 13, 1, 2299.00),
-- 订单14的商品
(14, 6, 1, 9999.00),
-- 订单15的商品
(15, 5, 1, 18999.00),
-- 订单16的商品
(16, 2, 1, 3999.00),
-- 订单17的商品
(17, 10, 1, 2999.00),
-- 订单18的商品
(18, 16, 1, 89.00),
-- 订单19的商品
(19, 14, 1, 199.00),
-- 订单20的商品
(20, 17, 1, 599.00),
-- 一些订单有多个商品
(1, 12, 1, 1899.00),  -- 订单1还买了耳机
(2, 11, 1, 249.00),   -- 订单2还买了手环
(5, 14, 2, 199.00);   -- 订单5还买了2件衬衫
