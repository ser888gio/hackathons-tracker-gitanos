from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.models import CATEGORIES


EVALUATION_SYSTEM_PROMPT = """You are a senior engineer and unforgiving hackathon judge.
Be skeptical, concrete, and brutally honest. Do not reward effort, polish, buzzwords, or a good cause unless the project shows real execution, technical depth, originality, and user value.
Respond only with a valid JSON object. Do not include markdown, comments, prose, or a preamble."""


def _evaluation_prompt(project_name: str, description: str, category: str) -> str:
    category_instruction = ""
    if not category or category == "other":
        category_instruction = (
            'Because "category" is empty or "other", infer the most fitting canonical category '
            "from this list and include it as a category field in the JSON response: "
            f"{', '.join(CATEGORIES)}."
        )

    return f"""
Evaluate this hackathon project.

Project name: {project_name}
Category: {category or "other"}
Description:
{description}

Use this harsh rating scale:
- 1-2: barely a concept, broken, incoherent, or no meaningful implementation.
- 3-4: simple demo with major gaps, derivative idea, weak execution, or unclear usefulness.
- 5-6: average hackathon project; functional but ordinary, shallow, incomplete, or mostly wrapper/glue work.
- 7: genuinely solid; useful and implemented well, but still has clear limitations or little novelty.
- 8: unusually strong; convincing execution, clear value, and some technical or product distinction.
- 9: exceptional; production-adjacent, original, technically impressive, and broadly useful.
- 10: rare winner-level project with outstanding originality, execution, polish, and impact.

Calibration rules:
- The default score for a reasonable working project is 5 or 6, not 8.
- Do not give 8+ unless the description gives explicit evidence of standout implementation and impact.
- Penalize vague descriptions, missing demos, thin wrappers around APIs, generic AI chatbots, unclear users, missing validation, and unfinished workflows.
- If evidence is limited, score conservatively and mention the uncertainty in feedback_improvements.
- feedback_pros should identify only real strengths proven by the description.
- feedback_improvements should be direct and critical, naming what would keep this from winning.

Return exactly this JSON structure:
{{
  "rating": <integer 1-10>,
  "feedback_pros": "<string>",
  "feedback_improvements": "<string>"
}}

{category_instruction}
""".strip()


async def evaluate_project(
    project_name: str,
    description: str,
    category: str,
) -> dict[str, Any]:
    provider = _resolve_provider()
    prompt = _evaluation_prompt(project_name, description, category)
    if provider == "openai":
        raw_text = await _evaluate_with_openai(prompt)
    elif provider == "gemini":
        raw_text = await _evaluate_with_gemini(prompt)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
    return _parse_evaluation(raw_text)


def _resolve_provider() -> str:
    if settings.llm_provider in {"openai", "gemini"}:
        return settings.llm_provider
    if settings.openai_api_key:
        return "openai"
    if settings.gemini_api_key:
        return "gemini"
    raise RuntimeError("Set OPENAI_API_KEY or GEMINI_API_KEY before running evaluations.")


async def _evaluate_with_openai(prompt: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    completion = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI returned an empty evaluation response.")
    return content


async def _evaluate_with_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=f"{EVALUATION_SYSTEM_PROMPT}\n\n{prompt}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty evaluation response.")
    return response.text


def _parse_evaluation(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    data = json.loads(cleaned)
    rating = int(data["rating"])
    if rating < 1 or rating > 10:
        raise ValueError(f"rating must be between 1 and 10, got {rating}")

    parsed: dict[str, Any] = {
        "rating": rating,
        "feedback_pros": str(data["feedback_pros"]).strip(),
        "feedback_improvements": str(data["feedback_improvements"]).strip(),
    }
    category = str(data.get("category") or "").strip().lower()
    if category:
        parsed["category"] = category if category in CATEGORIES else "other"
    return parsed
