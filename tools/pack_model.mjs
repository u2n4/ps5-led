#!/usr/bin/env node
/**
 * pack_model.mjs - one-shot: turn the CC BY source GLB into the file we ship.
 *
 * Run once; the output is committed. Measured on this repo with
 * @gltf-transform/cli 4.5.0:
 *   source                          6,658 KB
 *   webp  (textures PNG -> WebP)    4,306 KB
 *   meshopt (geometry)              1,178 KB   <- shipped
 *
 * ORDER MATTERS. Running `webp` after `meshopt` decodes the mesh compression
 * ("Decoded EXT_meshopt_compression. Further compression will be lossy.") and
 * lands at 2,164 KB. Textures first, geometry second.
 *
 * The result requires EXT_meshopt_compression, EXT_texture_webp and
 * KHR_mesh_quantization, all handled by three.js 0.185.1's GLTFLoader.
 *
 * Usage: node tools/pack_model.mjs --in <source.glb> --out web/assets/dualsense.glb
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).flatMap((a, i, arr) =>
  a.startsWith('--') ? [[a.slice(2), arr[i + 1]]] : []));
const IN = args.in;
const OUT = args.out ?? 'web/assets/dualsense.glb';
if (!IN || !existsSync(IN)) { console.error('need --in <source.glb>'); process.exit(1); }

const work = mkdtempSync(join(tmpdir(), 'packmodel-'));
const webp = join(work, 'webp.glb');

function transform(command, input, output) {
  // shell:true because npx is a .cmd shim on Windows.
  execFileSync('npx', ['--yes', '@gltf-transform/cli@4.5.0', command, input, output],
               { stdio: 'inherit', shell: true });
}

const kb = (path) => (readFileSync(path).length / 1024).toFixed(0);

console.log(`source ${kb(IN)} KB`);
console.log('1/2 textures -> WebP');
transform('webp', IN, webp);
console.log(`   ${kb(webp)} KB`);

console.log('2/2 geometry -> meshopt');
mkdirSync(dirname(OUT), { recursive: true });
transform('meshopt', webp, OUT);
console.log(`wrote ${OUT}: ${kb(OUT)} KB`);

// Belt and braces: the loader needs every extension the file requires.
const glb = readFileSync(OUT);
const jsonLength = glb.readUInt32LE(12);
const gltf = JSON.parse(glb.subarray(20, 20 + jsonLength).toString('utf8'));
console.log(`extensionsRequired: ${(gltf.extensionsRequired ?? []).join(', ')}`);
const names = (gltf.nodes ?? []).map((n) => n.name);
for (const wanted of ['Object_18', 'Object_47']) {
  if (!names.includes(wanted)) console.warn(`WARNING: lightbar candidate ${wanted} did not survive packing`);
}
console.log('Verify it loads in the app before committing.');
