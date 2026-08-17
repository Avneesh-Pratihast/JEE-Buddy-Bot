"""
Spaced Repetition Engine — implements the 1-7-30 rule.

When a topic is completed or an error is logged, this module schedules
Day-1 / Day-7 / Day-30 reviews and tracks completion.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)

QUEUE_PATH: Path = config.DATA_DIR / "revision_queue.json"


def _load() -> dict:
    try:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"topics": [], "errors": [], "completed_reviews": []}


def _save(data: dict) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


# ── Add Items ───────────────────────────────────────────────────────────────

def add_topic(topic: str, subject: str, learned_date: date | None = None) -> dict:
    """
    Schedule spaced repetition reviews for a completed topic.
    Returns the created entry.
    """
    d = learned_date or date.today()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "type": "topic",
        "topic": topic,
        "subject": subject,
        "learned_date": d.isoformat(),
        "reviews": {
            "day_7": {"due": (d + timedelta(days=7)).isoformat(), "done": False},
            "day_30": {"due": (d + timedelta(days=30)).isoformat(), "done": False},
        },
    }
    data = _load()
    data["topics"].append(entry)
    _save(data)
    logger.info("Scheduled revision for topic '%s' (%s)", topic, subject)
    return entry


def add_error(
    error_id: str, topic: str, subject: str, error_date: date | None = None
) -> dict:
    """
    Schedule reviews for an error note.
    Errors get extra review at Day 3 in addition to Day 7 and Day 30.
    """
    d = error_date or date.today()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "type": "error",
        "error_id": error_id,
        "topic": topic,
        "subject": subject,
        "logged_date": d.isoformat(),
        "reviews": {
            "day_3": {"due": (d + timedelta(days=3)).isoformat(), "done": False},
            "day_7": {"due": (d + timedelta(days=7)).isoformat(), "done": False},
            "day_30": {"due": (d + timedelta(days=30)).isoformat(), "done": False},
        },
    }
    data = _load()
    data["errors"].append(entry)
    _save(data)
    logger.info("Scheduled error revision for %s ('%s')", error_id, topic)
    return entry


# ── Query Reviews ───────────────────────────────────────────────────────────

def get_due_reviews(target_date: date | None = None) -> list[dict]:
    """
    Return all review items due on or before `target_date`.
    Each dict has: id, type, topic, subject, review_type, due_date.
    """
    d = (target_date or date.today()).isoformat()
    data = _load()
    due: list[dict] = []

    for item in data["topics"]:
        for rev_type, rev in item["reviews"].items():
            if not rev["done"] and rev["due"] <= d:
                due.append({
                    "id": item["id"],
                    "type": "topic",
                    "topic": item["topic"],
                    "subject": item["subject"],
                    "review_type": rev_type,
                    "due_date": rev["due"],
                })

    for item in data["errors"]:
        for rev_type, rev in item["reviews"].items():
            if not rev["done"] and rev["due"] <= d:
                due.append({
                    "id": item["id"],
                    "type": "error",
                    "error_id": item.get("error_id", "?"),
                    "topic": item["topic"],
                    "subject": item["subject"],
                    "review_type": rev_type,
                    "due_date": rev["due"],
                })

    return sorted(due, key=lambda x: x["due_date"])


def mark_reviewed(item_id: str, review_type: str) -> bool:
    """Mark a specific review as completed. Returns True if found."""
    data = _load()

    for collection in (data["topics"], data["errors"]):
        for item in collection:
            if item["id"] == item_id and review_type in item["reviews"]:
                item["reviews"][review_type]["done"] = True
                item["reviews"][review_type]["completed"] = date.today().isoformat()
                data["completed_reviews"].append({
                    "item_id": item_id,
                    "review_type": review_type,
                    "completed": date.today().isoformat(),
                })
                _save(data)
                return True

    return False


# ── Formatting ──────────────────────────────────────────────────────────────

def format_due_reviews(target_date: date | None = None) -> str:
    """Format due reviews as a readable message."""
    reviews = get_due_reviews(target_date)

    if not reviews:
        return "✅ No reviews due today! Keep studying. 💪"

    lines = [f"🔁 **{len(reviews)} review(s) due today:**\n"]
    for r in reviews:
        emoji = "📚" if r["type"] == "topic" else "❌"
        rev_label = r["review_type"].replace("_", " ").title()
        lines.append(
            f"{emoji} **{r['subject']}** — {r['topic']} ({rev_label})"
        )

    lines.append("\nReply `/reviewed <id>` when done, or `skip` to postpone.")
    return "\n".join(lines)


def get_stats() -> dict:
    """Return overall spaced rep statistics."""
    data = _load()
    total_topics = len(data["topics"])
    total_errors = len(data["errors"])
    total_completed = len(data["completed_reviews"])
    pending = len(get_due_reviews())
    return {
        "topics_tracked": total_topics,
        "errors_tracked": total_errors,
        "reviews_completed": total_completed,
        "reviews_pending": pending,
    }
