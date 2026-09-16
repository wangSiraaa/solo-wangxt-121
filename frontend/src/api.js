const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    let body = null;
    let detail = `${res.status}`;
    try {
      body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return res.json();
}

const idem = (key) => (key ? { "Idempotency-Key": key } : {});

export const api = {
  listExperiments: () => request("/experiments"),
  getExperiment: (id) => request(`/experiments/${id}`),
  analyze: (id, fractions) =>
    request(`/experiments/${id}/analyze`, {
      method: "POST",
      body: JSON.stringify({ fractions }),
    }),

  // 方案与版本
  listSchemes: (expId) => request(`/experiments/${expId}/schemes`),
  getScheme: (sid) => request(`/schemes/${sid}`),
  createScheme: (expId, name, fractions, key) =>
    request(`/experiments/${expId}/schemes`, {
      method: "POST",
      body: JSON.stringify({ name, fractions }),
      headers: idem(key),
    }),
  saveDraft: (sid, name, fractions, revision, key) =>
    request(`/schemes/${sid}/draft`, {
      method: "PUT",
      body: JSON.stringify({ name, fractions, base_revision: revision }),
      headers: idem(key),
    }),
  transition: (sid, action, revision, key, extra = {}) =>
    request(`/schemes/${sid}/${action}`, {
      method: "POST",
      body: JSON.stringify({ base_revision: revision, ...extra }),
      headers: idem(key),
    }),
  switchVersion: (sid, target, expectedActive, revision, key) =>
    request(`/schemes/${sid}/switch-version`, {
      method: "POST",
      body: JSON.stringify({
        target_version_id: target,
        expected_active_version_id: expectedActive,
        base_revision: revision,
      }),
      headers: idem(key),
    }),
  getCurrentVersion: (sid) => request(`/schemes/${sid}/current-version`),
  getDiff: (sid, fromId, toId) =>
    request(`/schemes/${sid}/diff?from_id=${fromId}&to_id=${toId}`),
  getVersion: (vid) => request(`/scheme-versions/${vid}`),
  copyVersion: (vid, key) =>
    request(`/scheme-versions/${vid}/copy`, { method: "POST", headers: idem(key) }),

  // 导出
  exportLiveUrl: (expId, schemeId, format) =>
    `${BASE}/experiments/${expId}/schemes/${schemeId}/export?format=${format}`,
  exportVersionUrl: (vid, format) => `${BASE}/scheme-versions/${vid}/export?format=${format}`,
};
