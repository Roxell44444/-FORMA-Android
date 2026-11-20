from pathlib import Path
import re

ROOT = Path("FORMA-1.1.0")
html_path = ROOT / "index.html"
app_path = ROOT / "src/app.js"
html = html_path.read_text(encoding="utf-8")
app = app_path.read_text(encoding="utf-8")

# Remove provider-specific permission checkboxes and provider names from the scanner UI.
for element_id in ("scan-cloud-consent", "forma-clad-consent"):
    pattern = re.compile(r'<label\b[^>]*>\s*<input\b[^>]*id="' + re.escape(element_id) + r'"[^>]*>.*?</label>', re.S)
    html, count = pattern.subn("", html, count=1)
    if count != 1:
        raise SystemExit(f"Could not safely remove scanner provider control: {element_id}")

html = re.sub(
    r'<p class="scan-privacy-note">.*?</p>',
    '<p class="scan-privacy-note">FORMA analiza primero tus fotografías en el dispositivo. Si el análisis local no basta, puede utilizar procesamiento remoto seguro para completar la lectura. Tú autorizas este uso una sola vez.</p>',
    html,
    count=1,
    flags=re.S,
)
html = html.replace("Gemini", "procesamiento remoto").replace("Clad", "procesamiento remoto")
if "scan-cloud-consent" in html or "forma-clad-consent" in html:
    raise SystemExit("Provider-specific scanner copy or controls remain in the user interface.")
html_path.write_text(html, encoding="utf-8")

# A single generic, one-time permission replaces separate provider checkboxes.
anchor = "async function runBodyScan() {"
helper = """function formaEnsureCloudScanConsent() {
  try {
    if (localStorage.getItem("forma.cloud-scan-consent.v1") === "accepted") return true;
    const accepted = window.confirm(
      "Para completar el análisis cuando el procesamiento del teléfono no sea suficiente, algunas fotografías podrán enviarse a un servicio remoto de procesamiento. ¿Autorizas este uso? Puedes continuar sin autorizarlo, pero el análisis podría quedar limitado."
    );
    if (accepted) localStorage.setItem("forma.cloud-scan-consent.v1", "accepted");
    return accepted;
  } catch (error) {
    console.warn("FORMA could not store scan privacy preference:", error);
    return false;
  }
}

function formaWithTimeout(promise, milliseconds, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), milliseconds);
    })
  ]).finally(() => clearTimeout(timer));
}

"""
if app.count(anchor) != 1:
    raise SystemExit("Could not locate scanner orchestration entry point.")
if "function formaEnsureCloudScanConsent()" not in app:
    app = app.replace(anchor, helper + anchor, 1)

# The remote visual fallback must be governed by one generic consent decision.
app = app.replace(
    "  // El envío de fotografías a Gemini requiere consentimiento explícito del usuario.\n  if (!$('#scan-cloud-consent')?.checked) return null;\n",
    ""
)
app = app.replace("$('#forma-clad-consent')?.checked === true;", "formaRemoteScanAllowed;")
app = app.replace(
    """    const visualFallbackDone = $('#scan-cloud-consent')?.checked === true
      ? await runGeminiPhotoFallback()
      : null;""",
    """    const visualFallbackDone = await runGeminiPhotoFallback();"""
)
app = app.replace(
    """      $('#capture-status').textContent = $('#scan-cloud-consent')?.checked === true
        ? "No se pudo completar el análisis con la conexión actual. Comprueba Internet e inténtalo de nuevo."
        : "El análisis local no se completó. El envío opcional a Gemini está desactivado; puedes activarlo para obtener una lectura visual.";""",
    """      $('#capture-status').textContent = "No se pudo completar el análisis. Comprueba la conexión y los datos del perfil; puedes intentarlo de nuevo.";"""
)

# Bound Clad waiting time so a queued/paid/unavailable job cannot freeze the scan.
app = app.replace("while (Date.now() - startedAt < 60000)", "while (Date.now() - startedAt < 18000)")
app = app.replace("await new Promise(resolve => setTimeout(resolve, 2200));", "await new Promise(resolve => setTimeout(resolve, 1500));")
app = app.replace("Analizando la fotografía y calculando las medidas disponibles…", "Comprobando las medidas disponibles…")
app = app.replace("La reconstrucción 3D superó el tiempo de espera.", "El servicio de medidas no respondió a tiempo; FORMA continuará con el siguiente método.")

# Give local inference a bounded window and let other methods take over on failure.
app = app.replace(
    """  const [bodyCompResult, cladResult] = await Promise.allSettled([
    bodyCompPromise, cladPromise
  ]);""",
    """  const [bodyCompResult, cladResult] = await Promise.allSettled([
    formaWithTimeout(bodyCompPromise, 45000, "El análisis local superó el tiempo de espera."),
    formaWithTimeout(cladPromise, 20000, "El servicio de medidas superó el tiempo de espera.")
  ]);"""
)

# Ask once before any remote photo processing; declining still allows local analysis.
if "let formaRemoteScanAllowed = false;" not in app:
    app = app.replace(anchor, "let formaRemoteScanAllowed = false;\n\n" + anchor, 1)
fallback_anchor = "async function runGeminiPhotoFallback() {"
if app.count(fallback_anchor) != 1:
    raise SystemExit("Could not find visual fallback entry point.")
app = app.replace(fallback_anchor, fallback_anchor + "\n  if (!formaRemoteScanAllowed) return null;", 1)
start_anchor = """  scanBusy = true;
  updateScanButton();"""
if app.count(start_anchor) != 1:
    raise SystemExit("Could not safely insert one-time scan privacy confirmation.")
app = app.replace(
    start_anchor,
    """  formaRemoteScanAllowed = formaEnsureCloudScanConsent();
  scanBusy = true;
  updateScanButton();""",
    1
)

# Do not discard valid composition estimates solely because no perimeter was returned.
old = """    if (!Object.keys(measurements).length) {
      bodyComp = null;
      composition = null;
    }"""
if old in app:
    app = app.replace(old, "    if (!Object.keys(measurements).length) measurements = null;", 1)

app = app.replace("LECTURA VISUAL DE GEMINI", "LECTURA VISUAL")
app = app.replace("Modelo BodyComp · análisis fotográfico", "Análisis fotográfico")
app = app.replace('result.analysisProvider === "Clad" ? "Reconstrucción a partir de fotografía" : "Análisis fotográfico"', '"Análisis fotográfico"')
app = app.replace("Gemini analizó las fotografías y describió lo que puede observarse.", "La lectura visual de tus fotografías está lista.")
app = app.replace("Análisis completado con composición estimada y lectura visual de Gemini.", "Análisis completado con composición estimada y lectura visual.")
app = app.replace("Se obtuvieron medidas parciales y Gemini completó una lectura visual.", "Se obtuvieron medidas parciales y se completó una lectura visual.")
app = app.replace(" cm · Clad", " cm")
app = app.replace("detector = await createPoseLandmarker();", 'detector = await formaWithTimeout(createPoseLandmarker(), 15000, "El detector de postura superó el tiempo de espera.");')
for forbidden in ("scan-cloud-consent", "forma-clad-consent"):
    if forbidden in app:
        raise SystemExit(f"Provider-specific control reference remains in app.js: {forbidden}")

app_path.write_text(app, encoding="utf-8")
print("FORMA scanner privacy and failover patch applied.")
