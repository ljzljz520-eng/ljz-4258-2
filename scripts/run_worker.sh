#!/usr/bin/env bash
# 独立计算 Worker（与 Web 进程分离）
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
exec python -m worker.compute_worker
