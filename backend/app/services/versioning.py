"""方案版本化：状态机、乐观锁、幂等、不可变快照、审计。

状态机：
    draft --submit--> pending_review --approve--> published --withdraw--> withdrawn
    pending_review --withdraw--> draft
    draft / published / withdrawn --save_draft--> draft（工作副本可继续编辑，
    已发布的版本快照不受影响）

幂等：调用方在 Idempotency-Key 头中携带唯一键；命中已有审计记录时直接回放
当时的响应，不重复写库。服务重启后状态全部在数据库中，可恢复。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from . import assembly
from .fractions import FractionInput
from .report import build_report

DRAFT = "draft"
PENDING = "pending_review"
PUBLISHED = "published"
WITHDRAWN = "withdrawn"

ACTION_LABELS = {
    "create": "创建方案",
    "save_draft": "保存草稿",
    "submit": "提交审核",
    "approve": "审核通过（发布）",
    "withdraw": "撤回",
    "copy": "基于历史版本复制",
    "switch": "切换生效版本",
}


class ConflictError(Exception):
    """可见冲突（HTTP 409）：过期修订号、生效版本不一致、撤回缺继任等。"""

    def __init__(self, message: str, *, code: str = "REVISION_CONFLICT", payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


class InvalidTransitionError(Exception):
    """当前状态不允许的迁移。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def find_replay(db: Session, idempotency_key: str | None) -> models.AuditRecord | None:
    """按幂等键查找已完成的操作。"""
    if not idempotency_key:
        return None
    return (
        db.query(models.AuditRecord)
        .filter(models.AuditRecord.idempotency_key == idempotency_key)
        .first()
    )


def _check_revision(scheme: models.CutScheme, base_revision: int) -> None:
    current = scheme.current_revision
    if base_revision != current:
        raise ConflictError(
            f"版本冲突：基于 r{base_revision} 的操作已被拒绝，当前版本为 r{current}，"
            f"请刷新获取最新内容后重试",
            code="REVISION_CONFLICT",
            payload={"current_revision": current},
        )


def _audit(
    db: Session,
    scheme: models.CutScheme,
    *,
    action: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    idempotency_key: str | None,
    version_id: int | None = None,
    detail: dict | None = None,
) -> models.AuditRecord:
    rec = models.AuditRecord(
        scheme_id=scheme.id,
        version_id=version_id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        idempotency_key=idempotency_key,
        detail_json=detail or {},
    )
    db.add(rec)
    db.flush()
    return rec


def _touch(scheme: models.CutScheme, status: str) -> None:
    scheme.status = status
    _bump_revision(scheme)


def _bump_revision(scheme: models.CutScheme) -> None:
    scheme.revision = scheme.current_revision + 1
    scheme.updated_at = _utcnow()


def create_scheme(
    db: Session,
    exp: models.Experiment,
    *,
    name: str,
    fractions: list[FractionInput],
    actor: str = "",
    idempotency_key: str | None = None,
) -> tuple[models.CutScheme, models.AuditRecord]:
    scheme = models.CutScheme(
        experiment_id=exp.id,
        name=name,
        status=DRAFT,
        revision=1,
        cuts=[
            models.SchemeCut(position=i, label=f.label, start_pct=f.start_pct, end_pct=f.end_pct)
            for i, f in enumerate(fractions)
        ],
    )
    db.add(scheme)
    db.flush()
    audit = _audit(
        db, scheme, action="create", from_status=None, to_status=DRAFT,
        actor=actor, idempotency_key=idempotency_key,
        detail={"revision": 1},
    )
    return scheme, audit


def save_draft(
    db: Session,
    scheme: models.CutScheme,
    *,
    name: str,
    fractions: list[FractionInput],
    base_revision: int,
    actor: str = "",
    idempotency_key: str | None = None,
) -> tuple[models.CutScheme, models.AuditRecord]:
    _check_revision(scheme, base_revision)
    from_status = scheme.current_status
    if from_status == PENDING:
        raise InvalidTransitionError("方案正在待审核，不可编辑；请先撤回或等待审核完成")
    scheme.cuts = [
        models.SchemeCut(position=i, label=f.label, start_pct=f.start_pct, end_pct=f.end_pct)
        for i, f in enumerate(fractions)
    ]
    scheme.name = name
    _touch(scheme, DRAFT)
    audit = _audit(
        db, scheme, action="save_draft", from_status=from_status, to_status=DRAFT,
        actor=actor, idempotency_key=idempotency_key,
        detail={"revision": scheme.current_revision},
    )
    return scheme, audit


def submit(
    db: Session,
    scheme: models.CutScheme,
    *,
    base_revision: int,
    actor: str = "",
    idempotency_key: str | None = None,
    note: str = "",
) -> tuple[models.CutScheme, models.AuditRecord]:
    _check_revision(scheme, base_revision)
    from_status = scheme.current_status
    if from_status != DRAFT:
        raise InvalidTransitionError(f"当前状态为 {from_status}，仅草稿可提交审核")
    _touch(scheme, PENDING)
    audit = _audit(
        db, scheme, action="submit", from_status=from_status, to_status=PENDING,
        actor=actor, idempotency_key=idempotency_key,
        detail={"revision": scheme.current_revision, "note": note},
    )
    return scheme, audit


def approve(
    db: Session,
    scheme: models.CutScheme,
    *,
    base_revision: int,
    actor: str = "",
    idempotency_key: str | None = None,
    note: str = "",
) -> tuple[models.CutScheme, models.SchemeVersion, models.AuditRecord]:
    """审核通过：生成不可变版本快照，冻结当时的切点/密度/插值范围。"""
    _check_revision(scheme, base_revision)
    from_status = scheme.current_status
    if from_status != PENDING:
        raise InvalidTransitionError(f"当前状态为 {from_status}，仅待审核方案可审核通过")

    exp = scheme.experiment
    fractions = [FractionInput(c.label, c.start_pct, c.end_pct) for c in scheme.cuts]
    analysis = assembly.run_analysis(exp, fractions)
    published_at = _utcnow().isoformat()
    version_no = len(scheme.versions) + 1
    report = build_report(
        exp,
        scheme_id=scheme.id,
        scheme_name=scheme.name,
        fractions=fractions,
        frozen=True,
        version_no=version_no,
        published_at=published_at,
    )
    curve = assembly.build_curve(exp)
    version = models.SchemeVersion(
        scheme_id=scheme.id,
        version_no=version_no,
        note=note,
        fractions_json=[{"label": f.label, "start_pct": f.start_pct, "end_pct": f.end_pct} for f in fractions],
        densities_json=[
            {"label": d.label, "start_pct": d.start_pct, "end_pct": d.end_pct, "density_kg_m3": d.density_kg_m3}
            for d in exp.densities
        ],
        curve_json={
            "points": [
                {"recovery_pct": r, "temperature_c": t} for r, t in assembly.sorted_points(exp)
            ],
            "interpolation": assembly.interpolation_meta(curve),
        },
        analysis_json=analysis.as_dict(),
        report_json=report,
    )
    db.add(version)
    db.flush()
    _touch(scheme, PUBLISHED)
    # 新发布的版本自动成为当前生效版本
    scheme.active_version_id = version.id
    audit = _audit(
        db, scheme, action="approve", from_status=from_status, to_status=PUBLISHED,
        actor=actor, idempotency_key=idempotency_key, version_id=version.id,
        detail={"revision": scheme.current_revision, "version_no": version_no, "note": note},
    )
    return scheme, version, audit


def withdraw(
    db: Session,
    scheme: models.CutScheme,
    *,
    base_revision: int,
    successor_version_id: int | None = None,
    actor: str = "",
    idempotency_key: str | None = None,
    note: str = "",
) -> tuple[models.CutScheme, models.AuditRecord]:
    """撤回：待审核 -> 草稿；已发布 -> 已撤回（版本快照保留为历史）。

    明确规则：撤回已发布方案时若仍存在生效版本指针，必须显式指定继任的
    历史版本（successor_version_id），否则拒绝 —— 不允许静默丢失生效指针。
    指定继任时，切换与撤回在同一事务内原子完成（两条审计记录）。
    """
    _check_revision(scheme, base_revision)
    from_status = scheme.current_status
    if from_status == PENDING:
        to_status = DRAFT
    elif from_status == PUBLISHED:
        to_status = WITHDRAWN
        if scheme.active_version_id is not None:
            available = [v for v in scheme.versions if v.id != scheme.active_version_id]
            if successor_version_id is None:
                raise ConflictError(
                    "撤回当前生效发布版本会失去生效指针，已拒绝："
                    "请指定继任的历史版本（successor_version_id）后重试",
                    code="ACTIVE_VERSION_REQUIRES_SUCCESSOR",
                    payload={
                        "active_version_id": scheme.active_version_id,
                        "available_versions": [
                            {"id": v.id, "version_no": v.version_no} for v in available
                        ],
                    },
                )
            successor = next(
                (v for v in available if v.id == successor_version_id), None
            )
            if successor is None:
                raise ConflictError(
                    f"继任版本 {successor_version_id} 不可用：必须选择该方案的其他已发布版本",
                    code="ACTIVE_VERSION_REQUIRES_SUCCESSOR",
                    payload={
                        "active_version_id": scheme.active_version_id,
                        "available_versions": [
                            {"id": v.id, "version_no": v.version_no} for v in available
                        ],
                    },
                )
            # 先切换生效指针（原子同事务），再撤回
            from_version = next(
                (v for v in scheme.versions if v.id == scheme.active_version_id), None
            )
            scheme.active_version_id = successor.id
            _audit(
                db, scheme, action="switch",
                from_status=from_status, to_status=from_status,
                actor=actor, idempotency_key=None, version_id=successor.id,
                detail={
                    "from_version_id": from_version.id if from_version else None,
                    "from_version_no": from_version.version_no if from_version else None,
                    "to_version_id": successor.id,
                    "to_version_no": successor.version_no,
                    "reason": "withdraw_successor",
                },
            )
    else:
        raise InvalidTransitionError(f"当前状态为 {from_status}，仅待审核或已发布方案可撤回")
    _touch(scheme, to_status)
    audit = _audit(
        db, scheme, action="withdraw", from_status=from_status, to_status=to_status,
        actor=actor, idempotency_key=idempotency_key,
        detail={
            "revision": scheme.current_revision,
            "note": note,
            "successor_version_id": successor_version_id,
        },
    )
    return scheme, audit


def switch_active_version(
    db: Session,
    scheme: models.CutScheme,
    *,
    target: models.SchemeVersion,
    expected_active_version_id: int | None,
    base_revision: int,
    actor: str = "",
    idempotency_key: str | None = None,
    note: str = "",
) -> tuple[models.CutScheme, models.AuditRecord | None, bool]:
    """受控切换当前生效版本。

    只移动生效指针并写新审计事件，不改写任何旧快照、旧报告或原审核记录。
    请求必须携带当前生效版本与修订号；目标已是生效版本时为幂等空操作。
    返回 (scheme, audit|None, changed)。
    """
    _check_revision(scheme, base_revision)
    current = scheme.active_version_id
    if expected_active_version_id != current:
        raise ConflictError(
            f"生效版本冲突：请求基于生效版本 {expected_active_version_id}，"
            f"当前生效版本为 {current}，请刷新后重试",
            code="ACTIVE_VERSION_CONFLICT",
            payload={"current_active_version_id": current},
        )
    if target.id == current:
        return scheme, None, False  # 已是生效版本：幂等空操作，不写审计
    from_version = next((v for v in scheme.versions if v.id == current), None)
    scheme.active_version_id = target.id
    _bump_revision(scheme)
    audit = _audit(
        db, scheme, action="switch",
        from_status=scheme.current_status, to_status=scheme.current_status,
        actor=actor, idempotency_key=idempotency_key, version_id=target.id,
        detail={
            "from_version_id": from_version.id if from_version else None,
            "from_version_no": from_version.version_no if from_version else None,
            "to_version_id": target.id,
            "to_version_no": target.version_no,
            "note": note,
            "revision": scheme.current_revision,
        },
    )
    return scheme, audit, True


def copy_version(
    db: Session,
    version: models.SchemeVersion,
    *,
    actor: str = "",
    idempotency_key: str | None = None,
    new_name: str | None = None,
) -> tuple[models.CutScheme, models.AuditRecord]:
    """基于历史版本复制出一个新草稿方案。"""
    src = version.scheme
    name = new_name or f"{src.name}（基于 v{version.version_no} 复制）"
    scheme = models.CutScheme(
        experiment_id=src.experiment_id,
        name=name,
        status=DRAFT,
        revision=1,
        cuts=[
            models.SchemeCut(
                position=i,
                label=f["label"],
                start_pct=f["start_pct"],
                end_pct=f["end_pct"],
            )
            for i, f in enumerate(version.fractions_json)
        ],
    )
    db.add(scheme)
    db.flush()
    audit = _audit(
        db, scheme, action="copy", from_status=None, to_status=DRAFT,
        actor=actor, idempotency_key=idempotency_key,
        detail={"source_scheme_id": src.id, "source_version_id": version.id,
                "source_version_no": version.version_no},
    )
    return scheme, audit
