from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import batches, jobs, measurements, topology, worker
from app.core.config import get_settings

app = FastAPI(
    title="Milk-Fat Separation and Re-blending Reconciliation Platform",
    version="1.0.0",
    description=(
        "Stores process topology, heterogeneous measurements, calculation "
        "versions and signed closure results. The system performs conservation "
        "accounting only; it never recommends re-blend ratios or control actions."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(batches.router)
app.include_router(topology.router)
app.include_router(measurements.router)
app.include_router(jobs.router)
app.include_router(worker.router)


@app.get("/health")
def health():
    return {"ok": True, "algorithm_version": get_settings().algorithm_version}


@app.get("/api/engineering-notes")
def engineering_notes():
    return {
        "time_alignment": (
            "Point density/fat samples are held constant over half-open intervals "
            "to the next sample and intersected with flow intervals. Gaps are not "
            "interpolated; they are reported as uncovered duration. Range switches "
            "are adjacent non-overlapping records and are integrated separately."
        ),
        "constraint_solving": (
            "Mass and fat node balances use the same linear equations for normal "
            "streams, recirculation cycles, cross-batch returns and tank initial/"
            "final inventory. Before solving, the stacked conservation and "
            "measurement matrix must have full column rank. Weighted least squares "
            "then minimizes normalized measurement corrections subject to non-"
            "negativity and exact node closure."
        ),
        "missing_data": (
            "If under-determined, the API reports minimal additional measurement "
            "sets and LP-derived feasible intervals. It does not fabricate a unique "
            "graph or silently choose a return flow."
        ),
        "frozen_inputs": (
            "Every worker job snapshots topology, measurements, stable window and "
            "algorithm version. Adjusting a window bumps the segment version; slow "
            "old jobs are marked superseded and cannot replace the current graph."
        ),
        "units_and_basis": (
            "Convenience units and expanded uncertainty are normalized at the API "
            "boundary. Dry-basis fat is converted only when a coincident wet-basis "
            "solids fraction is available."
        ),
        "safety_scope": "No re-blend ratio recommendation and no equipment control is provided.",
    }
