import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.skill_sync import SkillHubWatcher  # noqa: E402


class SkillHubWatcherTest(unittest.TestCase):
    def test_new_and_updated_skills_are_downloaded_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            changed = []
            watcher = SkillHubWatcher(
                on_change=changed.append,
                base_url="http://hub",
                skills_dir=tmp,
                subscribed=["configured"],
                watch_all=True,
                interval=1,
                initial_versions={"configured": "1.0.0"},
            )
            Path(tmp, "configured.zip").write_bytes(b"old")

            def fake_download(names, **_kwargs):
                paths = []
                for name in names:
                    path = Path(tmp, f"{name}.zip")
                    path.write_bytes(b"new")
                    paths.append(path)
                return paths

            with patch.object(
                watcher,
                "_poll_hub",
                return_value={"configured": "2.0.0", "brand-new": "1.0.0"},
            ), patch("agent.skill_sync.download_skills", side_effect=fake_download):
                watcher._sync_once()

            self.assertEqual(changed, [["brand-new", "configured"]])
            self.assertEqual(watcher._known["configured"], "2.0.0")
            self.assertEqual(watcher._known["brand-new"], "1.0.0")

    def test_stop_does_not_shadow_thread_internal_stop_method(self) -> None:
        watcher = SkillHubWatcher(
            on_change=lambda _changed: None,
            base_url="http://hub",
            subscribed=[],
            interval=60,
        )
        with patch.object(watcher, "_poll_hub", return_value={}):
            watcher.start()
            watcher.stop()
        self.assertFalse(watcher.is_alive())


if __name__ == "__main__":
    unittest.main()
