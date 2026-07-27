import io
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "skill-hub"))
# Import only the lightweight SDK modules used by skill-hub. The SDK package's
# top-level __init__ also imports the execution runner and its LangChain stack,
# which a registry metadata test neither needs nor should have to initialise.
skill_sdk_package = types.ModuleType("skill_sdk")
skill_sdk_package.__path__ = [str(repo_root / "skill_sdk" / "skill_sdk")]
sys.modules.setdefault("skill_sdk", skill_sdk_package)

from skill_hub.server import (  # noqa: E402
    SkillConflictError,
    SkillIndex,
    SkillValidationError,
    app,
)


def make_skill(path: Path, name: str, version: str, description: str = "test") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "_meta.json",
            json.dumps({"slug": name, "version": version}),
        )
        archive.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: {description}\n---\n\nInstructions.\n",
        )


def skill_bytes(name: str, version: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(
            "_meta.json", json.dumps({"slug": name, "version": version})
        )
        archive.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: test\n---\n\nInstructions.\n",
        )
    return out.getvalue()


class SkillIndexRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = SkillIndex(self.root)
        self.index.reload()

    def tearDown(self) -> None:
        self.index.close()
        self.tmp.cleanup()

    def test_publish_lists_and_resolves_multiple_versions(self) -> None:
        one = self.root / ".one.zip"
        make_skill(one, "demo", "1.0.0")
        result = self.index.ingest(one)
        self.assertTrue(result["created"])

        two = self.root / ".two.zip"
        make_skill(two, "demo", "2.0.0")
        self.index.ingest(two)

        listed = self.index.list_skills()
        self.assertEqual(listed[0]["version"], "2.0.0")
        self.assertEqual(listed[0]["available_versions"], ["2.0.0", "1.0.0"])
        self.assertEqual(self.index.resolve_zip("demo", "1.0.0").name, "demo-1.0.0.zip")

    def test_duplicate_requires_overwrite(self) -> None:
        first = self.root / ".first.zip"
        make_skill(first, "demo", "1.0.0", "first")
        self.index.ingest(first)

        duplicate = self.root / ".duplicate.zip"
        make_skill(duplicate, "demo", "1.0.0", "second")
        with self.assertRaises(SkillConflictError):
            self.index.ingest(duplicate)

        replacement = self.root / ".replacement.zip"
        make_skill(replacement, "demo", "1.0.0", "second")
        result = self.index.ingest(replacement, overwrite=True)
        self.assertFalse(result["created"])
        self.assertEqual(self.index.list_skills()[0]["description"], "second")

    def test_named_publish_rejects_package_with_different_name(self) -> None:
        upload = self.root / ".upload.zip"
        make_skill(upload, "actual", "1.0.0")
        with self.assertRaises(SkillValidationError):
            self.index.ingest(upload, expected_name="expected")
        self.assertEqual(self.index.list_skills(), [])

    def test_rejects_unaddressable_metadata(self) -> None:
        upload = self.root / ".upload.zip"
        make_skill(upload, "bad/name", "1.0.0")
        with self.assertRaises(SkillValidationError):
            self.index.ingest(upload)


class SkillHubApiTest(unittest.TestCase):
    def test_authenticated_push_list_pull_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"SKILLS_DIR": tmp, "SKILL_HUB_PUSH_TOKEN": "secret"},
            clear=False,
        ):
            body = skill_bytes("api-demo", "1.0.0")
            with TestClient(app) as client:
                unauthorized = client.post("/skills", content=body)
                self.assertEqual(unauthorized.status_code, 401)

                headers = {"Authorization": "Bearer secret"}
                published = client.post("/skills", content=body, headers=headers)
                self.assertEqual(published.status_code, 200)
                self.assertTrue(published.json()["created"])

                listed = client.get("/skills").json()
                self.assertEqual(listed["skills"][0]["name"], "api-demo")

                pulled = client.get("/api-demo.zip")
                self.assertEqual(pulled.status_code, 200)
                self.assertEqual(pulled.headers["x-skill-version"], "1.0.0")
                self.assertEqual(pulled.content, body)

                conflict = client.post("/skills", content=body, headers=headers)
                self.assertEqual(conflict.status_code, 409)


if __name__ == "__main__":
    unittest.main()
