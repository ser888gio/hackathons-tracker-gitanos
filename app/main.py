from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, status
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
    jobs[job_id] = {
        "status": "accepted",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    asyncio.create_task(_run_pipeline_job(job_id))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job_id, "status": "accepted"},
    )


@app.get("/projects")
async def get_projects(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await list_projects(session)


async def _run_pipeline_job(job_id: str) -> None:
    async def update_status(state: str, payload: dict[str, Any]) -> None:
        jobs[job_id] = {
            "status": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }

    try:
        await run_pipeline(job_id=job_id, status_callback=update_status)
    except Exception as exc:
        jobs[job_id] = {
            "status": "failed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
