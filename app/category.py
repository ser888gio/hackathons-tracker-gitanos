from __future__ import annotations

from collections.abc import Iterable

from app.models import CATEGORIES


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "defense": (
        "defense",
        "security",
        "cyber",
        "military",
        "emergency",
        "disaster",
        "safety",
        "surveillance",
        "threat",
    ),
    "health": (
        "health",
        "healthcare",
        "medical",
        "medicine",
        "mental health",
        "wellness",
        "patient",
        "clinical",
        "hospital",
    ),
    "education": (
        "education",
        "learning",
        "school",
        "student",
        "teacher",
        "classroom",
        "course",
        "edtech",
    ),
    "environment": (
        "environment",
        "climate",
        "sustainability",
        "sustainable",
        "carbon",
        "recycling",
        "energy",
        "water",
        "agriculture",
    ),
    "finance": (
        "finance",
        "fintech",
        "banking",
        "payment",
        "payments",
        "crypto",
        "trading",
        "investment",
        "insurance",
    ),
    "social": (
        "social",
        "community",
        "civic",
        "accessibility",
        "communication",
        "chat",
        "network",
        "nonprofit",
    ),
    "productivity": (
        "productivity",
        "workflow",
        "automation",
        "planner",
        "calendar",
        "task",
        "notes",
        "document",
        "collaboration",
    ),
}


def normalize_category(tags: Iterable[str] | None, description: str = "") -> str:
    haystack = " ".join([*(tags or []), description]).lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword in haystack)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    best_category = max(scores, key=scores.get)
    if scores[best_category] == 0:
        return "other"
    return best_category if best_category in CATEGORIES else "other"
