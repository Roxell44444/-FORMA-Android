import { buildMask, qualityCheck } from "../../vendor/bodycomp/mask.js";
import { loadModels, analyse } from "../../vendor/bodycomp/pipeline.js";

const VISION_BASE = new URL("../../vendor/mediapipe/", import.meta.url).href;
const SEGMENTER_MODEL = new URL("../../models/bodycomp/selfie_multiclass.tflite", import.meta.url).href;
const BODYCOMP_MODELS = "https://cdn.jsdelivr.net/gh/rishabcv-eng/bodycomp@9b4f73469f9b099809ddb19a6e23cb346072e4f4/app/public/models";
const PERSON_CLASSES = [1, 2, 3, 4, 5];
const MAX_EDGE = 900;

let visionPromise;
let segmenterPromise;
let modelsPromise;

async function vision() {
  if (!visionPromise) {
    visionPromise = import("../../vendor/mediapipe/vision_bundle.js").then(async lib => {
      const fileset = await lib.FilesetResolver.forVisionTasks(new URL("wasm/", VISION_BASE).href);
      return { lib, fileset };
    }).catch(error => {
      visionPromise = null;
      throw error;
    });
  }
  return visionPromise;
}

async function segmenter() {
  if (!segmenterPromise) {
    segmenterPromise = vision().then(async ({ lib, fileset }) => {
      const instance = await lib.ImageSegmenter.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: SEGMENTER_MODEL },
        runningMode: "IMAGE",
        outputCategoryMask: false,
        outputConfidenceMasks: true
      });
      return instance;
    }).catch(error => {
      segmenterPromise = null;
      throw error;
    });
  }
  return segmenterPromise;
}

async function models() {
  if (!modelsPromise) {
    modelsPromise = loadModels(BODYCOMP_MODELS).catch(error => {
      modelsPromise = null;
      throw error;
    });
  }
  return modelsPromise;
}

function makeCanvas(image) {
  if (!image || !image.complete || !image.naturalWidth || !image.naturalHeight) {
    throw new Error("No se pudo abrir una de las fotografías.");
  }
  const scale = Math.min(1, MAX_EDGE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("No se pudo preparar la fotografía.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas;
}

async function makeSilhouette(image, landmarks, engine) {
  const canvas = makeCanvas(image);
  const width = canvas.width;
  const height = canvas.height;
  const result = engine.segment(canvas);
  try {
    const confidence = new Float32Array(width * height);
    for (const classIndex of PERSON_CLASSES) {
      const classMask = result.confidenceMasks?.[classIndex];
      if (!classMask) continue;
      const values = classMask.getAsFloat32Array();
      for (let i = 0; i < confidence.length; i++) confidence[i] += values[i];
    }
    const mask = buildMask(confidence, width, height);
    // Quality is reported to the user, not used as a hard stop. We still run
    // the model on imperfect silhouettes and label the result as limited.
    const quality = qualityCheck(mask, width, height, landmarks);
    return { mask, width, height, quality };
  } finally {
    result.close?.();
  }
}

/**
 * BodyComp's own segmentation, mask cleanup and capture gates are retained.
 * FORMA's separate pose detector is used only to provide the landmarks needed
 * by BodyComp's quality checks; its segmentation mask is never substituted.
 */
export async function analyseBodyCompPhotos(frontImage, sideImage, profile, frontLandmarks, sideLandmarks) {
  if (!profile || profile.age < 18 || profile.age > 59) {
    throw new Error("Este análisis fotográfico solo está disponible para edades de 18 a 59 años.");
  }
  if (!["male", "female"].includes(profile.equation)) {
    throw new Error("El análisis fotográfico necesita una referencia compatible seleccionada en el perfil.");
  }
  const heightCm = Number(profile.height);
  const weightKg = Number(profile.weight);
  if (!Number.isFinite(heightCm) || !Number.isFinite(weightKg) ||
      heightCm < 130 || heightCm > 230 || weightKg <= 0) {
    throw new Error("Revisa tu estatura y peso antes de repetir el análisis.");
  }
  // Pose landmarks improve quality diagnostics, but are not required to attempt
  // segmentation and silhouette inference from the two supplied photographs.

  const [engine] = await Promise.all([segmenter(), models()]);
  const [front, side] = await Promise.all([
    makeSilhouette(frontImage, frontLandmarks, engine),
    makeSilhouette(sideImage, sideLandmarks, engine)
  ]);
  const output = analyse(
    { mask: front.mask, width: front.width, height: front.height },
    { mask: side.mask, width: side.width, height: side.height },
    {
      heightCm,
      weightKg,
      age: Number(profile.age),
      sex: profile.equation === "male" ? 1 : 0
    }
  );

  const bodyFat = output.composition?.bodyfat_pct;
  const appendicularLean = output.composition?.alm_kg;
  if (!Number.isFinite(bodyFat?.estimate) || !Number.isFinite(bodyFat?.low) ||
      !Number.isFinite(bodyFat?.high) || !Number.isFinite(appendicularLean?.estimate)) {
    throw new Error("El análisis no produjo resultados completos y coherentes.");
  }
  if (bodyFat.low > bodyFat.high || bodyFat.estimate < bodyFat.low || bodyFat.estimate > bodyFat.high) {
    throw new Error("El resultado del análisis no superó las comprobaciones de coherencia.");
  }

  return {
    output,
    quality: {
      front: { usable: front.quality.usable, issues: front.quality.issues, metrics: front.quality.metrics },
      side: { usable: side.quality.usable, issues: side.quality.issues, metrics: side.quality.metrics }
    },
    mae: bodyFat.mae,
    coverage80: bodyFat.coverage80
  };
}
