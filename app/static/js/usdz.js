/**
 * USDZ (Apple's 3D format: an iPhone or iPad photogrammetry scan, Reality Composer, Object Capture) to GLB,
 * in the browser: three.js's USDLoader reads the USDZ, its meshes, materials and textures, and the
 * GLTFExporter writes them as one .glb file, which every 3D program and the rest of the suite read.
 *
 * The viewer (model3d.js) shows a USDZ with loadUsdz() and offers the GLB; tests/test_usdz_to_glb.py runs
 * usdzToGlb() in a real browser on a scan.
 */
import * as THREE from 'three';

/** The USDZ as a three.js group, once its textures are read too. */
export async function loadUsdz(bytes) {
  const { USDLoader } = await import('three/addons/loaders/USDLoader.js');
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const group = await new Promise((resolve, reject) => {
    try {
      new USDLoader().parse(buffer, '', resolve, reject);
    } catch (err) {
      reject(err);
    }
  });
  let meshes = 0;
  group.traverse((o) => { if (o.isMesh) meshes += 1; });
  if (!meshes) throw new Error('There is no mesh in this USDZ');
  return group;
}

/** How much is in a model: meshes, vertices, triangles, textures and the box round it. */
export function describe(object) {
  const textures = new Set();
  let meshes = 0; let vertices = 0; let triangles = 0;
  object.updateMatrixWorld(true);
  object.traverse((o) => {
    if (!o.isMesh) return;
    meshes += 1;
    const g = o.geometry;
    const n = g.getAttribute('position')?.count || 0;
    vertices += n;
    triangles += (g.index ? g.index.count : n) / 3;
    for (const m of [].concat(o.material || [])) {
      for (const v of Object.values(m)) if (v?.isTexture && v.image) textures.add(v);
    }
  });
  const box = new THREE.Box3().setFromObject(object);
  return { meshes, vertices, triangles: Math.round(triangles), textures: textures.size,
    size: box.isEmpty() ? [0, 0, 0] : box.getSize(new THREE.Vector3()).toArray() };
}

/** A three.js object as a GLB file (an ArrayBuffer), textures inside it. */
export async function toGlb(object) {
  const { GLTFExporter } = await import('three/addons/exporters/GLTFExporter.js');
  return new GLTFExporter().parseAsync(object, { binary: true, onlyVisible: true });
}

/** A USDZ file's bytes as a GLB file's, with what is in each. */
export async function usdzToGlb(bytes) {
  const model = await loadUsdz(bytes);
  const glb = await toGlb(model);
  return { glb, model, stats: describe(model) };
}
