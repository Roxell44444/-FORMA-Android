const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400"
};

const COACH_RULES = [
  "Eres FORMA Coach, un asistente en español especializado exclusivamente en entrenamiento, ejercicio, nutrición general, descanso, recuperación y hábitos de bienestar.",
  "Responde de forma práctica, amable y personalizada con el contexto proporcionado. Limita la respuesta a este ámbito; para cualquier otro tema explica amablemente tu especialidad y redirige la conversación.",
  "No diagnostiques enfermedades, no interpretes análisis clínicos, no prescribas medicamentos ni trates lesiones. Ante síntomas preocupantes, recomienda detener la actividad y consultar a profesionales sanitarios.",
  "No inventes resultados ni medidas. Distingue las estimaciones visuales de las mediciones directas.",
  "Si el perfil es menor de 18 años, no des objetivos de calorías, pérdida de peso, grasa corporal, macros ni rutinas de fuerza adultas. Prioriza crecimiento, hábitos variados y actividad apropiada para la edad.",
  "No fomentes dietas extremas, deshidratación, suplementos peligrosos ni cambios bruscos. Responde en español claro y evita jerga."
].join(" ");

const VISION_RULES = [
  "Eres un asistente visual de bienestar de FORMA. Solo puedes ofrecer observaciones cualitativas y orientación general sobre la calidad de las fotografías para un análisis corporal.",
  "No estimes ni inventes porcentajes de grasa, masa muscular, peso, edad, sexo, perímetros, calorías ni ninguna cifra corporal a partir de las imágenes.",
  "No diagnostiques ni hagas juicios sobre atractivo, salud o condición médica. No identifiques a la persona.",
  "Indica si se ve el cuerpo completo, la postura, la iluminación y si las vistas frontal y lateral parecen utilizables. Describe únicamente observaciones generales y limita las recomendaciones a cómo repetir la foto.",
  "Empieza dejando claro que es una orientación visual aproximada y no una medición."
].join(" ");

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
  });
}

function splitDataUrl(value) {
  if (typeof value !== "string" || value.length > 5_500_000) throw new Error("Imagen no válida o demasiado grande.");
  const match = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match) throw new Error("Formato de imagen no admitido.");
  return { mime_type: match[1], data: match[2] };
}

async function generate(env, system, parts) {
  if (!env.GEMINI_API_KEY) return json({ error: "El asistente inteligente aún no está configurado." }, 503);
  const model = env.GEMINI_MODEL || "gemini-3.8-flash";
  const endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" +
    encodeURIComponent(model) + ":generateContent";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: "user", parts }],
      generationConfig: { temperature: 0.45, maxOutputTokens: 700 }
    })
  });
  if (!response.ok) {
    // Never return provider details, credentials or request contents to the app.
    return json({ error: "El servicio inteligente no pudo responder ahora." }, 502);
  }
  const result = await response.json();
  const text = (result.candidates?.[0]?.content?.parts || [])
    .map(part => part.text || "").join("\n").trim();
  if (!text) return json({ error: "No llegó una respuesta utilizable." }, 502);
  return json({ text });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, aiConfigured: Boolean(env.GEMINI_API_KEY) });
    }
    if (request.method !== "POST") return json({ error: "Ruta no disponible." }, 404);
    const length = Number(request.headers.get("content-length") || 0);
    if (length > 12_000_000) return json({ error: "La solicitud supera el tamaño permitido." }, 413);

    if (url.pathname === "/api/coach") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Solicitud no válida." }, 400); }
      const message = String(body.message || "").trim();
      if (!message || message.length > 500) return json({ error: "La pregunta debe tener entre 1 y 500 caracteres." }, 400);
      const context = body.context && typeof body.context === "object" ? body.context : {};
      const contextJson = JSON.stringify(context).slice(0, 7000);
      return generate(env, COACH_RULES, [{
        text: "Contexto autorizado por el usuario (datos resumidos, no fotografías):\n" +
          contextJson + "\n\nPregunta:\n" + message
      }]);
    }

    if (url.pathname === "/api/scan-fallback") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Solicitud no válida." }, 400); }
      try {
        const front = splitDataUrl(body.frontImage);
        const side = splitDataUrl(body.sideImage);
        return generate(env, VISION_RULES, [
          { text: "Vista frontal de la persona:" },
          { inline_data: front },
          { text: "Vista lateral de la misma persona:" },
          { inline_data: side },
          { text: "Proporciona solo una orientación cualitativa y las indicaciones para repetir las fotos si hacen falta." }
        ]);
      } catch (error) {
        return json({ error: error.message || "Las imágenes no son válidas." }, 400);
      }
    }
    return json({ error: "Ruta no disponible." }, 404);
  }
};
