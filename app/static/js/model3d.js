/**
 * The 3D viewer: a GLB or glTF model, a USDZ (an iPhone scan, say: usdz.js, which also turns it into a GLB),
 * a PLY mesh or point cloud, or a Gaussian splat (3DGS: PLY, SPZ, SPLAT, KSPLAT, SOG), opened from a page's
 * attachments.
 *
 * Drag to turn it, right-drag (or Shift-drag) to move it, scroll to zoom. A scan that comes in lying down or
 * upside down is stood up with the ↻ buttons. "Video…" records the model turning round, from the camera
 * view on the screen, as an MP4 (WebCodecs; a WebM where the browser cannot make an MP4), and "Picture"
 * saves that view as a PNG.
 *
 * three.js, Spark (the splat renderer) and mp4-muxer are kept in static/vendor and named in the page's import
 * map, so nothing is fetched from the internet. Spark is loaded only for a splat.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const SPLAT_ENDINGS = ['splat', 'ksplat', 'spz', 'sog'];
const FPS = 30;
const SIZES = [
  { id: '1920x1080', label: '1920 × 1080 (HD, wide)', w: 1920, h: 1080 },
  { id: '1280x720', label: '1280 × 720 (smaller file)', w: 1280, h: 720 },
  { id: '1080x1080', label: '1080 × 1080 (square)', w: 1080, h: 1080 },
  { id: '1080x1920', label: '1080 × 1920 (upright, phone)', w: 1080, h: 1920 },
  { id: '3840x2160', label: '3840 × 2160 (4K)', w: 3840, h: 2160 },
];
const BACKGROUNDS = { dark: '#1f1d1a', grey: '#8a8580', white: '#ffffff', black: '#000000' };
const H264 = ['avc1.640033', 'avc1.4d0033', 'avc1.640028', 'avc1.42e028', 'avc1.42001f'];

/* --- small helpers -------------------------------------------------------------------- */

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c);
  return node;
}
const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const even = (n) => Math.max(2, Math.round(n / 2) * 2);
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/** What is in the file: 'gltf', 'usdz', 'ply-mesh' or 'splat'. A PLY is a splat when it has 3DGS's properties. */
export function modelType(filename, bytes) {
  const ending = (filename.split('.').pop() || '').toLowerCase();
  if (ending === 'glb' || ending === 'gltf') return 'gltf';
  if (ending === 'usdz') return 'usdz';
  if (SPLAT_ENDINGS.includes(ending)) return 'splat';
  if (ending === 'ply') {
    const head = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.length, 65536)));
    const header = head.slice(0, head.indexOf('end_header') + 1 || head.length);
    return /property\s+\S+\s+(f_dc_0|scale_0|rot_0|opacity)\b|element\s+chunk\b/.test(header) ? 'splat' : 'ply-mesh';
  }
  throw new Error(`A .${ending} file is not a 3D model this viewer reads`);
}

async function download(url, onProgress) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(res.status === 403 ? 'This file is not yours to open' : `It could not be fetched (${res.status})`);
  const total = Number(res.headers.get('Content-Length')) || 0;
  if (!res.body || !total) return new Uint8Array(await res.arrayBuffer());
  const bytes = new Uint8Array(total);
  const reader = res.body.getReader();
  let at = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes.set(value, at);
    at += value.length;
    onProgress(at / total);
  }
  return bytes.subarray(0, at);
}

/** The middle of most of the points: the farthest few of a scan (stray splats, the sky) left out. */
function trimmedBox(points, keep = 0.96) {
  const box = new THREE.Box3();
  if (!points.length) return box;
  const cut = (1 - keep) / 2;
  for (const axis of ['x', 'y', 'z']) {
    const values = points.map((p) => p[axis]).sort((a, b) => a - b);
    box.min[axis] = values[Math.floor(cut * (values.length - 1))];
    box.max[axis] = values[Math.ceil((1 - cut) * (values.length - 1))];
  }
  return box;
}

/* --- loading ---------------------------------------------------------------------------- */

async function loadGltf(bytes) {
  const [{ GLTFLoader }, { DRACOLoader }, { MeshoptDecoder }] = await Promise.all([
    import('three/addons/loaders/GLTFLoader.js'), import('three/addons/loaders/DRACOLoader.js'),
    import('three/addons/libs/meshopt_decoder.module.js')]);
  const loader = new GLTFLoader();
  const draco = new DRACOLoader();
  draco.setDecoderPath(new URL('../vendor/three/addons/libs/draco/gltf/', import.meta.url).href);
  loader.setDRACOLoader(draco);
  loader.setMeshoptDecoder(MeshoptDecoder);
  try {
    const gltf = await new Promise((resolve, reject) => loader.parse(bytes.slice().buffer, '', resolve, reject));
    return gltf.scene;
  } catch (err) {
    if (/fetch|load|uri/i.test(String(err?.message || err))) {
      throw new Error('This .gltf points at other files beside it. Save it as a .glb (one file) to view it here.');
    }
    throw err;
  } finally {
    draco.dispose();
  }
}

async function loadPlyMesh(bytes) {
  const { PLYLoader } = await import('three/addons/loaders/PLYLoader.js');
  const geometry = new PLYLoader().parse(bytes.slice().buffer);
  const coloured = !!geometry.getAttribute('color');
  if (geometry.index) {
    if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
    return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      vertexColors: coloured, color: coloured ? 0xffffff : 0xb8b2a8, roughness: 0.8, side: THREE.DoubleSide }));
  }
  // No faces: a point cloud. The points' size is set once its size is known (fit()).
  return new THREE.Points(geometry, new THREE.PointsMaterial({ vertexColors: coloured, color: coloured ? 0xffffff : 0x6b8f71, size: 1 }));
}

/* --- the viewer ----------------------------------------------------------------------------- */

/**
 * Show the model at `url` in `host` (an empty element that it fills). Returns { dispose }, to call when the
 * viewer closes or moves on to another file. attach(file): put a file on the note (a USDZ's GLB), where the
 * person may change it.
 */
export function mount(host, { url, filename, attach = null }) {
  const state = { disposed: false, busy: false, preview: false, framing: null, background: 'dark', abort: null };
  const view = h('div', { class: 'm3d-view' });
  const status = h('div', { class: 'm3d-status' }, 'Fetching the file…');
  const bar = h('div', { class: 'm3d-bar', hidden: true });
  const panel = h('div', { class: 'm3d-panel', hidden: true });
  const help = h('div', { class: 'm3d-help' }, 'Drag to turn · right-drag or Shift-drag to move · scroll to zoom');
  const root = h('div', { class: 'm3d' }, view, help, bar, panel, status);
  host.append(root);

  let renderer; let controls; let spark; let disposeModel = () => {};
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
  const holder = new THREE.Group();        // the ↻ buttons turn this, to stand a scan up
  scene.add(holder);
  let sample = [];                          // points of the model, in its own space, to frame it by
  let isPoints = false;

  const setBackground = (name) => {
    state.background = name;
    scene.background = new THREE.Color(BACKGROUNDS[name]);
    root.dataset.background = name;
  };

  /** Size the canvas to the space, or to the video's shape while the video panel is open. */
  const resize = () => {
    if (!renderer || state.busy) return;
    const W = view.clientWidth; const H = view.clientHeight;
    if (!W || !H) return;
    let w = W; let hgt = H;
    if (state.framing) {
      const aspect = state.framing.w / state.framing.h;
      if (W / H > aspect) w = Math.round(H * aspect); else hgt = Math.round(W / aspect);
    }
    renderer.setSize(w, hgt);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
    view.classList.toggle('framed', !!state.framing);
  };
  const observer = new ResizeObserver(resize);
  observer.observe(view);

  /** Point the camera at the whole model, a little from above and in front. */
  const fit = () => {
    holder.updateMatrixWorld(true);
    const box = new THREE.Box3();
    if (sample.length) {
      const m = (holder.children[0] || holder).matrixWorld;
      box.copy(trimmedBox(sample.map((p) => p.clone().applyMatrix4(m))));
    } else box.setFromObject(holder);
    if (box.isEmpty()) box.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const distance = (radius / Math.sin(Math.min(fov, fov * camera.aspect) / 2)) * 1.05;
    camera.position.copy(centre).add(new THREE.Vector3(0, 0.35, 1).normalize().multiplyScalar(distance));
    camera.near = distance / 200;
    camera.far = distance * 200;
    camera.updateProjectionMatrix();
    controls.target.copy(centre);
    controls.update();
    if (isPoints) holder.traverse((o) => { if (o.isPoints) o.material.size = radius / 300; });
  };

  /** Turn the camera round the model's upright axis, through its middle, by `angle` (radians). */
  const orbit = (from, angle) => {
    const offset = from.clone().sub(controls.target).applyAxisAngle(camera.up, angle);
    camera.position.copy(controls.target).add(offset);
    camera.lookAt(controls.target);
  };

  const render = () => renderer.render(scene, camera);
  let last = performance.now();
  const loop = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (state.busy) return;
    if (state.preview) {
      const { seconds, degrees, direction } = settings();
      orbit(camera.position, direction * THREE.MathUtils.degToRad(degrees) * (dt / seconds));
    }
    controls.update();
    render();
  };

  /* --- the buttons under the model ------------------------------------------------------- */

  const turn = (axis, angle) => {
    holder.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(axis, angle));
    fit();
  };
  const button = (label, title, onclick, extra = {}) => h('button', { class: 'btn btn-secondary btn-sm', type: 'button', title, onclick, ...extra }, label);
  const backgroundChoice = h('select', { class: 'm3d-select', title: 'The background, in the viewer and the video',
    onchange: (e) => setBackground(e.target.value) },
  Object.keys(BACKGROUNDS).map((k) => h('option', { value: k, text: k[0].toUpperCase() + k.slice(1) })));
  const previewButton = button('▶ Turn', 'Turn it round as the video will (again to stop)', () => setPreview(!state.preview));
  const setPreview = (on) => {
    state.preview = on;
    previewButton.textContent = on ? '■ Stop' : '▶ Turn';
    previewButton.classList.toggle('active', on);
  };
  bar.append(
    button('⟲ Reset', 'Back to the whole model, from the front', () => fit()),
    h('span', { class: 'm3d-sep' }),
    button('↻ Tip forward', 'Lying down? Tip it a quarter turn forward', () => turn(new THREE.Vector3(1, 0, 0), Math.PI / 2)),
    button('↻ Tip sideways', 'Tip it a quarter turn to the side', () => turn(new THREE.Vector3(0, 0, 1), Math.PI / 2)),
    button('↕ Flip', 'Upside down? Turn it over', () => turn(new THREE.Vector3(1, 0, 0), Math.PI)),
    h('span', { class: 'm3d-sep' }),
    backgroundChoice, previewButton,
    button('Picture', 'Save this view as a PNG, at the video size chosen', () => picture().catch(fail)),
    button('Video…', 'Record it turning round, from this view', () => togglePanel()));

  /* --- the video panel ------------------------------------------------------------------- */

  const remembered = (() => { try { return JSON.parse(localStorage.getItem('nb.m3d.video') || '{}'); } catch (e) { return {}; } })();
  const select = (name, title, options, fallback) => h('label', { class: 'm3d-field' }, h('span', {}, title),
    h('select', { class: 'm3d-select', name, onchange: changed },
      options.map(([value, label]) => h('option', { value, text: label, selected: String(remembered[name] ?? fallback) === String(value) }))));
  const fields = h('div', { class: 'm3d-fields' },
    select('size', 'Size', SIZES.map((s) => [s.id, s.label]), '1920x1080'),
    select('seconds', 'Length', [[4, '4 seconds'], [6, '6 seconds'], [8, '8 seconds'], [12, '12 seconds'], [20, '20 seconds'], [30, '30 seconds']], 8),
    select('degrees', 'Turn', [[360, 'One full turn'], [720, 'Two full turns'], [180, 'Half a turn'], [90, 'A quarter turn']], 360),
    select('direction', 'Direction', [[1, 'Clockwise, seen from above'], [-1, 'Anticlockwise, seen from above']], 1));
  const progress = h('progress', { class: 'm3d-progress', max: 1, value: 0, hidden: true });
  const note = h('p', { class: 'hint m3d-note' });
  const record = h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => (state.busy ? state.abort?.() : video()) }, '● Record');
  const saved = h('div', { class: 'm3d-saved' });
  panel.append(
    h('div', { class: 'm3d-panel-head' }, h('b', {}, 'Video of it turning'),
      h('button', { class: 'icon-btn', type: 'button', title: 'Close', onclick: () => togglePanel(false) }, '✕')),
    h('p', { class: 'hint' }, 'It starts from the view you see now, inside the frame: turn, move and zoom it there first. ',
      'The camera goes round the model’s upright axis, through the middle of the view.'),
    fields, record, progress, note, saved);

  function settings() {
    const get = (name) => panel.querySelector(`[name="${name}"]`).value;
    const size = SIZES.find((s) => s.id === get('size')) || SIZES[0];
    return { size, seconds: Number(get('seconds')), degrees: Number(get('degrees')), direction: Number(get('direction')) };
  }
  function changed() {
    const s = settings();
    try {
      localStorage.setItem('nb.m3d.video', JSON.stringify({ size: s.size.id, seconds: s.seconds, degrees: s.degrees, direction: s.direction }));
    } catch (e) { /* no storage */ }
    if (!panel.hidden) { state.framing = s.size; resize(); }
    const frames = Math.round(s.seconds * FPS);
    note.textContent = `${frames} frames at ${FPS} a second.${window.VideoEncoder ? ' Saved as an MP4.' : ' This browser saves a WebM (Chrome, Edge and Safari make an MP4).'}`;
  }
  function togglePanel(open = panel.hidden) {
    if (state.busy) return;
    panel.hidden = !open;
    state.framing = open ? settings().size : null;
    if (open) changed();
    resize();
  }

  /* --- recording --------------------------------------------------------------------------- */

  const baseName = filename.replace(/\.[^.]+$/, '') || 'model';
  const offer = (blob, name) => {
    const href = URL.createObjectURL(blob);
    const link = h('a', { href, download: name, class: 'btn btn-secondary btn-sm' }, `⤓ ${name}`);
    saved.replaceChildren(h('span', { class: 'hint' }, `Saved (${(blob.size / 1048576).toFixed(1)} MB). Again: `), link);
    link.click();
    // Kept while the viewer is open, to save again.
    cleanups.push(() => URL.revokeObjectURL(href));
  };
  const cleanups = [];

  /** Draw at the video's size, run `work`, and put the viewer back as it was, whatever happens. */
  async function atSize(size, work) {
    state.busy = true;
    setPreview(false);
    const pixelRatio = renderer.getPixelRatio();
    const shown = renderer.getSize(new THREE.Vector2());
    const aspect = camera.aspect;
    const from = camera.position.clone();
    try {
      renderer.setPixelRatio(1);
      renderer.setSize(size.w, size.h, false);   // the canvas stays its size on the screen
      renderer.domElement.style.width = `${shown.x}px`;
      renderer.domElement.style.height = `${shown.y}px`;
      camera.aspect = size.w / size.h;
      camera.updateProjectionMatrix();
      return await work(from);
    } finally {
      renderer.setPixelRatio(pixelRatio);
      renderer.setSize(shown.x, shown.y);
      camera.aspect = aspect;
      camera.position.copy(from);
      camera.lookAt(controls.target);
      camera.updateProjectionMatrix();
      state.busy = false;
      if (!state.disposed) resize();
    }
  }

  /** One frame, drawn twice a frame apart: a splat is sorted for the new view in the background. */
  async function settle() {
    render();
    await nextFrame();
    render();
  }

  async function picture() {
    if (state.busy) return;
    const size = settings().size;
    const blob = await atSize(size, async () => {
      await settle();
      return new Promise((resolve) => renderer.domElement.toBlob(resolve, 'image/png'));
    });
    offer(blob, `${baseName}.png`);
  }

  async function video() {
    if (state.busy) return;
    const { size, seconds, degrees, direction } = settings();
    const frames = Math.round(seconds * FPS);
    const full = degrees % 360 === 0;
    const angleAt = (i) => direction * THREE.MathUtils.degToRad(degrees) * (full ? i / frames : ease(i / (frames - 1)));
    let cancelled = false;
    state.abort = () => { cancelled = true; };
    record.textContent = '■ Cancel';
    progress.hidden = false;
    progress.value = 0;
    fields.querySelectorAll('select').forEach((s) => { s.disabled = true; });
    saved.replaceChildren();
    try {
      const encoder = window.VideoEncoder ? await mp4Encoder(size) : null;
      const recorder = encoder ? null : webmRecorder(size);
      const blob = await atSize(size, async (from) => {
        for (let i = 0; i < frames; i++) {
          if (cancelled || state.disposed) throw new Error('cancelled');
          orbit(from, angleAt(i));
          await settle();
          if (encoder) await encoder.add(i); else await recorder.add();
          progress.value = (i + 1) / frames;
        }
        return encoder ? encoder.finish() : recorder.finish();
      });
      offer(blob, `${baseName}-turning.${blob.type === 'video/mp4' ? 'mp4' : 'webm'}`);
    } catch (err) {
      if (err.message !== 'cancelled') fail(err);
      else saved.replaceChildren(h('span', { class: 'hint' }, 'Stopped; nothing saved.'));
    } finally {
      state.abort = null;
      record.textContent = '● Record';
      progress.hidden = true;
      fields.querySelectorAll('select').forEach((s) => { s.disabled = false; });
    }
  }

  /** H.264 in an MP4, frame by frame, as fast as the computer draws: every frame is in it, whatever the speed. */
  async function mp4Encoder(size) {
    const { Muxer, ArrayBufferTarget } = await import('mp4-muxer');
    const bitrate = Math.round(size.w * size.h * FPS * 0.2);    // about 12 Mbit/s at 1080p
    let config = null;
    for (const codec of H264) {
      const candidate = { codec, width: size.w, height: size.h, bitrate, framerate: FPS, avc: { format: 'avc' } };
      try {
        if ((await VideoEncoder.isConfigSupported(candidate)).supported) { config = candidate; break; }
      } catch (e) { /* try the next */ }
    }
    if (!config) throw new Error(`This browser cannot make an MP4 ${size.w} × ${size.h}: choose a smaller size`);
    const target = new ArrayBufferTarget();
    const muxer = new Muxer({ target, video: { codec: 'avc', width: size.w, height: size.h, frameRate: FPS },
      fastStart: 'in-memory', firstTimestampBehavior: 'offset' });
    let failure = null;
    const encoder = new VideoEncoder({ output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: (e) => { failure = e; } });
    encoder.configure(config);
    return {
      async add(i) {
        // Taken at once, in the task that drew it: a WebGL canvas is cleared once it is shown.
        const frame = new VideoFrame(renderer.domElement, { timestamp: Math.round((i * 1e6) / FPS), duration: Math.round(1e6 / FPS) });
        if (failure) { frame.close(); throw failure; }
        encoder.encode(frame, { keyFrame: i % (FPS * 2) === 0 });
        frame.close();
        while (encoder.encodeQueueSize > 6) await sleep(4);
      },
      async finish() {
        await encoder.flush();
        if (failure) throw failure;
        encoder.close();
        muxer.finalize();
        return new Blob([target.buffer], { type: 'video/mp4' });
      },
    };
  }

  /** Where WebCodecs is missing: the canvas recorded as it is drawn, in real time. */
  function webmRecorder(size) {
    const stream = renderer.domElement.captureStream(0);
    const track = stream.getVideoTracks()[0];
    if (!window.MediaRecorder || !renderer.domElement.captureStream) throw new Error('This browser cannot record a video: try Chrome, Edge, Firefox or Safari');
    const type = ['video/mp4;codecs=avc1', 'video/webm;codecs=vp9', 'video/webm'].find((t) => MediaRecorder.isTypeSupported(t)) || 'video/webm';
    const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: Math.round(size.w * size.h * FPS * 0.2) });
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.start();
    let next = performance.now();
    return {
      async add() {
        track.requestFrame();
        next += 1000 / FPS;
        await sleep(Math.max(0, next - performance.now()));
      },
      finish: () => new Promise((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: type.split(';')[0] }));
        recorder.stop();
        track.stop();
      }),
    };
  }

  /** A USDZ as a GLB: saved, or attached to the note beside it. Stood up as it is shown. */
  function glbButtons() {
    const glbName = `${baseName}.glb`;
    const convert = async () => {
      const { toGlb } = await import('./usdz.js');
      return new Blob([await toGlb(holder)], { type: 'model/gltf-binary' });
    };
    const working = async (buttonEl, label, work) => {
      if (state.busy) return;
      state.busy = true;
      buttonEl.disabled = true;
      buttonEl.textContent = 'Converting…';
      try { await work(); } catch (err) { fail(err); } finally {
        state.busy = false;
        buttonEl.disabled = false;
        buttonEl.textContent = label;
      }
    };
    const save = button('⤓ GLB', 'Save it as a GLB file, which most 3D programs open', () => working(save, '⤓ GLB', async () => {
      const blob = await convert();
      const href = URL.createObjectURL(blob);
      h('a', { href, download: glbName }).click();
      setTimeout(() => URL.revokeObjectURL(href), 60000);
    }));
    const add = attach && button('Attach GLB', `Put ${glbName} on this page, beside the USDZ`, () => working(add, 'Attach GLB', async () => {
      await attach(new File([await convert()], glbName, { type: 'model/gltf-binary' }));
    }));
    return [save, add].filter(Boolean);
  }

  function fail(err) {
    console.error(err);
    status.hidden = false;
    status.classList.add('m3d-error');
    status.textContent = String(err?.message || err).slice(0, 300);
    setTimeout(() => { if (!state.disposed && renderer) status.hidden = true; }, 6000);
  }

  /* --- start ------------------------------------------------------------------------------ */

  (async () => {
    const bytes = await download(url, (f) => { status.textContent = `Fetching the file… ${Math.round(f * 100)}%`; });
    if (state.disposed) return;
    const type = modelType(filename, bytes);
    status.textContent = type === 'splat' ? 'Reading the splats…' : 'Reading the model…';
    // A splat is drawn sharper without antialiasing, and Spark wants it off.
    renderer = new THREE.WebGLRenderer({ antialias: type !== 'splat', powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    view.append(renderer.domElement);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.screenSpacePanning = true;
    controls.addEventListener('start', () => setPreview(false));
    setBackground(remembered.background && BACKGROUNDS[remembered.background] ? remembered.background : 'dark');
    backgroundChoice.value = state.background;
    backgroundChoice.addEventListener('change', () => {
      try { localStorage.setItem('nb.m3d.video', JSON.stringify({ ...JSON.parse(localStorage.getItem('nb.m3d.video') || '{}'), background: state.background })); } catch (e) { /* no storage */ }
    });
    resize();

    if (type === 'splat') {
      const { SparkRenderer, SplatMesh } = await import('@sparkjsdev/spark');
      spark = new SparkRenderer({ renderer });
      scene.add(spark);
      const splat = new SplatMesh({ fileBytes: bytes, fileName: filename });
      await splat.initialized;
      if (state.disposed) { splat.dispose(); return; }
      // Most 3DGS scans are written y-down, as their cameras see: stood up the usual way round.
      splat.quaternion.set(1, 0, 0, 0);
      holder.add(splat);
      const count = splat.getNumSplats ? splat.getNumSplats() : 0;
      const step = Math.max(1, Math.floor(count / 40000));
      splat.forEachSplat((i, centre) => { if (i % step === 0) sample.push(centre.clone()); });
      disposeModel = () => splat.dispose();
      status.textContent = '';
    } else {
      const model = type === 'gltf' ? await loadGltf(bytes)
        : type === 'usdz' ? await (await import('./usdz.js')).loadUsdz(bytes) : await loadPlyMesh(bytes);
      if (state.disposed) return;
      if (type === 'usdz') bar.append(h('span', { class: 'm3d-sep' }), ...glbButtons());
      isPoints = model.isPoints;
      holder.add(model);
      renderer.toneMapping = THREE.NeutralToneMapping;
      const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js');
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
      scene.add(new THREE.HemisphereLight(0xffffff, 0x444040, 0.6));
      const sun = new THREE.DirectionalLight(0xffffff, 1.2);
      sun.position.set(1, 2, 1.5);
      scene.add(sun);
      disposeModel = () => model.traverse((o) => {
        o.geometry?.dispose();
        [].concat(o.material || []).forEach((m) => { Object.values(m).forEach((v) => v?.isTexture && v.dispose()); m.dispose(); });
      });
    }
    fit();
    status.hidden = true;
    bar.hidden = false;
    renderer.setAnimationLoop(loop);
  })().catch((err) => {
    if (state.disposed) return;
    console.error(err);
    status.classList.add('m3d-error');
    status.textContent = `It cannot be shown: ${String(err?.message || err).slice(0, 300)}. Download it to open it in its program.`;
  });

  return {
    dispose() {
      state.disposed = true;
      state.abort?.();
      observer.disconnect();
      cleanups.forEach((f) => f());
      if (renderer) {
        renderer.setAnimationLoop(null);
        controls?.dispose();
        disposeModel();
        spark?.dispose?.();
        scene.environment?.dispose?.();
        renderer.dispose();
        renderer.forceContextLoss();
      }
      root.remove();
    },
  };
}
