"""生效版本受控切换与版本差异审阅的验收测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

FOUR = [
    {"label": "石脑油", "start_pct": 0, "end_pct": 20},
    {"label": "煤油", "start_pct": 20, "end_pct": 40},
    {"label": "柴油", "start_pct": 40, "end_pct": 70},
    {"label": "重油", "start_pct": 70, "end_pct": 96.5},
]
# v2：切点调整（石脑油扩到25、柴油扩到75、重油到98）
FOUR_V2 = [
    {"label": "石脑油", "start_pct": 0, "end_pct": 25},
    {"label": "煤油", "start_pct": 25, "end_pct": 40},
    {"label": "柴油", "start_pct": 40, "end_pct": 75},
    {"label": "重油", "start_pct": 75, "end_pct": 98},
]


@pytest.fixture()
def exp_id(client, exp2_payload):
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201
    return r.json()["id"]


def _create(client, exp_id, fractions=FOUR, name="生效版本方案"):
    r = client.post(f"/api/experiments/{exp_id}/schemes",
                    json={"name": name, "fractions": fractions})
    assert r.status_code == 201, r.text
    return r.json()


def _transition(client, sid, action, revision, key=None, extra=None):
    headers = {"Idempotency-Key": key} if key else {}
    body = {"base_revision": revision, **(extra or {})}
    return client.post(f"/api/schemes/{sid}/{action}", json=body, headers=headers)


def _publish(client, exp_id, fractions=FOUR):
    s = _create(client, exp_id, fractions)
    r = _transition(client, s["id"], "submit", s["revision"])
    assert r.status_code == 200, r.text
    r = _transition(client, s["id"], "approve", r.json()["revision"])
    assert r.status_code == 200, r.text
    return r.json(), r.json()["version"]["id"]


def _edit_and_republish(client, exp_id, sid, revision, fractions):
    r = client.put(f"/api/schemes/{sid}/draft",
                   json={"name": "生效版本方案", "fractions": fractions,
                         "base_revision": revision})
    assert r.status_code == 200, r.text
    r = _transition(client, sid, "submit", r.json()["revision"])
    assert r.status_code == 200, r.text
    r = _transition(client, sid, "approve", r.json()["revision"])
    assert r.status_code == 200, r.text
    return r.json()


def _switch(client, sid, target, expected, revision, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/api/schemes/{sid}/switch-version",
        json={"target_version_id": target,
              "expected_active_version_id": expected,
              "base_revision": revision},
        headers=headers,
    )


@pytest.fixture()
def two_versions(client, exp_id, exp2_payload):
    """发布 v1 后修改试验（扩曲线+改密度）并发布 v2，返回 (sid, v1_id, v2_id, state)。"""
    state, v1 = _publish(client, exp_id)
    sid = state["id"]
    # 修改试验：曲线延伸到 98%，柴油密度 845->850
    modified = dict(exp2_payload)
    modified["points"] = exp2_payload["points"] + [
        {"recovery_pct": 98.0, "temperature_c": 420.0}
    ]
    modified["densities"] = [
        {**d, "density_kg_m3": 850.0} if d["label"] == "柴油" else d
        for d in exp2_payload["densities"]
    ]
    r = client.put(f"/api/experiments/{exp_id}", json=modified)
    assert r.status_code == 200
    state2 = _edit_and_republish(client, exp_id, sid, state["revision"], FOUR_V2)
    v2 = state2["version"]["id"]
    return sid, v1, v2, state2


# ---- 验收 1：v1->v2 差异准确，两版导出各自冻结 ------------------------------
def test_diff_and_frozen_exports(two_versions, client):
    sid, v1, v2, state2 = two_versions
    # 发布后生效指针自动指向 v2
    assert state2["active_version_id"] == v2
    cur = client.get(f"/api/schemes/{sid}/current-version").json()
    assert cur["version"]["id"] == v2
    assert cur["version"]["version_no"] == 2

    d = client.get(f"/api/schemes/{sid}/diff?from_id={v1}&to_id={v2}").json()
    assert d["from"]["version_no"] == 1 and d["to"]["version_no"] == 2

    # 切点变化：石脑油 end 20->25，柴油 end 70->75，重油 70~96.5 -> 75~98
    frac_changes = {c["label"]: {ch["field"]: ch for ch in c["changes"]}
                    for c in d["fractions"]["changed"]}
    assert frac_changes["石脑油"]["end_pct"]["from"] == 20
    assert frac_changes["石脑油"]["end_pct"]["to"] == 25
    assert frac_changes["重油"]["start_pct"]["to"] == 75
    assert frac_changes["重油"]["end_pct"]["to"] == 98
    assert d["fractions"]["added"] == [] and d["fractions"]["removed"] == []

    # 密度变化：柴油 845 -> 850
    dens_changes = {c["label"]: c["changes"] for c in d["densities"]["changed"]}
    assert dens_changes["柴油"][0]["from"] == 845.0
    assert dens_changes["柴油"][0]["to"] == 850.0

    # 插值范围变化：回收率上限 96.5 -> 98，温度上限 412 -> 420
    rng = {c["field"]: c for c in d["interpolation"]["range_changes"]}
    assert rng["recovery_max_pct"]["from"] == 96.5
    assert rng["recovery_max_pct"]["to"] == 98.0
    assert rng["temperature_max_pct".replace("pct", "c")]["to"] == 420.0
    assert d["interpolation"]["method_changed"] is False

    # 产率差异：石脑油占进料 20 -> 25
    yields = {y["label"]: y for y in d["yields"]}
    assert yields["石脑油"]["pct_of_feed"]["from"] == pytest.approx(20.0)
    assert yields["石脑油"]["pct_of_feed"]["to"] == pytest.approx(25.0)
    assert yields["石脑油"]["pct_of_feed"]["delta"] == pytest.approx(5.0)

    # 两版导出各自冻结且不同
    r1 = client.get(f"/api/scheme-versions/{v1}/export?format=json").json()
    r2 = client.get(f"/api/scheme-versions/{v2}/export?format=json").json()
    assert r1["frozen"] and r2["frozen"]
    assert r1["interpolation"]["applicable_range"]["recovery_max_pct"] == 96.5
    assert r2["interpolation"]["applicable_range"]["recovery_max_pct"] == 98.0
    assert r1["analysis"]["fractions"][0]["pct_of_feed"] == pytest.approx(20.0)
    assert r2["analysis"]["fractions"][0]["pct_of_feed"] == pytest.approx(25.0)


# ---- 验收 2：两个窗口先后切换 -> 后者冲突，前一生效版本保留 -------------------
def test_concurrent_switch_conflict(two_versions, client):
    sid, v1, v2, state2 = two_versions
    rev = state2["revision"]

    # 窗口 A 切换到 v1
    ra = _switch(client, sid, target=v1, expected=v2, revision=rev)
    assert ra.status_code == 200, ra.text
    assert ra.json()["changed"] is True
    assert ra.json()["active_version_id"] == v1

    # 窗口 B 基于过期状态切换 -> 409 可见冲突
    rb = _switch(client, sid, target=v1, expected=v2, revision=rev)
    assert rb.status_code == 409
    assert rb.json()["code"] in ("REVISION_CONFLICT", "ACTIVE_VERSION_CONFLICT")

    # 生效版本保持 A 的结果
    cur = client.get(f"/api/schemes/{sid}/current-version").json()
    assert cur["version"]["id"] == v1

    # B 刷新后可正常切换
    detail = client.get(f"/api/schemes/{sid}").json()
    rb2 = _switch(client, sid, target=v2, expected=v1, revision=detail["revision"])
    assert rb2.status_code == 200
    assert rb2.json()["active_version_id"] == v2

    # 切换只写新审计，不改写旧快照：v1 导出仍冻结为原内容
    r1 = client.get(f"/api/scheme-versions/{v1}/export?format=json").json()
    assert r1["analysis"]["fractions"][0]["pct_of_feed"] == pytest.approx(20.0)
    switches = [a for a in client.get(f"/api/schemes/{sid}").json()["audits"]
                if a["action"] == "switch"]
    assert len(switches) == 2
    assert switches[0]["detail"]["to_version_no"] == 1
    assert switches[1]["detail"]["to_version_no"] == 2


def test_switch_with_stale_expected_active_conflicts(two_versions, client):
    sid, v1, v2, state2 = two_versions
    # expected_active 传错（谎称当前生效是 v1）
    r = _switch(client, sid, target=v1, expected=v1, revision=state2["revision"])
    assert r.status_code == 409
    assert r.json()["code"] == "ACTIVE_VERSION_CONFLICT"
    assert r.json()["current_active_version_id"] == v2


def test_switch_to_current_is_noop(two_versions, client):
    sid, v1, v2, state2 = two_versions
    r = _switch(client, sid, target=v2, expected=v2, revision=state2["revision"])
    assert r.status_code == 200
    assert r.json()["changed"] is False
    # 空操作不写审计
    switches = [a for a in client.get(f"/api/schemes/{sid}").json()["audits"]
                if a["action"] == "switch"]
    assert switches == []


# ---- 验收 3：切换幂等 + 重启恢复 ---------------------------------------------
def test_switch_idempotent_and_restart(two_versions, client):
    sid, v1, v2, state2 = two_versions
    r1 = _switch(client, sid, target=v1, expected=v2,
                 revision=state2["revision"], key="sw-001")
    assert r1.status_code == 200
    r2 = _switch(client, sid, target=v1, expected=v2,
                 revision=state2["revision"], key="sw-001")
    assert r2.status_code == 200
    assert r2.headers.get("Idempotent-Replay") == "true"

    # 只留一条切换审计
    detail = client.get(f"/api/schemes/{sid}").json()
    switches = [a for a in detail["audits"] if a["action"] == "switch"]
    assert len(switches) == 1

    # 模拟重启：新客户端读取，生效指针与导出一致
    with TestClient(app) as c2:
        cur = c2.get(f"/api/schemes/{sid}/current-version").json()
        assert cur["version"]["id"] == v1
        d2 = c2.get(f"/api/schemes/{sid}").json()
        assert d2["active_version_id"] == v1
        assert len([a for a in d2["audits"] if a["action"] == "switch"]) == 1
        rep = c2.get(f"/api/scheme-versions/{v1}/export?format=json").json()
        assert rep["frozen"] is True
        assert rep["analysis"]["fractions"][0]["pct_of_feed"] == pytest.approx(20.0)


# ---- 验收 4：撤回当前版本不得静默丢失生效指针 ---------------------------------
def test_withdraw_active_with_successor(two_versions, client):
    sid, v1, v2, state2 = two_versions
    # 不指定继任 -> 409，列出可用历史版本
    r = _transition(client, sid, "withdraw", state2["revision"])
    assert r.status_code == 409
    assert r.json()["code"] == "ACTIVE_VERSION_REQUIRES_SUCCESSOR"
    assert r.json()["available_versions"] == [{"id": v1, "version_no": 1}]

    # 指定非法继任（当前生效版本自身）-> 409
    r = _transition(client, sid, "withdraw", state2["revision"],
                    extra={"successor_version_id": v2})
    assert r.status_code == 409

    # 指定 v1 继任 -> 原子完成切换+撤回
    r = _transition(client, sid, "withdraw", state2["revision"],
                    extra={"successor_version_id": v1}, key="wd-001")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "withdrawn"
    assert r.json()["active_version_id"] == v1

    detail = client.get(f"/api/schemes/{sid}").json()
    actions = [a["action"] for a in detail["audits"]]
    assert actions[-2:] == ["switch", "withdraw"]
    switch_audit = [a for a in detail["audits"] if a["action"] == "switch"][0]
    assert switch_audit["detail"]["reason"] == "withdraw_successor"

    # 两版快照与导出均未改写
    r1 = client.get(f"/api/scheme-versions/{v1}/export?format=json").json()
    r2 = client.get(f"/api/scheme-versions/{v2}/export?format=json").json()
    assert r1["frozen"] and r2["frozen"]
    assert r1["version"]["version_no"] == 1
    assert r2["version"]["version_no"] == 2


# ---- 验收 5：旧单版本方案迁移后行为保持 ---------------------------------------
def test_legacy_scheme_publish_and_behaviour(client, exp_id):
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    legacy = models.CutScheme(
        experiment_id=exp_id, name="旧单版本方案", status=None, revision=None,
        cuts=[models.SchemeCut(position=0, label="全馏分", start_pct=0, end_pct=96.5)],
    )
    db.add(legacy)
    db.commit()
    sid = legacy.id
    db.close()

    # 迁移后按草稿载入，走完整发布流程
    detail = client.get(f"/api/schemes/{sid}").json()
    assert detail["status"] == "draft" and detail["active_version_id"] is None
    r = _transition(client, sid, "submit", detail["revision"])
    r = _transition(client, sid, "approve", r.json()["revision"])
    assert r.status_code == 200
    vid = r.json()["version"]["id"]

    # 发布后生效指针自动设置
    cur = client.get(f"/api/schemes/{sid}/current-version").json()
    assert cur["version"]["id"] == vid

    # 实时分析、质量/体积换算、不外推行为保持
    ana = client.post(f"/api/experiments/{exp_id}/analyze",
                      json={"fractions": FOUR}).json()
    assert ana["balance_ok"] is True
    fr = ana["fractions"][0]
    assert fr["mass_pct_of_recovered"] != fr["vol_pct_of_recovered"]
    r = client.post(f"/api/experiments/{exp_id}/interpolate",
                    json={"recovery_pct": 99})
    assert r.status_code == 422
    assert "不外推" in r.json()["detail"]
