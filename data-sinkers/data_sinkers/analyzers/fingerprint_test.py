from .fingerprint import FingerprintAnalyzer
import time

# python -m data_sinkers.analyzers.fingerprint_test

def main():

    test_schemas = [
        {
            "table_name": "balance_sheet",
            "table_comment": "核心资产负债表",
            "columns": [
                {"COLUMN_NAME": "data_date", "COLUMN_TYPE": "DATE", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "报表日期"},
                {"COLUMN_NAME": "branch_id", "COLUMN_TYPE": "VARCHAR(4)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构编号"},
                {"COLUMN_NAME": "branch_name", "COLUMN_TYPE": "VARCHAR(50)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构名称"},
                {"COLUMN_NAME": "total_assets", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "资产总额"},
                {"COLUMN_NAME": "customer_loans", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "客户贷款总额"},
                {"COLUMN_NAME": "interbank_assets", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "同业资产总额"},
                {"COLUMN_NAME": "other_assets", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "其他资产总额"},
                {"COLUMN_NAME": "total_liabilities", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "负债总额"},
                {"COLUMN_NAME": "customer_deposits", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "客户存款总额"},
                {"COLUMN_NAME": "interbank_liabilities", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "同业负债总额"},
                {"COLUMN_NAME": "other_liabilities", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "其他负债总额"},
                {"COLUMN_NAME": "total_customers", "COLUMN_TYPE": "INT", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "客户总数"},
                {"COLUMN_NAME": "individual_customers", "COLUMN_TYPE": "INT", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "个人客户数"},
                {"COLUMN_NAME": "corporate_customers", "COLUMN_TYPE": "INT", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "公司客户数"},
                {"COLUMN_NAME": "interbank_customers", "COLUMN_TYPE": "INT", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "同业客户数"},
                {"COLUMN_NAME": "total_employees", "COLUMN_TYPE": "INT", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "员工总数"}
            ]
        },
        {
            "table_name": "deposit_data",
            "table_comment": "存款总额",
            "columns": [
                {"COLUMN_NAME": "data_date", "COLUMN_TYPE": "DATE", "IS_NULLABLE": "YES", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "数据日期（格式：YYYY/MM/DD）"},
                {"COLUMN_NAME": "branch_id", "COLUMN_TYPE": "VARCHAR(4)", "IS_NULLABLE": "YES", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构号（4位数字代码）"},
                {"COLUMN_NAME": "branch_name", "COLUMN_TYPE": "VARCHAR(50)", "IS_NULLABLE": "YES", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构名称"},
                {"COLUMN_NAME": "customer_deposit_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "客户存款总额（公司+零售，单位：元）"},
                {"COLUMN_NAME": "corporate_deposit_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "公司存款总额（单位：元）"},
                {"COLUMN_NAME": "corporate_current_deposit", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "公司活期存款（单位：元）"},
                {"COLUMN_NAME": "corporate_term_deposit", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "公司定期存款（单位：元）"},
                {"COLUMN_NAME": "retail_deposit_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "零售存款总额（单位：元）"},
                {"COLUMN_NAME": "retail_current_deposit", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "零售活期存款（单位：元）"},
                {"COLUMN_NAME": "retail_term_deposit", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "零售定期存款（单位：元）"}
            ]
        },
        {
            "table_name": "loan_data",
            "table_comment": "贷款数据表",
            "columns": [
                {"COLUMN_NAME": "data_date", "COLUMN_TYPE": "DATE", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "数据日期（格式：YYYY/MM/DD）"},
                {"COLUMN_NAME": "branch_id", "COLUMN_TYPE": "VARCHAR(4)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构号（4位数字代码）"},
                {"COLUMN_NAME": "branch_name", "COLUMN_TYPE": "VARCHAR(50)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构名称"},
                {"COLUMN_NAME": "total_customer_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "客户贷款总额（单位：元）"},
                {"COLUMN_NAME": "substantive_loan_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "实质性贷款总额（实际发放的贷款，单位：元）"},
                {"COLUMN_NAME": "corporate_loan_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "公司贷款总额（单位：元）"},
                {"COLUMN_NAME": "inclusive_sme_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "普惠小微贷款总额（单位：元）"},
                {"COLUMN_NAME": "retail_loan_total", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "零售贷款总额（单位：元）"},
                {"COLUMN_NAME": "credit_card_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "信用卡贷款总额（单位：元）"},
                {"COLUMN_NAME": "medium_small_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "中小额贷款总额（单位：元）"},
                {"COLUMN_NAME": "large_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "大额贷款总额（单位：元）"},
                {"COLUMN_NAME": "medium_small_corporate_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "中小额公司贷款（公司贷款子项，单位：元）"},
                {"COLUMN_NAME": "large_corporate_loan", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "大额公司贷款（公司贷款子项，单位：元）"},
                {"COLUMN_NAME": "total_discount", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "贴现总额（直贴+转贴，单位：元）"},
                {"COLUMN_NAME": "direct_discount", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "直贴总额（直接贴现业务，单位：元）"},
                {"COLUMN_NAME": "transfer_discount", "COLUMN_TYPE": "DECIMAL(18,0)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "转贴总额（转贴现业务，单位：元）"}
            ]
        },
        {
            "table_name": "retail_loan_detail",
            "table_comment": "零售贷款明细表",
            "columns": [
                {"COLUMN_NAME": "data_date", "COLUMN_TYPE": "DATE", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "数据日期（格式：YYYY/MM/DD）"},
                {"COLUMN_NAME": "branch_id", "COLUMN_TYPE": "VARCHAR(4)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构号（4位数字代码）"},
                {"COLUMN_NAME": "branch_name", "COLUMN_TYPE": "VARCHAR(50)", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": "机构名称"},
                {"COLUMN_NAME": "retail_loan_total", "COLUMN_TYPE": "DECIMAL(18,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "零售贷款总额"},
                {"COLUMN_NAME": "mortgage_total", "COLUMN_TYPE": "DECIMAL(18,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "按揭贷款总额"},
                {"COLUMN_NAME": "first_hand_mortgage", "COLUMN_TYPE": "DECIMAL(18,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "一手按揭总额"},
                {"COLUMN_NAME": "second_hand_mortgage", "COLUMN_TYPE": "DECIMAL(18,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "二手按揭总额"},
                {"COLUMN_NAME": "consumer_loan_total", "COLUMN_TYPE": "DECIMAL(18,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": "消费贷款总额"}
            ]
        }
    ]

    # Initialize analyzer
    analyzer = FingerprintAnalyzer(
        provider="openai_compatible",
        api_key="sk-xxx",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3-32b"
    )
    
    # Single analysis
    # result = analyzer.analyze(test_schemas, datasource_type="mysql")
    # print("=================")
    # print(result)


    relationship_data = """
    {'foreign_keys': [{'from_table': 'categories', 'from_column': 'parent_id', 'to_table': 'categories', 'to_column': 'category_id', 'CONSTRAINT_NAME': 'categories_ibfk_1'}, {'from_table': 'order_items', 'from_column': 'order_id', 'to_table': 'orders', 'to_column': 'order_id', 'CONSTRAINT_NAME': 'order_items_ibfk_1'}, {'from_table': 'order_items', 'from_column': 'product_id', 'to_table': 'products', 'to_column': 'product_id', 'CONSTRAINT_NAME': 'order_items_ibfk_2'}, {'from_table': 'orders', 'from_column': 'user_id', 'to_table': 'users', 'to_column': 'user_id', 'CONSTRAINT_NAME': 'orders_ibfk_1'}, {'from_table': 'products', 'from_column': 'category_id', 'to_table': 'categories', 'to_column': 'category_id', 'CONSTRAINT_NAME': 'products_ibfk_1'}], 'relationships_summary': {'one_to_many': [{'from_table': 'order_items', 'from_column': 'order_id', 'to_table': 'orders', 'to_column': 'order_id', 'CONSTRAINT_NAME': 'order_items_ibfk_1'}, {'from_table': 'order_items', 'from_column': 'product_id', 'to_table': 'products', 'to_column': 'product_id', 'CONSTRAINT_NAME': 'order_items_ibfk_2'}, {'from_table': 'orders', 'from_column': 'user_id', 'to_table': 'users', 'to_column': 'user_id', 'CONSTRAINT_NAME': 'orders_ibfk_1'}, {'from_table': 'products', 'from_column': 'category_id', 'to_table': 'categories', 'to_column': 'category_id', 'CONSTRAINT_NAME': 'products_ibfk_1'}], 'many_to_many': [], 'self_referencing': [{'from_table': 'categories', 'from_column': 'parent_id', 'to_table': 'categories', 'to_column': 'category_id', 'CONSTRAINT_NAME': 'categories_ibfk_1'}]}}
    """

    # result = analyzer.generate_table_relationship(relationship_data)
    # print("=================")
    # print(result)

    tables_schema = """
    ## Table: `categories`
    *商品分类表，支持无限级分类结构，用于组织和管理商品分类体系*

    | Column | Type | Nullable | Key | Comment |
    |--------|------|----------|-----|---------|
    | `category_id` | `int` | NO | PRI | 分类唯一标识ID，主键，自增长 |
    | `category_name` | `varchar(100)` | NO |  | 分类名称，不能为空 |
    | `parent_id` | `int` | YES | MUL | 父分类ID，指向当前表的category_id，用于构建多级分类结构。NULL表示一级分类 |
    | `description` | `text` | YES |  | 分类详细描述，可选填 |
    | `created_at` | `timestamp` | YES |  | 分类创建时间，默认为当前时间戳 |

    ## Table: `order_items`
    *订单详情表，存储订单中每个商品的具体信息，支持一个订单包含多个商品*

    | Column | Type | Nullable | Key | Comment |
    |--------|------|----------|-----|---------|
    | `order_item_id` | `int` | NO | PRI | 订单项唯一标识ID，主键，自增长 |
    | `order_id` | `int` | NO | MUL | 订单ID，外键关联orders表，标识所属订单 |
    | `product_id` | `int` | NO | MUL | 商品ID，外键关联products表，标识购买的商品 |
    | `quantity` | `int` | NO |  | 购买数量，不能为空 |
    | `unit_price` | `decimal(10,2)` | NO |  | 下单时的商品单价，十进制数，整数位8位小数位2位，不能为空 |
    | `subtotal` | `decimal(10,2)` | YES |  | 小计金额，计算字段，自动生成（数量 × 单价），存储类型 |

    ## Table: `orders`
    *订单主表，存储订单的基本信息、状态和配送地址*

    | Column | Type | Nullable | Key | Comment |
    |--------|------|----------|-----|---------|
    | `order_id` | `int` | NO | PRI | 订单唯一标识ID，主键，自增长 |
    | `user_id` | `int` | NO | MUL | 用户ID，外键关联users表，标识订单所属用户 |
    | `order_date` | `timestamp` | YES |  | 订单日期，默认为当前时间戳，表示下单时间 |
    | `total_amount` | `decimal(10,2)` | NO |  | 订单总金额，十进制数，整数位8位小数位2位，不能为空 |
    | `status` | `enum('pending','confirmed','shipped','delivered','cancelled')` | YES |  | 订单状态：pending-待处理, confirmed-已确认, shipped-已发货, delivered-已送达, cancelled-已取消 |
    | `shipping_address` | `text` | NO |  | 收货地址，详细配送信息，不能为空 |
    | `created_at` | `timestamp` | YES |  | 订单记录创建时间，默认为当前时间戳 |

    ## Table: `products`
    *商品信息表，存储所有商品的基本信息、价格和库存数据*

    | Column | Type | Nullable | Key | Comment |
    |--------|------|----------|-----|---------|
    | `product_id` | `int` | NO | PRI | 商品唯一标识ID，主键，自增长 |
    | `product_name` | `varchar(200)` | NO |  | 商品名称，不能为空 |
    | `description` | `text` | YES |  | 商品详细描述，支持长文本，可选填 |
    | `price` | `decimal(10,2)` | NO |  | 商品价格，十进制数，整数位8位小数位2位，不能为空 |
    | `stock_quantity` | `int` | YES |  | 库存数量，默认为0 |
    | `category_id` | `int` | NO | MUL | 所属分类ID，外键关联categories表，不能为空 |
    | `created_at` | `timestamp` | YES |  | 商品创建时间，默认为当前时间戳 |
    | `updated_at` | `timestamp` | YES |  | 商品最后更新时间，默认为当前时间戳并在更新时自动更新 |

    ## Table: `users`
    *用户信息表，存储系统所有注册用户的基本信息*

    | Column | Type | Nullable | Key | Comment |
    |--------|------|----------|-----|---------|
    | `user_id` | `int` | NO | PRI | 用户唯一标识ID，主键，自增长 |
    | `username` | `varchar(50)` | NO | UNI | 用户名，唯一且不能为空，用于登录 |
    | `email` | `varchar(100)` | NO | UNI | 邮箱地址，唯一且不能为空，用于登录和通知 |
    | `password` | `varchar(255)` | NO |  | 加密后的密码，使用哈希算法存储 |
    | `full_name` | `varchar(100)` | YES |  | 用户全名，可选填 |
    | `phone` | `varchar(20)` | YES |  | 手机号码，可选填 |
    | `created_at` | `timestamp` | YES |  | 记录创建时间，默认为当前时间戳 |
    | `updated_at` | `timestamp` | YES |  | 记录最后更新时间，默认为当前时间戳并在更新时自动更新 |

    """

    result = analyzer.generate_tables_summary(tables_schema)
    print("=================")
    print(result)


if __name__ == "__main__":
    main()