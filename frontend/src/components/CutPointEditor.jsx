export default function CutPointEditor({ fractions, onChange, disabled = false }) {
  const update = (i, field, value) => {
    const next = fractions.map((f, j) =>
      j === i ? { ...f, [field]: field === "label" ? value : Number(value) } : f
    );
    onChange(next);
  };
  const addRow = () => {
    const last = fractions[fractions.length - 1];
    const start = last ? last.end_pct : 0;
    onChange([...fractions, { label: `馏分${fractions.length + 1}`, start_pct: start, end_pct: start + 10 }]);
  };
  const removeRow = (i) => onChange(fractions.filter((_, j) => j !== i));

  return (
    <div className="panel">
      <h2>
        切点调整（回收率 %）
        {disabled && <span className="hint">　待审核状态不可编辑，请先撤回或等待审核完成</span>}
      </h2>
      <table className="grid">
        <thead>
          <tr>
            <th>馏分</th>
            <th>起点 %</th>
            <th>终点 %</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {fractions.map((f, i) => (
            <tr key={i} className={f.end_pct <= f.start_pct ? "row-warn" : ""}>
              <td>
                <input value={f.label} disabled={disabled} onChange={(e) => update(i, "label", e.target.value)} />
              </td>
              <td>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={f.start_pct}
                  disabled={disabled}
                  onChange={(e) => update(i, "start_pct", e.target.value)}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={f.end_pct}
                  disabled={disabled}
                  onChange={(e) => update(i, "end_pct", e.target.value)}
                />
              </td>
              <td>
                <button onClick={() => removeRow(i)} disabled={disabled} title="删除该馏分">
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={addRow} disabled={disabled}>+ 添加馏分</button>
    </div>
  );
}
