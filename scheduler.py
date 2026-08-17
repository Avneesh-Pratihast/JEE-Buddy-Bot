"""
Study Plan Scheduler — generates daily plans and progress summaries
by combining chapter tracker data, coaching schedule, and Gemini AI.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import config
import gemini_client
import obsidian_writer
import spaced_rep

logger = logging.getLogger(__name__)


def _load_aakash_schedule() -> dict:
    """Load the parsed Aakash coaching schedule."""
    path = config.DATA_DIR / "aakash_schedule.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"parsed": {"days": {}}}


def _load_study_log() -> dict:
    """Load the study log."""
    path = config.DATA_DIR / "study_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"days": {}}


def _save_study_log(data: dict) -> None:
    path = config.DATA_DIR / "study_log.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def log_study_session(
    subject: str, topic: str, hours: float, questions: int = 0
) -> str:
    """Log a completed study session."""
    today = date.today().isoformat()
    data = _load_study_log()

    if today not in data["days"]:
        data["days"][today] = {"sessions": [], "total_hours": 0}

    session = {
        "subject": subject,
        "topic": topic,
        "hours": hours,
        "questions": questions,
    }
    data["days"][today]["sessions"].append(session)
    data["days"][today]["total_hours"] += hours
    _save_study_log(data)

    # Also update chapter tracker hours
    obsidian_writer.update_chapter_status(
        subject, topic, hours_add=hours, started=True
    )

    return (
        f"✅ Logged: **{subject}** — {topic}\n"
        f"⏱️ {hours}h | 📝 {questions} questions\n"
        f"📊 Today's total: {data['days'][today]['total_hours']}h"
    )


def get_streak() -> int:
    """Calculate the current consecutive study day streak."""
    data = _load_study_log()
    streak = 0
    check_date = date.today()

    while True:
        if check_date.isoformat() in data["days"]:
            day_data = data["days"][check_date.isoformat()]
            if day_data.get("total_hours", 0) > 0:
                streak += 1
                check_date -= timedelta(days=1)
                continue
        break

    return streak


async def generate_daily_plan(target_date: date | None = None) -> str:
    """Generate a personalised daily study plan using Gemini."""
    d = target_date or date.today()
    is_coaching = d.weekday() in config.COACHING_DAYS
    day_name = d.strftime("%A")

    # Gather context
    progress = obsidian_writer.get_phase1_progress()
    aakash = _load_aakash_schedule()
    due_reviews = spaced_rep.get_due_reviews(d)
    streak = get_streak()

    # Get coaching info for today
    coaching_info = aakash.get("parsed", {}).get("days", {}).get(day_name, {})

    # Build context prompt
    context = f"""Generate a study plan for {d.isoformat()} ({day_name}).

**Day Type**: {"Coaching day (5h self-study)" if is_coaching else "Self-study day (8h available)"}
**Current Streak**: {streak} days

**Phase 1 Progress**:
"""
    for subj, stats in progress.items():
        context += (
            f"- {subj}: {stats['completed']}/{stats['total']} chapters done, "
            f"{stats['hours_done']}/{stats['hours_required']}h completed\n"
        )

    if coaching_info:
        context += f"\n**Today's Coaching**: {coaching_info.get('subject', 'Unknown')} — {coaching_info.get('topic', 'Unknown')}\n"
    else:
        context += "\n**Coaching schedule**: Not yet updated for this week.\n"

    if due_reviews:
        context += f"\n**Spaced Repetition Due**: {len(due_reviews)} item(s):\n"
        for r in due_reviews[:5]:
            context += f"  - {r['subject']}: {r['topic']} ({r['review_type']})\n"

    context += "\nGenerate 3-4 specific study blocks with topics, question counts, and time allocations."

    plan = await gemini_client.generate_plan(context)
    return plan


async def generate_progress_summary(target_date: date | None = None) -> str:
    """Generate an end-of-day progress summary."""
    d = target_date or date.today()
    data = _load_study_log()
    today_data = data["days"].get(d.isoformat(), {})

    if not today_data.get("sessions"):
        return (
            f"📊 **{d.isoformat()} Summary**\n\n"
            "No study sessions logged today. "
            "Use `/done` to log what you studied!"
        )

    sessions = today_data["sessions"]
    total_hours = today_data.get("total_hours", 0)
    streak = get_streak()

    # Group by subject
    by_subject: dict[str, float] = {}
    for s in sessions:
        by_subject[s["subject"]] = by_subject.get(s["subject"], 0) + s["hours"]

    context = f"""Summarise this day's study progress:

**Date**: {d.isoformat()}
**Total Hours**: {total_hours}
**Streak**: {streak} days
**Sessions**:
"""
    for s in sessions:
        context += f"- {s['subject']}: {s['topic']} ({s['hours']}h, {s['questions']} questions)\n"

    progress = obsidian_writer.get_phase1_progress()
    context += "\n**Overall Phase 1 Progress**:\n"
    for subj, stats in progress.items():
        context += f"- {subj}: {stats['hours_done']}/{stats['hours_required']}h\n"

    return await gemini_client.generate_summary(context)


async def generate_weekly_report() -> str:
    """Generate a comprehensive weekly analytics report."""
    today = date.today()
    # Find the Monday of the current week
    week_start = today - timedelta(days=today.weekday())
    data = _load_study_log()

    weekly_hours: dict[str, float] = {}
    total_sessions = 0
    total_questions = 0

    for i in range(7):
        d = week_start + timedelta(days=i)
        day_data = data["days"].get(d.isoformat(), {})
        for s in day_data.get("sessions", []):
            subj = s["subject"]
            weekly_hours[subj] = weekly_hours.get(subj, 0) + s["hours"]
            total_sessions += 1
            total_questions += s.get("questions", 0)

    progress = obsidian_writer.get_phase1_progress()
    streak = get_streak()
    rep_stats = spaced_rep.get_stats()

    context = f"""Generate a weekly JEE prep report for {week_start.isoformat()} to {today.isoformat()}.

**Hours This Week**:
"""
    for subj in ["Physics", "Chemistry", "Mathematics"]:
        hours = weekly_hours.get(subj, 0)
        target = config.WEEKLY_TARGETS.get(subj, 0)
        status = "✅ On Track" if hours >= target else "⚠️ Behind"
        context += f"- {subj}: {hours:.1f}h / {target}h target — {status}\n"

    total = sum(weekly_hours.values())
    context += f"\n**Total**: {total:.1f}h | **Sessions**: {total_sessions} | **Questions**: {total_questions}\n"
    context += f"**Streak**: {streak} days\n"

    context += "\n**Phase 1 Chapter Progress**:\n"
    for subj, stats in progress.items():
        context += (
            f"- {subj}: {stats['completed']} completed, "
            f"{stats['in_progress']} in progress, "
            f"{stats['not_started']} not started\n"
        )

    context += f"\n**Spaced Repetition**: {rep_stats['reviews_pending']} reviews pending\n"

    context += "\nProvide: subject-wise analysis, top 3 recommendations, and next week focus areas."

    report = await gemini_client.generate_summary(context)

    # Save to Obsidian
    obsidian_writer.create_weekly_review(week_start, report)

    return report
