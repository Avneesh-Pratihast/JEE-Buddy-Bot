"""
Antigravity <-> Telegram Bridge
Connects Antigravity's high-intelligence engine with your Telegram chat.
Handles automated Telegram pushes for Daily Plans, Weekly Reports, and Deep Doubts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import requests

import config
import gemini_client
import obsidian_writer
import scheduler
import spaced_rep

logging.basicConfig(
    format="%(asctime)s [AntigravityBridge] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("AntigravityBridge")

MAX_TG_MSG_LEN = 4000


# ── Telegram Direct Messenger ───────────────────────────────────────────────

def send_telegram_message(text: str, chat_id: int | None = None) -> bool:
    """Send a formatted message directly to Avneesh's Telegram chat."""
    token = config.TELEGRAM_BOT_TOKEN
    target_chat = chat_id or config.AVNEESH_CHAT_ID

    if not token or target_chat == 0:
        logger.error("TELEGRAM_BOT_TOKEN or AVNEESH_CHAT_ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = [text[i : i + MAX_TG_MSG_LEN] for i in range(0, len(text), MAX_TG_MSG_LEN)]

    success = True
    for chunk in chunks:
        payload = {
            "chat_id": target_chat,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code != 200:
                # Fallback to plain text if Markdown parsing fails
                payload.pop("parse_mode")
                r2 = requests.post(url, json=payload, timeout=10)
                if r2.status_code != 200:
                    logger.error("Failed to send Telegram message: %s", r2.text)
                    success = False
        except Exception as e:
            logger.exception("Error sending message to Telegram: %s", e)
            success = False

    return success


# ── High-Intelligence Generation Functions ─────────────────────────────────

async def run_morning_plan_pipeline() -> str:
    """
    1. Reads yesterday's logged sessions to compile Previous Day Performance Report.
    2. Reads chapter tracker, Aakash timetable (FR01), routine (4:30 PM start), spaced rep queue.
    3. Generates elite daily study plan.
    4. Saves to Obsidian (01_Daily_Logs/YYYY-MM-DD.md).
    5. Pushes combined Previous Day Report + Today's Plan directly to Telegram.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    logger.info("Generating morning report for %s and plan for %s", yesterday.isoformat(), today.isoformat())

    # 1. Previous Day Report
    yesterday_summary = await scheduler.generate_progress_summary(yesterday)
    streak = scheduler.get_streak()
    streak_str = f"🔥 Streak: **{streak} days**" if streak > 0 else "🔥 Streak: **Day 1**"

    # 2. Today's Plan
    plan = await scheduler.generate_daily_plan(today)

    # Save to Obsidian
    obsidian_path = obsidian_writer.create_daily_log(today, plan)
    logger.info("Saved daily log to %s", obsidian_path)

    # Format and push to Telegram
    day_name = today.strftime("%A")
    yesterday_day_name = yesterday.strftime("%A")
    tg_message = (
        f"🌅 **Good Morning Avneesh!**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **PREVIOUS DAY REPORT ({yesterday.isoformat()} - {yesterday_day_name})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{yesterday_summary}\n\n"
        f"{streak_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 **TODAY'S STUDY PLAN ({today.isoformat()} - {day_name})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏋️ *Workout*: 8:30 AM – 10:00 AM\n"
        f"🏫 *Coaching*: 11:00 AM – 3:30 PM (Batch FR01)\n"
        f"⚡ *Deep Self-Study Window*: **Starts 4:30 PM**\n\n"
        f"{plan}\n\n"
        f"📝 *Saved to Obsidian*: `{obsidian_path.name}`\n"
        f"Reply with `/done <Subject> <Topic> <hours>h <questions>q` when completing sessions!"
    )

    send_telegram_message(tg_message)
    return plan


async def run_night_summary_pipeline() -> str:
    """
    1. Reads today's logged sessions & tracker progress.
    2. Generates end-of-day summary.
    3. Pushes to Telegram.
    """
    today = date.today()
    logger.info("Generating nightly summary for %s", today.isoformat())

    summary = await scheduler.generate_progress_summary(today)
    streak = scheduler.get_streak()
    streak_str = f"🔥 Streak: **{streak} days**" if streak > 0 else ""

    tg_message = (
        f"🌙 **End-of-Day Progress Summary — {today.isoformat()}**\n\n"
        f"{summary}\n\n"
        f"{streak_str}\n\n"
        f"😴 Rest well tonight — tomorrow we continue the grind to AIR < 100!"
    )

    send_telegram_message(tg_message)
    return summary


async def run_weekly_review_pipeline() -> str:
    """
    1. Compiles all logs, study hours vs targets (P:14h, C:10h, M:12h), error notes.
    2. Generates deep weekly report.
    3. Saves to Obsidian (04_Weekly_Reviews/).
    4. Pushes report to Telegram.
    """
    logger.info("Generating weekly review report")
    report = await scheduler.generate_weekly_report()

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    tg_message = (
        f"📊 **JEE Advanced Weekly Analytics Report**\n"
        f"🗓️ **Week of {week_start.isoformat()} to {today.isoformat()}**\n\n"
        f"{report}\n\n"
        f"📁 *Saved in your Obsidian vault under 04_Weekly_Reviews/*"
    )

    send_telegram_message(tg_message)
    return report


# ── Direct CLI Runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"

    if cmd == "plan":
        print("[Antigravity] Generating and pushing Daily Plan...")
        asyncio.run(run_morning_plan_pipeline())
        print("[OK] Daily Plan pushed to Telegram and saved to Obsidian!")
    elif cmd == "night":
        print("[Antigravity] Generating and pushing Nightly Summary...")
        asyncio.run(run_night_summary_pipeline())
        print("[OK] Nightly Summary pushed to Telegram!")
    elif cmd == "week":
        print("[Antigravity] Generating and pushing Weekly Review...")
        asyncio.run(run_weekly_review_pipeline())
        print("[OK] Weekly Review pushed to Telegram and saved to Obsidian!")
    elif cmd == "test":
        print("[Antigravity] Sending test message to Telegram...")
        ok = send_telegram_message("🚀 **Antigravity Bridge is Connected!**\nYour top-tier AI planner and review engine is live.")
        if ok:
            print("[OK] Telegram test message delivered successfully!")
        else:
            print("[FAIL] Could not deliver test message. Check your .env config.")
    else:
        print(f"Unknown command '{cmd}'. Available: plan, night, week, test")
