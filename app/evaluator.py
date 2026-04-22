from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.models import CATEGORIES


EVALUATION_SYSTEM_PROMPT = """You are a senior engineer, product-minded hackathon judge, and tough jury member.
Judge like the project is competing for prizes. Reward boldness, usefulness, real implementation, and memorable execution. Penalize vague claims, buzzwords, copycat ideas, weak problem framing, unrealistic moonshots, and demos that sound like slides instead of software.
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

Use this judging rubric internally. Do not output the subtotal scores.

1. Problem Statement, Relevance & Potential Impact (18%):
- Does the team understand a real problem and user pain point?
- Is this solving something meaningful, or is it technology for technology's sake?
- Could this make a positive impact on users, a community, an organization, or a market?
- A basic but highly relevant solution can beat a flashy but pointless one.

2. Quality of the Idea, Innovation & Creativity (18%):
- Is there a fresh angle, surprising combination of technologies, or courageous idea?
- Does it make a judge think "why didn't I think of that?"
- Copycat ideas, generic AI wrappers, and template apps should score poorly here.

3. Technological Implementation (22%):
- Is there evidence that the team actually built and deployed something working?
- Did they use the required tools and technologies well?
- Did they push beyond a mockup or pitch deck with APIs, AI models, hardware, data, integrations, or meaningful engineering?
- Is the project technically sophisticated relative to the time limit, or is it mostly glue/template work?
- Duct tape is acceptable in a hackathon, but there must be real execution.

4. Ease of Use, User Experience & Design (15%):
- Is the flow understandable and usable by real people?
- Does the interface, interaction model, or pitch make the solution easy to grasp?
- Can the project be explained and used in one or two sentences?
- Is the design clean, functional, professional, and presented well?
- A working hack that confuses users should lose points.

5. Demonstration & Communication (10%):
- Does the submission clearly explain the project, features, benefits, and why it matters?
- Is there evidence of a concise demo, walkthrough, or pitch that would help judges understand the value quickly?
- If no demo quality is described, do not invent it; score this category conservatively.

6. Feasibility, Scalability & Business Value (12%):
- Could this realistically grow with more time and resources?
- Is there a path to adoption, impact, revenue, operational use, or becoming a stepping stone to something bigger?
- Balance ambitious moonshots against practical execution.

7. Wow Factor (5%):
- Is there a goosebump moment, memorable spark, or judging-room buzz?
- Would judges and other hackers talk about it afterward?
- Reward surprising elegance, mind-bending AI use, unusual hustle, or a bold demo that pushes the room forward.

Harsh rating calibration:
- 1-2: incoherent, irrelevant, barely a concept, or no meaningful implementation.
- 3-4: weak prototype, unclear user need, copycat idea, poor feasibility, or mostly presentation.
- 5: average hackathon submission; some value, but ordinary or shallow.
- 6: decent and plausible, but missing strong innovation, polish, or technical proof.
- 7: strong project with clear problem fit and working execution, but not prize-level.
- 8: standout project with strong evidence across most criteria and a real spark.
- 9: winner-contender with excellent execution, originality, relevance, feasibility, and wow factor.
- 10: rare, unforgettable hackathon project that feels special and complete despite time limits.

Calibration rules:
- Default to 5 or 6 for reasonable working projects. Do not drift upward out of politeness.
- Give 8+ only when the description proves strong implementation, real relevance, creativity, and wow factor.
- Give 9+ only when it could credibly win a competitive hackathon.
- If evidence is missing, assume it is unproven and score conservatively.
- Reward courageous, fresh attempts even if imperfect, but do not excuse lack of execution.
- Penalize vague descriptions, missing demos, thin wrappers around APIs, generic chatbots, unclear users, unrealistic claims, and no path to impact.
- feedback_pros should cite the strongest rubric categories actually supported by the description.
- feedback_improvements should be direct and critical, naming what would stop this from winning.

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
