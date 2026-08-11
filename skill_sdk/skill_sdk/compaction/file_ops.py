"""Track file read/modify operations across compaction boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage


@dataclass
class FileOperations:
    """Accumulated file paths observed in tool calls."""

    read: set[str] = field(default_factory=set)
    written: set[str] = field(default_factory=set)
    edited: set[str] = field(default_factory=set)


def create_file_ops() -> FileOperations:
    """Create an empty ``FileOperations`` container.

    Returns:
        New empty file-ops set.
    """
    return FileOperations()


def _path_from_args(args: Mapping[str, Any], *keys: str) -> str | None:
    """Pick the first non-empty string path from ``args`` using ``keys``.

    Args:
        args: Tool call arguments.
        *keys: Candidate argument names in priority order.

    Returns:
        Path string or ``None``.
    """
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_file_ops_from_tool_call(name: str, args: Mapping[str, Any], file_ops: FileOperations) -> None:
    """Update ``file_ops`` from a single skill_sdk tool call.

    Mapping:
      - ``readline_in_range`` / ``grep`` / ``glob`` / ``lsp`` → read
      - write-like tools (if present) → written / edited

    Args:
        name: Tool name.
        args: Tool arguments.
        file_ops: Mutable accumulator.
    """
    tool = (name or "").strip()
    if tool == "readline_in_range":
        path = _path_from_args(args, "file_path", "path")
        if path:
            file_ops.read.add(path)
        return
    if tool in ("grep", "glob"):
        path = _path_from_args(args, "path", "file_path", "glob")
        if path:
            file_ops.read.add(path)
        return
    if tool == "lsp":
        path = _path_from_args(args, "file_path", "path", "uri")
        if path:
            file_ops.read.add(path)
        return
    if tool in ("write", "write_file"):
        path = _path_from_args(args, "path", "file_path")
        if path:
            file_ops.written.add(path)
        return
    if tool in ("edit", "edit_file", "apply_patch"):
        path = _path_from_args(args, "path", "file_path")
        if path:
            file_ops.edited.add(path)


def extract_file_ops_from_message(message: BaseMessage, file_ops: FileOperations) -> None:
    """Extract file operations from tool calls on an assistant message.

    Args:
        message: Chat message (only ``AIMessage`` contributes).
        file_ops: Mutable accumulator.
    """
    if not isinstance(message, AIMessage):
        return
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        if not isinstance(call, Mapping):
            continue
        name = str(call.get("name") or "")
        args = call.get("args")
        if args is None:
            args = call.get("arguments") or {}
        if isinstance(args, str):
            import json

            try:
                args = json.loads(args)
            except (TypeError, ValueError, json.JSONDecodeError):
                args = {}
        if not isinstance(args, Mapping):
            continue
        extract_file_ops_from_tool_call(name, args, file_ops)


def extract_file_ops_from_messages(
    messages: Sequence[BaseMessage],
    previous_details: Mapping[str, Any] | None = None,
) -> FileOperations:
    """Build cumulative file ops from prior compaction details plus new messages.

    Args:
        messages: Messages being summarized (and optional turn prefix).
        previous_details: Prior compaction ``details`` with read/modified lists.

    Returns:
        Merged ``FileOperations``.
    """
    file_ops = create_file_ops()
    if previous_details:
        for path in previous_details.get("readFiles") or previous_details.get("read_files") or []:
            if isinstance(path, str) and path:
                file_ops.read.add(path)
        for path in previous_details.get("modifiedFiles") or previous_details.get("modified_files") or []:
            if isinstance(path, str) and path:
                file_ops.edited.add(path)
    for msg in messages:
        extract_file_ops_from_message(msg, file_ops)
    return file_ops


def compute_file_lists(file_ops: FileOperations) -> tuple[list[str], list[str]]:
    """Split ops into read-only files vs modified files (sorted).

    Args:
        file_ops: Accumulated operations.

    Returns:
        ``(read_files, modified_files)`` where read_files excludes modified paths.
    """
    modified = set(file_ops.edited) | set(file_ops.written)
    read_only = sorted(p for p in file_ops.read if p not in modified)
    modified_files = sorted(modified)
    return read_only, modified_files


def format_file_operations(read_files: list[str], modified_files: list[str]) -> str:
    """Format file lists as XML-ish tags appended to a summary.

    Args:
        read_files: Paths only read.
        modified_files: Paths written or edited.

    Returns:
        Suffix string (may be empty), including leading newlines when non-empty.
    """
    sections: list[str] = []
    if read_files:
        sections.append("<read-files>\n" + "\n".join(read_files) + "\n</read-files>")
    if modified_files:
        sections.append("<modified-files>\n" + "\n".join(modified_files) + "\n</modified-files>")
    if not sections:
        return ""
    return "\n\n" + "\n\n".join(sections)


def details_from_file_ops(file_ops: FileOperations) -> dict[str, list[str]]:
    """Convert file ops into JSON-serializable compaction details.

    Args:
        file_ops: Accumulated operations.

    Returns:
        Dict with ``readFiles`` and ``modifiedFiles`` lists.
    """
    read_files, modified_files = compute_file_lists(file_ops)
    return {"readFiles": read_files, "modifiedFiles": modified_files}
