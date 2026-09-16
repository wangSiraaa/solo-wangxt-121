import { useEffect, useState } from "react";
import { api } from "../api.js";

const fmt = (v, digits = 2) => (v == null ? "—" : Number(v).toFixed(digits));
const arrow = (a, b, digits = 1) => `${fmt(a, digits)} → ${fmt(b, digits)}`;

function Delta({ value, digits = 2 }) {
  if (value == null) return <span className="delta-none">—</span>;
  const cls = value > 0 ? "delta-up" : value < 0 ? "delta-down" : "delta-none";
  const sign = value > 0 ? "+" : "";
  return <span className={cls}>{sign}{fmt(value, digits)}</span>;
}

/** 只读版本差异比较：切点 / 密度 / 插值范围 / 产率。 */
export default function DiffView({ schemeId, versions, fromId, toId, onClose }) {
  const [from, setFrom] = useState(fromId);
  const [to, setTo] = useState(toId);
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (from == null || to == null) return;
    api.getDiff(schemeId, from, to).then(setDiff).catch((e) => setError(e.message));
  }, [schemeId, from, to]);

  if (error) return <div className="banner error">差异比较失败：{error}</div>;

  return (
    <div className="panel version-view">
      <h2>版本差异比较（只读）</h2>
      <div className="toolbar">
        <label>
          从：
          <select value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value))}>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>v{v.version_no}</option>
            ))}
          </select>
        </label>
        <label>
          到：
          <select value={to ?? ""} onChange={(e) => setTo(Number(e.target.value))}>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>v{v.version_no}</option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={onClose}>关闭</button>
      </div>

      {diff && (
        <>
          <h3>切点变化</h3>
          {diff.fractions.changed.length === 0 &&
          diff.fractions.added.length === 0 &&
          diff.fractions.removed.length === 0 ? (
            <p className="hint">切点无变化</p>
          ) : (
            <table className="grid">
              <tbody>
                {diff.fractions.added.map((f, i) => (
                  <tr key={`a${i}`} className="diff-added">
                    <td>新增馏分「{f.label}」</td>
                    <td>{fmt(f.start_pct, 1)} ~ {fmt(f.end_pct, 1)}%</td>
                  </tr>
                ))}
                {diff.fractions.removed.map((f, i) => (
                  <tr key={`r${i}`} className="diff-removed">
                    <td>删除馏分「{f.label}」</td>
                    <td>{fmt(f.start_pct, 1)} ~ {fmt(f.end_pct, 1)}%</td>
                  </tr>
                ))}
                {diff.fractions.changed.map((c, i) => (
                  <tr key={`c${i}`} className="diff-changed">
                    <td>「{c.label}」</td>
                    <td>
                      {c.changes.map((ch, j) => (
                        <div key={j}>
                          {ch.field === "start_pct" ? "起点" : "终点"}：
                          {arrow(ch.from, ch.to)}%
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>密度变化</h3>
          {diff.densities.changed.length === 0 ? (
            <p className="hint">密度无变化</p>
          ) : (
            <table className="grid">
              <tbody>
                {diff.densities.changed.map((c, i) => (
                  <tr key={i} className="diff-changed">
                    <td>「{c.label}」</td>
                    <td>
                      {c.changes.map((ch, j) => (
                        <div key={j}>
                          {ch.field === "density_kg_m3"
                            ? `密度：${arrow(ch.from, ch.to, 1)} kg/m³`
                            : `${ch.field}：${arrow(ch.from, ch.to)}`}
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>插值适用范围</h3>
          {diff.interpolation.range_changes.length === 0 &&
          !diff.interpolation.method_changed ? (
            <p className="hint">插值方法与适用范围无变化</p>
          ) : (
            <table className="grid">
              <tbody>
                {diff.interpolation.method_changed && (
                  <tr className="diff-changed">
                    <td>插值方法</td>
                    <td>{diff.interpolation.method_from} → {diff.interpolation.method_to}</td>
                  </tr>
                )}
                {diff.interpolation.range_changes.map((c, i) => (
                  <tr key={i} className="diff-changed">
                    <td>{c.field}</td>
                    <td>{arrow(c.from, c.to)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>产率差异</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>馏分</th>
                <th>占进料%（从 → 到）</th>
                <th>Δ</th>
                <th>体积%（从 → 到）</th>
                <th>质量%（从 → 到）</th>
                <th>温度范围变化 °C</th>
              </tr>
            </thead>
            <tbody>
              {diff.yields.map((y, i) => (
                <tr key={i} className={!y.in_from ? "diff-added" : !y.in_to ? "diff-removed" : ""}>
                  <td>{y.label}{!y.in_from && "（新增）"}{!y.in_to && "（已删除）"}</td>
                  <td>{arrow(y.pct_of_feed.from, y.pct_of_feed.to)}</td>
                  <td><Delta value={y.pct_of_feed.delta} /></td>
                  <td>{arrow(y.vol_pct_of_recovered.from, y.vol_pct_of_recovered.to)}</td>
                  <td>{arrow(y.mass_pct_of_recovered.from, y.mass_pct_of_recovered.to)}</td>
                  <td>
                    {y.temp_start_c.from != null || y.temp_start_c.to != null
                      ? `${arrow(y.temp_start_c.from, y.temp_start_c.to)} / ${arrow(y.temp_end_c.from, y.temp_end_c.to)}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
