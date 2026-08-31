#!/usr/bin/env python3
from __future__ import annotations

import unittest

import wwybsj_l3


class L3GateTest(unittest.TestCase):
    def test_allows_excavation_phrase_when_source_material_names_same_tomb(self) -> None:
        mat = {
            "facts": [
                {"事实": "obtained_by = 1957年陕西省西安市鲜于庭诲墓出土", "id": "s1"},
                {"事实": "dated_to = {\"registry_literal\":\"约开元十一年(723)\"}", "id": "s2"},
            ],
            "background": [],
            "gaps": set(),
        }
        out = {
            "text": "唐三彩釉陶载乐骆驼约作于开元十一年，1957年出土于陕西省西安市鲜于庭诲墓，属陶质雕塑、造像类文物，现状基本完整但局部构件残缺。"
        }

        ok, problems, _ = wwybsj_l3.gate(mat, out)

        self.assertTrue(ok, problems)

    def test_rejects_excavation_phrase_absent_from_source_material(self) -> None:
        mat = {
            "facts": [
                {"事实": "obtained_by = 征集购买", "id": "s1"},
                {"事实": "dated_to = {\"registry_literal\":\"唐(618~907)\"}", "id": "s2"},
            ],
            "background": [],
            "gaps": set(),
        }
        out = {
            "text": "这件陶俑为唐代雕塑、造像类文物，登记为基本完整，器形与唐代陶俑传统相关，1957年出土于洛阳某墓。"
        }

        ok, problems, _ = wwybsj_l3.gate(mat, out)

        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("P7") for p in problems), problems)

    def test_rejects_historical_date_attached_to_modern_excavation_place(self) -> None:
        mat = {
            "facts": [
                {"事实": "obtained_by = 1957年陕西省西安市鲜于庭诲墓出土", "id": "s1"},
                {"事实": "dated_to = {\"registry_literal\":\"约开元十一年(723)\"}", "id": "s2"},
            ],
            "background": [],
            "gaps": set(),
        }
        out = {
            "text": "唐三彩釉陶载乐骆驼由陶制成，约开元十一年出土于陕西省西安市鲜于庭诲墓，为墓葬中的随葬品，现状基本完整。"
        }

        ok, problems, _ = wwybsj_l3.gate(mat, out)

        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("P8") for p in problems), problems)

    def test_allows_artifact_subject_attached_to_supported_excavation_place(self) -> None:
        mat = {
            "facts": [
                {"事实": "obtained_by = 1957年陕西省西安市鲜于庭诲墓出土", "id": "s1"},
                {"事实": "dated_to = {\"registry_literal\":\"约开元十一年(723)\"}", "id": "s2"},
            ],
            "background": [],
            "gaps": set(),
        }
        out = {
            "text": "该文物出土于陕西省西安市鲜于庭诲墓，属陶质雕塑、造像类文物，登记年代为约开元十一年，现状基本完整但局部构件残缺。"
        }

        ok, problems, _ = wwybsj_l3.gate(mat, out)

        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
