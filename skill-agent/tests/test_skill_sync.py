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

            def fake_download(refs, **_kwargs):
                paths = []
                for ref in refs:
                    path = Path(tmp, f"{ref.name}.zip")
                    path.write_bytes(b"new")
                    paths.append(path)
                return paths

            with patch.object(
                watcher,
                "_poll_hub",
                return_value={
                    ("default", "configured"): ("2.0.0", frozenset({"2.0.0"})),
                    ("default", "brand-new"): ("1.0.0", frozenset({"1.0.0"})),
                },
            ), patch("agent.skill_sync.download_skills", side_effect=fake_download):
                watcher._sync_once()

            self.assertEqual(changed, [["brand-new", "configured"]])
            self.assertEqual(watcher._known["configured"], "2.0.0")
            self.assertEqual(watcher._known["brand-new"], "1.0.0")

    def test_undownloadable_skill_backs_off_instead_of_retrying_every_poll(self) -> None:
        """Phase 0.5: `tavily-search` with no API key must not be re-pulled forever.

        The downloader drops it silently, so the watcher sees a target it asked
        for and never received.
        """
        with tempfile.TemporaryDirectory() as tmp:
            watcher = SkillHubWatcher(
                on_change=lambda _changed: None,
                base_url="http://hub",
                skills_dir=tmp,
                subscribed=["tavily-search"],
                watch_all=False,
                interval=30,
            )
            watcher._failure_backoff = 300.0
            watcher._failure_backoff_max = 3600.0

            clock = {"now": 1000.0}
            hub = {("default", "tavily-search"): ("1.0.0", frozenset({"1.0.0"}))}

            with patch.object(watcher, "_poll_hub", return_value=hub), patch.object(
                type(watcher), "_now", staticmethod(lambda: clock["now"])
            ), patch(
                "agent.skill_sync.download_skills", return_value=[]
            ) as download:
                watcher._sync_once()
                self.assertEqual(download.call_count, 1)

                # Nine further polls inside the backoff window: no new requests.
                for _ in range(9):
                    clock["now"] += 30.0
                    watcher._sync_once()
                self.assertEqual(download.call_count, 1)

                # After the window elapses it retries exactly once, then doubles.
                clock["now"] += 300.0
                watcher._sync_once()
                self.assertEqual(download.call_count, 2)

                clock["now"] += 300.0
                watcher._sync_once()
                self.assertEqual(download.call_count, 2)

    def test_backoff_clears_when_the_hub_publishes_a_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            watcher = SkillHubWatcher(
                on_change=lambda _changed: None,
                base_url="http://hub",
                skills_dir=tmp,
                subscribed=["flaky"],
                watch_all=False,
                interval=30,
            )
            clock = {"now": 0.0}

            with patch.object(
                type(watcher), "_now", staticmethod(lambda: clock["now"])
            ), patch("agent.skill_sync.download_skills", return_value=[]) as download:
                with patch.object(
                    watcher,
                    "_poll_hub",
                    return_value={("default", "flaky"): ("1.0.0", frozenset({"1.0.0"}))},
                ):
                    watcher._sync_once()
                    clock["now"] += 30.0
                    watcher._sync_once()
                    self.assertEqual(download.call_count, 1)

                # A newer version is a different target: retry without waiting.
                with patch.object(
                    watcher,
                    "_poll_hub",
                    return_value={("default", "flaky"): ("2.0.0", frozenset({"2.0.0"}))},
                ):
                    watcher._sync_once()
                    self.assertEqual(download.call_count, 2)

    def test_successful_download_clears_backoff_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            watcher = SkillHubWatcher(
                on_change=lambda _changed: None,
                base_url="http://hub",
                skills_dir=tmp,
                subscribed=["recovers"],
                watch_all=False,
                interval=30,
            )
            clock = {"now": 0.0}
            hub = {("default", "recovers"): ("1.0.0", frozenset({"1.0.0"}))}

            def fake_download(refs, **_kwargs):
                paths = []
                for ref in refs:
                    path = Path(tmp, f"{ref.name}.zip")
                    path.write_bytes(b"new")
                    paths.append(path)
                return paths

            with patch.object(watcher, "_poll_hub", return_value=hub), patch.object(
                type(watcher), "_now", staticmethod(lambda: clock["now"])
            ):
                with patch("agent.skill_sync.download_skills", return_value=[]):
                    watcher._sync_once()
                self.assertTrue(watcher._unavailable)

                clock["now"] += 300.0
                with patch("agent.skill_sync.download_skills", side_effect=fake_download):
                    watcher._sync_once()
                self.assertFalse(watcher._unavailable)
                self.assertEqual(watcher._known["recovers"], "1.0.0")

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
