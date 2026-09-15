import StatusBadge from "./StatusBadge.jsx";

const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

/** 版本时间线：审计记录 + 发布版本，按时间排列。 */
export default function VersionTimeline({ detail, onOpenVersion }) {
  if (!detail) return null;
  const versionById = Object.fromEntries(detail.versions.map((v) => [v.id, v]));

  return (
    <div className="panel">
      <h2>
        版本时间线（当前状态：<StatusBadge status={detail.status} /> 修订 r{detail.revision}）
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
                <span className="t-action">{a.action_label}</span>
                {a.actor && <span className="t-actor">操作人：{a.actor}</span>}
                <span className="t-trans">
                  {a.from_status ? `${statusLabel(a.from_status)} → ` : ""}
                  {statusLabel(a.to_status)}
                </span>
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
            <button key={v.id} className="chip" onClick={() => onOpenVersion(v.id)}>
              v{v.version_no} · {fmtTime(v.created_at)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
