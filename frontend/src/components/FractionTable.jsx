const fmt = (v, digits = 2) => (v == null ? "—" : Number(v).toFixed(digits));

export default function FractionTable({ analysis }) {
  const basisLabel = analysis.curve_basis === "volume" ? "体积" : "质量";
  return (
    <div className="panel">
      <h2>馏分产率核对</h2>
      <p className="hint">
        「占进料%」为曲线基准（{basisLabel}%）；「体积%/质量%（占回收馏分）」由实测密度换算，
        两者不是同一横轴，不可混用。
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th>馏分</th>
            <th>区间 %</th>
            <th>宽度 %</th>
            <th>温度范围 °C</th>
            <th>密度 kg/m³</th>
            <th>占进料 %</th>
            <th>体积%（占回收馏分）</th>
            <th>质量%（占回收馏分）</th>
            <th>提示</th>
          </tr>
        </thead>
        <tbody>
          {analysis.fractions.map((f, i) => (
            <tr key={i} className={f.warnings.length > 0 ? "row-warn" : ""}>
              <td>{f.label}</td>
              <td>
                {fmt(f.start_pct, 1)} ~ {fmt(f.end_pct, 1)}
              </td>
              <td>{fmt(f.width_pct)}</td>
              <td>
                {f.temp_start_c == null || f.temp_end_c == null
                  ? "—（超出数据范围，不外推）"
                  : `${fmt(f.temp_start_c, 1)} ~ ${fmt(f.temp_end_c, 1)}`}
              </td>
              <td>{fmt(f.density_kg_m3, 1)}</td>
              <td>{fmt(f.pct_of_feed)}</td>
              <td>{fmt(f.vol_pct_of_recovered)}</td>
              <td>{fmt(f.mass_pct_of_recovered)}</td>
              <td className="warn-text">
                {f.warnings.map((w, j) => (
                  <div key={j}>{w}</div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
