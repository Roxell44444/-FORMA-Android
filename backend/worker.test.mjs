import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

const ORIGIN = "https://appassets.androidplatform.net";
const ENV = { ALLOWED_ORIGINS: ORIGIN };

function request(path, body, method = "POST", headers = {}) {
  return new Request("https://forma.example" + path, {
    method,
    headers: { Origin: ORIGIN, ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...headers },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

test("health reports which server secrets are present without revealing them", async () => {
  const response = await worker.fetch(request("/health", undefined, "GET"), ENV);
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.ok, true);
  assert.equal(data.geminiConfigured, false);
  assert.equal(data.cladConfigured, false);
  assert.equal(data.rateLimitsConfigured, false);
});

test("rejects browser origins that are not explicitly allowed", async () => {
  const req = new Request("https://forma.example/health", {
    headers: { Origin: "https://unknown.example" }
  });
  const response = await worker.fetch(req, ENV);
  assert.equal(response.status, 403);
});

test("rate limiting can reject Coach requests before calling Gemini", async () => {
  let calls = 0;
  const limitedEnv = {
    ...ENV,
    COACH_RATE_LIMITER: {
      async limit(input) {
        calls++;
        assert.ok(input.key.includes("203.0.113.10"));
        assert.ok(input.key.includes("/api/coach"));
        return { success: false };
      }
    }
  };
  const response = await worker.fetch(
    request("/api/coach", { message: "Hola" }, "POST", { "CF-Connecting-IP": "203.0.113.10" }),
    limitedEnv
  );
  assert.equal(response.status, 429);
  assert.equal(calls, 1);
});

test("Clad polling has a separate limit so normal polling does not consume scan-start quota", async () => {
  let scanCalls = 0;
  let pollCalls = 0;
  const env = {
    ...ENV,
    SCAN_RATE_LIMITER: { async limit() { scanCalls++; return { success: false }; } },
    CLAD_POLL_RATE_LIMITER: { async limit(input) {
      pollCalls++;
      assert.ok(input.key.includes("/api/clad/poll"));
      return { success: true };
    } }
  };
  const response = await worker.fetch(
    request("/api/clad/poll", { jobId: "job_123" }, "POST", { "CF-Connecting-IP": "203.0.113.11" }),
    env
  );
  assert.equal(response.status, 503); // Clad is optional and no key is configured in this test.
  assert.equal(scanCalls, 0);
  assert.equal(pollCalls, 1);
});

test("rejects oversized request bodies before parsing JSON", async () => {
  const req = new Request("https://forma.example/api/coach", {
    method: "POST",
    headers: { Origin: ORIGIN, "Content-Type": "application/json", "Content-Length": "12000001" },
    body: "{}"
  });
  const response = await worker.fetch(req, ENV);
  assert.equal(response.status, 413);
});

test("Gemini Coach uses Interactions and disables server-side conversation storage", async () => {
  const originalFetch = globalThis.fetch;
  let observed;
  globalThis.fetch = async (url, options) => {
    observed = { url: String(url), options, body: JSON.parse(options.body) };
    return Response.json({
      status: "completed",
      steps: [{ type: "model_output", content: [{ type: "text", text: "Respuesta de prueba." }] }]
    });
  };
  try {
    const response = await worker.fetch(
      request("/api/coach", { message: "¿Cómo organizo mi entrenamiento?", context: { profile: { age: 30 } } }),
      { ...ENV, GEMINI_API_KEY: "test-gemini-key", GEMINI_MODEL: "gemini-3.5-flash-lite" }
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { text: "Respuesta de prueba." });
    assert.equal(observed.url, "https://generativelanguage.googleapis.com/v1beta/interactions");
    assert.equal(observed.options.headers["x-goog-api-key"], "test-gemini-key");
    assert.equal(observed.body.model, "gemini-3.5-flash-lite");
    assert.equal(observed.body.store, false);
    assert.match(observed.body.system_instruction, /FORMA Coach/);
    assert.equal(observed.body.generation_config.temperature, 0.45);
    assert.equal(observed.body.input[0].type, "text");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Gemini visual fallback analyzes a single arbitrary photo", async () => {
  const originalFetch = globalThis.fetch;
  let observed;
  globalThis.fetch = async (url, options) => {
    observed = JSON.parse(options.body);
    return Response.json({
      status: "completed",
      steps: [{ type: "model_output", content: [{ type: "text", text: "LECTURA VISUAL\\nSe observa la zona visible." }] }]
    });
  };
  try {
    const image = "data:image/jpeg;base64," + btoa("partial-body-photo");
    const response = await worker.fetch(
      request("/api/scan-fallback", { images: [{ label: "Foto subida", image }] }),
      { ...ENV, GEMINI_API_KEY: "test-gemini-key" }
    );
    assert.equal(response.status, 200);
    assert.match((await response.json()).text, /LECTURA VISUAL/);
    assert.equal(observed.input.filter(item => item.type === "image").length, 1);
    assert.match(observed.system_instruction, /Analiza siempre lo que esté visible/);
    assert.equal(observed.store, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Clad photo job sends only the frontal photo and height, then polls the same provider host", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).endsWith("/v1/body/from-photo")) {
      assert.equal(options.headers.Authorization, "Bearer test-clad-key");
      const form = options.body;
      assert.equal(form.get("height_cm"), "172");
      const photo = form.get("photo");
      assert.equal(photo.name, "forma-front.jpg");
      assert.equal(photo.type, "image/jpeg");
      return Response.json({ job_id: "job_123", poll_url: "https://api.clad.you/v1/jobs/job_123" });
    }
    if (String(url) === "https://api.clad.you/v1/jobs/job_123") {
      assert.equal(options.headers.Authorization, "Bearer test-clad-key");
      return Response.json({
        status: "completed",
        result: {
          measurements: { waist_cm: 80, bust_cm: 94, hip_cm: 100, thigh_cm: 54, upperarm_cm: 29 },
          mesh: "not-returned-to-client"
        }
      });
    }
    throw new Error("Unexpected provider request: " + String(url));
  };
  try {
    const frontImage = "data:image/jpeg;base64," + btoa("front-test-image");
    const started = await worker.fetch(
      request("/api/clad/scan", { frontImage, heightCm: 172 }),
      { ...ENV, CLAD_API_KEY: "test-clad-key" }
    );
    assert.equal(started.status, 200);
    const job = await started.json();
    assert.equal(job.jobId, "job_123");
    assert.equal(job.status, "queued");

    const polled = await worker.fetch(
      request("/api/clad/poll", job),
      { ...ENV, CLAD_API_KEY: "test-clad-key" }
    );
    assert.equal(polled.status, 200);
    const result = await polled.json();
    assert.equal(result.status, "completed");
    assert.equal(result.measurements.waist_cm, 80);
    assert.equal(result.measurements.bust_cm, 94);
    assert.equal(result.has3dModel, true);
    assert.equal(calls.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Clad poll URLs cannot redirect the provider key to another host", async () => {
  const response = await worker.fetch(
    request("/api/clad/poll", { jobId: "job_123", pollUrl: "https://attacker.example/v1/jobs/job_123" }),
    { ...ENV, CLAD_API_KEY: "test-clad-key" }
  );
  assert.equal(response.status, 400);
});


test("rate limits expensive Coach requests before contacting Gemini", async () => {
  let observedKey = null;
  const response = await worker.fetch(
    request("/api/coach", { message: "Dame un plan", context: {} }, "POST", { "cf-connecting-ip": "203.0.113.10" }),
    {
      ...ENV,
      COACH_RATE_LIMITER: {
        limit: async ({ key }) => { observedKey = key; return { success: false }; }
      }
    }
  );
  assert.equal(response.status, 429);
  assert.equal(observedKey, "203.0.113.10:/api/coach");
});

test("rate limits photo analysis independently from Coach traffic", async () => {
  let observedKey = null;
  const response = await worker.fetch(
    request("/api/scan-fallback", { images: [] }, "POST", { "cf-connecting-ip": "203.0.113.11" }),
    {
      ...ENV,
      SCAN_RATE_LIMITER: {
        limit: async ({ key }) => { observedKey = key; return { success: false }; }
      }
    }
  );
  assert.equal(response.status, 429);
  assert.equal(observedKey, "203.0.113.11:/api/scan-fallback");
});

test("rejects streamed JSON bodies that exceed the maximum even without Content-Length", async () => {
  const response = await worker.fetch(new Request("https://forma.example/api/scan-fallback", {
    method: "POST",
    headers: { Origin: ORIGIN, "Content-Type": "application/json" },
    body: " ".repeat(12_000_100)
  }), ENV);
  assert.equal(response.status, 413);
});
