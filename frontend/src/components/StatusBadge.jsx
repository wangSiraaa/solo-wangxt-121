const STATUS_LABEL = {
  draft: "草稿",
  pending_review: "待审核",
  published: "已发布",
  withdrawn: "已撤回",
};

export function statusLabel(s) {
  return STATUS_LABEL[s] ?? s;
}

export default function StatusBadge({ status }) {
  return <span className={`badge st-${status}`}>{statusLabel(status)}</span>;
}
