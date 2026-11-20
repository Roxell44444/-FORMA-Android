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
html = html.replace(
    '<strong>Personalizar respuestas con mis datos</strong><small>Si lo activas, FORMA enviará a procesamiento remoto un resumen de tu perfil y evolución. Tu pregunta se envía al Coach cuando la envías.</small>',
    '<strong>Incluir mi perfil, escáner y progreso en el Coach</strong><small>Al activarlo, el Coach recibirá datos resumidos de tu perfil, último análisis corporal y evolución. Nunca se envían las fotografías.</small>'
)
if "scan-cloud-consent" in html or "forma-clad-consent" in html:
    raise SystemExit("Provider-specific scanner copy or controls remain in the user interface.")
html_path.write_text(html, encoding="utf-8")

# A single generic, one-time permission replaces separate provider checkboxes.
anchor = "async function runBodyScan() {"
helper = """function formaEnsureCloudScanConsent() {
  try {
    if (localStorage.getItem("forma.cloud-scan-consent.v1") === "accepted") return true;
    const accepted = window.confirm(
      "Para completar el análisis cuando el procesamiento del teléfono no sea suficiente, algunas fotografías podrán enviarse a un servicio remoto de procesamiento. Ese uso puede consumir la cuota o generar costes según la cuenta conectada. ¿Autorizas este uso? Puedes continuar sin autorizarlo, pero el análisis podría quedar limitado."
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
    """  const canRunClad = Boolean(imageForClad) &&
    Number(profile.height) >= 140 && Number(profile.height) <= 220 &&
    formaRemoteScanAllowed;""",
    "  const canRunClad = false;"
)

app = app.replace("const cloudAnalysisAllowed = $('#scan-cloud-consent')?.checked === true;", "const cloudAnalysisAllowed = formaRemoteScanAllowed;")
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
app = app.replace("No llegó una respuesta visual de Gemini. Comprueba la conexión e inténtalo de nuevo.", "No llegó una respuesta visual. Comprueba la conexión e inténtalo de nuevo.")
app = app.replace("El análisis local no pudo obtener cifras con esta fotografía. Activa Gemini para recibir una lectura de las zonas visibles; el envío externo es opcional.", "El análisis local no pudo obtener cifras con esta fotografía. Autoriza el procesamiento remoto para recibir una lectura de las zonas visibles.")
app = app.replace("Gemini describe las zonas visibles. No equivale a un porcentaje medido ni a kilos de músculo.", "La lectura visual describe las zonas visibles. No equivale a un porcentaje medido ni a kilos de músculo.")
app = app.replace("La pregunta se envía a Gemini al pulsar el botón. El contexto personal es opcional y empieza desactivado.", "La pregunta se procesa al pulsar el botón. El contexto personal es opcional y empieza desactivado.")
app = app.replace(" cm · Clad", " cm")
app = app.replace("detector = await createPoseLandmarker();", 'detector = await formaWithTimeout(createPoseLandmarker(), 15000, "El detector de postura superó el tiempo de espera.");')
for forbidden in ("scan-cloud-consent", "forma-clad-consent"):
    if forbidden in app:
        raise SystemExit(f"Provider-specific control reference remains in app.js: {forbidden}")


# Remove the blocking confirmation. The optional remote fallback is enabled only
# through a persistent, generic preference in Mi progreso > Privacidad.
app, consent_count = re.subn(
    r'function formaEnsureCloudScanConsent\(\) \{.*?\n\}',
    """function formaEnsureCloudScanConsent() {
  try { return localStorage.getItem("forma.cloud-scan-consent.v1") === "accepted"; }
  catch (error) {
    console.warn("FORMA could not read the remote-analysis preference:", error);
    return false;
  }
}""",
    app, count=1, flags=re.S
)
if consent_count != 1:
    raise SystemExit("Could not remove the scanner confirmation.")

privacy_tail = """    '<p class="fs-muted">La conexión en la nube queda desactivada en esta versión: primero se necesita una identidad de usuario y un sistema de autenticación seguro. CORS y límites por IP no sustituyen una cuenta.</p></section>';"""
privacy_replacement = """    '<div class="fs-privacy-row"><strong>Respaldo de análisis por internet</strong><span>Si el análisis del teléfono no puede completar una lectura numérica, permite enviar las fotos a un servicio remoto para una lectura visual. Puede consumir la cuota o los límites del servicio conectado. No se envían fotos cuando está desactivado.</span><label class="fs-consent"><input id="fs-remote-scan-consent" type="checkbox"> Permitir este respaldo</label></div>' +
    '<p class="fs-muted">Tu perfil y los resultados se guardan en este dispositivo. El Coach recibe datos resumidos solo cuando autorizas incluirlos; nunca recibe las fotografías del escáner.</p></section>';"""
if privacy_tail in app:
    app = app.replace(privacy_tail, privacy_replacement, 1)
elif 'id="fs-remote-scan-consent"' not in app:
    raise SystemExit("Could not place the remote-analysis preference in Privacy.")

render_anchor = """  content.dataset.tab = tab;
}"""
render_replacement = """  content.dataset.tab = tab;
  const remoteConsent = content.querySelector("#fs-remote-scan-consent");
  if (remoteConsent) {
    remoteConsent.checked = formaEnsureCloudScanConsent();
    remoteConsent.addEventListener("change", () => {
      try {
        if (remoteConsent.checked) localStorage.setItem("forma.cloud-scan-consent.v1", "accepted");
        else localStorage.removeItem("forma.cloud-scan-consent.v1");
      } catch (error) {
        console.warn("FORMA could not save the remote-analysis preference:", error);
        remoteConsent.checked = false;
      }
    });
  }
  const suiteCoachConsent = content.querySelector("#fs-coach-consent");
  if (suiteCoachConsent) {
    suiteCoachConsent.checked = formaCoachContextAllowed();
    suiteCoachConsent.addEventListener("change", () => formaSetCoachContextAllowed(suiteCoachConsent.checked));
  }
}"""
if render_anchor not in app:
    raise SystemExit("Could not bind Privacy and Coach preferences.")
app = app.replace(render_anchor, render_replacement, 1)

# A visual-only scan still unlocks a profile-based plan; numeric estimates are
# used only when they actually exist.
app = app.replace("Boolean(p && p.age >= 18 && !state.scanResult?.measurements)", "Boolean(p && p.age >= 18 && !state.scanResult)")
app = app.replace("const scanComposition = state.scanResult?.analysisProvider === 'BodyComp' ? state.scanResult.composition : null;", "const scanComposition = state.scanResult?.composition || null;")
app = app.replace(
"""const muscleEstimate = state.scanResult?.analysisProvider === 'BodyComp' && Number.isFinite(state.scanResult.appendicularLeanMassKg)
    ? { kg: state.scanResult.appendicularLeanMassKg, bodyComp: true }
    : safe ? profileAppendicularMuscle(p) : null;""",
"""const scanMuscleKg = Number(state.scanResult?.appendicularLeanMassKg);
  const muscleEstimate = Number.isFinite(scanMuscleKg) && scanMuscleKg > 0
    ? { kg: scanMuscleKg, bodyComp: true }
    : safe ? profileAppendicularMuscle(p) : null;"""
)

# Replace the old scan summary, which assumed a waist estimate always existed.
scan_tile_pattern = r'  if \(state\.scanResult\?\.measurements\) \{[^\n]*\}\n'
scan_tile_replacement = """  if (state.scanResult) {
    const sm = state.scanResult.measurements || {};
    const sc = state.scanResult.composition || {};
    const positive = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : null;
    const items = [];
    if (positive(sc.bodyFatPercent) !== null) items.push("Grasa " + fmt(sc.bodyFatPercent, 1) + "%");
    else if (positive(sc.bodyFatLow) !== null && positive(sc.bodyFatHigh) !== null) items.push("Grasa " + fmt(sc.bodyFatLow, 1) + "–" + fmt(sc.bodyFatHigh, 1) + "%");
    if (positive(sc.fatFreeMassKg) !== null) items.push("Masa libre de grasa " + fmt(sc.fatFreeMassKg, 1) + " kg");
    for (const [key, label] of [["waist","Cintura"],["hip","Cadera"],["chest","Pecho"],["thigh","Muslo"],["bicep","Brazo"]]) {
      const value = positive(sm[key]?.circumferenceCm);
      if (value !== null) items.push(label + " " + fmt(value, 1) + " cm");
    }
    const scanLine = items.length ? items.join(" · ") : "Lectura visual sin cifras numéricas fiables";
    const scanDate = state.scanResult.createdAt ? dateFmt(String(state.scanResult.createdAt).slice(0, 10)) : "Análisis reciente";
    $('#plan-summary').insertAdjacentHTML('beforeend', '<article class="summary-tile"><small>ESCÁNER · INTEGRADO EN TU PLAN</small><strong>' + escapeHTML(scanLine) + '</strong><span>' + scanDate + '. Las cifras disponibles aportan una referencia inicial; tu objetivo, experiencia, sesiones y equipo también determinan las recomendaciones.</span></article>');
  }
"""
app, tile_count = re.subn(scan_tile_pattern, scan_tile_replacement, app, count=1)
if tile_count != 1:
    raise SystemExit("Could not safely replace the plan scan summary.")

# Diet energy now uses scanned lean mass when a valid numeric value exists.
diet_old = """  const energy= safe && capabilities.mifflinEnergy ? calculateEnergyEstimate({weightKg:p.weight,heightCm:p.height,age:p.age,equation:p.equation,activity:p.activity}) : null;
  const maintenance=energy?.maintenance;"""
diet_new = """  const energy= safe && capabilities.mifflinEnergy ? calculateEnergyEstimate({weightKg:p.weight,heightCm:p.height,age:p.age,equation:p.equation,activity:p.activity}) : null;
  const scanComposition = state.scanResult?.composition || null;
  const scanLeanMassKg = Number(scanComposition?.fatFreeMassKg);
  const scanMaintenance = safe && Number.isFinite(scanLeanMassKg) && scanLeanMassKg > 0
    ? (() => { const value = (370 + 21.6 * scanLeanMassKg) * Number(p.activity || 1.2); return { low: Math.round(value * 0.94), high: Math.round(value * 1.06) }; })()
    : null;
  const maintenance=scanMaintenance || energy?.maintenance;"""
if diet_old not in app:
    raise SystemExit("Could not connect scanned lean mass to the diet estimate.")
app = app.replace(diet_old, diet_new, 1)
app = app.replace(
"""  const fatDetails=profileBodyFatDetails(p);
  const muscleEstimate=profileAppendicularMuscle(p);""",
"""  const profileFatDetails=profileBodyFatDetails(p);
  const scanFatPercent = Number(scanComposition?.bodyFatPercent);
  const fatDetails = Number.isFinite(scanFatPercent) && scanFatPercent > 0 ? { percent: scanFatPercent, fromScan: true } : profileFatDetails;
  const scanMuscleKg = Number(state.scanResult?.appendicularLeanMassKg);
  const muscleEstimate = Number.isFinite(scanMuscleKg) && scanMuscleKg > 0
    ? { kg: scanMuscleKg, fromScan: true }
    : profileAppendicularMuscle(p);"""
)
app = app.replace(
    "Estimación complementaria basada en medidas corporales introducidas por ti.",
    "Estimación complementaria basada en medidas corporales o en el último escáner."
)
app = app.replace(
    "El escáner visual no se utiliza para inventar calorías ni músculo; sus perímetros no están validados para alimentar las ecuaciones.",
    "Cuando el escáner devuelve masa libre de grasa numérica, esta refina la referencia inicial de mantenimiento. Una lectura solo visual no se convierte en calorías, perímetros ni kilos de músculo."
)

# Persistent, explicit Coach permission for a numeric summary (not photographs).
app = app.replace(
    "<strong>Incluir mi perfil, escáner y progreso en el Coach</strong><small>Al activarlo, el Coach recibirá datos resumidos de tu perfil, último análisis corporal y evolución. Nunca se envían las fotografías.</small>",
    "<strong>Incluir mi perfil, escáner y progreso en el Coach</strong><small>Al activarlo, el Coach recibirá datos resumidos de tu perfil, último análisis corporal y evolución. Nunca se envían las fotografías.</small>"
)
coach_anchor = "function coachContextForGemini() {"
coach_helpers = """function formaCoachContextAllowed() {
  try { return localStorage.getItem("forma.coach-context-consent.v1") === "accepted"; }
  catch { return false; }
}
function formaSetCoachContextAllowed(allowed) {
  try {
    if (allowed) localStorage.setItem("forma.coach-context-consent.v1", "accepted");
    else localStorage.removeItem("forma.coach-context-consent.v1");
  } catch (error) { console.warn("FORMA could not save Coach privacy preference:", error); }
}
function formaBindCoachContextConsent() {
  const checkbox = $("#forma-coach-context-consent");
  if (!checkbox || checkbox.dataset.formaBound === "true") return;
  checkbox.checked = formaCoachContextAllowed();
  checkbox.addEventListener("change", () => formaSetCoachContextAllowed(checkbox.checked));
  checkbox.dataset.formaBound = "true";
}
formaBindCoachContextConsent();

"""
if app.count(coach_anchor) != 1:
    raise SystemExit("Could not find the main Coach context function.")
if "function formaCoachContextAllowed()" not in app:
    app = app.replace(coach_anchor, coach_helpers + coach_anchor, 1)

coach_old = """function coachContextForGemini() {
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
}"""
coach_new = """function coachContextForGemini() {
  const p = state.profile;
  const scan = state.scanResult || null;
  const composition = scan?.composition || {};
  const measurements = scan?.measurements || {};
  const clean = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const latestScan = scan ? {
    source: "Análisis corporal",
    bodyFatPercent: clean(composition.bodyFatPercent),
    bodyFatInterval: [clean(composition.bodyFatLow), clean(composition.bodyFatHigh)],
    fatMassKg: clean(composition.fatMassKg),
    fatFreeMassKg: clean(composition.fatFreeMassKg),
    appendicularLeanMassKg: clean(scan.appendicularLeanMassKg),
    measurementsCm: {
      waist: clean(measurements.waist?.circumferenceCm),
      hip: clean(measurements.hip?.circumferenceCm),
      chest: clean(measurements.chest?.circumferenceCm),
      thigh: clean(measurements.thigh?.circumferenceCm),
      arm: clean(measurements.bicep?.circumferenceCm)
    },
    visualReadingAvailable: Boolean(scan.visualFallback?.text),
    date: scan.createdAt || null
  } : null;
  return {
    profile: p ? {
      age: p.age, heightCm: p.height, weightKg: p.weight,
      goal: p.goal, activity: p.activity, experience: p.experience,
      sessionsPerWeek: p.sessions, equipment: p.equipment,
      foodPreferences: p.diet, safetyContext: p.safety
    } : null,
    latestScan,
    progress: {
      completedWorkouts: state.completedWorkouts?.length || 0,
      exerciseEntries: state.exerciseEntries?.length || 0,
      foodEntries: state.foodEntries?.length || 0
    }
  };
}"""
if coach_old not in app:
    raise SystemExit("Could not replace the old main Coach context safely.")
app = app.replace(coach_old, coach_new, 1)
app = app.replace(
    "state.profile?.age >= 18 && $('#forma-coach-context-consent')?.checked",
    "state.profile?.age >= 18 && formaCoachContextAllowed()"
)
app = app.replace(
    "Incluir mis registros de FORMA en esta consulta. No se enviarán fotografías.",
    "Incluir mi perfil, último escáner corporal y progreso en el Coach. No se envían fotografías."
)
app = app.replace(
    "Autorizo enviar al Coach el resumen de mis registros de esta semana. Por defecto no se comparte.",
    "Autorizo enviar al Coach mi perfil, último escáner y resumen de actividad de esta semana. No se envían fotografías."
)
history_old = """    bodyFatHigh: finiteOrNull(composition?.bodyFatHigh),
    fatFreeMassKg: finiteOrNull(composition?.fatFreeMassKg),
    waistCm: finiteOrNull(measurements.waist?.circumferenceCm),
    hipCm: finiteOrNull(measurements.hip?.circumferenceCm),
    chestCm: finiteOrNull(measurements.chest?.circumferenceCm),
    visualOnly: !composition && !Object.keys(measurements).length"""
history_new = """    bodyFatHigh: finiteOrNull(composition?.bodyFatHigh),
    fatMassKg: finiteOrNull(composition?.fatMassKg),
    fatFreeMassKg: finiteOrNull(composition?.fatFreeMassKg),
    appendicularLeanMassKg: finiteOrNull(result.appendicularLeanMassKg),
    waistCm: finiteOrNull(measurements.waist?.circumferenceCm),
    hipCm: finiteOrNull(measurements.hip?.circumferenceCm),
    chestCm: finiteOrNull(measurements.chest?.circumferenceCm),
    thighCm: finiteOrNull(measurements.thigh?.circumferenceCm),
    armCm: finiteOrNull(measurements.bicep?.circumferenceCm),
    visualOnly: !composition && !Object.keys(measurements).length"""
if history_old not in app:
    raise SystemExit("Could not extend the saved scan history fields.")
app = app.replace(history_old, history_new, 1)
suite_context_pattern = r'latestScan: latest \? \{.*?\} : null,'
suite_context_new = """latestScan: latest ? {
      source: "Análisis corporal",
      bodyFatPercent: latest.bodyFatPercent,
      bodyFatInterval: [latest.bodyFatLow, latest.bodyFatHigh],
      fatMassKg: latest.fatMassKg,
      fatFreeMassKg: latest.fatFreeMassKg,
      appendicularLeanMassKg: latest.appendicularLeanMassKg,
      measurementsCm: {
        waist: latest.waistCm, hip: latest.hipCm, chest: latest.chestCm,
        thigh: latest.thighCm, arm: latest.armCm
      },
      visualOnly: latest.visualOnly === true,
      date: latest.date
    } : null,"""
app, suite_context_count = re.subn(suite_context_pattern, suite_context_new, app, count=1, flags=re.S)
if suite_context_count != 1:
    raise SystemExit("Could not extend Studio Coach scan context.")

app = app.replace("Gemini analizó las fotografías y describió lo que puede observarse.", "La lectura visual de tus fotografías está lista.")
app = app.replace("Análisis completado con composición estimada y lectura visual de Gemini.", "Análisis completado con composición estimada y lectura visual.")
app = app.replace("Se obtuvieron medidas parciales y Gemini completó una lectura visual.", "Se obtuvieron medidas parciales y se completó una lectura visual.")
app = app.replace("Gemini describe las zonas visibles. No equivale a un porcentaje medido ni a kilos de músculo.", "La lectura visual describe las zonas visibles. No equivale a un porcentaje medido ni a kilos de músculo.")
app = app.replace("La pregunta se envía a Gemini al pulsar el botón.", "La pregunta se procesa al pulsar el botón.")
if "window.confirm(" in app[app.find("function formaEnsureCloudScanConsent"):app.find("function formaWithTimeout")]:
    raise SystemExit("Scanner confirmation was not removed.")


# Show one generic, non-blocking consent directly on the scanner. The remote
# option stays off until the user explicitly enables it; no modal interrupts a scan.
html, consent_ui_count = re.subn(
    r'<p class="scan-privacy-note">.*?</p>\s*',
    '''<p class="scan-privacy-note">El análisis local se intenta primero. Si no obtiene cifras, puedes permitir una lectura complementaria por internet con la opción siguiente. Las fotografías no salen del teléfono mientras esté desactivada.</p>
              <label class="scan-remote-consent" for="scan-remote-fallback-consent"><input id="scan-remote-fallback-consent" type="checkbox"><span><strong>Permitir lectura complementaria por internet</strong><small>Solo se enviarán las fotografías seleccionadas si el cálculo local no puede completarse. Puede utilizar la cuota o los límites del servicio conectado.</small></span></label>
''',
    html, count=1, flags=re.S
)
if consent_ui_count != 1:
    raise SystemExit("Could not place the generic scanner privacy option.")
html_path.write_text(html, encoding="utf-8")

css_path = ROOT / "src/ui/styles.css"
css = css_path.read_text(encoding="utf-8")
css += """
/* Generic remote-analysis permission, shown beside the scan action without a modal. */
.scan-remote-consent{display:flex;align-items:flex-start;gap:12px;margin:14px 0 20px;padding:14px 15px;border:1px solid var(--forma-border,rgba(198,224,212,.16));border-radius:16px;background:rgba(23,36,40,.72);color:var(--forma-text,#edf4ef);font-size:.9rem;line-height:1.45;cursor:pointer}
.scan-remote-consent input{flex:0 0 auto;width:19px;height:19px;margin:2px 0 0;accent-color:var(--forma-accent,#b8ef58)}
.scan-remote-consent span{display:grid;gap:4px}
.scan-remote-consent strong{font-weight:650}
.scan-remote-consent small{display:block;color:var(--forma-muted,#9aada5);font-size:.82rem;line-height:1.45}
"""
css_path.write_text(css, encoding="utf-8")

# Capture the exact network/config/quota failure instead of swallowing it.
if "let formaVisualFallbackError = null;" not in app:
    app = app.replace(
        "async function runGeminiPhotoFallback() {",
        "let formaVisualFallbackError = null;\n\nasync function runGeminiPhotoFallback() {",
        1
    )
app = app.replace(
    """async function runGeminiPhotoFallback() {
  if (!formaRemoteScanAllowed) return null;""",
    """async function runGeminiPhotoFallback() {
  formaVisualFallbackError = null;
  if (!formaRemoteScanAllowed) return null;"""
)
app = app.replace(
    """  } catch (error) {
    console.warn('FORMA visual analysis unavailable:', error);
    return null;
  }
}

function cladMeasurementsFromResult""",
    """  } catch (error) {
    formaVisualFallbackError = String(error?.message || error || "No se pudo completar la lectura complementaria.")
      .replace(/Gemini|Clad/gi, "el servicio remoto")
      .slice(0, 220);
    console.warn('FORMA visual analysis unavailable:', error);
    return null;
  }
}

function cladMeasurementsFromResult"""
)
if "formaVisualFallbackError = String(error?.message" not in app:
    raise SystemExit("Could not preserve the remote fallback error.")

# Bind the same preference from the scan page and Mi progreso > Privacidad.
consent_state_anchor = "let formaRemoteScanAllowed = false;"
consent_binding = """let formaRemoteScanAllowed = false;
const formaScanRemoteConsentControl = $("#scan-remote-fallback-consent");
if (formaScanRemoteConsentControl) {
  formaScanRemoteConsentControl.checked = formaEnsureCloudScanConsent();
  formaScanRemoteConsentControl.addEventListener("change", () => {
    formaRemoteScanAllowed = formaScanRemoteConsentControl.checked === true;
    try {
      if (formaRemoteScanAllowed) localStorage.setItem("forma.cloud-scan-consent.v1", "accepted");
      else localStorage.removeItem("forma.cloud-scan-consent.v1");
    } catch (error) {
      console.warn("FORMA could not save the scanner privacy preference:", error);
      formaRemoteScanAllowed = false;
      formaScanRemoteConsentControl.checked = false;
    }
  });
}"""
if app.count(consent_state_anchor) != 1:
    raise SystemExit("Could not bind the scanner privacy option.")
app = app.replace(consent_state_anchor, consent_binding, 1)

# Explain the local eligibility requirements and whether any remote request was made.
old_no_result = """    $('#capture-status').textContent = visualText
      ? "La lectura visual de tus fotografías está lista."
      : cloudAnalysisAllowed ? "No llegó una respuesta visual. Comprueba la conexión e inténtalo de nuevo." : "El análisis local no pudo obtener cifras con esta fotografía. Autoriza el procesamiento remoto para recibir una lectura de las zonas visibles.";
    $('#pose-pair-summary').textContent = visualText
      ? "Lectura visual completada con " + (Number(hasFront) + Number(hasSide)) + " fotografía(s)."
      : "No llegó una respuesta utilizable de los servicios de análisis.";"""
new_no_result = """    const missingLocalRequirements = [];
    if (!hasFront) missingLocalRequirements.push("una foto de frente");
    if (!hasSide) missingLocalRequirements.push("una foto de perfil");
    if (!(Number(profile.age) >= 18 && Number(profile.age) <= 59)) missingLocalRequirements.push("una edad adulta dentro del rango de referencia local");
    if (!["male", "female"].includes(profile.equation)) missingLocalRequirements.push("la referencia corporal del perfil");
    if (!(Number(profile.height) >= 130 && Number(profile.height) <= 230)) missingLocalRequirements.push("la estatura en tu perfil");
    if (!(Number(profile.weight) > 0)) missingLocalRequirements.push("el peso en tu perfil");
    const localRequirementsText = missingLocalRequirements.length
      ? "Para intentar el cálculo local hacen falta: " + missingLocalRequirements.join(", ") + "."
      : "Las fotos no permitieron obtener medidas numéricas fiables con el cálculo local.";
    const remoteFailureText = formaVisualFallbackError
      ? " La lectura complementaria no se completó: " + formaVisualFallbackError
      : " La lectura complementaria no devolvió un resultado.";
    $('#capture-status').textContent = visualText
      ? "La lectura visual de tus fotografías está lista."
      : cloudAnalysisAllowed
        ? "No se pudo completar la lectura complementaria." + remoteFailureText
        : localRequirementsText + " No se ha enviado ninguna foto. Activa «Permitir lectura complementaria por internet» debajo del aviso si deseas intentarlo por esa vía.";
    $('#pose-pair-summary').textContent = visualText
      ? "Lectura visual completada con " + (Number(hasFront) + Number(hasSide)) + " fotografía(s)."
      : cloudAnalysisAllowed
        ? "El cálculo local y la lectura complementaria no completaron un resultado."
        : "El cálculo local no obtuvo cifras y el respaldo por internet está desactivado; no se enviaron fotografías.";"""
if old_no_result not in app:
    raise SystemExit("Could not find no-result scanner messages")
app = app.replace(old_no_result, new_no_result, 1)

# Make the start action mirror saved settings and retain the last useful error.
app = app.replace(
    """  formaRemoteScanAllowed = formaEnsureCloudScanConsent();
  scanBusy = true;""",
    """  formaRemoteScanAllowed = formaEnsureCloudScanConsent();
  if (formaScanRemoteConsentControl) formaScanRemoteConsentControl.checked = formaRemoteScanAllowed;
  formaVisualFallbackError = null;
  scanBusy = true;"""
)
app = app.replace(
    """    if (!visualFallbackDone) {
      $('#capture-status').textContent = "No se pudo completar el análisis. Comprueba la conexión y los datos del perfil; puedes intentarlo de nuevo.";
    }""",
    """    if (!visualFallbackDone) {
      const reason = formaRemoteScanAllowed && formaVisualFallbackError
        ? " La lectura complementaria falló: " + formaVisualFallbackError
        : formaRemoteScanAllowed
          ? " No se recibió una respuesta; comprueba tu conexión."
          : " No se enviaron fotografías: el respaldo por internet está desactivado.";
      $('#capture-status').textContent = "No se pudo completar el análisis local." + reason;
      $('#pose-pair-summary').textContent = "Revisa las indicaciones del análisis y vuelve a intentarlo.";
    }"""
)

# Keep the privacy switch in Mi progreso synchronized with the scanner switch.
app = app.replace(
    """        if (remoteConsent.checked) localStorage.setItem("forma.cloud-scan-consent.v1", "accepted");
        else localStorage.removeItem("forma.cloud-scan-consent.v1");""",
    """        if (remoteConsent.checked) localStorage.setItem("forma.cloud-scan-consent.v1", "accepted");
        else localStorage.removeItem("forma.cloud-scan-consent.v1");
        if (formaScanRemoteConsentControl) formaScanRemoteConsentControl.checked = remoteConsent.checked;"""
)
if "El cálculo local no obtuvo cifras y el respaldo por internet está desactivado" not in app:
    raise SystemExit("Scanner failure diagnostics were not installed.")

app_path.write_text(app, encoding="utf-8")
print("FORMA scan consent and actionable fallback diagnostics applied.")

app_path.write_text(app, encoding="utf-8")
print("FORMA scanner privacy and failover patch applied.")
