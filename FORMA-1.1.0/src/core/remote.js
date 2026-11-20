let configPromise;

async function apiBaseUrl() {
  if (!configPromise) {
    configPromise = fetch("./public/config.json", { cache: "no-store" })
      .then(response => {
        if (!response.ok) throw new Error("La conexión inteligente no está configurada.");
        return response.json();
      })
      .then(config => String(config.apiBaseUrl || "").trim().replace(/\/+$/, ""))
      .catch(error => {
        configPromise = null;
        throw error;
      });
  }
  const base = await configPromise;
  if (!base) throw new Error("La conexión inteligente todavía no está disponible.");
  return base;
}

async function requestJson(path, payload) {
  const base = await apiBaseUrl();
  const response = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "No se pudo completar la solicitud.");
  return data;
}

export async function askFormaCoach(payload) {
  const data = await requestJson("/api/coach", payload);
  if (typeof data.text !== "string" || !data.text.trim()) throw new Error("La respuesta no estaba disponible.");
  return data.text;
}

export async function askFormaVisualFallback(payload) {
  const data = await requestJson("/api/scan-fallback", payload);
  if (typeof data.text !== "string" || !data.text.trim()) throw new Error("La respuesta visual no estaba disponible.");
  return data.text;
}

export function startCladPhotoJob(payload) {
  return requestJson("/api/clad/scan", payload);
}

export function pollCladPhotoJob(payload) {
  return requestJson("/api/clad/poll", payload);
}
