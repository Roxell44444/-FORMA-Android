from pathlib import Path
import re

ROOT = Path("FORMA-1.1.0")
index_path = ROOT / "index.html"
app_path = ROOT / "src/app.js"
css_path = ROOT / "src/ui/styles.css"

def once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one occurrence, found {count}")
    return source.replace(old, new, 1)

# Explicit, separate opt-ins: local processing remains available without either.
html = index_path.read_text(encoding="utf-8")
button = '              <button class="button button-primary full-width analyze-button" id="analyze-body-scan" disabled>Analizar mis fotos</button>'
if button not in html:
    button = '              <button class="button button-primary full-width analyze-button" id="analyze-body-scan" disabled>Analizar mi físico</button>'
if button not in html:
    raise SystemExit("Scanner action button was not found; refusing to inject consent controls in an unknown location.")
privacy = re.search(r'<p class="scan-privacy-note">.*?</p>', html, flags=re.S)
if not privacy:
    raise SystemExit("Scanner privacy notice was not found.")
privacy_copy = (
    '<p class="scan-privacy-note">FORMA intentará analizar las imágenes con los motores locales. '
    'Gemini y Clad son servicios externos y solo reciben fotografías cuando activas sus permisos independientes.</p>'
)
html = html[:privacy.start()] + privacy_copy + html[privacy.end():]

consent_parts = []
if 'id="scan-cloud-consent"' not in html:
    consent_parts.append('''              <label class="forma-consent-row" for="scan-cloud-consent">
                <input id="scan-cloud-consent" type="checkbox">
                <span><strong>Permitir lectura visual con Gemini</strong><small>Envía las fotografías seleccionadas a Google para describir las zonas visibles si los cálculos locales no están disponibles. Opcional.</small></span>
              </label>
''')
if 'id="forma-clad-consent"' not in html:
    consent_parts.append('''              <label class="forma-consent-row" for="forma-clad-consent">
                <input id="forma-clad-consent" type="checkbox">
                <span><strong>Permitir reconstrucción de medidas con Clad</strong><small>Envía la foto frontal y la estatura a Clad para intentar obtener perímetros. Servicio externo y opcional.</small></span>
              </label>
''')
if consent_parts:
    html = once(html, button, "".join(consent_parts) + button, "scanner consent controls")
index_path.write_text(html, encoding="utf-8")

# Improve the orchestration: each engine is independent and consent-gated.
app = app_path.read_text(encoding="utf-8")
# Enforce Gemini photo consent regardless of whether the current scanner
# starts the visual engine in parallel or invokes it after numeric engines fail.
parallel_visual = '  const visualPromise = Promise.resolve().then(() => runGeminiPhotoFallback());'
sequential_visual = '    visualText = await runGeminiPhotoFallback();'
if parallel_visual in app:
    app = once(
        app,
        parallel_visual,
        '''  const cloudAnalysisAllowed = $('#scan-cloud-consent')?.checked === true;
  const visualPromise = cloudAnalysisAllowed
    ? Promise.resolve().then(() => runGeminiPhotoFallback())
    : Promise.resolve(null);''',
        "Gemini explicit opt-in",
    )
elif sequential_visual in app:
    app = once(
        app,
        sequential_visual,
        '''    if ($('#scan-cloud-consent')?.checked === true) {
      visualText = await runGeminiPhotoFallback();
    }''',
        "Gemini explicit opt-in",
    )
elif "$('#scan-cloud-consent')?.checked === true" not in app:
    raise SystemExit("Gemini opt-in is not enforced in the scanner code.")
old_clad_gate = '''  const canRunClad = Boolean(imageForClad) &&
    Number(profile.height) >= 140 && Number(profile.height) <= 220;'''
if old_clad_gate in app:
    app = once(
        app,
        old_clad_gate,
        '''  const canRunClad = Boolean(imageForClad) &&
    Number(profile.height) >= 140 && Number(profile.height) <= 220 &&
    $('#forma-clad-consent')?.checked === true;''',
        "Clad explicit opt-in",
    )
elif "$('#forma-clad-consent')?.checked === true" not in app:
    raise SystemExit("Clad opt-in is not enforced in the scanner code.")

# Do not throw away body-fat and appendicular-lean estimates just because a
# perimeter is missing. Preserve each valid field independently.
app = once(
    app,
    '''    if (!Object.keys(measurements).length) {
      bodyComp = null;
      composition = null;
    }
    captureQuality = bodyComp ? bodyCompResult.value.quality : null;''',
    '''    if (!Object.keys(measurements).length) measurements = null;
    captureQuality = bodyComp ? bodyCompResult.value.quality : null;''',
    "preserve partial BodyComp results",
)
app = once(
    app,
    '''  const cladMeasurements = clad ? clad.measurements : null;
  if (!measurements && clad) measurements = clad.measurements;
  state.scanResult = {''',
    '''  const bodyCompMeasurements = measurements;
  const cladMeasurements = clad ? clad.measurements : null;
  const combinedMeasurements = { ...(bodyCompMeasurements || {}) };
  if (cladMeasurements) {
    for (const [key, value] of Object.entries(cladMeasurements)) {
      if (!combinedMeasurements[key]) combinedMeasurements[key] = value;
    }
  }
  measurements = Object.keys(combinedMeasurements).length ? combinedMeasurements : null;
  state.scanResult = {''',
    "merge available perimeters without overwriting primary estimates",
)
app = once(
    app,
    '    crossCheck: compareScanEngines(bodyComp ? measurements : null, cladMeasurements),',
    '    crossCheck: compareScanEngines(bodyCompMeasurements, cladMeasurements),',
    "compare independent engine results",
)
app = once(
    app,
    '"Los motores no pudieron completar el análisis. Comprueba la conexión e inténtalo de nuevo."',
    'cloudAnalysisAllowed ? "No llegó una respuesta visual de Gemini. Comprueba la conexión e inténtalo de nuevo." : "El análisis local no pudo obtener cifras con esta fotografía. Activa Gemini para recibir una lectura de las zonas visibles; el envío externo es opcional."',
    "helpful no-result message",
)

# Keep a compact local history of completed scans. It contains measurements,
# estimates and timestamps only — never photographs or Gemini conversation text.
history_code = r"""
// FORMA local scan history: compact snapshots only, capped at 12 records.
const formaOriginalRenderScanResult = renderScanResult;
renderScanResult = function(...args) {
  const result = state.scanResult;
  if (result && result.createdAt) {
    state.scanHistory = Array.isArray(state.scanHistory) ? state.scanHistory : [];
    const id = String(result.createdAt);
    if (!state.scanHistory.some(item => item && item.id === id)) {
      const composition = result.composition || {};
      const measurements = result.measurements || {};
      const finite = value => value !== null && value !== undefined && Number.isFinite(Number(value));
      state.scanHistory.unshift({
        id,
        createdAt: id,
        provider: result.analysisProvider || "FORMA",
        bodyFatPercent: finite(composition.bodyFatPercent) ? Number(composition.bodyFatPercent) : null,
        bodyFatLow: finite(composition.bodyFatLow) ? Number(composition.bodyFatLow) : null,
        bodyFatHigh: finite(composition.bodyFatHigh) ? Number(composition.bodyFatHigh) : null,
        waistCm: finite(measurements.waist?.circumferenceCm) ? Number(measurements.waist.circumferenceCm) : null,
        hipCm: finite(measurements.hip?.circumferenceCm) ? Number(measurements.hip.circumferenceCm) : null,
        photoCount: Number(result.visualFallback?.imageCount || 0)
      });
      state.scanHistory = state.scanHistory.slice(0, 12);
      try { saveState(); } catch (error) { console.warn("FORMA could not persist scan history:", error); }
    }
  }

  formaOriginalRenderScanResult.apply(this, args);
  const root = $('#scan-result');
  if (!root) return;
  root.querySelector(".forma-scan-history")?.remove();
  const history = Array.isArray(state.scanHistory) ? state.scanHistory : [];
  if (!history.length) return;

  const dateLabel = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Fecha no disponible" :
      new Intl.DateTimeFormat("es", { day:"2-digit", month:"short", year:"numeric" }).format(date);
  };
  const previous = history[1];
  const current = history[0];
  const delta = (a, b, unit) => Number.isFinite(a) && Number.isFinite(b)
    ? (a - b > 0 ? "+" : "") + (a - b).toFixed(1) + unit
    : "—";
  const rows = history.slice(0, 6).map((item, index) => {
    const fat = Number.isFinite(item.bodyFatPercent) ? item.bodyFatPercent.toFixed(1) + "%" : "Lectura visual";
    const waist = Number.isFinite(item.waistCm) ? item.waistCm.toFixed(1) + " cm" : "—";
    const marker = index === 0 ? '<span class="forma-history-current">Más reciente</span>' : "";
    return '<li><div><strong>' + dateLabel(item.createdAt) + '</strong>' + marker +
      '<small>' + String(item.provider || "FORMA").replace(/[<>&"]/g, "") + '</small></div>' +
      '<span>' + fat + '</span><span>' + waist + '</span></li>';
  }).join("");
  const summary = previous
    ? '<p class="forma-history-delta">Último cambio · grasa: <strong>' +
      delta(current.bodyFatPercent, previous.bodyFatPercent, " pp") +
      '</strong> · cintura: <strong>' + delta(current.waistCm, previous.waistCm, " cm") +
      '</strong></p>'
    : '<p class="forma-history-delta">Conserva tus próximos análisis para ver la evolución entre fechas.</p>';
  root.insertAdjacentHTML("beforeend",
    '<section class="forma-scan-history" aria-label="Historial de análisis">' +
      '<div class="forma-history-heading"><div><span>SEGUIMIENTO LOCAL</span><h3>Tu evolución</h3></div>' +
      '<button type="button" class="forma-history-clear" id="clear-forma-scan-history">Borrar historial</button></div>' +
      summary +
      '<div class="forma-history-table-head"><span>FECHA</span><span>GRASA</span><span>CINTURA</span></div>' +
      '<ol>' + rows + '</ol>' +
      '<small class="forma-history-privacy">Se guarda en este dispositivo. El historial no contiene fotografías.</small>' +
    '</section>');
  root.querySelector("#clear-forma-scan-history")?.addEventListener("click", () => {
    state.scanHistory = [];
    try { saveState(); } catch (error) { console.warn("FORMA history clear failed:", error); }
    root.querySelector(".forma-scan-history")?.remove();
  });
};
"""
app += "\n" + history_code + "\n"
app_path.write_text(app, encoding="utf-8")

# Final UI polish. This is deliberately appended after other theme layers.
css = css_path.read_text(encoding="utf-8")
css += r"""
/* FORMA 1.7 · shared premium design tokens and responsive scan history */
:root {
  --forma-bg:#090f13;
  --forma-surface:#121c22;
  --forma-surface-raised:#18252c;
  --forma-border:rgba(198,224,212,.13);
  --forma-text:#f2f7f4;
  --forma-muted:#9aada5;
  --forma-accent:#b8ef58;
}
h1,h2,h3,h4 { letter-spacing:-.04em; }
.panel,.metric-card,.capture-slot,.capture-panel,.scan-instructions,.summary-tile,.calorie-box,.coach-panel {
  border-color:var(--forma-border) !important;
  box-shadow:0 16px 42px rgba(0,0,0,.16) !important;
}
.panel { border-radius:24px !important; }
.section-heading,.page-heading { margin-bottom:18px; }
button,input,select,textarea { font:inherit; }
button { -webkit-tap-highlight-color:transparent; }
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible {
  outline:2px solid var(--forma-accent) !important;
  outline-offset:3px;
}
.forma-consent-row {
  display:flex;
  align-items:flex-start;
  gap:11px;
  margin:10px 0;
  padding:13px 14px;
  border:1px solid var(--forma-border);
  border-radius:15px;
  background:rgba(255,255,255,.025);
  color:var(--forma-text);
  cursor:pointer;
}
.forma-consent-row input {
  flex:0 0 18px;
  width:18px;
  height:18px;
  margin:2px 0 0;
  accent-color:var(--forma-accent);
}
.forma-consent-row span { display:grid; gap:4px; min-width:0; }
.forma-consent-row strong { color:var(--forma-text); font-size:13px; line-height:1.35; }
.forma-consent-row small { color:var(--forma-muted); font-size:11px; line-height:1.5; }
.forma-consent-row:has(input:checked) {
  border-color:rgba(184,239,88,.38);
  background:rgba(184,239,88,.055);
}
.forma-scan-history {
  margin-top:26px;
  padding-top:22px;
  border-top:1px solid var(--forma-border);
  color:var(--forma-text);
}
.forma-history-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.forma-history-heading>div>span {
  color:var(--forma-accent); font-size:9px; font-weight:850; letter-spacing:.17em;
}
.forma-history-heading h3 { margin:5px 0 0; font-size:20px; }
.forma-history-clear {
  border:0; background:transparent; color:var(--forma-muted);
  font-size:10px; text-decoration:underline; text-underline-offset:3px;
}
.forma-history-delta { color:var(--forma-muted); font-size:11px; line-height:1.5; margin:13px 0; }
.forma-history-delta strong { color:#dff4c3; font-variant-numeric:tabular-nums; }
.forma-history-table-head,.forma-scan-history li {
  display:grid; grid-template-columns:minmax(0,1.3fr) .8fr .8fr; gap:8px; align-items:center;
}
.forma-history-table-head {
  padding:9px 0; border-bottom:1px solid var(--forma-border);
  color:#82978d; font-size:8px; font-weight:850; letter-spacing:.1em;
}
.forma-scan-history ol { list-style:none; padding:0; margin:0; }
.forma-scan-history li {
  min-height:54px; padding:9px 0; border-bottom:1px solid rgba(198,224,212,.07);
  color:#e6eee9; font-size:11px; font-variant-numeric:tabular-nums;
}
.forma-scan-history li>div { display:grid; gap:4px; min-width:0; }
.forma-scan-history li>div strong { font-size:11px; }
.forma-scan-history li>div small { color:var(--forma-muted); font-size:9px; }
.forma-scan-history li>span { text-align:left; }
.forma-history-current {
  display:inline-block; width:max-content; padding:2px 6px; border-radius:999px;
  color:#d8f4a6 !important; background:rgba(184,239,88,.10); font-size:8px !important;
}
.forma-history-privacy {
  display:block; margin-top:12px; color:#82978d; font-size:9px; line-height:1.5;
}
@media(max-width:430px) {
  .forma-history-heading { align-items:flex-start; }
  .forma-history-table-head,.forma-scan-history li { grid-template-columns:minmax(0,1.2fr) .8fr .8fr; gap:5px; }
  .forma-scan-history li { font-size:10px; }
}
@media(prefers-reduced-motion:reduce) {
  *,*::before,*::after { animation-duration:.01ms !important; transition-duration:.01ms !important; scroll-behavior:auto !important; }
}
"""
css_path.write_text(css, encoding="utf-8")

# Re-apply the offline model path after the base ZIP is unpacked.
bodycomp_path = ROOT / "src/scanner/bodycomp.js"
bodycomp = bodycomp_path.read_text(encoding="utf-8")
bodycomp, model_base_count = re.subn(
    r'const BODYCOMP_MODELS = [^;]+;',
    'const BODYCOMP_MODELS = new URL("../../models/bodycomp/", import.meta.url).href;',
    bodycomp,
    count=1,
)
if model_base_count != 1:
    raise SystemExit("Could not configure bundled BodyComp model assets.")
bodycomp_path.write_text(bodycomp, encoding="utf-8")

# Build-time invariants: fail early if a later generator change drops a feature.
check = app_path.read_text(encoding="utf-8")
for required in ["scan-cloud-consent", "forma-clad-consent", "forma-scan-history", "preserve partial"]:
    if required == "preserve partial":
        continue
    if required not in (html + check):
        raise SystemExit(f"FORMA 1.7 invariant missing: {required}")
if "new URL(\"../../models/bodycomp/\", import.meta.url).href" not in (ROOT / "src/scanner/bodycomp.js").read_text(encoding="utf-8"):
    raise SystemExit("BodyComp regression models are not configured for local bundled loading.")

print("FORMA 1.7 quality pass applied: explicit cloud consent, partial results, local scan history and unified UI.")
