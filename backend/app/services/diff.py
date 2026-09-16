"""版本差异审阅：两个已发布快照之间的只读对比。

对比维度：切点（馏分区间）、密度、插值方法与适用范围、产率。
所有数据均来自冻结快照，不重新计算。
"""
from __future__ import annotations

from .. import models

_FRACTION_FIELDS = ("start_pct", "end_pct")
_DENSITY_FIELDS = ("start_pct", "end_pct", "density_kg_m3")
_YIELD_FIELDS = (
    "pct_of_feed",
    "vol_pct_of_recovered",
    "mass_pct_of_recovered",
    "temp_start_c",
    "temp_end_c",
)


def _by_label(items: list[dict]) -> dict[str, dict]:
    return {x["label"]: x for x in items}


def _diff_named_items(
    old: list[dict], new: list[dict], fields: tuple[str, ...]
) -> dict:
    """按标签匹配，给出新增/删除/字段变化。"""
    old_by, new_by = _by_label(old), _by_label(new)
    added = [new_by[k] for k in new_by.keys() - old_by.keys()]
    removed = [old_by[k] for k in old_by.keys() - new_by.keys()]
    changed = []
    unchanged = 0
    for label in old_by.keys() & new_by.keys():
        field_changes = [
            {"field": f, "from": old_by[label].get(f), "to": new_by[label].get(f)}
            for f in fields
            if old_by[label].get(f) != new_by[label].get(f)
        ]
        if field_changes:
            changed.append({"label": label, "changes": field_changes})
        else:
            unchanged += 1
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged,
    }


def _delta(old_v, new_v):
    if old_v is None or new_v is None:
        return None
    return new_v - old_v


def _diff_yields(old_analysis: dict, new_analysis: dict) -> list[dict]:
    """按标签对齐两版的产率与对应温度。"""
    old_by = _by_label(old_analysis.get("fractions", []))
    new_by = _by_label(new_analysis.get("fractions", []))
    rows = []
    for label in sorted(old_by.keys() | new_by.keys()):
        o, n = old_by.get(label), new_by.get(label)
        row = {"label": label, "in_from": o is not None, "in_to": n is not None}
        for f in _YIELD_FIELDS:
            ov = o.get(f) if o else None
            nv = n.get(f) if n else None
            row[f] = {"from": ov, "to": nv, "delta": _delta(ov, nv)}
        rows.append(row)
    return rows


def _diff_interpolation(old_curve: dict, new_curve: dict) -> dict:
    old_i = old_curve.get("interpolation", {})
    new_i = new_curve.get("interpolation", {})
    old_r = old_i.get("applicable_range", {})
    new_r = new_i.get("applicable_range", {})
    range_changes = [
        {"field": f, "from": old_r.get(f), "to": new_r.get(f)}
        for f in (
            "recovery_min_pct",
            "recovery_max_pct",
            "temperature_min_c",
            "temperature_max_c",
        )
        if old_r.get(f) != new_r.get(f)
    ]
    return {
        "method_from": old_i.get("method"),
        "method_to": new_i.get("method"),
        "method_changed": old_i.get("method_id") != new_i.get("method_id"),
        "applicable_range_from": old_r,
        "applicable_range_to": new_r,
        "range_changes": range_changes,
    }


def diff_versions(v_from: models.SchemeVersion, v_to: models.SchemeVersion) -> dict:
    """生成 v_from -> v_to 的差异报告（只读）。"""
    return {
        "from": {
            "id": v_from.id,
            "version_no": v_from.version_no,
            "created_at": v_from.created_at.isoformat(),
        },
        "to": {
            "id": v_to.id,
            "version_no": v_to.version_no,
            "created_at": v_to.created_at.isoformat(),
        },
        "fractions": _diff_named_items(
            v_from.fractions_json, v_to.fractions_json, _FRACTION_FIELDS
        ),
        "densities": _diff_named_items(
            v_from.densities_json, v_to.densities_json, _DENSITY_FIELDS
        ),
        "interpolation": _diff_interpolation(v_from.curve_json, v_to.curve_json),
        "yields": _diff_yields(v_from.analysis_json, v_to.analysis_json),
        "totals": {
            f: {"from": v_from.analysis_json.get(f), "to": v_to.analysis_json.get(f)}
            for f in (
                "recovered_pct",
                "assigned_pct",
                "residual_pct",
                "loss_pct",
                "overlap_pct",
            )
        },
    }
