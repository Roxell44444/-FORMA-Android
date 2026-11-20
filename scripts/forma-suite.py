#!/usr/bin/env python3
"""Add the FORMA 1.8 personal progress, training, nutrition and privacy center."""
from pathlib import Path

ROOT = Path("FORMA-1.1.0")
app_path = ROOT / "src/app.js"
css_path = ROOT / "src/ui/styles.css"
app = app_path.read_text(encoding="utf-8")
css = css_path.read_text(encoding="utf-8")

if "FORMA SUITE 1.8" in app:
    raise SystemExit("FORMA Suite is already present; refusing to append it twice.")

app += r"""

/* ======================== FORMA SUITE 1.8 ========================
   Local-first progress, manual measurements, training, nutrition,
   weekly review, temporary photo comparison and privacy controls.
   Photos are never persisted by this module or sent to the backend.
================================================================= */
const FORMA_SUITE_STORAGE_KEY = "forma.suite.v1";
const FORMA_SUITE_LIMIT = 250;
let formaSuitePhotoUrls = { before: null, after: null };

function formaSuiteRead() {
  const empty = { measurements: [], workouts: [], meals: [], habits: [] };
  try {
    const value = JSON.parse(localStorage.getItem(FORMA_SUITE_STORAGE_KEY) || "null");
    if (!value || typeof value !== "object") return empty;
    return {
      measurements: Array.isArray(value.measurements) ? value.measurements.slice(-FORMA_SUITE_LIMIT) : [],
      workouts: Array.isArray(value.workouts) ? value.workouts.slice(-FORMA_SUITE_LIMIT) : [],
      meals: Array.isArray(value.meals) ? value.meals.slice(-FORMA_SUITE_LIMIT) : [],
      habits: Array.isArray(value.habits) ? value.habits.slice(-FORMA_SUITE_LIMIT) : []
    };
  } catch { return empty; }
}

function formaSuiteWrite(data) {
  try {
    localStorage.setItem(FORMA_SUITE_STORAGE_KEY, JSON.stringify({
      measurements: data.measurements.slice(-FORMA_SUITE_LIMIT),
      workouts: data.workouts.slice(-FORMA_SUITE_LIMIT),
      meals: data.meals.slice(-FORMA_SUITE_LIMIT),
      habits: data.habits.slice(-FORMA_SUITE_LIMIT)
    }));
    return true;
  } catch (error) {
    console.warn("FORMA could not save local progress:", error);
    return false;
  }
}

function formaSuiteToday() {
  const now = new Date();
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
}

function formaSuiteEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}

function formaSuiteNumber(value, min, max) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= min && number <= max ? number : null;
}

function formaSuiteDateLabel(value) {
  try {
    return new Intl.DateTimeFormat("es", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value + "T12:00:00"));
  } catch { return value; }
}

function formaSuiteRecent(items, days = 7) {
  const cutoff = new Date();
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - (days - 1));
  return items.filter(item => {
    const date = new Date(String(item.date || "") + "T12:00:00");
    return !Number.isNaN(date.getTime()) && date >= cutoff;
  });
}

function formaSuiteLastScan() {
  try {
    if (state?.scanResult) return state.scanResult;
  } catch {}
  return null;
}

function formaSuiteCaptureSummary(result) {
  if (!result) return { title: "Aún no hay un análisis reciente", detail: "Cuando completes un escaneo, aquí verás su fuente y sus limitaciones." };
  const issues = ["front", "side"].flatMap(key => result.captureQuality?.[key]?.issues || []);
  if (result.visualFallback && !result.composition && !Object.keys(result.measurements || {}).length) {
    return { title: "Lectura visual, sin mediciones", detail: "Gemini describe las zonas visibles. No equivale a un porcentaje medido ni a kilos de músculo." };
  }
  if (result.composition) {
    const low = Number(result.composition.bodyFatLow);
    const high = Number(result.composition.bodyFatHigh);
    const interval = Number.isFinite(low) && Number.isFinite(high) ? " Intervalo orientativo: " + low.toFixed(1) + "–" + high.toFixed(1) + "%." : "";
    return issues.length
      ? { title: "Estimación condicionada por las fotografías", detail: "Se detectaron " + issues.length + " advertencia(s) de captura." + interval + " Revisa el encuadre y compara tendencias, no valores aislados." }
      : { title: "Estimación de composición disponible", detail: "Fuente: " + formaSuiteEscape(result.analysisProvider || "modelo local") + "." + interval + " Sigue siendo una estimación fotográfica, no una medición clínica." };
  }
  const count = Object.keys(result.measurements || {}).length;
  return { title: count ? "Medidas parciales disponibles" : "Análisis incompleto", detail: count + " perímetro(s) estimado(s). La fuente y la captura pueden afectar a su fiabilidad." };
}

function formaSuiteScanHistory() {
  try {
    return typeof readFormaScanHistory === "function" ? readFormaScanHistory() : [];
  } catch { return []; }
}

function formaSuiteTrend(items, field, suffix) {
  const values = items.filter(item => item[field] !== null && item[field] !== undefined && item[field] !== "" && Number.isFinite(Number(item[field]))).slice(-8);
  if (!values.length) return '<p class="fs-muted">Todavía no hay registros de esta métrica.</p>';
  const rows = values.slice(-5).reverse().map(item =>
    '<div class="fs-history-row"><span>' + formaSuiteEscape(formaSuiteDateLabel(String(item.date).slice(0, 10))) +
    '</span><strong>' + Number(item[field]).toFixed(1) + " " + suffix +
    '<small>' + formaSuiteEscape(item.source || "manual") + "</small></strong></div>"
  ).join("");
  if (values.length < 2) return '<div class="fs-history-list">' + rows + '</div>';
  const w = 300, h = 74, pad = 8;
  const nums = values.map(item => Number(item[field]));
  const min = Math.min(...nums), max = Math.max(...nums), span = Math.max(0.5, max - min);
  const points = nums.map((n, i) => (pad + i * ((w - pad * 2) / (nums.length - 1))).toFixed(1) + "," +
    (h - pad - ((n - min) / span) * (h - pad * 2)).toFixed(1)).join(" ");
  return '<svg class="fs-chart" viewBox="0 0 300 74" role="img" aria-label="Tendencia de ' + formaSuiteEscape(field) + '">' +
    '<polyline points="' + points + '" fill="none" stroke="var(--green,#427a5b)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' +
    points.split(" ").map(point => { const pair = point.split(","); return '<circle cx="' + pair[0] + '" cy="' + pair[1] + '" r="3" fill="var(--green,#427a5b)"/>'; }).join("") +
    '</svg><div class="fs-history-list">' + rows + '</div>';
}

function formaSuiteProgressHtml() {
  const data = formaSuiteRead();
  const scans = formaSuiteScanHistory();
  const manual = data.measurements.slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const latest = formaSuiteCaptureSummary(formaSuiteLastScan());
  const latestManual = manual[manual.length - 1];
  const latestScan = scans[scans.length - 1];
  const scanSummary = latestScan
    ? '<div class="fs-stat"><span>Último escáner guardado</span><strong>' +
      (latestScan.bodyFatPercent !== null && Number.isFinite(Number(latestScan.bodyFatPercent)) ? Number(latestScan.bodyFatPercent).toFixed(1) + "% grasa estimada" : "Lectura visual o parcial") +
      '</strong><small>' + formaSuiteEscape(latestScan.source || "IA") + " · " + formaSuiteEscape(formaSuiteDateLabel(String(latestScan.date).slice(0, 10))) + '</small></div>'
    : '<div class="fs-stat"><span>Historial de escáner</span><strong>Sin registros todavía</strong><small>Los resultados se guardan localmente sin las fotografías.</small></div>';
  return '<section class="fs-grid">' +
    '<div class="fs-card fs-wide"><span class="fs-kicker">ESCÁNER · CALIDAD</span><h3>' + latest.title + '</h3><p>' + latest.detail + '</p>' + scanSummary + '</div>' +
    '<div class="fs-card"><span class="fs-kicker">PESO · REGISTROS MANUALES</span><h3>' + (latestManual && Number.isFinite(Number(latestManual.weightKg)) ? Number(latestManual.weightKg).toFixed(1) + " kg" : "—") + '</h3>' + formaSuiteTrend(manual, "weightKg", "kg") + '</div>' +
    '<div class="fs-card"><span class="fs-kicker">CINTURA · REGISTROS MANUALES</span><h3>' + (latestManual && latestManual.waistCm !== null && Number.isFinite(Number(latestManual.waistCm)) ? Number(latestManual.waistCm).toFixed(1) + " cm" : "—") + '</h3>' + formaSuiteTrend(manual, "waistCm", "cm") + '</div>' +
    '</section>' +
    '<section class="fs-card"><span class="fs-kicker">AÑADIR MEDICIÓN</span><h3>Registra tus medidas</h3><p>Estos datos se guardan como mediciones manuales y nunca se mezclan con las estimaciones del escáner.</p>' +
    '<form id="fs-measure-form" class="fs-form"><label>Fecha<input name="date" type="date" value="' + formaSuiteToday() + '" required></label>' +
    '<label>Peso (kg)<input name="weightKg" type="number" min="1" max="500" step=".1" inputmode="decimal"></label>' +
    '<label>Cintura (cm)<input name="waistCm" type="number" min="20" max="250" step=".1" inputmode="decimal"></label>' +
    '<label>Cadera (cm)<input name="hipCm" type="number" min="20" max="250" step=".1" inputmode="decimal"></label>' +
    '<label>Pecho (cm)<input name="chestCm" type="number" min="20" max="250" step=".1" inputmode="decimal"></label>' +
    '<label>Muslo (cm)<input name="thighCm" type="number" min="10" max="150" step=".1" inputmode="decimal"></label>' +
    '<label>Brazo (cm)<input name="armCm" type="number" min="10" max="100" step=".1" inputmode="decimal"></label>' +
    '<button class="fs-primary" type="submit">Guardar medición</button></form></section>' +
    '<section class="fs-card"><span class="fs-kicker">COMPARACIÓN VISUAL LOCAL</span><h3>Compara dos fotografías</h3><p>Las imágenes se procesan solo en pantalla. No se suben ni se guardan en el historial.</p>' +
    '<div class="fs-form fs-photo-pickers"><label>Foto anterior<input id="fs-photo-before" type="file" accept="image/*"></label><label>Foto actual<input id="fs-photo-after" type="file" accept="image/*"></label></div>' +
    '<div id="fs-photo-stage" class="fs-photo-stage"><span>Selecciona dos imágenes para compararlas</span></div>' +
    '<label class="fs-range-label">Desliza para comparar<input id="fs-photo-range" type="range" min="0" max="100" value="50"></label>' +
    '<button type="button" class="fs-secondary" data-action="clear-photos">Quitar fotografías</button></section>';
}

function formaSuiteWorkoutsHtml() {
  const data = formaSuiteRead();
  const recent = data.workouts.slice().sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 8);
  const week = formaSuiteRecent(data.workouts);
  const minutes = week.reduce((sum, item) => sum + (Number(item.minutes) || 0), 0);
  const rows = recent.length ? recent.map(item =>
    '<div class="fs-history-row"><span>' + formaSuiteEscape(formaSuiteDateLabel(item.date)) + '</span><strong>' +
    formaSuiteEscape(item.type) + " · " + Number(item.minutes || 0) + " min" +
    '<small>' + formaSuiteEscape(item.exercise || "Sesión general") + (item.sets ? " · " + item.sets + "×" + item.reps : "") +
    (item.loadKg ? " · " + item.loadKg + " kg" : "") + "</small></strong></div>"
  ).join("") : '<p class="fs-muted">Todavía no hay entrenamientos registrados.</p>';
  return '<div class="fs-grid"><div class="fs-stat"><span>Sesiones · últimos 7 días</span><strong>' + week.length + '</strong></div><div class="fs-stat"><span>Tiempo total</span><strong>' + minutes + ' min</strong></div></div>' +
    '<section class="fs-card"><span class="fs-kicker">BITÁCORA</span><h3>Registrar entrenamiento</h3>' +
    '<form id="fs-workout-form" class="fs-form"><label>Fecha<input name="date" type="date" value="' + formaSuiteToday() + '" required></label>' +
    '<label>Tipo<select name="type"><option>Fuerza</option><option>Cardio</option><option>Movilidad</option><option>Deporte</option><option>Otro</option></select></label>' +
    '<label>Duración (min)<input name="minutes" type="number" min="1" max="600" step="1" required></label>' +
    '<label>Ejercicio o actividad<input name="exercise" maxlength="80" placeholder="Ej. sentadillas, caminar"></label>' +
    '<label>Series<input name="sets" type="number" min="0" max="100" step="1"></label>' +
    '<label>Repeticiones<input name="reps" type="number" min="0" max="500" step="1"></label>' +
    '<label>Carga (kg)<input name="loadKg" type="number" min="0" max="1000" step=".5"></label>' +
    '<label>Esfuerzo percibido (1–10)<input name="effort" type="number" min="1" max="10" step="1"></label>' +
    '<button class="fs-primary" type="submit">Guardar sesión</button></form></section>' +
    '<section class="fs-card"><span class="fs-kicker">HISTORIAL</span><h3>Sesiones recientes</h3><div class="fs-history-list">' + rows + '</div></section>';
}

function formaSuiteAllMeals() {
  const native = Array.isArray(state?.foodEntries) ? state.foodEntries : [];
  return [...native, ...formaSuiteRead().meals].filter(item => item && typeof item.date === "string");
}

function formaSuiteNutritionHtml() {
  const data = formaSuiteRead();
  const allMeals = formaSuiteAllMeals();
  const today = formaSuiteToday();
  const todaysMeals = allMeals.filter(item => item.date === today);
  const totals = todaysMeals.reduce((sum, item) => ({
    calories: sum.calories + (Number(item.calories) || 0),
    protein: sum.protein + (Number(item.protein) || 0),
    carbs: sum.carbs + (Number(item.carbs) || 0),
    fat: sum.fat + (Number(item.fat) || 0)
  }), { calories: 0, protein: 0, carbs: 0, fat: 0 });
  const recent = allMeals.slice().sort((a, b) => (String(b.date) + String(b.time || "")).localeCompare(String(a.date) + String(a.time || ""))).slice(0, 10);
  const rows = recent.length ? recent.map(item =>
    '<div class="fs-history-row"><span>' + formaSuiteEscape(formaSuiteDateLabel(item.date)) + '</span><strong>' +
    formaSuiteEscape(item.name) + '<small>' + formaSuiteEscape(({breakfast:"Desayuno",lunch:"Almuerzo",dinner:"Cena",snack:"Merienda"})[item.mealType] || item.mealType || "Comida") + " · " + Number(item.calories || 0) + " kcal · P " + Number(item.protein || 0) +
    " g · C " + Number(item.carbs || 0) + " g · G " + Number(item.fat || 0) + " g</small></strong></div>"
  ).join("") : '<p class="fs-muted">Registra una comida para empezar a ver tus totales.</p>';
  return '<div class="fs-grid fs-macros"><div class="fs-stat"><span>Calorías hoy</span><strong>' + Math.round(totals.calories) + '</strong><small>kcal registradas</small></div>' +
    '<div class="fs-stat"><span>Proteína</span><strong>' + Math.round(totals.protein) + ' g</strong></div><div class="fs-stat"><span>Carbohidratos</span><strong>' + Math.round(totals.carbs) + ' g</strong></div><div class="fs-stat"><span>Grasas</span><strong>' + Math.round(totals.fat) + ' g</strong></div></div>' +
    '<section class="fs-card"><span class="fs-kicker">DIARIO DE ALIMENTACIÓN</span><h3>Añadir comida</h3><p>Introduce cantidades de etiquetas o porciones que conozcas. Los totales son tan precisos como los datos registrados.</p>' +
    '<form id="fs-meal-form" class="fs-form"><label>Fecha<input name="date" type="date" value="' + today + '" required></label>' +
    '<label>Tipo<select name="mealType"><option value="breakfast">Desayuno</option><option value="lunch">Almuerzo</option><option value="dinner">Cena</option><option value="snack">Merienda</option></select></label>' +
    '<label>Comida<input name="name" maxlength="100" placeholder="Ej. avena con fruta" required></label>' +
    '<label>Calorías (kcal)<input name="calories" type="number" min="0" max="10000" step="1"></label>' +
    '<label>Proteína (g)<input name="protein" type="number" min="0" max="1000" step=".1"></label>' +
    '<label>Carbohidratos (g)<input name="carbs" type="number" min="0" max="1000" step=".1"></label>' +
    '<label>Grasas (g)<input name="fat" type="number" min="0" max="1000" step=".1"></label>' +
    '<button class="fs-primary" type="submit">Guardar comida</button></form></section>' +
    '<section class="fs-card"><span class="fs-kicker">HISTORIAL</span><h3>Comidas recientes</h3><div class="fs-history-list">' + rows + '</div></section>';
}

function formaSuiteReviewHtml() {
  const data = formaSuiteRead();
  const workouts = formaSuiteRecent(data.workouts);
  const meals = formaSuiteRecent(formaSuiteAllMeals());
  const exercises = formaSuiteRecent(Array.isArray(state?.exerciseEntries) ? state.exerciseEntries : []);
  const habits = formaSuiteRecent(data.habits);
  const minutes = workouts.reduce((sum, item) => sum + (Number(item.minutes) || 0), 0);
  const protein = meals.reduce((sum, item) => sum + (Number(item.protein) || 0), 0);
  const calories = meals.reduce((sum, item) => sum + (Number(item.calories) || 0), 0);
  const sleep = habits.filter(item => item.sleepHours !== null && item.sleepHours !== undefined && Number.isFinite(Number(item.sleepHours)));
  const sleepAverage = sleep.length ? (sleep.reduce((sum, item) => sum + Number(item.sleepHours), 0) / sleep.length).toFixed(1) + " h" : "Sin datos";
  const summary = workouts.length + " sesiones registradas, " + minutes + " minutos de actividad, " +
    exercises.length + " ejercicios del diario, " + meals.length + " comidas registradas, " +
    Math.round(protein) + " g de proteína acumulada y sueño promedio " + sleepAverage + ".";
  return '<section class="fs-card"><span class="fs-kicker">ÚLTIMOS 7 DÍAS</span><h3>Tu revisión semanal</h3><div class="fs-grid">' +
    '<div class="fs-stat"><span>Entrenamientos</span><strong>' + workouts.length + '</strong></div>' +
    '<div class="fs-stat"><span>Actividad</span><strong>' + minutes + ' min</strong></div>' +
    '<div class="fs-stat"><span>Comidas registradas</span><strong>' + meals.length + '</strong></div>' +
    '<div class="fs-stat"><span>Ejercicios del diario</span><strong>' + exercises.length + '</strong></div>' +
    '<div class="fs-stat"><span>Sueño promedio</span><strong>' + sleepAverage + '</strong></div></div>' +
    '<p>' + formaSuiteEscape(summary) + '</p><p class="fs-muted">Los registros incompletos no se interpretan como objetivos incumplidos. La revisión describe únicamente lo que anotaste.</p></section>' +
    '<section class="fs-card"><span class="fs-kicker">HÁBITOS</span><h3>Registrar descanso e hidratación</h3>' +
    '<form id="fs-habit-form" class="fs-form"><label>Fecha<input name="date" type="date" value="' + formaSuiteToday() + '" required></label>' +
    '<label>Sueño (horas)<input name="sleepHours" type="number" min="0" max="24" step=".25"></label>' +
    '<label>Vasos de agua<input name="waterGlasses" type="number" min="0" max="40" step="1"></label>' +
    '<button class="fs-primary" type="submit">Guardar hábitos</button></form></section>' +
    '<section class="fs-card"><span class="fs-kicker">COACH IA</span><h3>Solicitar una revisión</h3>' +
    '<label class="fs-consent"><input id="fs-review-consent" type="checkbox"><span>Autorizo enviar al Coach el resumen de mis registros de esta semana. Por defecto no se comparte.</span></label>' +
    '<button class="fs-primary" type="button" data-action="weekly-review">Preparar revisión con Coach</button><div id="fs-review-output" class="fs-ai-output" aria-live="polite"></div></section>';
}

function formaSuiteCoachHtml() {
  return '<section class="fs-card"><span class="fs-kicker">FORMA COACH</span><h3>Entrenamiento, alimentación y hábitos</h3>' +
    '<p>La pregunta se envía a Gemini al pulsar el botón. El contexto personal es opcional y empieza desactivado.</p>' +
    '<form id="fs-coach-form" class="fs-form fs-one-col"><label>¿En qué te ayudo?<textarea name="message" rows="4" maxlength="500" required placeholder="Ej. Ayúdame a organizar tres entrenamientos semanales."></textarea></label>' +
    '<label class="fs-consent"><input id="fs-coach-consent" type="checkbox"><span>Incluir mis registros de FORMA en esta consulta. No se enviarán fotografías.</span></label>' +
    '<button class="fs-primary" type="submit">Consultar al Coach</button></form><div id="fs-coach-output" class="fs-ai-output" aria-live="polite"></div></section>';
}

function formaSuitePrivacyHtml() {
  return '<section class="fs-card"><span class="fs-kicker">PRIVACIDAD Y CONTROL</span><h3>Tus datos permanecen en este dispositivo</h3>' +
    '<p>El Centro FORMA guarda medidas manuales, comidas, entrenamientos y hábitos en el almacenamiento local de la aplicación. Las fotos de comparación solo viven temporalmente en memoria.</p>' +
    '<div class="fs-privacy-row"><strong>Exportar copia local</strong><span>Descarga un archivo JSON con los registros del Centro y el historial numérico del escáner.</span><button class="fs-secondary" type="button" data-action="export">Exportar mis datos</button></div>' +
    '<div class="fs-privacy-row"><strong>Borrar registros del Centro</strong><span>Elimina medidas manuales, sesiones y hábitos del Centro. El diario principal se gestiona por separado.</span><button class="fs-danger" type="button" data-action="delete-suite">Borrar registros del Centro</button></div>' +
    '<div class="fs-privacy-row"><strong>Borrar comidas y ejercicios del diario</strong><span>Elimina solo las comidas y ejercicios registrados en el diario principal; conserva tu perfil y el resto de tus datos.</span><button class="fs-danger" type="button" data-action="delete-diary">Borrar comidas y ejercicios</button></div>' +
    '<div class="fs-privacy-row"><strong>Borrar historial numérico del escáner</strong><span>Elimina las tendencias guardadas del escáner. No borra tu perfil ni el resto de la aplicación.</span><button class="fs-danger" type="button" data-action="delete-scans">Borrar historial del escáner</button></div>' +
    '<p class="fs-muted">La conexión en la nube queda desactivada en esta versión: primero se necesita una identidad de usuario y un sistema de autenticación seguro. CORS y límites por IP no sustituyen una cuenta.</p></section>';
}

function formaSuiteClose() {
    '<div class="fs-privacy-row"><strong>Borrar historial numérico del escáner</strong><span>Elimina las tendencias guardadas del escáner. No borra tu perfil ni el resto de la aplicación.</span><button class="fs-danger" type="button" data-action="delete-scans">Borrar historial del escáner</button></div>' +
    '<p class="fs-muted">La conexión en la nube queda desactivada en esta versión: primero se necesita una identidad de usuario y un sistema de autenticación seguro. CORS y límites por IP no sustituyen una cuenta.</p></section>';
}

function formaSuiteRender(tab) {
  const content = document.getElementById("fs-content");
  if (!content) return;
  const renderers = {
    progreso: formaSuiteProgressHtml,
    entrenamiento: formaSuiteWorkoutsHtml,
    nutricion: formaSuiteNutritionHtml,
    revision: formaSuiteReviewHtml,
    coach: formaSuiteCoachHtml,
    privacidad: formaSuitePrivacyHtml
  };
  content.innerHTML = (renderers[tab] || formaSuiteProgressHtml)();
  content.dataset.tab = tab;
}

function formaSuiteOpen(tab = "progreso") {
  const overlay = document.getElementById("forma-suite-overlay");
  if (!overlay) return;
  overlay.classList.add("is-open");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("forma-suite-open");
  formaSuiteRender(tab);
  document.querySelectorAll("#fs-nav [data-tab]").forEach(button => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
}

function formaSuiteClose() {
  const overlay = document.getElementById("forma-suite-overlay");
  if (!overlay) return;
  overlay.classList.remove("is-open");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("forma-suite-open");
}

function formaSuiteCollectForm(form, fields) {
  const values = {};
  for (const [name, min, max] of fields) {
    values[name] = formaSuiteNumber(form.elements.namedItem(name)?.value, min, max);
  }
  return values;
}

function formaSuiteSaveMeasurement(form) {
  const values = formaSuiteCollectForm(form, [
    ["weightKg", 1, 500], ["waistCm", 20, 250], ["hipCm", 20, 250],
    ["chestCm", 20, 250], ["thighCm", 10, 150], ["armCm", 10, 100]
  ]);
  const useful = Object.values(values).some(value => value !== null);
  if (!useful) { alert("Introduce al menos una medida válida."); return; }
  const data = formaSuiteRead();
  data.measurements.push({ date: form.elements.date.value, source: "Manual", ...values });
  formaSuiteWrite(data);
  formaSuiteRender("progreso");
}

function formaSuiteSaveWorkout(form) {
  const minutes = formaSuiteNumber(form.elements.minutes.value, 1, 600);
  if (!minutes) { alert("Introduce una duración válida."); return; }
  const data = formaSuiteRead();
  data.workouts.push({
    date: form.elements.date.value, type: form.elements.type.value,
    minutes, exercise: form.elements.exercise.value.trim().slice(0, 80),
    sets: formaSuiteNumber(form.elements.sets.value, 0, 100),
    reps: formaSuiteNumber(form.elements.reps.value, 0, 500),
    loadKg: formaSuiteNumber(form.elements.loadKg.value, 0, 1000),
    effort: formaSuiteNumber(form.elements.effort.value, 1, 10)
  });
  formaSuiteWrite(data);
  formaSuiteRender("entrenamiento");
}

function formaSuiteSaveMeal(form) {
  try {
    const values = new FormData(form);
    const entry = validateFoodEntry({
      name: values.get("name"), mealType: values.get("mealType"), date: values.get("date"),
      calories: values.get("calories"), protein: values.get("protein"),
      carbs: values.get("carbs"), fat: values.get("fat")
    });
    state.foodEntries = Array.isArray(state.foodEntries) ? state.foodEntries : [];
    state.foodEntries.push({ ...entry, id: idForEntry(), createdAt: new Date().toISOString() });
    saveState();
    form.reset();
    form.elements.date.value = formaSuiteToday();
    renderDiary();
    formaSuiteRender("nutricion");
  } catch (error) {
    alert(error?.message || "No se pudo guardar la comida.");
  }
}

function formaSuiteSaveHabit(form) {
  const values = formaSuiteCollectForm(form, [["sleepHours", 0, 24], ["waterGlasses", 0, 40]]);
  if (Object.values(values).every(value => value === null)) { alert("Introduce las horas de sueño o los vasos de agua."); return; }
  const data = formaSuiteRead();
  data.habits.push({ date: form.elements.date.value, ...values });
  formaSuiteWrite(data);
  formaSuiteRender("revision");
}

function formaSuiteBuildCoachContext() {
  const data = formaSuiteRead();
  const profile = state?.profile;
  const adult = Number(profile?.age) >= 18;
  const latest = formaSuiteScanHistory().slice(-1)[0] || null;
  return adult ? {
    profile: profile ? {
      age: profile.age, heightCm: profile.height, weightKg: profile.weight,
      goal: profile.goal, activity: profile.activity, experience: profile.experience,
      sessionsPerWeek: profile.sessions, equipment: profile.equipment
    } : null,
    latestScan: latest ? {
      source: latest.source, bodyFatPercent: latest.bodyFatPercent,
      bodyFatInterval: [latest.bodyFatLow, latest.bodyFatHigh],
      waistCm: latest.waistCm, date: latest.date
    } : null,
    progress: {
      manualMeasurements: data.measurements.slice(-5),
      workoutsLast7Days: formaSuiteRecent(data.workouts).length,
      exerciseEntriesLast7Days: formaSuiteRecent(Array.isArray(state.exerciseEntries) ? state.exerciseEntries : []).length,
      mealsLast7Days: formaSuiteRecent(formaSuiteAllMeals()).length,
      habitsLast7Days: formaSuiteRecent(data.habits).length
    }
  } : { profile: null, latestScan: null, progress: null };
}

async function formaSuiteAskCoach(message, includeContext, output) {
  if (!output) return;
  output.textContent = "Conectando con FORMA Coach…";
  try {
    const reply = await askFormaCoach({
      message: String(message || "").slice(0, 500),
      context: includeContext ? formaSuiteBuildCoachContext() : { profile: null, latestScan: null, progress: null }
    });
    output.textContent = reply;
  } catch (error) {
    output.textContent = "No se pudo completar la consulta. Comprueba la conexión e inténtalo de nuevo. " + String(error?.message || "");
  }
}

function formaSuitePhotoInput(kind, file) {
  if (!file) return;
  if (!String(file.type || "").startsWith("image/") || file.size > 15 * 1024 * 1024) {
    alert("Selecciona una imagen de hasta 15 MB.");
    return;
  }
  if (formaSuitePhotoUrls[kind]) URL.revokeObjectURL(formaSuitePhotoUrls[kind]);
  formaSuitePhotoUrls[kind] = URL.createObjectURL(file);
  formaSuiteUpdatePhotoStage();
}

function formaSuiteUpdatePhotoStage() {
  const stage = document.getElementById("fs-photo-stage");
  if (!stage) return;
  if (!formaSuitePhotoUrls.before || !formaSuitePhotoUrls.after) {
    stage.innerHTML = "<span>Selecciona dos imágenes para compararlas</span>";
    return;
  }
  stage.innerHTML = '<img class="fs-photo-base" alt="Fotografía anterior" src="' + formaSuitePhotoUrls.before + '">' +
    '<img id="fs-photo-overlay" class="fs-photo-overlay" alt="Fotografía actual" src="' + formaSuitePhotoUrls.after + '">';
  const range = document.getElementById("fs-photo-range");
  const overlay = document.getElementById("fs-photo-overlay");
  const apply = () => { if (overlay && range) overlay.style.clipPath = "inset(0 " + (100 - Number(range.value)) + "% 0 0)"; };
  range?.addEventListener("input", apply);
  apply();
}

function formaSuiteClearPhotos() {
  for (const key of ["before", "after"]) {
    if (formaSuitePhotoUrls[key]) URL.revokeObjectURL(formaSuitePhotoUrls[key]);
    formaSuitePhotoUrls[key] = null;
  }
  const before = document.getElementById("fs-photo-before");
  const after = document.getElementById("fs-photo-after");
  if (before) before.value = "";
  if (after) after.value = "";
  formaSuiteUpdatePhotoStage();
}

function formaSuiteExport() {
  const payload = {
    product: "FORMA",
    exportedAt: new Date().toISOString(),
    privacy: "Exportación local; no contiene fotografías.",
    suite: formaSuiteRead(),
    appData: {
      profile: state?.profile || null,
      completedWorkouts: state?.completedWorkouts || [],
      foodEntries: state?.foodEntries || [],
      exerciseEntries: state?.exerciseEntries || [],
      activityEntries: state?.activityEntries || []
    },
    scanHistory: formaSuiteScanHistory()
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "forma-respaldo-" + formaSuiteToday() + ".json";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formaSuiteDeleteScans() {
  if (!confirm("¿Borrar el historial numérico del escáner guardado en este dispositivo? Esta acción no se puede deshacer.")) return;
  localStorage.removeItem("forma.scan-history.v1");
  formaSuiteRender("privacidad");
  if (typeof renderFormaScanHistory === "function") renderFormaScanHistory();
}

function formaSuiteWeeklyReview() {
  const consent = document.getElementById("fs-review-consent")?.checked === true;
  const data = formaSuiteRead();
  const summary = formaSuiteRecent(data.workouts).length + " entrenamientos, " +
    formaSuiteRecent(data.meals).length + " comidas y " + formaSuiteRecent(data.habits).length + " registros de hábitos en los últimos siete días.";
  const message = consent
    ? "Revisa este resumen semanal y dame recomendaciones realistas para la próxima semana. Distingue datos reales de registros incompletos; no propongas cambios extremos."
    : "Explícame cómo hacer una revisión semanal equilibrada de entrenamiento, alimentación, descanso y hábitos sin usar datos personales.";
  const output = document.getElementById("fs-review-output");
  if (output && consent) output.textContent = "Resumen que autorizaste: " + summary + " Preparando análisis…";
  void formaSuiteAskCoach(message, consent, output);
}

function formaSuiteInit() {
  if (document.getElementById("forma-suite-overlay")) return;
  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.id = "forma-suite-launcher";
  launcher.className = "fs-launcher";
  launcher.textContent = "Mi progreso";
  launcher.setAttribute("aria-label", "Abrir el Centro FORMA");

  const overlay = document.createElement("div");
  overlay.id = "forma-suite-overlay";
  overlay.className = "fs-overlay";
  overlay.setAttribute("aria-hidden", "true");
  overlay.innerHTML =
    '<section class="fs-shell" role="dialog" aria-modal="true" aria-labelledby="fs-title">' +
      '<header class="fs-header"><div><span class="fs-kicker">FORMA · PERSONAL STUDIO</span><h2 id="fs-title">Tu progreso, en contexto</h2><p>Datos propios, estimaciones identificadas y hábitos reales.</p></div>' +
      '<button type="button" class="fs-close" aria-label="Cerrar">×</button></header>' +
      '<nav id="fs-nav" class="fs-nav" aria-label="Centro FORMA">' +
        '<button data-tab="progreso" class="is-active">Progreso</button><button data-tab="entrenamiento">Entreno</button>' +
        '<button data-tab="nutricion">Nutrición</button><button data-tab="revision">Semana</button>' +
        '<button data-tab="coach">Coach IA</button><button data-tab="privacidad">Privacidad</button>' +
      '</nav><main id="fs-content" class="fs-content"></main>' +
    '</section>';
  document.body.append(launcher, overlay);

  launcher.addEventListener("click", () => formaSuiteOpen("progreso"));
  overlay.querySelector(".fs-close").addEventListener("click", formaSuiteClose);
  overlay.addEventListener("click", event => { if (event.target === overlay) formaSuiteClose(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") formaSuiteClose(); });
  overlay.querySelector("#fs-nav").addEventListener("click", event => {
    const button = event.target.closest("[data-tab]");
    if (!button) return;
    formaSuiteOpen(button.dataset.tab);
  });

  const content = overlay.querySelector("#fs-content");
  content.addEventListener("submit", event => {
    event.preventDefault();
    if (event.target.id === "fs-measure-form") formaSuiteSaveMeasurement(event.target);
    if (event.target.id === "fs-workout-form") formaSuiteSaveWorkout(event.target);
    if (event.target.id === "fs-meal-form") formaSuiteSaveMeal(event.target);
    if (event.target.id === "fs-habit-form") formaSuiteSaveHabit(event.target);
    if (event.target.id === "fs-coach-form") {
      const message = event.target.elements.message.value.trim();
      if (message) void formaSuiteAskCoach(message, document.getElementById("fs-coach-consent")?.checked === true, document.getElementById("fs-coach-output"));
    }
  });
  content.addEventListener("change", event => {
    if (event.target.id === "fs-photo-before") formaSuitePhotoInput("before", event.target.files?.[0]);
    if (event.target.id === "fs-photo-after") formaSuitePhotoInput("after", event.target.files?.[0]);
  });
  content.addEventListener("input", event => {
    if (event.target.id === "fs-photo-range") {
      const overlayImage = document.getElementById("fs-photo-overlay");
      if (overlayImage) overlayImage.style.clipPath = "inset(0 " + (100 - Number(event.target.value)) + "% 0 0)";
    }
  });
  content.addEventListener("click", event => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action) return;
    if (action === "clear-photos") formaSuiteClearPhotos();
    if (action === "export") formaSuiteExport();
    if (action === "delete-suite") {
      if (confirm("¿Borrar todos los registros creados en el Centro FORMA? El perfil de la aplicación no se modificará.")) {
        localStorage.removeItem(FORMA_SUITE_STORAGE_KEY);
        formaSuiteRender("privacidad");
      }
    }
    if (action === "delete-scans") formaSuiteDeleteScans();
    if (action === "delete-diary") formaSuiteDeleteDiary();
    if (action === "weekly-review") formaSuiteWeeklyReview();
  });

  // Enrich numeric scan history with transparent provenance/quality metadata.
  if (typeof saveFormaScanHistory === "function") {
    const originalSave = saveFormaScanHistory;
    saveFormaScanHistory = function(result) {
      originalSave(result);
      try {
        const history = formaSuiteScanHistory();
        const date = String(result?.createdAt || "");
        const entry = history.find(item => item.date === date);
        if (entry) {
          const issues = ["front", "side"].flatMap(key => result?.captureQuality?.[key]?.issues || []);
          entry.quality = issues.length ? "limited" : (result?.composition ? "estimated" : "visual-or-partial");
          entry.qualityWarnings = issues.length;
          entry.source = String(result?.analysisProvider || "Gemini");
          localStorage.setItem("forma.scan-history.v1", JSON.stringify(history.slice(-30)));
        }
      } catch (error) { console.warn("FORMA scan metadata could not be saved:", error); }
    };
  }

  // Add a readable confidence/provenance panel without changing the scanner's raw estimates.
  if (typeof renderScanResult === "function") {
    const originalRender = renderScanResult;
    renderScanResult = function() {
      originalRender();
      const root = document.getElementById("scan-result");
      if (!root) return;
      root.querySelector("#forma-capture-insight")?.remove();
      const result = formaSuiteLastScan();
      if (!result) return;
      const summary = formaSuiteCaptureSummary(result);
      const card = document.createElement("section");
      card.id = "forma-capture-insight";
      card.className = "fs-scan-insight";
      card.innerHTML = '<strong>' + formaSuiteEscape(summary.title) + '</strong><p>' + formaSuiteEscape(summary.detail) + '</p>' +
        '<small>Fuente y nivel de evidencia visibles para que no confundas una observación con una medición.</small>';
      root.append(card);
    };
  }
  formaSuiteRender("progreso");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", formaSuiteInit, { once: true });
} else {
  formaSuiteInit();
}
/* ====================== END FORMA SUITE 1.8 ====================== */
"""

css += r"""

/* FORMA 1.8 · Personal Studio */
.fs-launcher {
  position:fixed; z-index:999; right:16px; bottom:calc(18px + env(safe-area-inset-bottom));
  border:0; border-radius:999px; padding:13px 18px; min-height:48px;
  background:var(--green,#244d3e); color:#fff; font-weight:800; font-size:13px;
  box-shadow:0 10px 28px rgba(0,0,0,.2); cursor:pointer;
}
.fs-overlay {
  position:fixed; inset:0; z-index:1000; display:none; align-items:stretch; justify-content:center;
  background:rgba(5,12,10,.72); padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom);
}
.fs-overlay.is-open { display:flex; }
body.forma-suite-open { overflow:hidden; }
.fs-shell {
  width:min(100%,980px); height:100%; display:flex; flex-direction:column; overflow:hidden;
  background:var(--bg,#f4f7f5); color:var(--text,#17251e);
}
.fs-header {
  display:flex; align-items:flex-start; justify-content:space-between; gap:18px;
  padding:22px 22px 15px; background:var(--panel,#fff); border-bottom:1px solid var(--line,#dce6df);
}
.fs-header h2 { margin:5px 0 4px; font-size:24px; letter-spacing:-.04em; }
.fs-header p { margin:0; color:var(--muted,#64756c); font-size:12px; line-height:1.45; }
.fs-kicker { font-size:10px; letter-spacing:.13em; font-weight:850; color:var(--green,#427a5b); }
.fs-close {
  width:40px; height:40px; border:1px solid var(--line,#dce6df); border-radius:13px;
  background:var(--panel,#fff); color:var(--text,#17251e); font-size:25px; cursor:pointer;
}
.fs-nav { display:flex; gap:7px; padding:12px 18px; overflow-x:auto; background:var(--panel,#fff); border-bottom:1px solid var(--line,#dce6df); }
.fs-nav button {
  flex:0 0 auto; border:1px solid var(--line,#dce6df); border-radius:999px; padding:9px 13px;
  background:transparent; color:var(--muted,#64756c); font-size:12px; font-weight:750; cursor:pointer;
}
.fs-nav button.is-active { background:var(--green,#427a5b); border-color:var(--green,#427a5b); color:#fff; }
.fs-content { flex:1; overflow:auto; overscroll-behavior:contain; padding:16px; display:grid; align-content:start; gap:14px; }
.fs-card,.fs-stat {
  min-width:0; padding:17px; border:1px solid var(--line,#dce6df); border-radius:18px;
  background:var(--panel,#fff); box-shadow:0 8px 24px rgba(20,40,30,.045);
}
.fs-card h3 { margin:6px 0 8px; font-size:18px; letter-spacing:-.03em; }
.fs-card p { color:var(--muted,#64756c); font-size:12px; line-height:1.55; }
.fs-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.fs-stat { display:flex; flex-direction:column; gap:5px; }
.fs-stat span { color:var(--muted,#64756c); font-size:11px; }
.fs-stat strong { font-size:21px; letter-spacing:-.03em; overflow-wrap:anywhere; }
.fs-stat small { color:var(--muted,#64756c); font-size:10px; line-height:1.45; }
.fs-wide { grid-column:1/-1; }
.fs-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:11px; margin-top:14px; }
.fs-form label { min-width:0; display:grid; gap:6px; color:var(--muted,#64756c); font-size:11px; font-weight:700; }
.fs-form input,.fs-form select,.fs-form textarea {
  width:100%; min-width:0; box-sizing:border-box; border:1px solid var(--line,#dce6df);
  border-radius:11px; padding:11px 12px; background:var(--bg,#f8faf8); color:var(--text,#17251e);
  font:inherit; font-size:13px;
}
.fs-form input:focus,.fs-form select:focus,.fs-form textarea:focus { outline:2px solid var(--green,#427a5b); outline-offset:1px; }
.fs-primary,.fs-secondary,.fs-danger {
  min-height:43px; border:0; border-radius:12px; padding:11px 14px; font-weight:800; font-size:12px; cursor:pointer;
}
.fs-primary { grid-column:1/-1; background:var(--green,#427a5b); color:#fff; }
.fs-secondary { background:var(--bg,#eef4ef); color:var(--text,#17251e); border:1px solid var(--line,#dce6df); }
.fs-danger { background:#fff0ee; color:#a23428; border:1px solid #f0d1cc; }
.fs-history-list { display:grid; margin-top:8px; }
.fs-history-row { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; padding:11px 0; border-top:1px solid var(--line,#dce6df); }
.fs-history-row span { flex:0 0 82px; color:var(--muted,#64756c); font-size:11px; }
.fs-history-row strong { display:grid; gap:3px; color:var(--text,#17251e); font-size:12px; text-align:right; }
.fs-history-row small { color:var(--muted,#64756c); font-size:10px; font-weight:500; }
.fs-chart { display:block; width:100%; max-height:80px; margin:10px 0; }
.fs-muted { color:var(--muted,#64756c); font-size:11px !important; line-height:1.5; }
.fs-consent { display:flex !important; grid-column:1/-1; flex-direction:row !important; align-items:flex-start; gap:9px !important; padding:12px; border:1px solid var(--line,#dce6df); border-radius:12px; }
.fs-consent input { width:18px; height:18px; flex:0 0 18px; margin:0; accent-color:var(--green,#427a5b); }
.fs-consent span { font-size:11px; line-height:1.5; color:var(--muted,#64756c); }
.fs-ai-output { margin-top:12px; color:var(--text,#17251e); white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; line-height:1.65; }
.fs-one-col { grid-template-columns:1fr; }
.fs-one-col label { grid-column:1/-1; }
.fs-privacy-row { display:grid; gap:7px; padding:13px 0; border-top:1px solid var(--line,#dce6df); }
.fs-privacy-row strong { font-size:13px; }
.fs-privacy-row span { color:var(--muted,#64756c); font-size:11px; line-height:1.5; }
.fs-privacy-row button { justify-self:start; }
.fs-photo-stage { position:relative; width:100%; min-height:180px; aspect-ratio:4/3; overflow:hidden; margin-top:14px; border-radius:14px; background:var(--bg,#eef2ef); display:grid; place-items:center; color:var(--muted,#64756c); font-size:12px; }
.fs-photo-stage img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
.fs-photo-base { z-index:1; }
.fs-photo-overlay { z-index:2; }
.fs-range-label { display:grid; gap:6px; margin:12px 0; color:var(--muted,#64756c); font-size:11px; }
.fs-range-label input { accent-color:var(--green,#427a5b); }
.fs-photo-pickers { margin-bottom:10px; }
.fs-scan-insight { margin-top:14px; padding:14px 15px; border:1px solid var(--line,#dce6df); border-radius:15px; background:var(--panel,#fff); }
.fs-scan-insight strong { font-size:13px; }
.fs-scan-insight p { margin:6px 0; color:var(--muted,#64756c); font-size:11px; line-height:1.5; }
.fs-scan-insight small { color:var(--muted,#64756c); font-size:10px; line-height:1.4; }
@media(min-width:760px) {
  .fs-overlay { padding:28px; }
  .fs-shell { max-height:calc(100% - 0px); border-radius:24px; box-shadow:0 30px 100px rgba(0,0,0,.35); }
  .fs-content { padding:22px; grid-template-columns:repeat(2,minmax(0,1fr)); align-content:start; }
  .fs-content > section,.fs-content > .fs-grid { align-self:start; }
  .fs-wide { grid-column:1/-1; }
}
@media(max-width:430px) {
  .fs-header { padding:18px 16px 13px; }
  .fs-header h2 { font-size:21px; }
  .fs-content { padding:12px; gap:11px; }
  .fs-grid { gap:9px; }
  .fs-card,.fs-stat { padding:14px; }
  .fs-form { grid-template-columns:1fr; }
  .fs-form label,.fs-primary { grid-column:1/-1; }
  .fs-history-row { flex-direction:column; gap:5px; }
  .fs-history-row strong { text-align:left; }
  .fs-launcher { right:12px; bottom:calc(12px + env(safe-area-inset-bottom)); }
}
@media(prefers-reduced-motion:reduce) {
  .fs-overlay * { scroll-behavior:auto !important; transition-duration:.01ms !important; animation-duration:.01ms !important; }
}
"""

app_path.write_text(app, encoding="utf-8")
css_path.write_text(css, encoding="utf-8")

required = [
    "FORMA SUITE 1.8", "formaSuiteSaveMeasurement", "formaSuiteSaveWorkout",
    "formaSuiteSaveMeal", "formaSuiteWeeklyReview", "formaSuiteExport",
    "formaSuiteDeleteScans", "formaSuiteCaptureSummary", "formaSuitePhotoInput"
]
for token in required:
    if token not in app:
        raise SystemExit(f"FORMA Suite verification failed: {token}")
if "fs-launcher" not in css or "fs-photo-stage" not in css:
    raise SystemExit("FORMA Suite styles were not written.")
print("FORMA 1.8 Personal Studio added: manual progress, temporary photo comparison, workouts, nutrition, weekly review, Coach and privacy tools.")
