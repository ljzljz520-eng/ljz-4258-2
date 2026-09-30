"""FastAPI 入口。Web 与 Worker 是不同进程：
   uvicorn app.main:app   /   python -m worker.compute_worker
"""
from __future__ import annotations

import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.version import ALGORITHM_NOTES, ALGORITHM_VERSION, PLATFORM_NOTICE
from app.database import Base, engine
from app.routers import batches, compute, data, topologies
from app.services import ensure_calc_version

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ensure_calc_version(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="乳脂分离与回配核算平台",
    version=ALGORITHM_VERSION,
    description="质量/脂肪双守恒核算、闭合残差与缺测诊断。"
                "不推荐回配比例、不控制设备。",
    lifespan=lifespan,
)

def _origins():
    raw = os.environ.get("CORS_ORIGINS",
                         "http://localhost:5173,http://localhost:8000")
    return [x.strip() for x in raw.split(",") if x.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "algorithm_version": ALGORITHM_VERSION,
            "platform_notice": PLATFORM_NOTICE,
            "algorithm_notes": ALGORITHM_NOTES}


app.include_router(topologies.router)
app.include_router(batches.router)
app.include_router(data.router)
app.include_router(compute.router)

# 前端构建产物（可选）
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets",
              StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/")
    def index():
        return FileResponse(str(_DIST / "index.html"))

    @app.get("/ui/{full_path:path}")
    def ui_spa(full_path: str):
        return FileResponse(str(_DIST / "index.html"))
