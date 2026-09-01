#!/usr/bin/env python3

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
VENDOR_DIR = SKILL_DIR / "vendor" / "tdb_pipeline"
sys.path.insert(0, str(HERE))


class WwybsjVendoredLlmTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.modules.pop("llm_config_common", None)

    def tearDown(self) -> None:
        sys.modules.pop("llm_config_common", None)

    def assert_uses_vendored_llm_config(self, module_name: str) -> None:
        module = importlib.import_module(module_name)
        load_llm_config, _, _ = module.import_llm()

        self.assertTrue(
            Path(load_llm_config.__code__.co_filename).is_relative_to(VENDOR_DIR),
            f"{module_name} should load llm_config_common from {VENDOR_DIR}",
        )
        self.assertEqual(module.DAC_JSON, VENDOR_DIR / "dac.json")

    def test_l2_uses_skill_vendored_llm_config(self):
        self.assert_uses_vendored_llm_config("wwybsj_l2")

    def test_l3_uses_skill_vendored_llm_config(self):
        self.assert_uses_vendored_llm_config("wwybsj_l3")


if __name__ == "__main__":
    unittest.main()
