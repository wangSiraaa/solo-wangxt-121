import StatusBadge from "./StatusBadge.jsx";

const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

/** 版本时间线：审计记录 + 发布版本，标出当前生效版本。 */
export default function VersionTimeline({ detail, onOpenVersion }) {
  if (!detail) return null;
  const versionById = Object.fromEntries(detail.versions.map((v) => [v.id, v]));

  const switchText = (a) => {
    const d = a.detail || {};
    if (a.action === "switch" && d.to_version_no != null) {
      return `（v${d.from_version_no ?? "—"} → v${d.to_version_no}）`;
    }
    return "";
  };

  return (
    <div className="panel">
      <h2>
        版本时间线（当前状态：<StatusBadge status={detail.status} /> 修订 r{detail.revision}
        {detail.active_version_no != null && (
          <span className="badge st-published">　生效版本 v{detail.active_version_no}</span>
        )}
        ）
      </h2>
      {detail.audits.length === 0 ? (
        <p className="hint">暂无记录</p>
      ) : (
        <ol className="timeline">
          {detail.audits.map((a) => {
            const v = a.version_id ? versionById[a.version_id] : null;
            return (
              <li key={a.id}>
                <span className="t-time">{fmtTime(a.created_at)}</span>
                <span className="t-action">
                  {a.action_label}
                  {switchText(a)}
                </span>
                {a.actor && <span className="t-actor">操作人：{a.actor}</span>}
                {a.from_status !== a.to_status && (
                  <span className="t-trans">
                    {a.from_status ? `${statusLabel(a.from_status)} → ` : ""}
                    {statusLabel(a.to_status)}
                  </span>
                )}
                {v && (
                  <button className="link" onClick={() => onOpenVersion(v.id)}>
                    查看 v{v.version_no} 快照
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {detail.versions.length > 0 && (
        <div className="version-chips">
          {detail.versions.map((v) => (
            <button
              key={v.id}
              className={`chip ${v.id === detail.active_version_id ? "chip-active" : ""}`}
              onClick={() => onOpenVersion(v.id)}
            >
              v{v.version_no}
              {v.id === detail.active_version_id && " ★生效中"} · {fmtTime(v.created_at)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function statusLabel(s) {
  return { draft: "草稿", pending_review: "待审核", published: "已发布", withdrawn: "已撤回" }[s] ?? s;
}
