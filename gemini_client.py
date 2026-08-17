"""
Gemini API client — wraps google-genai for text and image inference.
Uses the free tier of Gemini Flash by default.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

import config

logger = logging.getLogger(__name__)

# ── Multi-Key Client Pool ──────────────────────────────────────────────────
_clients: list[genai.Client] = []
_key_index: int = 0


def _get_clients() -> list[genai.Client]:
    global _clients
    if not _clients:
        keys = config.GEMINI_API_KEYS
        for k in keys:
            if k:
                _clients.append(genai.Client(api_key=k))
        if not _clients:
            _clients.append(genai.Client(api_key=config.GEMINI_API_KEY))
    return _clients


def _next_client() -> genai.Client:
    """Round-robin through available API keys."""
    global _key_index
    clients = _get_clients()
    client = clients[_key_index % len(clients)]
    _key_index = (_key_index + 1) % len(clients)
    return client


# ── Optimal Model Fallback Hierarchy ───────────────────────────────────────
FALLBACK_MODELS = [
    "gemini-3.7-flash",       # Tier 1: Highest intelligence & deep reasoning
    "gemini-3.6-flash",       # Tier 2: High capability & speed
    "gemini-3.5-flash",       # Tier 3: Production stable & fast
    "gemini-3.5-flash-lite",  # Tier 4: Guaranteed fallback under extreme load
]

# ── System Prompts ─────────────────────────────────────────────────────────

JEE_SYSTEM = (
    "You are a JEE Advanced expert tutor and doubt solver for Avneesh, targeting Top 100 AIR in JEE Advanced 2028.\n"
    "CRITICAL FORMAT FOR EVERY PROBLEM SOLVED:\n"
    "For EVERY physics, chemistry, or math doubt, you MUST provide a TWO-TIER SOLUTION:\n\n"
    "### 📖 Approach 1: Standard / Systematic Method\n"
    "- Complete, rigorous step-by-step textbook derivation.\n"
    "- Full equations, free-body diagram descriptions, electron arrow mechanisms, or algebraic proofs.\n"
    "- Use proper LaTeX: $...$ inline, $$...$$ display.\n\n"
    "### ⚡ Approach 2: JEE Advanced Topper Shortcut (Fastest Method)\n"
    "- The sub-60-second trick that Top 100 rankers use: symmetry, extreme/boundary values ($0, \\infty, 1$), dimensional elimination, virtual work, ICR (Instantaneous Centre of Rotation), conservation laws, graphical insight, or substitution tricks.\n"
    "- Highlight exactly HOW MUCH TIME this saves in the exam hall.\n\n"
    "### 💡 Key Takeaway & Exam Strategy\n"
    "- 1-2 sentence core concept takeaway and when to deploy Approach 1 vs Approach 2.\n"
    "- Reference relevant JEE Advanced PYQs (Year + Paper) if similar."
)

PLANNER_SYSTEM = (
    "You are a JEE study planner for Avneesh. Generate focused, actionable "
    "daily study plans. "
    "Daily Routine Context:\n"
    "- Morning: Workout (8:30 AM – 10:00 AM)\n"
    "- Mid-day: Aakash Coaching (11:00 AM – 3:30 PM)\n"
    "- Post-coaching: Power nap & refresh (3:30 PM – 4:30 PM)\n"
    "- Self-Study Window: Starts strictly at 4:30 PM (5 hours on coaching days, 8+ hours on Sundays/holidays).\n"
    "Be specific about topics, question counts (○/△/★), and time slots. Keep output concise."
)

SCHEDULE_PARSER_SYSTEM = (
    "You are a schedule parser for Avneesh, a Class 11 JEE student. "
    "His batch is FR01 (Morning) (XI). Sometimes there are combined classes "
    "or compulsory sessions with FR02 (Evening) (XI) in Room 5. "
    "CRITICAL RULES:\n"
    "1. Completely IGNORE all doubt sessions (e.g. ECAPS doubts, subject doubt sessions).\n"
    "2. Extract regular lectures, tests (PT, AIATS), and compulsory lectures (e.g. IOQM) for FR01 and combined FR01/FR02.\n"
    "3. Return valid JSON with this schema:\n"
    '{"week_start": "YYYY-MM-DD", "days": {"Monday": {"classes": [{"time": "...", "subject": "...", "faculty": "...", "room": "..."}], "notes": "..."}, ...}}\n'
    "Only output valid JSON."
)


async def ask(prompt: str, *, system: str | None = JEE_SYSTEM) -> str:
    """Send a text prompt to Gemini with multi-key rotation and multi-model fallback."""
    clients = _get_clients()

    for client in clients:
        for model_name in FALLBACK_MODELS:
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                    ) if system else None,
                )
                if response.text:
                    return response.text
            except Exception as e:
                logger.warning("Model %s with key %s failed: %s. Trying fallback...", model_name, client, e)

    return "⚠️ High traffic on AI servers. Please retry in a moment."


async def ask_with_image(
    image_bytes: bytes,
    prompt: str = "Solve this JEE problem step by step.",
    *,
    system: str | None = JEE_SYSTEM,
) -> str:
    """Send an image + text prompt to Gemini with multi-key rotation and multi-model fallback."""
    clients = _get_clients()
    img = Image.open(BytesIO(image_bytes))

    for client in clients:
        for model_name in FALLBACK_MODELS:
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=[prompt, img],
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                    ) if system else None,
                )
                if response.text:
                    return response.text
            except Exception as e:
                logger.warning("Vision model %s failed: %s. Trying fallback...", model_name, e)

    return "⚠️ Could not analyze image. Try a clearer photo."


async def ask_with_file(
    file_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    system: str | None = None,
) -> str:
    """Send a file (like PDF) + text prompt to Gemini."""
    clients = _get_clients()
    
    # Use google.genai types
    part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    for client in clients:
        for model_name in FALLBACK_MODELS:
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=[part, prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                    ) if system else None,
                )
                if response.text:
                    return response.text
            except Exception as e:
                logger.warning("File model %s failed: %s. Trying fallback...", model_name, e)

    return "⚠️ Could not analyze file."


async def parse_schedule(raw_text: str) -> str:
    """Parse an Aakash WhatsApp schedule message into structured JSON."""
    return await ask(
        f"Parse this coaching schedule:\n\n{raw_text}",
        system=SCHEDULE_PARSER_SYSTEM,
    )


async def generate_plan(context: str) -> str:
    """Generate a daily study plan given context about progress and schedule."""
    return await ask(context, system=PLANNER_SYSTEM)


async def generate_summary(context: str) -> str:
    """Generate an end-of-day or weekly summary."""
    return await ask(
        context,
        system=(
            "You are a JEE prep analytics assistant. Summarise study progress "
            "concisely with actionable insights. Use emojis sparingly. "
            "Highlight what's behind schedule and what needs attention."
        ),
    )
