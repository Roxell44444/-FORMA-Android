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
        '''    const cloudAnalysisAllowed = $('#scan-cloud-consent')?.checked === true;
    if (cloudAnalysisAllowed) {
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
# Scan history is already implemented by forma-clad.py; avoid a duplicate wrapper.

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
.forma-history-header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.forma-history-header h3 { color:var(--forma-text); font-size:19px; margin:6px 0 4px; }
.forma-history-header p { color:var(--forma-muted); font-size:11px; line-height:1.5; margin:0; }
.forma-history-count {
  display:grid; place-items:center; min-width:30px; height:30px; padding:0 8px;
  border-radius:999px; background:rgba(184,239,88,.1); color:var(--forma-accent);
  font-size:12px; font-weight:800;
}
.forma-history-chart { display:block; width:100%; max-height:110px; margin:16px 0 6px; }
.forma-history-trend { margin:0 0 12px; color:#d8f4a6; font-size:11px; font-weight:750; }
.forma-history-empty { color:var(--forma-muted); font-size:11px; line-height:1.5; }
.forma-history-list { display:grid; }
.forma-history-row {
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:12px 0; border-top:1px solid rgba(198,224,212,.08);
}
.forma-history-row span { flex:0 0 82px; color:var(--forma-muted); font-size:11px; }
.forma-history-row strong { color:var(--forma-text); font-size:11px; font-weight:650; text-align:right; }
.forma-history-note { margin:12px 0 0; color:var(--forma-muted); font-size:10px; line-height:1.5; }
@media(max-width:430px) {
  .forma-history-row { align-items:flex-start; flex-direction:column; gap:4px; }
  .forma-history-row strong { text-align:left; }
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
