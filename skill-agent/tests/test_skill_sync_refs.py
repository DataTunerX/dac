from agent.skill_download_refs import SkillRef
from agent.skill_sync import SkillHubWatcher


def test_watcher_accepts_structured_skill_refs(tmp_path):
    watcher = SkillHubWatcher(
        on_change=lambda _names: None,
        skills_dir=str(tmp_path),
        subscribed=[SkillRef(name="report", namespace="team-a", version="1.0.0")],
        watch_all=False,
    )

    assert watcher.subscribed == {
        "report": SkillRef(name="report", namespace="team-a", version="1.0.0")
    }


def test_select_targets_preserves_namespace_and_version_pin(tmp_path):
    watcher = SkillHubWatcher(
        on_change=lambda _names: None,
        skills_dir=str(tmp_path),
        subscribed=[SkillRef(name="report", namespace="team-a", version="1.0.0")],
        watch_all=False,
    )
    hub = {
        ("team-a", "report"): ("2.0.0", frozenset({"1.0.0", "2.0.0"})),
        ("default", "weather"): ("3.0.0", frozenset({"3.0.0"})),
    }

    assert watcher._select_targets(hub) == [
        (SkillRef(name="report", namespace="team-a", version="1.0.0"), "1.0.0")
    ]


def test_select_targets_does_not_import_unsubscribed_namespace_skills(tmp_path):
    watcher = SkillHubWatcher(
        on_change=lambda _names: None,
        skills_dir=str(tmp_path),
        subscribed=[SkillRef(name="report", namespace="team-a")],
        watch_all=False,
    )
    hub = {
        ("team-a", "report"): ("2.0.0", frozenset({"2.0.0"})),
        ("team-a", "other"): ("1.0.0", frozenset({"1.0.0"})),
    }

    assert watcher._select_targets(hub) == [
        (SkillRef(name="report", namespace="team-a"), "2.0.0")
    ]
