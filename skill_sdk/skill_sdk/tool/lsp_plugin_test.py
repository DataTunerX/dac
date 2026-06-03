"""End-to-end smoke test for skill_sdk.skill.runner.SkillRunner.

Run **from repo root** (directory that contains the ``skill_sdk`` package), e.g.::

    cd /path/to/dac/skill_sdk
    python3 skill_sdk/tool/lsp_plugin_test.py

or equivalently::

    python3 -m skill_sdk.tool.lsp_plugin_test

Do **not** invoke this file in isolation from another cwd without the repo on
``PYTHONPATH`` — the bootstrap below only fixes ``sys.path`` when the script is
run directly.

Before running, put skill packages under ``<repo>/skills/`` and ensure
``model_sdk`` / LangChain / API keys are available (see env and credentials
below).

For PDF multimodal via ``extract_pdf``, replace the placeholder values in the
``PDF_VISION_*`` env vars (see below ``os.environ.setdefault(...)`` block).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

# ``skill_sdk/tool/lsp_plugin_test.py`` → parents[2] = repo root (parent of inner ``skill_sdk/``)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if __name__ == "__main__":
    root_s = str(_REPO_ROOT)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)

os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

from langchain_core.messages import HumanMessage  # noqa: E402
from model_sdk import ModelManager  # noqa: E402
from skill_sdk.skill.runner import SkillRunner  # noqa: E402
from skill_sdk.tool.code_execution import CodeExecution  # noqa: E402

SKILLS_DIR = _REPO_ROOT / "skills"


DASHSCOPE_API_KEY = os.environ.get(
    "OPENAI_API_KEY", "sk-xxx"
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-flash"


def build_llm():
    manager = ModelManager()
    return manager.get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        # model="deepseek-v3.2",
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def build_code_execution(llm) -> CodeExecution:
    """构造一个 ``CodeExecution`` 实例供 ``SkillRunner`` 注入。

    与 ``SkillRunner`` **共用同一份** ``llm``，避免 ``CodeExecution`` 里再
    ``get_llm`` 一次（重复建连接与配置）。

    仅当 ``SkillRunner(..., code_execution=...)`` 时才会把 ``code_exec`` 绑给
    模型。``metadata.trace_id`` 用 32 位 hex，满足 Langfuse 对 trace_id 的格式要求。
    """
    return CodeExecution(
        llm=llm,
        max_retries=3,
    )


def print_section(title: str) -> None:
    line = "=" * max(60, len(title) + 4)
    print(f"\n{line}\n{title}\n{line}")


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


async def demo_smoke(llm) -> None:
    print_section("Smoke: single LLM call")
    result = await llm.ainvoke([HumanMessage(content="Hello, reply one word.")])
    print(result.content)


async def demo_make_plan(runner: SkillRunner, query: str) -> None:
    print_section(f"make_plan: {query}")
    step = await runner.make_plan(query=query)
    print(dump(step.model_dump()))


async def demo_plan_and_run(runner: SkillRunner, query: str) -> None:
    print_section(f"plan_and_run: {query}")
    result = await runner.plan_and_run(query=query, user_id="user01", run_id="run01", trace_id="abcdef1234567890abcdef1234567890")
    print(dump(result))


async def main() -> None:
    llm = build_llm()

    runner = SkillRunner(
        llm=llm,
        max_steps=100,
        cmd_timeout_sec=60,
        same_cmd_fail_budget=2,
        total_fail_budget=3,
        make_plan_max_attempts=3,
        code_execution=build_code_execution(llm),
    )

    if not SKILLS_DIR.is_dir():
        raise SystemExit(
            f"Skills directory not found: {SKILLS_DIR}. "
            "Put *.zip skill packages there before running the test."
        )

    skills = runner.load_from_dir(SKILLS_DIR)
    print_section("Loaded skills")
    print(runner.lister.list_skills())
    print(f"Total: {len(skills)} skill(s)")

    try:

        # ===========================================================================
        # 下面 8 个查询 × 8 种语言 = 64 个测试 case，分别触发不同的 LSP 操作组合
        #
        # 每个语言包两种场景：
        #   - core/（原始数据处理管线，对应 main.c / main.cpp / main.rs / main.go / core.py / core.*.java / core.*.ts / core.*.js）
        #   - shop/（电商购物子包，对应 shop/ 子目录下的完整领域上下文）
        # ===========================================================================

        # ===================================================================
        # 1. goToDefinition + documentSymbol（流程 A：定向路径）
        # 预期触发：grep → goToDefinition → documentSymbol → readline_in_range
        # 场景：用户问"某个方法的定义在哪，把完整代码读出来"
        # ===================================================================

        # --- Go: 定位 main.go 中 HandleRequest 的定义范围，读取完整代码 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/main.go "
        #     "里 HandleRequest 这个方法是定义在哪里的，把它的完整代码读出来"
        # )

        # --- Python: 定位 core.py 中 finalize_result 函数的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/core.py "
        #     "里 finalize_result 这个函数是怎么定义的，把它的完整代码读出来"
        # )

        # --- Java: 定位 core/DefaultProcessor 中 process 方法的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/core/DefaultProcessor.java "
        #     "里 process 方法是怎么定义的，把它的完整代码读出来"
        # )
        #
        # --- C: 定位 core/default_processor.c 中 default_processor_init 函数的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/core/default_processor.c "
        #     "里 default_processor_init 函数是怎么定义的，把它的完整代码读出来"
        # )
        #
        # --- C++: 定位 core/DefaultProcessor.cpp 中 Process 方法的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/core/DefaultProcessor.cpp "
        #     "里 Process 方法是怎么定义的，把它的完整代码读出来"
        # )
        #
        # --- Rust: 定位 core/default_processor.rs 中 process 方法的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/core/default_processor.rs "
        #     "里 process 方法是怎么定义的，把它的完整代码读出来"
        # )

        # --- TypeScript: 定位 core/DefaultProcessor.ts 中 process 方法的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/core/DefaultProcessor.ts "
        #     "里 process 方法是怎么定义的，把它的完整代码读出来"
        # )
        #
        # --- JavaScript: 定位 core/DefaultProcessor.js 中 process 方法的定义 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/core/DefaultProcessor.js "
        #     "里 process 方法是怎么定义的，把它的完整代码读出来"
        # )

        # ===================================================================
        # 2. goToImplementation（流程：接口 → 实现）
        # 预期触发：grep → goToImplementation → documentSymbol → readline_in_range
        # 场景：用户问"这个接口有哪些具体实现"
        # ===================================================================

        # --- Go: DataProcessor 接口 → DefaultProcessor 实现 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/main.go "
        #     "里 DataProcessor 这个接口有哪些具体实现，每个实现的结构是怎样的"
        # )

        # --- Python: Repository ABC → InMemoryRepository + PostgresRepository ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/shop/repository.py "
        #     "里 Repository 这个抽象类有哪些具体实现，每个实现的结构是怎样的"
        # )

        # --- Java: PaymentGateway 接口 → StripeGateway + PayPalGateway + MockGateway ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/shop/payment/PaymentGateway.java "
        #     "里 PaymentGateway 这个接口有哪些具体实现，每个实现的结构是怎样的"
        # )
        #
        # --- C: DataProcessor 接口(vtable) → DefaultProcessor 实现 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/core/data_processor.h "
        #     "里 DataProcessor 这个接口(vtable)有哪些具体实现，每个实现的结构是怎样的"
        # )
        #
        # --- C++: PaymentGateway 接口 → StripeGateway + PayPalGateway + MockGateway ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/shop/PaymentGateway.h "
        #     "里 PaymentGateway 这个接口有哪些具体实现，每个实现的结构是怎样的"
        # )
        #
        # --- Rust: DiscountStrategy trait → PercentageDiscount + FixedAmountDiscount + BogoDiscount ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/shop/discount/discount_strategy.rs "
        #     "里 DiscountStrategy 这个 trait 有哪些具体实现，每个实现的结构是怎样的"
        # )
        #
        # --- TypeScript: DiscountStrategy 接口 → PercentageDiscount + FixedAmountDiscount + BogoDiscount ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/shop/discount/DiscountStrategy.ts "
        #     "里 DiscountStrategy 这个接口有哪些具体实现，每个实现的结构是怎样的"
        # )
        #
        # --- JavaScript: PaymentGateway 抽象类 → StripeGateway + PayPalGateway + MockGateway ---
        await demo_plan_and_run(
            runner,
            "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/shop/payment/PaymentGateway.js "
            "里 PaymentGateway 这个抽象类有哪些具体实现，每个实现的结构是怎样的"
        )

        # ===================================================================
        # 3. findReferences（流程 C：引用查找）
        # 预期触发：grep → findReferences
        # 场景：用户问"这个方法被哪些地方引用到了"
        # ===================================================================

        # --- Go: Validate 方法被哪些地方引用（Process, HandleRequest, handler.go）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/ "
        #     "这个目录里，看看 Validate 方法在哪些地方被引用到了"
        # )

        # --- Python: validate 方法被哪些地方引用（base class override + caller）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/ "
        #     "这个目录里，看看 validate 方法在哪些地方被引用到了"
        # )

        # --- Java: rawTotal 方法被哪些地方引用（Order → Cart, DiscountUtils）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/ "
        #     "这个目录里，看看 rawTotal 方法在哪些地方被引用到了"
        # )
        #
        # --- C: default_processor_fill 函数被哪些地方引用 ---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/ "
        #     "这个目录里，看看 default_processor_fill 函数在哪些地方被引用到了"
        # )
        #
        # --- C++: Validate 方法被哪些地方引用（DefaultProcessor, Handler）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/ "
        #     "这个目录里，看看 Validate 方法在哪些地方被引用到了"
        # )
        #
        # --- Rust: new_helper 函数被哪些地方引用（handler.rs, main.rs）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/ "
        #     "这个目录里，看看 new_helper 函数在哪些地方被引用到了"
        # )
        #
        # --- TypeScript: rawTotal 方法被哪些地方引用（Order → Cart, DiscountUtils）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/ "
        #     "这个目录里，看看 rawTotal 方法在哪些地方被引用到了"
        # )
        #
        # --- JavaScript: validate 方法被哪些地方引用（DefaultProcessor, Handler）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/ "
        #     "这个目录里，看看 validate 方法在哪些地方被引用到了"
        # )

        # ===================================================================
        # 4. prepareCallHierarchy + outgoingCalls（流程 D：正向展开调用链）
        # 预期触发：grep → prepareCallHierarchy → outgoingCalls → documentSymbol → readline_in_range
        # 场景：用户问"这个函数内部调了哪些方法，顺着链条往下追"
        # ===================================================================

        # --- Go: HandleRequest → Validate + Process + FinalizeOutput ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/main.go "
        #     "里 HandleRequest 函数内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )

        # --- Python: Cart.checkout → to_order + discount.apply + gateway.charge + repo.* ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/shop/cart.py "
        #     "里 checkout 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )

        # --- Java: Cart.checkout → toOrder + discount.apply + gateway.charge + repo.* ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/shop/cart/Cart.java "
        #     "里 checkout 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )
        #
        # --- C: order_service_place_order → cart_raw_total + discount.apply + gateway.charge + repo.save ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/shop/order_service.c "
        #     "里 order_service_place_order 函数内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )
        #
        # --- C++: PlaceOrder → ToOrder + Checkout (内部含 Charge, Save, Apply) ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/shop/OrderService.cpp "
        #     "里 PlaceOrder 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )
        #
        # --- Rust: place_order → raw_total + discount.apply + gateway.charge + repo.save ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/shop/service.rs "
        #     "里 place_order 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )
        #
        # --- TypeScript: Cart.checkout → toOrder + discount.apply + gateway.charge + repo.* ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/shop/cart/Cart.ts "
        #     "里 checkout 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )
        #
        # --- JavaScript: Cart.checkout → toOrder + discount.apply + gateway.charge + repo.* ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/shop/cart/Cart.js "
        #     "里 checkout 方法内部调用了哪些方法，顺着调用链往下追踪一下这些方法都是干什么的"
        # )

        # ===================================================================
        # 5. prepareCallHierarchy + incomingCalls（流程 D：反向追溯调用者）
        # 预期触发：grep → prepareCallHierarchy → incomingCalls
        # 场景：用户问"谁调用了这个函数，在哪些文件和哪些行"
        # ===================================================================

        # --- Go: 谁调用了 TransformData（被 DefaultProcessor.Process 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/ "
        #     "这个目录里，谁调用了 TransformData 函数，告诉我是在哪些文件和哪些行调用的"
        # )

        # --- Python: 谁调用了 apply_best_discount（被 OrderService.place_order 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/ "
        #     "这个目录里，谁调用了 apply_best_discount 函数，告诉我是在哪些文件和哪些行调用的"
        # )

        # --- Java: 谁调用了 DiscountUtils.applyBestDiscount（被 OrderService.placeOrder 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/ "
        #     "这个目录里，谁调用了 applyBestDiscount 方法，告诉我是在哪些文件和哪些行调用的"
        # )
        #
        # --- C: 谁调用了 finalize_output（被 helper_handle_request 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/ "
        #     "这个目录里，谁调用了 finalize_output 函数，告诉我是在哪些文件和哪些行调用的"
        # )
        #
        # --- C++: 谁调用了 HandleRequest（被 Handler.ProcessRequest 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/ "
        #     "这个目录里，谁调用了 HandleRequest 方法，告诉我是在哪些文件和哪些行调用的"
        # )
        #
        # --- Rust: 谁调用了 finalize_output（被 helper.handle_request 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/ "
        #     "这个目录里，谁调用了 finalize_output 函数，告诉我是在哪些文件和哪些行调用的"
        # )
        #
        # --- TypeScript: 谁调用了 DiscountUtils.applyBestDiscount（被 OrderService.placeOrder 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/ "
        #     "这个目录里，谁调用了 applyBestDiscount 方法，告诉我是在哪些文件和哪些行调用的"
        # )
        #
        # --- JavaScript: 谁调用了 TransformData.transform（被 DefaultProcessor.process 调用）---
        # await demo_plan_and_run(
        #     runner,
        #     "在 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/ "
        #     "这个目录里，谁调用了 transform 方法，告诉我是在哪些文件和哪些行调用的"
        # )

        # ===================================================================
        # 6. prepareCallHierarchy + outgoingCalls + incomingCalls（流程 D：双向完整调用关系）
        # 预期触发：grep → prepareCallHierarchy → outgoingCalls + incomingCalls
        # 场景：用户问"展示这个函数的完整调用关系——谁调了它，它又调了谁"
        # ===================================================================

        # --- Go: HandleRequest 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/main.go "
        #     "里面 HandleRequest 的完整调用关系图——谁调了它，它又调了谁"
        # )

        # --- Python: Cart.checkout 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/shop/cart.py "
        #     "里面 checkout 的完整调用关系图——谁调了它，它又调了谁"
        # )

        # --- Java: Cart.checkout 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/shop/cart/Cart.java "
        #     "里面 checkout 的完整调用关系图——谁调了它，它又调了谁"
        # )
        #
        # --- C: order_service_place_order 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/shop/order_service.c "
        #     "里面 order_service_place_order 的完整调用关系图——谁调了它，它又调了谁"
        # )
        #
        # --- C++: Cart.Checkout 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/shop/cart.cpp "
        #     "里面 Checkout 的完整调用关系图——谁调了它，它又调了谁"
        # )
        #
        # --- Rust: place_order 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/shop/service.rs "
        #     "里面 place_order 的完整调用关系图——谁调了它，它又调了谁"
        # )
        #
        # --- TypeScript: Cart.checkout 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/shop/cart/Cart.ts "
        #     "里面 checkout 的完整调用关系图——谁调了它，它又调了谁"
        # )
        #
        # --- JavaScript: OrderService.placeOrder 双向调用关系 ---
        # await demo_plan_and_run(
        #     runner,
        #     "分析 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/shop/service/OrderService.js "
        #     "里面 placeOrder 的完整调用关系图——谁调了它，它又调了谁"
        # )

        # ===================================================================
        # 7. documentSymbol（流程 B：概览路径）
        # 预期触发：documentSymbol → readline_in_range
        # 场景：用户问"这个文件里有哪些函数和类型，列个大纲"
        # ===================================================================

        # --- Go: main.go 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/main.go "
        #     "这个文件里有哪些函数和类型，给我列一个大纲出来"
        # )

        # --- Python: shop/cart.py 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/shop/cart.py "
        #     "这个文件里有哪些函数和类型，给我列一个大纲出来"
        # )

        # --- Java: shop/cart/Cart.java 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/shop/cart/Cart.java "
        #     "这个文件里有哪些函数和类型，给我列一个大纲出来"
        # )
        #
        # --- C: src/shop/order_service.h 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/shop/order_service.h "
        #     "这个文件里有哪些类型和函数，给我列一个大纲出来"
        # )
        #
        # --- C++: src/core/DefaultProcessor.h 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/core/DefaultProcessor.h "
        #     "这个文件里有哪些类型和方法，给我列一个大纲出来"
        # )
        #
        # --- Rust: src/core/default_processor.rs 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/core/default_processor.rs "
        #     "这个文件里有哪些类型和函数，给我列一个大纲出来"
        # )
        #
        # --- TypeScript: shop/cart/Cart.ts 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/shop/cart/Cart.ts "
        #     "这个文件里有哪些函数和类型，给我列一个大纲出来"
        # )
        #
        # --- JavaScript: core/DefaultProcessor.js 文件大纲 ---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/core/DefaultProcessor.js "
        #     "这个文件里有哪些函数和类型，给我列一个大纲出来"
        # )

        # ===================================================================
        # 8. goToDefinition + documentSymbol（跨文件定位 / cross-file）
        # 预期触发：grep → goToDefinition（跨文件）→ documentSymbol → readline_in_range
        # 场景：用户问"这个跨文件引用的定义在哪"
        # ===================================================================

        # --- Go: handler.go → main.go（NewHelper 跨文件定位）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/go-project/handler.go "
        #     "里 NewHelper 这个函数是定义在哪里的，把它的完整代码读出来"
        # )

        # --- Python: bridge.py → core.py（bridge_finalize 跨文件定位到 finalize_result）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/py-project/bridge.py "
        #     "里调用的 finalize_result 是定义在哪里的，把它的完整代码读出来"
        # )

        # --- Java: core/Handler → core/Helper（Handler.processRequest 跨类定位）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/java-project/src/main/java/"
        #     "com/fixture/core/Handler.java "
        #     "里调用的 handleRequest 方法是定义在哪里的，把它的完整代码读出来"
        # )
        #
        # --- C: handler.c → helper.h（handler_process_request 调用的 new_helper 定义在哪）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/c-project/src/core/handler.c "
        #     "里调用的 new_helper 函数是定义在哪里的，把它的完整代码读出来"
        # )
        #
        # --- C++: Handler.cpp → Helper.h（ProcessRequest 调用的 NewHelper 定义在哪）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/cpp-project/src/core/Handler.cpp "
        #     "里调用的 NewHelper 函数是定义在哪里的，把它的完整代码读出来"
        # )
        #
        # --- Rust: handler.rs → helper.rs（process_request 调用的 new_helper 定义在哪）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/rust-project/src/core/handler.rs "
        #     "里调用的 new_helper 函数是定义在哪里的，把它的完整代码读出来"
        # )
        #
        # --- TypeScript: core/Handler → core/Helper（Handler.processRequest 跨类定位）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/ts-project/src/core/Handler.ts "
        #     "里调用的 handleRequest 方法是定义在哪里的，把它的完整代码读出来"
        # )
        #
        # --- JavaScript: core/Handler → core/Helper（Handler.processRequest 跨类定位）---
        # await demo_plan_and_run(
        #     runner,
        #     "看看 /Users/james/daocloud/code/dac/skill_sdk/tests/fixtures/js-project/src/core/Handler.js "
        #     "里调用的 handleRequest 方法是定义在哪里的，把它的完整代码读出来"
        # )


    finally:
        runner.close()

if __name__ == "__main__":
    asyncio.run(main())
        