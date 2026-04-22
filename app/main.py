from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, init_db
from app.pipeline import list_projects, run_pipeline

jobs: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Hackathons Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/trigger-pipeline")
async def trigger_pipeline() -> JSONResponse:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    jobs[job_id] = {
        "status": "accepted",
        "stage": "queued",
        "message": "Pipeline queued.",
        "created_at": now,
        "updated_at": now,
        "messages": [{"at": now, "message": "Pipeline queued."}],
    }
    asyncio.create_task(_run_pipeline_job(job_id))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job_id, "status": "accepted"},
    )


@app.get("/projects")
async def get_projects(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await list_projects(session)


@app.get("/jobs/latest")
async def latest_job() -> dict[str, Any]:
    if not jobs:
        raise HTTPException(status_code=404, detail="No pipeline jobs have been started.")
    latest_job_id = next(reversed(jobs))
    return {"job_id": latest_job_id, **jobs[latest_job_id]}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
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
