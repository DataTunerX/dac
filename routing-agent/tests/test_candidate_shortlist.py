"""Phase 0.6: deterministic candidate shortlisting and its recall gate.

The fixtures mirror the 13 agents registered on `test-cluster` on 2026-09-12 and
the two queries whose routing runs are cited in the design document, so the
recall assertions here are the same measurement the shadow rollout makes.

Run::

    cd /path/to/dac/routing-agent
    python -m pytest tests/test_candidate_shortlist.py -v
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routing_agent.candidate_shortlist import (  # noqa: E402
    build_shortlist,
    find_explicit_target,
    static_matches,
    tokenize,
)


@dataclass
class _Skill:
    id: str
    name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class _Card:
    name: str
    description: str = ""
    skills: List[_Skill] = field(default_factory=list)


def _agent(name: str, skill_id: str, description: str) -> _Card:
    return _Card(
        name=name,
        description=description,
        skills=[_Skill(id=skill_id, name=skill_id, description=description)],
    )


# The live `test-cluster` registry.
REGISTRY = [
    _agent("Wwybsj-TDB-Agent", "tdb-wwybsj-answering",
           "巍巍博物馆 wwybsj 馆藏文物研究、器物条目、馆藏事实、材料与溯源分析、"
           "museum collection research, artifact typology, chronology, provenance"),
    _agent("Art-history-TDB-Agent", "tdb-art-history-qa",
           "艺术史 art history 绘画 雕塑 风格 图像学 敦煌 莫高窟 壁画 供养人 "
           "art historical questions grounded in the TDB art_history domain"),
    _agent("History-TDB-Agent", "tdb-history-qa",
           "历史 history 朝代 唐代 人物 事件 制度 evidence-backed historical answers"),
    _agent("Anthropology-sociology-TDB-Agent", "tdb-anthropology-sociology-qa",
           "人类学 社会学 anthropology sociology 社会身份 宗教实践 亲属"),
    _agent("Architecture-TDB-Agent", "tdb-architecture-qa",
           "Birchfield 建筑平面图 房间 开口 设施 OCR 几何关系 building floor plans"),
    _agent("Geo-environment-TDB-Agent", "tdb-geo-environment-qa",
           "地理 环境 geo environment 地貌 气候 矿产 地质"),
    _agent("Literature-humanities-TDB-Agent", "tdb-literature-humanities-qa",
           "文学 人文 literature humanities 文本 诗歌 文献"),
    _agent("Paper-Answering-TDB-Agent", "tdb-paper-answering",
           "学术论文 academic papers citations ontology statements provenance 考古 archeology"),
    _agent("Philosophy-theory-TDB-Agent", "tdb-philosophy-theory-qa",
           "哲学 理论 philosophy theory 概念 思想"),
    _agent("Wwybsj-Build-TDB-Agent", "tdb-wwybsj-build",
           "wwybsj 文物 TDB 写入 构建 重建 术语对齐 ingestion build"),
    _agent("Circuit-Diagram-QA-Agent", "circuit-diagram-qa",
           "汽车电路图 元件 端子 线束 automotive circuit diagrams"),
    _agent("Competitive-Analysis-Agent", "competitive-analysis",
           "企业存储 厂商 产品 竞争分析 enterprise storage vendor comparison"),
    _agent("SkillAgent", "code_execution",
           "本地技能执行器 code_execution extract_pdf weather web_fetch"),
]

MOGAO_QUERY = (
    "为什么莫高窟第 130 窟晋昌郡都督一家供养人像，"
    "不能只看作普通的功德肖像，而应看作唐代佛教绘画中国化的证据？"
)
CIRCUIT_QUERY = "BMW 328i 电路图里 K6 继电器的端子接到哪些线束？"


class TokenizeTest(unittest.TestCase):
    def test_ascii_words_and_cjk_bigrams(self) -> None:
        tokens = tokenize("art history 莫高窟")
        self.assertIn("art", tokens)
        self.assertIn("history", tokens)
        self.assertIn("莫高", tokens)
        self.assertIn("高窟", tokens)

    def test_single_characters_are_dropped_for_ascii(self) -> None:
        self.assertNotIn("a", tokenize("a big cat"))


class ShortlistRankingTest(unittest.TestCase):
    def test_irrelevant_agents_rank_below_relevant_ones(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=5)
        names = [c.name for c in shortlist.ranked]

        art_rank = names.index("Art-history-TDB-Agent")
        for unrelated in ("Circuit-Diagram-QA-Agent", "Competitive-Analysis-Agent"):
            self.assertLess(
                art_rank, names.index(unrelated),
                f"{unrelated} outranked the art-history agent",
            )

    def test_domain_agent_is_included_for_its_own_query(self) -> None:
        shortlist = build_shortlist(CIRCUIT_QUERY, REGISTRY, k=5)
        self.assertTrue(shortlist.contains("Circuit-Diagram-QA-Agent"))

    def test_ordering_is_deterministic_regardless_of_registry_order(self) -> None:
        forward = build_shortlist(MOGAO_QUERY, REGISTRY, k=5)
        reversed_ = build_shortlist(MOGAO_QUERY, list(reversed(REGISTRY)), k=5)
        self.assertEqual(
            [c.name for c in forward.ranked], [c.name for c in reversed_.ranked]
        )

    def test_k_bounds_the_included_set(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=5)
        self.assertEqual(len(shortlist.included), 5)
        self.assertEqual(len(shortlist.ranked), len(REGISTRY))


class RecallSafeguardTest(unittest.TestCase):
    def test_explicit_target_is_pinned_at_rank_one(self) -> None:
        shortlist = build_shortlist(
            "随便问点什么",
            REGISTRY,
            explicit_target="Architecture-TDB-Agent",
            k=3,
        )
        self.assertEqual(shortlist.ranked[0].name, "Architecture-TDB-Agent")
        self.assertTrue(shortlist.contains("Architecture-TDB-Agent"))
        self.assertEqual(shortlist.ranked[0].reason, "explicit_target")

    def test_explicit_target_survives_k_of_one(self) -> None:
        shortlist = build_shortlist(
            MOGAO_QUERY, REGISTRY, explicit_target="Competitive-Analysis-Agent", k=1
        )
        self.assertTrue(shortlist.contains("Competitive-Analysis-Agent"))
        self.assertEqual(len(shortlist.included), 1)

    def test_literal_agent_mention_is_a_static_match(self) -> None:
        query = "Must use Architecture-TDB-Agent to answer this question."
        self.assertIn("Architecture-TDB-Agent", static_matches(query, REGISTRY))

    def test_literal_skill_mention_is_a_static_match(self) -> None:
        query = "用 tdb-wwybsj-answering 查一下这件器物"
        self.assertIn("Wwybsj-TDB-Agent", static_matches(query, REGISTRY))

    def test_static_match_outranks_scored_candidates(self) -> None:
        query = f"{MOGAO_QUERY} 另外请 Competitive-Analysis-Agent 也看一下"
        shortlist = build_shortlist(
            query, REGISTRY, k=3, always_include=static_matches(query, REGISTRY)
        )
        self.assertTrue(shortlist.contains("Competitive-Analysis-Agent"))
        self.assertEqual(shortlist.ranked[0].name, "Competitive-Analysis-Agent")

    def test_unrelated_query_does_not_produce_static_matches(self) -> None:
        self.assertEqual(static_matches(MOGAO_QUERY, REGISTRY), [])


class HardCapTest(unittest.TestCase):
    """`k` is a ceiling on capability model calls, not a soft preference."""

    def test_static_matches_cannot_exceed_k(self) -> None:
        query = (
            "tdb-wwybsj-answering tdb-art-history-qa tdb-history-qa "
            "tdb-paper-answering tdb-philosophy-theory-qa circuit-diagram-qa"
        )
        matches = static_matches(query, REGISTRY)
        self.assertEqual(len(matches), 6)

        shortlist = build_shortlist(query, REGISTRY, k=3, always_include=matches)
        self.assertEqual(len(shortlist.included), 3)

    def test_explicit_plus_static_cannot_exceed_k(self) -> None:
        query = "tdb-wwybsj-answering tdb-art-history-qa tdb-history-qa"
        shortlist = build_shortlist(
            query,
            REGISTRY,
            k=2,
            explicit_target="Competitive-Analysis-Agent",
            always_include=static_matches(query, REGISTRY),
        )
        self.assertEqual(len(shortlist.included), 2)
        self.assertTrue(shortlist.contains("Competitive-Analysis-Agent"))

    def test_dropped_static_matches_are_reported(self) -> None:
        query = "tdb-wwybsj-answering tdb-art-history-qa tdb-history-qa"
        shortlist = build_shortlist(
            query, REGISTRY, k=1, always_include=static_matches(query, REGISTRY)
        )
        self.assertEqual(len(shortlist.included), 1)
        self.assertEqual(len(shortlist.dropped_static_matches), 2)
        self.assertEqual(
            shortlist.to_shadow_record()["dropped_static_matches"],
            shortlist.dropped_static_matches,
        )

    def test_included_never_exceeds_k_for_any_k(self) -> None:
        for k in range(1, len(REGISTRY) + 3):
            shortlist = build_shortlist(
                MOGAO_QUERY,
                REGISTRY,
                k=k,
                explicit_target="Architecture-TDB-Agent",
                always_include=["Circuit-Diagram-QA-Agent", "SkillAgent"],
            )
            self.assertLessEqual(len(shortlist.included), min(k, len(REGISTRY)))


class ExplicitTargetDetectionTest(unittest.TestCase):
    """A directive selects an agent; a bare mention does not."""

    def test_must_use_wins_over_a_bare_mention(self) -> None:
        query = "Must use Wwybsj-TDB-Agent; compare with Art-history-TDB-Agent."
        self.assertEqual(find_explicit_target(query, REGISTRY), "Wwybsj-TDB-Agent")

    def test_directive_target_survives_k_of_one_end_to_end(self) -> None:
        """The reviewer's repro: alphabetical tie-break must not win."""
        query = "Must use Wwybsj-TDB-Agent; compare with Art-history-TDB-Agent."
        shortlist = build_shortlist(
            query,
            REGISTRY,
            k=1,
            explicit_target=find_explicit_target(query, REGISTRY),
            always_include=static_matches(query, REGISTRY),
        )
        self.assertEqual(shortlist.included_names, ["Wwybsj-TDB-Agent"])

    def test_chinese_directive(self) -> None:
        query = "请使用 Art-history-TDB-Agent 回答这个问题"
        self.assertEqual(find_explicit_target(query, REGISTRY), "Art-history-TDB-Agent")

    def test_strong_directive_beats_weak_one(self) -> None:
        query = "please use Art-history-TDB-Agent, but you must use Wwybsj-TDB-Agent"
        self.assertEqual(find_explicit_target(query, REGISTRY), "Wwybsj-TDB-Agent")

    def test_bare_mention_is_not_a_directive(self) -> None:
        query = "How does Art-history-TDB-Agent differ from History-TDB-Agent?"
        self.assertIsNone(find_explicit_target(query, REGISTRY))

    def test_no_mention_returns_none(self) -> None:
        self.assertIsNone(find_explicit_target(MOGAO_QUERY, REGISTRY))

    def test_chinese_negated_directive_selects_the_permitted_agent(self) -> None:
        """`使用` lives inside `不要使用`; the forbidden agent must not win."""
        query = "不要使用 Art-history-TDB-Agent，请使用 Wwybsj-TDB-Agent。"
        self.assertEqual(find_explicit_target(query, REGISTRY), "Wwybsj-TDB-Agent")

    def test_chinese_negation_end_to_end_at_k_of_one(self) -> None:
        query = "不要使用 Art-history-TDB-Agent，请使用 Wwybsj-TDB-Agent。"
        shortlist = build_shortlist(
            query,
            REGISTRY,
            k=1,
            explicit_target=find_explicit_target(query, REGISTRY),
            always_include=static_matches(query, REGISTRY),
        )
        self.assertEqual(shortlist.included_names, ["Wwybsj-TDB-Agent"])

    def test_english_negated_directive_selects_the_permitted_agent(self) -> None:
        query = "Do not use Art-history-TDB-Agent, please use Wwybsj-TDB-Agent."
        self.assertEqual(find_explicit_target(query, REGISTRY), "Wwybsj-TDB-Agent")

    def test_negation_alone_selects_nothing(self) -> None:
        for query in (
            "不要使用 Art-history-TDB-Agent",
            "Do not use Art-history-TDB-Agent",
            "Never use Art-history-TDB-Agent",
            "禁止使用 Art-history-TDB-Agent",
        ):
            with self.subTest(query=query):
                self.assertIsNone(find_explicit_target(query, REGISTRY))

    def test_negation_between_directive_and_name(self) -> None:
        query = "请使用 History-TDB-Agent 而不是 Art-history-TDB-Agent"
        self.assertEqual(find_explicit_target(query, REGISTRY), "History-TDB-Agent")

    def test_english_exclusion_phrase(self) -> None:
        query = "Please use History-TDB-Agent rather than Art-history-TDB-Agent"
        self.assertEqual(find_explicit_target(query, REGISTRY), "History-TDB-Agent")

    def test_bare_english_use_is_not_a_directive(self) -> None:
        """Narrow by design: "can I use X?" must not pin X."""
        self.assertIsNone(
            find_explicit_target("Can I use Art-history-TDB-Agent?", REGISTRY)
        )

    def test_name_embedded_in_a_longer_name_is_not_a_match(self) -> None:
        """`History-TDB-Agent` is a substring of `Art-history-TDB-Agent`."""
        query = "必须使用 Art-history-TDB-Agent"
        self.assertEqual(find_explicit_target(query, REGISTRY), "Art-history-TDB-Agent")
        self.assertEqual(static_matches(query, REGISTRY), ["Art-history-TDB-Agent"])

    def test_strong_directive_still_wins_over_its_own_substring(self) -> None:
        """`必须使用` contains `使用`; the strong reading must survive."""
        query = "必须使用 Wwybsj-TDB-Agent，请使用 Art-history-TDB-Agent 补充"
        self.assertEqual(find_explicit_target(query, REGISTRY), "Wwybsj-TDB-Agent")

    def test_distant_directive_does_not_bind(self) -> None:
        query = "must use something else entirely " + "x" * 80 + " Art-history-TDB-Agent"
        self.assertIsNone(find_explicit_target(query, REGISTRY))


class GenericTokenTest(unittest.TestCase):
    def test_generic_words_do_not_create_name_matches(self) -> None:
        shortlist = build_shortlist("use a tdb agent please", REGISTRY, k=5)
        name_scores = {c.name: c.signals["name"] for c in shortlist.ranked}
        self.assertTrue(
            all(score == 0.0 for score in name_scores.values()),
            f"generic tokens still score: {name_scores}",
        )
        self.assertEqual(shortlist.positive_score_count, 0)

    def test_real_domain_word_still_matches(self) -> None:
        shortlist = build_shortlist("art history question", REGISTRY, k=5)
        art = next(c for c in shortlist.ranked if c.name == "Art-history-TDB-Agent")
        self.assertGreater(art.signals["name"], 0.0)


class ShadowRecordTest(unittest.TestCase):
    def test_record_reports_rank_and_exclusion_reason(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=3)
        record = shortlist.to_shadow_record(run_id="run-1", enforced=False)

        self.assertEqual(record["record_type"], "candidate_shortlist")
        self.assertEqual(record["k"], 3)
        self.assertEqual(record["candidate_count"], len(REGISTRY))
        self.assertEqual(len(record["included"]), 3)
        self.assertEqual(record["run_id"], "run-1")
        for entry in record["included"] + record["excluded"]:
            self.assertIn("rank", entry)
            self.assertIn("reason", entry)
            self.assertIn("signals", entry)

    def test_exclusion_reason_names_the_rank_and_k(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=1)
        excluded = shortlist.excluded[0]
        reason = shortlist.exclusion_reason(excluded.name)
        self.assertIn(f"rank_{excluded.rank}", reason)
        self.assertIn("beyond_k_1", reason)

    def test_arbitrary_cutoff_is_reported(self) -> None:
        """With 13 agents and one real match, slots 2..5 are name-ordered noise."""
        shortlist = build_shortlist(CIRCUIT_QUERY, REGISTRY, k=5)
        self.assertEqual(shortlist.positive_score_count, 1)
        self.assertTrue(shortlist.cutoff_is_arbitrary)
        self.assertTrue(shortlist.to_shadow_record()["cutoff_is_arbitrary"])

    def test_cutoff_not_arbitrary_when_evidence_separates_the_boundary(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=1)
        self.assertGreater(shortlist.ranked[0].score, shortlist.ranked[1].score)
        self.assertFalse(shortlist.cutoff_is_arbitrary)

    def test_unknown_agent_reports_not_in_registry(self) -> None:
        shortlist = build_shortlist(MOGAO_QUERY, REGISTRY, k=3)
        self.assertEqual(shortlist.exclusion_reason("Ghost-Agent"), "not_in_registry")
        self.assertIsNone(shortlist.rank_of("Ghost-Agent"))


if __name__ == "__main__":
    unittest.main()
