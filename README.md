# 馏分切割方案工具（离线试验数据）

化工培训用工具：根据累积蒸馏曲线选择馏分切点并核对产率，方案支持
**草稿 → 待审核 → 已发布 / 已撤回** 的版本化审阅流程。
**仅处理离线试验数据，不连接、不控制任何真实装置。**

## 架构

```
React (Vite + Recharts)  ──►  FastAPI  ──►  PostgreSQL
  温度-回收率曲线图            NumPy/SciPy      试验条件 / 密度
  切点编辑、重叠/缺口显示      单调插值 PCHIP    方案工作副本
  版本时间线、冲突提示         状态机/幂等/快照  版本快照 / 审计记录
```

- `backend/app/services/interpolation.py` — PCHIP 单调三次 Hermite 插值，**只在数据范围内取值，不外推**
- `backend/app/services/validation.py` — 曲线核查：下降段、回收总量异常、缺端点，先提示核实
- `backend/app/services/fractions.py` — 切割分析：重叠、缺口、残余、损失与总量平衡
- `backend/app/services/units.py` — 质量% ↔ 体积% 的密度换算（两轴不可混用）
- `backend/app/services/versioning.py` — 方案状态机、乐观锁、幂等、发布冻结快照
- `backend/app/services/report.py` — 报告构建（实时导出与发布冻结共用）
- `backend/app/models.py` — SQLAlchemy 模型（试验 / 曲线点 / 密度 / 方案 / 版本快照 / 审计）

## 方案版本化

**状态机**

```
draft --submit--> pending_review --approve--> published --withdraw--> withdrawn
pending_review --withdraw--> draft
draft / published / withdrawn --save_draft--> draft   （工作副本可继续编辑，
                                                       已发布版本快照不受影响）
```

**不可变快照**：审核通过时把当时的切点、密度、曲线点、插值方法与适用范围、
分析结果和完整报告 JSON 一并冻结进 `scheme_versions`；之后修改试验或草稿
都不会改写历史报告。版本导出（`/api/scheme-versions/{id}/export`）只读快照，
绝不重新计算；工作副本导出（`/api/experiments/{eid}/schemes/{sid}/export`）
仍是实时计算并标注"未冻结"。

**当前生效版本**：同一方案可保留多个已发布快照，但只有一个生效版本
（`cut_schemes.active_version_id`，普通整型指针，避免与版本表外键形成循环依赖，
完整性由应用层保证）。新发布版本自动生效；`POST /api/schemes/{sid}/switch-version`
受控切换到历史版本 —— 只移动指针并写新审计事件，不改写任何旧快照、旧报告或
原审核记录。切换请求必须携带 `expected_active_version_id` 与 `base_revision`，
乱序/过期返回 `409 ACTIVE_VERSION_CONFLICT / REVISION_CONFLICT`；目标已是生效
版本时为幂等空操作（不写审计）。撤回已发布方案时若生效指针存在，必须显式指定
继任历史版本（`successor_version_id`，切换+撤回同一事务原子完成），否则
`409 ACTIVE_VERSION_REQUIRES_SUCCESSOR` —— 绝不静默丢失生效指针。

**版本差异审阅**：`GET /api/schemes/{sid}/diff?from_id=&to_id=` 只读对比两个
冻结快照的切点、密度、插值适用范围与产率（含逐项 Δ）；前端时间线标出生效版本，
支持只读差异比较与从历史版本发起切换。

**乐观锁**：每次变更携带 `base_revision`，与当前 `revision` 不一致即返回
`409 REVISION_CONFLICT`，绝不覆盖他人修改；前端弹出冲突提示并可一键载入最新。

**幂等**：变更类接口接受 `Idempotency-Key` 请求头；重复提交命中已有审计记录时
回放当时的响应（`Idempotent-Replay: true`），不会产生第二条审计记录或重复版本。
前端按 `窗口ID:方案:动作:修订号` 生成键，失败重试天然安全；服务重启后状态全部
在数据库中，审计与状态一致。

**审计**：创建、保存草稿、提交、审核通过、撤回、复制均写入 `audit_records`
（操作人经 `X-Actor` 头传入），构成版本时间线。

**旧数据兼容**：启动时自动为旧版 `cut_schemes` 补齐 `status/revision/updated_at`
列并回填为可继续编辑的草稿（`ensure_schema()`，生产建议改用 Alembic）。

## 运行

### 本地开发（SQLite，免安装数据库）

```bash
cd backend
pip install -r requirements.txt
python -m app.seed                 # 导入教学算例（含一个已发布版本演示）
python -m uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                        # http://localhost:5173
```

### PostgreSQL（生产形态）

```bash
docker compose up --build          # 后端 8000 端口，自动建表迁移并导入算例
```

或不使用 Docker：

```bash
export DATABASE_URL=postgresql+psycopg2://distill:distill@localhost:5432/distillation
python -m uvicorn app.main:app --port 8000
```

### 测试

```bash
cd backend && python -m pytest tests/ -q     # 66 个用例
```

## 核心规则

1. **质量% ≠ 体积%**：曲线横轴有明确基准（试验的 `curve_basis`）。另一基准只能通过
   各馏分**实测密度**换算（`mass_i ∝ vol_i × ρ_i`），缺密度的馏分不参与换算并给出提示；
   损失与残余无密度数据，不强行折算。
2. **不外推**：插值查询超出曲线数据范围（含高温端）一律返回 422，界面与导出中标注
   适用范围。缺端点的曲线只能覆盖已有区间。
3. **异常先提示**：曲线下降段、回收总量 >100% 或过低，先给出"请核实"提示，不静默接受；
   回收率重复等错误级问题拒绝入库。
4. **总量平衡**：`已分配(并集) + 残余 + 损失 = 定义总量(默认100%)`，每次分析都校验；
   重叠部分被重复计数，单独列示并提示调整切点。
5. **发布即冻结**：已发布版本的导出固定到发布时刻的切点、密度与插值范围。

## 教学算例（种子数据）

| 算例 | 演示点 |
|---|---|
| 算例1-缺端点 | 曲线 8%~92%，范围外切点取不到温度，提示"不外推" |
| 算例2-密度随馏分变化 | 石脑油720/煤油798/柴油845/重油912 kg/m³，质量%明显偏离体积% |
| 算例2-四馏分方案 | 已发布 v1：版本时间线、冻结导出、基于版本复制 |
| 算例3-数据异常 | 60%→70% 段温度下降、回收总量100.8%，均触发核实提示 |
| 算例3b-相邻切点相等 | 含零宽度馏分的草稿方案：产率为0并提示，总量仍平衡 |

## API 摘要

试验与实时分析：

- `POST /api/experiments` 创建试验；`PUT /api/experiments/{id}` 更新（不改写已发布快照）
- `GET /api/experiments/{id}` 试验详情 + 曲线核查问题 + 插值元信息
- `POST /api/experiments/{id}/interpolate` 单点互查（超范围 422）
- `POST /api/experiments/{id}/analyze` 实时切割分析（不落库）

方案版本化（变更类接口均接受 `Idempotency-Key` 头与 `base_revision`）：

- `POST /api/experiments/{id}/schemes` 新建草稿；`GET .../schemes` 列表（含状态）
- `GET /api/schemes/{sid}` 工作副本详情 + 版本列表 + 审计时间线（含生效版本）
- `PUT /api/schemes/{sid}/draft` 保存草稿
- `POST /api/schemes/{sid}/submit | approve | withdraw` 状态迁移（withdraw 支持 `successor_version_id`）
- `POST /api/schemes/{sid}/switch-version` 受控切换生效版本
- `GET /api/schemes/{sid}/current-version` 当前生效版本查询
- `GET /api/schemes/{sid}/diff?from_id=&to_id=` 两版本差异（切点/密度/插值范围/产率）
- `GET /api/scheme-versions/{vid}` 版本快照查询；`POST .../copy` 基于版本复制新草稿
- `GET /api/scheme-versions/{vid}/export?format=json|csv` 冻结导出
- `GET /api/experiments/{eid}/schemes/{sid}/export` 工作副本实时导出（未冻结）
