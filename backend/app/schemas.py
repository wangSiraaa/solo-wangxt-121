"""Pydantic 模式：API 输入输出。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---- 输入 ---------------------------------------------------------------
class CurvePointIn(BaseModel):
    recovery_pct: float = Field(ge=0.0, le=200.0, description="回收率%，允许略超100以便触发异常提示")
    temperature_c: float = Field(ge=-100.0, le=800.0)


class FractionDensityIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    start_pct: float = Field(ge=0.0)
    end_pct: float = Field(ge=0.0)
    density_kg_m3: float = Field(gt=0.0, description="实测密度 kg/m³，必须为正")


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sample: str = ""
    method: str = ""
    curve_basis: Literal["volume", "mass"] = "volume"
    pressure_kpa: float | None = Field(default=None, gt=0.0)
    operator: str = ""
    defined_total_pct: float = Field(default=100.0, gt=0.0)
    notes: str = ""
    points: list[CurvePointIn] = Field(min_length=2)
    densities: list[FractionDensityIn] = []


class FractionIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    start_pct: float = Field(ge=0.0)
    end_pct: float = Field(ge=0.0)


class SchemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fractions: list[FractionIn] = Field(min_length=1)


class AnalyzeRequest(BaseModel):
    fractions: list[FractionIn] = Field(min_length=1)


class InterpolateRequest(BaseModel):
    recovery_pct: float | None = None
    temperature_c: float | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.recovery_pct is None) == (self.temperature_c is None):
            raise ValueError("必须且只能提供 recovery_pct 或 temperature_c 之一")
        return self


# ---- 输出 ---------------------------------------------------------------
class CurvePointOut(BaseModel):
    recovery_pct: float
    temperature_c: float


class ExperimentSummary(BaseModel):
    id: int
    name: str
    sample: str
    method: str
    curve_basis: str
    created_at: str


class ExperimentDetail(BaseModel):
    id: int
    name: str
    sample: str
    method: str
    curve_basis: str
    pressure_kpa: float | None
    operator: str
    defined_total_pct: float
    notes: str
    points: list[CurvePointOut]
    densities: list[FractionDensityIn]
    curve_issues: list[dict]
    interpolation: dict


class SchemeOut(BaseModel):
    id: int
    name: str
    fractions: list[FractionIn]
    analysis: dict
