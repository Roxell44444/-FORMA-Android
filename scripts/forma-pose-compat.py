#!/usr/bin/env python3
"""Harden MediaPipe Pose Landmarker startup across Android WebView devices."""
from pathlib import Path
import re

path = Path("FORMA-1.1.0/src/scanner/pose.js")
if not path.is_file():
    raise SystemExit(f"Missing generated scanner source: {path}")
source = path.read_text(encoding="utf-8")
# MediaPipe appends "/vision_wasm_internal.js" to this base path itself.
# Keep the base URL without a trailing slash to avoid a double-slash URL on Android WebView.
old_wasm_url = "const WASM_URL = new URL('wasm/', VISION_BASE).href;"
new_wasm_url = "const WASM_URL = new URL('wasm', VISION_BASE).href;"
if old_wasm_url not in source and new_wasm_url not in source:
    raise SystemExit("Could not find the expected MediaPipe WASM base URL.")
source = source.replace(old_wasm_url, new_wasm_url)

pattern = re.compile(
    r"export async function createPoseLandmarker\(\) \{.*?\n\}\n\nexport function resetPoseLandmarkerForTests",
    re.S,
)
replacement = r"""function describePoseError(error, depth = 0) {
  if (error == null) return 'error desconocido';
  if (depth > 3) return 'causa anidada';
  const parts = [];
  const add = (label, value) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      parts.push(label ? label + ': ' + String(value).slice(0, 240) : String(value).slice(0, 240));
    }
  };
  if (typeof error === 'string') return error.slice(0, 500);
  add('', error.name);
  add('', error.message);
  if (error.type) add('evento', error.type);
  if (error.filename) add('archivo', error.filename);
  if (Number.isFinite(error.lineno) && error.lineno > 0) add('línea', error.lineno);
  if (Number.isFinite(error.colno) && error.colno > 0) add('columna', error.colno);
  if (error.error && error.error !== error) add('error interno', describePoseError(error.error, depth + 1));
  const target = error.target || error.currentTarget;
  if (target) {
    add('elemento', target.tagName || target.nodeName || target.constructor?.name);
    add('recurso', target.currentSrc || target.src || target.href);
    if (target.error) add('error del recurso', describePoseError(target.error, depth + 1));
  }
  if (error.cause && error.cause !== error) add('causa', describePoseError(error.cause, depth + 1));
  if (error.stack && !error.message) add('pila', String(error.stack).split('\\n').slice(0, 3).join(' '));
  return (parts.join(' — ') || String(error)).slice(0, 900);
}

export async function createPoseLandmarker() {
  if (!landmarkerPromise) {
    landmarkerPromise = withTimeout((async () => {
      let FilesetResolver, PoseLandmarker;
      try {
        ({ FilesetResolver, PoseLandmarker } = await import(BUNDLE_URL));
      } catch (error) {
        const wrapped = new Error('No se pudo cargar el módulo local de MediaPipe. ' + describePoseError(error));\n        wrapped.cause = error;\n        throw wrapped;
      }

      let vision;
      try {
        vision = await FilesetResolver.forVisionTasks(WASM_URL);
      } catch (error) {
        const wrapped = new Error('No se pudieron inicializar los archivos WASM locales de MediaPipe. ' + describePoseError(error));\n        wrapped.cause = error;\n        throw wrapped;
      }

      const attempts = [
        { label: 'CPU', delegate: 'CPU' },
        { label: 'automático', delegate: null },
        { label: 'GPU', delegate: 'GPU' }
      ];
      const failures = [];
      for (const attempt of attempts) {
        try {
          const baseOptions = { modelAssetPath: POSE_MODEL_URL };
          if (attempt.delegate) baseOptions.delegate = attempt.delegate;
          return await PoseLandmarker.createFromOptions(vision, {
            runningMode: 'IMAGE',
            numPoses: 1,
            minPoseDetectionConfidence: 0.55,
            minPosePresenceConfidence: 0.55,
            minTrackingConfidence: 0.5,
            outputSegmentationMasks: true,
            baseOptions
          });
        } catch (error) {
          failures.push(attempt.label + ': ' + describePoseError(error));
        }
      }
      const error = new Error(
        'MediaPipe no pudo crear el detector con ninguno de los modos compatibles. ' +
        failures.join(' | ') +
        ' Comprueba que la app tenga espacio libre y que sus recursos locales estén completos.'
      );
      error.cause = new Error(failures.join(' | '));
      throw error;
    })(), 90000).catch(error => {
      landmarkerPromise = null;
      throw error;
    });
  }
  return landmarkerPromise;
}

export function resetPoseLandmarkerForTests"""
source, count = pattern.subn(replacement, source, count=1)
if count != 1:
    raise SystemExit("Could not locate the original createPoseLandmarker block; no files changed.")
if "MediaPipe no pudo crear el detector con ninguno de los modos compatibles." not in source:
    raise SystemExit("Pose compatibility patch verification failed.")
path.write_text(source, encoding="utf-8")
print("Patched MediaPipe startup: CPU, automatic and GPU delegates with actionable diagnostics.")
