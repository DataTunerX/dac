"""API-level tests for the multi-namespace skill-hub HTTP service."""

from __future__ import annotations

from tests.conftest import make_zip


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_default_skills_only(client):
    r = client.get("/skills")
    assert r.status_code == 200
    data = r.json()
    names = {s["name"] for s in data["skills"]}
    assert names == {"base64tool", "github", "hashgen"}
    assert data["count"] == 3
    assert all(s["namespace"] == "default" for s in data["skills"])


def test_hashgen_versions_newest_first(client):
    hg = next(
        s for s in client.get("/skills").json()["skills"] if s["name"] == "hashgen"
    )
    assert hg["version"] == "2.0.0"
    assert hg["available_versions"] == ["2.0.0", "1.10.0", "1.0.0"]
    # default namespace download_url keeps the legacy root path
    assert hg["download_url"] == "/hashgen.zip"


def test_list_namespaces(client):
    r = client.get("/namespaces")
    assert r.status_code == 200
    data = r.json()
    assert [n["id"] for n in data["namespaces"]] == ["default", "james", "team-a"]
    assert all(n["visibility"] == "public" for n in data["namespaces"])


def test_namespace_exists_true(client):
    r = client.get("/namespaces/default/exists")
    assert r.status_code == 200
    assert r.json() == {"namespace": "default", "exists": True}
    r = client.get("/namespaces/team-a/exists")
    assert r.status_code == 200
    assert r.json() == {"namespace": "team-a", "exists": True}


def test_namespace_exists_false(client):
    r = client.get("/namespaces/missing-ns/exists")
    assert r.status_code == 200
    assert r.json() == {"namespace": "missing-ns", "exists": False}


def test_namespace_exists_invalid_rejected(client):
    assert client.get("/namespaces/BadNS/exists").status_code == 400


def test_create_namespace(client, skills_dir):
    r = client.post("/namespaces/new-team")
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "new-team"
    assert body["visibility"] == "public"
    # Dir created on disk and the namespace now appears in the list.
    assert (skills_dir / "new-team").is_dir()
    assert "new-team" in [n["id"] for n in client.get("/namespaces").json()["namespaces"]]


def test_create_namespace_conflict_returns_409(client, skills_dir):
    # Existing namespace (pre-seeded in the fixture) -> 409 conflict.
    r = client.post("/namespaces/team-a")
    assert r.status_code == 409
    assert "already exists" in r.json()["error"]
    # Creating a namespace then re-creating it also yields 409.
    assert client.post("/namespaces/brand-new").status_code == 201
    assert client.post("/namespaces/brand-new").status_code == 409


def test_create_namespace_invalid_rejected(client):
    # Uppercase namespaces fail validation.
    assert client.post("/namespaces/BadNS").status_code == 400


def test_create_default_namespace_rejected(client):
    # default is the built-in namespace backed by SKILLS_DIR itself.
    r = client.post("/namespaces/default")
    assert r.status_code == 400
    assert "reserved" in r.json()["error"]


def test_delete_empty_namespace(client, skills_dir):
    # Create an empty namespace, then delete it.
    assert client.post("/namespaces/empty-ns").status_code == 201
    assert (skills_dir / "empty-ns").is_dir()
    r = client.delete("/namespaces/empty-ns")
    assert r.status_code == 204
    assert not (skills_dir / "empty-ns").exists()
    # Gone from the namespace list too.
    assert "empty-ns" not in [
        n["id"] for n in client.get("/namespaces").json()["namespaces"]
    ]


def test_delete_nonempty_namespace_returns_409(client):
    # team-a has skills -> cannot be deleted.
    r = client.delete("/namespaces/team-a")
    assert r.status_code == 409
    assert "not empty" in r.json()["error"]


def test_delete_default_namespace_rejected(client):
    # default is reserved and cannot be deleted.
    r = client.delete("/namespaces/default")
    assert r.status_code == 400
    assert "reserved" in r.json()["error"]


def test_delete_missing_namespace_returns_404(client):
    assert client.delete("/namespaces/does-not-exist").status_code == 404


def test_list_namespace_skills(client):
    r = client.get("/namespaces/team-a/skills")
    assert r.status_code == 200
    data = r.json()
    assert {s["name"] for s in data["skills"]} == {"report", "notify"}
    rep = next(s for s in data["skills"] if s["name"] == "report")
    assert rep["version"] == "1.1.0"
    assert rep["namespace"] == "team-a"
    # non-default download_url is namespace-scoped
    assert rep["download_url"] == "/namespaces/team-a/skills/report.zip"


def _assert_download_filename(resp, expected: str) -> None:
    cd = resp.headers.get("content-disposition", "")
    assert expected in cd, f"expected {expected!r} in Content-Disposition={cd!r}"


def test_download_default_root_path(client):
    r = client.get("/github.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-skill-version"] == "1.0.0"
    _assert_download_filename(r, "github-1.0.0.zip")


def test_download_default_under_skills_path(client):
    # Agents (skill_download.py) use GET /skills/{name}.zip; it must behave
    # identically to the legacy root-path alias for the default namespace.
    r = client.get("/skills/github.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-skill-version"] == "1.0.0"
    _assert_download_filename(r, "github-1.0.0.zip")
    r2 = client.get("/skills/hashgen.zip?version=1.10.0")
    assert r2.status_code == 200
    assert r2.headers["x-skill-version"] == "1.10.0"
    _assert_download_filename(r2, "hashgen-1.10.0.zip")
    assert client.get("/skills/nonexistent.zip").status_code == 404


def test_download_default_specific_version(client):
    r = client.get("/hashgen.zip?version=1.10.0")
    assert r.status_code == 200
    assert r.headers["x-skill-version"] == "1.10.0"
    _assert_download_filename(r, "hashgen-1.10.0.zip")


def test_download_namespace_skill(client):
    r = client.get("/namespaces/team-a/skills/report.zip")
    assert r.status_code == 200
    assert r.headers["x-skill-version"] == "1.1.0"
    _assert_download_filename(r, "report-1.1.0.zip")
    r = client.get("/namespaces/team-a/skills/report.zip?version=1.0.0")
    assert r.status_code == 200
    assert r.headers["x-skill-version"] == "1.0.0"
    _assert_download_filename(r, "report-1.0.0.zip")


def test_get_skill_detail(client):
    r = client.get("/namespaces/team-a/skills/report/detail")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "report"
    assert body["namespace"] == "team-a"
    assert body["version"] == "1.1.0"
    assert "detail" in body
    assert "allowed_tools" in body
    assert isinstance(body["allowed_tools"], list)
    assert "Test skill for report" in body["detail"]
    # specific version
    r2 = client.get("/namespaces/team-a/skills/report/detail?version=1.0.0")
    assert r2.status_code == 200
    assert r2.json()["version"] == "1.0.0"


def test_get_skill_detail_missing_404(client):
    assert client.get("/namespaces/team-a/skills/nope/detail").status_code == 404


def test_download_missing_returns_404(client):
    assert client.get("/nonexistent.zip").status_code == 404
    assert client.get("/namespaces/team-a/skills/nonexistent.zip").status_code == 404


def test_invalid_namespace_rejected(client):
    # uppercase namespace fails validation
    assert client.get("/namespaces/Team-A/skills").status_code == 400
    # multi-segment path simply doesn't match a route
    assert client.get("/namespaces/../../etc/skills").status_code in (400, 404)


def test_upload_new_skill(client, skills_dir):
    make_zip(
        __import__("pathlib").Path(skills_dir) / "new-1.0.0.zip", "newskill", "1.0.0"
    )
    with open(skills_dir / "new-1.0.0.zip", "rb") as f:
        r = client.post(
            "/namespaces/team-a/skills",
            files={"file": ("new-1.0.0.zip", f, "application/zip")},
        )
    assert r.status_code == 201
    up = r.json()
    assert up["name"] == "newskill"
    assert up["version"] == "1.0.0"
    assert up["namespace"] == "team-a"
    # immediately listed + downloadable after upload
    assert "newskill" in {
        s["name"] for s in client.get("/namespaces/team-a/skills").json()["skills"]
    }
    assert client.get("/namespaces/team-a/skills/newskill.zip").status_code == 200


def test_upload_to_default_lands_in_default_dir(client, skills_dir):
    # Uploading to the built-in default namespace writes the zip into the
    # skills_dir/default/ directory (the default namespace's own folder), and
    # the skill is visible via GET /skills and the legacy root download path.
    make_zip(skills_dir / "defskill-1.0.0.zip", "defskill", "1.0.0")
    with open(skills_dir / "defskill-1.0.0.zip", "rb") as f:
        r = client.post(
            "/namespaces/default/skills",
            files={"file": ("defskill-1.0.0.zip", f, "application/zip")},
        )
    assert r.status_code == 201
    up = r.json()
    assert up["namespace"] == "default"
    # The zip is written under skills_dir/default/ (the default namespace dir).
    assert (skills_dir / "default" / "defskill-1.0.0.zip").is_file()
    # Visible in GET /skills (default namespace) and downloadable at the root.
    assert "defskill" in {
        s["name"] for s in client.get("/skills").json()["skills"]
    }
    assert client.get("/defskill.zip").status_code == 200


def test_upload_overwrite_same_name_version(client, skills_dir):
    # upload twice with the same name+version -> overwritten, not duplicated
    for _ in range(2):
        make_zip(skills_dir / "dup-1.0.0.zip", "dup", "1.0.0")
        with open(skills_dir / "dup-1.0.0.zip", "rb") as f:
            r = client.post(
                "/namespaces/team-a/skills",
                files={"file": ("dup-1.0.0.zip", f, "application/zip")},
            )
        assert r.status_code == 201
    files = list((skills_dir / "team-a").glob("dup-*.zip"))
    assert len(files) == 1


def test_upload_autocreates_namespace(client, skills_dir):
    # Uploading to a not-yet-existing namespace lazily creates it and succeeds.
    make_zip(skills_dir / "x-1.0.0.zip", "x", "1.0.0")
    with open(skills_dir / "x-1.0.0.zip", "rb") as f:
        r = client.post(
            "/namespaces/nosuchns/skills",
            files={"file": ("x-1.0.0.zip", f, "application/zip")},
        )
    assert r.status_code == 201
    assert r.json()["namespace"] == "nosuchns"
    # The namespace dir now exists on disk and the skill is downloadable.
    assert (skills_dir / "nosuchns").is_dir()
    assert client.get("/namespaces/nosuchns/skills").status_code == 200
    assert client.get("/namespaces/nosuchns/skills/x.zip").status_code == 200


def test_upload_invalid_zip_400(client):
    bad = __import__("tempfile").NamedTemporaryFile(suffix=".zip", delete=False)
    bad.write(b"this is not a zip file")
    bad.close()
    with open(bad.name, "rb") as f:
        r = client.post(
            "/namespaces/team-a/skills",
            files={"file": ("bad.zip", f, "application/zip")},
        )
    assert r.status_code == 400


def test_create_skill_from_json(client, skills_dir):
    r = client.post(
        "/namespaces/team-a/skills/create",
        json={
            "name": "form-skill",
            "description": "Created from form",
            "detail": "## Goal\n\nHelp the user.\n",
            "version": "1.0.0",
            "allowed_tools": ["glob", "grep"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "form-skill"
    assert body["version"] == "1.0.0"
    assert body["namespace"] == "team-a"
    assert body["description"] == "Created from form"
    assert (skills_dir / "team-a" / "form-skill-1.0.0.zip").is_file()
    assert client.get("/namespaces/team-a/skills/form-skill.zip").status_code == 200


def test_create_skill_rejects_empty_description(client):
    r = client.post(
        "/namespaces/team-a/skills/create",
        json={"name": "x", "description": "  ", "version": "1.0.0"},
    )
    assert r.status_code == 400


def test_create_skill_rejects_invalid_name(client):
    r = client.post(
        "/namespaces/team-a/skills/create",
        json={"name": "bad name", "description": "x", "version": "1.0.0"},
    )
    assert r.status_code == 400


def test_update_skill_preserves_scripts(client, skills_dir):
    # Create base pack, then inject a script into the stored zip.
    assert (
        client.post(
            "/namespaces/team-a/skills/create",
            json={
                "name": "editable",
                "description": "v1",
                "detail": "old\n",
                "version": "1.0.0",
                "allowed_tools": ["glob"],
            },
        ).status_code
        == 201
    )
    zip_path = skills_dir / "team-a" / "editable-1.0.0.zip"
    import io
    import zipfile

    raw = zip_path.read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zin, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("scripts/run.py", "print(1)\n")
    zip_path.write_bytes(buf.getvalue())
    client.post("/skills/reload")

    r = client.post(
        "/namespaces/team-a/skills/editable/update?version=1.0.0",
        json={
            "name": "editable",
            "description": "v2",
            "detail": "new\n",
            "version": "1.0.0",
            "allowed_tools": ["grep"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "v2"
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.read("scripts/run.py") == b"print(1)\n"
        meta = __import__("json").loads(zf.read("_meta.json"))
        assert meta["allowed_tools"] == ["grep"]
    detail = client.get("/namespaces/team-a/skills/editable/detail").json()
    assert detail["description"] == "v2"
    assert "new" in detail["detail"]


def test_delete_specific_version_falls_back(client):
    assert (
        client.get("/namespaces/team-a/skills/report.zip?version=1.0.0").status_code
        == 200
    )
    r = client.delete("/namespaces/team-a/skills/report.zip?version=1.0.0")
    assert r.status_code == 204
    assert (
        client.get("/namespaces/team-a/skills/report.zip?version=1.0.0").status_code
        == 404
    )
    # latest still serves 1.1.0
    r = client.get("/namespaces/team-a/skills/report.zip")
    assert r.status_code == 200
    assert r.headers["x-skill-version"] == "1.1.0"


def test_delete_last_version_removes_skill(client):
    r = client.delete("/namespaces/james/skills/personal.zip")
    assert r.status_code == 204
    assert client.get("/namespaces/james/skills/personal.zip").status_code == 404
    assert client.get("/namespaces/james/skills").json()["count"] == 0


def test_delete_missing_404(client):
    assert client.delete("/namespaces/team-a/skills/nonexistent.zip").status_code == 404


def test_reload_legacy_endpoint(client):
    r = client.post("/skills/reload")
    assert r.status_code == 200
    assert r.json()["count"] == 3


def test_error_body_format(client):
    r = client.get("/namespaces/team-a/skills/nonexistent.zip")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "skill 'team-a/nonexistent' not found"
    assert body["status_code"] == 404
