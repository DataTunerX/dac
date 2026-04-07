"""Tests for ExpertAgent.format_llm_ouput (semantic domain parsing)."""

import unittest
from types import SimpleNamespace

from agent.expert_agent_semantic_domain import ExpertAgent


def _agent_without_init() -> ExpertAgent:
    return ExpertAgent.__new__(ExpertAgent)


class TestFormatLLMOutputDomain(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = _agent_without_init()

    def test_json_raw_double_quotes(self) -> None:
        msg = SimpleNamespace(content='{"reason":"ok","conclusion":"terminate"}')
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d, {"reason": "ok", "conclusion": "terminate"})

    def test_requery_json_double_quotes(self) -> None:
        msg = SimpleNamespace(
            content='{"requery":"改写后的问法","conclusion":"terminate"}'
        )
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["conclusion"], "terminate")
        self.assertEqual(d["requery"], "改写后的问法")

    def test_llm_result_json_double_quotes(self) -> None:
        msg = SimpleNamespace(
            content=(
                '{"answer":"SELECT 1","conclusion":"terminate","requery":""}'
            )
        )
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["answer"], "SELECT 1")
        self.assertEqual(d["conclusion"], "terminate")
        self.assertEqual(d["requery"], "")

    def test_llm_result_python_single_quotes(self) -> None:
        s = (
            "{'answer': '简单说明', 'conclusion': 'continue', "
            "'requery': '请补充条件'}"
        )
        msg = SimpleNamespace(content=s)
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["answer"], "简单说明")
        self.assertEqual(d["conclusion"], "continue")
        self.assertEqual(d["requery"], "请补充条件")

    def test_observe_json_double_quotes_multiline_reason(self) -> None:
        msg = SimpleNamespace(
            content='{"reason":"line1\\nline2","conclusion":"continue"}'
        )
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["reason"], "line1\nline2")
        self.assertEqual(d["conclusion"], "continue")

    def test_markdown_fence_without_json_tag(self) -> None:
        msg = SimpleNamespace(
            content='```\n{"reason":"in fence","conclusion":"terminate"}\n```'
        )
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["reason"], "in fence")
        self.assertEqual(d["conclusion"], "terminate")

    def test_raw_content_whitespace_around_json(self) -> None:
        msg = SimpleNamespace(content='  \n{"reason":"trim","conclusion":"terminate"}  ')
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["reason"], "trim")

    def test_observe_python_dict_unicode_smart_quotes_in_reason(self) -> None:
        # Must parse before smart-quote normalization corrupts single-quoted literals.
        inner = "符合上下文中的\u201c年度总额\u201d的规则"
        s = f"{{'reason': '{inner}', 'conclusion': 'terminate'}}"
        msg = SimpleNamespace(content=s)
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["conclusion"], "terminate")
        self.assertIn("年度总额", d["reason"])

    def test_observe_python_dict_internal_ascii_double_quotes(self) -> None:
        s = (
            "{'reason': '查询\"广州农商银行总行\"，SQL OK。', "
            "'conclusion': 'terminate'}"
        )
        msg = SimpleNamespace(content=s)
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["conclusion"], "terminate")
        self.assertIn("广州农商银行总行", d["reason"])

    def test_requery_python_dict_single_quotes(self) -> None:
        s = "{'requery': '广州农商银行2024年12月31日的公司贷款余额', 'conclusion': 'terminate'}"
        msg = SimpleNamespace(content=s)
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["conclusion"], "terminate")
        self.assertIn("公司贷款余额", d["requery"])

    def test_markdown_fence_json(self) -> None:
        msg = SimpleNamespace(
            content='```json\n{"reason":"x","conclusion":"continue"}\n```'
        )
        d = self.agent.format_llm_ouput(msg)
        self.assertEqual(d["reason"], "x")
        self.assertEqual(d["conclusion"], "continue")

    def test_reason_with_unicode_apostrophe_u2019(self) -> None:
        # U+2019 in value is fine for early literal_eval; normalization would turn it into ASCII '.
        s = "{'reason': 'it\u2019s fine', 'conclusion': 'terminate'}"
        msg = SimpleNamespace(content=s)
        d = self.agent.format_llm_ouput(msg)
        self.assertIsNotNone(d)
        self.assertEqual(d.get("conclusion"), "terminate")
        self.assertIn("fine", d.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
