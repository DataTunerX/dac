from orchestrator_agent.skill_download import SkillRef, _parse_skills_env


def test_parse_structured_local_skill_attachments():
    refs = _parse_skills_env(
        '[{"namespace":"team-a","name":"report","version":"1.2.0"}]'
    )

    assert refs == [SkillRef(name="report", namespace="team-a", version="1.2.0")]
    assert refs[0].download_path() == (
        "/namespaces/team-a/skills/report.zip?version=1.2.0"
    )


def test_parse_legacy_names_stays_compatible():
    refs = _parse_skills_env('["weather", "web_fetch"]')

    assert refs == [SkillRef(name="weather"), SkillRef(name="web_fetch")]
    assert refs[0].download_path() == "/skills/weather.zip"


def test_download_path_encodes_version_query_value():
    assert SkillRef(name="report", namespace="team-a", version="v1+build").download_path() == (
        "/namespaces/team-a/skills/report.zip?version=v1%2Bbuild"
    )
