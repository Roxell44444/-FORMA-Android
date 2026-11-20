from pathlib import Path
import re

ROOT = Path("FORMA-1.1.0")
def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)

index_path = ROOT / "index.html"
html = index_path.read_text(encoding="utf-8")
html, n = re.subn(r'<label class="guardian-row hidden" id="guardian-consent-row">.*?</label>', '', html, count=1, flags=re.S)
if n != 1: raise SystemExit("Guardian checkbox not found.")
html, n = re.subn(r'<article class="panel form-panel hidden" id="pediatric-rfm-panel">.*?</article>', '', html, count=1, flags=re.S)
if n != 1: raise SystemExit("Pediatric body measurement panel not found.")
scan_button = '              <button class="button button-primary full-width analyze-button" id="analyze-body-scan" disabled>Analizar mi físico</button>'
scan_consent = '''              <label class="external-consent"><input type="checkbox" id="scan-fallback-consent" /><span><strong>Permitir un análisis visual de respaldo</strong><small>Solo si el análisis principal falla, se enviarán estas dos fotos a Google Gemini para recibir observaciones cualitativas. No generará porcentajes ni medidas. En el nivel gratuito, Google puede usar el contenido enviado para mejorar sus productos.</small></span></label>
'''
html = once(html, scan_button, scan_consent + scan_button, "scanner consent")
coach_form = '<form id="chat-form" class="chat-input-row">'
coach_consent = '''<label class="external-consent coach-consent"><input type="checkbox" id="gemini-coach-consent" /><span><strong>Usar respuestas inteligentes personalizadas</strong><small>Con tu permiso, se enviará tu pregunta y un resumen de tu perfil y progreso a Gemini. No se enviarán fotos. El nivel gratuito de Google puede utilizar el contenido enviado para mejorar sus productos.</small></span></label>'''
html = once(html, coach_form, coach_consent + coach_form, "coach consent")
index_path.write_text(html, encoding="utf-8")

css_path = ROOT / "src/ui/styles.css"
css = css_path.read_text(encoding="utf-8")
css += '''

.external-consent { display:flex; align-items:flex-start; gap:10px; margin:12px 0; padding:13px 14px; border:1px solid var(--border, rgba(255,255,255,.14)); border-radius:14px; background:var(--surface, rgba(255,255,255,.035)); color:inherit; font-size:13px; line-height:1.45; }
.external-consent input { flex:0 0 auto; width:18px; height:18px; margin:2px 0 0; accent-color:var(--accent, #c8ff42); }
.external-consent span { display:grid; gap:4px; }
.external-consent strong { font-size:13px; }
.external-consent small { opacity:.76; font-size:11px; line-height:1.45; }
.coach-consent { margin:14px 0; }
'''
css_path.write_text(css, encoding="utf-8")

app_path = ROOT / "src/app.js"
app = app_path.read_text(encoding="utf-8")
app = once(app, "import { estimateTwoViewAnthropometry } from './scanner/anthropometry.js';\n", "import { analyseBodyCompPhotos } from './scanner/bodycomp.js';\nimport { askFormaCoach, askFormaVisualFallback } from './core/remote.js';\n", "scanner/AI imports")
old_minor = '''  if (profile.age < 18) {
    if (profile.guardianConfirmed !== true) return null;
    const estimate = estimatePediatricBodyFatRFM({ age: profile.age, equation: profile.equation, heightCm: profile.height, waistCm: profile.waist, measureMethod: profile.measureMethod });
    return estimate ? { percent: estimate.percent, low: estimate.percent, high: estimate.percent, count: 1, methods: [{ name: estimate.method, value: estimate.percent }], spreadIsConfidenceInterval: false, confidenceLabel: estimate.note, pediatric: true, studyRmsePercentagePoints: estimate.studyRmsePercentagePoints } : null;
  }'''
app = once(app, old_minor, "  if (profile.age < 18) return null;", "minor body fat restriction")
app = once(app, "  const guardianRow = $('#guardian-consent-row');\n  guardianRow.classList.toggle('hidden', !minor);\n  guardianRow.querySelector('input').required = minor;\n", "", "guardian UI logic")
app = once(app, "  const pediatricTapeEnabled = age >= 8 && age < 18;\n  $('#pediatric-rfm-panel').classList.toggle('hidden', !pediatricTapeEnabled);\n  setFieldsDisabled($('#pediatric-rfm-panel'), !pediatricTapeEnabled);\n", "  const pediatricTapeEnabled = false;\n", "pediatric tape restrictions")
app = once(app, "guardianConfirmed: isMinor ? form.get('guardianConfirmed') === 'on' : false,", "guardianConfirmed: false,", "guardian profile field")
app = once(app, "  if (isMinor && !profile.guardianConfirmed) {\n    $('#form-message').textContent = 'Para guardar un perfil menor de 18 años, un padre, madre o tutor debe confirmar la supervisión.';\n    return;\n  }\n", "", "guardian submit validation")

scan_start = app.index("function runBodyScan() {")
scan_end = app.index("async function analyzeCapture", scan_start)
new_scan = '''async function imageToCompactDataUrl(image) {
  if (!image.complete || !image.naturalWidth || !image.naturalHeight) await image.decode();
  const scale = Math.min(1, 1100 / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext('2d');
  if (!context) throw new Error('No se pudo preparar la fotografía.');
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.78);
}

async function runGeminiPhotoFallback() {
  if (!$('#scan-fallback-consent')?.checked) return false;
  try {
    const [frontImage, sideImage] = await Promise.all([
      imageToCompactDataUrl($('img', $('#slot-front'))),
      imageToCompactDataUrl($('img', $('#slot-side')))
    ]);
    const text = await askFormaVisualFallback({ frontImage, sideImage });
    state.scanResult = { visualFallback: { text }, createdAt: new Date().toISOString() };
    saveState();
    renderScanResult();
    renderPlan();
    renderDiet();
    $('#capture-status').textContent = 'Gemini ofrece una orientación visual aproximada. No se generaron medidas ni porcentajes corporales.';
    $('#pose-pair-summary').textContent = 'Para obtener medidas, mejora las fotos y vuelve a intentarlo.';
    toast('Orientación visual completada. No es una medición corporal.');
    return true;
  } catch (error) {
    console.warn('FORMA visual fallback unavailable:', error);
    return false;
  }
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
  try {
    const result = await analyseBodyCompPhotos(
      $('img', $('#slot-front')), $('img', $('#slot-side')), state.profile,
      poseResults.front.landmarks, poseResults.side.landmarks
    );
    const output = result.output;
    const weight = Number(state.profile.weight);
    const bf = output.composition.bodyfat_pct;
    const alm = output.composition.alm_kg;
    const bodyFatLow = Math.max(0, Math.min(100, bf.low));
    const bodyFatHigh = Math.max(bodyFatLow, Math.min(100, bf.high));
    const fatMassLowKg = Number((weight * bodyFatLow / 100).toFixed(1));
    const fatMassHighKg = Number((weight * bodyFatHigh / 100).toFixed(1));
    const composition = {
      source: 'BodyComp',
      bodyFatPercent: Number(bf.estimate.toFixed(1)),
      bodyFatLow: Number(bodyFatLow.toFixed(1)),
      bodyFatHigh: Number(bodyFatHigh.toFixed(1)),
      fatMassKg: output.derived.fatMassKg,
      fatMassLowKg, fatMassHighKg,
      fatFreeMassKg: output.derived.fatFreeMassKg,
      fatFreeMassLowKg: Number((weight - fatMassHighKg).toFixed(1)),
      fatFreeMassHighKg: Number((weight - fatMassLowKg).toFixed(1)),
      modelMae: bf.mae, intervalCoverage: bf.coverage80
    };
    const measurements = {};
    for (const key of ['waist', 'hip', 'chest', 'thigh', 'bicep']) {
      const value = Number(output.measurements[key]);
      if (!Number.isFinite(value) || value <= 0 || value > 250) throw new Error('Una de las medidas estimadas no superó la comprobación de coherencia.');
      measurements[key] = { circumferenceCm: value, source: 'BodyComp' };
    }
    if (!Number.isFinite(alm?.estimate) || alm.estimate <= 0) throw new Error('La estimación de masa magra apendicular no superó la comprobación de coherencia.');
    state.scanResult = {
      measurements, composition, appendicularLeanMassKg: alm.estimate,
      captureQuality: result.quality, analysisProvider: 'BodyComp',
      createdAt: new Date().toISOString()
    };
    saveState();
    renderScanResult();
    renderPlan();
    renderDiet();
    $('#capture-status').textContent = 'Análisis completado. Tus resultados y recomendaciones están listos.';
    $('#pose-pair-summary').textContent = 'Tus fotos superaron las comprobaciones del análisis.';
    $('#view-personal-plan')?.classList.remove('hidden');
    toast('Análisis completado. Tu plan está preparado.');
  } catch (error) {
    console.warn('FORMA BodyComp analysis unavailable:', error);
    state.scanResult = null;
    saveState();
    const usedVisualFallback = await runGeminiPhotoFallback();
    if (!usedVisualFallback) {
      $('#capture-status').textContent = $('#scan-fallback-consent')?.checked
        ? 'No pudimos completar el análisis ni conectar con el respaldo visual. Revisa las fotos e inténtalo de nuevo.'
        : 'No pudimos completar el análisis. Repite las fotos o autoriza el respaldo visual para recibir solo observaciones cualitativas.';
      $('#pose-pair-summary').textContent = 'Prueba con buena iluminación, ropa ajustada, brazos separados y el cuerpo completo.';
      renderScanResult();
      renderPlan();
      renderDiet();
    }
  }
}

'''
app = app[:scan_start] + new_scan + app[scan_end:]
app = once(app, "    runBodyScan();", "    await runBodyScan();", "await BodyComp scan")
app = once(app, "    console.error('FORMA vision initialization error:', error);\n    VIEW_KEYS.forEach(kind => {", "    console.error('FORMA vision initialization error:', error);\n    const visualFallbackDone = await runGeminiPhotoFallback();\n    if (visualFallbackDone) return;\n    VIEW_KEYS.forEach(kind => {", "pose failure fallback")

app = once(
    app,
    '''  const result = state.scanResult;
  if (!result?.measurements) { root.innerHTML = '<p class="muted">Tu resultado aparecerá aquí después del análisis.</p>'; $('#view-personal-plan')?.classList.add('hidden'); return; }
  const m = result.measurements, c = result.composition;''',
    '''  const result = state.scanResult;
  if (result?.visualFallback) {
    root.innerHTML = '<div class="notice notice-neutral"><strong>Orientación visual aproximada</strong><p>' +
      escapeHTML(result.visualFallback.text) +
      '</p><small>No es una medición. No se calcularon porcentajes de grasa, músculo ni perímetros.</small></div>';
    $('#view-personal-plan')?.classList.add('hidden');
    return;
  }
  if (!result?.measurements) { root.innerHTML = '<p class="muted">Tu resultado aparecerá aquí después del análisis.</p>'; $('#view-personal-plan')?.classList.add('hidden'); return; }
  const m = result.measurements, c = result.composition;''',
    "visual fallback display",
)

old_grid = '<article class="scan-result-card"><small>CADERA ESTIMADA</small><strong>${fmt(m.hip.circumferenceCm,1)} cm</strong></article></div>'
new_grid = '<article class="scan-result-card"><small>CADERA ESTIMADA</small><strong>${fmt(m.hip.circumferenceCm,1)} cm</strong></article><article class="scan-result-card"><small>MASA MAGRA APENDICULAR</small><strong>${fmt(result.appendicularLeanMassKg,1)} kg</strong><span>No equivale a toda la masa muscular.</span></article></div>'
app = once(app, old_grid, new_grid, "appendicular lean mass tile")

app = once(
    app,
    "  const maintenance = energy?.maintenance || null;\n  const labelGoal = { fatloss:'Pérdida de grasa', muscle:'Fuerza y músculo', recomp:'Composición y hábitos', maintain:'Mantenimiento' }[p.goal];",
    """  const scanComposition = state.scanResult?.analysisProvider === 'BodyComp' ? state.scanResult.composition : null;
  const scanLeanMassKg = Number(scanComposition?.fatFreeMassKg);
  const leanMaintenance = safe && Number.isFinite(scanLeanMassKg) && scanLeanMassKg > 0
    ? (() => { const value = (370 + 21.6 * scanLeanMassKg) * Number(p.activity || 1.2); return { low: Math.round(value * 0.94), high: Math.round(value * 1.06) }; })()
    : null;
  const maintenance = leanMaintenance || energy?.maintenance || null;
  const labelGoal = { fatloss:'Pérdida de grasa', muscle:'Fuerza y músculo', recomp:'Composición y hábitos', maintain:'Mantenimiento' }[p.goal];""",
    "composition-aware plan",
)
app = once(
    app,
    """  const fatDetails = profileBodyFatDetails(p);
  const circumferenceEstimate = fatDetails?.percent ?? null;
  const composition = safe && circumferenceEstimate !== null ? calculateCompositionEstimate({weightKg:p.weight, bodyFatPercent:circumferenceEstimate, heightCm:p.height}) : null;
  const muscleEstimate = safe ? profileAppendicularMuscle(p) : null;""",
    """  const fatDetails = profileBodyFatDetails(p);
  const circumferenceEstimate = scanComposition?.bodyFatPercent ?? fatDetails?.percent ?? null;
  const composition = scanComposition
    ? { fatMassKg: scanComposition.fatMassKg, fatFreeMassKg: scanComposition.fatFreeMassKg }
    : safe && circumferenceEstimate !== null
      ? calculateCompositionEstimate({weightKg:p.weight, bodyFatPercent:circumferenceEstimate, heightCm:p.height})
      : null;
  const muscleEstimate = state.scanResult?.analysisProvider === 'BodyComp' && Number.isFinite(state.scanResult.appendicularLeanMassKg)
    ? { kg: state.scanResult.appendicularLeanMassKg, bodyComp: true }
    : safe ? profileAppendicularMuscle(p) : null;""",
    "BodyComp plan metrics",
)
app = once(app, "GRASA CORPORAL · ESTIMACIÓN HÍBRIDA", "GRASA CORPORAL · ESTIMACIÓN", "simplify body fat label")
app = once(app, '<small>MÚSCULO ESQUELÉTICO APENDICULAR</small>', '<small>${muscleEstimate?.bodyComp ? "MASA MAGRA APENDICULAR" : "MÚSCULO ESQUELÉTICO APENDICULAR"}</small>', "muscle label")
app = once(app, "Cifra orientativa basada en medidas corporales.", "${muscleEstimate?.bodyComp ? 'Estimación de masa magra apendicular; no representa todo el músculo.' : 'Cifra orientativa basada en medidas corporales.'}", "muscle description")
app = once(app, "Perfil menor de 18 años · tutor confirmado", "Perfil menor de 18 años · bienestar y crecimiento", "minor plan label")

app = once(
    app,
    """  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
}

$('#chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const field = event.currentTarget.elements.message;
  const message = String(field.value || '').trim();
  if (!message) return;
  addMessage(message, 'user');
  field.value = '';
  addMessage(coachReply(message), 'coach');
});

$$('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  const message = button.dataset.prompt;
  addMessage(message, 'user');
  addMessage(coachReply(message), 'coach');
}));""",
    """  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
  return node;
}

function coachContextForGemini() {
  const p = state.profile;
  const scan = state.scanResult?.analysisProvider === 'BodyComp' ? state.scanResult : null;
  return {
    profile: p ? {
      age: p.age, heightCm: p.height, weightKg: p.weight,
      goal: p.goal, activity: p.activity, experience: p.experience,
      sessionsPerWeek: p.sessions, equipment: p.equipment, foodPreferences: p.diet
    } : null,
    latestScan: scan ? {
      bodyFatPercent: scan.composition.bodyFatPercent,
      bodyFatInterval: [scan.composition.bodyFatLow, scan.composition.bodyFatHigh],
      fatFreeMassKg: scan.composition.fatFreeMassKg,
      appendicularLeanMassKg: scan.appendicularLeanMassKg,
      waistCm: scan.measurements.waist.circumferenceCm,
      chestCm: scan.measurements.chest.circumferenceCm,
      hipCm: scan.measurements.hip.circumferenceCm,
      date: scan.createdAt
    } : null,
    progress: {
      completedWorkouts: state.completedWorkouts?.length || 0,
      exerciseEntries: state.exerciseEntries?.length || 0,
      foodEntries: state.foodEntries?.length || 0
    }
  };
}

async function sendCoachMessage(message) {
  const bubble = addMessage('Estoy preparando una respuesta…', 'coach');
  if ($('#gemini-coach-consent')?.checked && state.profile?.age >= 18) {
    try {
      bubble.textContent = await askFormaCoach({ message, context: coachContextForGemini() });
    } catch (error) {
      console.warn('FORMA Coach online unavailable:', error);
      bubble.textContent = coachReply(message) + ' (Respuesta local: el servicio inteligente no está conectado en este momento.)';
    }
  } else {
    bubble.textContent = coachReply(message);
  }
  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
}

$('#chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const field = event.currentTarget.elements.message;
  const message = String(field.value || '').trim();
  if (!message) return;
  addMessage(message, 'user');
  field.value = '';
  void sendCoachMessage(message);
});

$$('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  const message = button.dataset.prompt;
  addMessage(message, 'user');
  void sendCoachMessage(message);
}));""",
    "Gemini Coach",
)

if "guardian-consent-row" in app or "profile.guardianConfirmed" in app:
    raise SystemExit("Guardian consent dependency remains in app.js.")
app_path.write_text(app, encoding="utf-8")

pkg_path = ROOT / "package.json"
pkg = pkg_path.read_text(encoding="utf-8")
pkg = once(pkg, '"check": "node --check src/app.js && node --check src/scanner/pose.js', '"check": "node --check src/app.js && node --check src/scanner/bodycomp.js && node --check src/core/remote.js && node --check src/scanner/pose.js', "syntax checks")
pkg_path.write_text(pkg, encoding="utf-8")

if not (ROOT / "public/config.json").exists():
    (ROOT / "public/config.json").write_text('{\n  "apiBaseUrl": ""\n}\n', encoding="utf-8")
print("FORMA integration patch applied.")
