from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session, init_db
from app.models import CATEGORIES
from app.pipeline import create_manual_project, list_projects, mark_project_deleted, run_pipeline

jobs: dict[str, dict[str, Any]] = {}


class ManualProjectRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=255)
    hackathon_name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    category: str = "other"
    tech_stack: list[str] = Field(default_factory=list)
    project_url: str | None = None
    github_url: str | None = None
    demo_url: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Hackathons Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(
        "app/static/index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/add", include_in_schema=False)
async def add_project_frontend() -> FileResponse:
    return FileResponse(
        "app/static/add.html",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/trigger-pipeline")
async def trigger_pipeline() -> JSONResponse:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    jobs[job_id] = {
        "status": "accepted",
        "stage": "queued",
        "message": "Pipeline queued.",
        "scraped": 0,
        "max_projects": settings.max_projects,
        "created_at": now,
        "updated_at": now,
        "messages": [{"at": now, "message": "Pipeline queued."}],
    }
    asyncio.create_task(_run_pipeline_job(job_id))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        headers={"Cache-Control": "no-store"},
        content={
            "job_id": job_id,
            "status": "accepted",
            "scraped": 0,
            "max_projects": settings.max_projects,
            "status_url": f"/jobs/{job_id}",
        },
    )


@app.get("/config")
async def get_config(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return {"max_projects": settings.max_projects}


@app.get("/projects")
async def get_projects(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await list_projects(session)


@app.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ManualProjectRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = _manual_project_payload(project)
    created_project = await create_manual_project(session, payload)
    await session.commit()
    return created_project


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    deleted = await mark_project_deleted(session, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found.")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _manual_project_payload(project: ManualProjectRequest) -> dict[str, Any]:
    project_name = project.project_name.strip()
    hackathon_name = project.hackathon_name.strip()
    description = project.description.strip()
    category = project.category.strip().lower() or "other"
    if not project_name:
        raise HTTPException(status_code=422, detail="Project name is required.")
    if not hackathon_name:
        raise HTTPException(status_code=422, detail="Hackathon name is required.")
    if not description:
        raise HTTPException(status_code=422, detail="Description is required.")
    if category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Category is not supported.")

    return {
        "project_name": project_name,
        "hackathon_name": hackathon_name,
        "description": description,
        "category": category,
        "tech_stack": [tag.strip() for tag in project.tech_stack if tag.strip()],
        "github_url": _optional_string(project.github_url),
        "demo_url": _optional_string(project.project_url) or _optional_string(project.demo_url),
    }


def _optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


@app.get("/jobs/latest")
async def latest_job(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    if not jobs:
        raise HTTPException(status_code=404, detail="No pipeline jobs have been started.")
    latest_job_id = next(reversed(jobs))
    return {"job_id": latest_job_id, **jobs[latest_job_id]}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Pipeline job not found.")
    return {"job_id": job_id, **job}


async def _run_pipeline_job(job_id: str) -> None:
    async def update_status(state: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        current = jobs.get(job_id, {})
        messages = list(current.get("messages", []))
        message = str(payload.get("message") or "").strip()
        if message:
            messages.append({"at": now, "message": message})
            messages = messages[-80:]
        jobs[job_id] = {
            **current,
            **payload,
            "status": state,
            "updated_at": now,
            "message": message or current.get("message"),
            "messages": messages,
        }

    try:
        await update_status(
            "running",
            {
                "job_id": job_id,
                "stage": "starting",
                "message": "Background task started.",
            },
        )
        await run_pipeline(job_id=job_id, status_callback=update_status)
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        current = jobs.get(job_id, {})
        messages = list(current.get("messages", []))
        message = f"Pipeline failed: {exc}"
        messages.append({"at": now, "message": message})
        jobs[job_id] = {
            **current,
            "status": "failed",
            "stage": "failed",
            "message": message,
            "messages": messages[-80:],
            "updated_at": now,
            "error": str(exc),
        }
