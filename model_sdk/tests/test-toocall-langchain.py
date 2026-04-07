import json
import os
import sys
from pathlib import Path

# 优先使用本仓库的 model_sdk，而不是 site-packages 里 pip 安装的包
_repo_root = Path(__file__).resolve().parent.parent
_root_str = str(_repo_root)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from model_sdk import ModelManager
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# python tests/test-toocall.py

def _build_llm():
    manager = ModelManager()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-7f6c05a219b14b4ba5850bfeb49575b2")
    if not api_key:
        raise RuntimeError(
            "Set DASHSCOPE_API_KEY to run this test (DashScope compatible OpenAI API)."
        )
    return manager.get_llm(
        provider="openai_compatible",
        api_key=api_key,
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "MiniMax-M2.5"),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v3.2"),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "kimi-k2.5"),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "glm-5"),
        model=os.environ.get("DASHSCOPE_LLM_MODEL", "qwen3.5-397b-a17b"),

        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def _format_tool_calls(tool_calls: list) -> str:
    """将模型返回的 tool_calls 格式化为易读文本。"""
    blocks: list[str] = []
    for i, tc in enumerate(tool_calls, 1):
        name = tc.get("name", "")
        call_id = tc.get("id", "")
        args = tc.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        args_json = json.dumps(args, ensure_ascii=False, indent=2)
        blocks.append(
            f"[tool_call #{i}]\n"
            f"  name: {name}\n"
            f"  id:   {call_id}\n"
            f"  args:\n"
            + "\n".join(f"    {line}" for line in args_json.splitlines())
        )
    return "\n\n".join(blocks)


@tool
def get_weather(location: str) -> str:
    """获取指定城市的当前天气"""
    return f"{location}的天气是晴朗的，温度25°C。"


async def demonstrate_usage():
    llm = _build_llm()
    model_with_tools = llm.bind_tools([get_weather])

    user_input = "北京今天天气怎么样？"
    messages: list = [HumanMessage(content=user_input)]

    response = await model_with_tools.ainvoke(messages)
    messages.append(response)

    if not isinstance(response, AIMessage) or not response.tool_calls:
        print(getattr(response, "content", response))
        return

    print("=== LLM tool_calls（参数格式化）===\n")
    print(_format_tool_calls(response.tool_calls))
    print()

    tools_by_name = {get_weather.name: get_weather}
    for tool_call in response.tool_calls:
        name = tool_call["name"]
        args = tool_call.get("args") or {}
        tool_fn = tools_by_name.get(name)
        observation = (
            tool_fn.invoke(args) if tool_fn is not None else f"未知工具: {name}"
        )
        messages.append(
            ToolMessage(content=str(observation), tool_call_id=tool_call["id"])
        )

    final_response = await model_with_tools.ainvoke(messages)
    print(final_response.content)


if __name__ == "__main__":
    import asyncio

    asyncio.run(demonstrate_usage())
