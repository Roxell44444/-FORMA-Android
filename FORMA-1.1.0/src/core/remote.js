let configPromise;

async function readBackendConfig() {
  const paths = ["./config.json", "./public/config.json"];
  let lastError;
  for (const path of paths) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) {
        lastError = new Error("No se encontró la configuración del servidor (" + response.status + ").");
        continue;
      }
      const config = await response.json();
      const raw = String(config.apiBaseUrl || "").trim();
      if (!raw) {
        lastError = new Error("La dirección del servidor está vacía.");
        continue;
      }
      const parsed = new URL(raw);
      if (parsed.protocol !== "https:") throw new Error("La dirección del servidor no utiliza HTTPS.");
      return parsed.origin;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("No se pudo leer la configuración del servidor.");
}

async function apiBaseUrl() {
  if (!configPromise) {
    configPromise = readBackendConfig().catch(error => {
      configPromise = null;
      throw new Error("No se pudo localizar la conexión de FORMA: " + (error?.message || String(error)));
    });
  }
  return configPromise;
}

async function requestJson(path, payload) {
  const base = await apiBaseUrl();
  let response;
  try {
    response = await fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store"
    });
  } catch (error) {
    throw new Error("No se pudo conectar con el servidor de FORMA. Comprueba Internet y los permisos de conexión de la aplicación. " + (error?.message || ""));
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ("El servidor respondió con el código " + response.status + "."));
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
