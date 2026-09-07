/** Offline extraction only. Runtime loads the checked-in gzip with Python stdlib.
 * Usage: node tools/extract_model.mjs [source.glb] [meshopt_decoder.module.js]
 * The defaults reuse the sibling feat/webview-rewrite checkout's original asset.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sibling = path.resolve(root, '../dualled-pro');
const source = process.argv[2] || path.join(sibling, 'web/assets/dualsense.glb');
const decoder = process.argv[3] || path.join(sibling, 'web/vendor/three/meshopt_decoder.module.js');
const { MeshoptDecoder } = await import(pathToFileURL(decoder));
await MeshoptDecoder.ready;
const glb = fs.readFileSync(source);
if (glb.readUInt32LE(0) !== 0x46546c67 || glb.readUInt32LE(4) !== 2) throw Error('Expected GLB v2');
const jsonLength = glb.readUInt32LE(12);
const gltf = JSON.parse(glb.subarray(20, 20 + jsonLength).toString('utf8'));
const binStart = 28 + jsonLength;
const binary = glb.subarray(binStart, binStart + glb.readUInt32LE(20 + jsonLength));
const views = gltf.bufferViews.map(view => {
  const compressed = view.extensions?.EXT_meshopt_compression;
  if (!compressed) return binary.subarray(view.byteOffset || 0, (view.byteOffset || 0) + view.byteLength);
  const result = new Uint8Array(compressed.count * compressed.byteStride);
  MeshoptDecoder.decodeGltfBuffer(result, compressed.count, compressed.byteStride,
    binary.subarray(compressed.byteOffset, compressed.byteOffset + compressed.byteLength),
    compressed.mode, compressed.filter || 'NONE');
  return result;
});
const types = {5120: ['getInt8', 1, 127], 5121: ['getUint8', 1, 255],
  5122: ['getInt16', 2, 32767], 5123: ['getUint16', 2, 65535],
  5125: ['getUint32', 4, 4294967295], 5126: ['getFloat32', 4, 1]};
function accessor(index) {
  const a = gltf.accessors[index];
  if (a.sparse) throw Error('Sparse accessor unsupported');
  const [getter, bytes, maximum] = types[a.componentType];
  const width = {SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4}[a.type];
  const data = views[a.bufferView];
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const stride = gltf.bufferViews[a.bufferView].byteStride || width * bytes;
  return Array.from({length: a.count * width}, (_, i) => {
    const value = view[getter]((a.byteOffset || 0) + Math.floor(i / width) * stride + i % width * bytes, true);
    return a.normalized ? Math.max(-1, value / maximum) : value;
  });
}
const identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1];
function multiply(a, b) {
  return Array.from({length: 16}, (_, i) => {
    const row = i % 4, column = Math.floor(i / 4);
    return [0,1,2,3].reduce((sum, k) => sum + a[k * 4 + row] * b[column * 4 + k], 0);
  });
}
function localMatrix(node) {
  if (node.matrix) return node.matrix;
  const [x,y,z,w] = node.rotation || [0,0,0,1];
  const [sx,sy,sz] = node.scale || [1,1,1];
  const [tx,ty,tz] = node.translation || [0,0,0];
  return [(1-2*(y*y+z*z))*sx, 2*(x*y+z*w)*sx, 2*(x*z-y*w)*sx, 0,
    2*(x*y-z*w)*sy, (1-2*(x*x+z*z))*sy, 2*(y*z+x*w)*sy, 0,
    2*(x*z+y*w)*sz, 2*(y*z-x*w)*sz, (1-2*(x*x+y*y))*sz, 0, tx,ty,tz,1];
}
function normalMatrix(m) {
  // Cofactor matrix = inverse transpose times determinant; normalize afterward.
  const a=m[0], b=m[4], c=m[8], d=m[1], e=m[5], f=m[9], g=m[2], h=m[6], i=m[10];
  const result = [e*i-f*h,c*h-b*i,b*f-c*e, f*g-d*i,a*i-c*g,c*d-a*f, d*h-e*g,b*g-a*h,a*e-b*d];
  const det = a*result[0] + b*result[3] + c*result[6];
  if (Math.abs(det) < 1e-20) throw Error('Degenerate transform');
  return result.map(v => v / det);
}
// Semantic mapping uses the original scene node names, not glTF mesh names.
// Two sticks are combined in Object_16, the touchpad is Object_51.
const groups = {
  shell: [5,10,42], line: [14,63], touch: [51], dpad: [55,57],
  bump: [59], btn: [16,22,30,49,53,66,68,70,72],
  glyph: [8,20,24,26,28,32,34,36,38,61,74,80,86,92,98],
  inset: [7,12,40,44,46,76,78,82,84,88,90,94,96],
  lightbar: [18,47],
};
const slots = Object.fromEntries(Object.entries(groups).flatMap(([slot, ids]) => ids.map(id => [`Object_${id}`, slot])));
// Pillow is an offline build helper only. The app uploads raw RGBA using stdlib.
const textureIndexes = [...new Set(gltf.materials.flatMap(m => {
  const index = m.pbrMetallicRoughness?.baseColorTexture?.index;
  return index === undefined ? [] : [index];
}))];
const textures = textureIndexes.map(index => {
  const texture = gltf.textures[index];
  const sourceIndex = texture.extensions?.EXT_texture_webp?.source ?? texture.source;
  const image = gltf.images[sourceIndex];
  const conversion = spawnSync(process.env.PYTHON || 'python', ['-c',
    'import sys,json,base64,io; from PIL import Image; im=Image.open(io.BytesIO(sys.stdin.buffer.read())).convert("RGBA"); print(json.dumps({"width":im.width,"height":im.height,"rgba":base64.b64encode(im.tobytes()).decode("ascii")}))'],
    {input: Buffer.from(views[image.bufferView]), maxBuffer:64*1024*1024});
  if (conversion.status !== 0) throw Error(`Offline WebP conversion needs Pillow: ${conversion.stderr}`);
  return JSON.parse(conversion.stdout.toString());
});
const meshes = [];
function visit(index, parent) {
  const node = gltf.nodes[index];
  const matrix = multiply(parent, localMatrix(node));
  if (node.mesh !== undefined) {
    const slot = slots[node.name];
    if (!slot) throw Error(`Unmapped node ${node.name}`);
    const normal = normalMatrix(matrix);
    for (const [primitiveIndex, p] of gltf.meshes[node.mesh].primitives.entries()) {
      if ((p.mode ?? 4) !== 4) throw Error('Expected triangles');
      const vertices = accessor(p.attributes.POSITION), normals = accessor(p.attributes.NORMAL);
      for (let k=0; k<vertices.length; k+=3) {
        const [x,y,z] = vertices.slice(k,k+3);
        for (let row=0; row<3; row++) vertices[k+row] = matrix[row]*x+matrix[row+4]*y+matrix[row+8]*z+matrix[row+12];
        const [nx,ny,nz] = normals.slice(k,k+3);
        const n = [0,1,2].map(row => normal[row]*nx+normal[row+3]*ny+normal[row+6]*nz);
        const length = Math.hypot(...n);
        for (let row=0; row<3; row++) normals[k+row] = n[row]/length;
      }
      const mesh = {name: node.name + (primitiveIndex ? `_${primitiveIndex}` : ''), slot,
        vertices, normals, indices: accessor(p.indices)};
      const material = gltf.materials[p.material];
      const textureIndex = material.pbrMetallicRoughness?.baseColorTexture?.index;
      if (textureIndex !== undefined) {
        mesh.uvs = accessor(p.attributes.TEXCOORD_0);
        mesh.texture = textureIndexes.indexOf(textureIndex);
        mesh.alphaMode = material.alphaMode || 'OPAQUE';
      }
      meshes.push(mesh);
    }
  }
  for (const child of node.children || []) visit(child, matrix);
}
for (const index of gltf.scenes[gltf.scene || 0].nodes) visit(index, identity);
const bounds = [[Infinity,Infinity,Infinity],[-Infinity,-Infinity,-Infinity]];
for (const mesh of meshes) for (let k=0; k<mesh.vertices.length; k++) {
  const axis = k%3;
  bounds[0][axis] = Math.min(bounds[0][axis],mesh.vertices[k]);
  bounds[1][axis] = Math.max(bounds[1][axis],mesh.vertices[k]);
}
const centre = bounds[0].map((v,i) => (v+bounds[1][i])/2);
const scale = 2/(bounds[1][0]-bounds[0][0]);
const round = value => Math.round(value*1e6)/1e6;
for (const mesh of meshes) {
  mesh.vertices = mesh.vertices.map((v,i) => round((v-centre[i%3])*scale));
  mesh.normals = mesh.normals.map(round);
}
const asset = {version:1, meshes, textures, bounds: bounds.map(bound => bound.map((v,i) => round((v-centre[i])*scale))),
  orientation: 'Centered; width 2; +X right, +Y up, +Z front. All scene transforms baked.',
  attribution: {title:'PS5 Controller', author:'Taohid Animation', license:'CC BY 4.0',
    source:'https://sketchfab.com/3d-models/ps5-controller-b7bb9c5102a04cb0b1966c6d02bad7d6'}};
const output = path.join(root, 'assets/dualsense.mesh.json.gz');
fs.mkdirSync(path.dirname(output), {recursive:true});
fs.writeFileSync(output, gzipSync(JSON.stringify(asset), {level:9}));
console.log(JSON.stringify({output,bytes:fs.statSync(output).size,bounds:asset.bounds,
  vertices:meshes.reduce((n,m)=>n+m.vertices.length/3,0),triangles:meshes.reduce((n,m)=>n+m.indices.length/3,0),
  meshes:meshes.map(m=>({name:m.name,slot:m.slot,vertices:m.vertices.length/3,
    centre:[0,1,2].map(axis=>round(m.vertices.filter((_,i)=>i%3===axis).reduce((a,b)=>a+b,0)/(m.vertices.length/3)))}))},null,2));
