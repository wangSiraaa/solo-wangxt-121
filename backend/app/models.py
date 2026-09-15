"""ORM 模型：试验、曲线点、馏分密度、切割方案、版本快照、审计记录。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 方案状态机：draft -> pending_review -> published -> withdrawn
SCHEME_STATUSES = ("draft", "pending_review", "published", "withdrawn")


class Experiment(Base):
    """一次离线蒸馏试验：条件 + 累积曲线 + 各馏分密度。"""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sample: Mapped[str] = mapped_column(String(200), default="")
    method: Mapped[str] = mapped_column(String(100), default="")  # 如 ASTM D86 / GB/T 6536
    curve_basis: Mapped[str] = mapped_column(String(10), default="volume")  # volume | mass
    pressure_kpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    operator: Mapped[str] = mapped_column(String(100), default="")
    defined_total_pct: Mapped[float] = mapped_column(Float, default=100.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    points: Mapped[list["CurvePoint"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="CurvePoint.recovery_pct",
    )
    densities: Mapped[list["FractionDensity"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    schemes: Mapped[list["CutScheme"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class CurvePoint(Base):
    """累积蒸馏曲线上的一个点：回收率% -> 温度°C。"""

    __tablename__ = "curve_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    recovery_pct: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)

    experiment: Mapped[Experiment] = relationship(back_populates="points")


class FractionDensity(Base):
    """某段馏分的实测密度，用于质量% <-> 体积% 换算。"""

    __tablename__ = "fraction_densities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    start_pct: Mapped[float] = mapped_column(Float, nullable=False)
    end_pct: Mapped[float] = mapped_column(Float, nullable=False)
    density_kg_m3: Mapped[float] = mapped_column(Float, nullable=False)

    experiment: Mapped[Experiment] = relationship(back_populates="densities")


class CutScheme(Base):
    """一套馏分切割方案的工作副本（可变），带状态机与乐观锁。"""

    __tablename__ = "cut_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 旧数据可能为 NULL，代码按 draft / 1 处理，启动迁移会回填
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="draft")
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=True
    )

    experiment: Mapped[Experiment] = relationship(back_populates="schemes")
    cuts: Mapped[list["SchemeCut"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="SchemeCut.position",
    )
    versions: Mapped[list["SchemeVersion"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="SchemeVersion.version_no",
    )
    audits: Mapped[list["AuditRecord"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="AuditRecord.id",
    )

    @property
    def current_status(self) -> str:
        return self.status or "draft"

    @property
    def current_revision(self) -> int:
        return self.revision or 1


class SchemeCut(Base):
    """方案工作副本中的一个馏分区间 [start_pct, end_pct]。"""

    __tablename__ = "scheme_cuts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("cut_schemes.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    start_pct: Mapped[float] = mapped_column(Float, nullable=False)
    end_pct: Mapped[float] = mapped_column(Float, nullable=False)

    scheme: Mapped[CutScheme] = relationship(back_populates="cuts")


class SchemeVersion(Base):
    """发布时生成的不可变版本快照。

    冻结当时的切点、密度、曲线与插值范围、分析结果和完整导出报告；
    之后修改试验或草稿都不会改写本快照。
    """

    __tablename__ = "scheme_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("cut_schemes.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    fractions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    densities_json: Mapped[list] = mapped_column(JSON, nullable=False)
    curve_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    analysis_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    scheme: Mapped[CutScheme] = relationship(back_populates="versions")


class AuditRecord(Base):
    """审计记录：每次状态迁移/保存都留痕。

    idempotency_key 全局唯一：同一客户端请求重复提交时命中已有记录，
    直接回放当时的响应，不会产生第二条审计记录。
    """

    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("cut_schemes.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("scheme_versions.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), default="")
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), unique=True, nullable=True
    )
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    scheme: Mapped[CutScheme] = relationship(back_populates="audits")
