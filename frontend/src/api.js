const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  listExperiments: () => request("/experiments"),
  getExperiment: (id) => request(`/experiments/${id}`),
  analyze: (id, fractions) =>
    request(`/experiments/${id}/analyze`, {
      method: "POST",
      body: JSON.stringify({ fractions }),
    }),
  saveScheme: (id, name, fractions) =>
    request(`/experiments/${id}/schemes`, {
      method: "POST",
      body: JSON.stringify({ name, fractions }),
    }),
  listSchemes: (id) => request(`/experiments/${id}/schemes`),
  exportUrl: (id, schemeId, format) =>
    `${BASE}/experiments/${id}/schemes/${schemeId}/export?format=${format}`,
};
