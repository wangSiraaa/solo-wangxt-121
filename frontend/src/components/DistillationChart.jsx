import {
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1"];

export default function DistillationChart({ points, fractions, analysis, recoveredPct }) {
  const data = points.map((p) => ({ recovery: p.recovery_pct, temp: p.temperature_c }));
  const maxRecovery = recoveredPct ?? Math.max(...points.map((p) => p.recovery_pct));

  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart data={data} margin={{ top: 10, right: 30, bottom: 20, left: 10 }}>
          <XAxis
            dataKey="recovery"
            type="number"
            domain={[0, Math.max(100, maxRecovery)]}
            label={{ value: "回收率 %（占进料）", position: "insideBottom", offset: -10 }}
          />
          <YAxis
            label={{ value: "温度 °C", angle: -90, position: "insideLeft" }}
            domain={["auto", "auto"]}
          />
          <Tooltip
            formatter={(v, name) => [v, name === "temp" ? "温度 °C" : name]}
            labelFormatter={(v) => `回收率 ${v}%`}
          />
          {/* 馏分色带 */}
          {fractions.map((f, i) =>
            f.end_pct > f.start_pct ? (
              <ReferenceArea
                key={`f${i}`}
                x1={f.start_pct}
                x2={f.end_pct}
                fill={COLORS[i % COLORS.length]}
                fillOpacity={0.12}
                stroke="none"
                label={{ value: f.label, position: "insideTop", fontSize: 11 }}
              />
            ) : null
          )}
          {/* 重叠区：红色警示 */}
          {(analysis?.overlaps ?? []).map((o, i) => (
            <ReferenceArea
              key={`ov${i}`}
              x1={o.start_pct}
              x2={o.end_pct}
              fill="#d62728"
              fillOpacity={0.35}
              stroke="none"
              label={{ value: "重叠", position: "insideBottom", fontSize: 11, fill: "#d62728" }}
            />
          ))}
          {/* 缺口/残余：灰色 */}
          {(analysis?.gaps ?? []).map((g, i) => (
            <ReferenceArea
              key={`g${i}`}
              x1={g.start_pct}
              x2={g.end_pct}
              fill="#999999"
              fillOpacity={0.25}
              stroke="none"
              label={{ value: "残余", position: "insideBottom", fontSize: 11, fill: "#666" }}
            />
          ))}
          {/* 回收终点线 */}
          {recoveredPct != null && (
            <ReferenceLine
              x={recoveredPct}
              stroke="#333"
              strokeDasharray="6 4"
              label={{ value: `回收终点 ${recoveredPct}%`, position: "top", fontSize: 11 }}
            />
          )}
          <Line type="monotone" dataKey="temp" stroke="#1f3b73" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
