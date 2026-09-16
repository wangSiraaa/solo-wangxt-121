import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import DistillationChart from "./components/DistillationChart.jsx";
import CutPointEditor from "./components/CutPointEditor.jsx";
import FractionTable from "./components/FractionTable.jsx";
import WarningsPanel from "./components/WarningsPanel.jsx";
import TotalsBar from "./components/TotalsBar.jsx";
import StatusBadge from "./components/StatusBadge.jsx";
import VersionTimeline from "./components/VersionTimeline.jsx";
import VersionView from "./components/VersionView.jsx";
import DiffView from "./components/DiffView.jsx";

export default function App() {
  const [experiments, setExperiments] = useState([]);
  const [expId, setExpId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [schemes, setSchemes] = useState([]);
  const [schemeDetail, setSchemeDetail] = useState(null);
  const [fractions, setFractions] = useState([]);
  const [schemeName, setSchemeName] = useState("新方案");
  const [analysis, setAnalysis] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [versionView, setVersionView] = useState(null);
  const [diffPair, setDiffPair] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const timer = useRef(null);
  // 每个浏览器窗口一个客户端标识：幂等键 = 窗口:方案:动作:修订号
  const clientId = useRef(crypto.randomUUID());
  const ikey = (action, sid, rev) => `${clientId.current}:${sid}:${action}:${rev}`;

  useEffect(() => {
    api
      .listExperiments()
      .then((list) => {
        setExperiments(list);
        if (list.length > 0) setExpId(list[0].id);
      })
      .catch((e) => setError(e.message));
  }, []);

  const loadScheme = useCallback(async (sid) => {
    const d = await api.getScheme(sid);
    setSchemeDetail(d);
    setFractions(d.fractions.map((f) => ({ ...f })));
    setSchemeName(d.name);
    setConflict(null);
    setVersionView(null);
    setDiffPair(null);
  }, []);

  const reloadSchemes = useCallback(
    async (selectId) => {
      const list = await api.listSchemes(expId);
      setSchemes(list);
      if (selectId != null) await loadScheme(selectId);
      return list;
    },
    [expId, loadScheme]
  );

  useEffect(() => {
    if (expId == null) return;
    setSchemeDetail(null);
    setVersionView(null);
    setConflict(null);
    Promise.all([api.getExperiment(expId), api.listSchemes(expId)])
      .then(async ([d, list]) => {
        setDetail(d);
        setSchemes(list);
        if (list.length > 0) {
          await loadScheme(list[0].id);
        } else if (d.densities.length > 0) {
          setFractions(
            d.densities.map((x) => ({
              label: x.label,
              start_pct: x.start_pct,
              end_pct: x.end_pct,
            }))
          );
          setSchemeName("新方案");
        } else {
          setFractions([]);
        }
      })
      .catch((e) => setError(e.message));
  }, [expId, loadScheme]);

  // 切点变化后防抖调用实时分析（不保存）
  useEffect(() => {
    if (expId == null || fractions.length === 0) {
      setAnalysis(null);
      return;
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.analyze(expId, fractions).then(setAnalysis).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(timer.current);
  }, [expId, fractions]);

  const handleErr = useCallback((e) => {
    if (e.status === 409) {
      setConflict(e.message); // 可见冲突提示，不覆盖
    } else {
      setError(e.message);
    }
  }, []);

  const run = useCallback(
    async (fn) => {
      setBusy(true);
      try {
        await fn();
      } catch (e) {
        handleErr(e);
      } finally {
        setBusy(false);
      }
    },
    [handleErr]
  );

  const save = () =>
    run(async () => {
      if (schemeDetail) {
        const s = await api.saveDraft(
          schemeDetail.id,
          schemeName,
          fractions,
          schemeDetail.revision,
          ikey("save", schemeDetail.id, schemeDetail.revision)
        );
        await reloadSchemes(s.id);
      } else {
        const s = await api.createScheme(
          expId,
          schemeName || "新方案",
          fractions,
          ikey("create", expId, schemeName)
        );
        await reloadSchemes(s.id);
      }
    });

  const doTransition = (action) =>
    run(async () => {
      try {
        await api.transition(
          schemeDetail.id,
          action,
          schemeDetail.revision,
          ikey(action, schemeDetail.id, schemeDetail.revision)
        );
      } catch (e) {
        // 撤回已发布方案且存在生效指针：按规则要求显式选择继任历史版本
        if (
          action === "withdraw" &&
          e.status === 409 &&
          e.body?.code === "ACTIVE_VERSION_REQUIRES_SUCCESSOR" &&
          (e.body.available_versions ?? []).length > 0
        ) {
          const options = e.body.available_versions;
          const pick = window.prompt(
            `${e.body.detail}\n可选继任版本：${options
              .map((v) => `v${v.version_no}`)
              .join("、")}\n请输入要生效的版本号（数字）：`
          );
          const chosen = options.find((v) => String(v.version_no) === (pick ?? "").trim());
          if (!chosen) throw e;
          await api.transition(
            schemeDetail.id,
            action,
            schemeDetail.revision,
            ikey(`${action}-succ${chosen.id}`, schemeDetail.id, schemeDetail.revision),
            { successor_version_id: chosen.id }
          );
        } else {
          throw e;
        }
      }
      await reloadSchemes(schemeDetail.id);
    });

  const switchVersion = (targetId) =>
    run(async () => {
      await api.switchVersion(
        schemeDetail.id,
        targetId,
        schemeDetail.active_version_id,
        schemeDetail.revision,
        ikey("switch", schemeDetail.id, schemeDetail.revision)
      );
      await reloadSchemes(schemeDetail.id);
      setVersionView(null);
    });

  const compareVersions = (fromId, toId) => setDiffPair({ from: fromId, to: toId });

  const openVersion = (vid) =>
    run(async () => setVersionView(await api.getVersion(vid)));

  const copyVersion = (vid) =>
    run(async () => {
      const s = await api.copyVersion(vid, ikey("copy", vid, 0));
      await reloadSchemes(s.id);
    });

  if (error) {
    return (
      <div className="page">
        <div className="banner error">
          出错：{error} <button onClick={() => setError(null)}>关闭</button>
        </div>
      </div>
    );
  }

  const status = schemeDetail?.status ?? "draft";
  const editable = status !== "pending_review";

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

          {/* 方案状态栏 */}
          <div className="panel scheme-bar">
            <label>
              方案：
              <select
                value={schemeDetail?.id ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "new") {
                    setSchemeDetail(null);
                    setSchemeName("新方案");
                    setVersionView(null);
                  } else {
                    loadScheme(Number(v));
                  }
                }}
              >
                {schemes.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}（{s.version_count} 个版本）
                  </option>
                ))}
                <option value="new">＋ 新建方案…</option>
              </select>
            </label>
            <input
              className="scheme-name"
              value={schemeName}
              disabled={!editable}
              onChange={(e) => setSchemeName(e.target.value)}
            />
            {schemeDetail && (
              <>
                <StatusBadge status={status} />
                <span className="meta">r{schemeDetail.revision}</span>
                {schemeDetail.active_version_no != null && (
                  <span className="badge st-published">
                    生效 v{schemeDetail.active_version_no}
                  </span>
                )}
              </>
            )}
            <span className="spacer" />
            <button disabled={busy || !editable || fractions.length === 0} onClick={save}>
              保存草稿
            </button>
            {schemeDetail && status === "draft" && (
              <button disabled={busy} onClick={() => doTransition("submit")}>
                提交审核
              </button>
            )}
            {schemeDetail && status === "pending_review" && (
              <>
                <button disabled={busy} onClick={() => doTransition("approve")}>
                  审核通过（发布）
                </button>
                <button disabled={busy} className="secondary" onClick={() => doTransition("withdraw")}>
                  撤回
                </button>
              </>
            )}
            {schemeDetail && status === "published" && (
              <button disabled={busy} className="secondary" onClick={() => doTransition("withdraw")}>
                撤回发布
              </button>
            )}
            {schemeDetail && (
              <span className="meta">
                实时导出（未冻结）：
                <a href={api.exportLiveUrl(expId, schemeDetail.id, "json")} target="_blank" rel="noreferrer">
                  JSON
                </a>
                {" / "}
                <a href={api.exportLiveUrl(expId, schemeDetail.id, "csv")} target="_blank" rel="noreferrer">
                  CSV
                </a>
              </span>
            )}
          </div>

          {conflict && (
            <div className="banner conflict">
              <strong>版本冲突：</strong>
              {conflict}
              <button onClick={() => schemeDetail && loadScheme(schemeDetail.id)}>
                载入最新版本
              </button>
              <button className="secondary" onClick={() => setConflict(null)}>
                忽略
              </button>
            </div>
          )}

          <CutPointEditor fractions={fractions} onChange={setFractions} disabled={!editable} />

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

          {schemeDetail && <VersionTimeline detail={schemeDetail} onOpenVersion={openVersion} />}

          {versionView && (
            <VersionView
              version={versionView}
              isActive={versionView.id === schemeDetail?.active_version_id}
              onSwitch={() => switchVersion(versionView.id)}
              onCompare={() =>
                compareVersions(versionView.id, schemeDetail.active_version_id)
              }
              onClose={() => setVersionView(null)}
              onCopy={copyVersion}
            />
          )}

          {diffPair && schemeDetail && (
            <DiffView
              schemeId={schemeDetail.id}
              versions={schemeDetail.versions}
              fromId={diffPair.from}
              toId={diffPair.to}
              onClose={() => setDiffPair(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
