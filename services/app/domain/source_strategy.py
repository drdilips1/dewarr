"""Quick add walks source priority unless the reader asks to rank every source."""

from typing import Literal

REVIEW = "Request added. No automatic release was found, so the download did not start."


def roots(source_order: list[str]) -> list[str]:
    ordered: list[str] = []
    for item in source_order:
        root = item.split(":", 1)[0]
        if root not in ordered:
            ordered.append(root)
    return ordered


def search_order(source_order: list[str], connected: set[str]) -> list[str]:
    """Priority roots that are connected, then any other connected source."""
    ordered = [root for root in roots(source_order) if root in connected]
    for key in sorted(connected):
        root = key.split(":", 1)[0]
        if root not in ordered:
            ordered.append(root)
    return ordered


def outcome(
    strategy: str,
    fallback: bool,
    index: int,
    count: int,
    *,
    found: bool,
) -> Literal["use", "next", "review"]:
    if found:
        return "use"
    if strategy == "priority" and fallback and index + 1 < count:
        return "next"
    return "review"


def ready_for_next_source(slots: dict) -> bool:
    """Move on only after every unfinished format has missed this source."""
    pending = [item for item in slots.values() if not item.get("done")]
    return bool(pending) and all(item.get("wants_next") for item in pending)


def review_message(tried: list[dict], final: str | None = None) -> str:
    parts = [REVIEW]
    for item in tried:
        text = str(item.get("message") or "").strip()
        name = str(item.get("name") or "Source")
        if text:
            parts.append(f"{name}: {text}")
    if final and final not in parts:
        parts.append(final)
    return " ".join(parts)
