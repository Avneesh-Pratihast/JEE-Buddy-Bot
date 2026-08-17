"""
Doubt Solver — handles text and image-based JEE problem solving.
Uses Gemini for inference and optionally logs errors to Obsidian.
"""

from __future__ import annotations

import logging

import gemini_client

logger = logging.getLogger(__name__)


async def solve_text(question: str) -> str:
    """Solve a text-based JEE doubt using Gemini with Dual-Method approach."""
    prompt = (
        "Solve the following JEE problem using the TWO-TIER approach:\n"
        "1. **Approach 1: Standard Method** (Rigorous step-by-step textbook derivation)\n"
        "2. **Approach 2: JEE Advanced Topper Shortcut** (Fastest calculation trick, boundary inspection, symmetry, dimensional check, or ICR trick)\n"
        "3. **Key Takeaway & Exam Strategy**\n\n"
        f"**Problem**: {question}"
    )
    return await gemini_client.ask(prompt)


async def solve_image(image_bytes: bytes, context: str = "") -> str:
    """Solve a problem from a photo using Gemini multimodal with Dual-Method approach."""
    prompt = (
        "Solve this JEE problem using the TWO-TIER approach:\n"
        "1. **Approach 1: Standard Method** (Rigorous step-by-step textbook derivation)\n"
        "2. **Approach 2: JEE Advanced Topper Shortcut** (Fastest calculation trick, boundary inspection, symmetry, dimensional check, or ICR trick)\n"
        "3. **Key Takeaway & Exam Strategy**"
    )
    if context:
        prompt += f"\n\nAdditional context from student: {context}"

    return await gemini_client.ask_with_image(image_bytes, prompt)


async def explain_concept(concept: str) -> str:
    """Explain a JEE concept in depth."""
    prompt = (
        f"Explain the following concept at JEE Advanced level. "
        f"Include: definition, key formulas, common traps, "
        f"and 1-2 illustrative examples.\n\n"
        f"**Concept**: {concept}"
    )
    return await gemini_client.ask(prompt)


async def compare_concepts(concept_a: str, concept_b: str) -> str:
    """Compare two JEE concepts side by side."""
    prompt = (
        f"Compare these two concepts at JEE Advanced level:\n"
        f"A: {concept_a}\n"
        f"B: {concept_b}\n\n"
        f"Format as a comparison table with: Definition, Key Formula, "
        f"When to Use, Common Mistakes, JEE Weightage."
    )
    return await gemini_client.ask(prompt)
