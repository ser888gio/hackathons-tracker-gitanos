from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.evaluator import evaluate_project
from app.models import Evaluation, Hackathon, Project
from app.scraper import scrape_devpost_projects

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


async def run_pipeline(
    job_id: str | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    await _publish(
        status_callback,
        "running",
        {
            "job_id": job_id,
            "stage": "scraping",
            "message": "Pipeline started. Scraping Devpost first.",
        },
    )
    scraper_status_callback = lambda state, payload: _publish(
        status_callback,
        state,
        {"job_id": job_id, **payload},
    )
    scraped_projects = await asyncio.to_thread(
        _run_scraper_sync,
        settings.max_projects,
        scraper_status_callback,
    )
    await _publish(
        status_callback,
        "running",
        {
            "job_id": job_id,
            "stage": "saving",
            "message": f"Scraping finished with {len(scraped_projects)} projects. Saving and evaluating next.",
            "scraped": len(scraped_projects),
        },
    )

    evaluated = 0
    async with AsyncSessionLocal() as session:
        hackathon_id = await _upsert_devpost_hackathon(session)
        await session.commit()

        for scraped in scraped_projects:
            await _publish(
                status_callback,
                "running",
                {
                    "job_id": job_id,
                    "stage": "saving",
                    "message": f"Saving project {scraped['project_name']} to the database.",
                    "project_name": scraped["project_name"],
                    "evaluated": evaluated,
                    "total": len(scraped_projects),
                },
            )
            project_id = await _upsert_project(session, hackathon_id, scraped)
            await session.commit()

            await _publish(
                status_callback,
                "running",
                {
                    "job_id": job_id,
                    "stage": "evaluating",
                    "message": f"Evaluating {scraped['project_name']} with the LLM.",
                    "project_name": scraped["project_name"],
                    "evaluated": evaluated,
                    "total": len(scraped_projects),
                },
            )
            evaluation = await evaluate_project(
                scraped["project_name"],
                scraped["description"],
                scraped.get("category", "other"),
            )
            await _upsert_evaluation(session, project_id, evaluation)
            if evaluation.get("category") and scraped.get("category") in {"", "other", None}:
                await session.execute(
                    update(Project)
                    .where(Project.id == project_id)
                    .values(category=evaluation["category"], scraped_at=func.now())
                )
            await session.commit()
            evaluated += 1
            await _publish(
                status_callback,
                "running",
                {
                    "job_id": job_id,
                    "stage": "evaluating",
                    "message": f"Stored evaluation for {scraped['project_name']}.",
                    "project_name": scraped["project_name"],
                    "evaluated": evaluated,
                    "total": len(scraped_projects),
                },
            )

    result = {
        "job_id": job_id,
        "scraped": len(scraped_projects),
        "evaluated": evaluated,
    }
    await _publish(
        status_callback,
        "completed",
        {
            **result,
            "stage": "completed",
            "message": f"Pipeline completed: {evaluated} evaluations stored.",
        },
    )
    return result


def _run_scraper_sync(
    max_projects: int,
    status_callback: StatusCallback | None,
) -> list[dict[str, Any]]:
    return asyncio.run(
        scrape_devpost_projects(
            max_projects=max_projects,
            status_callback=status_callback,
        )
    )


async def _publish(
    status_callback: StatusCallback | None,
    state: str,
    payload: dict[str, Any],
) -> None:
    if status_callback is None:
        return
    result = status_callback(state, payload)
    if result is not None:
        await result


async def _upsert_devpost_hackathon(session: AsyncSession) -> uuid.UUID:
    statement = (
        insert(Hackathon)
        .values(
            name="Devpost winning projects with videos",
            platform="Devpost",
            url=settings.devpost_search_url,
        )
        .on_conflict_do_update(
            index_elements=[Hackathon.url],
            set_={
                "name": "Devpost winning projects with videos",
                "platform": "Devpost",
            },
        )
        .returning(Hackathon.id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def _upsert_project(
    session: AsyncSession,
    hackathon_id: uuid.UUID,
    scraped: dict[str, Any],
) -> uuid.UUID:
    statement = (
        insert(Project)
        .values(
            hackathon_id=hackathon_id,
            project_name=scraped["project_name"],
            description=scraped["description"],
            tech_stack=scraped.get("tech_stack") or [],
            category=scraped.get("category") or "other",
            github_url=scraped.get("github_url"),
            demo_url=scraped.get("demo_url"),
            scraped_at=func.now(),
        )
        .on_conflict_do_update(
            constraint="uq_projects_hackathon_project_name",
            set_={
                "description": scraped["description"],
                "tech_stack": scraped.get("tech_stack") or [],
                "category": scraped.get("category") or "other",
                "github_url": scraped.get("github_url"),
                "demo_url": scraped.get("demo_url"),
                "scraped_at": func.now(),
            },
        )
        .returning(Project.id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def _upsert_evaluation(
    session: AsyncSession,
    project_id: uuid.UUID,
    evaluation: dict[str, Any],
) -> uuid.UUID:
    statement = (
        insert(Evaluation)
        .values(
            project_id=project_id,
            rating=evaluation["rating"],
            feedback_pros=evaluation["feedback_pros"],
            feedback_improvements=evaluation["feedback_improvements"],
        )
        .on_conflict_do_update(
            constraint="uq_evaluations_project_id",
            set_={
                "rating": evaluation["rating"],
                "feedback_pros": evaluation["feedback_pros"],
                "feedback_improvements": evaluation["feedback_improvements"],
            },
        )
        .returning(Evaluation.id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def list_projects(session: AsyncSession) -> list[dict[str, Any]]:
    statement = (
        select(Project, Evaluation)
        .outerjoin(Evaluation, Evaluation.project_id == Project.id)
        .order_by(Project.scraped_at.desc(), Project.project_name.asc())
    )
    rows = (await session.execute(statement)).all()
    return [_serialize_project(project, evaluation) for project, evaluation in rows]


def _serialize_project(project: Project, evaluation: Evaluation | None) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "hackathon_id": str(project.hackathon_id),
        "project_name": project.project_name,
        "description": project.description,
        "tech_stack": project.tech_stack,
        "category": project.category,
        "github_url": project.github_url,
        "demo_url": project.demo_url,
        "scraped_at": project.scraped_at.isoformat() if project.scraped_at else None,
        "evaluation": None
        if evaluation is None
        else {
            "id": str(evaluation.id),
            "rating": evaluation.rating,
            "feedback_pros": evaluation.feedback_pros,
            "feedback_improvements": evaluation.feedback_improvements,
        },
    }
