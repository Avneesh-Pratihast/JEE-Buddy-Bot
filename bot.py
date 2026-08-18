"""
JEE Buddy — Telegram Bot
Main entry point. Handles all commands, photo doubts, and scheduled notifications.

Usage:
    python bot.py           # Run the bot
    python bot.py --test    # Verify config and exit
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, time, timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import doubt_solver
import gemini_client
import master_orchestrator
import obsidian_writer
import scheduler
import spaced_rep

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("jee_buddy")

# Telegram has a 4096-char message limit
MAX_MSG_LEN = 4000


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _send_long(
    update_or_context,
    text: str,
    chat_id: int | None = None,
) -> None:
    """Send a message, splitting if it exceeds Telegram's limit."""
    if hasattr(update_or_context, "message") and update_or_context.message:
        send = update_or_context.message.reply_text
    else:
        ctx = update_or_context
        async def send(t, **kw):
            await ctx.bot.send_message(
                chat_id=chat_id or config.AVNEESH_CHAT_ID, text=t, **kw
            )

    chunks = [text[i : i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
    for chunk in chunks:
        try:
            await send(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning("Markdown send failed (%s). Retrying as plain text...", e)
            try:
                await send(chunk)
            except Exception as e2:
                logger.exception("Failed to send message: %s", e2)


def _is_avneesh(update: Update) -> bool:
    """Check if the message is from Avneesh (security guard)."""
    if not update.effective_chat:
        return True
    if config.AVNEESH_CHAT_ID == 0:
        return True
    return str(update.effective_chat.id).strip() == str(config.AVNEESH_CHAT_ID).strip()


# ── Command Handlers ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🎯 **JEE Buddy Bot — Active!**\n\n"
        f"Hey Avneesh! I'm your JEE Advanced prep companion.\n\n"
        f"📌 **Your Chat ID**: `{chat_id}`\n"
        f"_(save this in your .env file as AVNEESH_CHAT_ID)_\n\n"
        f"**Commands**:\n"
        f"/plan — Today's study plan\n"
        f"/done — Log completed study\n"
        f"/doubt — Solve a JEE problem\n"
        f"/schedule — Forward Aakash schedule\n"
        f"/week — Weekly progress report\n"
        f"/streak — Study streak\n"
        f"/review — Spaced repetition queue\n"
        f"/help — Show all commands\n\n"
        f"📸 Or just **send a photo** of any JEE problem!",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "📖 **JEE Buddy Commands**\n\n"
        "`/plan` — Generate today's study plan\n"
        "`/done Physics Kinematics 2h 15q` — Log a study session\n"
        "`/doubt <question>` — Solve a text problem\n"
        "`/review` — See what's due for spaced repetition\n"
        "`/reviewed <id>` — Mark a review as done\n"
        "`/streak` — Your study streak\n"
        "`/week` — Weekly analytics report\n"
        "`/schedule` — Forward your Aakash schedule here\n"
        "`/progress` — Phase 1 chapter progress\n"
        "`/error` — Log a mistake for review\n\n"
        "📸 **Send any photo** → I'll solve it as a JEE problem",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /plan — generate today's study plan."""
    if not _is_avneesh(update):
        return

    await update.message.reply_text("📝 Generating your study plan...")

    plan = await scheduler.generate_daily_plan()

    # Save to Obsidian
    obsidian_writer.create_daily_log(date.today(), plan)

    await _send_long(update, f"📋 **Today's Plan** ({date.today().isoformat()}):\n\n{plan}")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /done — log a study session.
    Format: /done <Subject> <Topic> <hours>h [<questions>q]
    Example: /done Physics Kinematics 2h 15q
    """
    if not _is_avneesh(update):
        return

    text = update.message.text.replace("/done", "").strip()

    if not text:
        await update.message.reply_text(
            "📝 **How to log study**:\n"
            "`/done Physics Kinematics 2h 15q`\n\n"
            "Format: `/done <Subject> <Topic> <hours>h [questions]q`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Parse the input
    hours_match = re.search(r"(\d+\.?\d*)\s*h", text)
    questions_match = re.search(r"(\d+)\s*q", text)

    hours = float(hours_match.group(1)) if hours_match else 0
    questions = int(questions_match.group(1)) if questions_match else 0

    # Remove hours and questions from text to get subject + topic
    remaining = re.sub(r"\d+\.?\d*\s*h", "", text)
    remaining = re.sub(r"\d+\s*q", "", remaining).strip()

    parts = remaining.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Please include both subject and topic.\n"
            "Example: `/done Physics Kinematics 2h 15q`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    subject = parts[0].capitalize()
    topic = parts[1].strip()

    if hours <= 0:
        await update.message.reply_text("❌ Please include hours (e.g., `2h`).")
        return

    result = scheduler.log_study_session(subject, topic, hours, questions)
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)

    # Schedule spaced repetition
    spaced_rep.add_topic(topic, subject)
    await update.message.reply_text(
        f"🔁 Spaced repetition scheduled for **{topic}**:\n"
        f"  📅 Day 7 review: {(date.today() + timedelta(days=7)).isoformat()}\n"
        f"  📅 Day 30 review: {(date.today() + timedelta(days=30)).isoformat()}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_doubt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /doubt — solve a text-based problem."""
    if not _is_avneesh(update):
        return

    question = update.message.text.replace("/doubt", "").strip()

    if not question:
        await update.message.reply_text(
            "❓ **How to ask a doubt**:\n"
            "`/doubt Find the velocity of a ball dropped from 20m after 3s`\n\n"
            "Or just **send a photo** of the problem!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🧠 Solving...")
    solution = await doubt_solver.solve_text(question)
    await _send_long(update, solution)

    # Prompt to log as error
    await update.message.reply_text(
        "💡 Got it wrong before? Log it with:\n"
        "`/error <Subject> <Topic> <what went wrong>`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /schedule — prompt to forward Aakash WhatsApp schedule."""
    if not _is_avneesh(update):
        return

    await update.message.reply_text(
        "📅 **Forward your Aakash schedule here!**\n\n"
        "Just forward the WhatsApp message from your Aakash batch group. "
        "I'll parse it and adjust your study plan automatically.\n\n"
        "_(Forward any text message with this week's schedule)_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week — generate weekly analytics report."""
    if not _is_avneesh(update):
        return

    await update.message.reply_text("📊 Generating weekly report...")
    report = await scheduler.generate_weekly_report()
    await _send_long(update, f"📊 **Weekly Report**:\n\n{report}")


async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /streak — show study streak."""
    if not _is_avneesh(update):
        return

    streak = scheduler.get_streak()

    if streak == 0:
        msg = "🔥 Streak: **0 days**\nStart studying today to begin your streak!"
    elif streak < 7:
        msg = f"🔥 Streak: **{streak} day(s)**\nKeep going! 💪"
    elif streak < 30:
        msg = f"🔥🔥 Streak: **{streak} days**\nYou're on fire! Don't break it!"
    else:
        msg = f"🔥🔥🔥 Streak: **{streak} days**\nLEGENDARY consistency! 🏆"

    await _send_long(update, msg)


async def cmd_backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /backlog — show dynamic backlog reservoir with PT/Pareto priorities."""
    if not _is_avneesh(update):
        return

    msg = master_orchestrator.get_backlog_summary()
    await _send_long(update, msg)


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /review — show 1-7-30 spaced repetition review queue."""
    if not _is_avneesh(update):
        return

    msg = master_orchestrator.get_spaced_rep_summary()
    await _send_long(update, msg)


async def cmd_reviewed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reviewed <id> <review_type> — mark review as done."""
    if not _is_avneesh(update):
        return

    parts = update.message.text.replace("/reviewed", "").strip().split()
    if len(parts) < 1:
        await _send_long(
            update,
            "Usage: `/reviewed <item_id> [review_type]`\n"
            "Example: `/reviewed abc123 day_7`",
        )
        return

    item_id = parts[0]
    review_type = parts[1] if len(parts) > 1 else "day_7"

    if spaced_rep.mark_reviewed(item_id, review_type):
        await _send_long(
            update,
            f"✅ Marked review as complete! Great job revising! 💪",
        )
    else:
        await _send_long(
            update,
            "❌ Review item not found. Check `/review` for your queue.",
        )


async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /progress — show Phase 1 chapter progress."""
    if not _is_avneesh(update):
        return

    stats = obsidian_writer.get_phase1_progress()
    lines = ["📈 **Phase 1 Progress**:\n"]

    for subj, s in stats.items():
        bar_filled = int(s["hours_done"] / max(s["hours_required"], 1) * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(
            f"**{subj}**: {bar} {s['hours_done']:.0f}/{s['hours_required']}h\n"
            f"  ✅ {s['completed']} done | 🔄 {s['in_progress']} WIP | "
            f"⬜ {s['not_started']} remaining"
        )

    await _send_long(update, "\n\n".join(lines))


async def cmd_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /error — log a mistake.
    Format: /error <Subject> <Topic> <what went wrong>
    """
    if not _is_avneesh(update):
        return

    text = update.message.text.replace("/error", "").strip()

    if not text:
        await update.message.reply_text(
            "❌ **How to log an error**:\n"
            "`/error Physics NLM Forgot to resolve normal force in non-inertial frame`\n\n"
            "Format: `/error <Subject> <Topic> <description>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        await update.message.reply_text(
            "❌ Need subject, topic, and description.\n"
            "Example: `/error Physics NLM Forgot to resolve normal force`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    subject = parts[0].capitalize()
    topic = parts[1]
    mistake = parts[2]

    path = obsidian_writer.create_error_note(
        subject=subject,
        topic=topic,
        problem="(Logged via Telegram bot)",
        mistake=mistake,
        correct_solution="(To be filled during review)",
        takeaway="(To be filled during review)",
        error_type="Conceptual",
    )

    # Schedule spaced rep for the error
    err_id = path.stem.split("_")[0]  # e.g., "ERR-002"
    spaced_rep.add_error(err_id, topic, subject)

    await update.message.reply_text(
        f"✅ Error logged: **{err_id}** ({subject} — {topic})\n"
        f"📝 Saved to Obsidian: `{path.name}`\n"
        f"🔁 Review scheduled: Day 3, Day 7, Day 30\n\n"
        f"Open in Obsidian to fill in the full solution and takeaway!",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Natural Language Message Classifier & Handler ──────────────────────────

async def handle_natural_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Intelligently handles plain text and voice transcripts.
    Classifies between:
    1. Daily Study Recap / Evening Check-In -> master_orchestrator
    2. Academic JEE Question / Doubt -> doubt_solver
    3. General Conversation -> Gemini tutor
    """
    if not _is_avneesh(update):
        return

    text = update.message.text.strip()
    if not text:
        return

    # Check for keywords indicating study recap / evening check-in
    recap_keywords = ["studied", "hours", "hrs", "skipped", "missed", "questions", "solved", "pyq", "recap", "done today", "coaching was", "mistake"]
    is_likely_recap = any(k in text.lower() for k in recap_keywords)

    if is_likely_recap:
        await update.message.reply_text("⚡ Processing your study check-in & balancing backlog...")
        try:
            result = await master_orchestrator.process_evening_log(text)
            p = result.get("physics", 0)
            c = result.get("chemistry", 0)
            m = result.get("math", 0)
            total = result.get("total_day_hours", 0)
            summary = result.get("summary", "")

            msg = (
                f"✅ **Evening Study Check-In Logged!**\n\n"
                f"📊 **Hours Recorded**:\n"
                f"  ⚛️ Physics: `{p}h`\n"
                f"  🧪 Chemistry: `{c}h`\n"
                f"  📐 Mathematics: `{m}h`\n"
                f"  🔥 **Total Studied**: `{total} hours`\n\n"
                f"📋 **Executive Assessment**:\n{summary}\n\n"
                f"💾 _Synchronized with Master_State.json & Obsidian Daily Logs!_"
            )
            await _send_long(update, msg)
            return
        except Exception as e:
            logger.exception("Error in natural language evening check-in: %s", e)

    # Otherwise, check if it's an academic doubt or question
    await update.message.reply_text("🧠 Analyzing academic problem...")
    try:
        solution = await doubt_solver.solve_text(text)
        await _send_long(update, solution)
        await update.message.reply_text(
            "💡 Want me to log this in your Error Database? Reply with `/error <Subject> <Topic> <Mistake>`"
        )
    except Exception as e:
        logger.exception("Error solving text question: %s", e)
        await update.message.reply_text("⚠️ Could not process that message. Please try again.")


# ── Photo Handler ───────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos — treat as JEE doubt."""
    if not _is_avneesh(update):
        return

    await update.message.reply_text("📸 Analyzing your problem...")

    # Get the highest resolution photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    # Check for caption as additional context
    caption = update.message.caption or ""

    solution = await doubt_solver.solve_image(bytes(image_bytes), caption)
    await _send_long(update, solution)

    await update.message.reply_text(
        "💡 Got it wrong before? Log it with:\n"
        "`/error <Subject> <Topic> <what went wrong>`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Document Handler ────────────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded documents like schedule PDFs."""
    if not _is_avneesh(update):
        return

    doc = update.message.document
    caption = update.message.caption or ""
    
    if doc.mime_type == "application/pdf" and "/schedule" in caption:
        await update.message.reply_text("📥 Received schedule PDF! Parsing...")
        try:
            file = await context.bot.get_file(doc.file_id)
            pdf_bytes = await file.download_as_bytearray()
            
            parsed_json = await gemini_client.ask_with_file(
                bytes(pdf_bytes),
                "application/pdf",
                "Parse this coaching schedule PDF. Return ONLY raw JSON without markdown formatting.",
                system=gemini_client.SCHEDULE_PARSER_SYSTEM
            )
            
            # Clean markdown backticks if any
            clean_json = parsed_json.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:-3]
            elif clean_json.startswith("```"):
                clean_json = clean_json[3:-3]
            
            import json
            import os
            import obsidian_writer
            
            data = json.loads(clean_json.strip())
            
            os.makedirs("data", exist_ok=True)
            with open("data/aakash_schedule.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                
            obsidian_writer.update_schedule_note(data)
            
            await update.message.reply_text("✅ Schedule successfully parsed and saved to Obsidian!")
        except json.JSONDecodeError as e:
            logger.error("JSON parse error: %s\nOutput was: %s", e, parsed_json)
            await update.message.reply_text("❌ Failed to parse schedule. The AI did not return valid JSON.")
        except Exception as e:
            logger.exception("Failed to process PDF: %s", e)
            await update.message.reply_text(f"⚠️ Error processing PDF: {e}")



# ── Forwarded Message Handler (Schedule Parsing) ───────────────────────────

async def handle_forwarded(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle forwarded messages — try to parse as Aakash schedule."""
    if not _is_avneesh(update):
        return

    text = update.message.text or update.message.caption or ""

    if not text:
        return

    await update.message.reply_text("📅 Parsing your Aakash schedule...")

    try:
        parsed_json = await gemini_client.parse_schedule(text)

        # Clean up the response — strip markdown code fences if present
        cleaned = parsed_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```\w*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)

        parsed = json.loads(cleaned)

        # Save the schedule
        schedule_data = {
            "last_updated": date.today().isoformat(),
            "raw_text": text,
            "parsed": parsed,
        }
        schedule_path = config.DATA_DIR / "aakash_schedule.json"
        schedule_path.write_text(
            json.dumps(schedule_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Also update Obsidian
        days_info = parsed.get("days", {})
        table_rows = []
        for day, info in days_info.items():
            subj = info.get("subject", "—")
            topic = info.get("topic", "—")
            t = info.get("time", "—")
            table_rows.append(f"| {day} | {t} | {subj} | {topic} | From WhatsApp |")

        table = "\n".join(table_rows) if table_rows else "| — | — | — | — | — |"

        await update.message.reply_text(
            f"✅ **Schedule parsed and saved!**\n\n"
            f"Coaching days detected:\n" +
            "\n".join(
                f"  📚 {day}: {info.get('subject', '?')} — {info.get('topic', '?')}"
                for day, info in days_info.items()
            ) +
            "\n\nYour study plans will now adapt to this schedule!",
            parse_mode=ParseMode.MARKDOWN,
        )

    except (json.JSONDecodeError, Exception) as e:
        logger.exception("Failed to parse schedule")
        await update.message.reply_text(
            "⚠️ Couldn't parse that as a schedule. "
            "Try forwarding the exact WhatsApp message again.",
        )


# ── Scheduled Jobs ──────────────────────────────────────────────────────────

async def job_morning_plan(context: ContextTypes.DEFAULT_TYPE) -> None:
    """🌅 6:30 AM — Send today's study plan."""
    logger.info("Running morning plan job")
    plan = await scheduler.generate_daily_plan()
    obsidian_writer.create_daily_log(date.today(), plan)

    await context.bot.send_message(
        chat_id=config.AVNEESH_CHAT_ID,
        text=f"🌅 **Good morning Avneesh!**\n\n{plan}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def job_post_coaching(context: ContextTypes.DEFAULT_TYPE) -> None:
    """📚 3:00 PM — Post-coaching check-in (coaching days only)."""
    if date.today().weekday() not in config.COACHING_DAYS:
        return

    logger.info("Running post-coaching job")
    await context.bot.send_message(
        chat_id=config.AVNEESH_CHAT_ID,
        text=(
            "📚 **Back from Aakash?**\n\n"
            "Quick — what was covered today?\n"
            "Log it: `/done <Subject> <Topic> <hours>h`\n\n"
            "This helps me adjust your evening self-study plan!"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


async def job_revision_alert(context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔁 7:00 PM — Spaced repetition reminder."""
    logger.info("Running revision alert job")
    reviews = spaced_rep.get_due_reviews()

    if not reviews:
        return  # No reviews due, stay silent

    msg = spaced_rep.format_due_reviews()
    await context.bot.send_message(
        chat_id=config.AVNEESH_CHAT_ID,
        text=f"🔁 **Revision Alert!**\n\n{msg}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def job_night_log(context: ContextTypes.DEFAULT_TYPE) -> None:
    """🌙 10:30 PM — End of day log check."""
    logger.info("Running night log job")
    summary = await scheduler.generate_progress_summary()

    streak = scheduler.get_streak()
    streak_msg = f"🔥 Streak: **{streak} days**" if streak > 0 else ""

    await context.bot.send_message(
        chat_id=config.AVNEESH_CHAT_ID,
        text=(
            f"🌙 **End of Day Check**\n\n"
            f"{summary}\n\n"
            f"{streak_msg}\n\n"
            f"Missed anything? Log now with `/done`\n"
            f"Good night! 😴 Tomorrow we go harder. 💪"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


async def job_weekly_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """📊 Sunday 8:00 PM — Weekly analytics report."""
    if date.today().weekday() != 6:  # Only on Sundays
        return

    logger.info("Running weekly report job")
    report = await scheduler.generate_weekly_report()

    await context.bot.send_message(
        chat_id=config.AVNEESH_CHAT_ID,
        text=f"📊 **Weekly Report**\n\n{report}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot."""
    # ── Cloud Health Check Server (Render / Koyeb) ──────────────────────
    # Start immediately so cloud port checkers (Render) detect port 10000 in < 50ms
    port = int(os.getenv("PORT", "0"))
    if port > 0:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class HealthCheckHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-Length", "39")
                self.send_header("Connection", "close")
                self.end_headers()

            def do_GET(self):
                msg = b"JEE Buddy Bot is Alive & Running 24/7!\n"
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-Length", str(len(msg)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(msg)

            def log_message(self, format, *args):
                pass  # Suppress HTTP access logs to keep terminal clean

        class HealthCheckServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        def run_health_server():
            try:
                server = HealthCheckServer(("0.0.0.0", port), HealthCheckHandler)
                logger.info("Healthcheck HTTP server listening on 0.0.0.0:%d", port)
                server.serve_forever()
            except Exception as e:
                logger.exception("Healthcheck server error: %s", e)

        t = threading.Thread(target=run_health_server, daemon=True)
        t.start()

    # Test mode
    if "--test" in sys.argv:
        print("[TEST] Running config validation...")
        missing = config.validate()
        if missing:
            print(f"[FAIL] Missing config: {', '.join(missing)}")
            print("   Copy .env.example -> .env and fill in your values.")
            sys.exit(1)
        print("[OK] Config valid!")
        print(f"   Bot Token: {'*' * 10}...{config.TELEGRAM_BOT_TOKEN[-5:]}")
        print(f"   Gemini Key: {'*' * 10}...{config.GEMINI_API_KEY[-5:]}")
        print(f"   Chat ID: {config.AVNEESH_CHAT_ID}")
        print(f"   Vault: {config.OBSIDIAN_VAULT}")
        print(f"   Model: {config.GEMINI_MODEL}")
        print("[OK] All systems go! Run without --test to start the bot.")
        sys.exit(0)

    # Validate config
    missing = config.validate()
    if missing:
        logger.error("Missing config values: %s", ", ".join(missing))
        logger.error("Copy .env.example → .env and fill in your values.")
        sys.exit(1)

    logger.info("Starting JEE Buddy Bot polling engine...")

    def build_and_run():
        app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

        # Register command handlers
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("plan", cmd_plan))
        app.add_handler(CommandHandler("done", cmd_done))
        app.add_handler(CommandHandler("doubt", cmd_doubt))
        app.add_handler(CommandHandler("schedule", cmd_schedule))
        app.add_handler(CommandHandler("week", cmd_week))
        app.add_handler(CommandHandler("streak", cmd_streak))
        app.add_handler(CommandHandler("backlog", cmd_backlog))
        app.add_handler(CommandHandler("review", cmd_review))
        app.add_handler(CommandHandler("reviewed", cmd_reviewed))
        app.add_handler(CommandHandler("progress", cmd_progress))
        app.add_handler(CommandHandler("error", cmd_error))

        # Photo handler (for doubt solving via images)
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        # Document handler (for PDF schedules)
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

        # Forwarded message handler (for Aakash schedule parsing)
        app.add_handler(
            MessageHandler(filters.FORWARDED & filters.TEXT, handle_forwarded)
        )

        # Natural Language Text & Doubt Handler (plain text & voice transcripts)
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_text)
        )

        # ── Schedule daily jobs (IST = UTC+5:30) ────────────────────────
        jq = app.job_queue
        if jq is not None:
            jq.run_daily(job_morning_plan, time=time(1, 0))      # IST 6:30 AM
            jq.run_daily(job_post_coaching, time=time(9, 30))     # IST 3:00 PM
            jq.run_daily(job_revision_alert, time=time(13, 30))   # IST 7:00 PM
            jq.run_daily(job_night_log, time=time(17, 0))         # IST 10:30 PM
            jq.run_daily(job_weekly_report, time=time(14, 30))    # IST 8:00 PM Sun
            logger.info("Scheduled jobs registered (IST times via UTC offsets)")

        # Start polling with clean error handling
        logger.info("Bot is active and polling Telegram...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

    while True:
        try:
            build_and_run()
        except Exception as e:
            logger.exception("Error during bot polling cycle: %s. Reconnecting in 5s...", e)
            import time as _sys_time
            _sys_time.sleep(5)


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.critical("Fatal crash in bot.py: %s", e, exc_info=True)
        sys.exit(1)
