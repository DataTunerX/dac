"""
验证 passthrough 模式下 2 turn 只保留最后一轮skill执行的结果。

场景：
  - 总结开关关闭 (SUMMARIZE_ENABLED=false)
  - 2 turn: Turn 1 结果 ≠ Turn 2 结果
  - passthrough 应只包含 Turn 2 的结果，不包含 Turn 1 的

也验证：
  - NONE_TASK / DEPENDENT_TASK_SKIP 占位不会被输出
  - 同一 turn 内多个 task 结果相同时会重复出现（当前行为，不是bug）
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _mod in (
    "skill_sdk", "skill_sdk.skill", "skill_sdk.skill.runner",
    "skill_sdk.tool", "skill_sdk.tool.code_execution",
    "langfuse", "langfuse.langchain", "langfuse._client",
    "model_sdk", "model_sdk.api", "model_sdk.api.model_manager",
    "agent.broadcast_capability_check", "agent.agent_card_resolve",
    "agent.agentregistry_client", "agent.dataservices_client",
    "agent.tool_call_utils", "agent.skill_download",
    "agent.skill_download_refs", "agent.redis_registry",
):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules["agent.broadcast_capability_check"].ROUTING_AGENT_POOL_KEY = "routing_agent_pool"

from agent.skill_agent import (  # noqa: E402
    SkillAgentExecutor,
    NONE_TASK_UNASSIGNED_RESULT,
    DEPENDENT_TASK_SKIP_DESCRIPTION,
)


def _make(**attrs):
    inst = object.__new__(SkillAgentExecutor)
    for k, v in attrs.items():
        object.__setattr__(inst, k, v)
    return inst


TURN1_RESULT = """用户名「王五」对应的用户ID为 U003。

完整用户信息：

用户ID：U003
用户名：王五
电话：13800003333
邮箱：wangwu@example.com"""

TURN2_RESULT = "订单数据已确认：王五(U003)在2024年1月购买了iPhone 15 Pro，金额8999元。"


class TestPassthroughLastTurnOnly:
    """验证 passthrough 只输出最后 turn 的结果."""

    @pytest.mark.asyncio
    async def test_single_turn_returns_only_that_turns_result(self):
        """只传 Turn 2 的结果 → passthrough 只输出 Turn 2."""
        ex = _make(summarize_enabled=False, agent_id="test-agent")
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "initiator")
        )

        result = await ex._summarize(
            original_query="查王五的订单",
            task_results={3: TURN2_RESULT},  # Turn 2 的 ID 可能从 3 开始
            delegate_results={},
            agent_role="initiator",
        )
        assert "iPhone 15 Pro" in result
        assert "8999元" in result
        # Turn 1 的内容不应出现
        assert "wangwu@example.com" not in result

    @pytest.mark.asyncio
    async def test_two_turns_cumulative_includes_both(self):
        """如果传了 cumulative 结果（含两轮），确认 passthrough 都会输出.

        此测试意在反证：若 turn loop 错误地传了 accumulated task_results，
        用户就会看到两轮结果拼接。所以 turn loop 必须只传最后一轮。
        """
        ex = _make(summarize_enabled=False, agent_id="test-agent")
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "initiator")
        )

        result = await ex._summarize(
            original_query="查王五的订单",
            task_results={
                1: TURN1_RESULT,
                2: TURN2_RESULT,
            },
            delegate_results={},
            agent_role="initiator",
        )
        assert "wangwu@example.com" in result
        assert "iPhone 15 Pro" in result
        # 两个结果都在 → 确认 _summarize 本身不做 turn 级过滤

    @pytest.mark.asyncio
    async def test_none_task_filtered_out(self):
        """NONE_TASK_UNASSIGNED_RESULT 不会被输出."""
        ex = _make(summarize_enabled=False, agent_id="test-agent")
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "initiator")
        )

        result = await ex._summarize(
            original_query="查订单",
            task_results={
                1: TURN2_RESULT,
                2: NONE_TASK_UNASSIGNED_RESULT,
            },
            delegate_results={},
            agent_role="initiator",
        )
        assert "iPhone 15 Pro" in result
        assert "未派发" not in result

    @pytest.mark.asyncio
    async def test_dependent_skip_filtered_out(self):
        """DEPENDENT_TASK_SKIP_DESCRIPTION 也不会被输出."""
        ex = _make(summarize_enabled=False, agent_id="test-agent")
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "initiator")
        )

        result = await ex._summarize(
            original_query="查订单",
            task_results={
                1: TURN2_RESULT,
                2: DEPENDENT_TASK_SKIP_DESCRIPTION,
            },
            delegate_results={},
            agent_role="initiator",
        )
        assert "iPhone 15 Pro" in result
        assert "上游依赖" not in result

    @pytest.mark.asyncio
    async def test_duplicate_tasks_appear_twice(self):
        """同 turn 内两个 task 返回相同结果 → passthrough 会重复输出.

        这是当前行为（可能不是你想要的，但应先确认）。passthrough 不对结果内容去重。
        """
        ex = _make(summarize_enabled=False, agent_id="test-agent")
        ex._summary_prompt_agent_meta = MagicMock(
            return_value=("test-agent", "initiator")
        )

        result = await ex._summarize(
            original_query="查订单",
            task_results={
                1: TURN2_RESULT,
                2: TURN2_RESULT,  # 两个 task 返回相同
            },
            delegate_results={},
            agent_role="initiator",
        )
        count = result.count("iPhone 15 Pro")
        assert count == 2, (
            f"Expected 'iPhone 15 Pro' 2 times, got {count}.\n"
            f"Result:\n{result}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])