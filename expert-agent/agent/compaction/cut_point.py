"""Cut-point detection for context compaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent.compaction.messages import is_internal_message
from agent.compaction.tokens import estimate_tokens


@dataclass(frozen=True)
class CutPointResult:
    """Result of finding where to keep recent messages.

    Attributes:
        first_kept_index: Index into ``dialog`` of the first message to keep.
        turn_start_index: If splitting a turn, index of that turn's start; else -1.
        is_split_turn: True when the cut lands mid-turn (not on a turn-start message).
    """

    first_kept_index: int
    turn_start_index: int
    is_split_turn: bool


def is_cut_point_message(message: BaseMessage) -> bool:
    """Return whether compaction may cut immediately before this message.

    Valid cut points: human, assistant, and compaction-summary humans.
    Tool results must stay attached to their preceding tool-call assistant.

    Internal HumanMessages (nudge, analysis) are still valid cut points —
    they are just not treated as turn-start boundaries.

    Args:
        message: Dialog message.

    Returns:
        True if this index is a valid cut point.
    """
    if isinstance(message, ToolMessage):
        return False
    if isinstance(message, (HumanMessage, AIMessage)):
        return True
    return False


def is_turn_start_message(message: BaseMessage) -> bool:
    """Return whether this message starts a user turn.

    A turn starts at a human (including compaction summary) message.
    Internal messages (nudge, analysis) are NOT turn starts — they belong
    to the current turn.

    Assistant / tool messages continue the current turn.

    Args:
        message: Dialog message.

    Returns:
        True if the message starts a turn.
    """
    if isinstance(message, HumanMessage):
        if is_internal_message(message):
            return False
        return True
    if isinstance(message, (AIMessage, ToolMessage)):
        return False
    return False


def find_turn_start_index(
    dialog: Sequence[BaseMessage],
    entry_index: int,
    start_index: int,
) -> int:
    """Walk backwards to the human message that started the turn containing ``entry_index``.

    Args:
        dialog: Dialog messages (no leading system).
        entry_index: Index inside the turn being inspected.
        start_index: Earliest index allowed while searching.

    Returns:
        Turn-start index, or -1 if none found.
    """
    for i in range(entry_index, start_index - 1, -1):
        if is_turn_start_message(dialog[i]):
            return i
    return -1


def find_valid_cut_points(
    dialog: Sequence[BaseMessage],
    start_index: int,
    end_index: int,
) -> list[int]:
    """Collect valid cut-point indices in ``[start_index, end_index)``.

    Args:
        dialog: Dialog messages.
        start_index: Inclusive start of searchable range.
        end_index: Exclusive end of searchable range.

    Returns:
        Ordered list of valid cut indices.
    """
    points: list[int] = []
    for i in range(start_index, end_index):
        if is_cut_point_message(dialog[i]):
            points.append(i)
    return points


def find_cut_point(
    dialog: Sequence[BaseMessage],
    start_index: int,
    end_index: int,
    keep_recent_tokens: int,
) -> CutPointResult:
    """Find a cut that keeps approximately ``keep_recent_tokens`` of recent dialog.

    Walks newest→oldest accumulating ``estimate_tokens`` until the budget is
    reached, then snaps to the nearest valid cut point at or after that entry.

    Args:
        dialog: Dialog messages (system already stripped).
        start_index: Inclusive start of the span eligible for summarization.
        end_index: Exclusive end (typically ``len(dialog)``).
        keep_recent_tokens: Recent-token budget to keep verbatim.

    Returns:
        ``CutPointResult`` describing the keep boundary and split-turn state.
    """
    cut_points = find_valid_cut_points(dialog, start_index, end_index)
    if not cut_points:
        return CutPointResult(first_kept_index=start_index, turn_start_index=-1, is_split_turn=False)

    accumulated = 0
    cut_index = cut_points[0]

    for i in range(end_index - 1, start_index - 1, -1):
        message_tokens = estimate_tokens(dialog[i])
        if message_tokens == 0:
            continue
        accumulated += message_tokens
        if accumulated >= keep_recent_tokens:
            # Prefer the closest valid cut at or after this entry. If none exists
            # (e.g. landed on a trailing ToolMessage), fall back to the last valid
            # cut at or before this entry so tool results stay with their assistant.
            found: int | None = None
            for point in cut_points:
                if point >= i:
                    found = point
                    break
            if found is not None:
                cut_index = found
            else:
                for point in reversed(cut_points):
                    if point <= i:
                        cut_index = point
                        break
            break

    starts_turn = is_turn_start_message(dialog[cut_index])
    turn_start = -1 if starts_turn else find_turn_start_index(dialog, cut_index, start_index)
    return CutPointResult(
        first_kept_index=cut_index,
        turn_start_index=turn_start,
        is_split_turn=(not starts_turn and turn_start != -1),
    )