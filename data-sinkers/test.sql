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

-- 插入测试数据（用户表: 25条）
INSERT INTO users (username, email, password_hash, full_name, phone_number, registration_date, last_login, is_active) VALUES
('zhangsan',   'zhangsan@example.com',   'hash_abc001', '张三',   '13800001001', '2025-01-15 09:30:00', '2026-05-08 10:15:00', TRUE),
('lisi',       'lisi@example.com',       'hash_abc002', '李四',   '13800001002', '2025-02-20 14:20:00', '2026-05-09 08:30:00', TRUE),
('wangwu',     'wangwu@example.com',     'hash_abc003', '王五',   '13800001003', '2025-03-10 11:00:00', '2026-05-07 16:45:00', TRUE),
('zhaoliu',    'zhaoliu@example.com',    'hash_abc004', '赵六',   '13800001004', '2025-04-05 07:45:00', '2026-05-09 12:00:00', TRUE),
('sunqi',      'sunqi@example.com',      'hash_abc005', '孙七',   '13800001005', '2025-05-12 18:30:00', '2026-05-08 09:20:00', TRUE),
('zhouba',     'zhouba@example.com',     'hash_abc006', '周八',   '13800001006', '2025-06-01 10:10:00', '2026-05-06 14:00:00', TRUE),
('wujiu',      'wujiu@example.com',      'hash_abc007', '吴九',   '13800001007', '2025-07-15 08:00:00', '2026-04-28 11:30:00', TRUE),
('zhengshi',   'zhengshi@example.com',   'hash_abc008', '郑十',   '13800001008', '2025-08-20 13:15:00', '2026-05-05 10:00:00', TRUE),
('liuyi',      'liuyi@example.com',      'hash_abc009', '刘一',   '13800001009', '2025-09-10 16:20:00', '2026-05-03 15:40:00', TRUE),
('chener',     'chener@example.com',     'hash_abc010', '陈二',   '13800001010', '2025-10-05 09:50:00', '2026-05-01 17:00:00', TRUE),
('yangsan',    'yangsan@example.com',    'hash_abc011', '杨三',   '13800001011', '2025-11-12 11:10:00', '2026-04-20 08:55:00', TRUE),
('huangsi',    'huangsi@example.com',    'hash_abc012', '黄四',   '13800001012', '2025-12-01 14:40:00', '2026-05-10 07:30:00', TRUE),
('xuwu',       'xuwu@example.com',       'hash_abc013', '许五',   '13800001013', '2026-01-08 10:05:00', '2026-05-09 19:10:00', TRUE),
('heliu',      'heliu@example.com',      'hash_abc014', '何六',   '13800001014', '2026-02-14 15:30:00', '2026-05-07 12:55:00', TRUE),
('lvqi',       'lvqi@example.com',       'hash_abc015', '吕七',   '13800001015', '2026-03-01 08:15:00', '2026-05-06 09:45:00', TRUE),
('shiba',      'shiba@example.com',      'hash_abc016', '施八',   '13800001016', '2025-06-20 12:30:00', '2026-05-05 14:20:00', TRUE),
('zhangjiu',   'zhangjiu@example.com',   'hash_abc017', '张九',   '13800001017', '2025-08-15 17:00:00', '2026-05-04 11:10:00', TRUE),
('kongshi',    'kongshi@example.com',    'hash_abc018', '孔十',   '13800001018', '2025-10-22 09:20:00', '2026-05-03 16:35:00', TRUE),
('caoyi',      'caoyi@example.com',      'hash_abc019', '曹一',   '13800001019', '2025-12-15 13:45:00', '2026-05-02 08:50:00', TRUE),
('yaner',      'yaner@example.com',      'hash_abc020', '严二',   '13800001020', '2026-01-20 10:30:00', '2026-04-30 15:15:00', TRUE),
('huasan',     'huasan@example.com',     'hash_abc021', '花三',   '13800001021', '2026-02-25 08:50:00', '2026-04-25 12:00:00', TRUE),
('jinsi',      'jinsi@example.com',      'hash_abc022', '金四',   '13800001022', '2026-03-10 16:10:00', '2026-05-08 18:20:00', TRUE),
('weiwu',      'weiwu@example.com',      'hash_abc023', '魏五',   '13800001023', '2026-04-05 11:40:00', '2026-05-10 10:05:00', TRUE),
('taoliu',     'taoliu@example.com',     'hash_abc024', '陶六',   '13800001024', '2025-05-18 14:55:00', '2026-03-15 09:30:00', FALSE),  -- 已停用
('jiangqi',    'jiangqi@example.com',    'hash_abc025', '姜七',   '13800001025', '2026-05-01 07:00:00', '2026-05-10 08:00:00', TRUE);

-- 插入测试数据（用户地址表: 30条, 每用户1-3个地址）
INSERT INTO user_addresses (user_id, address_type, recipient_name, phone, province, city, district, detail_address, is_default) VALUES
(1,  'HOME',  '张三',   '13800001001', '北京市', '北京市', '朝阳区', '建国路88号院1号楼1201', TRUE),
(1,  'WORK',  '张三',   '13800001001', '北京市', '北京市', '海淀区', '中关村大街1号理想国际大厦15层', FALSE),
(2,  'HOME',  '李四',   '13800001002', '上海市', '上海市', '浦东新区', '陆家嘴环路1000号恒生银行大厦22层', TRUE),
(2,  'WORK',  '李四',   '13800001002', '上海市', '上海市', '徐汇区', '漕溪北路396号汇智大厦8层', FALSE),
(3,  'HOME',  '王五',   '13800001003', '广东省', '广州市', '天河区', '天河路385号太古汇1座18楼', TRUE),
(3,  'OTHER', '王五',   '13800001003', '广东省', '深圳市', '南山区', '科技园南路588号讯美科技广场3栋', FALSE),
(4,  'HOME',  '赵六',   '13800001004', '浙江省', '杭州市', '西湖区', '文三路478号华星时代广场A座12楼', TRUE),
(5,  'HOME',  '孙七',   '13800001005', '四川省', '成都市', '武侯区', '天府大道北段1199号银泰中心2栋2501', TRUE),
(5,  'WORK',  '孙七',   '13800001005', '四川省', '成都市', '锦江区', '东大街99号平安金融中心5层', FALSE),
(6,  'HOME',  '周八',   '13800001006', '湖北省', '武汉市', '洪山区', '珞瑜路1037号华中科技大学科技园', TRUE),
(7,  'HOME',  '吴九',   '13800001007', '江苏省', '南京市', '鼓楼区', '汉中路1号南京国际金融中心40层', TRUE),
(8,  'HOME',  '郑十',   '13800001008', '重庆市', '重庆市', '渝中区', '解放碑步行街民权路28号英利国际', TRUE),
(9,  'HOME',  '刘一',   '13800001009', '天津市', '天津市', '和平区', '南京路189号津汇广场2座19层', TRUE),
(10, 'HOME',  '陈二',   '13800001010', '山东省', '济南市', '历下区', '泉城路180号齐鲁国际大厦C座10层', TRUE),
(11, 'HOME',  '杨三',   '13800001011', '福建省', '厦门市', '思明区', '鹭江道100号财富中心25层', TRUE),
(12, 'HOME',  '黄四',   '13800001012', '湖南省', '长沙市', '岳麓区', '麓谷大道658号麓谷信息港A栋', TRUE),
(13, 'HOME',  '许五',   '13800001013', '陕西省', '西安市', '雁塔区', '高新四路17号志诚丽柏酒店15层', TRUE),
(14, 'HOME',  '何六',   '13800001014', '安徽省', '合肥市', '蜀山区', '长江西路88号环球金融广场B座', TRUE),
(15, 'HOME',  '吕七',   '13800001015', '辽宁省', '沈阳市', '和平区', '青年大街286号华润大厦9层', TRUE),
(16, 'HOME',  '施八',   '13800001016', '河南省', '郑州市', '金水区', '花园路39号国贸中心A座22层', TRUE),
(17, 'HOME',  '张九',   '13800001017', '河北省', '石家庄市', '长安区', '中山东路188号北国商城', TRUE),
(18, 'HOME',  '孔十',   '13800001018', '云南省', '昆明市', '五华区', '东风西路129号顺城购物中心', TRUE),
(19, 'HOME',  '曹一',   '13800001019', '贵州省', '贵阳市', '南明区', '中华南路78号贵阳壹号25楼', TRUE),
(20, 'HOME',  '严二',   '13800001020', '山西省', '太原市', '小店区', '长风街116号北美新天地', TRUE),
(21, 'HOME',  '花三',   '13800001021', '江西省', '南昌市', '红谷滩区', '红谷中大道998号绿地中央广场', TRUE),
(21, 'WORK',  '花三',   '13800001021', '江西省', '南昌市', '青山湖区', '北京东路398号恒茂梦时代广场', FALSE),
(22, 'HOME',  '金四',   '13800001022', '吉林省', '长春市', '朝阳区', '红旗街959号万达广场', TRUE),
(23, 'HOME',  '魏五',   '13800001023', '黑龙江省', '哈尔滨市', '道里区', '中央大街88号金安国际', TRUE),
(24, 'HOME',  '陶六',   '13800001024', '甘肃省', '兰州市', '城关区', '庆阳路42号万盛商务大厦', TRUE),
(25, 'HOME',  '姜七',   '13800001025', '广西',     '南宁市', '青秀区', '民族大道136号万象城3座', TRUE);

-- 插入测试数据（用户支付方式表: 25条, 每用户至少1个支付方式）
INSERT INTO user_payment_methods (user_id, payment_type, card_last_four, card_brand, is_default, expiry_date) VALUES
(1,  'CREDIT_CARD', '3891', 'Visa',       TRUE,  '2027-06-30'),
(1,  'ALIPAY',      NULL,   NULL,         FALSE, NULL),
(2,  'DEBIT_CARD',  '5210', 'MasterCard', TRUE,  '2028-03-31'),
(3,  'CREDIT_CARD', '6742', 'Visa',       TRUE,  '2027-12-31'),
(3,  'WECHAT',      NULL,   NULL,         FALSE, NULL),
(4,  'CREDIT_CARD', '9801', 'MasterCard', TRUE,  '2029-01-31'),
(5,  'PAYPAL',      NULL,   NULL,         TRUE,  NULL),
(6,  'ALIPAY',      NULL,   NULL,         TRUE,  NULL),
(7,  'DEBIT_CARD',  '1104', 'UnionPay',   TRUE,  '2026-09-30'),
(8,  'CREDIT_CARD', '4543', 'Visa',       TRUE,  '2028-08-31'),
(8,  'WECHAT',      NULL,   NULL,         FALSE, NULL),
(9,  'WECHAT',      NULL,   NULL,         TRUE,  NULL),
(10, 'CREDIT_CARD', '3328', 'AmericanExpress', TRUE, '2027-11-30'),
(11, 'ALIPAY',      NULL,   NULL,         TRUE,  NULL),
(12, 'DEBIT_CARD',  '7456', 'UnionPay',   TRUE,  '2027-05-31'),
(13, 'CREDIT_CARD', '8912', 'Visa',       TRUE,  '2029-04-30'),
(14, 'PAYPAL',      NULL,   NULL,         TRUE,  NULL),
(15, 'WECHAT',      NULL,   NULL,         TRUE,  NULL),
(16, 'CREDIT_CARD', '2378', 'MasterCard', TRUE,  '2027-02-28'),
(17, 'ALIPAY',      NULL,   NULL,         TRUE,  NULL),
(18, 'DEBIT_CARD',  '9634', 'Visa',       TRUE,  '2028-07-31'),
(19, 'CREDIT_CARD', '5087', 'AmericanExpress', TRUE, '2026-10-31'),
(20, 'WECHAT',      NULL,   NULL,         TRUE,  NULL),
(21, 'ALIPAY',      NULL,   NULL,         TRUE,  NULL),
(22, 'CREDIT_CARD', '6501', 'MasterCard', TRUE,  '2029-03-31'),
(23, 'DEBIT_CARD',  '1823', 'UnionPay',   TRUE,  '2027-08-31'),
(24, 'ALIPAY',      NULL,   NULL,         TRUE,  NULL),
(25, 'WECHAT',      NULL,   NULL,         TRUE,  NULL);


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

-- 插入测试数据（商品分类表: 20条, 树形结构, 最多3层）
INSERT INTO categories (category_name, parent_category_id, description, display_order, is_active) VALUES
('电子产品',      NULL, '手机、电脑、平板等数码产品',              1, TRUE),
('服装鞋帽',      NULL, '男装、女装、童装及鞋帽配饰',              2, TRUE),
('家居生活',      NULL, '家具、家纺、厨具、收纳等家居用品',        3, TRUE),
('食品饮料',      NULL, '零食、饮料、生鲜、粮油等食品',            4, TRUE),
('运动户外',      NULL, '运动装备、健身器材、户外用品',            5, TRUE),
('图书音像',      NULL, '图书、电子书、音乐、影视',                6, TRUE),
('美妆个护',      NULL, '护肤、彩妆、香水、个人护理',              7, TRUE),
('母婴用品',      NULL, '婴幼儿奶粉、尿裤、玩具、孕产用品',        8, TRUE),
('汽车用品',      NULL, '汽车装饰、维修保养、车载电器',            9, TRUE),
('珠宝配饰',      NULL, '珠宝首饰、手表、眼镜、箱包',             10, TRUE),
-- 二级分类 (parent=1 电子产品)
('智能手机',      1,    '各品牌安卓及iOS智能手机',                 1, TRUE),
('笔记本电脑',    1,    '轻薄本、游戏本、商务本',                  2, TRUE),
('平板电脑',      1,    'iPad及安卓平板',                          3, TRUE),
('智能穿戴',      1,    '智能手表、手环、TWS耳机',                 4, TRUE),
-- 三级分类 (parent=11 智能手机)
('手机配件',      11,   '手机壳、贴膜、充电器、数据线',            1, TRUE),
-- 二级分类 (parent=2 服装鞋帽)
('男装',          2,    '男士T恤、衬衫、外套、裤装',               1, TRUE),
('女装',          2,    '女士连衣裙、上衣、裤装、套装',            2, TRUE),
('运动鞋',        2,    '跑步鞋、篮球鞋、休闲运动鞋',              3, TRUE),
-- 二级分类 (其他)
('休闲零食',      4,    '薯片、坚果、糖果、膨化食品',              1, TRUE),
('健身器材',      5,    '瑜伽垫、哑铃、跑步机、弹力带',            1, TRUE);

-- 插入测试数据（商品表: 25条, 关联到categories, 用category_id 1-20）
INSERT INTO products (sku, product_name, description, category_id, brand, unit_price, cost_price, stock_quantity, reserved_quantity, weight_kg, is_listed) VALUES
-- 智能手机 (cat=11)
('SKU-PHONE-001', 'iPhone 16 Pro Max 256GB',   'A18 Pro芯片, 256GB存储, 钛金属边框',    11, 'Apple',   9999.00, 7200.00,  120, 8,  0.221, TRUE),
('SKU-PHONE-002', 'Samsung Galaxy S25 Ultra',   '骁龙8 Gen4, 12+512GB, 2亿像素',         11, 'Samsung', 8999.00, 6500.00,   85, 5,  0.232, TRUE),
('SKU-PHONE-003', 'Xiaomi 16 Pro',              '徕卡光学镜头, 骁龙8 Gen4, 16+512GB',    11, 'Xiaomi',  4999.00, 3500.00,  200, 12, 0.205, TRUE),
('SKU-PHONE-004', 'Huawei Mate 70 Pro',         '麒麟9100, 卫星通信, 16+512GB',          11, 'Huawei',  6999.00, 5000.00,   60, 3,  0.225, TRUE),
-- 笔记本电脑 (cat=12)
('SKU-LAPTOP-001', 'MacBook Pro 14" M4 Pro',    'M4 Pro芯片, 18GB RAM, 512GB SSD',       12, 'Apple',   14999.00, 11000.00, 45, 2,  1.600, TRUE),
('SKU-LAPTOP-002', 'ThinkPad X1 Carbon Gen12',  'Ultra 9 285H, 32GB, 1TB, 14" 2.8K',    12, 'Lenovo',  12999.00, 9500.00,  30, 0,  1.090, TRUE),
('SKU-LAPTOP-003', 'Dell XPS 16',               'Core Ultra 9, 32GB, RTX 4070, 16"',    12, 'Dell',    13999.00, 10000.00, 25, 1,  2.100, TRUE),
-- 手机配件 (cat=15)
('SKU-ACC-001',    'Apple 20W USB-C充电器',      '原装快充, Type-C接口',                  15, 'Apple',    149.00,   80.00,  500, 0,  0.085, TRUE),
('SKU-ACC-002',    '倍思30W氮化镓充电器',         'GaN技术, 支持PD3.0, 30W快充',          15, 'Baseus',   79.00,   35.00,  800, 0,  0.060, TRUE),
-- 男装 (cat=16)
('SKU-MEN-001',   '海澜之家商务衬衫',            '免烫纯棉, 修身版, 多色可选',            16, '海澜之家', 299.00,  150.00,  300, 0,  0.350, TRUE),
('SKU-MEN-002',   '优衣库纯棉T恤',               '纯棉圆领, 基础款, 多色可选',            16, 'UNIQLO',   79.00,   35.00, 1000, 0,  0.200, TRUE),
-- 女装 (cat=17)
('SKU-WOM-001',   'ZARA碎花连衣裙',              '2026春夏新款, V领收腰',                 17, 'ZARA',    459.00,  220.00,  150, 0,  0.400, TRUE),
('SKU-WOM-002',   '太平鸟宽松针织衫',            '羊毛混纺, 圆领落肩, 5色可选',           17, '太平鸟',  399.00,  180.00,  200, 0,  0.500, TRUE),
-- 运动鞋 (cat=18)
('SKU-SHOE-001',  'Nike Air Zoom Pegasus 42',   'ReactX泡棉, Flyknit鞋面, 公路跑鞋',     18, 'Nike',    1099.00, 650.00,  180, 0,  0.900, TRUE),
('SKU-SHOE-002',  'Adidas Ultraboost 5X',       'LIGHTBOOST中底, Primeknit+鞋面',        18, 'Adidas',  1299.00, 800.00,  120, 0,  0.950, TRUE),
-- 休闲零食 (cat=19)
('SKU-FOOD-001',  '乐事薯片大礼包',              '混合口味12包装, 总重540g',               19, '乐事',    49.90,  28.00,  800, 0,  0.650, TRUE),
('SKU-FOOD-002',  '德芙巧克力礼盒装',            '丝滑牛奶巧克力, 252g',                   19, '德芙',    89.00,  50.00,  400, 0,  0.280, TRUE),
('SKU-FOOD-003',  '每日坚果30包混合装',           '开心果腰果核桃葡萄干, 每日坚果750g',      19, '沃隆',   139.00,  85.00,  300, 0,  0.820, TRUE),
-- 健身器材 (cat=20)
('SKU-FIT-001',   'Keep瑜伽垫加厚防滑',          '185×80cm, 8mm厚度, NBR材质',            20, 'Keep',    169.00,  85.00,  250, 0,  2.500, TRUE),
('SKU-FIT-002',   '小米家智能跳绳',              '蓝牙计数, 3种模式, APP同步',             20, 'Xiaomi',   99.00,  50.00,  350, 0,  0.280, TRUE),
('SKU-FIT-003',   '可调节哑铃套装',              '2-20kg可调, 铸铁包胶, 家庭健身',         20, '锐步',    599.00,  350.00,  100, 0, 21.000, TRUE),
-- 智能穿戴 (cat=14)
('SKU-WEAR-001',  'Apple Watch Ultra 3',         '49mm钛金属, GPS+蜂窝, 全天候显示',      14, 'Apple',   6499.00, 4500.00,  70, 0,  0.061, TRUE),
('SKU-WEAR-002',  'Huawei Watch GT 5 Pro',       '钛金属表壳, 蓝宝石玻璃, ECG心电',       14, 'Huawei',  2999.00, 2000.00,  90, 0,  0.078, TRUE),
-- 平板电脑 (cat=13)
('SKU-TAB-001',   'iPad Air M3',                 'M3芯片, 11" Liquid Retina, 128GB',     13, 'Apple',   5499.00, 3800.00,  100, 0,  0.462, TRUE),
('SKU-TAB-002',   'Samsung Galaxy Tab S10 Ultra', '14.6" Dynamic AMOLED, 骁龙8 Gen4',    13, 'Samsung', 6999.00, 5000.00,  40, 0,  0.735, TRUE);

-- 插入测试数据（商品图片表: 50条, 每商品2张图）
INSERT INTO product_images (product_id, image_url, image_type, display_order, alt_text) VALUES
(1,  '/images/products/SKU-PHONE-001_main.jpg',      'MAIN',      0, 'iPhone 16 Pro Max正面图'),
(1,  '/images/products/SKU-PHONE-001_thumb.jpg',     'THUMBNAIL', 1, 'iPhone 16 Pro Max缩略图'),
(1,  '/images/products/SKU-PHONE-001_detail_01.jpg', 'DETAIL',    2, 'iPhone 16 Pro Max侧面'),
(2,  '/images/products/SKU-PHONE-002_main.jpg',      'MAIN',      0, 'Samsung S25 Ultra正面图'),
(2,  '/images/products/SKU-PHONE-002_thumb.jpg',     'THUMBNAIL', 1, 'Samsung S25 Ultra缩略图'),
(3,  '/images/products/SKU-PHONE-003_main.jpg',      'MAIN',      0, 'Xiaomi 16 Pro正面图'),
(3,  '/images/products/SKU-PHONE-003_thumb.jpg',     'THUMBNAIL', 1, 'Xiaomi 16 Pro缩略图'),
(4,  '/images/products/SKU-PHONE-004_main.jpg',      'MAIN',      0, 'Huawei Mate 70 Pro正面图'),
(4,  '/images/products/SKU-PHONE-004_thumb.jpg',     'THUMBNAIL', 1, 'Huawei Mate 70 Pro缩略图'),
(5,  '/images/products/SKU-LAPTOP-001_main.jpg',     'MAIN',      0, 'MacBook Pro 14 M4 Pro'),
(5,  '/images/products/SKU-LAPTOP-001_thumb.jpg',    'THUMBNAIL', 1, 'MacBook Pro 14缩略图'),
(6,  '/images/products/SKU-LAPTOP-002_main.jpg',     'MAIN',      0, 'ThinkPad X1 Carbon'),
(6,  '/images/products/SKU-LAPTOP-002_thumb.jpg',    'THUMBNAIL', 1, 'ThinkPad X1缩略图'),
(7,  '/images/products/SKU-LAPTOP-003_main.jpg',     'MAIN',      0, 'Dell XPS 16'),
(7,  '/images/products/SKU-LAPTOP-003_thumb.jpg',    'THUMBNAIL', 1, 'Dell XPS 16缩略图'),
(8,  '/images/products/SKU-ACC-001_main.jpg',        'MAIN',      0, 'Apple 20W充电器'),
(8,  '/images/products/SKU-ACC-001_detail.jpg',      'DETAIL',    1, '充电器接口细节'),
(9,  '/images/products/SKU-ACC-002_main.jpg',        'MAIN',      0, '倍思GaN充电器'),
(9,  '/images/products/SKU-ACC-002_thumb.jpg',       'THUMBNAIL', 1, '倍思充电器缩略图'),
(10, '/images/products/SKU-MEN-001_main.jpg',        'MAIN',      0, '海澜之家衬衫'),
(10, '/images/products/SKU-MEN-001_gallery_01.jpg',  'GALLERY',   1, '衬衫模特展示'),
(11, '/images/products/SKU-MEN-002_main.jpg',        'MAIN',      0, '优衣库T恤'),
(11, '/images/products/SKU-MEN-002_thumb.jpg',       'THUMBNAIL', 1, 'T恤缩略图'),
(12, '/images/products/SKU-WOM-001_main.jpg',        'MAIN',      0, 'ZARA连衣裙'),
(12, '/images/products/SKU-WOM-001_gallery_01.jpg',  'GALLERY',   1, '连衣裙模特图'),
(13, '/images/products/SKU-WOM-002_main.jpg',        'MAIN',      0, '太平鸟针织衫'),
(13, '/images/products/SKU-WOM-002_thumb.jpg',       'THUMBNAIL', 1, '针织衫缩略图'),
(14, '/images/products/SKU-SHOE-001_main.jpg',       'MAIN',      0, 'Nike Pegasus 42'),
(14, '/images/products/SKU-SHOE-001_detail_01.jpg',  'DETAIL',    1, 'Pegasus鞋底细节'),
(15, '/images/products/SKU-SHOE-002_main.jpg',       'MAIN',      0, 'Adidas Ultraboost 5X'),
(15, '/images/products/SKU-SHOE-002_thumb.jpg',      'THUMBNAIL', 1, 'Ultraboost缩略图'),
(16, '/images/products/SKU-FOOD-001_main.jpg',       'MAIN',      0, '乐事薯片大礼包'),
(16, '/images/products/SKU-FOOD-001_thumb.jpg',      'THUMBNAIL', 1, '薯片缩略图'),
(17, '/images/products/SKU-FOOD-002_main.jpg',       'MAIN',      0, '德芙巧克力礼盒'),
(17, '/images/products/SKU-FOOD-002_gallery_01.jpg', 'GALLERY',   1, '巧克力细节展示'),
(18, '/images/products/SKU-FOOD-003_main.jpg',       'MAIN',      0, '每日坚果混合装'),
(18, '/images/products/SKU-FOOD-003_thumb.jpg',      'THUMBNAIL', 1, '坚果缩略图'),
(19, '/images/products/SKU-FIT-001_main.jpg',        'MAIN',      0, 'Keep瑜伽垫'),
(19, '/images/products/SKU-FIT-001_detail_01.jpg',   'DETAIL',    1, '瑜伽垫厚度展示'),
(20, '/images/products/SKU-FIT-002_main.jpg',        'MAIN',      0, '小米智能跳绳'),
(20, '/images/products/SKU-FIT-002_thumb.jpg',       'THUMBNAIL', 1, '跳绳缩略图'),
(21, '/images/products/SKU-FIT-003_main.jpg',        'MAIN',      0, '可调节哑铃套装'),
(21, '/images/products/SKU-FIT-003_gallery_01.jpg',  'GALLERY',   1, '哑铃多角度展示'),
(22, '/images/products/SKU-WEAR-001_main.jpg',       'MAIN',      0, 'Apple Watch Ultra 3'),
(22, '/images/products/SKU-WEAR-001_thumb.jpg',      'THUMBNAIL', 1, 'AW Ultra缩略图'),
(23, '/images/products/SKU-WEAR-002_main.jpg',       'MAIN',      0, 'Huawei GT 5 Pro'),
(23, '/images/products/SKU-WEAR-002_thumb.jpg',      'THUMBNAIL', 1, 'GT5 Pro缩略图'),
(24, '/images/products/SKU-TAB-001_main.jpg',        'MAIN',      0, 'iPad Air M3'),
(24, '/images/products/SKU-TAB-001_thumb.jpg',       'THUMBNAIL', 1, 'iPad Air缩略图'),
(25, '/images/products/SKU-TAB-002_main.jpg',        'MAIN',      0, 'Samsung Tab S10 Ultra'),
(25, '/images/products/SKU-TAB-002_thumb.jpg',       'THUMBNAIL', 1, 'Tab S10缩略图');

-- 插入测试数据（库存变动记录: 30条, 关联products表）
INSERT INTO inventory_logs (product_id, change_type, quantity_change, previous_quantity, new_quantity, reference_id, notes, created_at, created_by) VALUES
(1,  'PURCHASE',    200,   0,   200, 'PO-2025-0001', '首批入库200台',                                  '2025-03-01 10:00:00', 'admin'),
(1,  'SALE',        -50, 200,   150, 'ORD-2025-00001', '订单销售50台',                                   '2025-04-15 14:30:00', 'system'),
(1,  'SALE',        -30, 150,   120, 'ORD-2025-00001', '订单销售30台',                                   '2025-06-20 09:15:00', 'system'),
(2,  'PURCHASE',    150,   0,   150, 'PO-2025-0002', '首批入库150台',                                  '2025-03-05 11:00:00', 'admin'),
(2,  'SALE',        -40, 150,   110, 'ORD-2025-00002', '订单销售40台',                                   '2025-04-20 16:45:00', 'system'),
(2,  'SALE',        -25, 110,    85, 'ORD-2025-00023', '订单销售25台',                                   '2025-07-05 10:00:00', 'system'),
(3,  'PURCHASE',    300,   0,   300, 'PO-2025-0003', '首批入库300台',                                  '2025-03-10 08:30:00', 'admin'),
(3,  'SALE',       -100, 300,   200, 'ORD-2025-00003', '双十一活动销售100台',                            '2025-11-11 00:05:00', 'system'),
(4,  'PURCHASE',    100,   0,   100, 'PO-2025-0004', '首批入库100台',                                  '2025-03-15 09:00:00', 'admin'),
(4,  'SALE',        -25, 100,    75, 'ORD-2025-00018', '订单销售25台',                                   '2025-12-01 13:20:00', 'system'),
(4,  'SALE',        -15,  75,    60, 'ORD-2025-00018', '订单销售15台',                                   '2026-01-15 11:30:00', 'system'),
(5,  'PURCHASE',     80,   0,    80, 'PO-2025-0005', '首批入库80台',                                   '2025-03-20 10:15:00', 'admin'),
(5,  'SALE',        -20,  80,    60, 'ORD-2025-00004', '订单销售20台',                                   '2025-05-10 09:00:00', 'system'),
(5,  'SALE',        -15,  60,    45, 'ORD-2025-00004', '订单销售15台',                                   '2026-03-01 14:00:00', 'system'),
(6,  'PURCHASE',     50,   0,    50, 'PO-2025-0006', '首批入库50台',                                   '2025-04-01 09:30:00', 'admin'),
(6,  'SALE',        -20,  50,    30, 'ORD-2025-00006', '订单销售20台',                                   '2025-06-15 11:00:00', 'system'),
(7,  'PURCHASE',     40,   0,    40, 'PO-2025-0007', '首批入库40台',                                   '2025-04-10 08:00:00', 'admin'),
(7,  'SALE',        -15,  40,    25, 'ORD-2025-00013', '订单销售15台',                                   '2025-08-20 15:30:00', 'system'),
(8,  'PURCHASE',   1000,   0,  1000, 'PO-2025-0008', '首次采购1000个',                                 '2025-02-15 10:00:00', 'admin'),
(8,  'SALE',       -500,1000,   500, 'ORD-2025-00006', '批量售出500个',                                  '2025-05-01 08:30:00', 'system'),
(9,  'PURCHASE',   1000,   0,  1000, 'PO-2025-0009', '首次采购1000个',                                 '2025-02-20 11:00:00', 'admin'),
(9,  'SALE',       -200,1000,   800, 'ORD-2025-00003', '售出200个',                                      '2025-06-10 14:00:00', 'system'),
(10, 'PURCHASE',    500,   0,   500, 'PO-2025-0010', '首次采购500件',                                  '2025-03-01 09:15:00', 'admin'),
(10, 'SALE',       -200, 500,   300, 'ORD-2025-00007', '售出200件',                                      '2025-07-01 10:00:00', 'system'),
(16, 'PURCHASE',   1000,   0,  1000, 'PO-2025-0011', '首次采购1000包',                                 '2025-02-10 08:00:00', 'admin'),
(16, 'SALE',       -200,1000,   800, 'ORD-2025-00014', '售出200包',                                      '2025-04-01 12:00:00', 'system'),
(20, 'PURCHASE',    500,   0,   500, 'PO-2025-0012', '首次采购500个',                                  '2025-05-01 10:30:00', 'admin'),
(20, 'SALE',       -150, 500,   350, 'ORD-2025-00005', '售出150个',                                      '2025-08-01 16:00:00', 'system'),
(12, 'DAMAGE',       -3, 153,   150, 'DMG-2025-001', '仓库搬运过程中包装破损3件',                      '2025-06-01 09:00:00', 'warehouse1'),
(14, 'RETURN',        5, 175,   180, 'RTN-2026-001', '客户退货5双（尺码不合适）',                       '2026-03-20 14:30:00', 'cservice1');


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

-- 插入测试数据（订单主表: 30条, user_id关联user_management.users）
INSERT INTO orders (order_number, user_id, total_amount, discount_amount, shipping_fee, final_amount, order_status, payment_status, shipping_address, payment_method, order_notes, created_at) VALUES
('ORD-2025-00001',  1, 10148.00,  300.00,  20.00,  9868.00, 'DELIVERED', 'PAID',  '北京市朝阳区建国路88号院1号楼1201',          'Visa尾号3891',       'iPhone 16 Pro Max + 充电器',                              '2025-04-10 10:15:30'),
('ORD-2025-00002',  2,  9078.00,  140.00,  15.00,  8953.00, 'DELIVERED', 'PAID',  '上海市浦东新区陆家嘴环路1000号恒生银行大厦22层', 'MasterCard尾号5210', 'Samsung Galaxy S25 Ultra + 充电器',                       '2025-04-15 14:20:00'),
('ORD-2025-00003',  3,  5078.00,   80.00,  15.00,  5013.00, 'DELIVERED', 'PAID',  '广东省广州市天河区天河路385号太古汇1座18楼',     'Visa尾号6742',       'Xiaomi 16 Pro + 倍思充电器',                              '2025-04-20 09:00:00'),
('ORD-2025-00004',  4, 15148.00,  500.00,  20.00, 14668.00, 'DELIVERED', 'PAID',  '浙江省杭州市西湖区文三路478号华星时代广场A座12楼', 'MasterCard尾号9801', 'MacBook Pro 14 M4 Pro + 充电器',                          '2025-05-01 16:45:00'),
('ORD-2025-00005',  5,   268.00,    8.00,  10.00,   270.00, 'DELIVERED', 'PAID',  '四川省成都市武侯区天府大道北段1199号银泰中心2栋',  'PayPal',             'Keep瑜伽垫 + 智能跳绳',                                  '2025-05-10 11:30:00'),
('ORD-2025-00006',  6, 20449.00,  600.00,  20.00, 19869.00, 'DELIVERED', 'PAID',  '湖北省武汉市洪山区珞瑜路1037号华中科技大学科技园',  '支付宝',             'ThinkPad X1 Carbon + 50个充电器',                         '2025-05-15 08:15:00'),
('ORD-2025-00007',  7,   378.00,   11.00,  10.00,   377.00, 'DELIVERED', 'PAID',  '江苏省南京市鼓楼区汉中路1号南京国际金融中心40层',   'UnionPay尾号1104',   '海澜之家衬衫 + T恤',                                     '2025-06-01 10:00:00'),
('ORD-2025-00008',  8,  1257.00,   20.00,  12.00,  1249.00, 'DELIVERED', 'PAID',  '重庆市渝中区解放碑步行街民权路28号英利国际',         '微信支付',           'Nike Pegasus 42 + 2件T恤',                               '2025-06-10 14:20:00'),
('ORD-2025-00009',  9,   228.00,    7.00,  10.00,   231.00, 'DELIVERED', 'PAID',  '天津市和平区南京路189号津汇广场2座19层',             '微信支付',           '优衣库T恤 + 充电器',                                     '2025-06-20 09:45:00'),
('ORD-2025-00010', 10,   538.00,    0.00,  10.00,   548.00, 'DELIVERED', 'PAID',  '山东省济南市历下区泉城路180号齐鲁国际大厦C座10层',  'Amex尾号3328',       'ZARA连衣裙 + T恤',                                       '2025-07-05 12:00:00'),
('ORD-2025-00011', 11,  2398.00,   40.00,  12.00,  2370.00, 'SHIPPED',   'PAID',  '福建省厦门市思明区鹭江道100号财富中心25层',          '支付宝',             'Adidas Ultraboost + Nike Pegasus',                        '2025-07-15 15:30:00'),
('ORD-2025-00012', 12,  6648.00,  100.00,  15.00,  6563.00, 'SHIPPED',   'PAID',  '湖南省长沙市岳麓区麓谷大道658号麓谷信息港A栋',      'UnionPay尾号7456',   'Apple Watch Ultra 3 + 充电器',                           '2025-08-01 10:10:00'),
('ORD-2025-00013', 13, 14297.00,  400.00,  20.00, 13917.00, 'PROCESSING','PAID',  '陕西省西安市雁塔区高新四路17号志诚丽柏酒店15层',     'Visa尾号8912',       'Dell XPS 16 + 2个充电器',                                 '2025-08-15 08:00:00'),
('ORD-2025-00014', 14,   227.90,    7.00,  10.00,   230.90, 'DELIVERED', 'PAID',  '安徽省合肥市蜀山区长江西路88号环球金融广场B座',      'PayPal',             '乐事薯片 + 德芙巧克力x2',                                '2025-09-01 14:00:00'),
('ORD-2025-00015', 15,   168.00,    5.00,   8.00,   171.00, 'DELIVERED', 'PAID',  '辽宁省沈阳市和平区青年大街286号华润大厦9层',         '微信支付',           '德芙巧克力 + 倍思充电器',                                '2025-09-10 16:20:00'),
('ORD-2025-00016', 16,   308.00,    9.00,  10.00,   309.00, 'DELIVERED', 'PAID',  '河南省郑州市金水区花园路39号国贸中心A座22层',        'MasterCard尾号2378', '每日坚果 + Keep瑜伽垫',                                  '2025-09-20 11:45:00'),
('ORD-2025-00017', 17,   698.00,   10.00,  10.00,   698.00, 'DELIVERED', 'PAID',  '河北省石家庄市长安区中山东路188号北国商城',           '支付宝',             '可调节哑铃 + 智能跳绳',                                  '2025-10-01 09:30:00'),
('ORD-2025-00018', 18,  7078.00,  110.00,  15.00,  6983.00, 'SHIPPED',   'PAID',  '云南省昆明市五华区东风西路129号顺城购物中心',         'Visa Debit尾号9634', 'Huawei Mate 70 Pro + 充电器',                             '2025-10-10 10:00:00'),
('ORD-2025-00019', 19,  7148.00,  110.00,  15.00,  7053.00, 'PROCESSING','PAID',  '贵州省贵阳市南明区中华南路78号贵阳壹号25楼',          'Amex尾号5087',       'Samsung Tab S10 Ultra + 充电器',                          '2025-10-20 13:15:00'),
('ORD-2025-00020', 20,   386.00,   12.00,  10.00,   384.00, 'DELIVERED', 'PAID',  '山西省太原市小店区长风街116号北美新天地',             '微信支付',           'Apple充电器 + 倍思充电器x3',                             '2025-11-01 08:30:00'),
('ORD-2025-00021', 21,  5648.00,   80.00,  15.00,  5583.00, 'SHIPPED',   'PAID',  '江西省南昌市红谷滩区红谷中大道998号绿地中央广场',     '支付宝',             'iPad Air M3 + 充电器',                                   '2025-11-10 15:00:00'),
('ORD-2025-00022', 22,   457.00,   14.00,  10.00,   453.00, 'DELIVERED', 'PAID',  '吉林省长春市朝阳区红旗街959号万达广场',               'MasterCard尾号6501', '海澜之家衬衫 + 2件T恤',                                  '2025-11-20 10:45:00'),
('ORD-2025-00023', 23,  9078.00,  140.00,  15.00,  8953.00, 'PROCESSING','PAID',  '黑龙江省哈尔滨市道里区中央大街88号金安国际',          'UnionPay尾号1823',   'Samsung S25 Ultra + 充电器',                              '2025-12-01 14:10:00'),
('ORD-2025-00024', 24,   377.00,   11.00,  10.00,   376.00, 'DELIVERED', 'PAID',  '甘肃省兰州市城关区庆阳路42号万盛商务大厦',             '支付宝',             '倍思充电器 + Apple充电器x2',                              '2025-12-10 11:20:00'),
('ORD-2025-00025', 25,   858.00,   10.00,  10.00,   858.00, 'DELIVERED', 'PAID',  '广西南宁市青秀区民族大道136号万象城3座',              '微信支付',           '太平鸟针织衫 + ZARA连衣裙',                              '2025-12-20 09:00:00'),
('ORD-2025-00026',  1,  3148.00,   50.00,  12.00,  3110.00, 'PAID',      'PAID',  '北京市朝阳区建国路88号院1号楼1201',                   '支付宝',             'Huawei Watch GT 5 Pro + 充电器',                          '2026-01-05 10:30:00'),
('ORD-2025-00027',  3,   138.90,    4.00,   8.00,   142.90, 'DELIVERED', 'PAID',  '广东省广州市天河区天河路385号太古汇1座18楼',          '微信支付',           '德芙巧克力 + 乐事薯片',                                  '2026-01-15 14:00:00'),
('ORD-2025-00028',  5,   268.00,    8.00,  10.00,   270.00, 'DELIVERED', 'PAID',  '四川省成都市武侯区天府大道北段1199号银泰中心2栋',     'PayPal',             '智能跳绳 + Keep瑜伽垫',                                  '2026-02-01 08:45:00'),
('ORD-2025-00029',  2,   188.90,    6.00,   8.00,   190.90, 'SHIPPED',   'PAID',  '上海市浦东新区陆家嘴环路1000号恒生银行大厦22层',      'MasterCard尾号5210', '每日坚果 + 乐事薯片',                                    '2026-02-20 13:30:00'),
('ORD-2025-00030',  8,  9498.00,  140.00,  15.00,  9373.00, 'PENDING',   'UNPAID','重庆市渝中区解放碑步行街民权路28号英利国际',            '微信支付',           'Apple Watch Ultra 3 + Huawei Watch GT 5 Pro',             '2026-03-01 16:00:00');

-- 插入测试数据（订单项表: 60条, 关联orders和products）
INSERT INTO order_items (order_id, product_id, sku, product_name, unit_price, quantity, subtotal, snapshot_data) VALUES
(1,  1,  'SKU-PHONE-001',   'iPhone 16 Pro Max 256GB',           9999.00,  1,  9999.00, '{}'),
(2,  2,  'SKU-PHONE-002',   'Samsung Galaxy S25 Ultra',          8999.00,  1,  8999.00, '{}'),
(3,  3,  'SKU-PHONE-003',   'Xiaomi 16 Pro',                     4999.00,  1,  4999.00, '{}'),
(4,  5,  'SKU-LAPTOP-001',  'MacBook Pro 14 M4 Pro',            14999.00,  1, 14999.00, '{}'),
(5,  19, 'SKU-FIT-001',     'Keep瑜伽垫加厚防滑',                 169.00,  1,   169.00, '{}'),
(6,  6,  'SKU-LAPTOP-002',  'ThinkPad X1 Carbon Gen12',          12999.00,  1, 12999.00, '{}'),
(7,  10, 'SKU-MEN-001',     '海澜之家商务衬衫',                    299.00,  1,   299.00, '{}'),
(8,  14, 'SKU-SHOE-001',    'Nike Air Zoom Pegasus 42',           1099.00,  1,  1099.00, '{}'),
(9,  11, 'SKU-MEN-002',     '优衣库纯棉T恤',                        79.00,  1,    79.00, '{}'),
(10, 12, 'SKU-WOM-001',     'ZARA碎花连衣裙',                      459.00,  1,   459.00, '{}'),
(11, 15, 'SKU-SHOE-002',    'Adidas Ultraboost 5X',               1299.00,  1,  1299.00, '{}'),
(12, 22, 'SKU-WEAR-001',    'Apple Watch Ultra 3',                6499.00,  1,  6499.00, '{}'),
(13, 7,  'SKU-LAPTOP-003',  'Dell XPS 16',                       13999.00,  1, 13999.00, '{}'),
(14, 16, 'SKU-FOOD-001',    '乐事薯片大礼包',                        49.90,  1,    49.90, '{}'),
(14, 17, 'SKU-FOOD-002',    '德芙巧克力礼盒装',                      89.00,  2,   178.00, '{}'),
(15, 17, 'SKU-FOOD-002',    '德芙巧克力礼盒装',                      89.00,  1,    89.00, '{}'),
(16, 18, 'SKU-FOOD-003',    '每日坚果30包混合装',                   139.00,  1,   139.00, '{}'),
(17, 21, 'SKU-FIT-003',     '可调节哑铃套装',                      599.00,  1,   599.00, '{}'),
(18, 4,  'SKU-PHONE-004',   'Huawei Mate 70 Pro',                 6999.00,  1,  6999.00, '{}'),
(19, 25, 'SKU-TAB-002',     'Samsung Galaxy Tab S10 Ultra',       6999.00,  1,  6999.00, '{}'),
(20, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                149.00,  1,   149.00, '{}'),
(21, 24, 'SKU-TAB-001',     'iPad Air M3',                        5499.00,  1,  5499.00, '{}'),
(22, 10, 'SKU-MEN-001',     '海澜之家商务衬衫',                      299.00,  1,   299.00, '{}'),
(23, 2,  'SKU-PHONE-002',   'Samsung Galaxy S25 Ultra',           8999.00,  1,  8999.00, '{}'),
(24, 9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                   79.00,  1,    79.00, '{}'),
(25, 13, 'SKU-WOM-002',     '太平鸟宽松针织衫',                     399.00,  1,   399.00, '{}'),
(26, 23, 'SKU-WEAR-002',    'Huawei Watch GT 5 Pro',              2999.00,  1,  2999.00, '{}'),
(27, 17, 'SKU-FOOD-002',    '德芙巧克力礼盒装',                      89.00,  1,    89.00, '{}'),
(28, 20, 'SKU-FIT-002',     '小米家智能跳绳',                        99.00,  1,    99.00, '{}'),
(29, 18, 'SKU-FOOD-003',    '每日坚果30包混合装',                   139.00,  1,   139.00, '{}'),
(30, 22, 'SKU-WEAR-001',    'Apple Watch Ultra 3',                6499.00,  1,  6499.00, '{}'),
-- 多商品订单：同一个人在一单中买多件
(3,  9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                   79.00,  1,    79.00, '{}'),
(5,  20, 'SKU-FIT-002',     '小米家智能跳绳',                        99.00,  1,    99.00, '{}'),
(8,  11, 'SKU-MEN-002',     '优衣库纯棉T恤',                         79.00,  2,   158.00, '{}'),
(11, 14, 'SKU-SHOE-001',    'Nike Air Zoom Pegasus 42',            1099.00,  1,  1099.00, '{}'),
(13, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  2,   298.00, '{}'),
(15, 9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                    79.00,  1,    79.00, '{}'),
(16, 19, 'SKU-FIT-001',     'Keep瑜伽垫加厚防滑',                    169.00,  1,   169.00, '{}'),
(21, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(22, 11, 'SKU-MEN-002',     '优衣库纯棉T恤',                          79.00,  2,   158.00, '{}'),
(25, 12, 'SKU-WOM-001',     'ZARA碎花连衣裙',                       459.00,  1,   459.00, '{}'),
-- 超大数量订单
(6,  8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00, 50,  7450.00, '{}'),
(20, 9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                    79.00,  3,   237.00, '{}'),
(24, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  2,   298.00, '{}'),
(27, 16, 'SKU-FOOD-001',    '乐事薯片大礼包',                         49.90,  1,    49.90, '{}'),
(28, 19, 'SKU-FIT-001',     'Keep瑜伽垫加厚防滑',                    169.00,  1,   169.00, '{}'),
(29, 16, 'SKU-FOOD-001',    '乐事薯片大礼包',                         49.90,  1,    49.90, '{}'),
-- 附加商品用于补足订单item数
(1,  8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(2,  9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                    79.00,  1,    79.00, '{}'),
(4,  8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(10, 11, 'SKU-MEN-002',     '优衣库纯棉T恤',                          79.00,  1,    79.00, '{}'),
(12, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(17, 20, 'SKU-FIT-002',     '小米家智能跳绳',                         99.00,  1,    99.00, '{}'),
(18, 9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                    79.00,  1,    79.00, '{}'),
(19, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(23, 9,  'SKU-ACC-002',     '倍思30W氮化镓充电器',                    79.00,  1,    79.00, '{}'),
(26, 8,  'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}'),
(30, 23, 'SKU-WEAR-002',    'Huawei Watch GT 5 Pro',               2999.00,  1,  2999.00, '{}'),
(7,  11, 'SKU-MEN-002',     '优衣库纯棉T恤',                          79.00,  1,    79.00, '{}'),
(9,   8, 'SKU-ACC-001',     'Apple 20W USB-C充电器',                 149.00,  1,   149.00, '{}');

-- 插入测试数据（订单物流表: 30条, 一单一物流）
INSERT INTO order_shipping (order_id, tracking_number, shipping_carrier, shipping_method, estimated_delivery_date, actual_delivery_date, shipping_status, receiver_name, receiver_phone, shipping_address, notes) VALUES
(1,  'SF1234567890',   '顺丰速运',   '标快',  '2025-04-13', '2025-04-12', 'DELIVERED', '张三', '13800001001', '北京市朝阳区建国路88号院1号楼1201',               '本人签收'),
(2,  'SF1234567891',   '顺丰速运',   '标快',  '2025-04-18', '2025-04-18', 'DELIVERED', '李四', '13800001002', '上海市浦东新区陆家嘴环路1000号恒生银行大厦22层',  '前台代收'),
(3,  'JD9876543210',   '京东物流',   '211限时达','2025-04-21','2025-04-21','DELIVERED', '王五', '13800001003', '广东省广州市天河区天河路385号太古汇1座18楼',     '本人签收'),
(4,  'SF1234567892',   '顺丰速运',   '特快',  '2025-05-03', '2025-05-03', 'DELIVERED', '赵六', '13800001004', '浙江省杭州市西湖区文三路478号华星时代广场A座12楼','本人签收'),
(5,  'YT1122334455',   '圆通速递',   '标准',  '2025-05-13', '2025-05-13', 'DELIVERED', '孙七', '13800001005', '四川省成都市武侯区天府大道北段1199号银泰中心2栋', '快递柜签收'),
(6,  'SF1234567893',   '顺丰速运',   '特快',  '2025-05-18', '2025-05-18', 'DELIVERED', '周八', '13800001006', '湖北省武汉市洪山区珞瑜路1037号华中科技大学科技园','本人签收'),
(7,  'JD2233445566',   '京东物流',   '标快',  '2025-06-04', '2025-06-04', 'DELIVERED', '吴九', '13800001007', '江苏省南京市鼓楼区汉中路1号南京国际金融中心40层',  '本人签收'),
(8,  'SF1234567894',   '顺丰速运',   '标快',  '2025-06-13', '2025-06-12', 'DELIVERED', '郑十', '13800001008', '重庆市渝中区解放碑步行街民权路28号英利国际',       '本人签收'),
(9,  'ST9988776655',   '申通快递',   '标准',  '2025-06-23', '2025-06-23', 'DELIVERED', '刘一', '13800001009', '天津市和平区南京路189号津汇广场2座19层',            '本人签收'),
(10, 'SF1234567895',   '顺丰速运',   '标快',  '2025-07-08', '2025-07-08', 'DELIVERED', '陈二', '13800001010', '山东省济南市历下区泉城路180号齐鲁国际大厦C座10层', '本人签收'),
(11, 'SF1234567896',   '顺丰速运',   '标快',  '2025-07-18', NULL,         'IN_TRANSIT',        '杨三', '13800001011', '福建省厦门市思明区鹭江道100号财富中心25层',       NULL),
(12, 'SF1234567897',   '顺丰速运',   '特快',  '2025-08-04', NULL,         'IN_TRANSIT',        '黄四', '13800001012', '湖南省长沙市岳麓区麓谷大道658号麓谷信息港A栋',    NULL),
(13, 'SF1234567898',   '顺丰速运',   '标快',  '2025-08-18', NULL,         'PREPARING',         '许五', '13800001013', '陕西省西安市雁塔区高新四路17号志诚丽柏酒店15层',   NULL),
(14, 'YD4455667788',   '韵达速递',   '标准',  '2025-09-04', '2025-09-03', 'DELIVERED', '何六', '13800001014', '安徽省合肥市蜀山区长江西路88号环球金融广场B座',    '本人签收'),
(15, 'YT2233445566',   '圆通速递',   '标准',  '2025-09-13', '2025-09-13', 'DELIVERED', '吕七', '13800001015', '辽宁省沈阳市和平区青年大街286号华润大厦9层',       '本人签收'),
(16, 'JD3344556677',   '京东物流',   '标快',  '2025-09-23', '2025-09-22', 'DELIVERED', '施八', '13800001016', '河南省郑州市金水区花园路39号国贸中心A座22层',     '本人签收'),
(17, 'SF1234567899',   '顺丰速运',   '重货',  '2025-10-05', '2025-10-05', 'DELIVERED', '张九', '13800001017', '河北省石家庄市长安区中山东路188号北国商城',        '本人签收，上楼'),
(18, 'SF1234567900',   '顺丰速运',   '特快',  '2025-10-13', NULL,         'IN_TRANSIT',        '孔十', '13800001018', '云南省昆明市五华区东风西路129号顺城购物中心',      NULL),
(19, 'SF1234567901',   '顺丰速运',   '标快',  '2025-10-23', NULL,         'PREPARING',         '曹一', '13800001019', '贵州省贵阳市南明区中华南路78号贵阳壹号25楼',       NULL),
(20, 'ST1122334455',   '申通快递',   '标准',  '2025-11-04', '2025-11-04', 'DELIVERED', '严二', '13800001020', '山西省太原市小店区长风街116号北美新天地',          '本人签收'),
(21, 'SF1234567902',   '顺丰速运',   '标快',  '2025-11-13', NULL,         'IN_TRANSIT',        '花三', '13800001021', '江西省南昌市红谷滩区红谷中大道998号绿地中央广场',  NULL),
(22, 'JD4455667788',   '京东物流',   '标快',  '2025-11-23', '2025-11-22', 'DELIVERED', '金四', '13800001022', '吉林省长春市朝阳区红旗街959号万达广场',             '快递柜签收'),
(23, 'SF1234567903',   '顺丰速运',   '标快',  '2025-12-04', NULL,         'PREPARING',         '魏五', '13800001023', '黑龙江省哈尔滨市道里区中央大街88号金安国际',       NULL),
(24, 'YD5566778899',   '韵达速递',   '标准',  '2025-12-13', '2025-12-12', 'DELIVERED', '陶六', '13800001024', '甘肃省兰州市城关区庆阳路42号万盛商务大厦',          '本人签收'),
(25, 'YT3344556677',   '圆通速递',   '标准',  '2025-12-23', '2025-12-23', 'DELIVERED', '姜七', '13800001025', '广西南宁市青秀区民族大道136号万象城3座',            '本人签收'),
(26, 'SF1234567904',   '顺丰速运',   '标快',  '2026-01-08', NULL,         'PICKED_UP',         '张三', '13800001001', '北京市朝阳区建国路88号院1号楼1201',                NULL),
(27, 'JD5566778899',   '京东物流',   '标快',  '2026-01-18', '2026-01-17', 'DELIVERED', '王五', '13800001003', '广东省广州市天河区天河路385号太古汇1座18楼',       '本人签收'),
(28, 'ST2233445566',   '申通快递',   '标准',  '2026-02-04', '2026-02-04', 'DELIVERED', '孙七', '13800001005', '四川省成都市武侯区天府大道北段1199号银泰中心2栋',  '本人签收'),
(29, 'SF1234567905',   '顺丰速运',   '标快',  '2026-02-23', NULL,         'IN_TRANSIT',        '李四', '13800001002', '上海市浦东新区陆家嘴环路1000号恒生银行大厦22层',   NULL),
(30, 'SF1234567906',   '顺丰速运',   '标快',  '2026-03-04', NULL,         'PREPARING',         '郑十', '13800001008', '重庆市渝中区解放碑步行街民权路28号英利国际',        '等待支付');

-- 插入测试数据（支付记录表: 30条, 一订单一支付记录）
INSERT INTO payment_records (order_id, payment_number, payment_amount, payment_method, payment_status, transaction_id, payer_info, payment_time, created_at) VALUES
(1,  'PAY-2025-00001',  9868.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250410101530', '{"user_id":1,"name":"张三"}',   '2025-04-10 10:15:30', '2025-04-10 10:15:30'),
(2,  'PAY-2025-00002',  8953.00, 'DEBIT_CARD',  'SUCCESS', 'TXN-20250415142000', '{"user_id":2,"name":"李四"}',   '2025-04-15 14:20:00', '2025-04-15 14:20:00'),
(3,  'PAY-2025-00003',  5013.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250420090000', '{"user_id":3,"name":"王五"}',   '2025-04-20 09:00:00', '2025-04-20 09:00:00'),
(4,  'PAY-2025-00004', 14668.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250501164500', '{"user_id":4,"name":"赵六"}',   '2025-05-01 16:45:00', '2025-05-01 16:45:00'),
(5,  'PAY-2025-00005',   270.00, 'PAYPAL',      'SUCCESS', 'TXN-20250510113000', '{"user_id":5,"name":"孙七"}',   '2025-05-10 11:30:00', '2025-05-10 11:30:00'),
(6,  'PAY-2025-00006', 19869.00, 'ALIPAY',      'SUCCESS', 'TXN-20250515081500', '{"user_id":6,"name":"周八"}',   '2025-05-15 08:15:00', '2025-05-15 08:15:00'),
(7,  'PAY-2025-00007',   377.00, 'DEBIT_CARD',  'SUCCESS', 'TXN-20250601100000', '{"user_id":7,"name":"吴九"}',   '2025-06-01 10:00:00', '2025-06-01 10:00:00'),
(8,  'PAY-2025-00008',  1249.00, 'WECHAT', 'SUCCESS', 'TXN-20250610142000', '{"user_id":8,"name":"郑十"}',   '2025-06-10 14:20:00', '2025-06-10 14:20:00'),
(9,  'PAY-2025-00009',    231.00, 'WECHAT',      'SUCCESS', 'TXN-20250620094500', '{"user_id":9,"name":"刘一"}',   '2025-06-20 09:45:00', '2025-06-20 09:45:00'),
(10, 'PAY-2025-00010',   548.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250705120000', '{"user_id":10,"name":"陈二"}',  '2025-07-05 12:00:00', '2025-07-05 12:00:00'),
(11, 'PAY-2025-00011',  2370.00, 'ALIPAY',      'SUCCESS', 'TXN-20250715153000', '{"user_id":11,"name":"杨三"}',  '2025-07-15 15:30:00', '2025-07-15 15:30:00'),
(12, 'PAY-2025-00012',  6563.00, 'DEBIT_CARD',  'SUCCESS', 'TXN-20250801101000', '{"user_id":12,"name":"黄四"}',  '2025-08-01 10:10:00', '2025-08-01 10:10:00'),
(13, 'PAY-2025-00013', 13917.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250815080000', '{"user_id":13,"name":"许五"}',  '2025-08-15 08:00:00', '2025-08-15 08:00:00'),
(14, 'PAY-2025-00014',    230.90, 'PAYPAL',      'SUCCESS', 'TXN-20250901140000', '{"user_id":14,"name":"何六"}',  '2025-09-01 14:00:00', '2025-09-01 14:00:00'),
(15, 'PAY-2025-00015',    171.00, 'WECHAT',      'SUCCESS', 'TXN-20250910162000', '{"user_id":15,"name":"吕七"}',  '2025-09-10 16:20:00', '2025-09-10 16:20:00'),
(16, 'PAY-2025-00016',   309.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20250920114500', '{"user_id":16,"name":"施八"}',  '2025-09-20 11:45:00', '2025-09-20 11:45:00'),
(17, 'PAY-2025-00017',   698.00, 'ALIPAY',      'SUCCESS', 'TXN-20251001093000', '{"user_id":17,"name":"张九"}',  '2025-10-01 09:30:00', '2025-10-01 09:30:00'),
(18, 'PAY-2025-00018',  6983.00, 'DEBIT_CARD',  'SUCCESS', 'TXN-20251010100000', '{"user_id":18,"name":"孔十"}',  '2025-10-10 10:00:00', '2025-10-10 10:00:00'),
(19, 'PAY-2025-00019',  7053.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20251020131500', '{"user_id":19,"name":"曹一"}',  '2025-10-20 13:15:00', '2025-10-20 13:15:00'),
(20, 'PAY-2025-00020',   384.00, 'WECHAT',      'SUCCESS', 'TXN-20251101083000', '{"user_id":20,"name":"严二"}',  '2025-11-01 08:30:00', '2025-11-01 08:30:00'),
(21, 'PAY-2025-00021',  5583.00, 'ALIPAY',      'SUCCESS', 'TXN-20251110150000', '{"user_id":21,"name":"花三"}',  '2025-11-10 15:00:00', '2025-11-10 15:00:00'),
(22, 'PAY-2025-00022',   453.00, 'CREDIT_CARD', 'SUCCESS', 'TXN-20251120104500', '{"user_id":22,"name":"金四"}',  '2025-11-20 10:45:00', '2025-11-20 10:45:00'),
(23, 'PAY-2025-00023',  8953.00, 'DEBIT_CARD',  'SUCCESS', 'TXN-20251201141000', '{"user_id":23,"name":"魏五"}',  '2025-12-01 14:10:00', '2025-12-01 14:10:00'),
(24, 'PAY-2025-00024',    376.00, 'ALIPAY',      'SUCCESS', 'TXN-20251210112000', '{"user_id":24,"name":"陶六"}',  '2025-12-10 11:20:00', '2025-12-10 11:20:00'),
(25, 'PAY-2025-00025',   858.00, 'WECHAT',      'SUCCESS', 'TXN-20251220090000', '{"user_id":25,"name":"姜七"}',  '2025-12-20 09:00:00', '2025-12-20 09:00:00'),
(26, 'PAY-2025-00026',  3110.00, 'ALIPAY',      'SUCCESS', 'TXN-20260105103000', '{"user_id":1,"name":"张三"}',   '2026-01-05 10:30:00', '2026-01-05 10:30:00'),
(27, 'PAY-2025-00027',    142.90, 'WECHAT',      'SUCCESS', 'TXN-20260115140000', '{"user_id":3,"name":"王五"}',   '2026-01-15 14:00:00', '2026-01-15 14:00:00'),
(28, 'PAY-2025-00028',    270.00, 'PAYPAL',      'SUCCESS', 'TXN-20260201084500', '{"user_id":5,"name":"孙七"}',   '2026-02-01 08:45:00', '2026-02-01 08:45:00'),
(29, 'PAY-2025-00029',   190.90, 'DEBIT_CARD',  'SUCCESS', 'TXN-20260220133000', '{"user_id":2,"name":"李四"}',   '2026-02-20 13:30:00', '2026-02-20 13:30:00'),
(30, 'PAY-2025-00030',  9373.00, 'WECHAT',      'PENDING', NULL,                 '{"user_id":8,"name":"郑十"}',   NULL,                    '2026-03-01 16:00:00');
