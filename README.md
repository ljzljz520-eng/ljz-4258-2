# 乳脂分离与回配核算平台

该系统用于保存乳脂分离/跨批回配过程的拓扑、不同粒度测量、计算版本和签署记录，并用独立 Worker 执行质量与脂肪守恒核算。它只提供核算与残差展示，不推荐回配比例，也不控制任何设备。

## 组成

- `backend/`：FastAPI、SQLAlchemy 2、Alembic、NumPy/SciPy 核算与独立 Worker。
- `frontend/`：Vue 3 + Vite + Plotly，可编辑批次、批段、拓扑、测量，查看可辨识性、闭合残差和签署信息。
- PostgreSQL：保存批次、批段、节点、物流、测量、作业、冻结快照、结果与签署。
- Worker：独立进程，通过队列锁领取任务；慢任务完成时再次校验输入版本。

## 快速启动（PostgreSQL）

```bash
cp .env.example .env
docker compose up -d --build
```

- API：<http://localhost:8000/docs>
- 前端：<http://localhost:5173>
- 种子批次：`B-DEMO-A` / `B-DEMO-B`，包含回流成环、罐底旧料、量程切换和不同粒度脂肪点样。

### 不用 Docker 的本地启动

后端：

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export FAT_DATABASE_URL='postgresql+psycopg2://fat:fat@localhost:5432/fat_platform'
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --host 0.0.0.0
python -m app.workers.worker
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 主要 API

- `POST /api/batches`、`GET /api/batches`
- `POST /api/batches/{batch_id}/segments`
- `PATCH /api/batches/segments/{segment_id}`：调整稳定窗口并升版
- `POST /api/segments/{segment_id}/nodes|edges|measurements`
- `POST /api/segments/{segment_id}/precheck`：计算前可辨识性检查
- `POST /api/segments/{segment_id}/jobs`：冻结输入并入队
- `POST /api/worker/claim`、`POST /api/worker/jobs/{job_id}/complete`
- `GET /api/segments/{segment_id}/current-result`
- `POST /api/jobs/{job_id}/signoff`
- `GET /api/engineering-notes`

## 测试

```bash
cd backend
# 测试默认使用内存 SQLite，不需要 PostgreSQL
pytest -q
```

测试覆盖：

1. 回流/跨批成环进入同一个守恒矩阵；
2. 罐底旧料以初始/终止库存进入同一节点方程；
3. 流量计量程切换分段积分；
4. 体积流量 × 密度、点样与不同时间粒度；
5. 单位、相对/95%扩展不确定度、湿基/干基转换；
6. 欠定模型返回最小补测集合和允许区间，不返回唯一图；
7. 冻结后晚到测量/窗口调整使旧作业过期；
8. 手算可核对的质量和脂肪闭合；
9. API 入队、Worker 领取完成、当前结果和签署。

## 安全边界

本系统输出的是“测量经守恒约束调整后的核算值与残差”。它不会输出推荐回配比例、最优配比、阀门/泵控制指令或设备设定值。
