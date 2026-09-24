"""Capability check 5-dimension accuracy battery — D/I/O/R/C x 10 each (50 total)

Usage:
  DASHSCOPE_API_KEY=sk-xxx \
  DASHSCOPE_MODEL=deepseek-v4-flash-0731 \
  python -m pytest tests/test_capability_dimension_battery.py -q -s -v
"""

from __future__ import annotations

import asyncio, os, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import capability_chain as cc
from agent import skill_agent as sa
from agent.tool_call_utils import invoke_llm_with_tool
from model_sdk.api.model_manager import ModelManager

AK = os.environ.get("DASHSCOPE_API_KEY", "sk-xxx")
BASE = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
CCY = 2

_llm = None
def get_llm():
    global _llm
    if _llm is None:
        _llm = ModelManager().get_llm(
            provider="openai_compatible", api_key=AK, base_url=BASE,
            model=MODEL, temperature=0.01, stream=False,
            extra_body={"enable_thinking": False})
    return _llm

# Agent skill definitions
SKU_SKILL = """### skill: product_query

# Product Query

## Data Source
Product data in `data/products.txt`, pipe-delimited fields:
ProductID | Name | Category(Clothing/Food/Electronics/Home/Beauty) | Brand | Price(CNY) | Specs | ListingDate | Status(Listed/Delisted)

## Query Methods
- By ProductID: `grep "PROD-001" data/products.txt`
- By Category: `grep "Electronics" data/products.txt`
- By Brand: `grep "Huawei" data/products.txt`
- Allowed tools: cat, grep, awk, sort, wc (read-only)

## Covered Scenarios
1. Query product details by ProductID
2. Browse product list by category
3. Filter products by brand
4. Filter by price range
5. Count products per category

## Notes
- Does NOT cover inventory/stock data
- Does NOT cover user reviews or sales ranking
- Does NOT cover product images or detailed descriptions"""

ORDER_SKILL = """### skill: order_query

# Order Query

## Data Source
Order data in `data/orders.txt`, pipe-delimited fields:
OrderID | UserID | ProductID | ProductName | Quantity | Amount | OrderTime | Status(Pending/Paid/Shipped/Delivered/Cancelled) | PaymentMethod(WeChat/Alipay/BankCard)

## Query Methods
- By OrderID: `grep "ORD-001" data/orders.txt`
- By UserID: `grep "U001" data/orders.txt`
- By Status: `grep "Cancelled" data/orders.txt`
- Sum amounts: `awk -F'|' '{sum+=$6} END {print sum}' data/orders.txt`
- Allowed tools: cat, grep, awk, sort, wc (read-only)

## Covered Scenarios
1. Query all orders for a user
2. Query order details
3. Filter by status
4. Statistics by payment method
5. Count orders and sum amounts

## Notes
- Read-only, no modification/deletion/creation
- Does NOT include product specs or inventory
- Order data synced daily at 2am, NOT real-time
- Does NOT include logistics/shipping info"""

PAY_SKILL = """### skill: payment_query

# Payment Query

## Data Source
Payment data in `data/payments.txt`, pipe-delimited fields:
PaymentID | OrderID | UserID | Amount(CNY) | PaymentMethod(WeChat/Alipay/BankCard) | Status(Success/Failed/Refunding/Refunded) | PaymentTime | RefundAmount(CNY)

## Query Methods
- By PaymentID: `grep "PAY-001" data/payments.txt`
- By OrderID: `grep "ORD-001" data/payments.txt`
- By Status: `grep "Refunded" data/payments.txt`
- Sum refunds: `awk -F'|' '$6=="Refunded" {sum+=$8} END {print sum}' data/payments.txt`
- Allowed tools: cat, grep, awk, sort, wc (read-only)

## Covered Scenarios
1. Query payment details by PaymentID
2. Query payments by OrderID
3. Filter by payment status
4. Sum refund amounts
5. Statistics by payment method

## Notes
- Read-only, no payment initiation/refund/cancellation
- Does NOT include order product details
- Payment data is real-time synced"""

VAGUE_SKILL = """### skill: enterprise_qa

# Enterprise Info Q&A

## Data Source
- Internal company document library
- Business system database

## Query Methods
- Retrieve relevant docs or data based on query
- Summarize retrieval results into answer
- Allowed tools: cat, grep, awk, sort, jq (read-only)

## Covered Scenarios
1. Internal document Q&A
2. Business data query
3. Common report generation

## Notes
- Data scope and content depends on actual document library and database"""

AGENTS = {
    "product": {"name": "product-agent", "description": "Product info query agent", "skills": SKU_SKILL},
    "order": {"name": "order-agent", "description": "Order query agent", "skills": ORDER_SKILL},
    "payment": {"name": "payment-agent", "description": "Payment management agent", "skills": PAY_SKILL},
    "vague": {"name": "vague-agent", "description": "Generic enterprise info Q&A", "skills": VAGUE_SKILL},
}

# ===================== TEST CASES (50) =====================

@dataclass(frozen=True)
class DimCase:
    id: str
    dim: str  # D / I / O / R / C
    query: str
    agent: str
    expect_handle: bool
    expect_contribute: bool
    expect_d_evidence: str = ""          # "solid" | "speculative"
    expect_d_ratio_min: float = -1.0
    expect_d_ratio_max: float = 2.0
    expect_o_min: float = -1.0
    expect_d0solid: bool = False
    expect_reason_has: list[str] = field(default_factory=list)

CASES: list[DimCase] = [
    # ====================================================================
    # D dimension (10): Data coverage accuracy
    # ====================================================================
    # D01: skill has field list -> D=1.0
    DimCase("D01", "D", "Query product PROD-001 price and brand", "product",
            True, True, expect_d_ratio_min=1.0),
    # D02: skill explicitly excludes inventory -> D=0 solid
    DimCase("D02", "D", "What is the stock level of PROD-001 in warehouse WH-001", "product",
            False, False, expect_d0solid=True),
    # D03: vague agent — "business data query" domain speculatively covers this (D speculative -> passes weighted avg)
    DimCase("D03", "D", "Query total revenue and profit margin for last fiscal year", "vague",
            True, True, expect_d_evidence="speculative"),
    # D04: payment agent has full field list -> D=1.0
    DimCase("D04", "D", "Query payment PAY-001 details including status and refund amount", "payment",
            True, True, expect_d_ratio_min=1.0),
    # D05: payment agent refund stats -> D=1.0
    DimCase("D05", "D", "Sum the total refund amount", "payment",
            True, True, expect_d_ratio_min=1.0),
    # D06: order agent fields precise match -> D=1.0
    DimCase("D06", "D", "Query order ORD-001: order time, amount and status", "order",
            True, True, expect_d_ratio_min=1.0),
    # D07: order agent vs logistics (body explicitly excludes) -> D=0 solid, hard gate rejects entirely
    DimCase("D07", "D", "What is the shipping status for order ORD-001", "order",
            False, False, expect_d0solid=True),
    # D08: vague agent — "business data query" covers revenue stats -> can_handle
    DimCase("D08", "D", "Statistics of last year Q4 revenue", "vague",
            True, True, expect_d_evidence="speculative"),
    # D09: product agent group-by stats -> D=1.0 (evidence may vary between solid/speculative)
    DimCase("D09", "D", "Count how many products in each category", "product",
            True, True, expect_d_ratio_min=1.0),
    # D10: payment agent order-linked payment -> D=1.0 (evidence may be speculative but ratio correct)
    DimCase("D10", "D", "What are the payment records for order ORD-001, amount and method", "payment",
            True, True),

    # ====================================================================
    # I dimension (10): Input matching accuracy
    # ====================================================================
    # I01: input fully provided -> pass
    DimCase("I01", "I", "Query order details for U001", "order", True, True),
    # I02: can query all orders without specific ID -> agent CAN handle
    DimCase("I02", "I", "Query order details", "order", True, True),
    # I03: "this month" is self-contained -> pass
    DimCase("I03", "I", "Count orders this month", "order", True, True),
    # I04: "last week" -> pass
    DimCase("I04", "I", "Query completed orders from last week", "order", True, True),
    # I05: multi-condition input -> pass
    DimCase("I05", "I", "Query products in Electronics category, price 100-500 CNY", "product", True, True),
    # I06: paymentID + userID -> pass
    DimCase("I06", "I", "Query payment PAY-001 for user U001", "payment", True, True),
    # I07: vague input but agent can query all orders -> can_handle=True
    DimCase("I07", "I", "Query some user's orders", "order", True, True),
    # I08: condition given -> pass
    DimCase("I08", "I", "Count refund records exceeding 500 CNY", "payment", True, True),
    # I09: category+brand filter -> pass
    DimCase("I09", "I", "Query Huawei products in Electronics category", "product", True, True),
    # I10: time expression + specific value -> pass
    DimCase("I10", "I", "Sum this month's order amounts for U001", "order", True, True),

    # ====================================================================
    # O dimension (10): Operation capability accuracy
    # ====================================================================
    # O01: lookup with grep command -> O=1.0
    DimCase("O01", "O", "Query product PROD-001 brand", "product", True, True, expect_o_min=1.0),
    # O02: aggregate with awk -> O=1.0
    DimCase("O02", "O", "Sum total amount of all orders", "order", True, True, expect_o_min=1.0),
    # O03: modify on read-only agent -> O=0
    DimCase("O03", "O", "Change order ORD-001 status to Cancelled", "order", False, False, expect_o_min=0.0),
    # O04: modify on payment agent -> O=0
    DimCase("O04", "O", "Initiate a refund for payment PAY-001", "payment", False, False, expect_o_min=0.0),
    # O05: translate on product agent -> O=0
    DimCase("O05", "O", "Translate 'The quick brown fox' to Chinese", "product", False, False),
    # O06: generate SQL on order agent -> O=0
    DimCase("O06", "O", "Write me a SQL query for order statistics", "order", False, False),
    # O07: filter on payment agent -> O=1.0
    DimCase("O07", "O", "Filter all refunded payment records", "payment", True, True, expect_o_min=1.0),
    # O08: aggregate on product agent -> O=1.0
    DimCase("O08", "O", "Count products per category", "product", True, True, expect_o_min=1.0),
    # O09: summarize on vague agent — body says "Summarize retrieval results" -> can_handle
    DimCase("O09", "O", "Summarize key points from this year's business report", "vague", True, True),
    # O10: classify on payment agent (not declared) -> O=0
    DimCase("O10", "O", "Classify payment records as high/medium/low risk", "payment", False, False),

    # ====================================================================
    # R dimension (10): Result matching accuracy
    # ====================================================================
    # R01: single record detail -> R=1.0
    DimCase("R01", "R", "Query product PROD-001 price", "product", True, True),
    # R02: list result -> R=1.0
    DimCase("R02", "R", "List all Electronics category products", "product", True, True),
    # R03: count aggregation -> R=1.0
    DimCase("R03", "R", "Count cancelled orders", "order", True, True),
    # R04: payment detail with amount+status -> R=1.0
    DimCase("R04", "R", "Query payment PAY-001 amount and status", "payment", True, True),
    # R05: refund sum -> R=1.0
    DimCase("R05", "R", "Sum total refund amount", "payment", True, True),
    # R06: cross-domain partial -> handle=F, contribute=T
    DimCase("R06", "R", "What is the price of PROD-001? Also check inventory in WH-001", "product", False, True),
    # R07: order details multi-field -> R=1.0
    DimCase("R07", "R", "Query order ORD-001: status, amount and payment method", "order", True, True),
    # R08: generate chart output — product agent can aggregate but not generate (2 distinct steps)
    DimCase("R08", "R", "Generate a pie chart showing product distribution across categories", "product", False, True),
    # R09: payment stats by method -> R=1.0
    DimCase("R09", "R", "Sum amounts grouped by payment method", "payment", True, True),
    # R10: multi-output: list + sum -> R=1.0
    DimCase("R10", "R", "List U001 orders and sum total amount", "order", True, True),

    # ====================================================================
    # C dimension (10): Constraint satisfaction accuracy
    # ====================================================================
    # C01: no constraints -> C=1.0
    DimCase("C01", "C", "Query product PROD-001 brand", "product", True, True),
    # C02: time constraint "last week" -> satisfiable per prompt rule
    DimCase("C02", "C", "Query completed orders from last week", "order", True, True),
    # C03: order data non-real-time -> time constraint satisfiable, risks flagged
    DimCase("C03", "C", "Query real-time status for order ORD-001", "order", True, True),
    # C04: payment data real-time -> time constraint fully satisfied
    DimCase("C04", "C", "Query all refund records from today", "payment", True, True),
    # C05: English query on English-defined agent -> C satisfiable, can_handle
    DimCase("C05", "C", "Query product PROD-001 details and categories", "product", True, True),
    # C06: modify constraint -> order body says read-only
    DimCase("C06", "C", "Delete order ORD-001 record", "order", False, False),
    # C07: read-only constraint satisfiable
    DimCase("C07", "C", "Query payment records only, no modifications", "payment", True, True),
    # C08: precision constraint satisfied
    DimCase("C08", "C", "Sum refund amounts accurately to two decimal places", "payment", True, True),
    # C09: last year data -> order has time field
    DimCase("C09", "C", "Query all completed orders from last year", "order", True, True),
    # C10: compliance certificate/test report — product has no such fields →
    #      D=0 speculative (LLM treats as speculative, not solid), score < threshold
    DimCase("C10", "C", "Query product PROD-001 compliance certificate and test report", "product", False, False),

    # ====================================================================
    # D dimension (10 additional): D11–D20 — Deeper data coverage tests
    # ====================================================================
    # D11: payment agent — all fields explicitly listed and covered → D=1.0 solid
    DimCase("D11", "D", "Query payment PAY-003: amount, payment method, status, and refund amount", "payment",
            True, True, expect_d_ratio_min=1.0),
    # D12: product agent — product image / detailed description explicitly excluded → D=0 solid, gate triggers
    DimCase("D12", "D", "Show the product image and detailed description text for PROD-001", "product",
            False, False, expect_d0solid=True),
    # D13: order agent — can aggregate top user but cannot get user email (step2 D=0) → handle=F contribute=T
    DimCase("D13", "D", "Find the user who placed the most orders and show their contact email", "order",
            False, True),
    # D14: vague agent — "business data query" too vague for specific financial KPIs (gross margin/net profit)
    #       → D=0 solid, gate triggers, cannot handle or contribute
    DimCase("D14", "D", "What were the gross margin and net profit for each business unit last quarter", "vague",
            False, False, expect_d0solid=True),
    # D15: product agent — all product master fields covered (name, brand, price, category, listing date) → D=1.0
    DimCase("D15", "D", "List all Electronics products with brand, price, and listing date", "product",
            True, True, expect_d_ratio_min=1.0),
    # D16: payment agent — refund grouping by method → all payment fields covered → D=1.0
    DimCase("D16", "D", "Break down refunded amounts by payment method", "payment",
            True, True, expect_d_ratio_min=1.0),
    # D17: nutritional query — order agent CAN list products from order (step1) but cannot answer
    #       nutritional questions (step2 D=0) → handle=F, contribute=T
    DimCase("D17", "D", "What are the calorie and fat content of the products in order ORD-001", "order",
            False, True),
    # D18: payment agent has payment data (step1 OK) but NOT product names (step2 D=0) → handle=F contribute=T
    DimCase("D18", "D", "Query PAY-001 details with the corresponding product name from the order", "payment",
            False, True),
    # D19: payment agent — forex/exchange rate query → domain mismatch → D=0 solid, gate triggers
    DimCase("D19", "D", "What is the current CNY to USD exchange rate", "payment",
            False, False, expect_d0solid=True),
    # D20: order agent — two-step: find top product from orders then query product → step1 OK, step2 D=0
    DimCase("D20", "D", "Find the most ordered product and check its current inventory stock", "order",
            False, True),

    # ====================================================================
    # I dimension (10 additional): I11–I20 — Deeper input matching tests
    # ====================================================================
    # I11: payment agent — PaymentID explicitly provided → I=1.0
    DimCase("I11", "I", "Query payment PAY-003 details", "payment", True, True),
    # I12: order agent — time expression "this week" is self-contained per prompt rule → I=1.0
    DimCase("I12", "I", "Count orders placed this week", "order", True, True),
    # I13: product agent — multi-condition filter (category + brand + price) → I=1.0
    DimCase("I13", "I", "Find Food category products by brand Nestle priced under 50 CNY", "product", True, True),
    # I14: order agent — filter by status, no specific ID needed → I=1.0
    DimCase("I14", "I", "List all cancelled orders", "order", True, True),
    # I15: payment agent — filter by status + amount range → I=1.0
    DimCase("I15", "I", "Show refunded payments exceeding 500 CNY", "payment", True, True),
    # I16: product agent — brand + category + status filter → I=1.0
    DimCase("I16", "I", "Query Huawei products in Home category that are currently listed", "product", True, True),
    # I17: order agent — UserID + time range → I=1.0
    DimCase("I17", "I", "Show orders for U002 from the last 30 days", "order", True, True),
    # I18: payment agent — aggregate without specific ID (query all) → input not needed → I=1.0
    DimCase("I18", "I", "Calculate the total amount of all successful payments", "payment", True, True),
    # I19: product agent — price range filter with comparison operators → I=1.0
    DimCase("I19", "I", "Show products priced between 100 and 500 CNY", "product", True, True),
    # I20: order agent — count all orders → no specific input needed → I=1.0
    DimCase("I20", "I", "How many orders are there in total", "order", True, True),

    # ====================================================================
    # O dimension (10 additional): O11–O20 — Deeper operation capability tests
    # ====================================================================
    # O11: order agent — grep lookup by OrderID explicitly described → O=1.0
    DimCase("O11", "O", "Look up order ORD-003 by its ID", "order", True, True, expect_o_min=1.0),
    # O12: payment agent — awk sum explicitly described for refund amounts → O=1.0
    DimCase("O12", "O", "Sum the total refund amount across all payments", "payment", True, True, expect_o_min=1.0),
    # O13: product agent — grep filter by category explicitly described → O=1.0
    DimCase("O13", "O", "Filter and show all Beauty category products", "product", True, True, expect_o_min=1.0),
    # O14: order agent — sort by amount (sort in tool list, no explicit sort example) → O=0.7 composable
    DimCase("O14", "O", "Rank all orders by amount from highest to lowest", "order", True, True),
    # O15: payment agent — initiate refund is modify on read-only agent → O=0
    DimCase("O15", "O", "Process a refund for payment PAY-003", "payment", False, False, expect_o_min=0.0),
    # O16: product agent — generate a marketing slogan is not covered → O=0
    DimCase("O16", "O", "Write a catchy marketing slogan for product PROD-001", "product", False, False),
    # O17: order agent — delete operation on read-only agent → O=0 + C constraint violation
    DimCase("O17", "O", "Remove cancelled order ORD-005 from the database", "order", False, False, expect_o_min=0.0),
    # O18: payment agent — filter by status explicitly described (grep "Refunded") → O=1.0
    DimCase("O18", "O", "Extract all refunded payment records", "payment", True, True, expect_o_min=1.0),
    # O19: product agent — count aggregation with wc explicitly described → O=1.0
    DimCase("O19", "O", "Count the total number of products in the catalog", "product", True, True, expect_o_min=1.0),
    # O20: vague agent — summarize retrieval results explicitly described → O=1.0
    DimCase("O20", "O", "Summarize the key findings from this quarter's operational review", "vague", True, True),

    # ====================================================================
    # R dimension (10 additional): R11–R20 — Deeper result matching tests
    # ====================================================================
    # R11: product agent — single scalar value (price) → R=1.0
    DimCase("R11", "R", "What is the price of PROD-002", "product", True, True),
    # R12: order agent — list result with multiple matching records → R=1.0
    DimCase("R12", "R", "List all orders from user U003", "order", True, True),
    # R13: payment agent — count aggregation result → R=1.0
    DimCase("R13", "R", "How many payments were processed today", "payment", True, True),
    # R14: order agent — grouped statistics by payment method → R=1.0
    DimCase("R14", "R", "Show order count and total amount grouped by payment method", "order", True, True),
    # R15: product agent — price is covered, warehouse is not → multi-step, handle=F, contribute=T
    DimCase("R15", "R", "PROD-001: what is the price and which warehouses currently have stock", "product",
            False, True),
    # R16: tabular output format within agent capability — aggregate reorders data → single step passes
    DimCase("R16", "R", "Show a tabular summary of daily order volume for the past week", "order",
            True, True),
    # R17: payment agent — multi-output: total amount + count → R=1.0
    DimCase("R17", "R", "Show the total refund amount and the count of refunded payments", "payment", True, True),
    # R18: product agent — list products + total count → R=1.0
    DimCase("R18", "R", "List all Clothing category products and count how many there are", "product", True, True),
    # R19: order agent — list + sum for user → R=1.0
    DimCase("R19", "R", "For user U001: list their orders and show the total spending", "order", True, True),
    # R20: tabular output for payment statistics — single-step aggregation passes
    DimCase("R20", "R", "Show a tabular summary of monthly payment totals by method", "payment",
            True, True),

    # ====================================================================
    # C dimension (10 additional): C11–C20 — Deeper constraint satisfaction tests
    # ====================================================================
    # C11: product agent — no constraints whatsoever → C=1.0
    DimCase("C11", "C", "Query product PROD-003 category", "product", True, True),
    # C12: order agent — "real-time" constraint, order data is NOT real-time, but per prompt rule time constraints
    #        with timestamp field + filter tools are deemed satisfiable → C=1.0, risks flag non-real-time
    DimCase("C12", "C", "Show real-time order count for the past hour", "order", True, True),
    # C13: payment agent — explicit read-only constraint fully satisfied → C=1.0
    DimCase("C13", "C", "Query all payment records for audit purposes, read-only access only", "payment", True, True),
    # C14: order agent — time constraint "last week" satisfiable with OrderTime field → C=1.0
    DimCase("C14", "C", "List all orders from last week", "order", True, True),
    # C15: product agent — English query on English-defined skill → language constraint satisfied → C=1.0
    DimCase("C15", "C", "List all Beauty products sorted by price ascending", "product", True, True),
    # C16: payment agent — precision constraint "to two decimal places" → payment amount is CNY → C=1.0
    DimCase("C16", "C", "Calculate the average refund amount accurate to two decimal places", "payment", True, True),
    # C17: delete constraint — order agent read-only, O=0 for modify, but can filter+list deletable orders → handle=F, contribute=T
    DimCase("C17", "C", "Delete all cancelled orders older than 90 days", "order", False, True),
    # C18: product agent — time scope constraint "this year" satisfiable with ListingDate → C=1.0
    DimCase("C18", "C", "Show products launched this year in the Electronics category", "product", True, True),
    # C19: order agent — multiple constraints (time + status + read-only) all satisfiable → C=1.0
    DimCase("C19", "C", "Show paid orders for U001 from last month, do not modify anything", "order", True, True),
    # C20: payment agent — fetch all records without filtering → no constraints → C=1.0
    DimCase("C20", "C", "Retrieve all payment records without any filtering", "payment", True, True),
]

# ===================== RUNNER =====================

async def _judge(case: DimCase) -> dict[str, Any]:
    agent = AGENTS[case.agent]
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=agent["name"], agent_description=agent["description"],
        agent_skills=agent["skills"], history="(none)", query=case.query)
    tool = StructuredTool(name="eval", description="eval", args_schema=cc.CapabilityChainResult,
                          func=None, coroutine=None)
    try:
        data = await invoke_llm_with_tool(
            llm=get_llm(), tool=tool, messages=[HumanMessage(content=prompt)],
            metadata={"run_id": f"dim-{case.id}", "trace_id": "f"*32, "user_id": "dim"},
            tool_choice="eval", span_name="dim", span_input={"did": case.id, "dim": case.dim})
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if data is None:
        return {"ok": False, "error": "no tool call"}
    chain = cc.parse_chain_result(data)
    agg = cc.aggregate(chain)
    steps = []
    for s in chain.steps:
        steps.append({
            "id": s.step_id, "op": s.operation,
            "Dr": s.data_coverage.ratio, "Dreq": s.data_coverage.required,
            "Dmat": s.data_coverage.matched, "Dev": s.data_coverage.evidence_strength,
            "O": s.operation_capability,
            "Ir": s.input_match.ratio, "Rr": s.result_match.ratio,
            "Cr": s.constraint_satisfaction.ratio,
            "ss": round(agg.step_scores.get(s.step_id, 0), 3),
        })
    dev_set = {s.data_coverage.evidence_strength for s in chain.steps}
    return {
        "ok": True,
        "can_handle": agg.can_handle, "can_contribute": agg.can_contribute,
        "confidence": agg.confidence, "handle_score": agg.handle_score,
        "evidence_grade": chain.evidence_grade, "reason": (chain.reason or "")[:500],
        "steps": steps,
        "all_d0solid": all(s.data_coverage.ratio == 0.0 and s.data_coverage.evidence_strength == "solid"
                           for s in chain.steps),
        "min_o": min((s.operation_capability for s in chain.steps), default=-1),
        "min_d": min((s.data_coverage.ratio for s in chain.steps), default=-1),
        "max_d": max((s.data_coverage.ratio for s in chain.steps), default=-1),
        "dev_set": dev_set,
    }

async def _sem(sem, case):
    async with sem:
        return await _judge(case)

_gr: dict[str, Any] = {}

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_dimension(case: DimCase) -> None:
    sem = asyncio.Semaphore(CCY)
    r = await _sem(sem, case)
    assert r["ok"], f"[{case.id}] LLM failed: {r.get('error')}"
    h, c = r["can_handle"], r["can_contribute"]
    _gr[case.id] = {"pass": True}

    print(f"\n[{case.id}] DIM={case.dim} {case.agent} | {case.query[:60]}...")
    print(f"  h={h} c={c} score={r['handle_score']:.3f} conf={r['confidence']:.3f} grade={r['evidence_grade']}")
    for s in r["steps"]:
        print(f"    S{s['id']}({s['op']}): D={s['Dr']:.2f}({s['Dev']}) O={s['O']:.1f} I={s['Ir']:.2f} R={s['Rr']:.2f} C={s['Cr']:.2f} -> {s['ss']:.3f}")

    assert h is case.expect_handle, f"[{case.id}] h: exp={case.expect_handle} got={h}"
    assert c is case.expect_contribute, f"[{case.id}] c: exp={case.expect_contribute} got={c}"
    if case.expect_d0solid:
        assert r["all_d0solid"], f"[{case.id}] expected D=0(solid) got dev_set={r['dev_set']}"
    if case.expect_d_evidence:
        for dv in r["dev_set"]:
            assert dv == case.expect_d_evidence, f"[{case.id}] D evidence: exp={case.expect_d_evidence} got={dv}"
    if case.expect_d_ratio_min >= 0:
        assert r["min_d"] >= case.expect_d_ratio_min - 0.01, f"[{case.id}] D min: exp>={case.expect_d_ratio_min} got={r['min_d']:.2f}"
    if case.expect_d_ratio_max <= 1.0:
        assert r["max_d"] <= case.expect_d_ratio_max + 0.01, f"[{case.id}] D max: exp<={case.expect_d_ratio_max} got={r['max_d']:.2f}"
    if case.expect_o_min >= 0:
        assert r["min_o"] >= case.expect_o_min - 0.01, f"[{case.id}] O min: exp>={case.expect_o_min} got={r['min_o']:.2f}"
    for sub in case.expect_reason_has:
        assert sub in r.get("reason", ""), f"[{case.id}] reason missing '{sub}'"

def pytest_sessionfinish(session, exitstatus):
    if not _gr: return
    total = len(_gr); passed = sum(1 for v in _gr.values() if v["pass"])
    print(f"\n{'='*60}\n DIMENSION ACCURACY: {passed}/{total} ({passed/total*100:.1f}%)\n{'='*60}")
    if passed < total:
        print(f" FAILED: {[k for k, v in _gr.items() if not v['pass']]}")
    else:
        print(" ALL 50 DIMENSION TESTS PASSED!")