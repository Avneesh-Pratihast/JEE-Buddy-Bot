"""
Obsidian vault reader/writer — creates and reads markdown files
in the JEE prep Obsidian vault.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# ── Chapter Tracker ─────────────────────────────────────────────────────────

def read_chapter_tracker() -> dict:
    """Load the chapter tracker JSON from the skill resources."""
    try:
        return json.loads(config.CHAPTER_TRACKER.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Chapter tracker not found at %s", config.CHAPTER_TRACKER)
        return {"subjects": {}}


def save_chapter_tracker(data: dict) -> None:
    """Write updated chapter tracker back to disk."""
    data["metadata"]["last_updated"] = date.today().isoformat()
    config.CHAPTER_TRACKER.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def update_chapter_status(
    subject: str,
    chapter_name: str,
    *,
    status: str | None = None,
    hours_add: float = 0,
    started: bool = False,
    completed: bool = False,
) -> str:
    """Update a chapter's status in the tracker. Returns a confirmation message."""
    tracker = read_chapter_tracker()
    subjects = tracker.get("subjects", {})

    if subject not in subjects:
        return f"❌ Subject '{subject}' not found."

    for ch in subjects[subject]["chapters"]:
        if ch["name"].lower() == chapter_name.lower():
            today = date.today().isoformat()
            if status:
                ch["status"] = status
            if hours_add:
                ch["hours_completed"] = ch.get("hours_completed", 0) + hours_add
            if started and not ch.get("started_date"):
                ch["started_date"] = today
                ch["status"] = "in_progress"
            if completed:
                ch["completed_date"] = today
                ch["status"] = "completed"

            save_chapter_tracker(tracker)
            return (
                f"✅ Updated **{ch['name']}** — "
                f"Status: {ch['status']}, "
                f"Hours: {ch['hours_completed']}/{ch['study_hours_required']}"
            )

    return f"❌ Chapter '{chapter_name}' not found in {subject}."


def get_phase1_progress() -> dict:
    """Return progress stats for Phase 1 chapters only."""
    tracker = read_chapter_tracker()
    stats = {}
    for subj, data in tracker.get("subjects", {}).items():
        phase1 = [c for c in data["chapters"] if c.get("phase") == 1]
        total = len(phase1)
        completed = sum(1 for c in phase1 if c["status"] == "completed")
        in_prog = sum(1 for c in phase1 if c["status"] == "in_progress")
        hours_done = sum(c.get("hours_completed", 0) for c in phase1)
        hours_req = sum(c["study_hours_required"] for c in phase1)
        stats[subj] = {
            "total": total,
            "completed": completed,
            "in_progress": in_prog,
            "not_started": total - completed - in_prog,
            "hours_done": hours_done,
            "hours_required": hours_req,
        }
    return stats


# ── Daily Logs ──────────────────────────────────────────────────────────────

def _daily_log_path(d: date) -> Path:
    return config.OBSIDIAN_VAULT / "01_Daily_Logs" / f"{d.isoformat()}.md"


def daily_log_exists(d: date) -> bool:
    return _daily_log_path(d).exists()


def read_daily_log(d: date) -> str | None:
    p = _daily_log_path(d)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def create_daily_log(d: date, plan_content: str) -> Path:
    """Create today's daily log with the generated study plan."""
    day_name = d.strftime("%A")
    is_coaching = d.weekday() in config.COACHING_DAYS

    content = f"""---
date: {d.isoformat()}
day: {day_name}
hours_studied: 0
efficiency_rating: 5
coaching_day: {str(is_coaching).lower()}
tags:
  - daily_log
  - jee_prep
---

# 📅 Daily Study Log — {d.isoformat()} ({day_name})

## 📋 Today's Plan
{"🏫 **Coaching Day** — focus on homework & practice after class" if is_coaching else "📖 **Self-Study Day** — full deep-study schedule"}

{plan_content}

---

## ⏱️ Time & Session Breakdown
| Session | Subject / Topic | Duration | Questions Solved | Difficulty (○/△/★) | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Slot 1 | | | | | |
| Slot 2 | | | | | |
| Slot 3 | | | | | |
| Slot 4 | | | | | |

**Total Hours**: 0

---

## 💡 Key Learnings
-

## ⚠️ Mistakes to Review
- Logged errors? [ ] Yes / [ ] None

## 📊 End-of-Day Self-Assessment
- **Productivity (1-10)**:
- **Understanding (1-10)**:
- **Tomorrow's focus**:
"""
    path = _daily_log_path(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Created daily log: %s", path)
    return path


# ── Error Notes ─────────────────────────────────────────────────────────────

def get_next_error_id() -> str:
    """Scan existing error notes and return the next ERR-NNN id."""
    error_dir = config.OBSIDIAN_VAULT / "03_Error_Database"
    error_dir.mkdir(parents=True, exist_ok=True)

    existing = list(error_dir.glob("ERR-*.md"))
    if not existing:
        return "ERR-001"

    ids = []
    for f in existing:
        match = re.match(r"ERR-(\d+)", f.stem)
        if match:
            ids.append(int(match.group(1)))

    next_id = max(ids, default=0) + 1
    return f"ERR-{next_id:03d}"


def create_error_note(
    subject: str,
    topic: str,
    problem: str,
    mistake: str,
    correct_solution: str,
    takeaway: str,
    *,
    error_type: str = "Conceptual",
    source: str = "",
    difficulty: str = "Advanced",
) -> Path:
    """Create an error note in the Obsidian error database."""
    err_id = get_next_error_id()
    safe_topic = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:30]
    filename = f"{err_id}_{subject}_{safe_topic}.md"

    content = f"""---
id: {err_id}
date: {date.today().isoformat()}
subject: {subject}
topic: {topic}
difficulty: {difficulty}
source: "{source}"
error_type: {error_type}
revision_status: Pending
tags:
  - error_database
  - {subject.lower()}
---

# ❌ Mistake Note: {err_id}

## ❓ Problem Statement
> {problem}

---

## 🛑 What Went Wrong?
- **Error Type**: {error_type}
- **Details**: {mistake}

---

## ✅ Correct Solution
{correct_solution}

---

## 📌 Golden Takeaway
{takeaway}
"""
    path = config.OBSIDIAN_VAULT / "03_Error_Database" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Created error note: %s", path)
    return path


# ── Weekly Reviews ──────────────────────────────────────────────────────────

def create_weekly_review(week_start: date, content: str) -> Path:
    """Save a weekly review report to the vault."""
    week_end = week_start
    # Find the Sunday of that week
    from datetime import timedelta
    week_end = week_start + timedelta(days=6 - week_start.weekday())

    filename = f"Week_{week_start.isoformat()}_to_{week_end.isoformat()}.md"
    path = config.OBSIDIAN_VAULT / "04_Weekly_Reviews" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Created weekly review: %s", path)
    return path
