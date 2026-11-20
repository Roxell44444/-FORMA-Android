from pathlib import Path

ROOT = Path("FORMA-1.1.0")

def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)

# Separate opt-in. Only the front photo and height are sent to Clad.
index_path = ROOT / "index.html"
html = index_path.read_text(encoding="utf-8")
anchor = '              <p class="scan-privacy-note">Puedes analizar una o dos fotos, desde cualquier ángulo. FORMA estudiará lo que se vea; las medidas numéricas aparecerán solo cuando exista información suficiente.</p>'
consent = ''
if "scan-privacy-note" not in html:
    raise SystemExit("Scanner privacy notice is missing.")
index_path.write_text(html, encoding="utf-8")

app_path = ROOT / "src/app.js"
app = app_path.read_text(encoding="utf-8")
app = once(
    app,
    "import { askFormaCoach, askFormaVisualFallback } from './core/remote.js';",
    "import { askFormaCoach, askFormaVisualFallback, startCladPhotoJob, pollCladPhotoJob } from './core/remote.js';",
    "Clad client imports",
)

start = app.index("async function runBodyScan() {")
end = app.index("async function analyzeCapture", start)
new_scan = '''function cladMeasurementsFromResult(data) {
  const source = data && data.measurements ? data.measurements : {};
  const mapping = {
    waist: "waist_cm",
    hip: "hip_cm",
    chest: "bust_cm",
    thigh: "thigh_cm",
    bicep: "upperarm_cm"
  };
  const result = {};
  for (const [key, sourceKey] of Object.entries(mapping)) {
    const value = Number(source[sourceKey]);
    if (Number.isFinite(value) && value > 0 && value < 250) {
      result[key] = { circumferenceCm: value, source: "Clad" };
    }
  }
  if (!Object.keys(result).length) throw new Error("Clad no devolvió medidas utilizables.");
  return result;
}

async function runCladPhotoScan(imageElement) {
  const heightCm = Number(state.profile?.height);
  if (!Number.isFinite(heightCm) || heightCm < 140 || heightCm > 220) {
    throw new Error("No hay una estatura compatible para la reconstrucción.");
  }
  const frontImage = await imageToCompactDataUrl(imageElement);
  const job = await startCladPhotoJob({ frontImage, heightCm });
  if (!job.jobId || !job.pollUrl) throw new Error("No se pudo iniciar la reconstrucción 3D.");
  const startedAt = Date.now();
  while (Date.now() - startedAt < 180000) {
    const result = await pollCladPhotoJob({ jobId: job.jobId, pollUrl: job.pollUrl });
    if (result.status === "completed") {
      return {
        measurements: cladMeasurementsFromResult(result),
        has3dModel: result.has3dModel === true
      };
    }
    if (result.status === "failed") throw new Error(result.error || "No se pudo completar la reconstrucción 3D.");
    $('#capture-status').textContent = "Analizando la fotografía y calculando las medidas disponibles…";
    await new Promise(resolve => setTimeout(resolve, 2200));
  }
  throw new Error("La reconstrucción 3D superó el tiempo de espera.");
}

function compareScanEngines(bodyCompMeasurements, cladMeasurements) {
  if (!bodyCompMeasurements || !cladMeasurements) return null;
  const output = {};
  for (const key of ["waist", "hip", "chest", "thigh", "bicep"]) {
    const a = Number(bodyCompMeasurements[key]?.circumferenceCm);
    const b = Number(cladMeasurements[key]?.circumferenceCm);
    if (Number.isFinite(a) && Number.isFinite(b)) output[key] = Number(Math.abs(a - b).toFixed(1));
  }
  return output;
}

async function runGeminiPhotoFallback() {
  try {
    const candidates = [
      { label: "Primera fotografía", image: $('img', $('#slot-front')) },
      { label: "Segunda fotografía", image: $('img', $('#slot-side')) }
    ].filter(item => item.image && item.image.complete && item.image.naturalWidth > 0);
    if (!candidates.length) return null;
    const images = await Promise.all(candidates.map(async item => ({
      label: item.label,
      image: await imageToCompactDataUrl(item.image)
    })));
    const text = await askFormaVisualFallback({ images });
    return typeof text === "string" && text.trim() ? text.trim() : null;
  } catch (error) {
    console.warn("FORMA visual analysis unavailable:", error);
    return null;
  }
}

async function runBodyScan() {
  if (state.profile && state.profile.age < 18) {
    $('#capture-status').textContent = "Para menores, FORMA ofrece orientación general de bienestar, no estimaciones de composición corporal.";
    return;
  }

  const frontImage = $('img', $('#slot-front'));
  const sideImage = $('img', $('#slot-side'));
  const hasFront = Boolean(frontImage && frontImage.complete && frontImage.naturalWidth > 0);
  const hasSide = Boolean(sideImage && sideImage.complete && sideImage.naturalWidth > 0);
  if (!hasFront && !hasSide) {
    $('#capture-status').textContent = "Añade al menos una fotografía para analizar lo que aparece en ella.";
    return;
  }

  $('#capture-status').textContent = "FORMA está analizando tus fotografías…";
  const profile = state.profile || {};
  const hasNumericProfile =
    Number.isFinite(Number(profile.age)) && Number(profile.age) >= 18 && Number(profile.age) <= 59 &&
    ["male", "female"].includes(profile.equation) &&
    Number.isFinite(Number(profile.height)) && Number(profile.height) >= 130 && Number(profile.height) <= 230 &&
    Number.isFinite(Number(profile.weight)) && Number(profile.weight) > 0;

  // La segmentación local se intenta aunque MediaPipe no haya devuelto landmarks.
  // Las advertencias de calidad se muestran en el informe, no bloquean el cálculo.
  const canRunBodyComp = hasFront && hasSide && hasNumericProfile;
  const bodyCompPromise = canRunBodyComp
    ? Promise.resolve().then(() => analyseBodyCompPhotos(
        frontImage, sideImage, profile,
        poseResults.front?.landmarks || null,
        poseResults.side?.landmarks || null
      ))
    : Promise.resolve(null);

  // Clad se intenta con la primera imagen disponible, frontal o lateral.
  const imageForClad = hasFront ? frontImage : sideImage;
  const canRunClad = Boolean(imageForClad) &&
    Number(profile.height) >= 140 && Number(profile.height) <= 220;
  const cladPromise = canRunClad ? runCladPhotoScan(imageForClad) : Promise.resolve(null);
  const visualPromise = Promise.resolve().then(() => runGeminiPhotoFallback());

  const [bodyCompResult, cladResult, visualResult] = await Promise.allSettled([
    bodyCompPromise, cladPromise, visualPromise
  ]);
  let bodyComp = bodyCompResult.status === "fulfilled" ? bodyCompResult.value : null;
  const clad = cladResult.status === "fulfilled" ? cladResult.value : null;
  const visualText = visualResult.status === "fulfilled" && typeof visualResult.value === "string"
    ? visualResult.value : null;
  if (!bodyComp && bodyCompResult.status === "rejected") console.warn("FORMA BodyComp unavailable:", bodyCompResult.reason);
  if (!clad && cladResult.status === "rejected") console.warn("FORMA Clad unavailable:", cladResult.reason);

  if (!bodyComp && !clad) {
    state.scanResult = visualText ? {
      visualFallback: { text: visualText, imageCount: Number(hasFront) + Number(hasSide) },
      analysisProvider: "Gemini",
      engines: { bodyComp: "unavailable", clad: "unavailable", gemini: "completed" },
      createdAt: new Date().toISOString()
    } : null;
    saveState();
    renderScanResult();
    renderPlan();
    renderDiet();
    $('#capture-status').textContent = visualText
      ? "Gemini analizó las fotografías y describió lo que puede observarse."
      : "Los motores no pudieron completar el análisis. Comprueba la conexión e inténtalo de nuevo.";
    $('#pose-pair-summary').textContent = visualText
      ? "Lectura visual completada con " + (Number(hasFront) + Number(hasSide)) + " fotografía(s)."
      : "No llegó una respuesta utilizable de los servicios de análisis.";
    return;
  }

  let composition = null;
  let measurements = null;
  let appendicularLeanMassKg = null;
  let captureQuality = null;
  if (bodyComp) {
    const output = bodyComp.output;
    const weight = Number(profile.weight);
    const bf = output.composition.bodyfat_pct;
    const alm = output.composition.alm_kg;
    const bodyFatLow = Math.max(0, Math.min(100, bf.low));
    const bodyFatHigh = Math.max(bodyFatLow, Math.min(100, bf.high));
    const fatMassLowKg = Number((weight * bodyFatLow / 100).toFixed(1));
    const fatMassHighKg = Number((weight * bodyFatHigh / 100).toFixed(1));
    composition = {
      source: "BodyComp",
      bodyFatPercent: Number(bf.estimate.toFixed(1)),
      bodyFatLow: Number(bodyFatLow.toFixed(1)),
      bodyFatHigh: Number(bodyFatHigh.toFixed(1)),
      fatMassKg: output.derived.fatMassKg,
      fatMassLowKg,
      fatMassHighKg,
      fatFreeMassKg: output.derived.fatFreeMassKg,
      fatFreeMassLowKg: Number((weight - fatMassHighKg).toFixed(1)),
      fatFreeMassHighKg: Number((weight - fatMassLowKg).toFixed(1)),
      modelMae: bf.mae,
      intervalCoverage: bf.coverage80
    };
    measurements = {};
    for (const key of ["waist", "hip", "chest", "thigh", "bicep"]) {
      const value = Number(output.measurements[key]);
      if (Number.isFinite(value) && value > 0 && value < 250) {
        measurements[key] = { circumferenceCm: value, source: "BodyComp" };
      }
    }
    if (!Number.isFinite(alm?.estimate) || alm.estimate <= 0) {
      appendicularLeanMassKg = null;
    } else {
      appendicularLeanMassKg = Number(alm.estimate.toFixed(1));
    }
    if (!Object.keys(measurements).length) {
      bodyComp = null;
      composition = null;
    }
    captureQuality = bodyComp ? bodyCompResult.value.quality : null;
  }

  if (!bodyComp && !clad) {
    state.scanResult = visualText ? {
      visualFallback: { text: visualText, imageCount: Number(hasFront) + Number(hasSide) },
      analysisProvider: "Gemini",
      engines: { bodyComp: "unavailable", clad: "unavailable", gemini: "completed" },
      createdAt: new Date().toISOString()
    } : null;
    saveState();
    renderScanResult();
    renderPlan();
    renderDiet();
    return;
  }

  const cladMeasurements = clad ? clad.measurements : null;
  if (!measurements && clad) measurements = clad.measurements;
  state.scanResult = {
    measurements: measurements || {},
    composition,
    appendicularLeanMassKg,
    captureQuality,
    analysisProvider: bodyComp ? "BodyComp" : "Clad",
    visualFallback: visualText ? { text: visualText, imageCount: Number(hasFront) + Number(hasSide) } : null,
    cladMeasurements,
    cladHas3dModel: Boolean(clad?.has3dModel),
    crossCheck: compareScanEngines(bodyComp ? measurements : null, cladMeasurements),
    engines: {
      bodyComp: bodyComp ? "completed" : "unavailable",
      clad: clad ? "completed" : (canRunClad ? "unavailable" : "not-used"),
      gemini: visualText ? "completed" : "unavailable"
    },
    createdAt: new Date().toISOString()
  };
  saveState();
  renderScanResult();
  renderPlan();
  renderDiet();
  $('#capture-status').textContent = bodyComp && visualText
    ? "Análisis completado con composición estimada y lectura visual de Gemini."
    : bodyComp
      ? "Composición corporal y medidas estimadas listas. Revisa también las limitaciones de las fotos."
      : visualText
        ? "Se obtuvieron medidas parciales y Gemini completó una lectura visual."
        : "Se han obtenido algunas medidas. La composición de grasa y músculo no pudo estimarse con fiabilidad.";
  $('#pose-pair-summary').textContent = "Análisis realizado con las fotografías disponibles.";
  $('#view-personal-plan')?.classList.remove("hidden");
  toast("Análisis completado.");
}

'''

app = app[:start] + new_scan + app[end:]

# Accept one or two photos and make pose analysis best-effort rather than mandatory.
start_body = app.index("async function startBodyAnalysis() {")
end_body = app.index("\nif (analyzeButton)", start_body)
new_start_body = '''async function startBodyAnalysis() {
  if (scanBusy) return;
  if (state.profile && state.profile.age < 18) {
    toast("El análisis de composición corporal está disponible para adultos.");
    return;
  }
  const availableKinds = VIEW_KEYS.filter(kind => Boolean(capturedUrls[kind]));
  if (!availableKinds.length) {
    toast("Añade al menos una fotografía para analizarla.");
    return;
  }

  scanBusy = true;
  updateScanButton();
  $('#capture-status').textContent = "FORMA está analizando las fotografías disponibles…";
  try {
    let detector = null;
    try {
      detector = await createPoseLandmarker();
    } catch (error) {
      console.warn("FORMA pose detector unavailable; continuing with visual analysis:", error);
    }

    if (detector) {
      for (const kind of availableKinds) {
        const image = $('img', $('#slot-' + kind));
        try {
          await analyzeCapture(kind, image, captureSequence[kind], detector);
        } catch (error) {
          poseResults[kind] = { status: "rejected", reason: error };
          console.warn("FORMA could not extract pose from", kind, error);
        }
      }
    }

    updatePosePairSummary();
    await runBodyScan();
  } catch (error) {
    console.error("FORMA scan orchestration failed:", error);
    const visualFallbackDone = await runGeminiPhotoFallback();
    if (!visualFallbackDone) {
      $('#capture-status').textContent = "No se pudo completar el análisis con la conexión actual. Comprueba Internet e inténtalo de nuevo.";
    }
  } finally {
    scanBusy = false;
    updateScanButton();
  }
}

'''
app = app[:start_body] + new_start_body + app[end_body:]

# Replace result renderer so either engine can provide perimeter estimates.
render_start = app.index("function renderScanResult() {")
render_end = app.index("function updateScanButton()", render_start)
new_render = '''function renderScanResult() {
  const root = $('#scan-result');
  if (!root) return;
  const result = state.scanResult;
  if (!result) {
    root.innerHTML = '<div class="composition-empty"><span class="composition-empty-mark">◌</span><p>Tu análisis aparecerá aquí cuando envíes una fotografía.</p></div>';
    $('#view-personal-plan')?.classList.add("hidden");
    return;
  }

  const visualHtml = result.visualFallback
    ? escapeHTML(result.visualFallback.text || "")
        .replace(/^#{1,3}\\s*(.+)$/gm, '<h4>$1</h4>')
        .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
        .replace(/^[-•]\\s+(.+)$/gm, '<div class="visual-report-line">• $1</div>')
        .replace(/\\r?\\n/g, '<br>')
    : "";
  const hasNumericResult = Boolean(result.composition || Object.keys(result.measurements || {}).length);
  if (result.visualFallback && !hasNumericResult) {
    root.innerHTML =
      '<section class="scan-composition-report visual-only-report">' +
        '<div class="composition-report-top"><span class="composition-brand">FORMA / BODY INSIGHT</span><span class="composition-status">LECTURA VISUAL</span></div>' +
        '<div class="composition-report-heading"><span class="composition-eyebrow">ANÁLISIS DE FOTOGRAFÍA</span><h2>Esto es lo que muestran tus fotos</h2><p>Lectura visual adaptada a las zonas que aparecen en la imagen.</p></div>' +
        '<div class="visual-report-copy">' + visualHtml + '</div>' +
        '<div class="composition-disclaimer"><span>i</span><p>La lectura visual no es una medición. FORMA no inventa perímetros ni kilos de músculo cuando la fotografía no permite calcularlos.</p></div>' +
      '</section>';
    $('#view-personal-plan')?.classList.add("hidden");
    return;
  }

  const m = result.measurements || {};
  const c = result.composition;
  const fatPercent = Number(c?.bodyFatPercent);
  const hasFat = Boolean(c && Number.isFinite(fatPercent));
  const ringPercent = hasFat ? Math.max(0, Math.min(100, fatPercent)) : 0;
  const fat = hasFat ? fmt(fatPercent, 1) + "%" : "No disponible";
  const fatRange = hasFat ? fmt(c.bodyFatLow, 1) + "–" + fmt(c.bodyFatHigh, 1) + "%" : "";
  const fatMass = c && Number.isFinite(Number(c.fatMassKg)) ? fmt(c.fatMassKg, 1) + " kg" : "—";
  const leanMass = c && Number.isFinite(Number(c.fatFreeMassKg)) ? fmt(c.fatFreeMassKg, 1) + " kg" : "—";
  const muscleMass = Number.isFinite(Number(result.appendicularLeanMassKg))
    ? fmt(result.appendicularLeanMassKg, 1) + " kg"
    : "No disponible";
  const source = result.analysisProvider === "Clad" ? "Reconstrucción a partir de fotografía" : "Modelo BodyComp · análisis fotográfico";
  const qualityIssues = [];
  for (const [view, label] of [["front", "Foto 1"], ["side", "Foto 2"]]) {
    for (const issue of (result.captureQuality?.[view]?.issues || []).slice(0, 3)) {
      let message = "El modelo detectó una limitación en esta imagen.";
      if (issue.includes("cut off") || issue.includes("missing your legs") || issue.includes("missing your head")) {
        message = "El cuerpo aparece parcialmente recortado.";
      } else if (issue.includes("arms")) {
        message = "La posición de los brazos dificulta leer la silueta.";
      } else if (issue.includes("lighting") || issue.includes("contrast")) {
        message = "La iluminación o el contraste dificulta separar el contorno.";
      } else if (issue.includes("visible") || issue.includes("detect a person")) {
        message = "No se distinguen con claridad todas las zonas de la silueta.";
      }
      qualityIssues.push('<li><span>' + label + '</span>' + message + '</li>');
    }
  }
  const qualityMarkup = result.captureQuality
    ? '<div class="composition-quality-note"><div class="composition-eyebrow">CALIDAD DE LAS FOTOS</div>' +
      (qualityIssues.length
        ? '<p>El análisis se realizó igualmente, pero estas limitaciones pueden reducir la fiabilidad de las cifras.</p><ul>' + qualityIssues.join("") + '</ul>'
        : '<p>Las imágenes quedaron dentro de los criterios de captura del modelo. Aun así, los resultados siguen siendo estimaciones.</p>') +
      '</div>'
    : "";
  const visualReportMarkup = visualHtml
    ? '<div class="visual-report-copy composition-visual-reading"><div class="composition-eyebrow">LECTURA VISUAL DE GEMINI</div>' + visualHtml + '</div>'
    : "";
  const measurementRows = [
    ["Cintura", m.waist?.circumferenceCm],
    ["Cadera", m.hip?.circumferenceCm],
    ["Pecho / busto", m.chest?.circumferenceCm],
    ["Muslo", m.thigh?.circumferenceCm],
    ["Brazo", m.bicep?.circumferenceCm]
  ].filter(([, value]) => Number.isFinite(Number(value)) && Number(value) > 0);
  const measurementsHtml = measurementRows.length
    ? measurementRows.map(([label, value]) =>
        '<div class="composition-measure-row"><span>' + label + '</span><strong>' + fmt(value, 1) + '<small> cm</small></strong></div>'
      ).join("")
    : '<p class="composition-muted">No se obtuvieron perímetros fiables en esta toma.</p>';

  const compositionVisual = hasFat
    ? '<div class="composition-visual">' +
        '<div class="composition-ring" style="--fat-value:' + ringPercent + '%"><div class="composition-ring-center"><strong>' + fat + '</strong><span>GRASA</span></div></div>' +
        '<div class="composition-legend">' +
          '<div><i class="legend-dot legend-fat"></i><span>Grasa corporal</span><strong>' + fat + '</strong></div>' +
          '<div><i class="legend-dot legend-lean"></i><span>Masa libre de grasa</span><strong>' + (c && Number.isFinite(Number(c.fatFreeMassKg)) ? leanMass : "—") + '</strong></div>' +
        '</div>' +
      '</div>' +
      '<div class="composition-proportion"><div class="composition-proportion-label"><span>Distribución estimada</span><strong>' + fat + ' / ' + fmt(100 - ringPercent, 1) + '%</strong></div><div class="composition-proportion-track"><span class="proportion-fat" style="width:' + ringPercent + '%"></span><span class="proportion-lean" style="width:' + (100 - ringPercent) + '%"></span></div><div class="composition-proportion-legend"><span>Grasa</span><span>Masa libre de grasa</span></div></div>'
    : '<div class="composition-unavailable"><span class="composition-unavailable-icon">◌</span><div><strong>Composición no estimada</strong><p>La foto permitió obtener algunas medidas, pero no hay base suficiente para mostrar un porcentaje de grasa corporal fiable.</p></div></div>';

  root.innerHTML =
    '<section class="scan-composition-report">' +
      '<div class="composition-report-top"><span class="composition-brand">FORMA / BODY INSIGHT</span><span class="composition-status">ANÁLISIS COMPLETADO</span></div>' +
      '<div class="composition-report-heading"><span class="composition-eyebrow">TU INFORME CORPORAL</span><h2>Composición corporal</h2><p>Una lectura de los datos disponibles en tu análisis.</p></div>' +
      '<div class="composition-hero">' +
        '<div class="composition-main-metric"><span>GRASA CORPORAL ESTIMADA</span><strong>' + fat + '</strong><small>' + (hasFat ? "Rango orientativo: " + fatRange : "No calculada por este análisis") + '</small></div>' +
        compositionVisual +
      '</div>' +
      '<div class="composition-section">' +
        '<div class="composition-section-heading"><span>01</span><div><h3>Distribución corporal</h3><p>Estimaciones derivadas del análisis, no mediciones clínicas.</p></div></div>' +
        '<div class="composition-data-row"><span>Masa grasa</span><strong>' + fatMass + '</strong></div>' +
        '<div class="composition-data-row"><span>Masa libre de grasa</span><strong>' + leanMass + '</strong></div>' +
        '<div class="composition-data-row"><span>Masa magra apendicular</span><strong>' + muscleMass + '</strong></div>' +
        '<p class="composition-footnote">La masa magra apendicular no equivale a toda la masa muscular del cuerpo.</p>' +
      '</div>' +
      '<div class="composition-section">' +
        '<div class="composition-section-heading"><span>02</span><div><h3>Medidas corporales</h3><p>Perímetros estimados que el modelo pudo recuperar.</p></div></div>' +
        '<div class="composition-measure-list">' + measurementsHtml + '</div>' +
      '</div>' +
      '<div class="composition-report-footer"><div class="composition-source"><span class="composition-source-dot"></span><span>' + source + '</span></div>' + visualReportMarkup + qualityMarkup + '<div class="composition-disclaimer"><span>i</span><p>Las estimaciones fotográficas pueden variar con el encuadre, la ropa, la postura y la iluminación. Úsalas para observar tendencias, no como sustituto de una medición profesional.</p></div></div>' +
    '</section>';

  if (result.cladMeasurements && result.analysisProvider === "BodyComp") {
    const rows = [["Cintura","waist"],["Cadera","hip"],["Pecho","chest"],["Muslo","thigh"],["Brazo","bicep"]];
    const tableRows = rows.map(([label,key]) => {
      const a = Number(m[key]?.circumferenceCm), b = Number(result.cladMeasurements[key]?.circumferenceCm);
      if (!Number.isFinite(b)) return "";
      return '<div class="composition-measure-row"><span>' + label + '</span><strong>' + (Number.isFinite(a) ? fmt(a,1) + " / " : "") + fmt(b,1) + '<small> cm · Clad</small></strong></div>';
    }).join("");
    root.insertAdjacentHTML("beforeend", '<details class="composition-comparison"><summary>Ver contraste entre sistemas</summary>' + tableRows + '<p>Los sistemas pueden diferir. FORMA conserva sus resultados por separado y no los promedia.</p></details>');
  }
  $('#view-personal-plan')?.classList.remove("hidden");
}

'''
app = app[:render_start] + new_render + app[render_end:]

# The unified scanner privacy notice is inserted by forma-integrate.py.
app += """
/* Accept one or two photos. Keep numeric services optional; always allow visual analysis. */
(() => {
  const scanButton = $('#analyze-body-scan');
  if (!scanButton) return;
  const originalUpdateScanButton = updateScanButton;
  updateScanButton = function () {
    if (typeof originalUpdateScanButton === 'function') originalUpdateScanButton();
    const hasAnyPhoto = Boolean(capturedUrls.front || capturedUrls.side);
    scanButton.disabled = !hasAnyPhoto;
    scanButton.textContent = 'Analizar mis fotos';
  };
  updateScanButton();
})();
"""
app_path.write_text(app, encoding="utf-8")

# Include all new code in syntax checks.
package_path = ROOT / "package.json"
package = package_path.read_text(encoding="utf-8")
if "node --check backend" not in package:
    package = package.replace(
        '"check": "node --check src/app.js',
        '"check": "node --check src/app.js',
        1,
    )
package_path.write_text(package, encoding="utf-8")

worker_path = Path("backend/worker.js")
worker = worker_path.read_text(encoding="utf-8")
if "node --check backend/worker.js" not in package:
    print("Worker syntax will be checked in the GitHub Actions workflow.")

# Keep the Gemini visual fallback readable on narrow Android screens.
css_path = ROOT / "src/ui/styles.css"
css = css_path.read_text(encoding="utf-8")
css += """
.scan-visual-fallback {
  display:block !important;
  grid-column:1 / -1;
  width:100% !important;
  max-width:100%;
  min-width:0;
  box-sizing:border-box;
  padding:16px;
  margin:12px 0;
  border:1px solid var(--line,#dce5eb);
  border-radius:16px;
  background:var(--panel-2,#edf3f6);
  color:var(--text,#172536);
  white-space:normal;
  overflow-wrap:anywhere;
  line-height:1.55;
}
.scan-visual-fallback h3 {
  margin:0 0 12px;
  font-size:17px;
  line-height:1.3;
  color:var(--text,#172536);
}
.scan-visual-fallback-text {
  display:block;
  width:100%;
  min-width:0;
  font-size:14px;
  line-height:1.6;
  overflow-wrap:anywhere;
}
.scan-visual-fallback-text strong { font-weight:750; }
.scan-visual-fallback small {
  display:block;
  margin-top:14px;
  padding-top:12px;
  border-top:1px solid var(--line,#dce5eb);
  color:var(--muted,#5d6d7d);
  font-size:12px;
  line-height:1.5;
}
"""
css_path.write_text(css, encoding="utf-8")


# FORMA visual identity refresh — premium dark, editorial, less box-heavy UI.
css_path = ROOT / "src/ui/styles.css"
css = css_path.read_text(encoding="utf-8")
css += """
:root {
  color-scheme: dark;
  --bg:#0b1114;
  --panel:#121b1f;
  --panel-2:#182428;
  --line:rgba(201,232,218,.13);
  --text:#f1f6f3;
  --muted:#9aada5;
  --green:#b9f2d2;
  --green-2:#78d7a7;
  --mint:rgba(185,242,210,.10);
  --accent:#b9f2d2;
  --shadow:0 18px 44px rgba(0,0,0,.22);
}
html { background:var(--bg); }
body {
  background:
    radial-gradient(ellipse at 85% -12%, rgba(105,190,143,.12), transparent 36%),
    radial-gradient(ellipse at -12% 44%, rgba(88,135,119,.08), transparent 34%),
    var(--bg) !important;
  color:var(--text) !important;
  font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing:.005em;
}
h1,h2,h3,h4 { color:var(--text); letter-spacing:-.035em; }
.sidebar,.topbar,.mobile-nav {
  background:rgba(12,19,22,.94) !important;
  color:var(--text) !important;
  border-color:var(--line) !important;
  backdrop-filter:blur(18px);
}
.brand strong,.mobile-brand { color:var(--text) !important; }
.brand small,.sidebar-label,.eyebrow,.topbar-context,.nav-item,.mobile-nav-item { color:var(--muted) !important; }
.nav-item { border-radius:13px; }
.nav-item:hover,.nav-item.active {
  background:rgba(185,242,210,.10) !important;
  color:var(--green) !important;
}
.nav-item.active { box-shadow:inset 3px 0 var(--green); }
.topbar { border-bottom:1px solid var(--line); }
.local-pill,.avatar { background:var(--mint) !important; color:var(--green) !important; border-color:var(--line) !important; }
.panel,.metric-card,.capture-slot,.capture-panel,.scan-instructions,.summary-tile,.calorie-box,.coach-panel {
  background:linear-gradient(145deg,rgba(24,36,40,.96),rgba(16,25,29,.98)) !important;
  color:var(--text) !important;
  border:1px solid var(--line) !important;
  border-radius:22px !important;
  box-shadow:var(--shadow);
}
.panel { padding:clamp(16px,3vw,26px); }
.metric-card { border-radius:19px !important; }
.metric-top,.metric-foot,.metric-value small,.muted,.muted-text { color:var(--muted) !important; }
.metric-symbol,.history-count,.history-values span,.trend-number { color:var(--green) !important; }
.button-primary,.send-button {
  background:linear-gradient(135deg,#c5f5d9,#82d9ad) !important;
  color:#102018 !important;
  border:0 !important;
  border-radius:999px !important;
  font-weight:750;
  box-shadow:0 8px 24px rgba(120,215,167,.14);
}
.button-primary:hover,.send-button:hover { filter:brightness(1.06); }
.button-secondary,.suggested-prompts button {
  background:rgba(185,242,210,.09) !important;
  border:1px solid rgba(185,242,210,.20) !important;
  color:var(--green) !important;
  border-radius:999px !important;
}
.button-ghost { background:rgba(255,255,255,.035) !important; border-color:var(--line) !important; color:var(--text) !important; border-radius:999px !important; }
.notice-neutral,.capture-status,.privacy-note,.nutrition-reminder,.coach-bubble {
  background:rgba(185,242,210,.08) !important;
  border-color:rgba(185,242,210,.18) !important;
  color:var(--text) !important;
  border-radius:16px;
}
.notice-warning { background:rgba(205,156,81,.10) !important; border-color:rgba(205,156,81,.24) !important; }
.capture-preview { background:#0c1417 !important; border-color:var(--line) !important; border-radius:18px !important; }
.scan-result-card,.summary-tile { background:rgba(255,255,255,.025) !important; border-color:var(--line) !important; }
.scan-result-card strong,.summary-tile strong,.metric-value { color:var(--text) !important; }
.scan-result-card small,.summary-tile small { color:var(--muted) !important; }
.workout-day,.macro-row,.history-row,.coach-header,.chat-input-row { border-color:var(--line) !important; }
.workout-day li,.coach-rule { color:#c1d0c9 !important; }
.user-bubble { background:#b9f2d2 !important; color:#102018 !important; border-radius:18px 18px 4px 18px; }
.coach-bubble { background:#1c292d !important; color:#edf5f0 !important; border-radius:18px 18px 18px 4px; }
.chat-input-row input,input,select,textarea {
  background:#0f191d !important;
  color:var(--text) !important;
  border-color:var(--line) !important;
  border-radius:14px !important;
}
.mobile-nav {
  border-top:1px solid var(--line) !important;
  box-shadow:0 -10px 34px rgba(0,0,0,.28);
}
.mobile-nav-item.active { color:var(--green) !important; }
.mobile-nav-item.active span { background:rgba(185,242,210,.12) !important; border-radius:13px; }
:where(button,input,select,textarea,[tabindex]):focus-visible { outline:3px solid var(--green); outline-offset:3px; }
button:disabled { opacity:.45; }
.scan-privacy-note,.coach-privacy-note {
  background:rgba(185,242,210,.06) !important;
  border-left:3px solid var(--green) !important;
  color:var(--muted) !important;
  border-radius:0 12px 12px 0;
  font-size:12px;
  line-height:1.55;
}
@media(max-width:760px) {
  .content-wrap { padding-top:18px; }
  .panel { border-radius:20px !important; }
  .mobile-nav { padding-top:8px; }
  .mobile-nav-item small { font-size:9px; }
}

/* The body-composition report is editorial and graphic — no grids of square cards. */
#scan-result { width:100%; min-width:0; }
.scan-composition-report {
  width:100%;
  min-width:0;
  box-sizing:border-box;
  overflow:hidden;
  padding:clamp(18px,4vw,30px);
  color:#eef6f1;
  background:
    radial-gradient(circle at 90% 5%, rgba(130,217,173,.13), transparent 30%),
    linear-gradient(150deg,#18272a 0%,#111a1e 62%,#0e171a 100%);
  border:1px solid rgba(185,242,210,.15);
  border-radius:26px;
  box-shadow:0 24px 58px rgba(0,0,0,.28);
}
.composition-report-top {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  flex-wrap:wrap;
  padding-bottom:17px;
  border-bottom:1px solid rgba(221,241,229,.13);
}
.composition-brand {
  font-size:10px;
  font-weight:800;
  letter-spacing:.18em;
  color:#b9f2d2;
}
.composition-status {
  display:inline-flex;
  align-items:center;
  gap:7px;
  padding:6px 10px;
  border:1px solid rgba(185,242,210,.20);
  border-radius:999px;
  color:#b9f2d2;
  background:rgba(185,242,210,.07);
  font-size:9px;
  font-weight:800;
  letter-spacing:.12em;
}
.composition-status:before {
  content:"";
  width:6px;height:6px;border-radius:50%;background:#91e0b4;
  box-shadow:0 0 12px rgba(145,224,180,.65);
}
.composition-report-heading { padding:25px 0 22px; }
.composition-eyebrow {
  color:#91caaa;
  font-size:10px;
  font-weight:800;
  letter-spacing:.2em;
}
.composition-report-heading h2 {
  margin:8px 0 7px;
  font-size:clamp(25px,6vw,34px);
  line-height:1.06;
  font-weight:760;
  color:#f4faf6;
}
.composition-report-heading p {
  margin:0;
  color:#9aada5;
  font-size:13px;
  line-height:1.5;
}
.composition-hero {
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(120px,.9fr);
  align-items:center;
  gap:clamp(14px,4vw,34px);
  padding:21px 0 24px;
  border-top:1px solid rgba(221,241,229,.10);
  border-bottom:1px solid rgba(221,241,229,.10);
}
.composition-main-metric { min-width:0; }
.composition-main-metric>span {
  display:block;
  color:#9eb5a9;
  font-size:9px;
  font-weight:800;
  letter-spacing:.16em;
  line-height:1.45;
}
.composition-main-metric>strong {
  display:block;
  margin:8px 0 6px;
  color:#c5f5d9;
  font-size:clamp(42px,11vw,64px);
  font-weight:760;
  line-height:.98;
  letter-spacing:-.065em;
  font-variant-numeric:tabular-nums;
}
.composition-main-metric>small {
  color:#9aada5;
  font-size:11px;
  line-height:1.4;
}
.composition-visual { display:flex; align-items:center; justify-content:center; gap:16px; min-width:0; }
.composition-ring {
  --fat-value:0%;
  flex:0 0 auto;
  width:clamp(112px,30vw,152px);
  aspect-ratio:1;
  display:grid;
  place-items:center;
  border-radius:50%;
  background:conic-gradient(#9ce3bb var(--fat-value),rgba(223,243,231,.11) 0);
  position:relative;
  box-shadow:0 0 28px rgba(125,218,166,.08);
}
.composition-ring:before {
  content:"";
  position:absolute;
  inset:9px;
  border-radius:50%;
  background:#162327;
  border:1px solid rgba(221,241,229,.12);
}
.composition-ring-center { position:relative; z-index:1; display:grid; gap:2px; text-align:center; }
.composition-ring-center strong { font-size:21px; font-weight:800; color:#f1f8f3; letter-spacing:-.04em; }
.composition-ring-center span { font-size:8px; font-weight:800; letter-spacing:.17em; color:#96b3a2; }
.composition-legend { display:grid; gap:10px; min-width:0; }
.composition-legend>div { display:grid; grid-template-columns:8px minmax(0,1fr); align-items:center; column-gap:7px; row-gap:2px; }
.composition-legend>div strong { grid-column:2; color:#e9f4ed; font-size:12px; font-variant-numeric:tabular-nums; }
.composition-legend>div span { color:#9aada5; font-size:10px; line-height:1.2; }
.legend-dot { width:7px;height:7px;border-radius:50%; }
.legend-fat { background:#9ce3bb; }
.legend-lean { background:#50635a; }
.composition-proportion { padding:18px 0 10px; }
.composition-proportion-label,.composition-proportion-legend {
  display:flex; justify-content:space-between; align-items:center; gap:12px;
}
.composition-proportion-label { margin-bottom:9px; color:#c5d6cc; font-size:11px; }
.composition-proportion-label strong { color:#f0f7f2; font-variant-numeric:tabular-nums; }
.composition-proportion-track { width:100%; height:10px; display:flex; overflow:hidden; border-radius:999px; background:rgba(255,255,255,.08); }
.proportion-fat { background:linear-gradient(90deg,#9ce3bb,#c0f3d2); }
.proportion-lean { background:#4d6258; }
.composition-proportion-legend { margin-top:7px; color:#83978d; font-size:9px; }
.composition-section { padding:23px 0 4px; border-bottom:1px solid rgba(221,241,229,.10); }
.composition-section-heading { display:flex; align-items:flex-start; gap:13px; margin-bottom:13px; }
.composition-section-heading>span { color:#8bd5aa; font-size:11px; font-weight:850; letter-spacing:.1em; padding-top:4px; }
.composition-section-heading h3 { margin:0; color:#f0f7f2; font-size:17px; letter-spacing:-.03em; }
.composition-section-heading p { margin:4px 0 0; color:#8fa49a; font-size:11px; line-height:1.4; }
.composition-data-row,.composition-measure-row {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  min-height:43px;
  border-bottom:1px solid rgba(221,241,229,.075);
}
.composition-data-row:last-of-type,.composition-measure-row:last-child { border-bottom:0; }
.composition-data-row>span,.composition-measure-row>span { color:#bccdc3; font-size:12px; }
.composition-data-row>strong,.composition-measure-row>strong {
  color:#f2f8f4;
  font-size:14px;
  font-weight:750;
  text-align:right;
  font-variant-numeric:tabular-nums;
}
.composition-measure-row>strong small { color:#91a79a; font-size:10px; font-weight:600; }
.composition-footnote { margin:8px 0 12px; color:#81958b; font-size:10px; line-height:1.5; }
.composition-muted { color:#9aada5; font-size:12px; padding:10px 0; }
.composition-unavailable {
  display:flex; align-items:center; gap:14px;
  padding:18px 0;
  border-top:1px solid rgba(221,241,229,.10);
  border-bottom:1px solid rgba(221,241,229,.10);
}
.composition-unavailable-icon { color:#9ce3bb; font-size:32px; }
.composition-unavailable strong { display:block; color:#f0f7f2; font-size:14px; }
.composition-unavailable p { margin:4px 0 0; color:#97aaa0; font-size:11px; line-height:1.5; }
.composition-report-footer { padding-top:17px; }
.composition-source { display:flex; align-items:center; gap:8px; color:#9ab0a3; font-size:10px; }
.composition-source-dot { width:6px;height:6px;border-radius:50%;background:#9ce3bb; }
.composition-disclaimer {
  display:flex; align-items:flex-start; gap:10px;
  margin-top:15px; padding:12px 13px;
  border-radius:12px;
  background:rgba(255,255,255,.035);
  border:1px solid rgba(221,241,229,.08);
}
.composition-disclaimer>span { flex:0 0 18px; height:18px; display:grid; place-items:center; border-radius:50%; background:rgba(185,242,210,.12); color:#b9f2d2; font-size:11px; font-weight:800; }
.composition-disclaimer p { margin:0; color:#96a99f; font-size:10px; line-height:1.55; }
.composition-comparison { margin-top:15px; color:#d7e6dc; border-top:1px solid rgba(221,241,229,.12); padding-top:13px; }
.composition-comparison summary { color:#b9f2d2; font-size:11px; font-weight:750; cursor:pointer; }
.composition-comparison>p { color:#91a49a; font-size:10px; line-height:1.5; }
.visual-only-report .composition-report-heading { padding-bottom:17px; }
.visual-report-copy {
  color:#dce9e1;
  font-size:13px;
  line-height:1.75;
  overflow-wrap:anywhere;
  word-break:normal;
  padding:16px 0 5px;
}
.visual-report-copy h4 {
  margin:13px 0 4px;
  color:#b9f2d2;
  font-size:11px;
  font-weight:850;
  letter-spacing:.12em;
}
.visual-report-copy strong { color:#f3faf5; font-weight:800; }
.visual-report-line { margin:4px 0; }
.composition-empty {
  padding:28px 18px;
  text-align:center;
  color:#9aada5;
  border:1px dashed rgba(185,242,210,.20);
  border-radius:18px;
  background:rgba(185,242,210,.035);
}
.composition-empty-mark { display:block; color:#a8e8c2; font-size:33px; margin-bottom:8px; }
.composition-empty p { margin:0; font-size:12px; line-height:1.5; }
@media(max-width:420px) {
  .scan-composition-report { padding:17px 15px; border-radius:21px; }
  .composition-hero { grid-template-columns:minmax(0,1fr); gap:17px; }
  .composition-main-metric>strong { font-size:54px; }
  .composition-visual { justify-content:flex-start; }
  .composition-ring { width:122px; }
  .composition-legend { flex:1; }
}
"""
css_path.write_text(css, encoding="utf-8")

print("Clad front-end orchestration and comparison UI integrated.")
