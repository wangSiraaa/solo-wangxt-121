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
}


class ConflictError(Exception):
    """基于过期版本的操作：返回 409，绝不覆盖他人修改。"""

    def __init__(self, message: str, current_revision: int):
        super().__init__(message)
        self.current_revision = current_revision


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
            current,
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
    actor: str = "",
    idempotency_key: str | None = None,
    note: str = "",
) -> tuple[models.CutScheme, models.AuditRecord]:
    """撤回：待审核 -> 草稿；已发布 -> 已撤回（版本快照保留为历史）。"""
    _check_revision(scheme, base_revision)
    from_status = scheme.current_status
    if from_status == PENDING:
        to_status = DRAFT
    elif from_status == PUBLISHED:
        to_status = WITHDRAWN
    else:
        raise InvalidTransitionError(f"当前状态为 {from_status}，仅待审核或已发布方案可撤回")
    _touch(scheme, to_status)
    audit = _audit(
        db, scheme, action="withdraw", from_status=from_status, to_status=to_status,
        actor=actor, idempotency_key=idempotency_key,
        detail={"revision": scheme.current_revision, "note": note},
    )
    return scheme, audit


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
