#!/usr/bin/env python3
"""
测试图表生成能力：
1. 单元测试：图表意图识别、option 解析、option 校验、无效配置写 HTML
2. 集成测试：若配置了 API key，则调用 invoke_common 并打印结果
3. 在浏览器中打开生成的图表（有 API 用 LLM 结果，无 API 用内置示例图）
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

# 确保能 import agent 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试数据：各商品分类销售总额（你提供的分析结果）
SAMPLE_KNOWLEDGE = """根据提供的分析结果，各商品分类的销售总额如下：

| 商品分类 | 总销售额 |
| :--- | :--- |
| 笔记本电脑 | 36,997.0 |
| 手机 | 18,997.0 |
| 平板电脑 | 10,397.0 |
| 智能手表 | 4,296.0 |
| 耳机 | 3,095.0 |
| 童装 | 1,198.0 |
| 厨房用品 | 699.0 |
| 休闲鞋 | 399.0 |
| 男装 | 299.0 |
| 女装 | 89.0 |

**数据说明**：以上数据是通过关联商品分类、产品及订单明细表，对每个分类下所有订单的金额进行求和计算得出，并按销售额从高到低排序。"""

# 测试数据：用户订单数量及总消费金额统计
SAMPLE_KNOWLEDGE_USER_CONSUMPTION = """根据查询结果，系统中每个用户的订单数量及总消费金额统计如下：

**用户消费统计详情：**
1.  **张三 (zhangsan)**: 2笔订单，总消费11,998.0
2.  **李四 (lisi)**: 2笔订单，总消费6,248.0
3.  **王五 (wangwu)**: 2笔订单，总消费6,698.0
4.  **赵六 (zhaoliu)**: 1笔订单，总消费1,899.0
5.  **刘霞 (liuxia)**: 1笔订单，总消费7,999.0
6.  **陈明 (chenming)**: 1笔订单，总消费199.0
7.  **杨岚 (yanglan)**: 1笔订单，总消费599.0
8.  **周红 (zhouhong)**: 1笔订单，总消费299.0
9.  **吴峰 (wufeng)**: 1笔订单，总消费399.0
10. **郑涛 (zhengtao)**: 1笔订单，总消费699.0
11. **孙丽 (sunli)**: 1笔订单，总消费9,999.0
12. **钱军 (qianjun)**: 1笔订单，总消费18,999.0
13. **冯艳 (fengyan)**: 1笔订单，总消费3,999.0
14. **陈伟 (chenwei)**: 1笔订单，总消费2,999.0
15. **胡燕 (huyan)**: 1笔订单，总消费89.0
16. **林慧 (linhui)**: 1笔订单，总消费199.0
17. **郭斌 (guobin)**: 1笔订单，总消费599.0
18. **马威 (mawei)**: 0笔订单，总消费null
19. **王露西 (lucywang)**: 0笔订单，总消费null
20. **李大卫 (davidli)**: 0笔订单，总消费null

**数据总结：**
* 系统中共有 **20位用户**。
* 其中 **17位用户** 有订单和消费记录。
* 另有 **3位用户**（马威、王露西、李大卫）尚未产生任何消费。"""

# 内置示例：用上述测试数据生成的 ECharts 配置（柱状图 + 饼图可选）
# 柱状图：各商品分类销售总额对比
SAMPLE_ECHARTS_OPTION = {
    "title": {"text": "各商品分类销售总额", "subtext": "按销售额从高到低排序", "left": "center"},
    "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
    "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
    "xAxis": {
        "type": "category",
        "data": ["笔记本电脑", "手机", "平板电脑", "智能手表", "耳机", "童装", "厨房用品", "休闲鞋", "男装", "女装"],
        "axisLabel": {"rotate": 30, "interval": 0},
    },
    "yAxis": {"type": "value", "name": "总销售额"},
    "series": [
        {
            "type": "bar",
            "data": [36997, 18997, 10397, 4296, 3095, 1198, 699, 399, 299, 89],
            "itemStyle": {
                "color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "#5470c6"}, {"offset": 1, "color": "#91cc75"}]},
            },
        }
    ],
}

# 测试数据二：订单状态分布（你提供的背景知识）
SAMPLE_KNOWLEDGE_ORDER_STATUS = """根据提供的背景知识，当前系统中订单的状态分布情况如下：

**订单状态统计结果：**
*   **已交付 (delivered)**: 7个订单，占比35.0%
*   **已发货 (shipped)**: 5个订单，占比25.0%
*   **已确认 (confirmed)**: 4个订单，占比20.0%
*   **待处理 (pending)**: 4个订单，占比20.0%
*   **已取消 (cancelled)**: 0个订单，占比0.0%

**分析总结：**
1.  **状态分布**：系统订单主要集中在“已交付”和“已发货”状态，合计占总订单数的60%。
2.  **订单流转**：“已确认”和“待处理”状态的订单数量相同，各占20%，表明从下单到发货前的环节订单分布较为均衡。
3.  **异常情况**：“已取消”状态的订单数量为0，在当前数据集中未出现订单取消的情况。"""

# 内置示例二：订单状态占比饼图
SAMPLE_ECHARTS_OPTION_ORDER = {
    "title": {"text": "订单状态分布", "subtext": "当前系统订单状态占比", "left": "center"},
    "tooltip": {"trigger": "item", "formatter": "{b}: {c}个订单 ({d}%)"},
    "legend": {"orient": "vertical", "left": "left"},
    "series": [
        {
            "type": "pie",
            "radius": ["40%", "70%"],
            "center": ["50%", "55%"],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 2},
            "label": {"show": True, "formatter": "{b}\n{d}%"},
            "emphasis": {"label": {"show": True}, "itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0, 0, 0, 0.5)"}},
            "data": [
                {"value": 7, "name": "已交付 (delivered)"},
                {"value": 5, "name": "已发货 (shipped)"},
                {"value": 4, "name": "已确认 (confirmed)"},
                {"value": 4, "name": "待处理 (pending)"},
                {"value": 0, "name": "已取消 (cancelled)"},
            ],
        }
    ],
}

# 测试数据三：广州农商银行总行存款（你提供的查询结果）
SAMPLE_KNOWLEDGE_BANK = """根据提供的查询结果，广州农商银行总行在2023年12月31日的存款总额为470.03亿元。

**数据详情如下：**
*   **存款总额：** 47,003,000,000元
*   **对公存款：** 22,583,700,000元
*   **零售存款：** 24,419,300,000元

> 注：此数据为2023年12月31日（年末）的时点存款总额。"""

# 内置示例三：广州农商银行存款结构饼图（对公 vs 零售）
SAMPLE_ECHARTS_OPTION_BANK = {
    "title": {"text": "广州农商银行总行存款结构", "subtext": "2023年12月31日（亿元）", "left": "center"},
    "tooltip": {"trigger": "item", "formatter": "{b}: {c}亿元 ({d}%)"},
    "legend": {"orient": "vertical", "left": "left"},
    "series": [
        {
            "type": "pie",
            "radius": ["40%", "70%"],
            "center": ["50%", "55%"],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderRadius": 4, "borderColor": "#fff", "borderWidth": 2},
            "label": {"show": True, "formatter": "{b}\n{c}亿元\n{d}%"},
            "emphasis": {"label": {"show": True}, "itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0, 0, 0, 0.5)"}},
            "data": [
                {"value": 225.837, "name": "对公存款"},
                {"value": 244.193, "name": "零售存款"},
            ],
        }
    ],
}

# 内置示例四：用户订单数量及总消费金额（与 SAMPLE_KNOWLEDGE_USER_CONSUMPTION 一致）
SAMPLE_ECHARTS_OPTION_USER = {
    "title": {"text": "用户总消费金额统计", "subtext": "单位：元", "left": "center"},
    "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
    "grid": {"left": "3%", "right": "4%", "bottom": "15%", "containLabel": True},
    "xAxis": {
        "type": "category",
        "data": [
            "张三", "李四", "王五", "赵六", "刘霞", "陈明", "杨岚", "周红", "吴峰", "郑涛",
            "孙丽", "钱军", "冯艳", "陈伟", "胡燕", "林慧", "郭斌", "马威", "王露西", "李大卫",
        ],
        "axisLabel": {"rotate": 45, "interval": 0},
    },
    "yAxis": {"type": "value", "name": "总消费（元）"},
    "series": [
        {
            "type": "bar",
            "name": "总消费金额",
            "data": [
                11998, 6248, 6698, 1899, 7999, 199, 599, 299, 399, 699,
                9999, 18999, 3999, 2999, 89, 199, 599, 0, 0, 0,
            ],
        }
    ],
}

# 测试数据：华为Watch GT4 等商品销售分析
SAMPLE_KNOWLEDGE_WATCH_GT4 = """根据提供的销售数据分析，**华为Watch GT4** 属于最畅销的商品之一。

**具体分析如下：**
* **销售数量**：华为Watch GT4的总销售数量为 **2件**。
* **排名情况**：在所有产品中，其销量与“佳明Forerunner265”和“儿童冬季外套”并列 **第二**。
* **对比说明**：销量最高的产品是“森海塞尔MOMENTUM真无线”（4件）。因此，基于销售数量，华为Watch GT4是排名前列的最畅销产品之一。"""

# 内置示例五：热销商品销量对比（与 SAMPLE_KNOWLEDGE_WATCH_GT4 一致）
SAMPLE_ECHARTS_OPTION_SALES = {
    "title": {"text": "热销商品销量对比", "subtext": "单位：件", "left": "center"},
    "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
    "grid": {"left": "3%", "right": "4%", "bottom": "20%", "containLabel": True},
    "xAxis": {
        "type": "category",
        "data": ["森海塞尔MOMENTUM真无线", "华为Watch GT4", "佳明Forerunner265", "儿童冬季外套"],
        "axisLabel": {"rotate": 25, "interval": 0},
    },
    "yAxis": {"type": "value", "name": "销售数量（件）"},
    "series": [
        {"type": "bar", "name": "销量", "data": [4, 2, 2, 2]},
    ],
}


def _is_chart_related_query(query: str) -> bool:
    """与 ChartAgent._is_chart_related_query 逻辑一致，用于无 LLM 时的单元测试"""
    if not query or not isinstance(query, str):
        return False
    q = query.strip().lower()
    chart_keywords = (
        "图", "chart", "图表", "可视化", "画图", "画一张", "画一个",
        "饼图", "柱状图", "折线图", "直方图", "散点图", "雷达图",
        "占比", "趋势", "分布", "对比"
    )
    return any(k in q for k in chart_keywords)


def _extract_chart_option_from_response(response: str):
    """从 agent 返回文本中解析 ```chart ... ``` 中的 JSON，返回 dict 或 None"""
    if not response or "```chart" not in response:
        return None
    start = response.find("```chart")
    if start == -1:
        return None
    start = response.index("\n", start) + 1
    end = response.find("```", start)
    if end == -1:
        return None
    raw = response[start:end].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _is_valid_echarts_option(option: dict) -> bool:
    """校验 option 具备可渲染结构（至少有一个 series 且含 data）。"""
    if not option or not isinstance(option, dict):
        return False
    series = option.get("series")
    if not series or not isinstance(series, list):
        return False
    for s in series:
        if not isinstance(s, dict):
            continue
        data = s.get("data")
        if data is None:
            continue
        if isinstance(data, list) and len(data) > 0:
            return True
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return True
    return False


def _write_html_and_open(option: dict, out_path: Path, open_browser: bool = True) -> None:
    """将 ECharts option 写入 HTML 并可选择用默认浏览器打开；若 option 无效则写入友好提示页。"""
    if not _is_valid_echarts_option(option):
        html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chart Agent - 无法渲染</title>
</head>
<body>
  <div style="font-family: sans-serif; padding: 2rem; max-width: 600px;">
    <h2>图表配置无效，无法渲染</h2>
    <p>当前数据或生成的配置不适合画图（缺少 series 或数据）。请检查描述或背景知识是否包含可绘图的结构化数据。</p>
  </div>
</body>
</html>
"""
        out_path.write_text(html, encoding="utf-8")
        if open_browser:
            webbrowser.open(out_path.as_uri())
        print(f"  已写入（图表配置无效，已展示说明）: {out_path}")
        return
    option_js = json.dumps(option, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chart Agent 测试图表</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
</head>
<body>
  <div id="chart" style="width: 800px; height: 500px;"></div>
  <script>
    var chart = echarts.init(document.getElementById('chart'));
    var option = {option_js};
    chart.setOption(option);
  </script>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(out_path.as_uri())
    print(f"  已写入" + ("并打开浏览器" if open_browser else "") + f" 展示图表: {out_path}")


def test_is_chart_related():
    """测试图表相关查询识别（不依赖 ChartAgent）"""
    assert _is_chart_related_query("画一个饼图显示各部门占比") is True
    assert _is_chart_related_query("用柱状图对比各月销量") is True
    assert _is_chart_related_query("生成折线图看趋势") is True
    assert _is_chart_related_query("什么是 Java？") is False
    assert _is_chart_related_query("") is False
    assert _is_chart_related_query("  占比多少  ") is True
    assert _is_chart_related_query("  对比一下  ") is True
    print("  _is_chart_related_query: OK")


def test_extract_chart_option():
    """测试从 agent 返回中解析 ```chart ... ``` 与「无法生成图表」"""
    # 正常 chart 块
    resp = "已生成。\n\n```chart\n{\"title\":{\"text\":\"测试\"},\"series\":[{\"type\":\"bar\",\"data\":[1,2]}]}\n```"
    opt = _extract_chart_option_from_response(resp)
    assert opt is not None
    assert opt.get("title", {}).get("text") == "测试"
    assert opt.get("series") and len(opt["series"]) > 0 and opt["series"][0].get("data") == [1, 2]

    # 无 chart 块
    assert _extract_chart_option_from_response("【无法生成图表】背景知识中无结构化数据。") is None
    assert _extract_chart_option_from_response("") is None
    assert _extract_chart_option_from_response("纯文字回答") is None

    # 空 chart 块或非法 JSON
    assert _extract_chart_option_from_response("```chart\n{}\n```") is not None  # {} 解析成功但后续校验会拦
    bad = "```chart\n{ invalid json }\n```"
    assert _extract_chart_option_from_response(bad) is None
    print("  _extract_chart_option_from_response: OK")


def test_is_valid_echarts_option():
    """测试 ECharts option 校验：有效 / 缺 series / 缺 data"""
    assert _is_valid_echarts_option(SAMPLE_ECHARTS_OPTION) is True
    assert _is_valid_echarts_option(SAMPLE_ECHARTS_OPTION_ORDER) is True
    assert _is_valid_echarts_option({}) is False
    assert _is_valid_echarts_option(None) is False
    assert _is_valid_echarts_option({"title": {"text": "x"}}) is False
    assert _is_valid_echarts_option({"series": []}) is False
    assert _is_valid_echarts_option({"series": [{}]}) is False
    assert _is_valid_echarts_option({"series": [{"data": []}]}) is False
    assert _is_valid_echarts_option({"series": [{"data": [1, 2, 3]}]}) is True
    assert _is_valid_echarts_option({"series": [{"type": "pie", "data": [{"value": 1, "name": "A"}]}]}) is True
    print("  _is_valid_echarts_option: OK")


def test_write_html_invalid_option():
    """测试无效 option 写 HTML 不抛错，且写入「无法渲染」页"""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = Path(f.name)
    try:
        _write_html_and_open({}, path, open_browser=False)
        content = path.read_text(encoding="utf-8")
        assert "图表配置无效" in content or "无法渲染" in content
        assert "series" in content or "数据" in content
    finally:
        path.unlink(missing_ok=True)
    print("  _write_html_invalid_option (写无效配置不崩溃): OK")


async def test_generate_chart_integration():
    """集成测试：通过 invoke_common 调用 LLM 生成图表（需要配置 API）。返回 (raw_response, option_dict)。"""
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not api_key:
        print("  [skip] invoke_common 图表生成: 未设置 DASHSCOPE_API_KEY/OPENAI_API_KEY/API_KEY，跳过 LLM 调用")
        print("         将使用内置示例图表在浏览器中展示效果。")
        return None, None
    from agent.chart_agent import ChartAgent
    # 使用测试数据作为背景知识，让 LLM 根据「各商品分类销售总额」生成图表
    query = "根据背景知识，用柱状图展示各商品分类的销售总额对比；若无柱状图则用饼图展示各分类占比。"
    # Langfuse 要求 trace_id 为 32 位小写十六进制
    agent = ChartAgent(
        query=query + "\n\n背景知识:\n" + SAMPLE_KNOWLEDGE,
        metadata={"user_id": "test", "run_id": "test", "trace_id": "0" * 32},
        provider="openai_compatible",
        api_key=api_key,
        base_url=base_url,
        model=os.getenv("CHART_MODEL", "qwen2.5-72b-instruct"),
        stream=False,
    )
    print("  调用 invoke_common（背景知识：各商品分类销售总额表）...")
    llm_result = await agent.invoke_common()
    result = (llm_result.answer or "").strip()
    print("  结果预览:", result[:500] + "..." if len(result) > 500 else result)
    if "```chart" in result:
        print("  [OK] 返回中包含 ```chart 代码块")
    else:
        print("  [WARN] 返回中未包含 ```chart 代码块")
    option = _extract_chart_option_from_response(result)
    return result, option


async def test_user_consumption_chart():
    """集成测试：用「用户订单数量及总消费金额」数据调用 invoke_common 生成图表。返回 (raw_response, option_dict)。"""
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not api_key:
        return None, None
    from agent.chart_agent import ChartAgent
    query = "根据背景知识，用柱状图展示各用户的订单数量或总消费金额对比；可只展示有消费的用户，或同时标注订单数。"
    agent = ChartAgent(
        query=query + "\n\n背景知识:\n" + SAMPLE_KNOWLEDGE_USER_CONSUMPTION,
        metadata={"user_id": "test", "run_id": "test", "trace_id": "0" * 32},
        provider="openai_compatible",
        api_key=api_key,
        base_url=base_url,
        model=os.getenv("CHART_MODEL", "qwen2.5-72b-instruct"),
        stream=False,
    )
    print("  调用 invoke_common（背景知识：用户消费统计）...")
    llm_result = await agent.invoke_common()
    result = (llm_result.answer or "").strip()
    if "```chart" in result:
        print("  [OK] 用户消费图表返回中包含 ```chart 代码块")
    option = _extract_chart_option_from_response(result)
    return result, option


def main():
    parser = argparse.ArgumentParser(description="Chart Agent 测试：单元测试 + 可选集成测试 + 生成并打开图表 HTML")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器，仅生成 HTML 文件")
    args = parser.parse_args()
    open_browser = not args.no_browser

    base_dir = Path(__file__).resolve().parent
    out_html = base_dir / "chart_output.html"
    out_html_order = base_dir / "chart_output_order.html"

    print("========== 1. 单元测试 ==========")
    test_is_chart_related()
    test_extract_chart_option()
    test_is_valid_echarts_option()
    test_write_html_invalid_option()

    print("\n========== 2. 集成测试（需 LLM，未配置 API 则跳过）==========")

    async def run_integration_tests():
        r1, o1 = await test_generate_chart_integration()
        r2, o2 = await test_user_consumption_chart()
        return (r1, o1), (r2, o2)

    (result, option), (result_user, option_user) = asyncio.run(run_integration_tests())

    print("\n========== 3. 生成图表 HTML ==========")
    chart_unavailable = result and "【无法生成图表】" in (result.strip() or "")
    if option:
        _write_html_and_open(option, out_html, open_browser=open_browser)
        print("  图表一：使用 LLM 生成的 ECharts 配置渲染。")
    elif chart_unavailable:
        print("  图表一：LLM 判断数据不适合画图，未打开示例图。")
        print("  说明:", result.strip()[:200] + ("..." if len(result.strip()) > 200 else ""))
    else:
        _write_html_and_open(SAMPLE_ECHARTS_OPTION, out_html, open_browser=open_browser)
        print("  图表一：各商品分类销售总额（柱状图）")
    _write_html_and_open(SAMPLE_ECHARTS_OPTION_ORDER, out_html_order, open_browser=open_browser)
    print("  图表二：订单状态分布（饼图）")
    out_html_bank = base_dir / "chart_output_bank.html"
    _write_html_and_open(SAMPLE_ECHARTS_OPTION_BANK, out_html_bank, open_browser=open_browser)
    print("  图表三：广州农商银行总行存款结构（对公 vs 零售，饼图）")
    out_html_user = base_dir / "chart_output_user.html"
    if option_user:
        _write_html_and_open(option_user, out_html_user, open_browser=open_browser)
        print("  图表四：用户订单数量及总消费金额统计（LLM 生成）")
    else:
        _write_html_and_open(SAMPLE_ECHARTS_OPTION_USER, out_html_user, open_browser=open_browser)
        print("  图表四：用户总消费金额统计（内置示例）")
    out_html_sales = base_dir / "chart_output_sales.html"
    _write_html_and_open(SAMPLE_ECHARTS_OPTION_SALES, out_html_sales, open_browser=open_browser)
    print("  图表五：热销商品销量对比（华为Watch GT4 等）")

    if result:
        print("\n--- 完整返回（可复制到前端用于渲染）---")
        print(result)

    print("\n========== 测试完成 ==========")


if __name__ == "__main__":
    main()
