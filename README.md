# 馏分切割方案工具（离线试验数据）

化工培训用工具：根据累积蒸馏曲线选择馏分切点并核对每段产率。
**仅处理离线试验数据，不连接、不控制任何真实装置。**

## 架构

```
React (Vite + Recharts)  ──►  FastAPI  ──►  PostgreSQL
  温度-回收率曲线图            NumPy/SciPy      试验条件 / 密度 / 方案
  切点编辑、重叠/缺口显示      单调插值 PCHIP
```

- `backend/app/services/interpolation.py` — PCHIP 单调三次 Hermite 插值，**只在数据范围内取值，不外推**
- `backend/app/services/validation.py` — 曲线核查：下降段、回收总量异常、缺端点，先提示核实
- `backend/app/services/fractions.py` — 切割分析：重叠、缺口、残余、损失与总量平衡
- `backend/app/services/units.py` — 质量% ↔ 体积% 的密度换算（两轴不可混用）
- `backend/app/models.py` — SQLAlchemy 模型（试验 / 曲线点 / 馏分密度 / 切割方案）

## 运行

### 本地开发（SQLite，免安装数据库）

```bash
cd backend
pip install -r requirements.txt
python -m app.seed                 # 导入三个教学算例
python -m uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                        # http://localhost:5173
```

### PostgreSQL（生产形态）

```bash
export POSTGRES_PASSWORD='choose-a-local-password'
docker compose up --build          # 后端 8000 端口，自动建表并导入算例
```

或不使用 Docker：

```bash
export DB_HOST=localhost DB_PORT=5432 DB_NAME=distillation DB_USER=distill
export DB_PASSWORD='choose-a-local-password'
python -m uvicorn app.main:app --port 8000
```

### 测试

```bash
cd backend && python -m pytest tests/ -q     # 49 个用例
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

## 教学算例（种子数据）

| 算例 | 演示点 |
|---|---|
| 算例1-缺端点 | 曲线 8%~92%，范围外切点取不到温度，提示"不外推" |
| 算例2-密度随馏分变化 | 石脑油720/煤油798/柴油845/重油912 kg/m³，质量%明显偏离体积% |
| 算例3-数据异常 | 60%→70% 段温度下降、回收总量100.8%，均触发核实提示 |
| 算例3b-相邻切点相等 | 含零宽度馏分的方案：产率为0并提示，总量仍平衡 |

## API 摘要

- `POST /api/experiments` 创建试验（条件 + 曲线点 + 各馏分密度）
- `GET /api/experiments/{id}` 试验详情 + 曲线核查问题 + 插值元信息
- `POST /api/experiments/{id}/interpolate` 单点互查（超范围 422）
- `POST /api/experiments/{id}/analyze` 实时切割分析（不保存，供调切点时反复调用）
- `POST /api/experiments/{id}/schemes` 保存方案；`GET .../schemes` 列表
- `GET /api/experiments/{id}/schemes/{sid}/export?format=json|csv` 导出报告，
  含插值方法、适用范围与"不外推"声明
