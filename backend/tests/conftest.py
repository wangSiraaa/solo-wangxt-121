import os
import tempfile

# 必须在导入 app 之前设置，测试使用独立 SQLite 文件
_TMPDIR = tempfile.mkdtemp(prefix="distill_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def exp2_payload():
    """算例2：密度随馏分变化的完整试验数据。"""
    return {
        "name": "算例2-密度随馏分变化",
        "sample": "混合原油",
        "method": "ASTM D86",
        "curve_basis": "volume",
        "pressure_kpa": 101.3,
        "points": [
            {"recovery_pct": r, "temperature_c": t}
            for r, t in [
                (0.0, 38.0), (5.0, 62.0), (10.0, 84.0), (20.0, 128.0),
                (30.0, 172.0), (40.0, 214.0), (50.0, 252.0), (60.0, 288.0),
                (70.0, 322.0), (80.0, 355.0), (90.0, 388.0), (96.5, 412.0),
            ]
        ],
        "densities": [
            {"label": "石脑油", "start_pct": 0, "end_pct": 20, "density_kg_m3": 720.0},
            {"label": "煤油", "start_pct": 20, "end_pct": 40, "density_kg_m3": 798.0},
            {"label": "柴油", "start_pct": 40, "end_pct": 70, "density_kg_m3": 845.0},
            {"label": "重油", "start_pct": 70, "end_pct": 96.5, "density_kg_m3": 912.0},
        ],
    }
