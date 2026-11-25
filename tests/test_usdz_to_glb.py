"""
USDZ to GLB, as the 3D viewer does it (app/static/js/usdz.js), in a real browser on a real scan.

The conversion runs in the browser (three.js's USDLoader and GLTFExporter), so this test serves the
notebook's static files, opens them in a headless Chromium or Edge through Playwright, converts the scan,
and checks that:
  - what comes out is a GLB: the header, a JSON chunk, a binary chunk, of the length it says;
  - nothing is lost: read back, the GLB has the meshes, vertices, triangles and textures of the USDZ,
    and the same size;
  - it looks the same: the USDZ and the GLB drawn from the same camera differ by very little, while
    either differs a lot from an empty picture (so a model with no colour would not pass).

It needs Playwright (pip install playwright; it uses Edge or Chrome where installed, or run
`playwright install chromium`) and a scan: USDZ_SAMPLE, or "photogrammetry_mesh 2.usdz" beside this
repository. Without either, it is skipped. The GLB made is left in pytest's temporary directory, and
USDZ_GLB_OUT saves a copy where you say.
"""

import base64
import json
import os
import shutil
import struct
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, '..', 'app', 'static')
SAMPLE = os.environ.get('USDZ_SAMPLE') or os.path.join(HERE, '..', '..', 'photogrammetry_mesh 2.usdz')

playwright_api = pytest.importorskip('playwright.sync_api', reason='needs Playwright: pip install playwright')
pytestmark = pytest.mark.skipif(not os.path.isfile(SAMPLE), reason=f'no USDZ to convert at {SAMPLE} (set USDZ_SAMPLE)')

HARNESS = """<!doctype html><meta charset="utf-8"><title>USDZ to GLB</title>
<script type="importmap">{"imports": {
  "three": "/static/vendor/three/three.module.js",
  "three/addons/": "/static/vendor/three/addons/"}}</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { usdzToGlb, describe } from '/static/js/usdz.js';

const SIZE = 256;
const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
renderer.setSize(SIZE, SIZE, false);

/** The object drawn from the front and a little above, lit the same way each time, as RGBA bytes. */
function picture(object) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202020);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x404040, 1.5));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  if (object) scene.add(object);
  const box = object ? new THREE.Box3().setFromObject(object) : new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  const centre = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() / 2;
  const camera = new THREE.PerspectiveCamera(40, 1, radius / 100, radius * 100);
  camera.position.copy(centre).add(new THREE.Vector3(0, 0.35, 1).normalize().multiplyScalar(radius / Math.sin(THREE.MathUtils.degToRad(20))));
  camera.lookAt(centre);
  renderer.render(scene, camera);
  const gl = renderer.getContext();
  const pixels = new Uint8Array(SIZE * SIZE * 4);
  gl.readPixels(0, 0, SIZE, SIZE, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  if (object) scene.remove(object);
  return pixels;
}
/** How far apart two pictures are, where either shows the model: the mean difference (0-255) and how much is covered. */
const difference = (a, b, empty) => {
  let sum = 0; let covered = 0;
  for (let i = 0; i < a.length; i += 4) {
    const shown = [0, 1, 2].some((c) => a[i + c] !== empty[i + c] || b[i + c] !== empty[i + c]);
    if (!shown) continue;
    covered += 1;
    sum += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
  }
  return { mean: covered ? sum / (covered * 3) : 0, covered: covered / (a.length / 4) };
};
const png = (pixels) => {
  const c = document.createElement('canvas'); c.width = c.height = SIZE;
  const data = new ImageData(SIZE, SIZE);
  for (let y = 0; y < SIZE; y++) data.data.set(pixels.subarray((SIZE - 1 - y) * SIZE * 4, (SIZE - y) * SIZE * 4), y * SIZE * 4);
  c.getContext('2d').putImageData(data, 0, 0);
  return c.toDataURL('image/png').split(',')[1];
};

window.convert = async () => {
  const bytes = new Uint8Array(await (await fetch('/sample.usdz')).arrayBuffer());
  const started = performance.now();
  const { glb, model, stats } = await usdzToGlb(bytes);
  const seconds = (performance.now() - started) / 1000;
  const back = (await new Promise((resolve, reject) => new GLTFLoader().parse(glb, '', resolve, reject))).scene;
  const read = describe(back);
  const empty = picture(null);
  const before = picture(model);
  const after = picture(back);
  let binary = '';
  const view = new Uint8Array(glb);
  for (let i = 0; i < view.length; i += 0x8000) binary += String.fromCharCode.apply(null, view.subarray(i, i + 0x8000));
  return { stats, read, seconds, glb: btoa(binary), pictures: [png(before), png(after)],
           change: difference(before, after, empty), seen: difference(before, empty, empty) };
};
window.ready = true;
</script>"""


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server's name)
        if self.path == '/':
            return self._send(HARNESS.encode(), 'text/html')
        if self.path == '/sample.usdz':
            with open(SAMPLE, 'rb') as f:
                return self._send(f.read(), 'application/octet-stream')
        if self.path.startswith('/static/'):
            self.path = self.path[len('/static'):]
            return super().do_GET()
        self.send_error(404)

    def _send(self, body, mime):
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guess_type(self, path):
        return 'text/javascript' if path.endswith('.js') else super().guess_type(path)

    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def server():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(_Handler, directory=os.path.abspath(STATIC)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}/'
    httpd.shutdown()


@pytest.fixture(scope='module')
def page(server):
    args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
    with playwright_api.sync_playwright() as p:
        browser, tried = None, []
        for channel in ('msedge', 'chrome', None):
            try:
                browser = p.chromium.launch(channel=channel, headless=True, args=args)
                break
            except Exception as exc:  # not installed: the next
                tried.append(f'{channel or "chromium"}: {str(exc).splitlines()[0]}')
        if browser is None:
            pytest.skip('no browser for Playwright: ' + '; '.join(tried))
        tab = browser.new_page()
        errors = []
        tab.on('pageerror', lambda e: errors.append(str(e)))
        tab.goto(server)
        tab.wait_for_function('window.ready === true', timeout=30000)
        tab.errors = errors
        yield tab
        browser.close()


def _glb_chunks(data: bytes):
    magic, version, length = struct.unpack_from('<4sII', data, 0)
    assert magic == b'glTF' and version == 2, 'a GLB, version 2'
    assert length == len(data), 'its length is the one in its header'
    chunks, at = {}, 12
    while at < length:
        size, kind = struct.unpack_from('<I4s', data, at)
        chunks[kind] = data[at + 8:at + 8 + size]
        at += 8 + size
    return json.loads(chunks[b'JSON']), chunks.get(b'BIN\x00', b'')


def test_a_photogrammetry_usdz_becomes_a_glb(page, tmp_path):
    result = page.evaluate('window.convert()')
    assert not page.errors, page.errors
    glb = base64.b64decode(result['glb'])
    out = tmp_path / (os.path.splitext(os.path.basename(SAMPLE))[0] + '.glb')
    out.write_bytes(glb)
    for name, picture in zip(('usdz', 'glb'), result['pictures']):
        (tmp_path / f'{name}.png').write_bytes(base64.b64decode(picture))
    if os.environ.get('USDZ_GLB_OUT'):
        shutil.copy(out, os.environ['USDZ_GLB_OUT'])
    stats, read = result['stats'], result['read']
    print(f"\n{os.path.basename(SAMPLE)}: {stats} -> {len(glb) / 1048576:.1f} MB GLB in {result['seconds']:.1f} s; "
          f"read back {read}; pictures {result['change']} apart, against empty {result['seen']}; at {out}")

    gltf, binary = _glb_chunks(glb)
    assert gltf['asset']['version'] == '2.0'
    assert len(gltf['meshes']) >= 1 and binary, 'its meshes, and their data in the binary chunk'
    # A scan's colour, and its normal and occlusion maps, go inside the file.
    assert len(gltf.get('images', [])) == stats['textures'] >= 1
    assert all('bufferView' in image for image in gltf['images']), 'the pictures are in the GLB, not beside it'
    material = gltf['materials'][0]
    assert 'baseColorTexture' in material.get('pbrMetallicRoughness', {}), 'the scan keeps its colours'

    # Read back, nothing is missing.
    assert stats['meshes'] >= 1 and stats['triangles'] > 1000
    for key in ('meshes', 'vertices', 'triangles', 'textures'):
        assert read[key] == stats[key], key
    assert read['size'] == pytest.approx(stats['size'], rel=1e-4)

    # And it looks the same: drawn alike, where the model is the two differ by under 2 levels in 255 on
    # average, where the model against an empty picture differs by far more.
    assert result['seen']['covered'] > 0.05 and result['seen']['mean'] > 20, 'the model is in the picture'
    assert result['change']['mean'] < 2, result['change']
