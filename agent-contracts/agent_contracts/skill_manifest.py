"""Shared parsing for package-authored skill output schemas."""

from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Callable, Dict, List, Mapping, Union

from .schemas import SchemaDescriptor

SchemaFile = Union[bytes, str, Mapping[str, Any]]
SchemaReader = Callable[[str], SchemaFile]


class SkillSchemaDeclarationError(ValueError):
    """Raised when a skill package declares an invalid output schema."""


def normalize_schema_path(value: Any) -> str:
    """Return a safe POSIX-relative package path or raise."""

    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or PureWindowsPath(raw).is_absolute()
        or path in {PurePosixPath("."), PurePosixPath("..")}
        or ".." in path.parts
    ):
        raise SkillSchemaDeclarationError(
            f"unsafe or empty output schema path: {raw!r}"
        )
    return path.as_posix()


def load_output_schema_descriptors(
    metadata: Mapping[str, Any],
    *,
    read_schema: SchemaReader,
    owner: str,
) -> List[SchemaDescriptor]:
    """Resolve schema declarations with a caller-provided package file reader."""

    declarations = metadata.get("output_schemas") or []
    if not isinstance(declarations, list):
        raise SkillSchemaDeclarationError("output_schemas must be a list")

    descriptors: List[SchemaDescriptor] = []
    seen: set[str] = set()
    for index, declaration in enumerate(declarations):
        if not isinstance(declaration, dict):
            raise SkillSchemaDeclarationError(
                f"output_schemas[{index}] must be an object"
            )
        if "schema" in declaration:
            raise SkillSchemaDeclarationError(
                f"output_schemas[{index}] must reference a package file, not inline schema"
            )
        path = normalize_schema_path(declaration.get("path"))
        try:
            raw_schema = read_schema(path)
        except (KeyError, FileNotFoundError, IsADirectoryError) as exc:
            raise SkillSchemaDeclarationError(
                f"output schema file not found in skill package: {path}"
            ) from exc

        try:
            if isinstance(raw_schema, Mapping):
                schema_body: Dict[str, Any] = dict(raw_schema)
            else:
                text = (
                    raw_schema.decode("utf-8")
                    if isinstance(raw_schema, bytes)
                    else str(raw_schema)
                )
                loaded = json.loads(text)
                if not isinstance(loaded, dict):
                    raise TypeError("schema root must be an object")
                schema_body = loaded
            descriptor = SchemaDescriptor(
                schema_id=str(declaration.get("schema_id") or ""),
                schema=schema_body,
                schema_digest=declaration.get("schema_digest"),
                owner=owner,
                description=str(declaration.get("description") or ""),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            schema_id = str(declaration.get("schema_id") or index)
            raise SkillSchemaDeclarationError(
                f"invalid output schema {schema_id}: {exc}"
            ) from exc

        if descriptor.schema_id in seen:
            raise SkillSchemaDeclarationError(
                f"duplicate output schema declaration: {descriptor.schema_id}"
            )
        seen.add(descriptor.schema_id)
        descriptors.append(descriptor)
    return descriptors
