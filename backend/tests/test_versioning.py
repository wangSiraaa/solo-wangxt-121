"""版本化验收测试：状态机、冻结导出、乐观锁冲突、幂等、重启恢复、旧数据兼容。"""
import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, ensure_schema
from app.main import app

FOUR = [
    {"label": "石脑油", "start_pct": 0, "end_pct": 20},
    {"label": "煤油", "start_pct": 20, "end_pct": 40},
    {"label": "柴油", "start_pct": 40, "end_pct": 70},
    {"label": "重油", "start_pct": 70, "end_pct": 96.5},
]
TWO = [
    {"label": "轻组", "start_pct": 0, "end_pct": 50},
    {"label": "重组", "start_pct": 50, "end_pct": 96.5},
]


@pytest.fixture()
def exp_id(client, exp2_payload):
    r = client.post("/api/experiments", json=exp2_payload)
    assert r.status_code == 201
    return r.json()["id"]


def create_scheme(client, exp_id, fractions=FOUR, name="验收方案", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    r = client.post(
        f"/api/experiments/{exp_id}/schemes",
        json={"name": name, "fractions": fractions},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def save_draft(client, sid, revision, fractions, name="验收方案", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.put(
        f"/api/schemes/{sid}/draft",
        json={"name": name, "fractions": fractions, "base_revision": revision},
        headers=headers,
    )


def transition(client, sid, action, revision, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/api/schemes/{sid}/{action}",
        json={"base_revision": revision},
        headers=headers,
    )


def publish(client, exp_id, fractions=FOUR):
    """走完 草稿->提交->发布，返回 (scheme_state, version_id)。"""
    s = create_scheme(client, exp_id, fractions)
    r = transition(client, s["id"], "submit", s["revision"])
    assert r.status_code == 200, r.text
    r = transition(client, s["id"], "approve", r.json()["revision"])
    assert r.status_code == 200, r.text
    return r.json(), r.json()["version"]["id"]


# ---- 验收 1：发布后导出被冻结 ---------------------------------------------
def test_publish_then_export_frozen(client, exp_id, exp2_payload):
    state, vid = publish(client, exp_id)
    assert state["status"] == "published"

    r1 = client.get(f"/api/scheme-versions/{vid}/export?format=json").json()
    assert r1["frozen"] is True
    assert r1["version"]["version_no"] == 1
    assert r1["analysis"]["fractions"][0]["temp_start_c"] == pytest.approx(38.0)

    # 修改试验曲线（整体温度 +50）与密度
    modified = dict(exp2_payload)
    modified["points"] = [
        {"recovery_pct": p["recovery_pct"], "temperature_c": p["temperature_c"] + 50}
        for p in exp2_payload["points"]
    ]
    modified["densities"] = [
        {**d, "density_kg_m3": d["density_kg_m3"] + 100} for d in exp2_payload["densities"]
    ]
    r = client.put(f"/api/experiments/{exp_id}", json=modified)
    assert r.status_code == 200

    # 修改草稿（发布后工作副本可继续编辑，状态回到草稿）
    r = save_draft(client, state["id"], state["revision"], TWO)
    assert r.status_code == 200
    assert r.json()["status"] == "draft"

    # 历史版本导出不变：逐字节相同
    r2 = client.get(f"/api/scheme-versions/{vid}/export?format=json").json()
    assert r2 == r1
    csv2 = client.get(f"/api/scheme-versions/{vid}/export?format=csv").text
    assert "v1（已发布，内容冻结）" in csv2
    assert "38.0000" in csv2  # 仍是旧曲线温度

    # 工作副本实时导出反映新数据，与冻结报告不同
    live = client.get(f"/api/experiments/{exp_id}/schemes/{state['id']}/export?format=json").json()
    assert live["frozen"] is False
    assert live["analysis"]["fractions"][0]["temp_start_c"] == pytest.approx(88.0)


# ---- 验收 2：两个窗口保存同一版本 -> 后者冲突 ------------------------------
def test_two_windows_conflict(client, exp_id):
    s = create_scheme(client, exp_id)
    sid, rev = s["id"], s["revision"]

    # 窗口 A 先保存
    ra = save_draft(client, sid, rev, TWO, name="窗口A")
    assert ra.status_code == 200
    assert ra.json()["revision"] == rev + 1

    # 窗口 B 基于过期版本保存 -> 409 冲突
    rb = save_draft(client, sid, rev, FOUR, name="窗口B")
    assert rb.status_code == 409
    assert rb.json()["code"] == "REVISION_CONFLICT"
    assert rb.json()["current_revision"] == rev + 1

    # 前一版本内容保留
    cur = client.get(f"/api/schemes/{sid}").json()
    assert cur["name"] == "窗口A"
    assert [f["label"] for f in cur["fractions"]] == ["轻组", "重组"]

    # B 刷新后基于新版本可正常保存
    rb2 = save_draft(client, sid, cur["revision"], FOUR, name="窗口B")
    assert rb2.status_code == 200

    # 过期审核同样冲突
    s2 = create_scheme(client, exp_id, name="审核冲突演示")
    transition(client, s2["id"], "submit", s2["revision"])
    r = transition(client, s2["id"], "approve", 1)  # 过期 revision
    assert r.status_code == 409
    assert r.json()["code"] == "REVISION_CONFLICT"


# ---- 验收 3：重复提交/重试不产生重复审计 -----------------------------------
def test_idempotent_retry_no_duplicate_audit(client, exp_id):
    # 创建幂等
    s1 = create_scheme(client, exp_id, key="create-001")
    headers = {"Idempotency-Key": "create-001"}
    r = client.post(
        f"/api/experiments/{exp_id}/schemes",
        json={"name": "验收方案", "fractions": FOUR},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.headers.get("Idempotent-Replay") == "true"
    assert r.json()["id"] == s1["id"]
    assert len(client.get(f"/api/experiments/{exp_id}/schemes").json()) == 1

    # 提交审核幂等
    sid = s1["id"]
    r1 = transition(client, sid, "submit", s1["revision"], key="submit-001")
    assert r1.status_code == 200
    r2 = transition(client, sid, "submit", s1["revision"], key="submit-001")
    assert r2.status_code == 200
    assert r2.headers.get("Idempotent-Replay") == "true"

    # 审核通过幂等：重复重试只生成一个版本、一条 approve 审计
    rev = r1.json()["revision"]
    a1 = transition(client, sid, "approve", rev, key="approve-001")
    assert a1.status_code == 200
    a2 = transition(client, sid, "approve", rev, key="approve-001")
    assert a2.headers.get("Idempotent-Replay") == "true"

    detail = client.get(f"/api/schemes/{sid}").json()
    assert len(detail["versions"]) == 1
    submits = [a for a in detail["audits"] if a["action"] == "submit"]
    approves = [a for a in detail["audits"] if a["action"] == "approve"]
    assert len(submits) == 1
    assert len(approves) == 1


# ---- 验收 4：重启后状态与审计一致 ------------------------------------------
def test_restart_recovers_state(client, exp_id):
    s = create_scheme(client, exp_id, key="boot-1")
    transition(client, s["id"], "submit", s["revision"], key="boot-2")

    # 模拟服务重启：新建应用客户端，同一数据库
    with TestClient(app) as c2:
        detail = c2.get(f"/api/schemes/{s['id']}").json()
        assert detail["status"] == "pending_review"
        actions = [a["action"] for a in detail["audits"]]
        assert actions == ["create", "submit"]

        # 重启后继续审核通过，版本与审计连贯
        r = c2.post(
            f"/api/schemes/{s['id']}/approve",
            json={"base_revision": detail["revision"]},
            headers={"Idempotency-Key": "boot-3"},
        )
        assert r.status_code == 200
        vid = r.json()["version"]["id"]

    # 再次"重启"验证
    with TestClient(app) as c3:
        detail = c3.get(f"/api/schemes/{s['id']}").json()
        assert detail["status"] == "published"
        assert [a["action"] for a in detail["audits"]] == ["create", "submit", "approve"]
        rep = c3.get(f"/api/scheme-versions/{vid}/export?format=json").json()
        assert rep["frozen"] is True


def test_ensure_schema_idempotent():
    ensure_schema()
    ensure_schema()  # 重复执行不报错


# ---- 验收 5：旧方案（无版本状态）兼容 ---------------------------------------
def test_legacy_scheme_editable_and_publishable(client, exp_id):
    # 直接写入一条无状态/无修订号的旧数据
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    legacy = models.CutScheme(
        experiment_id=exp_id,
        name="旧版方案",
        status=None,
        revision=None,
        cuts=[models.SchemeCut(position=0, label="全馏分", start_pct=0, end_pct=96.5)],
    )
    db.add(legacy)
    db.commit()
    sid = legacy.id
    db.close()

    # 载入：按旧草稿处理
    detail = client.get(f"/api/schemes/{sid}").json()
    assert detail["status"] == "draft"
    assert detail["revision"] == 1

    # 编辑
    r = save_draft(client, sid, 1, FOUR, name="旧版方案-改")
    assert r.status_code == 200

    # 发布
    r = transition(client, sid, "submit", r.json()["revision"])
    assert r.status_code == 200
    r = transition(client, sid, "approve", r.json()["revision"])
    assert r.status_code == 200
    assert r.json()["status"] == "published"
    vid = r.json()["version"]["id"]
    rep = client.get(f"/api/scheme-versions/{vid}/export?format=json").json()
    assert rep["frozen"] is True


# ---- 状态机与复制 -----------------------------------------------------------
def test_invalid_transitions_rejected(client, exp_id):
    s = create_scheme(client, exp_id)
    sid = s["id"]
    # 草稿直接审核通过 -> 409
    r = transition(client, sid, "approve", s["revision"])
    assert r.status_code == 409
    assert r.json()["code"] == "INVALID_TRANSITION"
    # 草稿撤回 -> 409
    r = transition(client, sid, "withdraw", s["revision"])
    assert r.status_code == 409
    # 提交后不可编辑
    r = transition(client, sid, "submit", s["revision"])
    rev = r.json()["revision"]
    r = save_draft(client, sid, rev, TWO)
    assert r.status_code == 409
    assert r.json()["code"] == "INVALID_TRANSITION"
    # 重复提交 -> 409
    r = transition(client, sid, "submit", rev)
    assert r.status_code == 409
    # 撤回后回到草稿可编辑
    r = transition(client, sid, "withdraw", rev)
    assert r.json()["status"] == "draft"
    r = save_draft(client, sid, r.json()["revision"], TWO)
    assert r.status_code == 200


def test_withdraw_published_requires_successor(client, exp_id):
    """撤回唯一生效版本：按明确规则拒绝，生效指针不丢失。"""
    state, vid = publish(client, exp_id)
    r = transition(client, state["id"], "withdraw", state["revision"])
    assert r.status_code == 409
    assert r.json()["code"] == "ACTIVE_VERSION_REQUIRES_SUCCESSOR"
    assert r.json()["available_versions"] == []
    # 生效指针保留，快照仍可只读查询
    detail = client.get(f"/api/schemes/{state['id']}").json()
    assert detail["status"] == "published"
    assert detail["active_version_id"] == vid
    rep = client.get(f"/api/scheme-versions/{vid}/export?format=json").json()
    assert rep["frozen"] is True


def test_copy_from_version_creates_new_draft(client, exp_id):
    state, vid = publish(client, exp_id)
    r = client.post(f"/api/scheme-versions/{vid}/copy")
    assert r.status_code == 201
    new_scheme = r.json()
    assert new_scheme["id"] != state["id"]
    assert new_scheme["status"] == "draft"
    assert new_scheme["revision"] == 1
    assert [f["label"] for f in new_scheme["fractions"]] == [f["label"] for f in FOUR]
    audits = client.get(f"/api/schemes/{new_scheme['id']}").json()["audits"]
    assert audits[0]["action"] == "copy"
    assert audits[0]["detail"]["source_version_no"] == 1


def test_version_detail_query(client, exp_id):
    state, vid = publish(client, exp_id)
    v = client.get(f"/api/scheme-versions/{vid}").json()
    assert v["version_no"] == 1
    assert len(v["fractions"]) == 4
    assert len(v["densities"]) == 4
    assert v["curve"]["interpolation"]["applicable_range"]["recovery_max_pct"] == 96.5
    assert v["analysis"]["balance_ok"] is True
    # 时间线：创建/提交/发布均在审计中
    detail = client.get(f"/api/schemes/{state['id']}").json()
    assert [a["action"] for a in detail["audits"]] == ["create", "submit", "approve"]
