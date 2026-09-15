export default function WarningsPanel({ issues, title }) {
  if (!issues || issues.length === 0) return null;
  return (
    <div className="panel warnings">
      <h2>{title}</h2>
      <ul>
        {issues.map((it, i) => (
          <li key={i} className={`sev-${it.severity ?? "warning"}`}>
            <strong>[{it.severity === "error" ? "错误" : it.severity === "info" ? "提示" : "警告"}]</strong>{" "}
            {it.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
