"""ORM 模型：试验、曲线点、馏分密度、切割方案。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    """一套馏分切割方案（若干馏分区间）。"""

    __tablename__ = "cut_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="schemes")
    cuts: Mapped[list["SchemeCut"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="SchemeCut.position",
    )


class SchemeCut(Base):
    """方案中的一个馏分区间 [start_pct, end_pct]。"""

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
