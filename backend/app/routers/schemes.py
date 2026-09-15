"""方案版本化接口：草稿、状态迁移、版本查询、审计、复制。

幂等约定：客户端在 Idempotency-Key 请求头中携带唯一键；
重复提交命中已有审计记录时回放当时的响应（Idempotent-Replay: true），
不会产生第二条审计记录。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..services import assembly, versioning
from ..services.fractions import FractionInput
from ..services.versioning import ACTION_LABELS
from .experiments import load_experiment

router = APIRouter(prefix="/api", tags=["schemes"])


# ---- 装载与响应 ---------------------------------------------------------
def load_scheme(db: Session, scheme_id: int) -> models.CutScheme:
    scheme = (
        db.query(models.CutScheme)
        .options(
            selectinload(models.CutScheme.cuts),
            selectinload(models.CutScheme.versions),
            selectinload(models.CutScheme.experiment).selectinload(models.Experiment.points),
            selectinload(models.CutScheme.experiment).selectinload(models.Experiment.densities),
        )
        .filter(models.CutScheme.id == scheme_id)
        .first()
    )
    if scheme is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    return scheme


def _fractions_of(scheme: models.CutScheme) -> list[FractionInput]:
    return [FractionInput(c.label, c.start_pct, c.end_pct) for c in scheme.cuts]


def _state_dict(scheme: models.CutScheme) -> dict:
    """工作副本当前状态 + 实时分析（供保存/迁移后返回）。"""
    analysis = assembly.run_analysis(scheme.experiment, _fractions_of(scheme))
    return {
        "id": scheme.id,
        "experiment_id": scheme.experiment_id,
        "name": scheme.name,
        "status": scheme.current_status,
        "revision": scheme.current_revision,
        "fractions": [
            {"label": c.label, "start_pct": c.start_pct, "end_pct": c.end_pct}
            for c in scheme.cuts
        ],
        "analysis": analysis.as_dict(),
    }


def _replay(db: Session, key: str | None):
    rec = versioning.find_replay(db, key)
    if rec is not None and rec.response_json is not None:
        return JSONResponse(
            content=rec.response_json,
            status_code=200,
            headers={"Idempotent-Replay": "true"},
        )
    return None


def _finish(db: Session, audit: models.AuditRecord, payload: dict, status_code: int = 200):
    """把响应写入审计记录并提交，保证重试时可回放。"""
    audit.response_json = payload
    db.commit()
    return JSONResponse(content=payload, status_code=status_code)


# ---- 创建与查询 ---------------------------------------------------------
@router.post("/experiments/{experiment_id}/schemes", status_code=201)
def create_scheme(
    experiment_id: int,
    payload: schemas.SchemeIn,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    exp = load_experiment(db, experiment_id)
    fractions = [FractionInput(f.label, f.start_pct, f.end_pct) for f in payload.fractions]
    scheme, audit = versioning.create_scheme(
        db, exp, name=payload.name, fractions=fractions,
        actor=x_actor, idempotency_key=idempotency_key,
    )
    return _finish(db, audit, _state_dict(scheme), status_code=201)


@router.get("/experiments/{experiment_id}/schemes", response_model=list[schemas.SchemeSummary])
def list_schemes(experiment_id: int, db: Session = Depends(get_db)):
    load_experiment(db, experiment_id)
    schemes = (
        db.query(models.CutScheme)
        .options(selectinload(models.CutScheme.versions))
        .filter(models.CutScheme.experiment_id == experiment_id)
        .order_by(models.CutScheme.id)
        .all()
    )
    return [
        schemas.SchemeSummary(
            id=s.id,
            name=s.name,
            status=s.current_status,
            revision=s.current_revision,
            version_count=len(s.versions),
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
        )
        for s in schemes
    ]


@router.get("/schemes/{scheme_id}", response_model=schemas.SchemeDetailOut)
def get_scheme(scheme_id: int, db: Session = Depends(get_db)):
    scheme = load_scheme(db, scheme_id)
    audits = (
        db.query(models.AuditRecord)
        .filter(models.AuditRecord.scheme_id == scheme.id)
        .order_by(models.AuditRecord.id)
        .all()
    )
    state = _state_dict(scheme)
    return schemas.SchemeDetailOut(
        **state,
        versions=[
            schemas.VersionSummaryOut(
                id=v.id, version_no=v.version_no, note=v.note,
                created_at=v.created_at.isoformat(),
            )
            for v in scheme.versions
        ],
        audits=[
            schemas.AuditOut(
                id=a.id,
                action=a.action,
                action_label=ACTION_LABELS.get(a.action, a.action),
                from_status=a.from_status,
                to_status=a.to_status,
                actor=a.actor,
                version_id=a.version_id,
                detail=a.detail_json or {},
                created_at=a.created_at.isoformat(),
            )
            for a in audits
        ],
        created_at=scheme.created_at.isoformat(),
        updated_at=scheme.updated_at.isoformat() if scheme.updated_at else None,
    )


# ---- 状态迁移 -----------------------------------------------------------
@router.put("/schemes/{scheme_id}/draft")
def save_draft(
    scheme_id: int,
    payload: schemas.DraftSaveIn,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    scheme = load_scheme(db, scheme_id)
    fractions = [FractionInput(f.label, f.start_pct, f.end_pct) for f in payload.fractions]
    scheme, audit = versioning.save_draft(
        db, scheme, name=payload.name, fractions=fractions,
        base_revision=payload.base_revision, actor=x_actor,
        idempotency_key=idempotency_key,
    )
    return _finish(db, audit, _state_dict(scheme))


@router.post("/schemes/{scheme_id}/submit")
def submit_scheme(
    scheme_id: int,
    payload: schemas.TransitionIn,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    scheme = load_scheme(db, scheme_id)
    scheme, audit = versioning.submit(
        db, scheme, base_revision=payload.base_revision, actor=x_actor,
        idempotency_key=idempotency_key, note=payload.note,
    )
    return _finish(db, audit, _state_dict(scheme))


@router.post("/schemes/{scheme_id}/approve")
def approve_scheme(
    scheme_id: int,
    payload: schemas.TransitionIn,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    scheme = load_scheme(db, scheme_id)
    scheme, version, audit = versioning.approve(
        db, scheme, base_revision=payload.base_revision, actor=x_actor,
        idempotency_key=idempotency_key, note=payload.note,
    )
    payload_out = _state_dict(scheme)
    payload_out["version"] = {
        "id": version.id,
        "version_no": version.version_no,
        "created_at": version.created_at.isoformat(),
    }
    return _finish(db, audit, payload_out)


@router.post("/schemes/{scheme_id}/withdraw")
def withdraw_scheme(
    scheme_id: int,
    payload: schemas.TransitionIn,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    scheme = load_scheme(db, scheme_id)
    scheme, audit = versioning.withdraw(
        db, scheme, base_revision=payload.base_revision, actor=x_actor,
        idempotency_key=idempotency_key, note=payload.note,
    )
    return _finish(db, audit, _state_dict(scheme))


# ---- 版本查询与复制 -------------------------------------------------------
@router.get("/scheme-versions/{version_id}", response_model=schemas.VersionDetailOut)
def get_version(version_id: int, db: Session = Depends(get_db)):
    v = _load_version(db, version_id)
    return schemas.VersionDetailOut(
        id=v.id,
        scheme_id=v.scheme_id,
        version_no=v.version_no,
        note=v.note,
        fractions=[schemas.FractionIn(**f) for f in v.fractions_json],
        densities=[schemas.FractionDensityIn(**d) for d in v.densities_json],
        curve=v.curve_json,
        analysis=v.analysis_json,
        created_at=v.created_at.isoformat(),
    )


@router.post("/scheme-versions/{version_id}/copy", status_code=201)
def copy_scheme_version(
    version_id: int,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
    x_actor: str = Header(default=""),
):
    replay = _replay(db, idempotency_key)
    if replay is not None:
        return replay
    v = _load_version(db, version_id)
    scheme, audit = versioning.copy_version(
        db, v, actor=x_actor, idempotency_key=idempotency_key
    )
    return _finish(db, audit, _state_dict(scheme), status_code=201)


def _load_version(db: Session, version_id: int) -> models.SchemeVersion:
    v = db.query(models.SchemeVersion).filter(models.SchemeVersion.id == version_id).first()
    if v is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return v
