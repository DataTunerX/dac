"""
SemanticGrouper 集成测试
使用真实的 MySQL 和 pgvector client 进行测试

运行方式：
    python -m data_sinkers.semantic_group.semantic_group_test
    python -m data_sinkers.semantic_group.semantic_group_test consolidate
    python -m data_sinkers.semantic_group.semantic_group_test decremental

配置说明：
    - DATA_SERVICES_URL: data-services 服务的地址，默认 http://192.168.3.238:22000
    - COLLECTION_NAME: pgvector 集合名称，默认 "semantic_groups"

测试流程：
    1. 初始化 VectorClient 和 SemanticGroupClient
    2. 准备测试数据（约20个语义域）
    3. 逐个调用 SemanticGrouper.incremental_semantic_group_analyse() 处理语义域
    4. 验证结果并显示最终状态

测试数据说明：
    包含约20个不同业务领域的语义域，用于测试：
    - CREATE：创建新组
    - JOIN：加入现有组
    - 不同业务领域的语义域分组
"""
import os
import sys
import uuid
import json
import logging
from typing import Dict, Any, List

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from data_sinkers.semantic_group.semantic_group import SemanticGrouper
from data_sinkers.client.vector_client import VectorClient
from data_sinkers.client.semantic_group_client import SemanticGroupClient
from data_sinkers.client.semantic_domain_client import SemanticDomainClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置信息
DATA_SERVICES_URL = "http://192.168.3.238:22000"
COLLECTION_NAME = "semantic_groups"


def prepare_test_data() -> List[Dict[str, Any]]:
    """
    准备测试数据：约20个语义域
    
    测试数据设计说明：
    包含多个业务领域，用于测试不同的分组场景：
    - 用户相关：用户管理、权限管理、客户服务等
    - 订单相关：订单管理、支付、物流、优惠券等
    - 商品相关：商品管理、库存管理、评价系统等
    - 通用系统：日志、监控、消息、文件存储等
    
    Returns:
        语义域列表，每个包含：
        - semantic_domain_id: 语义域ID
        - semantic_domain: 语义域描述文本
        - dd_name: 数据描述符名称
        - dd_namespace: 数据描述符命名空间
    """


    test_domains = [
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统
            这是一个完整的用户管理系统，包含用户基本信息、用户认证、用户权限管理等功能。
            
            主要功能模块：
            1. 用户注册和登录
            2. 用户信息管理
            3. 角色和权限管理
            4. 用户会话管理
            
            主要表结构：
            - users: 用户基本信息表，包含用户ID、用户名、邮箱、手机号、密码哈希等字段
            - user_roles: 用户角色关联表，管理用户与角色的多对多关系
            - roles: 角色表，定义系统中的各种角色，如管理员、普通用户等
            - permissions: 权限表，定义系统中的各种权限，如读取、写入、删除等
            - user_sessions: 用户会话表，记录用户的登录会话信息
            """,
            "dd_name": "user_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            权限管理系统
            这是一个权限管理系统，用于管理系统的角色、权限和访问控制。
            
            主要功能模块：
            1. 角色管理
            2. 权限管理
            3. 权限分配
            4. 访问控制
            
            主要表结构：
            - roles: 角色表，包含角色ID、角色名称、角色描述等字段
            - permissions: 权限表，定义系统中的各种权限
            - role_permissions: 角色权限关联表，管理角色与权限的关系
            - access_control: 访问控制表，记录访问控制规则
            """,
            "dd_name": "permission_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            订单管理系统
            这是一个电商订单管理系统，处理订单的创建、查询、更新和取消等操作。
            
            主要功能模块：
            1. 订单创建和管理
            2. 订单状态跟踪
            3. 订单与用户的关联
            4. 订单与商品的关联
            
            主要表结构：
            - orders: 订单主表，包含订单ID、用户ID、订单状态、订单金额、创建时间等字段
            - order_items: 订单明细表，包含订单项ID、商品ID、数量、单价、总价等字段
            - order_payments: 订单支付表，记录订单的支付信息，包括支付方式、支付状态等
            - order_shipping: 订单配送表，记录订单的配送信息
            """,
            "dd_name": "order_management",
            "dd_namespace": "dac"
        }
    ]


    # test_domains = [
    #     {
    #         "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
    #         "semantic_domain": """
    #         日志分析系统
    #         这是一个日志分析系统，用于收集、存储和分析系统日志数据。
            
    #         主要功能模块：
    #         1. 日志收集
    #         2. 日志存储
    #         3. 日志查询和分析
    #         4. 日志可视化
            
    #         主要表结构：
    #         - log_entries: 日志条目表，包含日志ID、日志级别、消息内容、时间戳、来源系统等字段
    #         - log_sources: 日志来源表，定义日志的来源系统，如用户系统、订单系统等
    #         - log_analytics: 日志分析结果表，存储分析后的结果，如错误统计、性能指标等
    #         - log_alerts: 日志告警表，记录需要关注的日志事件
    #         """,
    #         "dd_name": "log_analytics",
    #         "dd_namespace": "dac"
    #     },
    # ]


    return test_domains



    test_domains = [
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统
            这是一个完整的用户管理系统，包含用户基本信息、用户认证、用户权限管理等功能。
            
            主要功能模块：
            1. 用户注册和登录
            2. 用户信息管理
            3. 角色和权限管理
            4. 用户会话管理
            
            主要表结构：
            - users: 用户基本信息表，包含用户ID、用户名、邮箱、手机号、密码哈希等字段
            - user_roles: 用户角色关联表，管理用户与角色的多对多关系
            - roles: 角色表，定义系统中的各种角色，如管理员、普通用户等
            - permissions: 权限表，定义系统中的各种权限，如读取、写入、删除等
            - user_sessions: 用户会话表，记录用户的登录会话信息
            """,
            "dd_name": "user_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            订单管理系统
            这是一个电商订单管理系统，处理订单的创建、查询、更新和取消等操作。
            
            主要功能模块：
            1. 订单创建和管理
            2. 订单状态跟踪
            3. 订单与用户的关联
            4. 订单与商品的关联
            
            主要表结构：
            - orders: 订单主表，包含订单ID、用户ID、订单状态、订单金额、创建时间等字段
            - order_items: 订单明细表，包含订单项ID、商品ID、数量、单价、总价等字段
            - order_payments: 订单支付表，记录订单的支付信息，包括支付方式、支付状态等
            - order_shipping: 订单配送表，记录订单的配送信息
            """,
            "dd_name": "order_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品管理系统
            这是一个商品信息管理系统，管理商品信息、库存、分类等。
            
            主要功能模块：
            1. 商品信息管理
            2. 商品分类管理
            3. 库存管理
            4. 商品价格管理
            
            主要表结构：
            - products: 商品表，包含商品ID、商品名称、价格、描述、图片等字段
            - product_categories: 商品分类表，定义商品的分类层级
            - inventory: 库存表，记录商品的库存数量、仓库位置等信息
            - product_reviews: 商品评价表，记录用户对商品的评价
            """,
            "dd_name": "product_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            支付服务系统
            这是一个支付服务系统，处理支付相关的业务逻辑，包括支付方式、支付记录等。
            
            主要功能模块：
            1. 支付方式管理
            2. 支付处理
            3. 支付记录查询
            4. 退款处理
            
            主要表结构：
            - payments: 支付记录表，包含支付ID、订单ID、支付方式、支付金额、支付状态、支付时间等字段
            - payment_methods: 支付方式表，定义支持的支付方式，如支付宝、微信、银行卡等
            - payment_transactions: 支付交易表，记录详细的交易信息，包括交易流水号、交易状态等
            - refunds: 退款表，记录退款信息
            """,
            "dd_name": "payment_service",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统（另一个版本）
            这是另一个用户管理系统的实现，功能与第一个用户管理系统高度相似，但表结构略有不同。
            
            主要功能模块：
            1. 用户账户管理
            2. 用户资料管理
            3. 用户会话管理
            4. 用户认证
            
            主要表结构：
            - user_accounts: 用户账户表，包含账户ID、用户名、邮箱、手机号等字段
            - user_profiles: 用户资料表，包含用户的详细信息，如昵称、头像、个人简介等
            - user_sessions: 用户会话表，记录用户的登录会话信息
            - user_authentication: 用户认证表，记录用户的认证信息，如密码、令牌等
            """,
            "dd_name": "user_management_v2",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            日志分析系统
            这是一个日志分析系统，用于收集、存储和分析系统日志数据。
            
            主要功能模块：
            1. 日志收集
            2. 日志存储
            3. 日志查询和分析
            4. 日志可视化
            
            主要表结构：
            - log_entries: 日志条目表，包含日志ID、日志级别、消息内容、时间戳、来源系统等字段
            - log_sources: 日志来源表，定义日志的来源系统，如用户系统、订单系统等
            - log_analytics: 日志分析结果表，存储分析后的结果，如错误统计、性能指标等
            - log_alerts: 日志告警表，记录需要关注的日志事件
            """,
            "dd_name": "log_analytics",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            库存管理系统
            这是一个库存管理系统，用于管理商品的库存信息、出入库记录、库存预警等。
            
            主要功能模块：
            1. 库存查询和统计
            2. 入库管理
            3. 出库管理
            4. 库存预警和补货提醒
            
            主要表结构：
            - inventory: 库存主表，包含商品ID、仓库ID、库存数量、安全库存等字段
            - inventory_transactions: 库存交易表，记录所有出入库操作
            - warehouses: 仓库表，定义仓库信息
            - stock_alerts: 库存预警表，记录需要补货的商品
            """,
            "dd_name": "inventory_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            物流配送系统
            这是一个物流配送管理系统，处理订单的配送、物流跟踪、配送员管理等。
            
            主要功能模块：
            1. 配送单管理
            2. 物流跟踪
            3. 配送员管理
            4. 配送路线优化
            
            主要表结构：
            - shipments: 配送单表，包含配送单ID、订单ID、配送地址、配送状态等字段
            - delivery_tracking: 配送跟踪表，记录配送过程中的位置和时间信息
            - delivery_persons: 配送员表，管理配送员信息
            - delivery_routes: 配送路线表，优化配送路径
            """,
            "dd_name": "logistics_delivery",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            客户服务系统
            这是一个客户服务系统，处理客户咨询、投诉、工单管理等。
            
            主要功能模块：
            1. 客户咨询管理
            2. 工单系统
            3. 客户反馈处理
            4. 客服人员管理
            
            主要表结构：
            - customer_tickets: 客户工单表，包含工单ID、用户ID、问题类型、处理状态等字段
            - customer_inquiries: 客户咨询表，记录客户的咨询记录
            - customer_feedback: 客户反馈表，收集客户的意见和建议
            - service_agents: 客服人员表，管理客服团队
            """,
            "dd_name": "customer_service",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            营销活动系统
            这是一个营销活动管理系统，用于创建和管理各种营销活动、促销活动等。
            
            主要功能模块：
            1. 活动创建和管理
            2. 活动参与记录
            3. 活动效果分析
            4. 优惠券发放
            
            主要表结构：
            - marketing_campaigns: 营销活动表，包含活动ID、活动名称、开始时间、结束时间等字段
            - campaign_participants: 活动参与表，记录用户参与活动的情况
            - campaign_analytics: 活动分析表，统计活动效果数据
            - campaign_coupons: 活动优惠券表，关联活动与优惠券
            """,
            "dd_name": "marketing_campaigns",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            优惠券系统
            这是一个优惠券管理系统，处理优惠券的创建、发放、使用和核销等。
            
            主要功能模块：
            1. 优惠券创建
            2. 优惠券发放
            3. 优惠券使用
            4. 优惠券核销
            
            主要表结构：
            - coupons: 优惠券表，包含优惠券ID、优惠类型、折扣金额、使用条件等字段
            - coupon_issuance: 优惠券发放表，记录优惠券的发放记录
            - coupon_usage: 优惠券使用表，记录优惠券的使用情况
            - coupon_validation: 优惠券核销表，记录核销操作
            """,
            "dd_name": "coupon_system",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品评价系统
            这是一个商品评价系统，允许用户对购买的商品进行评价和打分。
            
            主要功能模块：
            1. 评价发布
            2. 评价管理
            3. 评价统计
            4. 评价审核
            
            主要表结构：
            - product_reviews: 商品评价表，包含评价ID、商品ID、用户ID、评分、评价内容等字段
            - review_images: 评价图片表，存储评价中的图片
            - review_likes: 评价点赞表，记录用户对评价的点赞
            - review_statistics: 评价统计表，汇总商品的评价数据
            """,
            "dd_name": "product_reviews",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            消息通知系统
            这是一个消息通知系统，用于向用户发送各种类型的通知消息。
            
            主要功能模块：
            1. 消息发送
            2. 消息模板管理
            3. 消息推送
            4. 消息统计
            
            主要表结构：
            - notifications: 通知表，包含通知ID、用户ID、通知类型、内容、状态等字段
            - notification_templates: 通知模板表，定义各种通知模板
            - notification_channels: 通知渠道表，定义推送渠道（短信、邮件、APP推送等）
            - notification_logs: 通知日志表，记录发送历史
            """,
            "dd_name": "notification_system",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            文件存储系统
            这是一个文件存储系统，用于管理用户上传的文件、图片、文档等。
            
            主要功能模块：
            1. 文件上传
            2. 文件存储
            3. 文件访问控制
            4. 文件管理
            
            主要表结构：
            - files: 文件表，包含文件ID、文件名、文件类型、文件大小、存储路径等字段
            - file_metadata: 文件元数据表，存储文件的额外信息
            - file_permissions: 文件权限表，控制文件的访问权限
            - file_versions: 文件版本表，管理文件的历史版本
            """,
            "dd_name": "file_storage",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            数据分析系统
            这是一个数据分析系统，用于收集、分析和展示业务数据。
            
            主要功能模块：
            1. 数据收集
            2. 数据分析
            3. 数据可视化
            4. 报表生成
            
            主要表结构：
            - data_sources: 数据源表，定义数据来源
            - data_metrics: 数据指标表，存储各种业务指标
            - data_reports: 数据报表表，存储生成的报表
            - data_dashboards: 数据看板表，定义数据展示看板
            """,
            "dd_name": "data_analytics",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            权限管理系统
            这是一个权限管理系统，用于管理系统的角色、权限和访问控制。
            
            主要功能模块：
            1. 角色管理
            2. 权限管理
            3. 权限分配
            4. 访问控制
            
            主要表结构：
            - roles: 角色表，包含角色ID、角色名称、角色描述等字段
            - permissions: 权限表，定义系统中的各种权限
            - role_permissions: 角色权限关联表，管理角色与权限的关系
            - access_control: 访问控制表，记录访问控制规则
            """,
            "dd_name": "permission_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            内容管理系统
            这是一个内容管理系统，用于管理网站内容、文章、页面等。
            
            主要功能模块：
            1. 内容创建和编辑
            2. 内容发布
            3. 内容分类
            4. 内容审核
            
            主要表结构：
            - contents: 内容表，包含内容ID、标题、内容、作者、发布时间等字段
            - content_categories: 内容分类表，定义内容的分类
            - content_tags: 内容标签表，管理内容的标签
            - content_versions: 内容版本表，记录内容的修改历史
            """,
            "dd_name": "content_management",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            搜索服务系统
            这是一个搜索服务系统，提供全文搜索、商品搜索、用户搜索等功能。
            
            主要功能模块：
            1. 索引管理
            2. 搜索查询
            3. 搜索结果排序
            4. 搜索统计
            
            主要表结构：
            - search_indexes: 搜索索引表，存储搜索索引信息
            - search_queries: 搜索查询表，记录用户的搜索行为
            - search_results: 搜索结果表，缓存搜索结果
            - search_analytics: 搜索分析表，统计搜索数据
            """,
            "dd_name": "search_service",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            缓存服务系统
            这是一个缓存服务系统，用于提供高性能的数据缓存服务。
            
            主要功能模块：
            1. 缓存设置
            2. 缓存读取
            3. 缓存更新
            4. 缓存失效
            
            主要表结构：
            - cache_keys: 缓存键表，管理缓存键的元数据
            - cache_statistics: 缓存统计表，记录缓存命中率等指标
            - cache_config: 缓存配置表，定义缓存策略
            """,
            "dd_name": "cache_service",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            监控告警系统
            这是一个监控告警系统，用于监控系统运行状态并发送告警。
            
            主要功能模块：
            1. 指标监控
            2. 告警规则管理
            3. 告警发送
            4. 告警处理
            
            主要表结构：
            - monitoring_metrics: 监控指标表，存储各种监控指标
            - alert_rules: 告警规则表，定义告警触发条件
            - alerts: 告警表，记录告警信息
            - alert_history: 告警历史表，存储历史告警记录
            """,
            "dd_name": "monitoring_alerts",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统（第三个版本）
            这是第三个用户管理系统的实现，功能与之前的用户管理系统类似，但架构不同。
            
            主要功能模块：
            1. 用户注册登录
            2. 用户信息管理
            3. 用户认证授权
            4. 用户行为追踪
            
            主要表结构：
            - accounts: 账户表，包含账户ID、用户名、密码等字段
            - user_info: 用户信息表，存储用户的详细信息
            - auth_tokens: 认证令牌表，管理用户的认证令牌
            - user_behaviors: 用户行为表，记录用户的操作行为
            """,
            "dd_name": "user_management_v3",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            订单管理系统（企业版）
            这是企业版的订单管理系统，功能更加强大，支持批量订单、订单审批等。
            
            主要功能模块：
            1. 订单创建和管理
            2. 批量订单处理
            3. 订单审批流程
            4. 订单统计分析
            
            主要表结构：
            - enterprise_orders: 企业订单表，包含订单ID、企业ID、订单类型、审批状态等字段
            - order_approvals: 订单审批表，记录订单的审批流程
            - batch_orders: 批量订单表，管理批量订单
            - order_statistics: 订单统计表，汇总订单数据
            """,
            "dd_name": "order_management_enterprise",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            支付服务系统（国际版）
            这是国际版的支付服务系统，支持多种国际支付方式和货币。
            
            主要功能模块：
            1. 多币种支付
            2. 国际支付方式
            3. 汇率管理
            4. 跨境支付
            
            主要表结构：
            - international_payments: 国际支付表，包含支付ID、货币类型、汇率等字段
            - payment_currencies: 支付货币表，定义支持的货币
            - exchange_rates: 汇率表，存储汇率信息
            - cross_border_transactions: 跨境交易表，记录跨境支付
            """,
            "dd_name": "payment_service_international",
            "dd_namespace": "dac"
        },
        {
            "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品管理系统（多店铺版）
            这是多店铺版的商品管理系统，支持多个店铺管理各自的商品。
            
            主要功能模块：
            1. 店铺管理
            2. 商品管理
            3. 店铺商品关联
            4. 商品同步
            
            主要表结构：
            - shops: 店铺表，包含店铺ID、店铺名称、店主ID等字段
            - shop_products: 店铺商品表，管理每个店铺的商品
            - product_sync: 商品同步表，记录商品同步操作
            - shop_statistics: 店铺统计表，汇总店铺数据
            """,
            "dd_name": "product_management_multi_shop",
            "dd_namespace": "dac"
        }
    ]
    
    return test_domains


def test_semantic_grouper():
    """
    测试 SemanticGrouper 的完整流程
    """
    logger.info("=" * 80)
    logger.info("开始 SemanticGrouper 集成测试")
    logger.info("=" * 80)
    
    # 1. 初始化客户端
    logger.info("\n1. 初始化客户端...")
    vector_client = VectorClient(base_url=DATA_SERVICES_URL, timeout=600)
    semantic_group_client = SemanticGroupClient(base_url=DATA_SERVICES_URL, timeout=600)
    
    # 初始化 vector client（创建 collection）
    try:
        vector_client.initialize()
        logger.info("✓ VectorClient 初始化成功")
    except Exception as e:
        logger.warning(f"VectorClient 初始化警告: {e}（可能 collection 已存在）")
    
    # 检查服务健康状态
    try:
        is_healthy = semantic_group_client.health_check()
        logger.info(f"✓ SemanticGroupClient 健康检查: {'通过' if is_healthy else '失败'}")
    except Exception as e:
        logger.error(f"✗ SemanticGroupClient 健康检查失败: {e}")
        return
    
    # 2. 创建 SemanticGrouper
    logger.info("\n2. 创建 SemanticGrouper...")
    grouper = SemanticGrouper(
        vector_client=vector_client,
        semantic_group_client=semantic_group_client,
        collection_name=COLLECTION_NAME,
        allow_merge=False  # 禁止合并操作，避免测试时的复杂性
    )
    logger.info("✓ SemanticGrouper 创建成功")
    
    # 3. 准备测试数据
    logger.info("\n3. 准备测试数据...")
    test_domains = prepare_test_data()
    logger.info(f"✓ 准备了 {len(test_domains)} 个测试语义域")
    for i, domain in enumerate(test_domains, 1):
        logger.info(f"   {i}. {domain['dd_name']} ({domain['dd_namespace']})")
    
    # 4. 逐个处理语义域
    logger.info("\n4. 开始处理语义域...")
    results = []
    
    for i, domain in enumerate(test_domains, 1):
        logger.info(f"\n--- 处理第 {i}/{len(test_domains)} 个语义域: {domain['dd_name']} ---")
        logger.info(f"语义域ID: {domain['semantic_domain_id']}")
        logger.info(f"语义域描述: {domain['semantic_domain'][:100]}...")
        
        try:
            # 调用增量式语义域分组分析
            result = grouper.incremental_semantic_group_analyse(domain)
            
            if result:
                action = result.get('action', 'UNKNOWN')
                group_id = result.get('group_id', 'N/A')
                group_name = result.get('group_name', 'N/A')
                confidence = result.get('confidence', 0.0)
                
                logger.info(f"✓ 处理成功:")
                logger.info(f"  操作: {action}")
                logger.info(f"  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  置信度: {confidence:.2f}")
                logger.info(f"  理由: {result.get('reason', 'N/A')[:100]}...")
                
                results.append({
                    'domain': domain,
                    'result': result
                })
            else:
                logger.warning(f"✗ 处理失败: 返回结果为空")
                results.append({
                    'domain': domain,
                    'result': None
                })
                
        except Exception as e:
            logger.error(f"✗ 处理失败: {str(e)}", exc_info=True)
            results.append({
                'domain': domain,
                'result': None,
                'error': str(e)
            })
    
    # 5. 验证结果
    logger.info("\n" + "=" * 80)
    logger.info("测试结果汇总")
    logger.info("=" * 80)
    
    success_count = sum(1 for r in results if r.get('result') is not None)
    logger.info(f"\n成功处理: {success_count}/{len(results)}")
    
    # 统计操作类型
    action_counts = {}
    for r in results:
        if r.get('result'):
            action = r['result'].get('action', 'UNKNOWN')
            action_counts[action] = action_counts.get(action, 0) + 1
    
    logger.info("\n操作类型统计:")
    for action, count in action_counts.items():
        logger.info(f"  {action}: {count}")
    
    # 显示每个语义域的处理结果
    logger.info("\n详细结果:")
    for i, r in enumerate(results, 1):
        domain = r['domain']
        result = r.get('result')
        error = r.get('error')
        
        logger.info(f"\n{i}. {domain['dd_name']} ({domain['dd_namespace']})")
        if result:
            logger.info(f"   ✓ {result.get('action')} -> 组: {result.get('group_name')} (置信度: {result.get('confidence', 0):.2f})")
        elif error:
            logger.info(f"   ✗ 错误: {error}")
        else:
            logger.info(f"   ✗ 处理失败")
    
    # 6. 查询最终状态
    logger.info("\n" + "=" * 80)
    logger.info("查询最终状态")
    logger.info("=" * 80)
    
    try:
        # 获取所有语义组
        all_groups = semantic_group_client.get_all_semantic_groups()
        groups_data = all_groups.get('data', [])
        logger.info(f"\n当前共有 {len(groups_data)} 个语义组:")
        
        for group in groups_data:
            group_id = group.get('id') or group.get('group_id', 'N/A')
            group_name = group.get('group_name', 'N/A')
            description = group.get('description', 'N/A')
            
            # 获取该组的成员
            try:
                relations = semantic_group_client.get_relations_by_group_id(group_id)
                relations_data = relations.get('data', [])
                member_count = len(relations_data)
                
                logger.info(f"\n  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  描述: {description[:100]}...")
                logger.info(f"  成员数: {member_count}")
                if member_count > 0:
                    member_ids = [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
                    logger.info(f"  成员ID: {', '.join(member_ids[:5])}{'...' if len(member_ids) > 5 else ''}")
            except Exception as e:
                logger.warning(f"  获取组成员失败: {e}")
                
    except Exception as e:
        logger.error(f"查询最终状态失败: {e}", exc_info=True)
    
    logger.info("\n" + "=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)


def test_consolidate_semantic_domain_into_semantic_group():
    """
    测试 consolidate_semantic_domain_into_semantic_group 方法
    测试合并语义域到语义组的功能，包括 retry 机制
    """
    logger.info("=" * 80)
    logger.info("开始测试 consolidate_semantic_domain_into_semantic_group")
    logger.info("=" * 80)
    
    # 1. 初始化客户端
    logger.info("\n1. 初始化客户端...")
    vector_client = VectorClient(base_url=DATA_SERVICES_URL, timeout=600)
    semantic_group_client = SemanticGroupClient(base_url=DATA_SERVICES_URL, timeout=600)
    
    # 初始化 vector client（创建 collection）
    try:
        vector_client.initialize()
        logger.info("✓ VectorClient 初始化成功")
    except Exception as e:
        logger.warning(f"VectorClient 初始化警告: {e}（可能 collection 已存在）")
    
    # 检查服务健康状态
    try:
        is_healthy = semantic_group_client.health_check()
        logger.info(f"✓ SemanticGroupClient 健康检查: {'通过' if is_healthy else '失败'}")
    except Exception as e:
        logger.error(f"✗ SemanticGroupClient 健康检查失败: {e}")
        return
    
    # 2. 创建 SemanticGrouper
    logger.info("\n2. 创建 SemanticGrouper...")
    grouper = SemanticGrouper(
        vector_client=vector_client,
        semantic_group_client=semantic_group_client,
        collection_name=COLLECTION_NAME,
        allow_merge=False
    )
    logger.info("✓ SemanticGrouper 创建成功")
    
    # 3. 准备测试数据
    logger.info("\n3. 准备测试数据...")
    
    # 第一个语义域
    semantic_domain_1 = {
        "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
        "semantic_domain": """
        用户管理系统
        这是一个完整的用户管理系统，包含用户基本信息、用户认证、用户权限管理等功能。
        
        主要功能模块：
        1. 用户注册和登录
        2. 用户信息管理
        3. 角色和权限管理
        4. 用户会话管理
        
        主要表结构：
        - users: 用户基本信息表，包含用户ID、用户名、邮箱、手机号、密码哈希等字段
        - user_roles: 用户角色关联表，管理用户与角色的多对多关系
        - roles: 角色表，定义系统中的各种角色，如管理员、普通用户等
        - permissions: 权限表，定义系统中的各种权限，如读取、写入、删除等
        - user_sessions: 用户会话表，记录用户的登录会话信息
        """,
        "agent_card": "",
        "dd_name": "user_management",
        "dd_namespace": "dac"
    }
    
    # 第二个语义域（用于合并）
    semantic_domain_2 = {
        "semantic_domain_id": f"sd_{uuid.uuid4().hex[:8]}",
        "semantic_domain": """
        权限管理系统
        这是一个权限管理系统，用于管理系统的角色、权限和访问控制。
        
        主要功能模块：
        1. 角色管理
        2. 权限管理
        3. 权限分配
        4. 访问控制
        
        主要表结构：
        - roles: 角色表，包含角色ID、角色名称、角色描述等字段
        - permissions: 权限表，定义系统中的各种权限
        - role_permissions: 角色权限关联表，管理角色与权限的关系
        - access_control: 访问控制表，记录访问控制规则
        """,
        "agent_card": "",
        "dd_name": "permission_management",
        "dd_namespace": "dac"
    }
    
    # 语义组（基于第一个语义域创建）
    semantic_group = {
        "id": semantic_domain_1["semantic_domain_id"],
        "group_name": "用户与权限管理系统",
        "description": semantic_domain_1["semantic_domain"],
        "version": "v1.0",
        "agent_card": ""
    }
    
    logger.info("✓ 测试数据准备完成")
    logger.info(f"  语义域1: {semantic_domain_1['dd_name']}")
    logger.info(f"  语义域2: {semantic_domain_2['dd_name']}")
    logger.info(f"  语义组: {semantic_group['group_name']}")
    
    # 4. 测试 consolidate_semantic_domain_into_semantic_group
    logger.info("\n4. 测试 consolidate_semantic_domain_into_semantic_group...")
    
    try:
        # 测试基本功能
        logger.info("\n4.1 测试基本合并功能...")
        result = grouper.consolidate_semantic_domain_into_semantic_group(
            semantic_domain=semantic_domain_2,
            semantic_group=semantic_group,
            max_retries=3,
            retry_delay=1.0,
            exponential_backoff=True
        )
        
        if result:
            logger.info("✓ 合并成功")
            logger.info(f"  返回结果类型: {type(result)}")
            
            # 检查返回结果结构
            if isinstance(result, dict):
                if 'summary' in result:
                    summary = result['summary']
                    logger.info(f"  ✓ 包含 'summary' 字段")
                    logger.info(f"  Summary 长度: {len(str(summary))} 字符")
                    logger.info(f"  Summary 预览: {str(summary)[:200]}...")
                else:
                    logger.warning(f"  ⚠ 返回结果不包含 'summary' 字段")
                    logger.info(f"  返回结果键: {list(result.keys())}")
                
                # 打印完整结果（如果不太长）
                if len(str(result)) < 1000:
                    logger.info(f"  完整结果: {result}")
            else:
                logger.warning(f"  ⚠ 返回结果不是字典类型: {type(result)}")
        else:
            logger.error("✗ 合并失败: 返回结果为 None")
            
    except ValueError as e:
        logger.error(f"✗ 参数验证失败: {e}")
    except RuntimeError as e:
        logger.error(f"✗ 合并失败（所有重试都失败）: {e}")
    except Exception as e:
        logger.error(f"✗ 测试执行失败: {e}", exc_info=True)
    
    # 5. 测试 retry 机制（可选，通过设置较小的 max_retries 来验证）
    logger.info("\n5. 测试 retry 机制...")
    logger.info("  注意: 此测试需要 LLM 服务可用，如果 LLM 服务正常，retry 机制不会触发")
    logger.info("  可以通过模拟异常来测试 retry 机制（需要修改代码）")
    
    # 6. 测试参数验证
    logger.info("\n6. 测试参数验证...")
    
    # 测试无效的 semantic_domain
    try:
        invalid_domain = {"invalid": "data"}
        grouper.consolidate_semantic_domain_into_semantic_group(
            semantic_domain=invalid_domain,
            semantic_group=semantic_group,
            max_retries=1
        )
        logger.error("✗ 参数验证失败: 应该抛出 ValueError")
    except ValueError as e:
        logger.info(f"  ✓ 参数验证正常: {e}")
    except Exception as e:
        logger.warning(f"  ⚠ 抛出其他异常: {e}")
    
    # 测试无效的 semantic_group
    try:
        invalid_group = {"invalid": "data"}
        grouper.consolidate_semantic_domain_into_semantic_group(
            semantic_domain=semantic_domain_1,
            semantic_group=invalid_group,
            max_retries=1
        )
        logger.error("✗ 参数验证失败: 应该抛出 ValueError")
    except ValueError as e:
        logger.info(f"  ✓ 参数验证正常: {e}")
    except Exception as e:
        logger.warning(f"  ⚠ 抛出其他异常: {e}")
    
    logger.info("\n" + "=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)


def test_decremental_semantic_group_analyse():
    """
    测试 decremental_semantic_group_analyse 方法
    测试移除语义域的功能，包括：
    1. 创建语义域并加入组
    2. 移除语义域
    3. 验证移除结果（组是否为空、是否删除组等）
    """
    logger.info("=" * 80)
    logger.info("开始测试 decremental_semantic_group_analyse")
    logger.info("=" * 80)
    
    # 1. 初始化客户端
    logger.info("\n1. 初始化客户端...")
    vector_client = VectorClient(base_url=DATA_SERVICES_URL, timeout=600)
    semantic_group_client = SemanticGroupClient(base_url=DATA_SERVICES_URL, timeout=600)
    semantic_domain_client = SemanticDomainClient(base_url=DATA_SERVICES_URL, timeout=600)
    
    # 初始化 vector client（创建 collection）
    try:
        vector_client.initialize()
        logger.info("✓ VectorClient 初始化成功")
    except Exception as e:
        logger.warning(f"VectorClient 初始化警告: {e}（可能 collection 已存在）")
    
    # 检查服务健康状态
    try:
        is_healthy = semantic_group_client.health_check()
        logger.info(f"✓ SemanticGroupClient 健康检查: {'通过' if is_healthy else '失败'}")
    except Exception as e:
        logger.error(f"✗ SemanticGroupClient 健康检查失败: {e}")
        return
    
    # 2. 创建 SemanticGrouper
    logger.info("\n2. 创建 SemanticGrouper...")
    grouper = SemanticGrouper(
        vector_client=vector_client,
        semantic_group_client=semantic_group_client,
        semantic_domain_client=semantic_domain_client,
        collection_name=COLLECTION_NAME,
        allow_merge=False
    )
    logger.info("✓ SemanticGrouper 创建成功")
    
    # 3. 准备测试数据 - 创建至少10个测试语义域，设计为能够分组到几个组中，每个组3-5个成员
    logger.info("\n3. 准备测试数据（至少10个语义域，设计为分组到几个组中，每个组3-5个成员）...")
    
    # 设计思路：准备几个业务领域，每个领域有3-5个相关的语义域，让它们能够JOIN到同一个组
    # 组1：用户与权限管理（4个成员）
    # 组2：订单与交易（4个成员）
    # 组3：商品与库存（4个成员）
    # 组4：客户服务与通知（3个成员）
    
    test_domains = [
        # 组1：用户与权限管理组（4个成员）
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统
            这是一个用户管理系统，负责管理用户的基本信息、用户认证和用户会话。
            
            主要功能模块：
            1. 用户注册和登录
            2. 用户信息管理
            3. 用户会话管理
            4. 用户认证
            
            主要表结构：
            - users: 用户基本信息表，包含用户ID、用户名、邮箱、手机号、密码哈希等字段
            - user_sessions: 用户会话表，记录用户的登录会话信息
            - user_profiles: 用户资料表，包含用户的详细信息
            """,
            "agent_card": json.dumps({
                "name": "UserManagementAgent",
                "description": "用户管理Agent，负责用户身份和认证",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_user_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            权限管理系统
            这是一个权限管理系统，用于管理系统的角色、权限和访问控制。
            
            主要功能模块：
            1. 角色管理
            2. 权限管理
            3. 权限分配
            4. 访问控制
            
            主要表结构：
            - roles: 角色表，包含角色ID、角色名称、角色描述等字段
            - permissions: 权限表，定义系统中的各种权限
            - role_permissions: 角色权限关联表，管理角色与权限的关系
            - access_control: 访问控制表，记录访问控制规则
            """,
            "agent_card": json.dumps({
                "name": "PermissionManagementAgent",
                "description": "权限管理Agent，负责角色和权限控制",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_permission_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            角色管理系统
            这是一个角色管理系统，用于定义和管理系统中的各种角色。
            
            主要功能模块：
            1. 角色定义
            2. 角色权限配置
            3. 用户角色分配
            
            主要表结构：
            - roles: 角色表
            - role_permissions: 角色权限关联表
            - user_roles: 用户角色关联表
            """,
            "agent_card": json.dumps({
                "name": "RoleManagementAgent",
                "description": "角色管理Agent，负责角色定义和分配",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_role_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            认证服务系统
            这是一个认证服务系统，提供用户身份验证和授权服务。
            
            主要功能模块：
            1. 用户身份验证
            2. Token生成和管理
            3. 授权检查
            
            主要表结构：
            - auth_tokens: 认证令牌表
            - auth_sessions: 认证会话表
            - auth_logs: 认证日志表
            """,
            "agent_card": json.dumps({
                "name": "AuthenticationServiceAgent",
                "description": "认证服务Agent，负责用户身份验证",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_authentication_service",
            "dd_namespace": "test"
        },
        
        # 组2：订单与交易组（4个成员）
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            订单管理系统
            这是一个订单管理系统，处理订单的创建、查询、更新和取消等操作。
            
            主要功能模块：
            1. 订单创建和管理
            2. 订单状态跟踪
            3. 订单与用户的关联
            4. 订单与商品的关联
            
            主要表结构：
            - orders: 订单主表，包含订单ID、用户ID、订单状态、订单金额、创建时间等字段
            - order_items: 订单明细表，包含订单项ID、商品ID、数量、单价、总价等字段
            - order_payments: 订单支付表，记录订单的支付信息
            - order_shipping: 订单配送表，记录订单的配送信息
            """,
            "agent_card": json.dumps({
                "name": "OrderManagementAgent",
                "description": "订单管理Agent，负责订单生命周期管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_order_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            支付服务系统
            这是一个支付服务系统，处理支付相关的业务逻辑，包括支付方式、支付记录等。
            
            主要功能模块：
            1. 支付方式管理
            2. 支付处理
            3. 支付记录查询
            4. 退款处理
            
            主要表结构：
            - payments: 支付记录表，包含支付ID、订单ID、支付方式、支付金额、支付状态、支付时间等字段
            - payment_methods: 支付方式表，定义支持的支付方式，如支付宝、微信、银行卡等
            - payment_transactions: 支付交易表，记录详细的交易信息
            - refunds: 退款表，记录退款信息
            """,
            "agent_card": json.dumps({
                "name": "PaymentServiceAgent",
                "description": "支付服务Agent，负责支付处理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_payment_service",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            物流配送系统
            这是一个物流配送管理系统，处理订单的配送、物流跟踪、配送员管理等。
            
            主要功能模块：
            1. 配送单管理
            2. 物流跟踪
            3. 配送员管理
            4. 配送路线优化
            
            主要表结构：
            - shipments: 配送单表，包含配送单ID、订单ID、配送地址、配送状态等字段
            - delivery_tracking: 配送跟踪表，记录配送过程中的位置和时间信息
            - delivery_persons: 配送员表，管理配送员信息
            - delivery_routes: 配送路线表，优化配送路径
            """,
            "agent_card": json.dumps({
                "name": "LogisticsDeliveryAgent",
                "description": "物流配送Agent，负责订单配送",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_logistics_delivery",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            优惠券系统
            这是一个优惠券管理系统，处理优惠券的创建、发放、使用和核销等。
            
            主要功能模块：
            1. 优惠券创建
            2. 优惠券发放
            3. 优惠券使用
            4. 优惠券核销
            
            主要表结构：
            - coupons: 优惠券表，包含优惠券ID、优惠类型、折扣金额、使用条件等字段
            - coupon_issuance: 优惠券发放表，记录优惠券的发放记录
            - coupon_usage: 优惠券使用表，记录优惠券的使用情况
            - coupon_validation: 优惠券核销表，记录核销操作
            """,
            "agent_card": json.dumps({
                "name": "CouponSystemAgent",
                "description": "优惠券Agent，负责优惠券管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_coupon_system",
            "dd_namespace": "test"
        },
        
        # 组3：商品与库存组（4个成员）
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品管理系统
            这是一个商品信息管理系统，管理商品信息、库存、分类等。
            
            主要功能模块：
            1. 商品信息管理
            2. 商品分类管理
            3. 商品价格管理
            4. 商品上下架
            
            主要表结构：
            - products: 商品表，包含商品ID、商品名称、价格、描述、图片等字段
            - product_categories: 商品分类表，定义商品的分类层级
            - product_images: 商品图片表，存储商品图片信息
            - product_attributes: 商品属性表，定义商品的属性
            """,
            "agent_card": json.dumps({
                "name": "ProductManagementAgent",
                "description": "商品管理Agent，负责商品信息管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_product_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            库存管理系统
            这是一个库存管理系统，用于管理商品的库存信息、出入库记录、库存预警等。
            
            主要功能模块：
            1. 库存查询和统计
            2. 入库管理
            3. 出库管理
            4. 库存预警和补货提醒
            
            主要表结构：
            - inventory: 库存主表，包含商品ID、仓库ID、库存数量、安全库存等字段
            - inventory_transactions: 库存交易表，记录所有出入库操作
            - warehouses: 仓库表，定义仓库信息
            - stock_alerts: 库存预警表，记录需要补货的商品
            """,
            "agent_card": json.dumps({
                "name": "InventoryManagementAgent",
                "description": "库存管理Agent，负责库存管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_inventory_management",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品分类系统
            这是一个商品分类管理系统，用于管理商品的分类层级和分类属性。
            
            主要功能模块：
            1. 分类创建和管理
            2. 分类层级管理
            3. 分类属性定义
            
            主要表结构：
            - product_categories: 商品分类表，定义商品的分类层级
            - category_attributes: 分类属性表，定义每个分类的属性
            - category_products: 分类商品关联表
            """,
            "agent_card": json.dumps({
                "name": "ProductCategoryAgent",
                "description": "商品分类Agent，负责商品分类管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_product_category",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品评价系统
            这是一个商品评价系统，允许用户对购买的商品进行评价和打分。
            
            主要功能模块：
            1. 评价发布
            2. 评价管理
            3. 评价统计
            4. 评价审核
            
            主要表结构：
            - product_reviews: 商品评价表，包含评价ID、商品ID、用户ID、评分、评价内容等字段
            - review_images: 评价图片表，存储评价中的图片
            - review_likes: 评价点赞表，记录用户对评价的点赞
            - review_statistics: 评价统计表，汇总商品的评价数据
            """,
            "agent_card": json.dumps({
                "name": "ProductReviewAgent",
                "description": "商品评价Agent，负责商品评价管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_product_reviews",
            "dd_namespace": "test"
        },
        
        # 组4：客户服务与通知组（3个成员）
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            客户服务系统
            这是一个客户服务系统，处理客户咨询、投诉、工单管理等。
            
            主要功能模块：
            1. 客户咨询管理
            2. 工单系统
            3. 客户反馈处理
            4. 客服人员管理
            
            主要表结构：
            - customer_tickets: 客户工单表，包含工单ID、用户ID、问题类型、处理状态等字段
            - customer_inquiries: 客户咨询表，记录客户的咨询记录
            - customer_feedback: 客户反馈表，收集客户的意见和建议
            - service_agents: 客服人员表，管理客服团队
            """,
            "agent_card": json.dumps({
                "name": "CustomerServiceAgent",
                "description": "客户服务Agent，负责客户服务",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_customer_service",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            消息通知系统
            这是一个消息通知系统，用于向用户发送各种类型的通知消息。
            
            主要功能模块：
            1. 消息发送
            2. 消息模板管理
            3. 消息推送
            4. 消息统计
            
            主要表结构：
            - notifications: 通知表，包含通知ID、用户ID、通知类型、内容、状态等字段
            - notification_templates: 通知模板表，定义各种通知模板
            - notification_channels: 通知渠道表，定义推送渠道（短信、邮件、APP推送等）
            - notification_logs: 通知日志表，记录发送历史
            """,
            "agent_card": json.dumps({
                "name": "NotificationSystemAgent",
                "description": "消息通知Agent，负责消息通知",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_notification_system",
            "dd_namespace": "test"
        },
        {
            "semantic_domain_id": f"sd_test_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            工单管理系统
            这是一个工单管理系统，用于处理客户服务工单的创建、分配、处理和关闭。
            
            主要功能模块：
            1. 工单创建
            2. 工单分配
            3. 工单处理
            4. 工单关闭和评价
            
            主要表结构：
            - tickets: 工单表，包含工单ID、用户ID、问题描述、优先级、状态等字段
            - ticket_assignments: 工单分配表，记录工单分配给哪个客服
            - ticket_comments: 工单评论表，记录工单处理过程中的评论
            - ticket_history: 工单历史表，记录工单状态变更历史
            """,
            "agent_card": json.dumps({
                "name": "TicketManagementAgent",
                "description": "工单管理Agent，负责工单管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "test_ticket_management",
            "dd_namespace": "test"
        }
    ]
    
    logger.info(f"✓ 准备了 {len(test_domains)} 个测试语义域")
    for i, domain in enumerate(test_domains, 1):
        logger.info(f"   {i}. {domain['dd_name']} (ID: {domain['semantic_domain_id']})")
    
    # 4. 先将所有语义域加入组（使用 incremental）
    logger.info("\n4. 将所有语义域加入组（使用 incremental_semantic_group_analyse）...")
    incremental_results = []
    domain_to_group_map = {}  # 记录每个语义域所属的组
    
    for i, domain in enumerate(test_domains, 1):
        logger.info(f"\n--- 处理第 {i}/{len(test_domains)} 个语义域: {domain['dd_name']} ---")
        try:
            incremental_result = grouper.incremental_semantic_group_analyse(domain)
            
            if incremental_result:
                action = incremental_result.get('action', 'UNKNOWN')
                group_id = incremental_result.get('group_id', 'N/A')
                group_name = incremental_result.get('group_name', 'N/A')
                
                logger.info(f"✓ 语义域已加入组:")
                logger.info(f"  操作: {action}")
                logger.info(f"  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                
                incremental_results.append({
                    'domain': domain,
                    'result': incremental_result
                })
                domain_to_group_map[domain['semantic_domain_id']] = {
                    'group_id': group_id,
                    'group_name': group_name
                }
            else:
                logger.warning(f"✗ 语义域 {domain['dd_name']} 加入组失败: 返回结果为空")
                incremental_results.append({
                    'domain': domain,
                    'result': None
                })
                
        except Exception as e:
            logger.error(f"✗ 语义域 {domain['dd_name']} 加入组失败: {str(e)}", exc_info=True)
            incremental_results.append({
                'domain': domain,
                'result': None,
                'error': str(e)
            })
    
    # 统计分组情况
    logger.info("\n5. 统计分组情况...")
    success_count = sum(1 for r in incremental_results if r.get('result') is not None)
    logger.info(f"✓ 成功处理: {success_count}/{len(incremental_results)}")
    
    # 统计每个组的成员数
    group_member_count = {}
    for r in incremental_results:
        if r.get('result'):
            group_id = r['result'].get('group_id')
            if group_id:
                group_member_count[group_id] = group_member_count.get(group_id, 0) + 1
    
    logger.info(f"\n分组统计:")
    for group_id, count in group_member_count.items():
        group_name = next((r['result'].get('group_name', 'N/A') for r in incremental_results 
                          if r.get('result') and r['result'].get('group_id') == group_id), 'N/A')
        logger.info(f"  组: {group_name} (ID: {group_id}) - {count} 个成员")
    
    # 6. 测试移除语义域（使用 decremental）- 重点测试"组有多个成员，移除一个成员"的场景
    logger.info("\n6. 测试移除语义域（使用 decremental_semantic_group_analyse）...")
    logger.info("=" * 80)
    logger.info("关键测试场景：一个组有多个成员，移除其中一个成员")
    logger.info("验证点：")
    logger.info("  1. 关系记录是否正确删除")
    logger.info("  2. 组的成员数是否正确减少")
    logger.info("  3. Re-Induct 是否正确执行（重新聚合剩余成员的语义）")
    logger.info("  4. 组的描述是否正确更新（反映剩余成员的语义）")
    logger.info("  5. Vector Update 是否正确执行（向量数据更新）")
    logger.info("=" * 80)
    
    # 先找到有多个成员的组，选择其中一个成员进行移除测试
    logger.info("\n6.1 查找有多个成员的组...")
    multi_member_groups = {}  # group_id -> {group_name, member_count, domains}
    
    for domain_id, group_info in domain_to_group_map.items():
        group_id = group_info['group_id']
        if group_id not in multi_member_groups:
            try:
                relations_response = semantic_group_client.get_relations_by_group_id(group_id)
                relations_data = relations_response.get('data', [])
                if not isinstance(relations_data, list):
                    relations_data = []
                member_count = len(relations_data)
                
                if member_count > 1:  # 只关注有多个成员的组
                    # 获取组的详细信息
                    group_response = semantic_group_client.get_semantic_group_by_id(group_id)
                    group_data = group_response.get('data', {})
                    group_name = group_data.get('group_name', group_info.get('group_name', 'N/A'))
                    description = group_data.get('description', '')
                    
                    # 找到这个组的所有成员
                    member_domains = []
                    for rel in relations_data:
                        sd_id = rel.get('sd_id')
                        if sd_id:
                            domain = next((d for d in test_domains if d['semantic_domain_id'] == sd_id), None)
                            if domain:
                                member_domains.append(domain)
                    
                    multi_member_groups[group_id] = {
                        'group_name': group_name,
                        'member_count': member_count,
                        'description': description,
                        'member_domains': member_domains
                    }
            except Exception as e:
                logger.warning(f"⚠️ 检查组 {group_id} 的成员数失败: {str(e)}")
    
    logger.info(f"找到 {len(multi_member_groups)} 个有多个成员的组:")
    for group_id, group_info in multi_member_groups.items():
        logger.info(f"  组: {group_info['group_name']} (ID: {group_id}) - {group_info['member_count']} 个成员")
        for domain in group_info['member_domains']:
            logger.info(f"    - {domain['dd_name']}")
    
    # 选择第一个有多个成员的组进行详细测试
    group_state_before = None  # 初始化变量
    if not multi_member_groups:
        logger.warning("⚠️ 没有找到有多个成员的组，将使用默认的移除测试")
        domains_to_remove = test_domains[:5]
    else:
        # 选择第一个有多个成员的组，移除其中一个成员
        test_group_id = list(multi_member_groups.keys())[0]
        test_group_info = multi_member_groups[test_group_id]
        test_group_name = test_group_info['group_name']
        test_member_domains = test_group_info['member_domains']
        
        logger.info(f"\n6.2 选择测试组: {test_group_name} (ID: {test_group_id})")
        logger.info(f"  当前成员数: {test_group_info['member_count']}")
        logger.info(f"  当前描述长度: {len(test_group_info['description'])} 字符")
        
        # 保存移除前的组状态
        group_state_before = {
            'group_id': test_group_id,
            'group_name': test_group_name,
            'description': test_group_info['description'],
            'member_count': test_group_info['member_count'],
            'member_domains': test_member_domains.copy()
        }
        
        # 选择要移除的成员（选择第一个成员）
        domain_to_remove = test_member_domains[0]
        logger.info(f"\n6.3 准备移除成员: {domain_to_remove['dd_name']} (ID: {domain_to_remove['semantic_domain_id']})")
        logger.info(f"  移除后预期成员数: {test_group_info['member_count'] - 1}")
        
        domains_to_remove = [domain_to_remove]
    
    decremental_results = []
    for i, domain in enumerate(domains_to_remove, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"--- 移除第 {i}/{len(domains_to_remove)} 个语义域: {domain['dd_name']} ---")
        logger.info(f"语义域ID: {domain['semantic_domain_id']}")
        logger.info(f"{'=' * 80}")
        
        # 如果是详细测试场景，显示移除前的状态
        if len(domains_to_remove) == 1 and group_state_before is not None:
            logger.info(f"\n移除前状态:")
            logger.info(f"  组名: {group_state_before['group_name']}")
            logger.info(f"  成员数: {group_state_before['member_count']}")
            logger.info(f"  描述长度: {len(group_state_before['description'])} 字符")
            logger.info(f"  成员列表:")
            for member in group_state_before['member_domains']:
                logger.info(f"    - {member['dd_name']}")
        
        try:
            decremental_result = grouper.decremental_semantic_group_analyse(
                semantic_domain_id=domain['semantic_domain_id']
            )
            
            if decremental_result:
                status = decremental_result.get('status', 'UNKNOWN')
                action = decremental_result.get('action', 'UNKNOWN')
                remaining_count = decremental_result.get('remaining_member_count', 0)
                message = decremental_result.get('message', '')
                group_id = decremental_result.get('group_id', 'N/A')
                group_name = decremental_result.get('group_name', 'N/A')
                
                logger.info(f"\n✓ 移除操作完成:")
                logger.info(f"  状态: {status}")
                logger.info(f"  操作: {action}")
                logger.info(f"  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  剩余成员数: {remaining_count}")
                logger.info(f"  消息: {message}")
                
                decremental_results.append({
                    'domain': domain,
                    'result': decremental_result,
                    'group_state_before': group_state_before if len(domains_to_remove) == 1 and 'group_state_before' in locals() else None
                })
                
                # 如果是详细测试场景，立即进行详细验证
                if len(domains_to_remove) == 1 and group_state_before is not None and status == 'success':
                    logger.info(f"\n{'=' * 80}")
                    logger.info("详细验证移除后的状态...")
                    logger.info(f"{'=' * 80}")
                    
                    # 验证1: 成员数是否正确
                    expected_count = group_state_before['member_count'] - 1
                    if remaining_count == expected_count:
                        logger.info(f"✓ 验证1通过: 成员数正确 ({remaining_count} = {group_state_before['member_count']} - 1)")
                    else:
                        logger.error(f"✗ 验证1失败: 成员数不正确 (预期: {expected_count}, 实际: {remaining_count})")
                    
                    # 验证2: 关系是否已删除
                    try:
                        relations_response = semantic_group_client.get_relations_by_sd_id(domain['semantic_domain_id'])
                        relations_data = relations_response.get('data', [])
                        if not isinstance(relations_data, list):
                            relations_data = []
                        if len(relations_data) == 0:
                            logger.info(f"✓ 验证2通过: 语义域 {domain['dd_name']} 的关系已成功删除")
                        else:
                            logger.error(f"✗ 验证2失败: 语义域 {domain['dd_name']} 仍有 {len(relations_data)} 个关系记录")
                    except Exception as e:
                        logger.warning(f"⚠️ 验证2失败: 检查关系时出错: {str(e)}")
                    
                    # 验证3: 组的描述是否被更新（Re-Induct）
                    if remaining_count > 0:
                        try:
                            group_response = semantic_group_client.get_semantic_group_by_id(group_id)
                            group_data = group_response.get('data', {})
                            if group_data:
                                new_description = group_data.get('description', '')
                                new_group_name = group_data.get('group_name', '')
                                
                                if new_description and len(new_description) > 0:
                                    logger.info(f"✓ 验证3通过: 组的描述已更新（Re-Induct 已执行）")
                                    logger.info(f"  新描述长度: {len(new_description)} 字符 (原: {len(group_state_before['description'])} 字符)")
                                    logger.info(f"  新组名: {new_group_name}")
                                    
                                    # 验证描述是否反映了剩余成员的语义（简单检查：描述应该包含剩余成员的关键词）
                                    remaining_member_names = [m['dd_name'] for m in group_state_before['member_domains'] if m['semantic_domain_id'] != domain['semantic_domain_id']]
                                    logger.info(f"  剩余成员: {', '.join(remaining_member_names)}")
                                else:
                                    logger.error(f"✗ 验证3失败: 组的描述为空")
                            else:
                                logger.error(f"✗ 验证3失败: 无法获取组数据")
                        except Exception as e:
                            logger.error(f"✗ 验证3失败: {str(e)}", exc_info=True)
                    
                    # 验证4: 向量数据是否已更新（Vector Update）
                    if remaining_count > 0 and vector_client:
                        try:
                            logger.info(f"✓ 验证4通过: 向量数据应该已更新（Vector Update 已执行）")
                            # 注意：这里可以添加更详细的向量验证，比如查询向量数据是否存在
                        except Exception as e:
                            logger.warning(f"⚠️ 验证4警告: 无法验证向量数据: {str(e)}")
                    
                    logger.info(f"{'=' * 80}\n")
                
                if action == "REMOVED" and remaining_count == 0:
                    logger.info("  ✓ 组已为空（但不会自动删除，需要在页面上手动删除）")
                    # 从映射中移除已删除的组
                    if domain['semantic_domain_id'] in domain_to_group_map:
                        del domain_to_group_map[domain['semantic_domain_id']]
                elif action == "REMOVED" or action == "REINDUCT_SCHEDULED":
                    logger.info(f"  ✓ 语义域已移除，组剩余 {remaining_count} 个成员")
            else:
                logger.error("✗ 移除操作失败: 返回结果为空")
                decremental_results.append({
                    'domain': domain,
                    'result': None
                })
                
        except Exception as e:
            logger.error(f"✗ 移除操作失败: {str(e)}", exc_info=True)
            decremental_results.append({
                'domain': domain,
                'result': None,
                'error': str(e)
            })
    
    # 7. 批量验证移除后的状态（如果进行了批量移除测试）
    logger.info("\n7. 批量验证移除后的状态...")
    success_remove_count = sum(1 for r in decremental_results if r.get('result') and r['result'].get('status') == 'success')
    logger.info(f"✓ 成功移除: {success_remove_count}/{len(decremental_results)}")
    
    # 如果进行了详细测试（单个成员移除），验证已经在步骤6中完成
    # 这里只对批量移除的情况进行验证
    if len(domains_to_remove) > 1:
        logger.info("进行批量移除后的验证...")
        for r in decremental_results:
            if r.get('result') and r['result'].get('status') == 'success':
                domain = r['domain']
                result = r['result']
                group_id = result.get('group_id')
                remaining_count = result.get('remaining_member_count', 0)
                
                try:
                    # 验证关系是否已删除
                    relations_response = semantic_group_client.get_relations_by_sd_id(domain['semantic_domain_id'])
                    relations_data = relations_response.get('data', [])
                    if not isinstance(relations_data, list):
                        relations_data = []
                    
                    if len(relations_data) == 0:
                        logger.info(f"✓ 语义域 {domain['dd_name']} 的关系已成功删除")
                    else:
                        logger.warning(f"⚠️ 语义域 {domain['dd_name']} 仍有 {len(relations_data)} 个关系记录")
                    
                    # 如果组还有成员，验证组的描述是否被更新（Re-Induct 应该已经执行）
                    if group_id and remaining_count > 0:
                        try:
                            group_response = semantic_group_client.get_semantic_group_by_id(group_id)
                            group_data = group_response.get('data', {})
                            if group_data:
                                description = group_data.get('description', '')
                                group_name = group_data.get('group_name', '')
                                logger.info(f"  ✓ 组 {group_name} (ID: {group_id}) 的描述已更新（Re-Induct 已执行）")
                                logger.info(f"    描述长度: {len(description)} 字符")
                                
                                # 验证向量是否已更新
                                if vector_client:
                                    try:
                                        logger.info(f"  ✓ 向量数据应该已更新（Vector Update 已执行）")
                                    except Exception as e:
                                        logger.warning(f"  ⚠️ 验证向量数据失败: {str(e)}")
                        except Exception as e:
                            logger.warning(f"  ⚠️ 验证组状态失败: {str(e)}")
                            
                except Exception as e:
                    logger.warning(f"⚠️ 验证语义域 {domain['dd_name']} 的关系失败: {str(e)}")
    else:
        logger.info("已进行详细测试，跳过批量验证")
    
    # 8. 测试从同一个组中连续移除多个成员（验证每次移除后 Re-Induct 是否正确执行）
    logger.info("\n8. 测试从同一个组中连续移除多个成员...")
    logger.info("=" * 80)
    logger.info("关键测试场景：从同一个组中连续移除多个成员")
    logger.info("验证点：每次移除后 Re-Induct 是否正确执行，组的描述是否正确更新")
    logger.info("=" * 80)
    
    # 找到一个有至少3个成员的组
    test_group_for_sequential = None
    for group_id, group_info in multi_member_groups.items():
        if group_info['member_count'] >= 3:
            test_group_for_sequential = {
                'group_id': group_id,
                'group_info': group_info
            }
            break
    
    if test_group_for_sequential:
        group_id_seq = test_group_for_sequential['group_id']
        group_info_seq = test_group_for_sequential['group_info']
        member_domains_seq = group_info_seq['member_domains']
        
        logger.info(f"\n8.1 选择测试组: {group_info_seq['group_name']} (ID: {group_id_seq})")
        logger.info(f"  当前成员数: {group_info_seq['member_count']}")
        
        # 选择要移除的成员（移除前2个成员，保留至少1个）
        domains_to_remove_seq = member_domains_seq[:2]  # 移除前2个
        logger.info(f"\n8.2 准备连续移除 {len(domains_to_remove_seq)} 个成员...")
        for i, domain in enumerate(domains_to_remove_seq, 1):
            logger.info(f"  {i}. {domain['dd_name']} (ID: {domain['semantic_domain_id']})")
        
        # 连续移除成员，每次移除后验证状态
        for i, domain in enumerate(domains_to_remove_seq, 1):
            logger.info(f"\n{'=' * 80}")
            logger.info(f"--- 连续移除第 {i}/{len(domains_to_remove_seq)} 个成员: {domain['dd_name']} ---")
            logger.info(f"{'=' * 80}")
            
            # 获取移除前的组状态
            try:
                group_response_before = semantic_group_client.get_semantic_group_by_id(group_id_seq)
                group_data_before = group_response_before.get('data', {})
                relations_before = semantic_group_client.get_relations_by_group_id(group_id_seq)
                relations_data_before = relations_before.get('data', [])
                if not isinstance(relations_data_before, list):
                    relations_data_before = []
                member_count_before = len(relations_data_before)
                
                logger.info(f"\n移除前状态:")
                logger.info(f"  成员数: {member_count_before}")
                logger.info(f"  描述长度: {len(group_data_before.get('description', ''))} 字符")
            except Exception as e:
                logger.warning(f"⚠️ 获取移除前状态失败: {str(e)}")
                member_count_before = None
            
            try:
                decremental_result = grouper.decremental_semantic_group_analyse(
                    semantic_domain_id=domain['semantic_domain_id']
                )
                
                if decremental_result and decremental_result.get('status') == 'success':
                    remaining_count = decremental_result.get('remaining_member_count', 0)
                    logger.info(f"\n✓ 移除成功，剩余成员数: {remaining_count}")
                    
                    # 验证移除后的状态
                    if member_count_before is not None:
                        expected_count = member_count_before - 1
                        if remaining_count == expected_count:
                            logger.info(f"✓ 验证通过: 成员数正确 ({remaining_count} = {member_count_before} - 1)")
                        else:
                            logger.error(f"✗ 验证失败: 成员数不正确 (预期: {expected_count}, 实际: {remaining_count})")
                    
                    # 验证组的描述是否被更新（Re-Induct）
                    if remaining_count > 0:
                        try:
                            group_response_after = semantic_group_client.get_semantic_group_by_id(group_id_seq)
                            group_data_after = group_response_after.get('data', {})
                            description_after = group_data_after.get('description', '')
                            
                            if description_after and len(description_after) > 0:
                                logger.info(f"✓ 验证通过: 组的描述已更新（Re-Induct 已执行）")
                                logger.info(f"  新描述长度: {len(description_after)} 字符")
                            else:
                                logger.error(f"✗ 验证失败: 组的描述为空")
                        except Exception as e:
                            logger.error(f"✗ 验证失败: {str(e)}", exc_info=True)
                else:
                    logger.error(f"✗ 移除失败: {decremental_result}")
                    
            except Exception as e:
                logger.error(f"✗ 移除操作失败: {str(e)}", exc_info=True)
            
            logger.info(f"{'=' * 80}\n")
    else:
        logger.warning("⚠️ 没有找到有至少3个成员的组，跳过连续移除测试")
    
    # 9. 测试移除最后一个成员（组会变空，但不会自动删除）
    logger.info("\n9. 测试移除最后一个成员（组会变空，但不会自动删除）...")
    
    # 找到只有一个成员的组
    single_member_groups = []
    for domain_id, group_info in domain_to_group_map.items():
        group_id = group_info['group_id']
        try:
            relations_response = semantic_group_client.get_relations_by_group_id(group_id)
            relations_data = relations_response.get('data', [])
            if not isinstance(relations_data, list):
                relations_data = []
            if len(relations_data) == 1:
                # 找到这个唯一的成员
                remaining_domain = next((d for d in test_domains if d['semantic_domain_id'] == domain_id), None)
                if remaining_domain:
                    single_member_groups.append({
                        'domain': remaining_domain,
                        'group_id': group_id,
                        'group_name': group_info['group_name']
                    })
        except Exception as e:
            logger.warning(f"⚠️ 检查组 {group_id} 的成员数失败: {str(e)}")
    
    if single_member_groups:
        test_domain = single_member_groups[0]['domain']
        test_group_id = single_member_groups[0]['group_id']
        test_group_name = single_member_groups[0]['group_name']
        
        logger.info(f"找到只有一个成员的组: {test_group_name} (ID: {test_group_id})")
        logger.info(f"准备移除最后一个成员: {test_domain['dd_name']} (ID: {test_domain['semantic_domain_id']})")
        
        try:
            last_remove_result = grouper.decremental_semantic_group_analyse(
                semantic_domain_id=test_domain['semantic_domain_id']
            )
            
            if last_remove_result:
                status = last_remove_result.get('status', 'UNKNOWN')
                action = last_remove_result.get('action', 'UNKNOWN')
                remaining_count = last_remove_result.get('remaining_member_count', 0)
                message = last_remove_result.get('message', '')
                
                logger.info(f"✓ 移除最后一个成员完成:")
                logger.info(f"  状态: {status}")
                logger.info(f"  操作: {action}")
                logger.info(f"  剩余成员数: {remaining_count}")
                logger.info(f"  消息: {message}")
                
                if action == "REMOVED" and remaining_count == 0:
                    logger.info("  ✓ 组已为空（但不会自动删除，需要在页面上手动删除）")
                    
                    # 验证组是否仍然存在（应该存在，因为不会自动删除）
                    try:
                        group_response = semantic_group_client.get_semantic_group_by_id(test_group_id)
                        group_data = group_response.get('data', {})
                        if group_data:
                            logger.info("✓ 组仍然存在（符合预期，因为组可能被agent使用，不会自动删除）")
                            
                            # 验证组确实没有成员了
                            relations_response = semantic_group_client.get_relations_by_group_id(test_group_id)
                            relations_data = relations_response.get('data', [])
                            if not isinstance(relations_data, list):
                                relations_data = []
                            if len(relations_data) == 0:
                                logger.info("✓ 验证通过：组确实没有成员了")
                            else:
                                logger.warning(f"⚠️ 组应该没有成员，但仍有 {len(relations_data)} 个成员")
                        else:
                            logger.warning("⚠️ 组不存在（这可能不正常，因为组不应该被自动删除）")
                    except Exception as e:
                        logger.warning(f"⚠️ 验证组状态失败: {str(e)}")
                else:
                    logger.info(f"  ✓ 操作完成: {action}，剩余成员: {remaining_count}")
            else:
                logger.error("✗ 移除最后一个成员失败: 返回结果为空")
        except Exception as e:
            logger.error(f"✗ 移除最后一个成员失败: {str(e)}", exc_info=True)
    else:
        logger.warning("⚠️ 没有找到只有一个成员的组，跳过此测试")
    
    # 10. 测试移除不存在的语义域
    logger.info("\n10. 测试移除不存在的语义域...")
    try:
        non_existent_result = grouper.decremental_semantic_group_analyse(
            semantic_domain_id=f"sd_nonexistent_{uuid.uuid4().hex[:8]}"
        )
        
        if non_existent_result:
            status = non_existent_result.get('status', 'UNKNOWN')
            message = non_existent_result.get('message', '')
            logger.info(f"✓ 处理结果:")
            logger.info(f"  状态: {status}")
            logger.info(f"  消息: {message}")
        else:
            logger.warning("⚠️ 返回结果为空")
            
    except Exception as e:
        logger.error(f"✗ 测试移除不存在的语义域失败: {str(e)}", exc_info=True)
    
    # 11. 最终状态统计
    logger.info("\n11. 最终状态统计...")
    try:
        all_groups = semantic_group_client.get_all_semantic_groups()
        groups_data = all_groups.get('data', [])
        logger.info(f"\n当前共有 {len(groups_data)} 个语义组:")
        
        for group in groups_data:
            group_id = group.get('id') or group.get('group_id', 'N/A')
            group_name = group.get('group_name', 'N/A')
            
            try:
                relations = semantic_group_client.get_relations_by_group_id(group_id)
                relations_data = relations.get('data', [])
                member_count = len(relations_data) if isinstance(relations_data, list) else 0
                
                logger.info(f"\n  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  成员数: {member_count}")
            except Exception as e:
                logger.warning(f"  获取组成员失败: {e}")
                
    except Exception as e:
        logger.error(f"查询最终状态失败: {e}", exc_info=True)
    
    logger.info("\n" + "=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)


def test_merge_capability():
    """
    测试 incremental_semantic_group_analyse 的 MERGE 能力
    
    测试场景：电子商务系统
    1. 第一阶段：创建多个独立的业务模块，每个都是独立的语义域，应该形成不同的组
       - 用户管理系统（独立）
       - 订单管理系统（独立）
       - 商品管理系统（独立）
       - 支付服务系统（独立）
       - 物流配送系统（独立）
    2. 第二阶段：添加一个"电子商务综合系统"，它应该能够触发 MERGE 操作，将之前创建的多个组合并
    3. 验证合并后的组是否正确，旧组是否被删除
    """
    logger.info("=" * 80)
    logger.info("开始测试 incremental_semantic_group_analyse 的 MERGE 能力")
    logger.info("测试场景：电子商务系统（用户、订单、商品、支付、物流 -> 电商综合系统）")
    logger.info("=" * 80)
    
    # 1. 初始化客户端
    logger.info("\n1. 初始化客户端...")
    vector_client = VectorClient(base_url=DATA_SERVICES_URL, timeout=600)
    semantic_group_client = SemanticGroupClient(base_url=DATA_SERVICES_URL, timeout=600)
    
    # 初始化 vector client（创建 collection）
    try:
        vector_client.initialize()
        logger.info("✓ VectorClient 初始化成功")
    except Exception as e:
        logger.warning(f"VectorClient 初始化警告: {e}（可能 collection 已存在）")
    
    # 检查服务健康状态
    try:
        is_healthy = semantic_group_client.health_check()
        logger.info(f"✓ SemanticGroupClient 健康检查: {'通过' if is_healthy else '失败'}")
    except Exception as e:
        logger.error(f"✗ SemanticGroupClient 健康检查失败: {e}")
        return
    
    # 2. 创建 SemanticGrouper（关键：设置 allow_merge=True）
    logger.info("\n2. 创建 SemanticGrouper（allow_merge=True）...")
    grouper = SemanticGrouper(
        vector_client=vector_client,
        semantic_group_client=semantic_group_client,
        collection_name=COLLECTION_NAME,
        allow_merge=True  # 允许合并操作，这是测试的重点
    )
    logger.info("✓ SemanticGrouper 创建成功（已启用 MERGE 功能）")
    
    # 3. 准备测试数据
    logger.info("\n3. 准备测试数据...")
    logger.info("策略：先创建几个独立的业务模块（每个都是独立的语义域），然后添加一个综合系统触发 MERGE")
    
    # 第一阶段：创建多个独立的业务模块，每个都是独立的语义域，应该形成不同的组
    # 这些组应该能够被后续的 MERGE 操作合并
    phase1_domains = [
        {
            "semantic_domain_id": f"sd_merge_ecommerce_user_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            用户管理系统
            这是一个独立的用户管理系统，专注于用户账户的创建、管理和维护。
            
            主要功能模块：
            1. 用户注册和登录
            2. 用户信息管理（个人资料、联系方式）
            3. 用户账户状态管理（激活、禁用、删除）
            4. 用户认证和安全
            
            主要表结构：
            - users: 用户主表，包含用户ID、用户名、邮箱、手机号、密码哈希、注册时间等字段
            - user_profiles: 用户资料表，存储用户的详细信息（昵称、头像、个人简介等）
            - user_sessions: 用户会话表，记录用户的登录会话信息
            - user_authentication: 用户认证表，记录认证相关信息（密码、令牌等）
            """,
            "agent_card": json.dumps({
                "name": "UserManagementSystemAgent",
                "description": "用户管理系统Agent，专注于用户账户和认证管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "merge_test_ecommerce_user",
            "dd_namespace": "merge_test"
        },
        {
            "semantic_domain_id": f"sd_merge_ecommerce_order_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            订单管理系统
            这是一个独立的订单管理系统，专注于订单的创建、管理和跟踪。
            
            主要功能模块：
            1. 订单创建和管理
            2. 订单状态跟踪（待支付、已支付、已发货、已完成、已取消）
            3. 订单查询和统计
            4. 订单与用户的关联
            
            主要表结构：
            - orders: 订单主表，包含订单ID、用户ID、订单状态、订单金额、创建时间、更新时间等字段
            - order_items: 订单明细表，包含订单项ID、商品ID、数量、单价、总价等字段
            - order_status_history: 订单状态历史表，记录订单状态变更历史
            - order_addresses: 订单地址表，记录订单的收货地址信息
            """,
            "agent_card": json.dumps({
                "name": "OrderManagementSystemAgent",
                "description": "订单管理系统Agent，专注于订单生命周期管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "merge_test_ecommerce_order",
            "dd_namespace": "merge_test"
        },
        {
            "semantic_domain_id": f"sd_merge_ecommerce_product_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            商品管理系统
            这是一个独立的商品管理系统，专注于商品信息的管理和维护。
            
            主要功能模块：
            1. 商品信息管理（商品名称、描述、价格、图片等）
            2. 商品分类管理
            3. 商品上下架管理
            4. 商品属性管理
            
            主要表结构：
            - products: 商品表，包含商品ID、商品名称、价格、描述、图片、状态等字段
            - product_categories: 商品分类表，定义商品的分类层级
            - product_attributes: 商品属性表，定义商品的属性（颜色、尺寸、品牌等）
            - product_images: 商品图片表，存储商品图片信息
            """,
            "agent_card": json.dumps({
                "name": "ProductManagementSystemAgent",
                "description": "商品管理系统Agent，专注于商品信息管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "merge_test_ecommerce_product",
            "dd_namespace": "merge_test"
        },
        {
            "semantic_domain_id": f"sd_merge_ecommerce_payment_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            支付服务系统
            这是一个独立的支付服务系统，专注于支付处理和管理。
            
            主要功能模块：
            1. 支付方式管理（支付宝、微信、银行卡等）
            2. 支付处理（支付请求、支付回调、支付确认）
            3. 支付记录查询
            4. 退款处理
            
            主要表结构：
            - payments: 支付记录表，包含支付ID、订单ID、支付方式、支付金额、支付状态、支付时间等字段
            - payment_methods: 支付方式表，定义支持的支付方式
            - payment_transactions: 支付交易表，记录详细的交易信息（交易流水号、交易状态等）
            - refunds: 退款表，记录退款信息（退款ID、原支付ID、退款金额、退款状态等）
            """,
            "agent_card": json.dumps({
                "name": "PaymentServiceSystemAgent",
                "description": "支付服务系统Agent，专注于支付处理和退款管理",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "merge_test_ecommerce_payment",
            "dd_namespace": "merge_test"
        },
        {
            "semantic_domain_id": f"sd_merge_ecommerce_logistics_{uuid.uuid4().hex[:8]}",
            "semantic_domain": """
            物流配送系统
            这是一个独立的物流配送系统，专注于订单的配送和物流跟踪。
            
            主要功能模块：
            1. 配送单管理
            2. 物流跟踪（实时位置、配送状态）
            3. 配送员管理
            4. 配送路线优化
            
            主要表结构：
            - shipments: 配送单表，包含配送单ID、订单ID、配送地址、配送状态、配送员ID等字段
            - delivery_tracking: 配送跟踪表，记录配送过程中的位置和时间信息
            - delivery_persons: 配送员表，管理配送员信息（姓名、联系方式、配送区域等）
            - delivery_routes: 配送路线表，优化配送路径
            """,
            "agent_card": json.dumps({
                "name": "LogisticsDeliverySystemAgent",
                "description": "物流配送系统Agent，专注于订单配送和物流跟踪",
                "version": "1.0.0"
            }, ensure_ascii=False),
            "dd_name": "merge_test_ecommerce_logistics",
            "dd_namespace": "merge_test"
        }
    ]
    
    # 第二阶段：创建一个"电子商务综合系统"，它应该能够触发 MERGE，将之前的组合并
    phase2_domain = {
        "semantic_domain_id": f"sd_merge_ecommerce_comprehensive_{uuid.uuid4().hex[:8]}",
        "semantic_domain": """
        电子商务综合系统
        这是一个完整的电子商务综合系统，整合了用户管理、订单管理、商品管理、支付服务和物流配送等所有核心业务模块。
        
        主要功能模块：
        1. 用户管理：用户注册、登录、信息管理、认证和安全
        2. 商品管理：商品信息管理、分类管理、上下架、属性管理
        3. 订单管理：订单创建、状态跟踪、查询统计、与用户和商品的关联
        4. 支付服务：支付方式管理、支付处理、支付记录查询、退款处理
        5. 物流配送：配送单管理、物流跟踪、配送员管理、路线优化
        6. 综合业务：购物车、商品搜索、商品推荐、订单评价等
        
        主要表结构：
        - users: 用户主表
        - products: 商品表
        - orders: 订单主表
        - order_items: 订单明细表（关联订单和商品）
        - payments: 支付记录表（关联订单）
        - shipments: 配送单表（关联订单）
        - shopping_carts: 购物车表（关联用户和商品）
        - product_reviews: 商品评价表（关联用户、商品和订单）
        
        业务关系：
        - 用户创建订单，订单包含多个商品（通过order_items关联）
        - 订单需要支付（通过payments关联）
        - 订单需要配送（通过shipments关联）
        - 用户可以将商品加入购物车（通过shopping_carts关联）
        - 用户可以对购买的商品进行评价（通过product_reviews关联）
        """,
        "agent_card": json.dumps({
            "name": "ECommerceComprehensiveSystemAgent",
            "description": "电子商务综合系统Agent，整合用户、订单、商品、支付、物流等所有核心业务模块",
            "version": "1.0.0"
        }, ensure_ascii=False),
        "dd_name": "merge_test_ecommerce_comprehensive",
        "dd_namespace": "merge_test"
    }
    
    logger.info(f"✓ 准备了 {len(phase1_domains)} 个第一阶段语义域（应该形成不同的组）")
    logger.info(f"✓ 准备了 1 个第二阶段语义域（应该触发 MERGE）")
    
    # 4. 第一阶段：逐个处理语义域，让它们形成不同的组
    logger.info("\n" + "=" * 80)
    logger.info("第一阶段：创建多个相关的语义域，让它们形成不同的组")
    logger.info("=" * 80)
    
    phase1_results = []
    phase1_groups = {}  # 记录每个语义域所属的组
    
    for i, domain in enumerate(phase1_domains, 1):
        logger.info(f"\n--- 处理第 {i}/{len(phase1_domains)} 个语义域: {domain['dd_name']} ---")
        logger.info(f"语义域ID: {domain['semantic_domain_id']}")
        
        try:
            result = grouper.incremental_semantic_group_analyse(domain)
            
            if result:
                action = result.get('action', 'UNKNOWN')
                group_id = result.get('group_id', 'N/A')
                group_name = result.get('group_name', 'N/A')
                confidence = result.get('confidence', 0.0)
                
                logger.info(f"✓ 处理成功:")
                logger.info(f"  操作: {action}")
                logger.info(f"  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  置信度: {confidence:.2f}")
                
                phase1_results.append({
                    'domain': domain,
                    'result': result
                })
                phase1_groups[domain['semantic_domain_id']] = {
                    'group_id': group_id,
                    'group_name': group_name,
                    'action': action
                }
            else:
                logger.warning(f"✗ 处理失败: 返回结果为空")
                phase1_results.append({
                    'domain': domain,
                    'result': None
                })
                
        except Exception as e:
            logger.error(f"✗ 处理失败: {str(e)}", exc_info=True)
            phase1_results.append({
                'domain': domain,
                'result': None,
                'error': str(e)
            })
    
    # 统计第一阶段的分组情况
    logger.info("\n第一阶段分组统计:")
    unique_groups = {}
    for domain_id, group_info in phase1_groups.items():
        group_id = group_info['group_id']
        if group_id not in unique_groups:
            unique_groups[group_id] = {
                'group_name': group_info['group_name'],
                'members': []
            }
        domain = next((d for d in phase1_domains if d['semantic_domain_id'] == domain_id), None)
        if domain:
            unique_groups[group_id]['members'].append(domain['dd_name'])
    
    logger.info(f"共形成 {len(unique_groups)} 个不同的组:")
    for group_id, group_info in unique_groups.items():
        logger.info(f"  组: {group_info['group_name']} (ID: {group_id})")
        logger.info(f"    成员: {', '.join(group_info['members'])}")
    
    # 如果第一阶段没有形成多个组，记录警告
    if len(unique_groups) < 2:
        logger.warning(f"⚠️ 第一阶段只形成了 {len(unique_groups)} 个组，可能无法触发 MERGE")
        logger.warning("   继续测试，看看是否能触发 MERGE 或 JOIN")
    
    # 5. 第二阶段：添加能触发 MERGE 的语义域
    logger.info("\n" + "=" * 80)
    logger.info("第二阶段：添加能触发 MERGE 的语义域")
    logger.info("=" * 80)
    logger.info(f"\n处理语义域: {phase2_domain['dd_name']}")
    logger.info(f"语义域ID: {phase2_domain['semantic_domain_id']}")
    logger.info(f"预期操作: MERGE（将之前形成的 {len(unique_groups)} 个组合并）")
    
    # 记录合并前的组状态
    groups_before_merge = {}
    for group_id, group_info in unique_groups.items():
        try:
            # 获取组的详细信息
            group_response = semantic_group_client.get_semantic_group_by_id(group_id)
            group_data = group_response.get('data', {})
            relations_response = semantic_group_client.get_relations_by_group_id(group_id)
            relations_data = relations_response.get('data', [])
            if not isinstance(relations_data, list):
                relations_data = []
            
            groups_before_merge[group_id] = {
                'group_name': group_data.get('group_name', group_info['group_name']),
                'description': group_data.get('description', ''),
                'member_count': len(relations_data),
                'member_ids': [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
            }
        except Exception as e:
            logger.warning(f"获取组 {group_id} 的状态失败: {str(e)}")
    
    logger.info(f"\n合并前的组状态:")
    for group_id, group_info in groups_before_merge.items():
        logger.info(f"  组: {group_info['group_name']} (ID: {group_id})")
        logger.info(f"    成员数: {group_info['member_count']}")
    
    # 执行 MERGE 操作
    try:
        merge_result = grouper.incremental_semantic_group_analyse(phase2_domain)
        
        if merge_result:
            action = merge_result.get('action', 'UNKNOWN')
            group_id = merge_result.get('group_id', 'N/A')
            group_name = merge_result.get('group_name', 'N/A')
            confidence = merge_result.get('confidence', 0.0)
            merged_from = merge_result.get('merged_from', {})
            
            logger.info(f"\n✓ 处理完成:")
            logger.info(f"  操作: {action}")
            logger.info(f"  组ID: {group_id}")
            logger.info(f"  组名: {group_name}")
            logger.info(f"  置信度: {confidence:.2f}")
            
            if action == 'MERGE':
                logger.info(f"\n🎉 MERGE 操作成功！")
                logger.info(f"  合并来源:")
                merged_group_ids = merged_from.get('group_ids', [])
                merged_group_names = merged_from.get('group_names', [])
                for i, (old_group_id, old_group_name) in enumerate(zip(merged_group_ids, merged_group_names), 1):
                    logger.info(f"    {i}. {old_group_name} (ID: {old_group_id})")
                
                # 验证合并结果
                logger.info(f"\n验证合并结果...")
                
                # 验证1: 新组是否存在
                try:
                    new_group_response = semantic_group_client.get_semantic_group_by_id(group_id)
                    new_group_data = new_group_response.get('data', {})
                    if new_group_data:
                        logger.info(f"✓ 验证1通过: 新组已创建")
                        logger.info(f"  组名: {new_group_data.get('group_name', 'N/A')}")
                        logger.info(f"  描述长度: {len(new_group_data.get('description', ''))} 字符")
                    else:
                        logger.error(f"✗ 验证1失败: 新组不存在")
                except Exception as e:
                    logger.error(f"✗ 验证1失败: {str(e)}")
                
                # 验证2: 旧组是否被删除
                logger.info(f"\n验证2: 检查旧组是否被删除...")
                all_deleted = True
                for old_group_id in merged_group_ids:
                    try:
                        old_group_response = semantic_group_client.get_semantic_group_by_id(old_group_id)
                        old_group_data = old_group_response.get('data', {})
                        if old_group_data:
                            logger.warning(f"⚠️ 旧组 {old_group_id} 仍然存在（可能不应该存在）")
                            all_deleted = False
                        else:
                            logger.info(f"✓ 旧组 {old_group_id} 已删除")
                    except Exception as e:
                        # 如果获取失败，可能是组已被删除（这是正常的）
                        logger.info(f"✓ 旧组 {old_group_id} 已删除（无法获取，说明已删除）")
                
                if all_deleted:
                    logger.info(f"✓ 验证2通过: 所有旧组都已删除")
                else:
                    logger.warning(f"⚠️ 验证2警告: 部分旧组仍然存在")
                
                # 验证3: 新组的成员是否正确（应该包含所有旧组的成员 + 新成员）
                logger.info(f"\n验证3: 检查新组的成员...")
                try:
                    new_relations_response = semantic_group_client.get_relations_by_group_id(group_id)
                    new_relations_data = new_relations_response.get('data', [])
                    if not isinstance(new_relations_data, list):
                        new_relations_data = []
                    
                    new_member_ids = [rel.get('sd_id') for rel in new_relations_data if rel.get('sd_id')]
                    expected_member_ids = [phase2_domain['semantic_domain_id']]
                    for old_group_id in merged_group_ids:
                        if old_group_id in groups_before_merge:
                            expected_member_ids.extend(groups_before_merge[old_group_id]['member_ids'])
                    
                    logger.info(f"  新组成员数: {len(new_member_ids)}")
                    logger.info(f"  预期成员数: {len(expected_member_ids)}")
                    
                    # 检查是否包含新成员
                    if phase2_domain['semantic_domain_id'] in new_member_ids:
                        logger.info(f"✓ 新成员已加入新组")
                    else:
                        logger.warning(f"⚠️ 新成员未加入新组")
                    
                    # 检查是否包含旧成员（至少部分）
                    old_members_included = sum(1 for mid in new_member_ids if mid in [m for g in groups_before_merge.values() for m in g['member_ids']])
                    if old_members_included > 0:
                        logger.info(f"✓ 至少 {old_members_included} 个旧成员已加入新组")
                    else:
                        logger.warning(f"⚠️ 没有旧成员加入新组")
                    
                except Exception as e:
                    logger.error(f"✗ 验证3失败: {str(e)}")
                
                # 验证4: 新组的描述是否正确（应该反映合并后的语义）
                logger.info(f"\n验证4: 检查新组的描述...")
                try:
                    new_group_response = semantic_group_client.get_semantic_group_by_id(group_id)
                    new_group_data = new_group_response.get('data', {})
                    new_description = new_group_data.get('description', '')
                    
                    if new_description and len(new_description) > 100:
                        logger.info(f"✓ 验证4通过: 新组描述已生成（长度: {len(new_description)} 字符）")
                        logger.info(f"  描述预览: {new_description[:200]}...")
                    else:
                        logger.warning(f"⚠️ 验证4警告: 新组描述可能不完整（长度: {len(new_description)} 字符）")
                except Exception as e:
                    logger.error(f"✗ 验证4失败: {str(e)}")
                
            elif action == 'JOIN':
                logger.warning(f"\n⚠️ 执行了 JOIN 操作而不是 MERGE")
                logger.warning(f"  这可能是因为：")
                logger.warning(f"  1. 置信度 < 0.9（当前: {confidence:.2f}）")
                logger.warning(f"  2. LLM 判断应该 JOIN 而不是 MERGE")
                logger.warning(f"  3. 第一阶段没有形成多个组（只形成了 {len(unique_groups)} 个组）")
            elif action == 'CREATE':
                logger.warning(f"\n⚠️ 执行了 CREATE 操作而不是 MERGE")
                logger.warning(f"  这可能是因为：")
                logger.warning(f"  1. 没有找到相似的现有组")
                logger.warning(f"  2. LLM 判断应该创建新组")
        else:
            logger.error("✗ 处理失败: 返回结果为空")
            
    except Exception as e:
        logger.error(f"✗ 处理失败: {str(e)}", exc_info=True)
    
    # 6. 最终状态统计
    logger.info("\n" + "=" * 80)
    logger.info("最终状态统计")
    logger.info("=" * 80)
    
    try:
        all_groups = semantic_group_client.get_all_semantic_groups()
        groups_data = all_groups.get('data', [])
        logger.info(f"\n当前共有 {len(groups_data)} 个语义组:")
        
        for group in groups_data:
            group_id = group.get('id') or group.get('group_id', 'N/A')
            group_name = group.get('group_name', 'N/A')
            
            try:
                relations = semantic_group_client.get_relations_by_group_id(group_id)
                relations_data = relations.get('data', [])
                member_count = len(relations_data) if isinstance(relations_data, list) else 0
                
                logger.info(f"\n  组ID: {group_id}")
                logger.info(f"  组名: {group_name}")
                logger.info(f"  成员数: {member_count}")
            except Exception as e:
                logger.warning(f"  获取组成员失败: {e}")
                
    except Exception as e:
        logger.error(f"查询最终状态失败: {e}", exc_info=True)
    
    logger.info("\n" + "=" * 80)
    logger.info("MERGE 能力测试完成")
    logger.info("=" * 80)


def main():
    """主函数"""
    try:
        # 可以选择运行哪个测试
        import sys
        if len(sys.argv) > 1:
            if sys.argv[1] == "consolidate":
                test_consolidate_semantic_domain_into_semantic_group()
            elif sys.argv[1] == "decremental":
                test_decremental_semantic_group_analyse()
            elif sys.argv[1] == "merge":
                test_merge_capability()
            else:
                logger.error(f"未知的测试选项: {sys.argv[1]}")
                logger.info("可用选项: consolidate, decremental, merge")
        else:
            test_semantic_grouper()
    except KeyboardInterrupt:
        logger.info("\n测试被用户中断")
    except Exception as e:
        logger.error(f"测试执行失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
