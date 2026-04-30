-- 创建在线教育平台数据库
CREATE DATABASE IF NOT EXISTS online_edu_bi_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE online_edu_bi_test;

-- 1. 用户表（学生、教师、管理员）
CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '用户ID，主键，自增长',
    user_code VARCHAR(30) UNIQUE NOT NULL COMMENT '用户编号',
    username VARCHAR(50) NOT NULL COMMENT '用户名',
    email VARCHAR(100) UNIQUE NOT NULL COMMENT '邮箱',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    user_type ENUM('student', 'teacher', 'admin', 'assistant') NOT NULL COMMENT '用户类型',
    real_name VARCHAR(100) NOT NULL COMMENT '真实姓名',
    gender ENUM('male', 'female', 'other') COMMENT '性别',
    birth_date DATE COMMENT '出生日期',
    phone VARCHAR(20) COMMENT '联系电话',
    avatar_url VARCHAR(500) COMMENT '头像URL',
    bio TEXT COMMENT '个人简介',
    level INT DEFAULT 1 COMMENT '用户等级',
    points INT DEFAULT 0 COMMENT '积分',
    registration_date DATE NOT NULL COMMENT '注册日期',
    last_login_time DATETIME COMMENT '最后登录时间',
    status ENUM('active', 'inactive', 'banned', 'graduated') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user_type (user_type),
    INDEX idx_registration_date (registration_date)
) COMMENT = '用户基本信息表';

-- 2. 学校/机构表
CREATE TABLE institutions (
    institution_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '机构ID',
    institution_code VARCHAR(30) UNIQUE NOT NULL COMMENT '机构编码',
    institution_name VARCHAR(200) NOT NULL COMMENT '机构名称',
    institution_type ENUM('university', 'college', 'training_school', 'online_platform', 'other') NOT NULL COMMENT '机构类型',
    location VARCHAR(200) COMMENT '所在地',
    website VARCHAR(200) COMMENT '官方网站',
    contact_phone VARCHAR(20) COMMENT '联系电话',
    contact_email VARCHAR(100) COMMENT '联系邮箱',
    description TEXT COMMENT '机构描述',
    established_year YEAR COMMENT '成立年份',
    status ENUM('active', 'inactive', 'pending') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT = '教育机构表';

-- 3. 课程分类表
CREATE TABLE course_categories (
    category_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '分类ID',
    category_code VARCHAR(30) UNIQUE NOT NULL COMMENT '分类编码',
    category_name VARCHAR(100) NOT NULL COMMENT '分类名称',
    parent_category_id INT NULL COMMENT '父分类ID',
    description TEXT COMMENT '分类描述',
    sort_order INT DEFAULT 0 COMMENT '排序顺序',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    FOREIGN KEY (parent_category_id) REFERENCES course_categories(category_id) ON DELETE SET NULL,
    INDEX idx_parent_category (parent_category_id)
) COMMENT = '课程分类表';

-- 4. 课程表
CREATE TABLE courses (
    course_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '课程ID',
    course_code VARCHAR(50) UNIQUE NOT NULL COMMENT '课程编码',
    course_name VARCHAR(200) NOT NULL COMMENT '课程名称',
    institution_id INT COMMENT '所属机构ID',
    category_id INT NOT NULL COMMENT '课程分类ID',
    teacher_id INT NOT NULL COMMENT '主讲教师ID',
    course_type ENUM('live', 'recorded', 'hybrid', 'self_paced') NOT NULL COMMENT '课程类型',
    level ENUM('beginner', 'intermediate', 'advanced', 'all_levels') DEFAULT 'beginner' COMMENT '难度等级',
    language ENUM('chinese', 'english', 'japanese', 'korean', 'other') DEFAULT 'chinese' COMMENT '授课语言',
    description TEXT NOT NULL COMMENT '课程描述',
    learning_outcomes TEXT COMMENT '学习成果',
    prerequisites TEXT COMMENT '先修要求',
    total_hours DECIMAL(6,2) DEFAULT 0 COMMENT '总课时数',
    total_students INT DEFAULT 0 COMMENT '报名学生数',
    max_students INT COMMENT '最大学生数',
    price DECIMAL(10,2) DEFAULT 0.00 COMMENT '课程价格',
    discount_price DECIMAL(10,2) COMMENT '折扣价格',
    start_date DATE COMMENT '开课日期',
    end_date DATE COMMENT '结课日期',
    enrollment_deadline DATE COMMENT '报名截止日期',
    cover_image_url VARCHAR(500) COMMENT '封面图片URL',
    avg_rating DECIMAL(3,2) DEFAULT 0.00 COMMENT '平均评分',
    review_count INT DEFAULT 0 COMMENT '评价数量',
    completion_rate DECIMAL(5,2) DEFAULT 0.00 COMMENT '完课率',
    status ENUM('draft', 'published', 'enrolling', 'ongoing', 'ended', 'archived') DEFAULT 'draft' COMMENT '课程状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (institution_id) REFERENCES institutions(institution_id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES course_categories(category_id) ON DELETE RESTRICT,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id) ON DELETE RESTRICT,
    INDEX idx_course_status (status),
    INDEX idx_start_date (start_date),
    INDEX idx_teacher_id (teacher_id)
) COMMENT = '课程主表';

-- 5. 课程章节表
CREATE TABLE course_chapters (
    chapter_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '章节ID',
    course_id INT NOT NULL COMMENT '所属课程ID',
    chapter_number INT NOT NULL COMMENT '章节序号',
    chapter_title VARCHAR(200) NOT NULL COMMENT '章节标题',
    chapter_description TEXT COMMENT '章节描述',
    estimated_hours DECIMAL(5,2) DEFAULT 0 COMMENT '预计学习时长（小时）',
    is_free BOOLEAN DEFAULT FALSE COMMENT '是否免费',
    sort_order INT DEFAULT 0 COMMENT '排序顺序',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    UNIQUE KEY uk_course_chapter (course_id, chapter_number),
    INDEX idx_course_id (course_id)
) COMMENT = '课程章节表';

-- 6. 课程资源表
CREATE TABLE course_resources (
    resource_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '资源ID',
    chapter_id INT NOT NULL COMMENT '所属章节ID',
    resource_type ENUM('video', 'document', 'quiz', 'assignment', 'link', 'other') NOT NULL COMMENT '资源类型',
    resource_title VARCHAR(200) NOT NULL COMMENT '资源标题',
    resource_url VARCHAR(500) NOT NULL COMMENT '资源URL',
    resource_duration INT COMMENT '资源时长（秒，针对视频）',
    file_size BIGINT COMMENT '文件大小（字节）',
    download_count INT DEFAULT 0 COMMENT '下载次数',
    view_count INT DEFAULT 0 COMMENT '观看/查看次数',
    is_preview BOOLEAN DEFAULT FALSE COMMENT '是否可预览',
    sort_order INT DEFAULT 0 COMMENT '排序顺序',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (chapter_id) REFERENCES course_chapters(chapter_id) ON DELETE CASCADE,
    INDEX idx_chapter_id (chapter_id),
    INDEX idx_resource_type (resource_type)
) COMMENT = '课程资源表';

-- 7. 学生选课表
CREATE TABLE enrollments (
    enrollment_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '选课ID',
    student_id INT NOT NULL COMMENT '学生ID',
    course_id INT NOT NULL COMMENT '课程ID',
    enrollment_date DATETIME NOT NULL COMMENT '选课时间',
    enrollment_type ENUM('free', 'paid', 'trial', 'scholarship') NOT NULL COMMENT '选课类型',
    payment_amount DECIMAL(10,2) DEFAULT 0.00 COMMENT '支付金额',
    payment_status ENUM('pending', 'paid', 'refunded', 'free') DEFAULT 'pending' COMMENT '支付状态',
    certificate_issued BOOLEAN DEFAULT FALSE COMMENT '是否已发放证书',
    certificate_issue_date DATE COMMENT '证书发放日期',
    enrollment_status ENUM('active', 'completed', 'dropped', 'suspended') DEFAULT 'active' COMMENT '选课状态',
    completed_date DATE COMMENT '完成日期',
    progress_percentage DECIMAL(5,2) DEFAULT 0.00 COMMENT '学习进度百分比',
    last_access_time DATETIME COMMENT '最后访问时间',
    total_study_hours DECIMAL(8,2) DEFAULT 0 COMMENT '总学习时长（小时）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    UNIQUE KEY uk_student_course (student_id, course_id),
    INDEX idx_enrollment_date (enrollment_date),
    INDEX idx_enrollment_status (enrollment_status)
) COMMENT = '学生选课记录表';

-- 8. 学习进度表
CREATE TABLE learning_progress (
    progress_id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '进度ID',
    enrollment_id INT NOT NULL COMMENT '选课ID',
    resource_id INT NOT NULL COMMENT '资源ID',
    start_time DATETIME COMMENT '开始学习时间',
    end_time DATETIME COMMENT '结束学习时间',
    study_duration_seconds INT DEFAULT 0 COMMENT '学习时长（秒）',
    completion_status ENUM('not_started', 'in_progress', 'completed', 'skipped') DEFAULT 'not_started' COMMENT '完成状态',
    quiz_score DECIMAL(5,2) COMMENT '测验得分（如果有）',
    assignment_submitted BOOLEAN DEFAULT FALSE COMMENT '作业是否已提交',
    assignment_score DECIMAL(5,2) COMMENT '作业得分',
    notes TEXT COMMENT '学习笔记',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id) ON DELETE CASCADE,
    FOREIGN KEY (resource_id) REFERENCES course_resources(resource_id) ON DELETE CASCADE,
    UNIQUE KEY uk_enrollment_resource (enrollment_id, resource_id),
    INDEX idx_completion_status (completion_status)
) COMMENT = '学习进度跟踪表';

-- 9. 课程评价表
CREATE TABLE course_reviews (
    review_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '评价ID',
    enrollment_id INT NOT NULL COMMENT '选课ID',
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5) COMMENT '评分（1-5星）',
    review_title VARCHAR(200) COMMENT '评价标题',
    review_content TEXT NOT NULL COMMENT '评价内容',
    is_anonymous BOOLEAN DEFAULT FALSE COMMENT '是否匿名',
    helpful_count INT DEFAULT 0 COMMENT '有帮助的投票数',
    reply_content TEXT COMMENT '教师回复内容',
    reply_time DATETIME COMMENT '回复时间',
    status ENUM('pending', 'published', 'hidden', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id) ON DELETE CASCADE,
    UNIQUE KEY uk_enrollment_review (enrollment_id),
    INDEX idx_rating (rating),
    INDEX idx_created_at (created_at)
) COMMENT = '课程评价表';

-- 10. 直播课程表
CREATE TABLE live_sessions (
    session_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '直播会话ID',
    course_id INT NOT NULL COMMENT '课程ID',
    session_title VARCHAR(200) NOT NULL COMMENT '直播标题',
    session_description TEXT COMMENT '直播描述',
    teacher_id INT NOT NULL COMMENT '主讲教师ID',
    assistant_ids JSON COMMENT '助教ID数组',
    start_time DATETIME NOT NULL COMMENT '开始时间',
    end_time DATETIME NOT NULL COMMENT '结束时间',
    actual_start_time DATETIME COMMENT '实际开始时间',
    actual_end_time DATETIME COMMENT '实际结束时间',
    live_url VARCHAR(500) COMMENT '直播URL',
    recording_url VARCHAR(500) COMMENT '录播URL',
    max_attendees INT COMMENT '最大参与人数',
    attendees_count INT DEFAULT 0 COMMENT '实际参与人数',
    avg_watch_duration_minutes INT COMMENT '平均观看时长（分钟）',
    interaction_count INT DEFAULT 0 COMMENT '互动次数',
    status ENUM('scheduled', 'live', 'ended', 'cancelled', 'recorded') DEFAULT 'scheduled' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id) ON DELETE RESTRICT,
    INDEX idx_start_time (start_time),
    INDEX idx_session_status (status)
) COMMENT = '直播课程安排表';




-- 11. 证书管理表
CREATE TABLE certificates (
    certificate_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '证书ID',
    certificate_code VARCHAR(50) UNIQUE NOT NULL COMMENT '证书编号',
    enrollment_id INT NOT NULL COMMENT '关联选课记录ID',
    student_id INT NOT NULL COMMENT '学生ID',
    course_id INT NOT NULL COMMENT '课程ID',
    certificate_title VARCHAR(200) NOT NULL COMMENT '证书标题',
    issue_date DATE NOT NULL COMMENT '颁发日期',
    expiry_date DATE COMMENT '有效期至（可为空表示永久有效）',
    certificate_url VARCHAR(500) NOT NULL COMMENT '证书文件URL',
    verification_code VARCHAR(100) UNIQUE COMMENT '验证码',
    issuer_institution_id INT COMMENT '颁发机构ID',
    status ENUM('valid', 'expired', 'revoked', 'pending') DEFAULT 'valid' COMMENT '证书状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    FOREIGN KEY (issuer_institution_id) REFERENCES institutions(institution_id) ON DELETE SET NULL,
    INDEX idx_issue_date (issue_date),
    INDEX idx_certificate_status (status)
) COMMENT = '证书颁发与管理表';

-- 12. 优惠活动表
CREATE TABLE promotions (
    promotion_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '活动ID',
    promotion_code VARCHAR(50) UNIQUE NOT NULL COMMENT '活动编码',
    promotion_name VARCHAR(200) NOT NULL COMMENT '活动名称',
    promotion_type ENUM('discount', 'coupon', 'group_buying', 'flash_sale', 'free_trial') NOT NULL COMMENT '活动类型',
    discount_type ENUM('percentage', 'fixed_amount', 'free_course') COMMENT '折扣类型',
    discount_value DECIMAL(10,2) COMMENT '折扣值',
    applicable_course_ids JSON COMMENT '适用课程ID列表',
    applicable_category_ids JSON COMMENT '适用分类ID列表',
    min_order_amount DECIMAL(10,2) COMMENT '最低订单金额',
    usage_limit INT COMMENT '使用次数限制',
    used_count INT DEFAULT 0 COMMENT '已使用次数',
    start_time DATETIME NOT NULL COMMENT '开始时间',
    end_time DATETIME NOT NULL COMMENT '结束时间',
    status ENUM('pending', 'active', 'ended', 'cancelled') DEFAULT 'pending' COMMENT '活动状态',
    created_by INT COMMENT '创建人ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL,
    INDEX idx_promotion_time (start_time, end_time),
    INDEX idx_promotion_status (status)
) COMMENT = '营销优惠活动表';

-- 13. 订单支付表
CREATE TABLE payments (
    payment_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '支付记录ID',
    payment_no VARCHAR(50) UNIQUE NOT NULL COMMENT '支付订单号',
    enrollment_id INT NOT NULL COMMENT '关联选课ID',
    student_id INT NOT NULL COMMENT '学生ID',
    total_amount DECIMAL(10,2) NOT NULL COMMENT '订单总金额',
    discount_amount DECIMAL(10,2) DEFAULT 0.00 COMMENT '折扣金额',
    actual_amount DECIMAL(10,2) NOT NULL COMMENT '实际支付金额',
    payment_method ENUM('alipay', 'wechat_pay', 'bank_card', 'wallet', 'other') NOT NULL COMMENT '支付方式',
    payment_channel VARCHAR(100) COMMENT '支付渠道',
    transaction_no VARCHAR(100) COMMENT '第三方交易号',
    payment_status ENUM('pending', 'paid', 'failed', 'refunded', 'cancelled') DEFAULT 'pending' COMMENT '支付状态',
    paid_time DATETIME COMMENT '支付时间',
    refund_time DATETIME COMMENT '退款时间',
    refund_amount DECIMAL(10,2) DEFAULT 0.00 COMMENT '退款金额',
    promotion_id INT COMMENT '使用的优惠活动ID',
    payment_notes TEXT COMMENT '支付备注',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (promotion_id) REFERENCES promotions(promotion_id) ON DELETE SET NULL,
    INDEX idx_payment_status (payment_status),
    INDEX idx_paid_time (paid_time)
) COMMENT = '订单支付明细表';

-- 14. 问答讨论表
CREATE TABLE qa_discussions (
    discussion_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '讨论ID',
    course_id INT NOT NULL COMMENT '课程ID',
    chapter_id INT COMMENT '章节ID（可选）',
    resource_id INT COMMENT '资源ID（可选）',
    student_id INT NOT NULL COMMENT '提问学生ID',
    title VARCHAR(200) NOT NULL COMMENT '问题标题',
    content TEXT NOT NULL COMMENT '问题内容',
    question_type ENUM('general', 'technical', 'assignment', 'exam', 'other') DEFAULT 'general' COMMENT '问题类型',
    is_anonymous BOOLEAN DEFAULT FALSE COMMENT '是否匿名',
    view_count INT DEFAULT 0 COMMENT '查看次数',
    reply_count INT DEFAULT 0 COMMENT '回复数量',
    like_count INT DEFAULT 0 COMMENT '点赞数',
    is_resolved BOOLEAN DEFAULT FALSE COMMENT '是否已解决',
    resolved_by INT COMMENT '解决人ID',
    resolved_time DATETIME COMMENT '解决时间',
    status ENUM('open', 'closed', 'archived') DEFAULT 'open' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES course_chapters(chapter_id) ON DELETE SET NULL,
    FOREIGN KEY (resource_id) REFERENCES course_resources(resource_id) ON DELETE SET NULL,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_by) REFERENCES users(user_id) ON DELETE SET NULL,
    INDEX idx_course_discussion (course_id, created_at),
    INDEX idx_is_resolved (is_resolved)
) COMMENT = '课程问答讨论表';

-- 15. 讨论回复表
CREATE TABLE discussion_replies (
    reply_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '回复ID',
    discussion_id INT NOT NULL COMMENT '所属讨论ID',
    user_id INT NOT NULL COMMENT '回复用户ID',
    parent_reply_id INT COMMENT '父回复ID（用于构建回复树）',
    content TEXT NOT NULL COMMENT '回复内容',
    is_teacher_reply BOOLEAN DEFAULT FALSE COMMENT '是否是教师回复',
    is_best_answer BOOLEAN DEFAULT FALSE COMMENT '是否是最佳答案',
    like_count INT DEFAULT 0 COMMENT '点赞数',
    reply_to_user_id INT COMMENT '回复给哪个用户',
    status ENUM('normal', 'deleted', 'hidden') DEFAULT 'normal' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (discussion_id) REFERENCES qa_discussions(discussion_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_reply_id) REFERENCES discussion_replies(reply_id) ON DELETE CASCADE,
    FOREIGN KEY (reply_to_user_id) REFERENCES users(user_id) ON DELETE SET NULL,
    INDEX idx_discussion_replies (discussion_id, created_at),
    INDEX idx_is_best_answer (is_best_answer)
) COMMENT = '讨论回复表';

-- 16. 学习计划表
CREATE TABLE study_plans (
    plan_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '学习计划ID',
    student_id INT NOT NULL COMMENT '学生ID',
    plan_name VARCHAR(200) NOT NULL COMMENT '计划名称',
    description TEXT COMMENT '计划描述',
    start_date DATE NOT NULL COMMENT '开始日期',
    end_date DATE COMMENT '结束日期',
    target_hours_per_week DECIMAL(5,2) COMMENT '每周目标学习时长',
    status ENUM('active', 'completed', 'paused', 'abandoned') DEFAULT 'active' COMMENT '计划状态',
    actual_completion_date DATE COMMENT '实际完成日期',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_student_plan (student_id, status),
    INDEX idx_plan_dates (start_date, end_date)
) COMMENT = '个人学习计划表';

-- 17. 学习计划详情表
CREATE TABLE study_plan_details (
    plan_detail_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '计划详情ID',
    plan_id INT NOT NULL COMMENT '学习计划ID',
    course_id INT NOT NULL COMMENT '课程ID',
    enrollment_id INT COMMENT '关联选课记录ID',
    target_completion_date DATE COMMENT '目标完成日期',
    priority_level ENUM('high', 'medium', 'low') DEFAULT 'medium' COMMENT '优先级',
    current_progress DECIMAL(5,2) DEFAULT 0 COMMENT '当前进度',
    status ENUM('pending', 'in_progress', 'completed', 'delayed') DEFAULT 'pending' COMMENT '状态',
    notes TEXT COMMENT '备注',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (plan_id) REFERENCES study_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id) ON DELETE SET NULL,
    INDEX idx_plan_course (plan_id, course_id),
    UNIQUE KEY uk_plan_course (plan_id, course_id)
) COMMENT = '学习计划详情表';

-- 18. 系统通知表
CREATE TABLE system_notifications (
    notification_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '通知ID',
    notification_type ENUM('course_update', 'live_reminder', 'assignment_due', 'new_message', 'system_announcement', 'certificate_issued') NOT NULL COMMENT '通知类型',
    title VARCHAR(200) NOT NULL COMMENT '通知标题',
    content TEXT NOT NULL COMMENT '通知内容',
    target_user_id INT COMMENT '目标用户ID（NULL表示广播给所有用户）',
    related_course_id INT COMMENT '关联课程ID',
    related_resource_id INT COMMENT '关联资源ID',
    related_live_session_id INT COMMENT '关联直播ID',
    is_read BOOLEAN DEFAULT FALSE COMMENT '是否已读',
    is_urgent BOOLEAN DEFAULT FALSE COMMENT '是否紧急',
    scheduled_send_time DATETIME COMMENT '计划发送时间',
    actual_send_time DATETIME COMMENT '实际发送时间',
    expiry_time DATETIME COMMENT '过期时间',
    status ENUM('draft', 'scheduled', 'sent', 'cancelled', 'failed') DEFAULT 'draft' COMMENT '状态',
    created_by INT COMMENT '创建人ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (target_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (related_course_id) REFERENCES courses(course_id) ON DELETE SET NULL,
    FOREIGN KEY (related_resource_id) REFERENCES course_resources(resource_id) ON DELETE SET NULL,
    FOREIGN KEY (related_live_session_id) REFERENCES live_sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL,
    INDEX idx_notification_status (status),
    INDEX idx_target_user (target_user_id, is_read),
    INDEX idx_send_time (scheduled_send_time)
) COMMENT = '系统通知管理表';

-- 19. 用户消息表
CREATE TABLE user_messages (
    message_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '消息ID',
    sender_id INT NOT NULL COMMENT '发送者ID',
    receiver_id INT NOT NULL COMMENT '接收者ID',
    message_type ENUM('text', 'image', 'file', 'audio', 'system') DEFAULT 'text' COMMENT '消息类型',
    content TEXT NOT NULL COMMENT '消息内容',
    attachment_url VARCHAR(500) COMMENT '附件URL',
    is_read BOOLEAN DEFAULT FALSE COMMENT '是否已读',
    read_time DATETIME COMMENT '阅读时间',
    parent_message_id INT COMMENT '父消息ID（用于会话线程）',
    conversation_id VARCHAR(100) COMMENT '会话ID',
    status ENUM('sent', 'delivered', 'read', 'failed') DEFAULT 'sent' COMMENT '消息状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_message_id) REFERENCES user_messages(message_id) ON DELETE SET NULL,
    INDEX idx_conversation (sender_id, receiver_id, created_at),
    INDEX idx_message_status (status),
    INDEX idx_is_read (is_read, receiver_id)
) COMMENT = '用户私信消息表';

-- 20. 学习数据统计表（每日快照）
CREATE TABLE learning_statistics_daily (
    stat_id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '统计ID',
    stat_date DATE NOT NULL COMMENT '统计日期',
    user_id INT NOT NULL COMMENT '用户ID',
    course_id INT COMMENT '课程ID（可选）',
    total_study_minutes INT DEFAULT 0 COMMENT '总学习时长（分钟）',
    completed_resources INT DEFAULT 0 COMMENT '完成资源数',
    quiz_attempts INT DEFAULT 0 COMMENT '测验尝试次数',
    avg_quiz_score DECIMAL(5,2) COMMENT '平均测验得分',
    assignment_submissions INT DEFAULT 0 COMMENT '作业提交次数',
    discussion_posts INT DEFAULT 0 COMMENT '讨论发帖数',
    discussion_replies INT DEFAULT 0 COMMENT '讨论回复数',
    points_earned INT DEFAULT 0 COMMENT '获得积分',
    level_up BOOLEAN DEFAULT FALSE COMMENT '是否升级',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE KEY uk_daily_stat (stat_date, user_id, course_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE SET NULL,
    INDEX idx_stat_date (stat_date),
    INDEX idx_user_learning (user_id, stat_date)
) COMMENT = '每日学习数据统计表（用于BI分析）';




-- 先清理现有数据（如果存在）
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE learning_statistics_daily;
TRUNCATE TABLE user_messages;
TRUNCATE TABLE system_notifications;
TRUNCATE TABLE study_plan_details;
TRUNCATE TABLE study_plans;
TRUNCATE TABLE discussion_replies;
TRUNCATE TABLE qa_discussions;
TRUNCATE TABLE payments;
TRUNCATE TABLE promotions;
TRUNCATE TABLE certificates;
TRUNCATE TABLE live_sessions;
TRUNCATE TABLE course_reviews;
TRUNCATE TABLE learning_progress;
TRUNCATE TABLE enrollments;
TRUNCATE TABLE course_resources;
TRUNCATE TABLE course_chapters;
TRUNCATE TABLE courses;
TRUNCATE TABLE course_categories;
TRUNCATE TABLE institutions;
TRUNCATE TABLE users;
SET FOREIGN_KEY_CHECKS = 1;

-- 1. 插入机构数据
INSERT INTO institutions (institution_code, institution_name, institution_type, location, website, contact_phone, contact_email, description, established_year, status) VALUES
('EDU_001', '清华大学在线教育平台', 'university', '北京', 'https://online.tsinghua.edu.cn', '010-62780001', 'contact@tsinghua.edu.cn', '中国顶尖大学在线教育平台，提供高质量的学术课程', 2013, 'active'),
('EDU_002', '慕课网', 'online_platform', '北京', 'https://www.imooc.com', '400-800-8800', 'service@imooc.com', '领先的IT技能学习平台，专注于编程和数字技能', 2013, 'active'),
('EDU_003', '腾讯课堂', 'online_platform', '深圳', 'https://ke.qq.com', '0755-86013388', 'support@ke.qq.com', '腾讯旗下综合性在线终身教育平台', 2014, 'active'),
('EDU_004', '新东方在线', 'training_school', '北京', 'https://www.koolearn.com', '010-62605555', 'service@koolearn.com', '中国领先的在线教育服务提供商，涵盖多个学科', 2005, 'active'),
('EDU_005', '中国大学MOOC', 'online_platform', '北京', 'https://www.icourse163.org', '010-82345300', 'support@icourse163.org', '教育部精品在线开放课程平台', 2014, 'active'),
('EDU_006', '北京大学在线教育', 'university', '北京', 'https://online.pku.edu.cn', '010-62750001', 'contact@pku.edu.cn', '北京大学官方在线教育平台', 2014, 'active'),
('EDU_007', '网易云课堂', 'online_platform', '杭州', 'https://study.163.com', '0571-89853333', 'support@study.163.com', '网易旗下实用技能学习平台', 2012, 'active'),
('EDU_008', '好未来在线', 'training_school', '北京', 'https://www.100tal.com', '010-59320000', 'service@100tal.com', '好未来教育科技集团在线教育平台', 2010, 'active'),
('EDU_009', '学堂在线', 'online_platform', '北京', 'https://www.xuetangx.com', '010-62780002', 'support@xuetangx.com', '清华大学发起的在线教育平台', 2013, 'active'),
('EDU_010', '华图教育在线', 'training_school', '北京', 'https://online.htexam.com', '010-83421888', 'service@htexam.com', '公务员考试培训领先机构在线平台', 2012, 'active');

-- 2. 插入用户数据
INSERT INTO users (user_code, username, email, password_hash, user_type, real_name, gender, birth_date, phone, avatar_url, bio, level, points, registration_date, last_login_time, status) VALUES
-- 管理员用户
('ADMIN_001', 'admin_li', 'admin.li@edu.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'admin', '李管理员', 'male', '1985-03-15', '13800138000', 'https://cdn.edu.com/avatars/admin1.jpg', '平台总负责人，负责系统管理和运营', 10, 5000, '2020-01-15', '2024-03-20 14:30:00', 'active'),
('ADMIN_002', 'admin_wang', 'admin.wang@edu.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'admin', '王管理员', 'female', '1988-07-22', '13900139000', 'https://cdn.edu.com/avatars/admin2.jpg', '内容审核和用户管理负责人', 9, 4200, '2020-03-10', '2024-03-21 10:15:00', 'active'),

-- 教师用户
('TCH_001', 'prof_zhang', 'zhangwei@tsinghua.edu.cn', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '张伟', 'male', '1975-05-20', '13811112222', 'https://cdn.edu.com/avatars/tch1.jpg', '清华大学计算机系教授，博士生导师，擅长Python和机器学习', 5, 2850, '2021-01-15', '2024-03-22 09:45:00', 'active'),
('TCH_002', 'teacher_li', 'lina@imooc.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '李娜', 'female', '1985-08-12', '13911113333', 'https://cdn.edu.com/avatars/tch2.jpg', '数据科学家，前阿里巴巴数据分析师，擅长数据可视化和机器学习', 4, 1920, '2021-02-20', '2024-03-21 15:20:00', 'active'),
('TCH_003', 'dr_wang', 'wanggang@tsinghua.edu.cn', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '王刚', 'male', '1978-11-30', '13711114444', 'https://cdn.edu.com/avatars/tch3.jpg', '人工智能专家，深度学习领域研究者，发表多篇顶会论文', 5, 3180, '2021-03-10', '2024-03-22 11:10:00', 'active'),
('TCH_004', 'prof_chen', 'chenfang@tencent.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '陈芳', 'female', '1982-04-18', '13611115555', 'https://cdn.edu.com/avatars/tch4.jpg', '腾讯高级UI设计师，10年设计经验，多个获奖作品', 4, 1760, '2021-04-05', '2024-03-20 14:05:00', 'active'),
('TCH_005', 'expert_zhou', 'zhouhong@neworiental.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '周红', 'female', '1979-09-25', '13511116666', 'https://cdn.edu.com/avatars/tch5.jpg', '数字营销专家，15年市场营销经验，服务多家世界500强企业', 5, 2450, '2021-05-12', '2024-03-21 16:30:00', 'active'),
('TCH_006', 'prof_zhao', 'zhaoming@pku.edu.cn', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '赵明', 'male', '1972-12-05', '13411117777', 'https://cdn.edu.com/avatars/tch6.jpg', '北京大学金融学教授，投资理财专家', 5, 2100, '2021-06-08', '2024-03-22 10:45:00', 'active'),
('TCH_007', 'engineer_qian', 'qianjun@netease.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '钱军', 'male', '1988-03-14', '13311118888', 'https://cdn.edu.com/avatars/tch7.jpg', '网易高级前端工程师，8年开发经验，React专家', 4, 1890, '2021-07-15', '2024-03-20 13:20:00', 'active'),
('TCH_008', 'designer_sun', 'sunli@tencent.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'teacher', '孙丽', 'female', '1990-07-08', '13211119999', 'https://cdn.edu.com/avatars/tch8.jpg', '腾讯视觉设计师，擅长平面设计和品牌视觉', 3, 1560, '2021-08-20', '2024-03-21 14:15:00', 'active'),

-- 助教用户
('AST_001', 'assistant_liu', 'liuhua@edu.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'assistant', '刘华', 'male', '1995-02-28', '13122220001', 'https://cdn.edu.com/avatars/ast1.jpg', 'Python课程助教，计算机专业研究生', 3, 850, '2022-03-01', '2024-03-22 08:30:00', 'active'),
('AST_002', 'assistant_ma', 'maying@edu.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'assistant', '马颖', 'female', '1996-06-15', '13122220002', 'https://cdn.edu.com/avatars/ast2.jpg', '数据科学课程助教，统计学硕士', 3, 920, '2022-03-05', '2024-03-21 09:15:00', 'active'),

-- 学生用户（2023年）
('STU_2301', 'zhangsan_2023', 'zhangsan@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '张三', 'male', '2000-01-10', '13800138001', 'https://cdn.edu.com/avatars/stu1.jpg', '计算机专业大三学生，热爱编程', 2, 420, '2023-01-05', '2024-03-22 19:30:00', 'active'),
('STU_2302', 'lisi_study', 'lisi@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '李四', 'female', '1999-03-25', '13800138002', 'https://cdn.edu.com/avatars/stu2.jpg', '数据分析师，希望提升数据科学技能', 3, 680, '2023-01-12', '2024-03-21 20:15:00', 'active'),
('STU_2303', 'wangwu_code', 'wangwu@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '王五', 'male', '2001-07-15', '13800138003', 'https://cdn.edu.com/avatars/stu3.jpg', '前端开发工程师，2年工作经验', 4, 950, '2023-02-08', '2024-03-22 21:00:00', 'active'),
('STU_2304', 'zhaoliu_ai', 'zhaoliu@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '赵六', 'female', '1998-11-20', '13800138004', 'https://cdn.edu.com/avatars/stu4.jpg', 'AI研究员，专注于深度学习', 5, 1250, '2023-02-15', '2024-03-20 22:10:00', 'active'),
('STU_2305', 'chenmeng_design', 'chenmeng@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '陈梦', 'female', '2000-05-30', '13800138005', 'https://cdn.edu.com/avatars/stu5.jpg', 'UI设计师，希望提升设计技能', 3, 580, '2023-03-10', '2024-03-21 19:45:00', 'active'),
('STU_2306', 'liuqiang_tech', 'liuqiang@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '刘强', 'male', '1997-09-05', '13800138006', 'https://cdn.edu.com/avatars/stu6.jpg', '全栈工程师，5年工作经验', 5, 1450, '2023-03-18', '2024-03-22 18:20:00', 'active'),
('STU_2307', 'sunyang_business', 'sunyang@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '孙阳', 'male', '1996-12-12', '13800138007', 'https://cdn.edu.com/avatars/stu7.jpg', '产品经理，希望了解技术实现', 2, 350, '2023-04-01', '2024-03-20 20:30:00', 'active'),
('STU_2308', 'zhoufang_study', 'zhoufang@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '周芳', 'female', '1999-04-18', '13800138008', 'https://cdn.edu.com/avatars/stu8.jpg', '市场营销专员，学习数字营销', 3, 620, '2023-04-10', '2024-03-21 21:15:00', 'active'),
('STU_2309', 'wubin_dev', 'wubin@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '吴斌', 'male', '2002-02-22', '13800138009', 'https://cdn.edu.com/avatars/stu9.jpg', '计算机科学研究生', 4, 880, '2023-05-05', '2024-03-22 22:45:00', 'active'),
('STU_2310', 'zhenghua_data', 'zhenghua@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '郑华', 'female', '2000-08-08', '13800138010', 'https://cdn.edu.com/avatars/stu10.jpg', '统计学本科生，学习数据科学', 2, 410, '2023-05-15', '2024-03-20 19:20:00', 'active'),
('STU_2311', 'qianwei_ml', 'qianwei@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '钱伟', 'male', '1998-06-30', '13800138011', 'https://cdn.edu.com/avatars/stu11.jpg', '机器学习工程师', 5, 1320, '2023-06-01', '2024-03-21 18:40:00', 'active'),
('STU_2312', 'fengli_design', 'fengli@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '冯丽', 'female', '1997-03-14', '13800138012', 'https://cdn.edu.com/avatars/stu12.jpg', '平面设计师，学习UI设计', 4, 920, '2023-06-10', '2024-03-22 20:10:00', 'active'),
('STU_2313', 'guoyang_cloud', 'guoyang@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '郭阳', 'male', '2001-10-25', '13800138013', 'https://cdn.edu.com/avatars/stu13.jpg', '云计算初学者', 1, 180, '2023-07-05', '2024-03-20 21:50:00', 'active'),
('STU_2314', 'maying_finance', 'maying@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '马英', 'female', '1995-12-08', '13800138014', 'https://cdn.edu.com/avatars/stu14.jpg', '金融分析师，学习投资理财', 3, 640, '2023-07-20', '2024-03-21 22:30:00', 'active'),
('STU_2315', 'linfeng_web', 'linfeng@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '林峰', 'male', '2000-09-17', '13800138015', 'https://cdn.edu.com/avatars/stu15.jpg', 'Web开发爱好者', 2, 390, '2023-08-01', '2024-03-22 19:15:00', 'active'),
-- 2024年新注册学生
('STU_2401', 'student_hu', 'huming@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '胡明', 'male', '2002-04-10', '13800138016', 'https://cdn.edu.com/avatars/stu16.jpg', '大一新生，开始学习编程', 1, 120, '2024-01-08', '2024-03-20 20:05:00', 'active'),
('STU_2402', 'xuemei_learn', 'xuemei@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '薛梅', 'female', '1999-07-22', '13800138017', 'https://cdn.edu.com/avatars/stu17.jpg', '转行学习数据科学', 2, 280, '2024-01-15', '2024-03-21 19:30:00', 'active'),
('STU_2403', 'gaowei_designer', 'gaowei@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '高伟', 'male', '1998-11-05', '13800138018', 'https://cdn.edu.com/avatars/stu18.jpg', '学习UI设计提升职业技能', 3, 450, '2024-02-01', '2024-03-22 18:45:00', 'active'),
('STU_2404', 'fanghua_mkt', 'fanghua@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '方华', 'female', '1997-02-28', '13800138019', 'https://cdn.edu.com/avatars/stu19.jpg', '数字营销经理，学习新技能', 4, 720, '2024-02-10', '2024-03-20 21:20:00', 'active'),
('STU_2405', 'dongjian_finance', 'dongjian@email.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'student', '董健', 'male', '1996-05-15', '13800138020', 'https://cdn.edu.com/avatars/stu20.jpg', '银行职员，学习理财知识', 2, 310, '2024-03-05', '2024-03-21 20:45:00', 'active');

-- 3. 插入课程分类数据
INSERT INTO course_categories (category_code, category_name, parent_category_id, description, sort_order, is_active) VALUES
('CAT_001', '计算机科学', NULL, '计算机相关课程，涵盖编程、算法、系统等', 1, TRUE),
('CAT_002', '数据科学', 1, '数据分析、机器学习、人工智能等', 2, TRUE),
('CAT_003', '软件开发', 1, '编程语言、开发框架、软件工程等', 3, TRUE),
('CAT_004', '人工智能', 1, 'AI、深度学习、自然语言处理等', 4, TRUE),
('CAT_005', '设计创意', NULL, '设计、艺术、创意类课程', 5, TRUE),
('CAT_006', 'UI/UX设计', 5, '用户界面和用户体验设计', 6, TRUE),
('CAT_007', '平面设计', 5, '平面设计、视觉传达、品牌设计', 7, TRUE),
('CAT_008', '商业管理', NULL, '商业、管理、经济类课程', 8, TRUE),
('CAT_009', '市场营销', 8, '市场推广、品牌建设、数字营销', 9, TRUE),
('CAT_010', '金融财务', 8, '金融、投资、会计、理财', 10, TRUE),
('CAT_011', '前端开发', 3, 'HTML、CSS、JavaScript等前端技术', 11, TRUE),
('CAT_012', '后端开发', 3, '服务器端开发、数据库、API设计', 12, TRUE),
('CAT_013', '移动开发', 3, 'iOS、Android、React Native等', 13, TRUE),
('CAT_014', '云计算', 1, '云服务、容器化、DevOps', 14, TRUE),
('CAT_015', '网络安全', 1, '信息安全、网络攻防、数据安全', 15, TRUE);

-- 4. 插入课程数据
INSERT INTO courses (course_code, course_name, institution_id, category_id, teacher_id, course_type, level, language, description, learning_outcomes, prerequisites, total_hours, total_students, max_students, price, discount_price, start_date, end_date, enrollment_deadline, cover_image_url, avg_rating, review_count, completion_rate, status) VALUES
('PYTHON101', 'Python编程从入门到精通', 1, 3, 3, 'self_paced', 'beginner', 'chinese', '零基础学习Python编程，掌握核心语法和实战技能', '能够独立完成Python项目开发，掌握Web开发、数据分析基础', '无需编程基础，有计算机基本操作能力即可', 60.00, 125, 200, 399.00, 299.00, '2024-01-01', '2024-12-31', '2024-06-30', 'https://cdn.edu.com/courses/python101.jpg', 4.7, 89, 68.5, 'ongoing'),
('DS201', '数据科学实战训练营', 2, 2, 4, 'hybrid', 'intermediate', 'chinese', '系统学习数据科学全流程，掌握数据分析、机器学习技能', '能够独立完成数据分析项目，掌握常用机器学习算法', '具备Python基础，了解基本统计学知识', 80.00, 92, 150, 899.00, 699.00, '2024-02-01', '2024-08-31', '2024-04-30', 'https://cdn.edu.com/courses/ds201.jpg', 4.8, 76, 72.3, 'ongoing'),
('AI301', '深度学习与神经网络', 1, 4, 5, 'live', 'advanced', 'english', '深度学习理论与实战，掌握CNN、RNN等网络结构', '能够设计和实现深度学习模型，理解神经网络原理', '具备Python和机器学习基础，数学基础良好', 100.00, 68, 100, 1299.00, 999.00, '2024-03-01', '2024-09-30', '2024-05-15', 'https://cdn.edu.com/courses/ai301.jpg', 4.9, 45, 65.2, 'enrolling'),
('UI401', 'UI设计专业班', 3, 6, 6, 'recorded', 'beginner', 'chinese', '从零开始学习UI设计，掌握设计工具和设计思维', '能够独立完成移动端和Web端UI设计', '无需设计基础，有审美能力即可', 40.00, 156, 300, 499.00, 399.00, '2024-01-15', '2024-06-30', '2024-04-15', 'https://cdn.edu.com/courses/ui401.jpg', 4.6, 112, 75.8, 'ongoing'),
('MKT501', '数字营销策略实战', 4, 9, 7, 'hybrid', 'intermediate', 'chinese', '数字时代营销策略，掌握社交媒体、内容营销等技能', '能够制定数字营销策略，掌握营销数据分析', '具备基本商业知识，了解市场营销概念', 50.00, 108, 200, 699.00, 599.00, '2024-02-15', '2024-07-31', '2024-05-31', 'https://cdn.edu.com/courses/mkt501.jpg', 4.5, 84, 70.1, 'ongoing'),
('WEB101', 'Web前端开发全栈', 2, 11, 3, 'self_paced', 'beginner', 'chinese', 'HTML5、CSS3、JavaScript到React全栈学习', '能够独立开发响应式网站，掌握前端框架', '无需编程基础，有计算机基本操作能力', 70.00, 142, 250, 799.00, 649.00, '2024-01-10', '2024-09-30', '2024-06-30', 'https://cdn.edu.com/courses/web101.jpg', 4.7, 98, 68.9, 'ongoing'),
('FIN601', '个人投资理财入门', 5, 10, 8, 'recorded', 'beginner', 'chinese', '系统学习个人理财知识，掌握投资方法和风险控制', '能够制定个人理财计划，理解投资产品', '无需金融背景，有兴趣学习理财即可', 30.00, 210, 500, 199.00, 149.00, '2024-03-01', '2024-08-31', '2024-07-31', 'https://cdn.edu.com/courses/fin601.jpg', 4.4, 156, 80.2, 'enrolling'),
('ML401', '机器学习实战应用', 1, 2, 5, 'hybrid', 'intermediate', 'chinese', '机器学习算法原理与实战应用，包含多个项目实践', '掌握常用机器学习算法，能够解决实际问题', '具备Python和数学基础', 75.00, 87, 150, 999.00, 799.00, '2024-02-01', '2024-08-31', '2024-05-31', 'https://cdn.edu.com/courses/ml401.jpg', 4.7, 67, 71.5, 'ongoing'),
('APP501', 'React Native移动开发', 6, 13, 3, 'self_paced', 'intermediate', 'chinese', '使用React Native开发跨平台移动应用', '能够独立开发iOS和Android应用', '具备JavaScript和React基础', 65.00, 74, 120, 899.00, 749.00, '2024-03-15', '2024-10-31', '2024-06-30', 'https://cdn.edu.com/courses/app501.jpg', 4.6, 52, 64.8, 'enrolling'),
('CLOUD701', '云计算与DevOps', 7, 14, 9, 'live', 'advanced', 'chinese', '云计算架构、容器化、CI/CD全流程', '掌握云平台使用和DevOps实践', '具备Linux和网络基础', 85.00, 53, 80, 1499.00, 1199.00, '2024-04-01', '2024-11-30', '2024-06-15', 'https://cdn.edu.com/courses/cloud701.jpg', 4.8, 38, 69.3, 'enrolling'),
('DESIGN201', '平面设计大师课', 3, 7, 10, 'recorded', 'beginner', 'chinese', '学习Photoshop、Illustrator等设计软件', '能够完成海报、LOGO、宣传册等设计', '无需设计基础', 35.00, 189, 400, 399.00, 299.00, '2024-01-20', '2024-07-31', '2024-05-20', 'https://cdn.edu.com/courses/design201.jpg', 4.5, 124, 78.6, 'ongoing'),
('SEC801', '网络安全攻防实战', 8, 15, 11, 'hybrid', 'advanced', 'chinese', '学习网络安全知识，掌握攻防技术', '具备基本的安全防护能力，理解常见攻击方式', '具备计算机网络基础', 90.00, 61, 100, 1699.00, 1399.00, '2024-05-01', '2024-12-31', '2024-07-31', 'https://cdn.edu.com/courses/sec801.jpg', 4.9, 41, 66.7, 'enrolling'),
('DSA301', '数据结构与算法', 9, 1, 3, 'self_paced', 'intermediate', 'chinese', '计算机科学核心课程，掌握常用数据结构和算法', '能够分析和设计算法，准备技术面试', '具备编程基础，了解基本数学', 55.00, 96, 180, 599.00, 499.00, '2024-02-20', '2024-09-30', '2024-06-20', 'https://cdn.edu.com/courses/dsa301.jpg', 4.7, 72, 67.4, 'ongoing'),
('TEST101', '软件测试工程师', 10, 3, 12, 'recorded', 'beginner', 'chinese', '学习软件测试理论和方法，掌握自动化测试', '能够编写测试用例，使用测试工具', '具备基本计算机操作能力', 45.00, 78, 150, 499.00, 399.00, '2024-03-10', '2024-08-31', '2024-06-10', 'https://cdn.edu.com/courses/test101.jpg', 4.4, 58, 73.2, 'ongoing');

-- 由于篇幅限制，我将分批插入其他表的数据
-- 5. 插入课程章节数据（以Python课程为例）
INSERT INTO course_chapters (course_id, chapter_number, chapter_title, chapter_description, estimated_hours, is_free, sort_order) VALUES
(1, 1, 'Python基础入门', 'Python环境配置和基本语法', 8.00, TRUE, 1),
(1, 2, '数据类型和运算符', '学习Python的各种数据类型和运算符', 10.00, FALSE, 2),
(1, 3, '流程控制语句', '条件判断和循环语句', 8.00, FALSE, 3),
(1, 4, '函数和模块', '函数定义、参数传递和模块导入', 12.00, FALSE, 4),
(1, 5, '面向对象编程', '类、对象、继承和多态', 10.00, FALSE, 5),
(1, 6, '文件操作和异常处理', '文件读写和错误处理机制', 6.00, FALSE, 6),
(1, 7, 'Python标准库', '常用内置模块和第三方库', 8.00, FALSE, 7),
(1, 8, '项目实战：数据爬虫', '使用Python进行网络数据爬取', 10.00, FALSE, 8),
(1, 9, '项目实战：Web开发', '使用Flask开发简单Web应用', 12.00, FALSE, 9),
(1, 10, '项目实战：数据分析', '使用Pandas进行数据分析', 10.00, FALSE, 10);

-- 6. 插入课程资源数据（以Python第一章为例）
INSERT INTO course_resources (chapter_id, resource_type, resource_title, resource_url, resource_duration, file_size, download_count, view_count, is_preview, sort_order) VALUES
(1, 'video', 'Python安装与环境配置', 'https://cdn.edu.com/videos/python_setup.mp4', 1800, 157286400, 1250, 3560, TRUE, 1),
(1, 'document', 'Python基础语法讲义', 'https://cdn.edu.com/docs/python_basics.pdf', NULL, 5242880, 890, 2150, TRUE, 2),
(1, 'video', '第一个Python程序', 'https://cdn.edu.com/videos/first_python.mp4', 1200, 104857600, 780, 1890, TRUE, 3),
(1, 'quiz', '第一章基础测验', 'https://edu.com/quiz/python_chapter1', NULL, NULL, 0, 1420, FALSE, 4),
(1, 'document', 'Python编码规范', 'https://cdn.edu.com/docs/python_style_guide.pdf', NULL, 2097152, 650, 1670, FALSE, 5),
(1, 'assignment', '环境配置作业', 'https://edu.com/assignments/env_setup', NULL, NULL, 0, 1230, FALSE, 6),
(2, 'video', 'Python数据类型详解', 'https://cdn.edu.com/videos/python_types.mp4', 2400, 209715200, 920, 2450, FALSE, 1),
(2, 'document', '数据类型参考手册', 'https://cdn.edu.com/docs/data_types_manual.pdf', NULL, 3145728, 710, 1780, FALSE, 2),
(2, 'quiz', '数据类型测验', 'https://edu.com/quiz/data_types_quiz', NULL, NULL, 0, 1350, FALSE, 3);

-- 7. 插入选课记录（示例数据，显示完整字段）
INSERT INTO enrollments (student_id, course_id, enrollment_date, enrollment_type, payment_amount, payment_status, certificate_issued, certificate_issue_date, enrollment_status, completed_date, progress_percentage, last_access_time, total_study_hours) VALUES
(13, 1, '2024-01-02 09:30:00', 'paid', 299.00, 'paid', TRUE, '2024-03-15', 'completed', '2024-03-15', 100.00, '2024-03-22 20:15:00', 65.5),
(14, 1, '2024-01-03 14:20:00', 'paid', 299.00, 'paid', FALSE, NULL, 'active', NULL, 78.5, '2024-03-22 19:30:00', 51.2),
(15, 1, '2024-01-05 11:15:00', 'trial', 0.00, 'free', FALSE, NULL, 'active', NULL, 45.3, '2024-03-21 21:10:00', 29.8),
(16, 1, '2024-01-08 16:45:00', 'paid', 299.00, 'paid', FALSE, NULL, 'active', NULL, 62.7, '2024-03-22 18:45:00', 41.5),
(17, 1, '2024-01-10 10:30:00', 'scholarship', 0.00, 'free', FALSE, NULL, 'dropped', NULL, 25.4, '2024-02-15 14:20:00', 16.7),
(13, 2, '2024-02-02 13:25:00', 'paid', 699.00, 'paid', FALSE, NULL, 'active', NULL, 58.9, '2024-03-22 21:30:00', 47.2),
(14, 2, '2024-02-03 09:45:00', 'paid', 699.00, 'paid', FALSE, NULL, 'active', NULL, 72.3, '2024-03-21 20:15:00', 57.8),
(18, 2, '2024-02-05 15:30:00', 'paid', 699.00, 'paid', TRUE, '2024-03-20', 'completed', '2024-03-20', 100.00, '2024-03-20 16:45:00', 82.5),
(19, 2, '2024-02-08 11:20:00', 'paid', 699.00, 'paid', FALSE, NULL, 'active', NULL, 65.8, '2024-03-22 19:45:00', 52.6),
(20, 2, '2024-02-10 14:10:00', 'trial', 0.00, 'free', FALSE, NULL, 'suspended', NULL, 32.1, '2024-03-10 15:30:00', 25.7),
(15, 4, '2024-01-16 09:15:00', 'paid', 399.00, 'paid', TRUE, '2024-03-18', 'completed', '2024-03-18', 100.00, '2024-03-18 17:20:00', 42.5),
(16, 4, '2024-01-18 13:45:00', 'paid', 399.00, 'paid', FALSE, NULL, 'active', NULL, 88.7, '2024-03-22 20:30:00', 37.9),
(17, 4, '2024-01-20 10:30:00', 'paid', 399.00, 'paid', FALSE, NULL, 'active', NULL, 76.4, '2024-03-21 19:15:00', 32.5),
(21, 5, '2024-02-16 14:25:00', 'paid', 599.00, 'paid', FALSE, NULL, 'active', NULL, 54.3, '2024-03-22 21:45:00', 27.2),
(22, 5, '2024-02-18 11:10:00', 'paid', 599.00, 'paid', FALSE, NULL, 'active', NULL, 68.9, '2024-03-21 20:30:00', 34.5),
(23, 6, '2024-01-11 09:30:00', 'paid', 649.00, 'paid', TRUE, '2024-03-10', 'completed', '2024-03-10', 100.00, '2024-03-10 18:15:00', 72.5),
(24, 6, '2024-01-12 15:45:00', 'paid', 649.00, 'paid', FALSE, NULL, 'active', NULL, 82.6, '2024-03-22 22:10:00', 57.8),
(25, 6, '2024-01-14 10:20:00', 'scholarship', 0.00, 'free', FALSE, NULL, 'active', NULL, 65.4, '2024-03-21 21:45:00', 45.9),
(26, 7, '2024-03-02 13:30:00', 'paid', 149.00, 'paid', FALSE, NULL, 'active', NULL, 42.8, '2024-03-22 19:20:00', 12.8),
(27, 7, '2024-03-03 09:15:00', 'paid', 149.00, 'paid', FALSE, NULL, 'active', NULL, 58.3, '2024-03-21 18:30:00', 17.5);

-- 8. 插入学习进度记录
INSERT INTO learning_progress (enrollment_id, resource_id, start_time, end_time, study_duration_seconds, completion_status, quiz_score, assignment_submitted, assignment_score, notes) VALUES
(1, 1, '2024-01-03 09:30:00', '2024-01-03 10:00:00', 1800, 'completed', NULL, FALSE, NULL, '环境配置顺利完成'),
(1, 2, '2024-01-03 14:00:00', '2024-01-03 15:30:00', 5400, 'completed', NULL, FALSE, NULL, '语法基础很重要'),
(1, 3, '2024-01-04 10:00:00', '2024-01-04 10:30:00', 1800, 'completed', NULL, FALSE, NULL, '第一个程序运行成功'),
(1, 4, '2024-01-05 09:15:00', '2024-01-05 09:45:00', 1800, 'completed', 85.00, FALSE, NULL, '测验成绩不错'),
(1, 5, '2024-01-05 14:30:00', '2024-01-05 15:45:00', 4500, 'completed', NULL, FALSE, NULL, '编码规范需要牢记'),
(1, 6, '2024-01-06 10:00:00', '2024-01-06 11:30:00', 5400, 'completed', NULL, TRUE, 90.00, '作业完成质量高'),
(2, 1, '2024-01-04 14:30:00', '2024-01-04 15:10:00', 2400, 'completed', NULL, FALSE, NULL, '安装过程顺利'),
(2, 2, '2024-01-05 09:00:00', '2024-01-05 10:30:00', 5400, 'completed', NULL, FALSE, NULL, '需要多练习语法'),
(2, 3, '2024-01-05 14:15:00', '2024-01-05 15:00:00', 2700, 'completed', NULL, FALSE, NULL, 'Hello World!'),
(2, 4, '2024-01-06 09:30:00', '2024-01-06 10:00:00', 1800, 'completed', 78.00, FALSE, NULL, '测验有些难度'),
(2, 7, '2024-01-08 10:00:00', '2024-01-08 11:30:00', 5400, 'in_progress', NULL, FALSE, NULL, '数据类型需要重点掌握'),
(6, 1, '2024-02-03 13:45:00', '2024-02-03 14:45:00', 3600, 'completed', NULL, FALSE, NULL, 'Python基础回顾'),
(6, 2, '2024-02-04 09:30:00', '2024-02-04 11:00:00', 5400, 'completed', NULL, FALSE, NULL, '开始学习数据科学');

-- 9. 插入课程评价
INSERT INTO course_reviews (enrollment_id, rating, review_title, review_content, is_anonymous, helpful_count, reply_content, reply_time, status, created_at) VALUES
(1, 5, '非常棒的Python入门课程', '老师的讲解非常清晰，课程内容安排合理，项目实战很有帮助，完全适合零基础学习。', FALSE, 24, '谢谢你的认可！继续加油学习哦！', '2024-03-16 10:30:00', 'published', '2024-03-15 14:20:00'),
(2, 4, '课程质量不错', '内容全面，老师专业，但希望增加更多实际项目案例。', FALSE, 12, '感谢建议，我们会增加更多实战内容！', '2024-03-17 09:15:00', 'published', '2024-03-16 16:45:00'),
(11, 5, 'UI设计课程收获很大', '从零开始学习设计，现在能够独立完成UI设计项目，老师指导很有耐心。', FALSE, 18, '看到你的进步很开心！继续在设计道路上探索吧！', '2024-03-19 14:20:00', 'published', '2024-03-18 20:10:00'),
(17, 5, 'Web前端课程很实用', '学完后成功转行前端开发，课程内容紧跟技术发展趋势。', FALSE, 32, '恭喜转行成功！前端技术更新快，要继续学习哦！', '2024-03-11 11:30:00', 'published', '2024-03-10 19:45:00'),
(8, 4, '数据科学课程评价', '理论讲解清晰，但希望提供更多数据集用于练习。', TRUE, 8, '我们会补充更多实战数据集，感谢反馈！', '2024-03-21 16:20:00', 'published', '2024-03-20 21:15:00');

-- 10. 插入直播课程安排
INSERT INTO live_sessions (course_id, session_title, session_description, teacher_id, assistant_ids, start_time, end_time, actual_start_time, actual_end_time, live_url, recording_url, max_attendees, attendees_count, avg_watch_duration_minutes, interaction_count, status) VALUES
(3, '深度学习基础第一讲', '神经网络原理与基础架构', 5, '[11, 12]', '2024-03-15 19:00:00', '2024-03-15 21:00:00', '2024-03-15 19:05:00', '2024-03-15 21:10:00', 'https://live.edu.com/session/ai301_1', 'https://record.edu.com/session/ai301_1', 100, 68, 85, 156, 'ended'),
(3, '卷积神经网络详解', 'CNN原理、结构和应用', 5, '[11]', '2024-03-22 19:00:00', '2024-03-22 21:00:00', '2024-03-22 19:02:00', '2024-03-22 21:05:00', 'https://live.edu.com/session/ai301_2', 'https://record.edu.com/session/ai301_2', 100, 72, 88, 142, 'ended'),
(5, '数字营销趋势分析', '2024年数字营销最新趋势', 7, '[]', '2024-02-20 14:00:00', '2024-02-20 16:00:00', '2024-02-20 14:10:00', '2024-02-20 16:05:00', 'https://live.edu.com/session/mkt501_1', 'https://record.edu.com/session/mkt501_1', 200, 145, 92, 89, 'ended'),
(5, '社交媒体营销策略', '各大社交平台营销技巧', 7, '[12]', '2024-02-27 14:00:00', '2024-02-27 16:00:00', '2024-02-27 14:05:00', '2024-02-27 16:03:00', 'https://live.edu.com/session/mkt501_2', 'https://record.edu.com/session/mkt501_2', 200, 138, 87, 76, 'ended'),
(2, 'Pandas高级技巧', '数据清洗和分析高级方法', 4, '[11]', '2024-02-10 10:00:00', '2024-02-10 12:00:00', '2024-02-10 10:03:00', '2024-02-10 12:02:00', 'https://live.edu.com/session/ds201_1', 'https://record.edu.com/session/ds201_1', 150, 128, 95, 112, 'ended'),
(8, '机器学习项目实战', '完整机器学习项目流程', 5, '[11, 12]', '2024-03-25 19:00:00', '2024-03-25 21:00:00', NULL, NULL, 'https://live.edu.com/session/ml401_1', NULL, 150, 0, NULL, 0, 'scheduled'),
(10, '云计算架构设计', '云原生架构最佳实践', 9, '[]', '2024-04-05 14:00:00', '2024-04-05 16:00:00', NULL, NULL, 'https://live.edu.com/session/cloud701_1', NULL, 80, 0, NULL, 0, 'scheduled');

-- 继续插入其他表的数据...

-- 11. 插入证书数据
INSERT INTO certificates (certificate_code, enrollment_id, student_id, course_id, certificate_title, issue_date, expiry_date, certificate_url, verification_code, issuer_institution_id, status) VALUES
('CERT20240315001', 1, 13, 1, 'Python编程从入门到精通结业证书', '2024-03-15', '2027-03-15', 'https://cert.edu.com/certificates/20240315001.pdf', 'VER20240315001TSINGHUA', 1, 'valid'),
('CERT20240320001', 8, 18, 2, '数据科学实战训练营结业证书', '2024-03-20', '2027-03-20', 'https://cert.edu.com/certificates/20240320001.pdf', 'VER20240320001IMOOC', 2, 'valid'),
('CERT20240318001', 11, 15, 4, 'UI设计专业班结业证书', '2024-03-18', '2027-03-18', 'https://cert.edu.com/certificates/20240318001.pdf', 'VER20240318001TENCENT', 3, 'valid'),
('CERT20240310001', 17, 23, 6, 'Web前端开发全栈结业证书', '2024-03-10', '2027-03-10', 'https://cert.edu.com/certificates/20240310001.pdf', 'VER20240310001IMOOC', 2, 'valid'),
('CERT20240325001', 3, 15, 1, 'Python编程从入门到精通结业证书', '2024-03-25', '2027-03-25', 'https://cert.edu.com/certificates/20240325001.pdf', 'VER20240325001TSINGHUA', 1, 'valid');

-- 12. 插入优惠活动数据
INSERT INTO promotions (promotion_code, promotion_name, promotion_type, discount_type, discount_value, applicable_course_ids, applicable_category_ids, min_order_amount, usage_limit, used_count, start_time, end_time, status, created_by) VALUES
('SPRING2024', '春季开学季大促', 'discount', 'percentage', 20.00, '[1,2,4,5,6]', NULL, 299.00, 1000, 156, '2024-03-01 00:00:00', '2024-03-31 23:59:59', 'active', 1),
('NEWUSER100', '新用户专享券', 'coupon', 'fixed_amount', 100.00, NULL, '[1,2,3,4,5]', 199.00, 500, 243, '2024-01-01 00:00:00', '2024-12-31 23:59:59', 'active', 1),
('GROUP_DS201', '数据科学课程团购', 'group_buying', 'fixed_amount', 150.00, '[2]', NULL, 699.00, 50, 32, '2024-02-01 00:00:00', '2024-02-28 23:59:59', 'ended', 2),
('FLASH_PYTHON', 'Python限时秒杀', 'flash_sale', 'percentage', 25.00, '[1]', NULL, 299.00, 100, 87, '2024-03-15 09:00:00', '2024-03-15 18:00:00', 'ended', 3),
('FREETRIAL', '免费试学体验', 'free_trial', 'free_course', NULL, '[1,4,6,7]', NULL, 0.00, 200, 145, '2024-01-01 00:00:00', '2024-12-31 23:59:59', 'active', 1),
('SUMMER30OFF', '暑期学习季', 'discount', 'percentage', 30.00, '[8,9,10,12]', NULL, 399.00, 500, 0, '2024-06-01 00:00:00', '2024-08-31 23:59:59', 'pending', 1),
('CORPORATE50', '企业团体优惠', 'coupon', 'percentage', 50.00, NULL, '[1,2,3,8]', 1000.00, 100, 18, '2024-02-01 00:00:00', '2024-05-31 23:59:59', 'active', 2);

-- 13. 插入支付数据
INSERT INTO payments (payment_no, enrollment_id, student_id, total_amount, discount_amount, actual_amount, payment_method, payment_channel, transaction_no, payment_status, paid_time, refund_time, refund_amount, promotion_id, payment_notes) VALUES
('PAY20240102001', 1, 13, 399.00, 100.00, 299.00, 'alipay', '支付宝网页支付', '202401020001234567', 'paid', '2024-01-02 09:35:00', NULL, 0.00, 2, '新用户专享优惠'),
('PAY20240103001', 2, 14, 399.00, 79.80, 319.20, 'wechat_pay', '微信小程序支付', '420000123456789012', 'paid', '2024-01-03 14:25:00', NULL, 0.00, 1, '春季优惠活动'),
('PAY20240108001', 4, 16, 399.00, 99.75, 299.25, 'alipay', '支付宝APP支付', '202401080009876543', 'paid', '2024-01-08 16:50:00', NULL, 0.00, 1, '限时优惠'),
('PAY20240110001', 5, 17, 399.00, 0.00, 0.00, 'wallet', '平台钱包', NULL, 'paid', NULL, NULL, 0.00, 5, '奖学金免费课程'),
('PAY20240202001', 6, 13, 899.00, 179.80, 719.20, 'alipay', '支付宝网页支付', '202402020001111111', 'paid', '2024-02-02 13:30:00', NULL, 0.00, 1, '春季优惠'),
('PAY20240203001', 7, 14, 899.00, 224.75, 674.25, 'bank_card', '银联在线支付', '6228880012345678', 'paid', '2024-02-03 09:50:00', NULL, 0.00, 1, '银行卡支付'),
('PAY20240205001', 8, 18, 899.00, 134.85, 764.15, 'wechat_pay', '微信H5支付', '420000987654321098', 'paid', '2024-02-05 15:35:00', NULL, 0.00, 3, '团购优惠'),
('PAY20240116001', 11, 15, 499.00, 99.80, 399.20, 'wechat_pay', '微信小程序支付', '420000555555555555', 'paid', '2024-01-16 09:20:00', NULL, 0.00, 1, '春季优惠'),
('PAY20240111001', 17, 23, 799.00, 159.80, 639.20, 'bank_card', '银联快捷支付', '6228889999887766', 'paid', '2024-01-11 09:35:00', NULL, 0.00, 1, '前端课程优惠'),
('PAY20240302001', 19, 26, 199.00, 39.80, 159.20, 'alipay', '支付宝APP支付', '202403020003333333', 'paid', '2024-03-02 13:35:00', NULL, 0.00, 1, '理财课程优惠'),
('PAY20240303001', 20, 27, 199.00, 49.75, 149.25, 'wechat_pay', '微信小程序支付', '420000444444444444', 'paid', '2024-03-03 09:20:00', NULL, 0.00, 1, '新用户优惠');

-- 14. 插入问答讨论数据
INSERT INTO qa_discussions (course_id, chapter_id, resource_id, student_id, title, content, question_type, is_anonymous, view_count, reply_count, like_count, is_resolved, resolved_by, resolved_time, status, created_at) VALUES
(1, 1, NULL, 13, 'Python环境配置问题求助', '在Windows系统上安装Python 3.11时遇到环境变量配置问题，PATH设置后仍然无法在命令行运行python命令', 'technical', FALSE, 245, 8, 32, TRUE, 3, '2024-01-05 10:30:00', 'closed', '2024-01-04 14:20:00'),
(1, 2, 7, 14, '关于列表推导式的性能问题', '在处理大量数据时，使用列表推导式是否比传统for循环更高效？有没有具体的性能对比数据？', 'technical', FALSE, 156, 5, 18, TRUE, 11, '2024-01-10 15:20:00', 'closed', '2024-01-09 16:45:00'),
(1, 4, NULL, 15, '函数参数传递的疑问', 'Python中函数参数传递是值传递还是引用传递？传递可变对象和不可变对象有什么区别？', 'general', FALSE, 189, 6, 25, TRUE, 3, '2024-01-15 09:45:00', 'closed', '2024-01-14 21:10:00'),
(2, NULL, NULL, 13, '数据科学学习路径建议', '学完Python基础后，应该按照什么顺序学习数据科学的相关技术栈？需要重点掌握哪些库？', 'general', FALSE, 312, 12, 45, TRUE, 4, '2024-02-10 14:30:00', 'closed', '2024-02-08 10:15:00'),
(2, NULL, NULL, 18, '机器学习项目数据集', '课程提供的项目数据集较小，有没有更大规模的真实数据集可以用于练习？', 'assignment', FALSE, 128, 4, 15, FALSE, NULL, NULL, 'open', '2024-02-20 16:30:00'),
(4, NULL, NULL, 15, 'UI设计软件选择', '学习UI设计应该从哪个设计软件开始？Figma、Sketch、Adobe XD有什么区别和优缺点？', 'general', FALSE, 278, 9, 38, TRUE, 6, '2024-02-05 11:20:00', 'closed', '2024-01-25 14:45:00'),
(4, NULL, NULL, 16, '移动端设计规范', 'iOS和Android的设计规范有哪些主要区别？做跨平台设计时应该注意什么？', 'technical', TRUE, 195, 7, 22, FALSE, NULL, NULL, 'open', '2024-02-15 19:30:00'),
(6, NULL, NULL, 23, 'React学习建议', '学习React前需要掌握哪些JavaScript知识？有哪些推荐的React学习资源？', 'general', FALSE, 231, 8, 31, TRUE, 9, '2024-02-28 16:45:00', 'closed', '2024-02-25 21:15:00'),
(6, NULL, NULL, 24, '前端性能优化', '如何优化大型单页应用的首次加载速度？有哪些具体的优化策略？', 'technical', FALSE, 167, 6, 19, FALSE, NULL, NULL, 'open', '2024-03-05 15:20:00'),
(7, NULL, NULL, 26, '理财风险评估', '如何评估个人的风险承受能力？不同年龄阶段应该采取什么样的投资策略？', 'general', FALSE, 145, 5, 16, TRUE, 8, '2024-03-10 10:15:00', 'closed', '2024-03-08 14:30:00');

-- 15. 插入讨论回复数据
INSERT INTO discussion_replies (discussion_id, user_id, parent_reply_id, content, is_teacher_reply, is_best_answer, like_count, reply_to_user_id, status, created_at) VALUES
(1, 3, NULL, '请检查环境变量设置是否正确。在Windows上，需要将Python安装目录和Scripts目录都添加到PATH中。可以尝试重启命令行或者电脑。', TRUE, TRUE, 28, 13, 'normal', '2024-01-04 16:30:00'),
(1, 11, NULL, '也可以尝试使用Python Launcher或者直接使用Anaconda，它会自动配置好环境。', FALSE, FALSE, 15, 13, 'normal', '2024-01-04 17:45:00'),
(1, 13, 1, '谢谢老师！按照您的方法重新配置后问题解决了。', FALSE, FALSE, 8, 3, 'normal', '2024-01-05 09:15:00'),
(2, 11, NULL, '列表推导式在大多数情况下比传统for循环更快，因为它是用C语言实现的。但对于特别复杂的逻辑，可读性可能更重要。', TRUE, FALSE, 22, 14, 'normal', '2024-01-10 10:20:00'),
(2, 3, NULL, '这里有一篇详细的性能对比文章可以参考：https://realpython.com/python-list-comprehension/#using-list-comprehensions-effectively', TRUE, TRUE, 19, 14, 'normal', '2024-01-10 14:30:00'),
(3, 3, NULL, 'Python是"对象引用传递"。传递不可变对象（如数字、字符串、元组）时，函数内修改不会影响原对象；传递可变对象（如列表、字典）时，修改会影响原对象。', TRUE, TRUE, 35, 15, 'normal', '2024-01-15 09:00:00'),
(4, 4, NULL, '建议学习路径：Python基础 → NumPy/Pandas → 数据可视化(Matplotlib/Seaborn) → 统计学基础 → 机器学习(Scikit-learn) → 深度学习', TRUE, TRUE, 42, 13, 'normal', '2024-02-09 14:20:00'),
(4, 13, 7, '这个路径很清晰，谢谢老师！大概需要多长时间能学完？', FALSE, FALSE, 12, 4, 'normal', '2024-02-09 16:45:00'),
(4, 4, 8, '如果每天学习2-3小时，大概需要3-6个月可以掌握基础，要精通可能需要1-2年持续学习。', TRUE, FALSE, 18, 13, 'normal', '2024-02-10 10:15:00'),
(6, 6, NULL, '建议从Figma开始，它是跨平台的，有免费版，而且现在业界使用非常广泛。Sketch只能在Mac上用，Adobe XD功能相对较少。', TRUE, TRUE, 38, 15, 'normal', '2024-01-26 09:30:00'),
(8, 9, NULL, '需要掌握：ES6+语法、Promise、async/await、模块化、DOM操作。推荐React官方文档和Dan Abramov的博客。', TRUE, TRUE, 31, 23, 'normal', '2024-02-26 10:45:00'),
(10, 8, NULL, '风险承受能力评估可以从年龄、收入、投资经验、投资目标等方面考虑。年轻人可以承受更高风险，临近退休应该更保守。', TRUE, TRUE, 24, 26, 'normal', '2024-03-09 11:20:00');

-- 16. 插入学习计划数据
INSERT INTO study_plans (student_id, plan_name, description, start_date, end_date, target_hours_per_week, status, actual_completion_date) VALUES
(13, '2024年编程技能提升计划', '系统学习Python、数据科学和Web开发，提升全栈能力', '2024-01-01', '2024-12-31', 12.00, 'active', NULL),
(14, '数据科学家成长计划', '专注于数据科学和机器学习技术栈的学习', '2024-01-15', '2024-08-31', 15.00, 'active', NULL),
(15, 'UI/UX设计师转型计划', '从零开始学习设计，完成职业转型', '2024-01-10', '2024-06-30', 10.00, 'completed', '2024-06-30'),
(23, '前端工程师进阶计划', '深入学习现代前端开发技术', '2024-01-01', '2024-09-30', 14.00, 'active', NULL),
(18, '机器学习专项学习', '专注于深度学习算法研究和应用', '2024-02-01', '2024-10-31', 16.00, 'active', NULL),
(26, '理财知识学习计划', '系统学习个人理财和投资知识', '2024-03-01', '2024-08-31', 8.00, 'active', NULL),
(27, '职业发展综合计划', '结合技术和商业知识，提升综合能力', '2024-01-20', '2024-12-31', 10.00, 'paused', NULL);

-- 17. 插入学习计划详情数据
INSERT INTO study_plan_details (plan_id, course_id, enrollment_id, target_completion_date, priority_level, current_progress, status, notes) VALUES
(1, 1, 1, '2024-03-31', 'high', 100.00, 'completed', 'Python基础已完成，开始学习数据科学'),
(1, 2, 6, '2024-06-30', 'high', 58.90, 'in_progress', '正在进行数据科学学习'),
(1, 6, NULL, '2024-09-30', 'medium', 0.00, 'pending', '计划学习Web前端开发'),
(2, 1, 2, '2024-03-15', 'high', 78.50, 'in_progress', 'Python基础学习中'),
(2, 2, 7, '2024-07-31', 'high', 72.30, 'in_progress', '数据科学核心课程'),
(2, 8, NULL, '2024-10-31', 'medium', 0.00, 'pending', '计划学习机器学习'),
(3, 4, 11, '2024-03-31', 'high', 100.00, 'completed', 'UI设计课程已完成'),
(3, 12, NULL, '2024-06-30', 'medium', 0.00, 'pending', '计划学习平面设计'),
(4, 6, 17, '2024-03-31', 'high', 100.00, 'completed', 'Web前端基础已完成'),
(4, 9, NULL, '2024-08-31', 'high', 0.00, 'pending', '计划学习React Native'),
(5, 2, 8, '2024-05-31', 'high', 100.00, 'completed', '数据科学课程已完成'),
(5, 3, NULL, '2024-09-30', 'high', 0.00, 'pending', '计划学习深度学习'),
(6, 7, 19, '2024-06-30', 'high', 42.80, 'in_progress', '理财知识学习中'),
(6, 13, NULL, '2024-08-31', 'medium', 0.00, 'pending', '计划学习投资策略');

-- 18. 插入系统通知数据
INSERT INTO system_notifications (notification_type, title, content, target_user_id, related_course_id, related_live_session_id, is_read, is_urgent, scheduled_send_time, actual_send_time, expiry_time, status, created_by) VALUES
('course_update', 'Python课程第3章已更新', 'Python编程从入门到精通课程第3章"流程控制语句"已更新，新增了5个实战案例和练习题', NULL, 1, NULL, FALSE, FALSE, '2024-03-10 09:00:00', '2024-03-10 09:00:00', '2024-04-10 23:59:59', 'sent', 1),
('live_reminder', '深度学习直播课提醒', '今天晚上19:00有深度学习基础第一讲直播课程"神经网络原理与基础架构"，请准时参加', 13, 3, 1, TRUE, FALSE, '2024-03-15 18:00:00', '2024-03-15 18:00:00', '2024-03-15 21:00:00', 'sent', 2),
('assignment_due', '数据科学作业即将截止', '数据科学实战训练营第2章作业将于3天后截止，请及时提交', 14, 2, NULL, TRUE, TRUE, '2024-03-05 09:00:00', '2024-03-05 09:00:00', '2024-03-08 23:59:59', 'sent', 1),
('certificate_issued', '恭喜获得结业证书', '您已完成Python编程从入门到精通课程，结业证书已颁发，请在个人中心查看', 13, 1, NULL, TRUE, FALSE, '2024-03-15 10:00:00', '2024-03-15 10:00:00', '2024-06-15 23:59:59', 'sent', 1),
('system_announcement', '平台维护通知', '为提升服务质量，平台将于3月25日凌晨2:00-4:00进行系统维护，期间可能无法访问，请提前安排学习时间', NULL, NULL, NULL, FALSE, FALSE, '2024-03-20 09:00:00', '2024-03-20 09:00:00', '2024-03-25 04:00:00', 'sent', 1),
('new_message', '您有新的私信', '老师给您回复了课程问题，请及时查看', 13, NULL, NULL, TRUE, FALSE, '2024-03-16 10:35:00', '2024-03-16 10:35:00', '2024-03-23 23:59:59', 'sent', 3),
('live_reminder', '数字营销直播课提醒', '明天下午14:00有数字营销策略直播课，主题"2024年数字营销最新趋势"', 21, 5, 3, FALSE, FALSE, '2024-02-19 18:00:00', '2024-02-19 18:00:00', '2024-02-20 14:00:00', 'sent', 2),
('course_update', 'UI设计课程新增素材', 'UI设计专业班新增了100+设计素材和模板，可在课程资源区下载使用', NULL, 4, NULL, FALSE, FALSE, '2024-02-28 10:00:00', '2024-02-28 10:00:00', '2024-03-31 23:59:59', 'sent', 1);

-- 19. 插入用户消息数据
INSERT INTO user_messages (sender_id, receiver_id, message_type, content, attachment_url, is_read, read_time, parent_message_id, conversation_id, status, created_at) VALUES
(3, 13, 'text', '张三同学，看到你在Python课程中表现很好，第一章测验取得了85分的好成绩，继续加油！', NULL, TRUE, '2024-01-06 14:30:00', NULL, 'conv_3_13', 'read', '2024-01-06 10:15:00'),
(13, 3, 'text', '谢谢老师鼓励！我会继续努力的，目前正在学习第二章的数据类型部分', NULL, TRUE, '2024-01-06 15:20:00', 1, 'conv_3_13', 'read', '2024-01-06 14:45:00'),
(3, 13, 'text', '很好！数据类型是Python的基础，一定要掌握牢固。有问题随时在讨论区提问。', NULL, TRUE, '2024-01-07 09:15:00', 2, 'conv_3_13', 'read', '2024-01-06 16:30:00'),
(4, 14, 'text', '李四同学，关于数据科学课程的问题，我已经在讨论区详细回复了，请查看', NULL, TRUE, '2024-02-06 11:25:00', NULL, 'conv_4_14', 'read', '2024-02-05 15:30:00'),
(6, 15, 'text', '陈梦同学，你的UI设计作业很有创意，建议可以尝试更多的配色方案，让界面更活泼一些', 'https://cdn.edu.com/feedback/design_critique.pdf', FALSE, NULL, NULL, 'conv_6_15', 'sent', '2024-02-10 14:20:00'),
(23, 9, 'text', '老师，我想咨询一下前端工程师的职业发展路径，有什么建议吗？', NULL, TRUE, '2024-02-28 10:45:00', NULL, 'conv_23_9', 'read', '2024-02-27 21:15:00'),
(9, 23, 'text', '前端工程师可以往全栈发展，也可以专注前端深入，比如前端架构师。建议先打好基础，再选择方向。', NULL, TRUE, '2024-02-28 14:30:00', 6, 'conv_23_9', 'read', '2024-02-28 11:20:00'),
(8, 26, 'text', '董健同学，你的理财规划作业已批改，得分92分，投资组合设计得很合理', 'https://cdn.edu.com/assignments/finance_feedback.pdf', TRUE, '2024-03-12 16:15:00', NULL, 'conv_8_26', 'read', '2024-03-12 10:30:00'),
(26, 8, 'text', '谢谢老师！我会继续学习更高级的投资策略', NULL, TRUE, '2024-03-12 17:20:00', 8, 'conv_8_26', 'read', '2024-03-12 16:45:00'),
(4, 18, 'text', '钱伟同学，恭喜你完成数据科学课程！有兴趣参加我们的进阶机器学习项目吗？', NULL, FALSE, NULL, NULL, 'conv_4_18', 'sent', '2024-03-21 09:30:00');

-- 20. 插入学习数据统计表（2024年3月示例数据）
INSERT INTO learning_statistics_daily (stat_date, user_id, course_id, total_study_minutes, completed_resources, quiz_attempts, avg_quiz_score, assignment_submissions, discussion_posts, discussion_replies, points_earned, level_up) VALUES
-- 3月1日数据
('2024-03-01', 13, 1, 120, 2, 1, 85.00, 1, 0, 0, 25, FALSE),
('2024-03-01', 14, 1, 90, 1, 0, NULL, 0, 1, 0, 20, FALSE),
('2024-03-01', 13, 2, 150, 2, 0, NULL, 0, 0, 1, 30, FALSE),
('2024-03-01', 15, 4, 180, 3, 0, NULL, 1, 0, 0, 35, FALSE),
-- 3月2日数据
('2024-03-02', 13, 1, 135, 1, 0, NULL, 0, 0, 0, 20, FALSE),
('2024-03-02', 14, 2, 210, 2, 1, 78.00, 0, 1, 0, 35, FALSE),
('2024-03-02', 16, 4, 165, 2, 0, NULL, 0, 0, 0, 25, FALSE),
('2024-03-02', 23, 6, 195, 3, 0, NULL, 1, 0, 0, 40, FALSE),
-- 3月3日数据
('2024-03-03', 13, 2, 180, 3, 0, NULL, 0, 0, 1, 30, FALSE),
('2024-03-03', 14, 1, 105, 1, 0, NULL, 0, 0, 0, 15, FALSE),
('2024-03-03', 18, 2, 240, 4, 0, NULL, 1, 0, 0, 45, TRUE),
('2024-03-03', 26, 7, 90, 1, 0, NULL, 0, 0, 0, 15, FALSE),
-- 3月4日数据
('2024-03-04', 13, 1, 150, 2, 1, 92.00, 0, 0, 0, 30, FALSE),
('2024-03-04', 15, 4, 120, 2, 0, NULL, 0, 0, 0, 20, FALSE),
('2024-03-04', 24, 6, 210, 3, 0, NULL, 0, 1, 0, 35, FALSE),
('2024-03-04', 27, 7, 75, 1, 0, NULL, 0, 0, 0, 12, FALSE),
-- 3月5日数据
('2024-03-05', 13, 2, 165, 2, 0, NULL, 1, 0, 0, 30, FALSE),
('2024-03-05', 14, 2, 195, 3, 0, NULL, 0, 0, 1, 35, FALSE),
('2024-03-05', 16, 4, 135, 2, 0, NULL, 0, 0, 0, 22, FALSE),
('2024-03-05', 21, 5, 180, 2, 0, NULL, 0, 0, 0, 28, FALSE),
-- 3月15日证书颁发日数据
('2024-03-15', 13, 1, 120, 1, 0, NULL, 0, 0, 0, 50, TRUE), -- 证书奖励50积分
('2024-03-15', 18, 2, 210, 2, 0, NULL, 0, 0, 0, 45, FALSE),
-- 3月20日数据
('2024-03-20', 18, 2, 180, 1, 0, NULL, 0, 0, 0, 50, TRUE), -- 完成课程奖励
('2024-03-20', 15, 4, 150, 2, 0, NULL, 0, 0, 0, 50, TRUE), -- 完成课程奖励
-- 3月22日最新数据
('2024-03-22', 13, 1, 135, 1, 0, NULL, 0, 0, 0, 20, FALSE),
('2024-03-22', 13, 2, 195, 2, 0, NULL, 0, 0, 0, 30, FALSE),
('2024-03-22', 14, 1, 120, 1, 0, NULL, 0, 0, 0, 18, FALSE),
('2024-03-22', 14, 2, 210, 3, 0, NULL, 0, 0, 0, 35, FALSE),
('2024-03-22', 15, 4, 90, 1, 0, NULL, 0, 0, 0, 15, FALSE),
('2024-03-22', 16, 4, 165, 2, 0, NULL, 0, 0, 0, 25, FALSE),
('2024-03-22', 23, 6, 180, 2, 0, NULL, 0, 0, 0, 28, FALSE),
('2024-03-22', 24, 6, 195, 3, 0, NULL, 0, 0, 0, 32, FALSE),
('2024-03-22', 26, 7, 105, 1, 0, NULL, 0, 0, 0, 16, FALSE),
('2024-03-22', 27, 7, 120, 2, 0, NULL, 0, 0, 0, 20, FALSE);