from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.evaluator import evaluate_project
from app.models import CATEGORIES, Evaluation, Hackathon, Project

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]
DEFAULT_MANUAL_HACKATHON_NAME = "Manual projects"


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
    scraper_skipped = 0

    async def scraper_status_callback(state: str, payload: dict[str, Any]) -> None:
        nonlocal scraper_skipped
        scraper_skipped = max(scraper_skipped, int(payload.get("skipped") or 0))
        await _publish(
            status_callback,
            state,
            {"job_id": job_id, **payload},
        )

    async with AsyncSessionLocal() as session:
        hackathon_id = await _upsert_devpost_hackathon(session)
        await session.commit()
        deleted_project_names = await _deleted_project_names(session, hackathon_id)

    scraped_projects = await asyncio.to_thread(
        _run_scraper_sync,
        settings.max_projects,
        scraper_status_callback,
        deleted_project_names,
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
    skipped = scraper_skipped
    async with AsyncSessionLocal() as session:
        deleted_project_names = await _deleted_project_names(session, hackathon_id)

        for scraped in scraped_projects:
            project_name = scraped["project_name"]
            if _project_name_key(project_name) in deleted_project_names:
                skipped += 1
                await _publish(
                    status_callback,
                    "running",
                    {
                        "job_id": job_id,
                        "stage": "saving",
                        "message": f"Skipping deleted project {project_name}.",
                        "project_name": project_name,
                        "evaluated": evaluated,
                        "skipped": skipped,
                        "total": len(scraped_projects),
                    },
                )
                continue

            await _publish(
                status_callback,
                "running",
                {
                    "job_id": job_id,
                    "stage": "saving",
                    "message": f"Saving project {project_name} to the database.",
                    "project_name": project_name,
                    "evaluated": evaluated,
                    "skipped": skipped,
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
                    "message": f"Evaluating {project_name} with the LLM.",
                    "project_name": project_name,
                    "evaluated": evaluated,
                    "skipped": skipped,
                    "total": len(scraped_projects),
                },
            )
            evaluation = await evaluate_project(
                project_name,
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
                    "message": f"Stored evaluation for {project_name}.",
                    "project_name": project_name,
                    "evaluated": evaluated,
                    "skipped": skipped,
                    "total": len(scraped_projects),
                },
            )

    result = {
        "job_id": job_id,
        "scraped": len(scraped_projects),
        "evaluated": evaluated,
        "skipped": skipped,
    }
    await _publish(
        status_callback,
        "completed",
        {
            **result,
            "stage": "completed",
            "message": f"Pipeline completed: {evaluated} evaluations stored, {skipped} deleted projects skipped.",
        },
    )
    return result


def _run_scraper_sync(
    max_projects: int,
    status_callback: StatusCallback | None,
    skip_project_names: set[str],
) -> list[dict[str, Any]]:
    from app.scraper import scrape_devpost_projects

    return asyncio.run(
        scrape_devpost_projects(
            max_projects=max_projects,
            status_callback=status_callback,
            skip_project_names=skip_project_names,
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


async def _upsert_manual_hackathon(session: AsyncSession, hackathon_name: str) -> uuid.UUID:
    name = hackathon_name.strip() or DEFAULT_MANUAL_HACKATHON_NAME
    statement = (
        insert(Hackathon)
        .values(
            name=name,
            platform="Manual",
            url=_manual_hackathon_url(name),
        )
        .on_conflict_do_update(
            index_elements=[Hackathon.url],
            set_={
                "name": name,
                "platform": "Manual",
            },
        )
        .returning(Hackathon.id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


def _manual_hackathon_url(hackathon_name: str) -> str:
    return f"manual://{quote(hackathon_name.strip().casefold(), safe='')}"


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


async def _deleted_project_names(session: AsyncSession, hackathon_id: uuid.UUID) -> set[str]:
    statement = select(Project.project_name).where(
        Project.hackathon_id == hackathon_id,
        Project.deleted.is_(True),
    )
    rows = (await session.execute(statement)).scalars()
    return {_project_name_key(project_name) for project_name in rows}


def _project_name_key(project_name: str) -> str:
    return project_name.strip().casefold()


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


async def create_manual_project(session: AsyncSession, project: dict[str, Any]) -> dict[str, Any]:
    project_name = str(project["project_name"]).strip()
    description = str(project["description"]).strip()
    hackathon_name = str(project.get("hackathon_name") or DEFAULT_MANUAL_HACKATHON_NAME).strip()
    category = str(project.get("category") or "other").strip().lower()
    if category not in CATEGORIES:
        category = "other"

    hackathon_id = await _upsert_manual_hackathon(session, hackathon_name)
    project_id = await _upsert_project(
        session,
        hackathon_id,
        {
            "project_name": project_name,
            "description": description,
            "tech_stack": project.get("tech_stack") or [],
            "category": category,
            "github_url": project.get("github_url"),
            "demo_url": project.get("demo_url"),
        },
    )
    await session.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(deleted=False, scraped_at=func.now())
    )

    evaluation = await evaluate_project(project_name, description, category)
    await _upsert_evaluation(session, project_id, evaluation)
    if evaluation.get("category") and category in {"", "other", None}:
        await session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(category=evaluation["category"], scraped_at=func.now())
        )

    return await get_project(session, project_id)


async def list_projects(session: AsyncSession) -> list[dict[str, Any]]:
    statement = (
        select(Project, Evaluation, Hackathon)
        .join(Hackathon, Hackathon.id == Project.hackathon_id)
        .outerjoin(Evaluation, Evaluation.project_id == Project.id)
        .where(Project.deleted.is_(False))
        .order_by(Project.scraped_at.desc(), Project.project_name.asc())
    )
    rows = (await session.execute(statement)).all()
    return [_serialize_project(project, evaluation, hackathon) for project, evaluation, hackathon in rows]


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    statement = (
        select(Project, Evaluation, Hackathon)
        .join(Hackathon, Hackathon.id == Project.hackathon_id)
        .outerjoin(Evaluation, Evaluation.project_id == Project.id)
        .where(Project.id == project_id)
    )
    row = (await session.execute(statement)).one()
    project, evaluation, hackathon = row
    return _serialize_project(project, evaluation, hackathon)


async def mark_project_deleted(session: AsyncSession, project_id: uuid.UUID) -> bool:
    statement = (
        update(Project)
        .where(Project.id == project_id)
        .values(deleted=True, scraped_at=func.now())
        .returning(Project.id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


def _serialize_project(
    project: Project,
    evaluation: Evaluation | None,
    hackathon: Hackathon | None = None,
) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "hackathon_id": str(project.hackathon_id),
        "hackathon_name": hackathon.name if hackathon is not None else None,
        "project_name": project.project_name,
        "description": project.description,
        "tech_stack": project.tech_stack,
        "category": project.category,
        "github_url": project.github_url,
        "demo_url": project.demo_url,
        "deleted": project.deleted,
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
