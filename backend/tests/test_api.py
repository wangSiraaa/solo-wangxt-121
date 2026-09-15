"""API 集成测试：试验管理、插值、分析、方案、导出。"""
import pytest

FOUR_FRACTIONS = [
    {"label": "石脑油", "start_pct": 0, "end_pct": 20},
    {"label": "煤油", "start_pct": 20, "end_pct": 40},
    {"label": "柴油", "start_pct": 40, "end_pct": 70},
    {"label": "重油", "start_pct": 70, "end_pct": 96.5},
]


@pytest.fixture()
def exp_id(client, exp2_payload):
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- 试验管理 -----------------------------------------------------------
def test_create_and_get_experiment(client, exp2_payload):
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201
    body = r.json()
    assert body["curve_issues"] == [] or all(
        i["severity"] != "error" for i in body["curve_issues"]
    )
    assert body["interpolation"]["method_id"] == "pchip"
    assert body["interpolation"]["applicable_range"]["recovery_max_pct"] == 96.5

    r = client.get(f"/api/experiments/{body['id']}")
    assert r.status_code == 200
    assert len(r.json()["points"]) == 12

    r = client.get("/api/experiments")
    assert any(e["name"] == exp2_payload["name"] for e in r.json())


def test_create_rejects_duplicate_recovery(client, exp2_payload):
    exp2_payload["points"].append({"recovery_pct": 96.5, "temperature_c": 420.0})
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 422
    assert "DUPLICATE_RECOVERY" in str(r.json()["detail"])


def test_decreasing_curve_warns_but_saves(client, exp2_payload):
    exp2_payload["points"][5]["temperature_c"] = 60.0  # 制造下降段
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201
    codes = {i["code"] for i in r.json()["curve_issues"]}
    assert "CURVE_DECREASING" in codes


def test_recovery_over_100_warns(client, exp2_payload):
    exp2_payload["points"][-1] = {"recovery_pct": 100.8, "temperature_c": 420.0}
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201
    codes = {i["code"] for i in r.json()["curve_issues"]}
    assert "RECOVERY_OVER_100" in codes


# ---- 插值 ---------------------------------------------------------------
def test_interpolate_within_range(client, exp_id):
    r = client.post(f"/api/experiments/{exp_id}/interpolate", json={"recovery_pct": 50})
    assert r.status_code == 200
    assert r.json()["temperature_c"] == pytest.approx(252.0)

    r = client.post(f"/api/experiments/{exp_id}/interpolate", json={"temperature_c": 252.0})
    assert r.status_code == 200
    assert r.json()["recovery_pct"] == pytest.approx(50.0)


def test_interpolate_no_extrapolation(client, exp_id):
    """超出数据范围（含高温端）一律 422，不外推。"""
    r = client.post(f"/api/experiments/{exp_id}/interpolate", json={"recovery_pct": 99})
    assert r.status_code == 422
    assert "不外推" in r.json()["detail"]
    r = client.post(f"/api/experiments/{exp_id}/interpolate", json={"temperature_c": 500})
    assert r.status_code == 422


def test_interpolate_requires_exactly_one_param(client, exp_id):
    r = client.post(f"/api/experiments/{exp_id}/interpolate", json={})
    assert r.status_code == 422
    r = client.post(
        f"/api/experiments/{exp_id}/interpolate",
        json={"recovery_pct": 50, "temperature_c": 252},
    )
    assert r.status_code == 422


# ---- 实时分析 -----------------------------------------------------------
def test_analyze_balance_and_conversion(client, exp_id):
    r = client.post(
        f"/api/experiments/{exp_id}/analyze", json={"fractions": FOUR_FRACTIONS}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["balance_ok"] is True
    assert body["assigned_pct"] == pytest.approx(96.5)
    assert body["loss_pct"] == pytest.approx(3.5)
    assert body["residual_pct"] == pytest.approx(0.0)
    fr = body["fractions"][0]
    assert fr["vol_pct_of_recovered"] != fr["mass_pct_of_recovered"]
    assert fr["temp_start_c"] == pytest.approx(38.0)
    assert body["interpolation"]["extrapolation"].startswith("禁止外推")


def test_analyze_overlap_and_gap_visible(client, exp_id):
    fractions = [
        {"label": "A", "start_pct": 0, "end_pct": 30},
        {"label": "B", "start_pct": 20, "end_pct": 60},
        {"label": "C", "start_pct": 70, "end_pct": 90},
    ]
    r = client.post(f"/api/experiments/{exp_id}/analyze", json={"fractions": fractions})
    body = r.json()
    assert body["overlap_pct"] == pytest.approx(10.0)
    assert body["residual_pct"] == pytest.approx(16.5)  # 60→70 与 90→96.5
    assert len(body["gaps"]) == 2
    assert body["balance_ok"] is True


def test_analyze_zero_width_fraction(client, exp_id):
    fractions = FOUR_FRACTIONS + [{"label": "零宽", "start_pct": 20, "end_pct": 20}]
    r = client.post(f"/api/experiments/{exp_id}/analyze", json={"fractions": fractions})
    body = r.json()
    zero = body["fractions"][-1]
    assert zero["width_pct"] == 0
    assert any("宽度为 0" in w for w in zero["warnings"])
    assert body["balance_ok"] is True


# ---- 方案保存与导出 -------------------------------------------------------
def test_scheme_save_list_export(client, exp_id):
    r = client.post(
        f"/api/experiments/{exp_id}/schemes",
        json={"name": "四馏分方案", "fractions": FOUR_FRACTIONS},
    )
    assert r.status_code == 201
    scheme = r.json()
    assert scheme["analysis"]["balance_ok"] is True

    r = client.get(f"/api/experiments/{exp_id}/schemes")
    assert len(r.json()) == 1

    r = client.get(f"/api/experiments/{exp_id}/schemes/{scheme['id']}/export?format=json")
    assert r.status_code == 200
    report = r.json()
    assert report["interpolation"]["method_id"] == "pchip"
    assert report["interpolation"]["applicable_range"]["temperature_max_c"] == 412.0
    assert "不外推" in report["disclaimer"]
    assert report["analysis"]["fractions"][2]["temp_end_c"] == pytest.approx(322.0)

    r = client.get(f"/api/experiments/{exp_id}/schemes/{scheme['id']}/export?format=csv")
    assert r.status_code == 200
    text = r.text
    assert "插值方法" in text
    assert "适用范围" in text
    assert "PCHIP" in text
    assert "总量平衡" in text


def test_export_missing_scheme_404(client, exp_id):
    r = client.get(f"/api/experiments/{exp_id}/schemes/999/export")
    assert r.status_code == 404
