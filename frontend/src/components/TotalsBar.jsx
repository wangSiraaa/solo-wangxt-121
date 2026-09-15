const fmt = (v, digits = 2) => (v == null ? "—" : Number(v).toFixed(digits));

export default function TotalsBar({ analysis }) {
  const a = analysis;
  return (
    <div className={`totals ${a.balance_ok ? "ok" : "bad"}`}>
      <span>定义总量 {fmt(a.defined_total_pct, 1)}%</span>
      <span>回收总量 {fmt(a.recovered_pct, 2)}%</span>
      <span>已分配 {fmt(a.assigned_pct, 2)}%</span>
      <span className={a.overlap_pct > 0 ? "warn-text" : ""}>重叠 {fmt(a.overlap_pct, 2)}%</span>
      <span className={a.residual_pct > 0 ? "warn-text" : ""}>残余 {fmt(a.residual_pct, 2)}%</span>
      <span>损失 {fmt(a.loss_pct, 2)}%</span>
      <strong>{a.balance_ok ? "✓ 总量平衡" : "✗ 总量不平衡，请核实"}</strong>
    </div>
  );
}
