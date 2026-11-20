#!/usr/bin/env python3
"""Harden MediaPipe Pose Landmarker startup across Android WebView devices."""
from pathlib import Path
import re

path = Path("FORMA-1.1.0/src/scanner/pose.js")
if not path.is_file():
    raise SystemExit(f"Missing generated scanner source: {path}")
source = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"export async function createPoseLandmarker\(\) \{.*?\n\}\n\nexport function resetPoseLandmarkerForTests",
    re.S,
)
replacement = r"""function describePoseError(error) {
  if (!error) return 'error desconocido';
  const parts = [];
  if (error.name) parts.push(error.name);
  if (error.message) parts.push(error.message);
  if (error.cause && error.cause !== error) {
    const cause = error.cause;
    parts.push(cause.name ? cause.name + ': ' + (cause.message || '') : String(cause));
  }
  return parts.join(' — ').slice(0, 500) || String(error).slice(0, 500);
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
