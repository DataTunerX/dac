#!/usr/bin/env python3

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class WwybsjCommonPathTests(unittest.TestCase):
    def import_common(self):
        sys.modules.pop("wwybsj_common", None)
        return importlib.import_module("wwybsj_common")

    def test_base_registry_defaults_to_skill_data_file(self):
        old_data = os.environ.get("WWYBSJ_DATA_JSON")
        old_overlay = os.environ.get("WWYBSJ_NEW_ITEMS")
        try:
            os.environ.pop("WWYBSJ_DATA_JSON", None)
            with tempfile.TemporaryDirectory() as td:
                os.environ["WWYBSJ_NEW_ITEMS"] = str(Path(td) / "overlay.json")
                common = self.import_common()

                self.assertEqual(common.DATA_JSON, HERE.parent / "data" / "wwybsj.json")
                self.assertEqual(len(common.load_records()), 465)
        finally:
            if old_data is None:
                os.environ.pop("WWYBSJ_DATA_JSON", None)
            else:
                os.environ["WWYBSJ_DATA_JSON"] = old_data
            if old_overlay is None:
                os.environ.pop("WWYBSJ_NEW_ITEMS", None)
            else:
                os.environ["WWYBSJ_NEW_ITEMS"] = old_overlay
            sys.modules.pop("wwybsj_common", None)

    def test_base_registry_path_can_be_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as td:
            data_path = Path(td) / "registry.json"
            data_path.write_text('[{"id": 999, "ww_bianhao": "T999"}]', encoding="utf-8")
            overlay_path = Path(td) / "overlay.json"

            old_data = os.environ.get("WWYBSJ_DATA_JSON")
            old_overlay = os.environ.get("WWYBSJ_NEW_ITEMS")
            try:
                os.environ["WWYBSJ_DATA_JSON"] = str(data_path)
                os.environ["WWYBSJ_NEW_ITEMS"] = str(overlay_path)
                common = self.import_common()

                self.assertEqual(common.DATA_JSON, data_path)
                self.assertEqual(common.load_records(), [{"id": 999, "ww_bianhao": "T999"}])
            finally:
                if old_data is None:
                    os.environ.pop("WWYBSJ_DATA_JSON", None)
                else:
                    os.environ["WWYBSJ_DATA_JSON"] = old_data
                if old_overlay is None:
                    os.environ.pop("WWYBSJ_NEW_ITEMS", None)
                else:
                    os.environ["WWYBSJ_NEW_ITEMS"] = old_overlay
                sys.modules.pop("wwybsj_common", None)


if __name__ == "__main__":
    unittest.main()
