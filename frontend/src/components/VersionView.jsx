import { api } from "../api.js";

const fmt = (v, digits = 2) => (v == null ? "—" : Number(v).toFixed(digits));

/** 只读历史版本视图：冻结的切点、密度、插值范围与导出。 */
export default function VersionView({ version, onClose, onCopy }) {
  if (!version) return null;
  const rng = version.curve?.interpolation?.applicable_range;
  return (
    <div className="panel version-view">
      <h2>
        历史版本 v{version.version_no}（只读快照，发布于{" "}
        {new Date(version.created_at).toLocaleString()}）
      </h2>
      <div className="banner info">
        插值：{version.curve?.interpolation?.method} ｜ 适用范围：回收率{" "}
        {rng?.recovery_min_pct}% ~ {rng?.recovery_max_pct}%（{rng?.temperature_min_c}°C ~{" "}
        {rng?.temperature_max_c}°C）｜ {version.curve?.interpolation?.extrapolation}
        <br />
        快照已冻结：此后对试验或草稿的修改不影响本版本。
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>馏分</th>
            <th>区间 %</th>
            <th>温度范围 °C</th>
            <th>密度 kg/m³</th>
            <th>占进料 %</th>
            <th>体积%（占回收馏分）</th>
            <th>质量%（占回收馏分）</th>
          </tr>
        </thead>
        <tbody>
          {version.analysis.fractions.map((f, i) => (
            <tr key={i}>
              <td>{f.label}</td>
              <td>
                {fmt(f.start_pct, 1)} ~ {fmt(f.end_pct, 1)}
              </td>
              <td>
                {f.temp_start_c == null || f.temp_end_c == null
                  ? "—（超出数据范围，不外推）"
                  : `${fmt(f.temp_start_c, 1)} ~ ${fmt(f.temp_end_c, 1)}`}
              </td>
              <td>{fmt(f.density_kg_m3, 1)}</td>
              <td>{fmt(f.pct_of_feed)}</td>
              <td>{fmt(f.vol_pct_of_recovered)}</td>
              <td>{fmt(f.mass_pct_of_recovered)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="toolbar">
        <a href={api.exportVersionUrl(version.id, "json")} target="_blank" rel="noreferrer">
          导出冻结 JSON
        </a>
        <a href={api.exportVersionUrl(version.id, "csv")} target="_blank" rel="noreferrer">
          导出冻结 CSV
        </a>
        <button onClick={() => onCopy(version.id)}>基于此版本新建草稿</button>
        <button className="secondary" onClick={onClose}>
          关闭
        </button>
      </div>
    </div>
  );
}
