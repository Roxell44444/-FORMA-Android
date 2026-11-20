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
anchor = '              <p class="scan-privacy-note">Al iniciar el análisis, tus fotografías podrán procesarse de forma segura para completar las mediciones y ofrecer orientación si el análisis principal no está disponible.</p>'
consent = ''
if "id=\"clad-scan-consent\"" not in html:
    html = once(html, anchor, consent + anchor, "Clad consent insertion")
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
  if (!result.waist || !result.hip || !result.chest) {
    throw new Error("Clad no devolvió las medidas principales necesarias.");
  }
  return result;
}

async function runCladPhotoScan() {
  // La reconstrucción se inicia automáticamente como parte del análisis.
  const heightCm = Number(state.profile?.height);
  if (!Number.isFinite(heightCm) || heightCm < 140 || heightCm > 220) {
    throw new Error("La reconstrucción admite estaturas entre 140 y 220 cm.");
  }
  const frontImage = await imageToCompactDataUrl($('img', $('#slot-front')));
  const job = await startCladPhotoJob({ frontImage, heightCm });
  if (!job.jobId || !job.pollUrl) throw new Error("No se pudo iniciar la reconstrucción 3D.");
  const startedAt = Date.now();
  let lastStatus = "queued";
  while (Date.now() - startedAt < 300000) {
    const result = await pollCladPhotoJob({ jobId: job.jobId, pollUrl: job.pollUrl });
    lastStatus = result.status || lastStatus;
    if (result.status === "completed") {
      return {
        measurements: cladMeasurementsFromResult(result),
        has3dModel: result.has3dModel === true
      };
    }
    if (result.status === "failed") throw new Error(result.error || "No se pudo completar la reconstrucción 3D.");
    $('#capture-status').textContent = "BodyComp está analizando tus fotos. Se está reconstruyendo el modelo 3D…";
    await new Promise(resolve => setTimeout(resolve, 2200));
  }
  throw new Error("La reconstrucción 3D de Clad superó el tiempo de espera.");
}

function compareScanEngines(bodyCompMeasurements, cladMeasurements) {
  if (!bodyCompMeasurements || !cladMeasurements) return null;
  const output = {};
  for (const key of ["waist", "hip", "chest", "thigh", "bicep"]) {
    const a = Number(bodyCompMeasurements[key]?.circumferenceCm);
    const b = Number(cladMeasurements[key]?.circumferenceCm);
    if (Number.isFinite(a) && Number.isFinite(b)) {
      output[key] = Number(Math.abs(a - b).toFixed(1));
    }
  }
  return output;
}

async function runBodyScan() {
  if (state.profile && state.profile.age < 18) return;
  if (!poseResults.front || !poseResults.side || !capturedUrls.front || !capturedUrls.side) return;
  if (poseResults.front.status === 'rejected' || poseResults.side.status === 'rejected') return;
  if (!state.profile?.height) {
    $('#capture-status').textContent = 'Completa tu estatura en Datos para terminar el análisis.';
    return;
  }
  if (poseResults.front.orientation !== 'front-likely' || poseResults.side.orientation !== 'side-likely') {
    $('#pose-pair-summary').textContent = 'Las fotos no muestran claramente una vista frontal y otra de perfil. Repite las que sean necesarias.';
    $('#capture-status').textContent = 'No pudimos confirmar el ángulo de las fotos.';
    return;
  }

  const bodyCompPromise = analyseBodyCompPhotos(
    $('img', $('#slot-front')), $('img', $('#slot-side')), state.profile,
    poseResults.front.landmarks, poseResults.side.landmarks
  );
  const cladEnabled = true;
  const cladPromise = cladEnabled ? runCladPhotoScan() : Promise.resolve(null);
  $('#capture-status').textContent = cladEnabled
    ? 'Estamos analizando tus fotos y preparando la reconstrucción 3D…'
    : 'Estamos analizando tus fotos…';

  const [bodyCompResult, cladResult] = await Promise.allSettled([bodyCompPromise, cladPromise]);
  const bodyCompOk = bodyCompResult.status === 'fulfilled';
  const cladOk = cladResult.status === 'fulfilled' && Boolean(cladResult.value);
  const bodyComp = bodyCompOk ? bodyCompResult.value : null;
  const clad = cladOk ? cladResult.value : null;

  if (!bodyCompOk) console.warn('FORMA BodyComp unavailable:', bodyCompResult.reason);
  if (cladEnabled && !cladOk) console.warn('FORMA Clad unavailable:', cladResult.reason);

  if (!bodyComp && !clad) {
    state.scanResult = null;
    saveState();
    const usedVisualFallback = await runGeminiPhotoFallback();
    if (!usedVisualFallback) {
      const cladProblem = cladEnabled ? ' Clad tampoco pudo completar la reconstrucción.' : '';
      $('#capture-status').textContent = ($('#scan-fallback-consent')?.checked)
        ? 'No pudimos completar los análisis ni conectar con el respaldo visual. Revisa las fotos e inténtalo de nuevo.'
        : 'No pudimos completar el análisis.' + cladProblem + ' Repite las fotos o autoriza el respaldo visual cualitativo.';
      $('#pose-pair-summary').textContent = 'Prueba con buena iluminación, ropa ajustada, brazos separados y el cuerpo completo.';
      renderScanResult();
      renderPlan();
      renderDiet();
    }
    return;
  }

  let composition = null;
  let measurements = null;
  let appendicularLeanMassKg = null;
  let captureQuality = null;
  if (bodyComp) {
    const output = bodyComp.output;
    const weight = Number(state.profile.weight);
    const bf = output.composition.bodyfat_pct;
    const alm = output.composition.alm_kg;
    const bodyFatLow = Math.max(0, Math.min(100, bf.low));
    const bodyFatHigh = Math.max(bodyFatLow, Math.min(100, bf.high));
    const fatMassLowKg = Number((weight * bodyFatLow / 100).toFixed(1));
    const fatMassHighKg = Number((weight * bodyFatHigh / 100).toFixed(1));
    composition = {
      source: 'BodyComp',
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
    for (const key of ['waist', 'hip', 'chest', 'thigh', 'bicep']) {
      const value = Number(output.measurements[key]);
      if (!Number.isFinite(value) || value <= 0 || value > 250) {
        measurements = null;
        break;
      }
      measurements[key] = { circumferenceCm: value, source: 'BodyComp' };
    }
    if (!measurements) {
      state.scanResult = null;
      saveState();
      const usedVisualFallback = await runGeminiPhotoFallback();
      if (!usedVisualFallback) {
        $('#capture-status').textContent = 'El resultado de BodyComp no superó las comprobaciones de coherencia. Repite las fotos.';
        renderScanResult();
      }
      return;
    }
    appendicularLeanMassKg = Number.isFinite(alm?.estimate) && alm.estimate > 0 ? alm.estimate : null;
    captureQuality = bodyComp.quality;
  } else if (clad) {
    measurements = clad.measurements;
  }

  const cladMeasurements = clad ? clad.measurements : null;
  const crossCheck = compareScanEngines(bodyComp ? measurements : null, cladMeasurements);
  state.scanResult = {
    measurements,
    composition,
    appendicularLeanMassKg,
    captureQuality,
    analysisProvider: bodyComp ? 'BodyComp' : 'Clad',
    cladMeasurements,
    cladHas3dModel: Boolean(clad?.has3dModel),
    crossCheck,
    engines: {
      bodyComp: bodyComp ? 'completed' : 'unavailable',
      clad: clad ? 'completed' : (cladEnabled ? 'unavailable' : 'not-authorized')
    },
    createdAt: new Date().toISOString()
  };
  saveState();
  renderScanResult();
  renderPlan();
  renderDiet();
  $('#capture-status').textContent = bodyComp && clad
    ? 'Análisis completado. Las medidas de los dos sistemas se muestran por separado.'
    : bodyComp
      ? (cladEnabled ? 'El análisis corporal está listo. La reconstrucción 3D no estuvo disponible.' : 'Análisis corporal completado.')
      : 'La reconstrucción 3D y las medidas están listas. La composición corporal no está disponible en este resultado.';
  $('#pose-pair-summary').textContent = 'Tus fotos se procesaron según los servicios autorizados.';
  $('#view-personal-plan')?.classList.remove('hidden');
  toast('Análisis completado. Tu plan está preparado.');
}

'''
app = app[:start] + new_scan + app[end:]

# Replace result renderer so either engine can provide perimeter estimates.
render_start = app.index("function renderScanResult() {")
render_end = app.index("function updateScanButton()", render_start)
new_render = '''function renderScanResult() {
  const root = $('#scan-result');
  if (!root) return;
  const result = state.scanResult;
  if (result?.visualFallback) {
    root.innerHTML = '<div class="notice notice-neutral"><strong>Orientación visual aproximada</strong><p>' +
      escapeHTML(result.visualFallback.text) +
      '</p><small>No es una medición. No se calcularon porcentajes de grasa, músculo ni perímetros.</small></div>';
    $('#view-personal-plan')?.classList.add('hidden');
    return;
  }
  if (!result?.measurements) {
    root.innerHTML = '<p class="muted">Tu resultado aparecerá aquí después del análisis.</p>';
    $('#view-personal-plan')?.classList.add('hidden');
    return;
  }
  const m = result.measurements, c = result.composition;
  const fat = c ? (c.bodyFatPercent === null ? fmt(c.bodyFatLow,1) + '–' + fmt(c.bodyFatHigh,1) + '%' : '≈ ' + fmt(c.bodyFatPercent,1) + '%') : 'No disponible';
  const fatMass = c ? (Number.isFinite(c.fatMassKg) ? fmt(c.fatMassKg,1) + ' kg' : fmt(c.fatMassLowKg,1) + '–' + fmt(c.fatMassHighKg,1) + ' kg') : '—';
  const leanMass = c ? (Number.isFinite(c.fatFreeMassKg) ? fmt(c.fatFreeMassKg,1) + ' kg' : fmt(c.fatFreeMassLowKg,1) + '–' + fmt(c.fatFreeMassHighKg,1) + ' kg') : '—';
  const circumferenceSource = result.analysisProvider === 'Clad' ? 'Clad · modelo 3D' : 'BodyComp · análisis fotográfico';
  root.innerHTML =
    '<div class="scan-result-grid">' +
    '<article class="scan-result-card featured"><small>GRASA CORPORAL ESTIMADA</small><strong>' + fat + '</strong><span>' + (c ? 'Estimación orientativa de BodyComp' : 'No estimada por Clad') + '</span></article>' +
    '<article class="scan-result-card"><small>MASA GRASA</small><strong>' + fatMass + '</strong></article>' +
    '<article class="scan-result-card"><small>MASA LIBRE DE GRASA</small><strong>' + leanMass + '</strong></article>' +
    '<article class="scan-result-card"><small>CINTURA ESTIMADA</small><strong>' + fmt(m.waist?.circumferenceCm,1) + ' cm</strong></article>' +
    '<article class="scan-result-card"><small>PECHO / BUSTO ESTIMADO</small><strong>' + fmt(m.chest?.circumferenceCm,1) + ' cm</strong></article>' +
    '<article class="scan-result-card"><small>CADERA ESTIMADA</small><strong>' + fmt(m.hip?.circumferenceCm,1) + ' cm</strong></article>' +
    '<article class="scan-result-card"><small>MASA MAGRA APENDICULAR</small><strong>' + (Number.isFinite(result.appendicularLeanMassKg) ? fmt(result.appendicularLeanMassKg,1) + ' kg' : 'No estimada') + '</strong><span>No equivale a toda la masa muscular.</span></article>' +
    '</div><p class="scan-result-note">' + circumferenceSource + '. Las medidas fotográficas son aproximadas; no se promediaron resultados de modelos distintos.</p>';

  if (result.cladMeasurements) {
    const rows = [
      ['Cintura', 'waist'],
      ['Cadera', 'hip'],
      ['Pecho', 'chest'],
      ['Muslo', 'thigh'],
      ['Brazo', 'bicep']
    ];
    const content = rows.map(([label, key]) => {
      const bodyCompValue = Number(m[key]?.circumferenceCm);
      const cladValue = Number(result.cladMeasurements[key]?.circumferenceCm);
      const difference = Number(result.crossCheck?.[key]);
      if (!Number.isFinite(cladValue)) return '';
      return '<tr><td>' + label + '</td><td>' + (Number.isFinite(bodyCompValue) ? fmt(bodyCompValue,1) + ' cm' : '—') +
        '</td><td>' + fmt(cladValue,1) + ' cm</td><td>' + (Number.isFinite(difference) ? fmt(difference,1) + ' cm' : '—') + '</td></tr>';
    }).join('');
    root.insertAdjacentHTML('beforeend',
      '<details class="scan-result-note"><summary>Comparar las medidas de los dos análisis</summary>' +
      '<table><thead><tr><th>Medida</th><th>BodyComp</th><th>Clad</th><th>Diferencia</th></tr></thead><tbody>' + content + '</tbody></table>' +
      '<p>Son estimaciones de dos sistemas diferentes, no dos mediciones clínicas. FORMA no las promedia. La reconstrucción 3D ' +
      (result.cladHas3dModel ? 'devolvió un modelo 3D.' : 'no devolvió un archivo 3D.') + '</p></details>');
  }
  $('#view-personal-plan')?.classList.remove('hidden');
}

'''
app = app[:render_start] + new_render + app[render_end:]

# Add Clad consent style if the original style step wasn't rerun.
if "clad-scan-consent" not in html:
    raise SystemExit("Clad consent did not persist in index.html.")
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
print("Clad front-end orchestration and comparison UI integrated.")
