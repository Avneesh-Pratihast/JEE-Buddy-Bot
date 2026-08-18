"""
Master JEE Advanced Academic Orchestrator.
Manages Master_State.json, Natural Language Evening Check-Ins,
Backlog Reservoir with PT/Pareto prioritization, and 1-7-30 Spaced Repetition.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import gemini_client
import obsidian_writer
import spaced_rep

logger = logging.getLogger("MasterOrchestrator")


# ── Master State Management ──────────────────────────────────────────────────

def load_master_state() -> dict:
    """Load Master_State.json from Obsidian Vault or data directory."""
    path = config.MASTER_STATE_PATH
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Error reading Master_State.json: %s", e)

    data_path = config.DATA_DIR / "Master_State.json"
    if data_path.exists():
        try:
            return json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fallback initial state
    return {
        "metadata": {
            "student": "Avneesh",
            "target_exam": "JEE Advanced 2028",
            "current_phase": 1,
            "phase_name": "Core Foundation & Syllabus Recovery",
            "total_study_target_hrs": 1498,
            "completed_study_hrs": 0,
            "last_updated": date.today().isoformat()
        },
        "subjects": {
            "Physics": {"total_target_hrs": 446, "completed_hrs": 0, "current_focus": "Kinematics"},
            "Chemistry": {"total_target_hrs": 568, "completed_hrs": 0, "current_focus": "Periodic Classification"},
            "Mathematics": {"total_target_hrs": 484, "completed_hrs": 0, "current_focus": "Trigonometry"}
        },
        "backlog_reservoir": [],
        "spaced_repetition_queue": [],
        "upcoming_tests": []
    }


def save_master_state(state: dict) -> None:
    """Save Master_State.json to both Obsidian vault and data directory."""
    state["metadata"]["last_updated"] = date.today().isoformat()

    # Save to Obsidian Vault
    if config.OBSIDIAN_VAULT.exists():
        vault_state = config.OBSIDIAN_VAULT / "00_Strategy" / "Master_State.json"
        vault_state.parent.mkdir(parents=True, exist_ok=True)
        try:
            vault_state.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning("Could not write to vault Master_State.json: %s", e)

    # Save to Local Data Mirror
    data_state = config.DATA_DIR / "Master_State.json"
    data_state.parent.mkdir(parents=True, exist_ok=True)
    try:
        data_state.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write to data Master_State.json: %s", e)


# ── Natural Language Evening Log Processor ──────────────────────────────────

EVENING_PARSER_SYSTEM = """
You are the Master JEE Advanced Academic Log Parser for Avneesh (Class 11, Target JEE Advanced 2028 AIR < 100).
Analyze the user's natural language daily study recap.

Extract the following information and return ONLY a valid JSON object matching this schema:
{
  "physics": {
    "hours": 0.0,
    "topic": "topic name or empty",
    "questions_solved": 0,
    "notes": "brief notes"
  },
  "chemistry": {
    "hours": 0.0,
    "topic": "topic name or empty",
    "questions_solved": 0,
    "notes": "brief notes"
  },
  "mathematics": {
    "hours": 0.0,
    "topic": "topic name or empty",
    "questions_solved": 0,
    "notes": "brief notes"
  },
  "missed_sessions": [
    {
      "subject": "Physics | Chemistry | Mathematics",
      "topic": "topic that was skipped or missed",
      "planned_hours": 1.5,
      "reason": "reason for skipping"
    }
  ],
  "flagged_errors": [
    {
      "subject": "Physics | Chemistry | Mathematics",
      "topic": "topic where mistake occurred",
      "error_type": "Conceptual Gap | Calculation Error | Question Misread | Formula Recall",
      "description": "what went wrong"
    }
  ],
  "motivating_summary": "4-5 line crisp, punchy executive summary of study achievements, backlog routing to weekend, and review items."
}
Only output valid JSON.
"""

async def process_evening_log(raw_text: str) -> dict:
    """
    Parses unstructured text/voice check-in, updates Master_State.json,
    schedules backlog & spaced rep, and creates Obsidian daily log & error notes.
    """
    state = load_master_state()
    today_str = date.today().isoformat()

    prompt = f"Daily Check-In Text:\n\"\"\"\n{raw_text}\n\"\"\"\n\nCurrent Master State Context:\n{json.dumps(state, indent=2)}"
    
    parsed_json_str = await gemini_client.ask(prompt, system=EVENING_PARSER_SYSTEM)
    
    try:
        # Strip code fences if present
        clean_json = parsed_json_str.strip()
        if clean_json.startswith("```"):
            clean_json = clean_json.split("\n", 1)[1]
        if clean_json.endswith("```"):
            clean_json = clean_json.rsplit("\n", 1)[0]
        data = json.loads(clean_json)
    except Exception as e:
        logger.exception("Failed to parse evening log JSON: %s", e)
        data = {
            "physics": {"hours": 0.0, "topic": "", "questions_solved": 0},
            "chemistry": {"hours": 0.0, "topic": "", "questions_solved": 0},
            "mathematics": {"hours": 0.0, "topic": "", "questions_solved": 0},
            "missed_sessions": [],
            "flagged_errors": [],
            "motivating_summary": "Logged your daily progress! Keep pushing for JEE Advanced."
        }

    # 1. Update Completed Hours
    p_hrs = float(data.get("physics", {}).get("hours", 0.0))
    c_hrs = float(data.get("chemistry", {}).get("hours", 0.0))
    m_hrs = float(data.get("mathematics", {}).get("hours", 0.0))
    total_day_hrs = p_hrs + c_hrs + m_hrs

    state["subjects"]["Physics"]["completed_hrs"] = round(state["subjects"]["Physics"].get("completed_hrs", 0) + p_hrs, 1)
    state["subjects"]["Chemistry"]["completed_hrs"] = round(state["subjects"]["Chemistry"].get("completed_hrs", 0) + c_hrs, 1)
    state["subjects"]["Mathematics"]["completed_hrs"] = round(state["subjects"]["Mathematics"].get("completed_hrs", 0) + m_hrs, 1)
    state["metadata"]["completed_study_hrs"] = round(state["metadata"].get("completed_study_hrs", 0) + total_day_hrs, 1)

    # 2. Process Missed Sessions -> Backlog Reservoir
    for missed in data.get("missed_sessions", []):
        subj = missed.get("subject", "General")
        topic = missed.get("topic", "Self-Study")
        hrs = missed.get("planned_hours", 1.5)
        
        # Calculate priority (PT test match > Mechanics/GOC Pareto > Normal)
        priority = "Moderate"
        topic_lower = topic.lower()
        if any(pt_word in topic_lower for pt_word in ["trigonometr", "2d", "projectile", "periodic", "motion in a plane"]):
            priority = "Critical (PT:03 Syllabus)"
        elif any(p_word in topic_lower for p_word in ["kinematics", "nlm", "friction", "work", "goc", "bonding"]):
            priority = "High (Advanced Pareto)"

        state["backlog_reservoir"].append({
            "date_missed": today_str,
            "subject": subj,
            "topic": topic,
            "deficit_hours": hrs,
            "priority": priority,
            "status": "Pending (Weekend Slot)"
        })

    # 3. Process Flagged Errors -> Spaced Repetition Queue & Obsidian Error Notes
    review_due_d7 = (date.today() + timedelta(days=7)).isoformat()
    review_due_d30 = (date.today() + timedelta(days=30)).isoformat()

    for err in data.get("flagged_errors", []):
        subj = err.get("subject", "Physics")
        topic = err.get("topic", "Core Concepts")
        etype = err.get("error_type", "Conceptual Gap")
        desc = err.get("description", "Identified gap")

        # Add to state queue
        state["spaced_repetition_queue"].append({
            "date_logged": today_str,
            "subject": subj,
            "topic": topic,
            "error_type": etype,
            "description": desc,
            "day7_due": review_due_d7,
            "day30_due": review_due_d30,
            "status": "Due Day 7"
        })

        # Create Obsidian Error Note
        try:
            err_path = obsidian_writer.create_error_note(
                subject=subj,
                topic=topic,
                problem="Logged from evening check-in.",
                mistake=desc,
                correct_solution=f"Review required for {etype}.",
                takeaway="Ensure conceptual rigor and double-check calculation steps.",
                error_type=etype,
                difficulty="Hard"
            )
            logger.info("Created error note in Obsidian: %s", err_path)
        except Exception as e:
            logger.warning("Could not create Obsidian error note: %s", e)

    # 4. Save Master State
    save_master_state(state)

    # 5. Append to Obsidian Daily Log
    try:
        log_content = (
            f"\n\n## 🌙 Evening Check-In Log ({today_str})\n"
            f"- **Physics**: {p_hrs}h ({data.get('physics', {}).get('topic', '-')}) — {data.get('physics', {}).get('questions_solved', 0)} questions\n"
            f"- **Chemistry**: {c_hrs}h ({data.get('chemistry', {}).get('topic', '-')}) — {data.get('chemistry', {}).get('questions_solved', 0)} questions\n"
            f"- **Mathematics**: {m_hrs}h ({data.get('math', {}).get('topic', '-')}) — {data.get('math', {}).get('questions_solved', 0)} questions\n"
            f"- **Total Studied**: **{total_day_hrs} hours**\n\n"
            f"### 📋 Executive Summary\n{data.get('motivating_summary', '')}\n"
        )
        daily_log_file = config.OBSIDIAN_VAULT / "01_Daily_Logs" / f"{today_str}.md"
        daily_log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(daily_log_file, "a", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        logger.warning("Could not append to daily log: %s", e)

    return {
        "total_day_hours": total_day_hrs,
        "physics": p_hrs,
        "chemistry": c_hrs,
        "math": m_hrs,
        "missed_count": len(data.get("missed_sessions", [])),
        "error_count": len(data.get("flagged_errors", [])),
        "summary": data.get("motivating_summary", "Evening check-in processed successfully!")
    }


# ── Backlog Summary Formatter ────────────────────────────────────────────────

def get_backlog_summary() -> str:
    """Format the active backlog reservoir with PT/Pareto prioritization."""
    state = load_master_state()
    queue = state.get("backlog_reservoir", [])
    
    if not queue:
        return (
            "🎉 **Zero Backlog! You are 100% on track.**\n\n"
            "Keep maintaining this discipline. Every minute ahead of schedule "
            "directly increases your rank buffer for JEE Advanced 2028."
        )

    # Sort: Critical (PT) -> High (Pareto) -> Moderate
    def sort_key(item):
        p = item.get("priority", "")
        if "Critical" in p or "PT" in p:
            return 0
        if "High" in p or "Pareto" in p:
            return 1
        return 2

    sorted_queue = sorted(queue, key=sort_key)
    total_deficit = sum(item.get("deficit_hours", 0) for item in sorted_queue)

    lines = [
        f"📋 **JEE 2028 Backlog Reservoir**",
        f"⏱️ Total Pending Deficit: **{total_deficit:.1f} hours**\n",
        "🎯 **Prioritized Recovery Order (PT:03 & Pareto First)**:"
    ]

    for idx, item in enumerate(sorted_queue, 1):
        subj = item.get("subject", "")
        topic = item.get("topic", "")
        hrs = item.get("deficit_hours", 0)
        prio = item.get("priority", "Moderate")
        lines.append(f"{idx}. **[{subj}]** {topic} — `{hrs}h` _({prio})_")

    lines.extend([
        "\n🛡️ **Backlog Golden Protocol**:",
        "• **Saturday Slot**: 1.5h Afternoon",
        "• **Sunday Slot**: 3.0h Morning (4.5h weekly recovery buffer)",
        "• *Never compromise ongoing coaching lectures for backlog!*"
    ])

    return "\n".join(lines)


# ── Spaced Repetition Due Formatter ──────────────────────────────────────────

def get_spaced_rep_summary() -> str:
    """Format active spaced repetition review queue."""
    state = load_master_state()
    queue = state.get("spaced_repetition_queue", [])
    
    if not queue:
        return "✨ **No active errors in your spaced repetition queue!**\nKeep logging your hard questions."

    today_str = date.today().isoformat()
    due_items = [q for q in queue if q.get("day7_due", "") <= today_str or q.get("day30_due", "") <= today_str]

    lines = ["🧠 **1-7-30 Spaced Repetition Review Queue**\n"]
    if due_items:
        lines.append("🔴 **Due for Re-Solving Today**:")
        for idx, item in enumerate(due_items, 1):
            lines.append(f"{idx}. **[{item.get('subject')}]** {item.get('topic')} — *{item.get('error_type')}* ({item.get('description')})")
    else:
        lines.append(f"🟢 All {len(queue)} items are in incubation. Next reviews scheduled upcoming this week.")

    return "\n".join(lines)
