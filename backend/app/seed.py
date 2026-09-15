"""演示数据：三个教学算例。

1. 缺端点算例：曲线从 8% 才开始、到 92% 结束，演示不外推与端点提示；
2. 密度随馏分变化算例：石脑油/煤油/柴油/重油密度各不相同，演示质量%≠体积%；
3. 相邻切点相等算例：方案中包含零宽度馏分，演示退化提示与总量平衡。

运行：python -m app.seed
"""
from __future__ import annotations

from .database import SessionLocal, ensure_schema
from . import models


def seed() -> None:
    ensure_schema()
    db = SessionLocal()
    try:
        if db.query(models.Experiment).count() > 0:
            print("已有数据，跳过种子导入")
            return

        # ---- 算例 1：缺端点 -------------------------------------------
        exp1 = models.Experiment(
            name="算例1-缺端点：常压柴油蒸馏",
            sample="0#柴油",
            method="GB/T 6536（常压）",
            curve_basis="volume",
            pressure_kpa=101.3,
            operator="培训组",
            notes="曲线缺低回收端点（起点8%）与高回收端点（终点92%），用于演示不外推。",
            points=[
                models.CurvePoint(recovery_pct=r, temperature_c=t)
                for r, t in [
                    (8.0, 168.0),
                    (10.0, 172.5),
                    (20.0, 191.0),
                    (30.0, 208.0),
                    (40.0, 224.5),
                    (50.0, 241.0),
                    (60.0, 258.5),
                    (70.0, 277.0),
                    (80.0, 298.0),
                    (90.0, 322.0),
                    (92.0, 328.5),
                ]
            ],
            densities=[
                models.FractionDensity(label="轻柴油", start_pct=0, end_pct=50, density_kg_m3=826.0),
                models.FractionDensity(label="重柴油", start_pct=50, end_pct=92, density_kg_m3=852.0),
            ],
        )

        # ---- 算例 2：密度随馏分变化 ------------------------------------
        exp2 = models.Experiment(
            name="算例2-密度随馏分变化：原油宽馏分",
            sample="混合原油",
            method="ASTM D86（常压）",
            curve_basis="volume",
            pressure_kpa=101.3,
            operator="培训组",
            notes="四段馏分密度差异明显，用于演示质量%与体积%不可混用。",
            points=[
                models.CurvePoint(recovery_pct=r, temperature_c=t)
                for r, t in [
                    (0.0, 38.0),
                    (5.0, 62.0),
                    (10.0, 84.0),
                    (20.0, 128.0),
                    (30.0, 172.0),
                    (40.0, 214.0),
                    (50.0, 252.0),
                    (60.0, 288.0),
                    (70.0, 322.0),
                    (80.0, 355.0),
                    (90.0, 388.0),
                    (96.5, 412.0),
                ]
            ],
            densities=[
                models.FractionDensity(label="石脑油", start_pct=0, end_pct=20, density_kg_m3=720.0),
                models.FractionDensity(label="煤油", start_pct=20, end_pct=40, density_kg_m3=798.0),
                models.FractionDensity(label="柴油", start_pct=40, end_pct=70, density_kg_m3=845.0),
                models.FractionDensity(label="重油", start_pct=70, end_pct=96.5, density_kg_m3=912.0),
            ],
        )

        # ---- 算例 3：曲线下降 + 回收总量异常（提示核实） -----------------
        exp3 = models.Experiment(
            name="算例3-数据异常演示：曲线下降且回收超100%",
            sample="待核实样品",
            method="ASTM D86（常压）",
            curve_basis="volume",
            pressure_kpa=101.3,
            operator="培训组",
            notes="故意放入异常数据：60%→70% 段温度下降，终点回收率 100.8%。",
            points=[
                models.CurvePoint(recovery_pct=r, temperature_c=t)
                for r, t in [
                    (0.0, 45.0),
                    (10.0, 88.0),
                    (20.0, 126.0),
                    (30.0, 160.0),
                    (40.0, 192.0),
                    (50.0, 222.0),
                    (60.0, 250.0),
                    (70.0, 243.0),   # 曲线下降，应提示核实
                    (80.0, 268.0),
                    (90.0, 296.0),
                    (100.8, 330.0),  # 回收总量超过 100%，应提示核实
                ]
            ],
            densities=[
                models.FractionDensity(label="轻组分", start_pct=0, end_pct=50, density_kg_m3=760.0),
                models.FractionDensity(label="重组分", start_pct=50, end_pct=100.8, density_kg_m3=870.0),
            ],
        )

        db.add_all([exp1, exp2, exp3])
        db.flush()

        # 算例2 的配套方案：相邻切点相等（含零宽度馏分）—— 保持草稿状态
        scheme = models.CutScheme(
            experiment_id=exp2.id,
            name="算例3b-相邻切点相等方案",
            status="draft",
            revision=1,
            cuts=[
                models.SchemeCut(position=0, label="石脑油", start_pct=0.0, end_pct=20.0),
                models.SchemeCut(position=1, label="零宽演示", start_pct=20.0, end_pct=20.0),
                models.SchemeCut(position=2, label="煤油", start_pct=20.0, end_pct=40.0),
                models.SchemeCut(position=3, label="柴油", start_pct=40.0, end_pct=70.0),
                models.SchemeCut(position=4, label="重油", start_pct=70.0, end_pct=96.5),
            ],
        )
        db.add(scheme)
        db.flush()

        # 算例2 的四馏分方案：走完整生命周期（草稿→提交→发布），生成 v1 冻结快照
        from .services.fractions import FractionInput
        from .services import versioning

        four = [
            FractionInput("石脑油", 0.0, 20.0),
            FractionInput("煤油", 20.0, 40.0),
            FractionInput("柴油", 40.0, 70.0),
            FractionInput("重油", 70.0, 96.5),
        ]
        demo, _ = versioning.create_scheme(
            db, exp2, name="算例2-四馏分方案（已发布演示）", fractions=four, actor="培训组"
        )
        versioning.submit(db, demo, base_revision=1, actor="培训组", note="首次提交")
        versioning.approve(db, demo, base_revision=2, actor="审核员", note="数据核对无误")

        db.commit()
        print("种子数据已导入：3 个试验 + 2 个方案（含 1 个已发布版本）")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
