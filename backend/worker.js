const DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite";
const DEFAULT_CLAD_BASE = "https://api.clad.you";
const MAX_BODY_BYTES = 12_000_000;
const MAX_IMAGE_CHARS = 7_000_000;

const COACH_RULES = [
  "Eres FORMA Coach, un asistente en español especializado exclusivamente en entrenamiento, ejercicio, nutrición general, descanso, recuperación y hábitos de bienestar.",
  "Responde de forma práctica, amable y personalizada con el contexto proporcionado. Limita la respuesta a este ámbito; para cualquier otro tema explica amablemente tu especialidad y redirige la conversación.",
  "No diagnostiques enfermedades, no interpretes análisis clínicos, no prescribas medicamentos ni trates lesiones. Ante síntomas preocupantes, recomienda detener la actividad y consultar a profesionales sanitarios.",
  "No inventes resultados ni medidas. Distingue las estimaciones visuales de las mediciones directas.",
  "Si el perfil es menor de 18 años, no des objetivos de calorías, pérdida de peso, grasa corporal, macros ni rutinas de fuerza adultas. Prioriza crecimiento, hábitos variados y actividad apropiada para la edad.",
  "No fomentes dietas extremas, deshidratación, suplementos peligrosos ni cambios bruscos. Responde en español claro y evita jerga."
].join(" ");

const VISION_RULES = [
  "Eres FORMA Visual, un analista de imágenes de bienestar. Analiza siempre lo que esté visible en cada fotografía recibida. Nunca rechaces una imagen por estar recortada, inclinada, tener una pose distinta, ropa holgada, iluminación imperfecta o no ser una vista frontal/lateral.",
  "Adapta el análisis al contenido real: si solo se ve medio cuerpo, analiza esa zona; si se ve una persona completa, describe la silueta general; si la foto está borrosa u oscura, explica qué detalles no pueden evaluarse. No afirmes haber visto partes que no aparecen.",
  "Da una descripción visual breve y neutral de la postura, las zonas visibles y la apariencia muscular general. No juzgues atractivo, salud o condición médica. No identifiques a la persona.",
  "Solo ofrece un rango amplio de grasa corporal cuando haya una porción suficiente del torso y la silueta visible para sostener una impresión visual. El rango debe ser deliberadamente amplio (al menos 10 puntos porcentuales), con confianza baja y explicado como una impresión visual, nunca como medición. Si no hay suficiente cuerpo visible, di claramente que no se puede estimar con sentido a partir de esa toma, pero analiza lo que sí se ve.",
  "Nunca inventes perímetros en centímetros, peso, masa muscular en kilogramos, masa grasa ni porcentajes exactos. La masa muscular solo puede describirse cualitativamente. No confundas masa libre de grasa con músculo.",
  "No exijas que se repita la foto para poder analizarla. Puedes sugerir opcionalmente una toma adicional para mejorar la precisión, pero primero entrega el análisis posible con el material recibido.",
  "Responde en español natural, con tono respetuoso y máximo 160 palabras. Usa encabezados cortos: LECTURA VISUAL; COMPOSICIÓN (solo si hay base para un rango); DESARROLLO MUSCULAR; LIMITACIONES. No uses tablas ni listas largas."
].join(" ");

const ALLOWED_MEASUREMENTS = [
  "height_cm", "bust_cm", "waist_cm", "hip_cm", "thigh_cm",
  "upperarm_cm", "shoulder_width_cm", "sleeve_length_cm", "inseam_cm",
  "neck_cm", "underbust_cm", "stomach_cm", "mass_kg"
];

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  const allowed = String(env.ALLOWED_ORIGINS || "https://appassets.androidplatform.net")
    .split(",").map(value => value.trim()).filter(Boolean);
  if (!origin || !allowed.includes(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin"
  };
}

function json(request, env, data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...corsHeaders(request, env),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function errorMessage(request, env, message, status = 400) {
  return json(request, env, { error: message }, status);
}

function readImageDataUrl(value) {
  if (typeof value !== "string" || value.length > MAX_IMAGE_CHARS) {
    throw new Error("Imagen no válida o demasiado grande.");
  }
  const match = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match) throw new Error("Formato de imagen no admitido.");
  const binary = atob(match[2]);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return { mimeType: match[1], bytes, base64: match[2] };
}

async function readJson(request) {
  const reader = request.body?.getReader();
  if (!reader) throw new Error("La solicitud no contiene datos JSON.");
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) {
        await reader.cancel();
        throw new Error("La solicitud supera el tamaño permitido.");
      }
      chunks.push(value);
    }
  } catch (error) {
    if (error instanceof Error && error.message === "La solicitud supera el tamaño permitido.") throw error;
    throw new Error("No se pudo leer la solicitud.");
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new Error("La solicitud no es válida.");
  }
}

async function isRateLimited(request, env, bindingName, route) {
  const limiter = env[bindingName];
  if (!limiter) return false;
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  try {
    const result = await limiter.limit({ key: ip + ":" + route });
    return result?.success !== true;
  } catch {
    // Keep the service available if Cloudflare's approximate limiter has a transient error.
    return false;
  }
}

function extractInteractionText(interaction) {
  const pieces = [];
  for (const step of interaction.steps || []) {
    if (step.type !== "model_output") continue;
    for (const part of step.content || []) {
      if (part.type === "text" && typeof part.text === "string") pieces.push(part.text);
    }
  }
  return pieces.join("\n").trim();
}

async function generateGemini(env, systemInstruction, input) {
  if (!env.GEMINI_API_KEY) {
    return { error: "El Coach inteligente todavía no está configurado.", status: 503 };
  }
  let response;
  try {
    response = await fetch("https://generativelanguage.googleapis.com/v1beta/interactions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": env.GEMINI_API_KEY
      },
      signal: AbortSignal.timeout(25000),
      body: JSON.stringify({
        model: env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL,
        system_instruction: systemInstruction,
        generation_config: { temperature: 0.45 },
        store: false,
        input: input
      })
    });
  } catch {
    return { error: "El servicio inteligente no respondió a tiempo. Inténtalo de nuevo.", status: 502 };
  }
  if (!response.ok) return { error: "El servicio inteligente no pudo responder ahora.", status: 502 };
  const interaction = await response.json();
  const text = extractInteractionText(interaction);
  if (!text) return { error: "No llegó una respuesta utilizable.", status: 502 };
  return { text: text };
}

function cladBase(env) {
  const base = String(env.CLAD_API_BASE_URL || DEFAULT_CLAD_BASE).replace(/\/+$/, "");
  const parsed = new URL(base);
  if (parsed.protocol !== "https:" || parsed.hostname !== "api.clad.you") {
    throw new Error("La dirección del servicio de reconstrucción no es válida.");
  }
  return base;
}

function checkedPollUrl(value, base, jobId) {
  const fallback = base + "/v1/jobs/" + encodeURIComponent(jobId);
  const url = new URL(value || fallback, base);
  const root = new URL(base);
  if (url.protocol !== "https:" || url.hostname !== root.hostname ||
      !url.pathname.startsWith("/v1/jobs/") ||
      !url.pathname.endsWith("/" + jobId)) {
    throw new Error("La dirección de seguimiento de la reconstrucción no es válida.");
  }
  return url.toString();
}

function normaliseMeasurements(source) {
  const measurements = {};
  for (const key of ALLOWED_MEASUREMENTS) {
    const value = Number(source && source[key]);
    if (Number.isFinite(value) && value > 0 && value < 300) measurements[key] = value;
  }
  return measurements;
}

async function startCladJob(request, env) {
  if (!env.CLAD_API_KEY) {
    return errorMessage(request, env, "La conexión de reconstrucción 3D aún no está configurada.", 503);
  }
  const body = await readJson(request);
  let image;
  try { image = readImageDataUrl(body.frontImage); }
  catch (error) { return errorMessage(request, env, error.message, 400); }

  const heightCm = Number(body.heightCm);
  if (!Number.isFinite(heightCm) || heightCm < 140 || heightCm > 220) {
    return errorMessage(request, env, "Clad acepta estaturas entre 140 y 220 cm.", 400);
  }

  let base;
  try { base = cladBase(env); }
  catch (error) { return errorMessage(request, env, error.message, 500); }

  const form = new FormData();
  form.append("photo", new Blob([image.bytes], { type: image.mimeType }), "forma-front.jpg");
  form.append("height_cm", String(heightCm));

  let upstream;
  try {
    upstream = await fetch(base + "/v1/body/from-photo", {
      method: "POST",
      headers: { "Authorization": "Bearer " + env.CLAD_API_KEY },
      signal: AbortSignal.timeout(25000),
      body: form
    });
  } catch {
    return errorMessage(request, env, "Clad no respondió a tiempo. Puedes continuar con el resto del análisis.", 502);
  }
  if (upstream.status === 401 || upstream.status === 403) {
    return errorMessage(request, env, "La clave de Clad no es válida o no tiene acceso.", 502);
  }
  if (!upstream.ok) {
    return errorMessage(request, env, "Clad no pudo iniciar la reconstrucción en este momento.", 502);
  }

  const job = await upstream.json();
  const jobId = String(job.job_id || "");
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) {
    return errorMessage(request, env, "Clad no devolvió un identificador de trabajo válido.", 502);
  }
  let pollUrl;
  try { pollUrl = checkedPollUrl(job.poll_url, base, jobId); }
  catch { pollUrl = checkedPollUrl(null, base, jobId); }
  return json(request, env, { status: "queued", jobId: jobId, pollUrl: pollUrl });
}

async function pollCladJob(request, env) {
  if (!env.CLAD_API_KEY) {
    return errorMessage(request, env, "La conexión de reconstrucción 3D aún no está configurada.", 503);
  }
  const body = await readJson(request);
  const jobId = String(body.jobId || "");
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) {
    return errorMessage(request, env, "El identificador de reconstrucción no es válido.", 400);
  }

  let base, pollUrl;
  try {
    base = cladBase(env);
    pollUrl = checkedPollUrl(body.pollUrl, base, jobId);
  } catch (error) {
    return errorMessage(request, env, error.message, 400);
  }

  let upstream;
  try {
    upstream = await fetch(pollUrl, {
      method: "GET",
      headers: { "Authorization": "Bearer " + env.CLAD_API_KEY },
      signal: AbortSignal.timeout(15000)
    });
  } catch {
    return errorMessage(request, env, "No se pudo consultar Clad a tiempo.", 502);
  }
  if (upstream.status === 401 || upstream.status === 403) {
    return errorMessage(request, env, "La clave de Clad no es válida o no tiene acceso.", 502);
  }
  if (!upstream.ok) return errorMessage(request, env, "No se pudo consultar la reconstrucción.", 502);

  const data = await upstream.json();
  if (data.status === "queued" || data.status === "running") {
    return json(request, env, { status: data.status, jobId: jobId });
  }
  if (data.status === "failed") {
    return json(request, env, { status: "failed", error: "Clad no pudo completar la reconstrucción. Revisa la foto e inténtalo de nuevo." }, 422);
  }
  if (data.status !== "completed" || !data.result) {
    return errorMessage(request, env, "Clad devolvió un estado de reconstrucción desconocido.", 502);
  }

  const measurements = normaliseMeasurements(data.result.measurements || {});
  if (!Object.keys(measurements).length) {
    return errorMessage(request, env, "Clad no devolvió medidas que FORMA pueda utilizar.", 502);
  }
  return json(request, env, {
    status: "completed",
    jobId: jobId,
    measurements: measurements,
    has3dModel: Boolean(data.result.mesh),
    source: "Clad"
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") {
      if (!cors["Access-Control-Allow-Origin"]) return new Response(null, { status: 403 });
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.headers.get("Origin") && !cors["Access-Control-Allow-Origin"]) {
      return errorMessage(request, env, "Origen no autorizado.", 403);
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return json(request, env, {
        ok: true,
        geminiConfigured: Boolean(env.GEMINI_API_KEY),
        cladConfigured: Boolean(env.CLAD_API_KEY),
        rateLimitsConfigured: Boolean(env.COACH_RATE_LIMITER && env.SCAN_RATE_LIMITER)
      });
    }
    if (request.method !== "POST") return errorMessage(request, env, "Ruta no disponible.", 404);
    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > MAX_BODY_BYTES) return errorMessage(request, env, "La solicitud supera el tamaño permitido.", 413);

    const rateBinding = url.pathname === "/api/coach" ? "COACH_RATE_LIMITER" :
      ["/api/scan-fallback", "/api/clad/scan", "/api/clad/poll"].includes(url.pathname) ? "SCAN_RATE_LIMITER" : null;
    if (rateBinding && await isRateLimited(request, env, rateBinding, url.pathname)) {
      return errorMessage(request, env, "Has alcanzado temporalmente el límite de solicitudes. Espera un momento y vuelve a intentarlo.", 429);
    }

    if (url.pathname === "/api/coach") {
      let body;
      try { body = await readJson(request); } catch (error) { return errorMessage(request, env, error.message, error.message === "La solicitud supera el tamaño permitido." ? 413 : 400); }
      const message = String(body.message || "").trim();
      if (!message || message.length > 500) return errorMessage(request, env, "La pregunta debe tener entre 1 y 500 caracteres.", 400);
      const context = body.context && typeof body.context === "object" ? body.context : {};
      const contextJson = JSON.stringify(context).slice(0, 7000);
      const result = await generateGemini(env, COACH_RULES, [{
        type: "text",
        text: "Contexto autorizado por el usuario (datos resumidos, no fotografías):\n" +
          contextJson + "\n\nPregunta:\n" + message
      }]);
      return result.error ? errorMessage(request, env, result.error, result.status) : json(request, env, result);
    }

    if (url.pathname === "/api/scan-fallback") {
      let body;
      try { body = await readJson(request); } catch (error) { return errorMessage(request, env, error.message, error.message === "La solicitud supera el tamaño permitido." ? 413 : 400); }
      const supplied = Array.isArray(body.images) ? body.images : [
        ...(body.frontImage ? [{ label: "Fotografía 1", image: body.frontImage }] : []),
        ...(body.sideImage ? [{ label: "Fotografía 2", image: body.sideImage }] : [])
      ];
      if (supplied.length < 1 || supplied.length > 2) {
        return errorMessage(request, env, "Envía una o dos fotografías para el análisis.", 400);
      }
      const visionInput = [];
      try {
        for (let index = 0; index < supplied.length; index++) {
          const item = supplied[index];
          const imageData = readImageDataUrl(typeof item === "string" ? item : item.image);
          const label = typeof item === "object" && item && typeof item.label === "string"
            ? item.label.slice(0, 40)
            : "Fotografía " + (index + 1);
          visionInput.push({ type: "text", text: label + ". Analiza todo lo que sea visible en esta toma:" });
          visionInput.push({ type: "image", data: imageData.base64, mime_type: imageData.mimeType });
        }
      } catch (error) {
        return errorMessage(request, env, error.message, 400);
      }
      visionInput.push({
        type: "text",
        text: "Analiza las imágenes recibidas sin exigir que sean perfectas ni completas. Entrega toda la orientación que pueda sostenerse con lo visible."
      });
      const result = await generateGemini(env, VISION_RULES, visionInput);
      return result.error ? errorMessage(request, env, result.error, result.status) : json(request, env, result);
    }

    if (url.pathname === "/api/clad/scan") {
      try { return await startCladJob(request, env); }
      catch (error) { return errorMessage(request, env, error.message === "La solicitud supera el tamaño permitido." ? error.message : "No se pudo iniciar la reconstrucción 3D.", error.message === "La solicitud supera el tamaño permitido." ? 413 : 502); }
    }
    if (url.pathname === "/api/clad/poll") {
      try { return await pollCladJob(request, env); }
      catch (error) { return errorMessage(request, env, error.message === "La solicitud supera el tamaño permitido." ? error.message : "No se pudo consultar la reconstrucción 3D.", error.message === "La solicitud supera el tamaño permitido." ? 413 : 502); }
    }
    return errorMessage(request, env, "Ruta no disponible.", 404);
  }
};
