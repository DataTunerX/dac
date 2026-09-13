"""Deterministic, dependency-free JSON Schema 2020-12 profile.

The protocol only needs data-contract validation, not schema transformation or
remote reference resolution.  Keeping this profile in the shared package makes
validation identical in every DAC component and avoids component-specific
dependency graphs.  Unsupported schema keywords fail registration instead of
being silently ignored.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


class JsonSchemaDefinitionError(ValueError):
    """Raised when a schema is outside the supported deterministic profile."""


@dataclass(frozen=True)
class JsonSchemaValueError(ValueError):
    message: str
    path: tuple[Any, ...] = ()

    def __str__(self) -> str:
        return self.message


_ANNOTATION_KEYWORDS = {
    "$schema",
    "$id",
    "$anchor",
    "title",
    "description",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
}
_VALIDATION_KEYWORDS = {
    "$ref",
    "$defs",
    "type",
    "enum",
    "const",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "required",
    "properties",
    "patternProperties",
    "additionalProperties",
    "dependentRequired",
    "propertyNames",
    "minProperties",
    "maxProperties",
    "items",
    "prefixItems",
    "contains",
    "minContains",
    "maxContains",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
}
_SUPPORTED_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}


def _schema_children(schema: Mapping[str, Any]) -> Iterable[Any]:
    for key in ("$defs", "properties", "patternProperties"):
        value = schema.get(key)
        if isinstance(value, Mapping):
            yield from value.values()
    for key in (
        "additionalProperties",
        "propertyNames",
        "items",
        "contains",
        "not",
        "if",
        "then",
        "else",
    ):
        if key in schema:
            yield schema[key]
    for key in ("prefixItems", "allOf", "anyOf", "oneOf"):
        value = schema.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            yield from value


def _resolve_pointer(root: Any, reference: str) -> Any:
    if not reference.startswith("#/"):
        raise JsonSchemaDefinitionError(
            f"only local JSON Pointer references are supported: {reference!r}"
        )
    current = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise JsonSchemaDefinitionError(
                f"unresolved local schema reference: {reference!r}"
            )
        current = current[part]
    return current


def check_schema(schema: Any) -> None:
    """Validate a schema and reject constraints this runtime cannot enforce."""

    root = schema

    def visit(node: Any, location: str) -> None:
        if isinstance(node, bool):
            return
        if not isinstance(node, Mapping):
            raise JsonSchemaDefinitionError(
                f"schema at {location} must be an object or boolean"
            )
        unknown = {
            key
            for key in node
            if key not in _ANNOTATION_KEYWORDS
            and key not in _VALIDATION_KEYWORDS
            and not key.startswith("x-")
        }
        if unknown:
            raise JsonSchemaDefinitionError(
                f"unsupported JSON Schema keyword(s) at {location}: {sorted(unknown)}"
            )
        raw_type = node.get("type")
        types = (
            raw_type
            if isinstance(raw_type, list)
            else [raw_type]
            if raw_type is not None
            else []
        )
        if any(
            not isinstance(value, str) or value not in _SUPPORTED_TYPES
            for value in types
        ):
            raise JsonSchemaDefinitionError(
                f"invalid type declaration at {location}: {raw_type!r}"
            )
        if len(types) != len(set(types)):
            raise JsonSchemaDefinitionError(
                f"duplicate type declaration at {location}: {raw_type!r}"
            )
        if "$ref" in node:
            target = _resolve_pointer(root, str(node["$ref"]))
            if target is node:
                raise JsonSchemaDefinitionError(
                    f"self-referencing schema at {location}"
                )
        if "required" in node and (
            not isinstance(node["required"], list)
            or any(not isinstance(item, str) for item in node["required"])
        ):
            raise JsonSchemaDefinitionError(
                f"required at {location} must be a string list"
            )
        if "enum" in node and not isinstance(node["enum"], list):
            raise JsonSchemaDefinitionError(f"enum at {location} must be a list")
        for key in ("properties", "patternProperties", "$defs", "dependentRequired"):
            if key in node and not isinstance(node[key], Mapping):
                raise JsonSchemaDefinitionError(
                    f"{key} at {location} must be an object"
                )
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            if key in node and not isinstance(node[key], list):
                raise JsonSchemaDefinitionError(f"{key} at {location} must be a list")
        for key in ("pattern",):
            if key in node:
                try:
                    re.compile(str(node[key]))
                except re.error as exc:
                    raise JsonSchemaDefinitionError(
                        f"invalid regex at {location}: {exc}"
                    ) from exc
        if "multipleOf" in node and (
            not isinstance(node["multipleOf"], (int, float))
            or isinstance(node["multipleOf"], bool)
            or node["multipleOf"] <= 0
        ):
            raise JsonSchemaDefinitionError(
                f"multipleOf at {location} must be positive"
            )
        for index, child in enumerate(_schema_children(node)):
            visit(child, f"{location}/{index}")

    visit(schema, "$")


def _is_type(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "number":
        return (
            isinstance(instance, (int, float))
            and not isinstance(instance, bool)
            and math.isfinite(instance)
        )
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    return False


def validate(instance: Any, schema: Any) -> None:
    """Validate one value and raise the first deterministic validation error."""

    root = schema

    def fail(message: str, path: tuple[Any, ...]) -> None:
        raise JsonSchemaValueError(message=message, path=path)

    def apply(value: Any, node: Any, path: tuple[Any, ...]) -> None:
        if node is True:
            return
        if node is False:
            fail("value is rejected by the schema", path)
        if "$ref" in node:
            apply(value, _resolve_pointer(root, str(node["$ref"])), path)

        raw_type = node.get("type")
        if raw_type is not None:
            expected = raw_type if isinstance(raw_type, list) else [raw_type]
            if not any(_is_type(value, item) for item in expected):
                fail(f"expected type {raw_type!r}, got {type(value).__name__}", path)
        if "const" in node and value != node["const"]:
            fail(f"expected constant value {node['const']!r}", path)
        if "enum" in node and value not in node["enum"]:
            fail(f"value is not one of {node['enum']!r}", path)

        for child in node.get("allOf", []):
            apply(value, child, path)
        if "anyOf" in node:
            if not any(_matches(value, child, path) for child in node["anyOf"]):
                fail("value does not satisfy anyOf", path)
        if "oneOf" in node:
            if sum(_matches(value, child, path) for child in node["oneOf"]) != 1:
                fail("value must satisfy exactly one oneOf branch", path)
        if "not" in node and _matches(value, node["not"], path):
            fail("value satisfies a forbidden schema", path)
        if "if" in node:
            branch = (
                node.get("then")
                if _matches(value, node["if"], path)
                else node.get("else")
            )
            if branch is not None:
                apply(value, branch, path)

        if isinstance(value, dict):
            required = node.get("required", [])
            missing = [name for name in required if name not in value]
            if missing:
                fail(f"missing required properties: {missing}", path)
            if "minProperties" in node and len(value) < int(node["minProperties"]):
                fail(f"object has fewer than {node['minProperties']} properties", path)
            if "maxProperties" in node and len(value) > int(node["maxProperties"]):
                fail(f"object has more than {node['maxProperties']} properties", path)
            properties = node.get("properties", {})
            patterns = node.get("patternProperties", {})
            for key, item in value.items():
                matched = False
                if key in properties:
                    apply(item, properties[key], path + (key,))
                    matched = True
                for pattern, child in patterns.items():
                    if re.search(pattern, key):
                        apply(item, child, path + (key,))
                        matched = True
                if not matched and "additionalProperties" in node:
                    additional = node["additionalProperties"]
                    if additional is False:
                        fail(f"unexpected property {key!r}", path + (key,))
                    if additional is not True:
                        apply(item, additional, path + (key,))
            for key, dependencies in node.get("dependentRequired", {}).items():
                if key in value:
                    missing_deps = [dep for dep in dependencies if dep not in value]
                    if missing_deps:
                        fail(f"property {key!r} requires {missing_deps}", path)
            if "propertyNames" in node:
                for key in value:
                    apply(key, node["propertyNames"], path + (key,))

        if isinstance(value, list):
            if "minItems" in node and len(value) < int(node["minItems"]):
                fail(f"array has fewer than {node['minItems']} items", path)
            if "maxItems" in node and len(value) > int(node["maxItems"]):
                fail(f"array has more than {node['maxItems']} items", path)
            if node.get("uniqueItems"):
                for index, item in enumerate(value):
                    if item in value[:index]:
                        fail("array items must be unique", path + (index,))
            prefix = node.get("prefixItems", [])
            for index, child in enumerate(prefix[: len(value)]):
                apply(value[index], child, path + (index,))
            if "items" in node:
                start = len(prefix)
                for index in range(start, len(value)):
                    apply(value[index], node["items"], path + (index,))
            if "contains" in node:
                count = sum(
                    _matches(item, node["contains"], path + (index,))
                    for index, item in enumerate(value)
                )
                minimum = int(node.get("minContains", 1))
                maximum = node.get("maxContains")
                if count < minimum or (maximum is not None and count > int(maximum)):
                    fail("array does not satisfy contains bounds", path)

        if isinstance(value, str):
            if "minLength" in node and len(value) < int(node["minLength"]):
                fail(f"string is shorter than {node['minLength']}", path)
            if "maxLength" in node and len(value) > int(node["maxLength"]):
                fail(f"string is longer than {node['maxLength']}", path)
            if "pattern" in node and re.search(str(node["pattern"]), value) is None:
                fail(f"string does not match {node['pattern']!r}", path)

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            for key, predicate, wording in (
                ("minimum", lambda a, b: a >= b, "at least"),
                ("maximum", lambda a, b: a <= b, "at most"),
                ("exclusiveMinimum", lambda a, b: a > b, "greater than"),
                ("exclusiveMaximum", lambda a, b: a < b, "less than"),
            ):
                if key in node and not predicate(value, node[key]):
                    fail(f"number must be {wording} {node[key]}", path)
            if "multipleOf" in node:
                factor = node["multipleOf"]
                quotient = value / factor
                if not math.isclose(
                    quotient, round(quotient), rel_tol=1e-9, abs_tol=1e-9
                ):
                    fail(f"number must be a multiple of {factor}", path)

    def _matches(value: Any, node: Any, path: tuple[Any, ...]) -> bool:
        try:
            apply(value, node, path)
            return True
        except JsonSchemaValueError:
            return False

    apply(instance, schema, ())
