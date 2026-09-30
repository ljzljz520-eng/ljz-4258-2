# 乳脂分离与回配核算平台

面向乳脂分离/标准化（回配）工段的**守恒核算**平台：在工程师选定的稳定窗口内，
对**质量与脂肪两条守恒律**做统一核算，展示每个节点/罐的**闭合残差**，
并在计算前进行**方程可辨识性检查**——欠定时报告缺失测量与允许区间，
**绝不强行生成唯一结果**。

> **平台边界**：本平台只做核算、残差展示与缺测诊断，
> **不推荐回配比例，也不向任何控制设备下发设定值**。
> 所有结果载荷与 `/api/health` 均带 `platform_notice` 明示此边界。

## 1. 技术栈与进程

| 层 | 选型 |
|---|---|
| Web/API | FastAPI + Pydantic v2 + Uvicorn |
| 核算内核 | NumPy / SciPy（SVD 秩检查、等式约束加权最小二乘、LP 区间） |
| 独立计算 | `worker/compute_worker.py`，**独立进程**轮询作业表 |
| 存储 | PostgreSQL（生产）；SQLite 仅用于本地/测试 |
| 前端 | Vue 3 + Vite + Plotly（残差柱状图、奇异值图），拓扑用 SVG |

三个进程职责分离：

```bash
# 1) 迁移 + 种子
python -m scripts.migrate
python -m scripts.seed --enqueue

# 2) API 进程
uvicorn app.main:app --reload --port 8000

# 3) 独立 Worker 进程（另开终端 / 另一个容器）
python -m worker.compute_worker        # 或 bash scripts/run_worker.sh

# 前端开发
cd frontend && npm install && npm run dev      # http://localhost:5173
```

`docker compose up` 会启动 `db`、`api`、`worker` 三个容器；
前端已构建产物会由 FastAPI 在 `/` 托管。

## 2. 数据模型（PostgreSQL）

- `topologies`：节点/流拓扑（source / separator / tank / blender / sink）。
- `batches` / `segments`：批与连续时间段；段带跨批边界备注。
- `samples`：流量/密度/脂肪检测，含**单位、绝对值或相对不确定度、
  量程通道、干湿基总固形物、接收时刻 `received_at`、被替代样本**。按 `batch_id` 隔离。
- `measurement_ranges`：计量通道量程（用于缺测建议的允许量程）。
- `tank_inventories`：**罐底旧料 (opening) / 中间 (middle) / 期末 (closing)**，
  可标记 `cross_batch`（跨批回流/旧料）。
- `windows`：工程师稳定窗口（连续段集合、最大样本间隔、外推容差）；
  调整窗口生成新行并令旧作业/结果失去 `is_current`。
- `jobs`：冻结输入快照 + **输入摘要 SHA-256** + 算法版本 + 状态机
  （queued/running/done/error/stale/superseded）。
- `results`：核算载荷，分 `identified / underdetermined`；仅当前结果 `is_current`。
- `signoffs` / `signoff_events`：签署冻结**摘要+算法版本**，只追加（撤销走事件）。

迁移：`migrations/0001_init.sql`（PostgreSQL），由 `scripts/migrate.py` 执行；
SQLite 走 SQLAlchemy `create_all`。

## 3. 核算模型与时间对齐

### 3.1 双守恒（罐底旧料与跨批回流进入同一条方程）

对窗口内每个段 `s`、每个内部节点 `n`，质量与脂肪各一行硬约束：

```
普通节点:   Σ_in M(s,e) − Σ_out M(s,e) = 0                         （脂肪同理）
罐:  V_before + Σ_in M(s,e) − Σ_out M(s,e) − V_after = 0
```

- 第一段 `V_before` = 罐 **opening**（含 `cross_batch` 的上一批罐底旧料）；
- 其后段 `V_before` = 上一段 `middle`（测得则为已知 RHS，未测则是变量）；
- 末段 `V_after` = closing。

因此**跨段/跨批回流与罐底旧料不是单独“补丁”，而是同一线性方程组的行/列**，
回流成环造成的不可辨识会被秩检查自然暴露（见种子算例 B）。

### 3.2 时间对齐（流量/密度/脂肪粒度不同）

- 取段内所有原始时间戳的**并集**作为评估网格，每个指标各自**分段线性插值**；
  不重采样到固定频率，避免高频流量被低频栅格平均。
- 梯形积分：`M = ∫ q(t)ρ(t)dt`，`F = ∫ q(t)ρ(t)w(t)dt`。
- **覆盖性判定**：首末样本必须覆盖段边界（受 `extrap_tolerance_s` 限制），
  相邻样本间隔不得超过窗口的 `max_gap_s`；不满足即判**缺测**，
  该测量行不进矩阵，交给可辨识性检查——**不用插补值冒充测量**。
- **量程切换**：同时刻多通道重叠时取相对不确定度更小者；
  两台表之间出现空档则视为缺测。种子 A 的 F1 在 seg1/seg2 间切换高/低量程表。
- **迟到样**：样品以服务端 `received_at` 为准。作业入队时冻结时间戳，
  之后到达的样本不进冻结快照（`audit.late_excluded_sample_ids` 会列出），
  其存在使“当前重建摘要”与作业摘要不一致，Worker 将作业判 `stale`，
  旧图保留可见但不再是当前图；禁止回填历史时间戳冒充及时测量。

### 3.3 单位与干湿基

- 流量内部统一 L/s（支持 L/min、L/h、m³/h、m³/s）；密度统一 kg/L；
  脂肪统一湿基分数。
- 干基脂肪必须随样提供总固形物湿基分数（或水分百分数），
  `w_wet = w_dry × TS_wet`；缺失则 API 返回 422，不做猜测。
- 不确定度统一为相对 1σ；独立量按方和根（RSS）合成，
  积分不确定度按网格一阶传播（忽略插值函数间协方差）。

## 4. 可辨识性、求解与缺测处理（取舍）

1. **装配**：变量 = 每段每流的 M 与 F + 罐的 middle/closing 存量（M、F）。
   守恒行为硬约束；积出的总量为带权测量行；未测流不给测量行。
2. **SVD 秩检查**：对 `[G(守恒); 测量]` 做奇异值分解，
   `rank < n ⇒ 欠定`。前端绘制奇异值曲线以辅助判断“差多少”。
3. **欠定时不求解唯一值**：
   - `missing_measurements`：枚举补录哪条流/段的哪类测量能提升秩，
     标注**是否已装计量通道**及其量程（允许区间），优先推荐已装表补读数；
   - `allowed_intervals`：以 `Gx=h`、已录测量、`x≥0` 为约束，
     用线性规划（HiGHS）求每个自由变量的**允许 min/max（kg）**。
     环上无任何流量测量时区间上界为 `∞`，并明确提示“需补测”。
4. **满秩时**才进行等式约束加权最小二乘（硬守恒高权重、测量 `1/σ`、
   非负边界 BVLS），输出调和值、调和后验不确定度与两套残差：
   - `closure.reconciled`：守恒调和后残差（应≈0）；
   - `closure.measured`：仅用测量原值、且入射流/存量齐全时计算的节点残差
     （不齐全标记 `complete=false`，不强行配平）。

## 5. 陈旧性、版本与签署（取舍）

- **窗口调整 → 依赖计算过期**：更新窗口会创建新窗口行并把旧作业/结果
  `is_current=false`（排队/运行中作业置 `superseded`）。
- **旧任务晚到不得覆盖当前图**：Worker 取作业后
  ①重查 `is_current`；②按作业冻结时刻重建快照并复算摘要，
  与入队摘要不一致即判 `stale` 且**不写结果**；
  写结果时再次确认仍为当前，否则结果仅作历史归档。
- **摘要**：`canonical JSON(sort_keys) → SHA-256`，覆盖拓扑/段/窗口参数/
  冻结时刻前样品/存量/量程，以及算法版本。
- **签署冻结**：只允许签署 `identified` 的当前结果；
  冻结输入摘要与算法版本，之后任何输入变化产生新摘要与新结果，
  旧签署不可原地修改，撤销只追加 `signoff_events`。
- 算法版本位于 `app/core/version.py`；求解逻辑变更必须提升版本号。

## 6. API 概览

```
POST   /api/topologies | GET /api/topologies
POST   /api/batches    | GET /api/batches/{id}
POST   /api/samples    | GET /api/samples?batch_id=&stream_id=
POST   /api/ranges     | GET /api/ranges
POST   /api/batches/{id}/inventories | GET .../inventories
POST   /api/batches/{id}/windows     | GET .../windows
PUT    /api/windows/{id}             # 调整窗口（旧结果失配）
POST   /api/windows/{id}/preview     # 不入队试算（与 Worker 同代码路径）
POST   /api/windows/{id}/jobs        # 入队（冻结快照+摘要）
GET    /api/windows/{id}/jobs | /api/jobs/{id}
GET    /api/windows/{id}/result      # 当前结果
GET    /api/results/{id}             # 任意历史结果（含非当前）
POST   /api/results/{id}/signoff     # 仅 identified 当前结果
GET    /api/windows/{id}/signoffs
POST   /api/signoffs/{id}/revoke     # 追加撤销事件
GET    /api/health
```

## 7. 种子算例（手算可核对）

### A `B-HANDCHECK`（满秩、完全闭合）
两段各 1 小时，速率恒定，段总量=速率×1h：

| 流 | 速率 | 脂肪 | 两段总质量 | 两段总脂肪 |
|---|---|---|---|---|
| F1 原料→分离机 | 900 kg/h | 4.0% | 1800 | 72 |
| F2 原料旁通 | 100 kg/h | 4.0% | 200 | 8 |
| CREAM 分离机→罐 | 120 kg/h | 30% | 240 | 72 |
| SKIM 脱脂乳 | 780 kg/h | 0% | 1560 | 0 |
| CREAM_OUT 罐成品 | 120 kg/h | 30% | 240 | 72 |
| PRODUCT 标准化乳 | 880 kg/h | 0.4545% | 1760 | 8 |

奶油罐跨批旧料 opening = closing = **40 kg（脂肪 30%，12 kg）**，
每段进出均 120 kg。全局：进料 **2000 kg / 80 kg 脂肪** =
出口 PRODUCT 1760/8 + CREAM_OUT 240/72，罐净变化 0。
测试断言全部调和残差为 0、中间/期末罐存量为 40/12。

### B `B-REFLUX`（未测回流成环 → 欠定）
增加 `T_CREAM → SEP` 的未测回流 REC，CREAM 与 REC 均无测量，
`SEP ⇄ 罐`成环：秩亏 4（质量环 2 + 脂肪环 2），
返回缺失测量（CREAM/REC 流量，已装 0–400 L/h 通道）与允许区间
（CREAM 质量下界 120 kg、上界 ∞；REC 下界 0、上界 ∞），
**不产出唯一调和值**。给环上任一流补测后系统转为满秩。

## 8. 测试

```bash
python -m pytest -q
```

覆盖（35 项）：
- 单位/干湿基换算、RSS 不确定度；时间积分、覆盖缺测、量程切换选表/空档；
- 种子 A 手算质量/脂肪闭合、逐节点/逐段平衡、罐底旧料保持、全局总量；
- 种子 B 回流成环、欠定不产唯一解、缺失测量定位与量程、允许区间无界、
  跨批旧料进入同一方程、补测后转满秩；
- Worker 摘要漂移判 stale、迟到样被排除、重新入队旧作业 superseded、
  旧结果不覆盖当前图；
- 窗口调整失配；签署冻结摘要/算法版本、欠定结果不可签署、撤销只追加；
- API 全链路（含单位校验、干基缺总固形物 422、签署载荷）。

## 9. 主要工程取舍小结

- **线性分段稳态**而非动态仿真：服务的是班次/批次核算与审计，可手算复核。
- **并集时间戳 + 线性插值**而非固定栅格重采样。
- **缺测即降秩**而非插值补齐：宁可欠定报缺，不造唯一数。
- **守恒为硬约束**、测量为软约束：调和结果优先满足物理闭合。
- **欠定区间用 LP**、只报可行范围：工程师据此决定补哪个表，不替人决策。
- **平台不产生建议/控制量**：残差与区间是诊断信息，回配决策由人负责。
