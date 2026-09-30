# API 摘要

OpenAPI 交互文档：`/docs`。所有时间戳使用带时区 ISO-8601。

## 批次/批段

- `POST /api/batches`
- `GET /api/batches`
- `GET /api/batches/{batch_id}`
- `POST /api/batches/{batch_id}/segments`
- `GET /api/batches/{batch_id}/segments`
- `PATCH /api/batches/segments/{segment_id}`

## 拓扑

- `POST /api/segments/{segment_id}/nodes`
- `GET /api/segments/{segment_id}/nodes`
- `POST /api/segments/{segment_id}/edges`
- `GET /api/segments/{segment_id}/edges`

边允许指向已连接的跨批段节点；`cross_batch=true` 只作语义标记，不改变守恒方程。

## 测量

- `POST /api/segments/{segment_id}/measurements`
- `GET /api/segments/{segment_id}/measurements`

支持指标：`mass_flow`、`volume_flow`、`density`、`fat_fraction`、`solids_fraction`、`mass`、`fat_mass`。点样指标省略 `period_end`；窗口流量/总量必须提供区间。节点边界库存使用 `target_type=node`、`metric=mass|fat_mass`，时间为稳定窗口起点或终点。

单位在边界转换为 SI：质量 kg、体积 m³、密度 kg/m³、比例 fraction。支持相对、绝对、标准差和 95%扩展不确定度。

## 计算

- `POST /api/segments/{segment_id}/precheck`
- `POST /api/segments/{segment_id}/jobs`
- `GET /api/segments/{segment_id}/jobs`
- `GET /api/segments/{segment_id}/current-result`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/signoff`

## Worker

- `POST /api/worker/claim`：`{ "worker_id": "..." }`
- `POST /api/worker/jobs/{job_id}/complete`

生产建议只运行独立 Worker；这两个端点便于编排、调试和测试。
