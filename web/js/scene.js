import * as THREE from '../vendor/three/three.module.js';
import { GLTFLoader } from '../vendor/three/GLTFLoader.js';
import { RoomEnvironment } from '../vendor/three/RoomEnvironment.js';
import { MeshoptDecoder } from '../vendor/three/meshopt_decoder.module.js';

// Located offline by bounding box in the CC BY source; see the plan's
// measured-facts list. Pinned by name, with a geometry fallback.
const LIGHTBAR_NODES = ['Object_18', 'Object_47'];

const SHELL_COLOURS = {
  white: 0xe9ecf2,
  black: 0x1b1f27,
  red: 0x8e1b2a,
};

export function createScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0.05, 0.55);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(1.5, 2.2, 2.0);
  scene.add(key);

  const root = new THREE.Group();
  scene.add(root);

  const lightbars = [];
  const shells = [];
  let glow = null;
  let disposed = false;

  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  loader.load('assets/dualsense.glb', (gltf) => {
    const model = gltf.scene;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    model.position.sub(centre);
    model.scale.setScalar(0.35 / Math.max(size.x, size.y, size.z));
    root.add(model);

    // The model's names are generic (Object_5 ... Object_98, materials like
    // VRayMtl55), so the lightbar was located offline by bounding box: the
    // meshes thin in Y, wide in X and forward in Z are Object_18 and
    // Object_47. Those names are pinned first; the geometry test below is
    // the fallback for a repacked model whose names changed.
    model.traverse((node) => {
      if (!node.isMesh) return;
      const bounds = new THREE.Box3().setFromObject(node);
      const extent = bounds.getSize(new THREE.Vector3());
      const pinned = LIGHTBAR_NODES.includes(node.name) || LIGHTBAR_NODES.includes(node.parent?.name);
      const thin = extent.y < size.y * 0.06;
      const wide = extent.x > size.x * 0.10 && extent.x < size.x * 0.45;
      if (pinned || (thin && wide && bounds.getCenter(new THREE.Vector3()).z > centre.z)) {
        node.material = node.material.clone();
        lightbars.push(node);
      } else if (extent.x > size.x * 0.5) {
        node.material = node.material.clone();
        shells.push(node);
      }
    });
    console.info(`lightbar meshes: ${lightbars.map((m) => m.name).join(', ') || '(none found)'}`);
    setColour(currentColour);
  });

  let currentColour = [0, 170, 255];

  function setColour(rgb) {
    currentColour = rgb;
    const colour = new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255);
    for (const mesh of lightbars) {
      mesh.material.emissive = colour;
      mesh.material.emissiveIntensity = 1.6;
      mesh.material.color = colour.clone().multiplyScalar(0.25);
    }
    if (glow) glow.material.color = colour;
  }

  function setShell(name) {
    const value = SHELL_COLOURS[name] ?? SHELL_COLOURS.white;
    for (const mesh of shells) mesh.material.color = new THREE.Color(value);
  }

  const target = new THREE.Quaternion();

  function setOrientation(quaternion) {
    target.set(quaternion[0], quaternion[1], quaternion[2], quaternion[3]);
  }

  function resize() {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function frame() {
    if (disposed) return;
    root.quaternion.slerp(target, 0.18);
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }

  addEventListener('resize', resize);
  resize();
  frame();

  return {
    setColour,
    setShell,
    setOrientation,
    resize,
    dispose() {
      disposed = true;
      removeEventListener('resize', resize);
      renderer.dispose();
      pmrem.dispose();
    },
  };
}
