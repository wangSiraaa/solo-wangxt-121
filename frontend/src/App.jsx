import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import DistillationChart from "./components/DistillationChart.jsx";
import CutPointEditor from "./components/CutPointEditor.jsx";
import FractionTable from "./components/FractionTable.jsx";
import WarningsPanel from "./components/WarningsPanel.jsx";
import TotalsBar from "./components/TotalsBar.jsx";

export default function App() {
  const [experiments, setExperiments] = useState([]);
  const [expId, setExpId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [fractions, setFractions] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [schemes, setSchemes] = useState([]);
  const [savedSchemeId, setSavedSchemeId] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    api.listExperiments().then((list) => {
      setExperiments(list);
      if (list.length > 0) setExpId(list[0].id);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (expId == null) return;
    setSavedSchemeId(null);
    Promise.all([api.getExperiment(expId), api.listSchemes(expId)])
      .then(([d, s]) => {
        setDetail(d);
        setSchemes(s);
        // 默认按密度分段预填切点，便于直接演示
        if (s.length > 0) {
          setFractions(s[0].fractions.map((f) => ({ ...f })));
        } else if (d.densities.length > 0) {
          setFractions(
            d.densities.map((x) => ({
              label: x.label,
              start_pct: x.start_pct,
              end_pct: x.end_pct,
            }))
          );
        } else {
          setFractions([]);
        }
      })
      .catch((e) => setError(e.message));
  }, [expId]);

  // 切点变化后防抖调用实时分析
  useEffect(() => {
    if (expId == null || fractions.length === 0) {
      setAnalysis(null);
      return;
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api
        .analyze(expId, fractions)
        .then(setAnalysis)
        .catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [expId, fractions]);

  const saveScheme = useCallback(() => {
    const name = window.prompt("方案名称", `方案-${new Date().toLocaleString()}`);
    if (!name) return;
    api
      .saveScheme(expId, name, fractions)
      .then((s) => {
        setSavedSchemeId(s.id);
        return api.listSchemes(expId).then(setSchemes);
      })
      .catch((e) => setError(e.message));
  }, [expId, fractions]);

  if (error) {
    return (
      <div className="page">
        <div className="banner error">出错：{error}
          <button onClick={() => setError(null)}>关闭</button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header>
        <h1>馏分切割方案工具</h1>
        <span className="tag">仅处理离线试验数据 · 不控制真实装置</span>
      </header>

      <div className="toolbar">
        <label>
          试验：
          <select value={expId ?? ""} onChange={(e) => setExpId(Number(e.target.value))}>
            {experiments.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        {detail && (
          <span className="meta">
            基准：{detail.curve_basis === "volume" ? "体积%" : "质量%"} ｜ 方法：
            {detail.method || "—"} ｜ 压力：{detail.pressure_kpa ?? "—"} kPa
          </span>
        )}
      </div>

      {detail && (
        <>
          <WarningsPanel issues={detail.curve_issues} title="曲线数据核查" />

          {detail.interpolation?.applicable_range && (
            <div className="banner info">
              插值方法：{detail.interpolation.method} ｜ 适用范围：回收率{" "}
              {detail.interpolation.applicable_range.recovery_min_pct}% ~{" "}
              {detail.interpolation.applicable_range.recovery_max_pct}%（
              {detail.interpolation.applicable_range.temperature_min_c}°C ~{" "}
              {detail.interpolation.applicable_range.temperature_max_c}°C）｜{" "}
              {detail.interpolation.extrapolation}
            </div>
          )}

          <DistillationChart
            points={detail.points}
            fractions={fractions}
            analysis={analysis}
            recoveredPct={analysis?.recovered_pct}
          />

          <div className="toolbar">
            <button onClick={saveScheme} disabled={fractions.length === 0}>
              保存方案
            </button>
            {savedSchemeId && (
              <>
                <a href={api.exportUrl(expId, savedSchemeId, "json")} target="_blank" rel="noreferrer">
                  导出 JSON
                </a>
                <a href={api.exportUrl(expId, savedSchemeId, "csv")} target="_blank" rel="noreferrer">
                  导出 CSV
                </a>
              </>
            )}
            {schemes.length > 0 && (
              <label>
                载入已存方案：
                <select
                  value=""
                  onChange={(e) => {
                    const s = schemes.find((x) => x.id === Number(e.target.value));
                    if (s) setFractions(s.fractions.map((f) => ({ ...f })));
                  }}
                >
                  <option value="">选择…</option>
                  {schemes.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <CutPointEditor fractions={fractions} onChange={setFractions} />

          {analysis && (
            <>
              <TotalsBar analysis={analysis} />
              <WarningsPanel
                issues={analysis.warnings.map((w) => ({ severity: "warning", message: w }))}
                title="切割方案核查"
              />
              <FractionTable analysis={analysis} />
            </>
          )}
        </>
      )}
    </div>
  );
}
