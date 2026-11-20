import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { inflateSync } from "node:zlib";
import { loadModels, analyse, analyseMany } from "../FORMA-1.1.0/vendor/bodycomp/pipeline.js";

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : (pb <= pc ? b : c);
}

function decodeBinaryMask(png) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(png.subarray(0, 8).compare(signature), 0, "fixture must be a PNG");
  let width = 0, height = 0, bitDepth = 0, colorType = 0;
  const compressed = [];
  for (let offset = 8; offset < png.length;) {
    const length = png.readUInt32BE(offset); offset += 4;
    const type = png.toString("ascii", offset, offset + 4); offset += 4;
    const data = png.subarray(offset, offset + length); offset += length + 4;
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    } else if (type === "IDAT") compressed.push(data);
    else if (type === "IEND") break;
  }
  assert.equal(bitDepth, 8, "8-bit fixture PNG required");
  const channelsByType = { 0: 1, 2: 3, 4: 2, 6: 4 };
  const channels = channelsByType[colorType];
  assert.ok(channels, "fixture must use grayscale, RGB, gray-alpha or RGBA PNG");
  const bpp = channels;
  const stride = width * bpp;
  const raw = inflateSync(Buffer.concat(compressed));
  const rows = new Uint8Array(height * stride);
  let source = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[source++];
    const rowOffset = y * stride;
    for (let x = 0; x < stride; x++) {
      const value = raw[source++];
      const left = x >= bpp ? rows[rowOffset + x - bpp] : 0;
      const above = y > 0 ? rows[rowOffset - stride + x] : 0;
      const upperLeft = y > 0 && x >= bpp ? rows[rowOffset - stride + x - bpp] : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      else if (filter === 2) predictor = above;
      else if (filter === 3) predictor = Math.floor((left + above) / 2);
      else if (filter === 4) predictor = paeth(left, above, upperLeft);
      else if (filter !== 0) throw new Error("Unsupported PNG filter " + filter);
      rows[rowOffset + x] = (value + predictor) & 255;
    }
  }
  const mask = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < mask.length; i++, p += bpp) mask[i] = rows[p] > 127 ? 1 : 0;
  return { mask, width, height };
}

function erode(mask, width, height) {
  const out = new Uint8Array(mask.length);
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      out[i] = mask[i] && mask[i - 1] && mask[i + 1] && mask[i - width] && mask[i + width] ? 1 : 0;
    }
  }
  return { mask: out, width, height };
}

const testDir = process.env.BODYCOMP_FIXTURE_DIR || "/tmp/forma-bodycomp-fixture";
const expected = JSON.parse(await readFile(testDir + "/expected.json", "utf8"));
const front = decodeBinaryMask(await readFile(testDir + "/front.png"));
const side = decodeBinaryMask(await readFile(testDir + "/side.png"));
const modelBase = "https://cdn.jsdelivr.net/gh/rishabcv-eng/bodycomp@9b4f73469f9b099809ddb19a6e23cb346072e4f4/app/public/models";

await loadModels(modelBase);
const profile = {
  heightCm: expected.height_cm,
  weightKg: expected.weight_kg,
  age: expected.age,
  sex: expected.sex
};
const started = performance.now();
const got = analyse(front, side, profile);
const elapsedMs = performance.now() - started;

for (const [key, value] of Object.entries(expected.measurements)) {
  assert.ok(Math.abs(got.measurements[key] - value) <= 0.05,
    key + " parity mismatch: " + got.measurements[key] + " vs " + value);
}
for (const [target, value] of Object.entries(expected.composition)) {
  for (const [field, expectedValue] of Object.entries(value)) {
    assert.ok(Math.abs(got.composition[target][field] - expectedValue) <= 0.05,
      target + "." + field + " parity mismatch: " + got.composition[target][field] + " vs " + expectedValue);
  }
}

const pairs = [
  { front, side },
  { front: erode(front.mask, front.width, front.height), side: erode(side.mask, side.width, side.height) },
  { front: erode(erode(front.mask, front.width, front.height).mask, front.width, front.height),
    side: erode(erode(side.mask, side.width, side.height).mask, side.width, side.height) }
];
const multi = analyseMany(pairs, profile);
assert.equal(multi.frameCount, 3);
assert.ok(Number.isFinite(multi.measurements.waist));
assert.ok(Math.abs(multi.measurements.waist - got.measurements.waist) < 3,
  "multi-frame median should not materially diverge from the reference fixture");

console.log("BodyComp pipeline parity: PASS");
console.log("Fixture subject:", expected.photo_id);
console.log("Measurements and composition fields match the published Python reference within 0.05.");
console.log("Multi-frame median: PASS");
console.log("Inference:", Math.round(elapsedMs), "ms");
console.log("Note: this validates the model pipeline on BodyM silhouettes; it is not an Android camera test.");
