'use strict';
/*
 * Marking up a photo: draw, highlight, point with arrows, frame with boxes and
 * ellipses, and write on it. Works with a mouse, a pen or a finger.
 *
 * The photo itself is never changed. The marks are kept as shapes over the
 * original, in the original's pixels, and saved as a new picture with the
 * marks drawn on (app/attachments.py), so opening it again brings the marks
 * back to change.
 *
 * Numbering (① Number): click spots on the photo, plants say, and each gets
 * the next number, with a row in a table beside the photo to say what it is.
 * The numbers are not drawn into the picture: they belong to the page's
 * numbered photo (a gel block), which shows them over it, as gel lanes are.
 *
 *   Markup.open({ attachmentId, spots: {order, lanes}, onSaved(attachment, lanes) })
 *
 * onSaved gets the new marked-up picture, or null when the drawing did not
 * change, and the numbered spots ({id, x, y, label, note}, x and y as
 * fractions of the photo), in the order of their numbers.
 */

const Markup = {
  COLOURS: [['#ef4444', 'Red'], ['#facc15', 'Yellow'], ['#22c55e', 'Green'], ['#3b82f6', 'Blue'],
    ['#ffffff', 'White'], ['#111827', 'Black']],
  TOOLS: [['pen', '✎', 'Draw freehand'], ['highlight', '▰', 'Highlight'], ['arrow', '↗', 'Arrow'],
    ['line', '╱', 'Line'], ['rect', '▭', 'Box'], ['ellipse', '◯', 'Ellipse'], ['text', 'T', 'Write text'],
    ['number', '①', 'Number spots (plants, colonies…): click each in turn, and say what it is in the table; click a number to take it away'],
    ['erase', '⌫', 'Rub out a mark: click or drag over it']],
  SIZES: [[1, 'Thin'], [2, 'Medium'], [4, 'Thick']],

  async open({ attachmentId, spots = null, onSaved }) {
    let info;
    try { info = await api('GET', `/attachments/${attachmentId}/markup`); } catch (err) { toast(err.message, 'error'); return; }
    const image = new Image();
    image.src = attachmentUrl(info.source_id);
    try { await image.decode(); } catch (err) { toast('The photo could not be opened', 'error'); return; }
    this.show(image, info, attachmentId, spots, onSaved);
  },

  show(image, info, attachmentId, spotsGiven, onSaved) {
    const W = image.naturalWidth;
    const H = image.naturalHeight;
    // One unit: what a thin line is, in the photo's own pixels, so marks look the same on any photo.
    const unit = Math.max(2, Math.round(Math.max(W, H) / 320));
    let marks = (info.marks || []).map((m) => ({ ...m, p: [...m.p] }));
    // Numbered spots, in the photo's pixels; a gel numbers them by rows, anything else as clicked.
    const order = spotsGiven?.order === 'rows' ? 'rows' : 'clicks';
    let spots = (spotsGiven?.lanes || []).map((l) => ({ id: l.id || newId(), x: l.x * W, y: l.y * H, label: l.label || '', note: l.note || '' }));
    const numberedSpots = () => (order === 'rows'
      ? gelRows(spots.map((s) => ({ ...s, x: s.x / W, y: s.y / H, ref: s }))).flat().map((s) => s.ref)
      : spots);
    let lit = null;
    let drawingChanged = false;
    const undo = [];
    const redo = [];
    let tool = store.get('markupTool', 'arrow');
    let colour = store.get('markupColour', '#ef4444');
    let size = store.get('markupSize', 2);
    let current = null;
    let changed = false;

    const canvas = el('canvas', { class: 'markup-canvas', width: W, height: H });
    const g = canvas.getContext('2d');
    const stage = el('div', { class: 'markup-stage' }, canvas);

    const state = () => JSON.stringify({ marks, spots });
    const remember = (drawing = true) => {
      undo.push(state());
      if (undo.length > 200) undo.shift();
      redo.length = 0;
      changed = true;
      if (drawing) drawingChanged = true;
    };
    // How big a number's disc is: 12 pixels on the screen, however big the photo.
    const disc = () => 12 * W / (canvas.getBoundingClientRect().width || W);
    const draw = (withNumbers = true) => {
      g.clearRect(0, 0, W, H);
      g.drawImage(image, 0, 0);
      for (const m of current && !current.rubbing ? [...marks, current] : marks) this.paint(g, m);
      if (withNumbers) numberedSpots().forEach((s, i) => this.number(g, s.x, s.y, i + 1, disc(), s.id === lit));
    };

    /* where the pointer is, in the photo's pixels */
    const at = (e) => {
      const r = canvas.getBoundingClientRect();
      return [(e.clientX - r.left) * W / r.width, (e.clientY - r.top) * H / r.height];
    };
    // The rubber reaches 8 pixels on the screen, however big the photo is.
    const tolerance = () => 8 * W / (canvas.getBoundingClientRect().width || W);
    const rubOut = (x, y) => {
      for (let i = marks.length - 1; i >= 0; i--) {
        if (this.hits(g, marks[i], x, y, tolerance())) {
          if (!current) { remember(); current = { rubbing: true }; }
          marks.splice(i, 1);
          draw();
          return;
        }
      }
    };

    canvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      e.preventDefault();
      const [x, y] = at(e);
      // Text opens its box when the click is over, so the box keeps the focus.
      if (tool === 'text') { pendingText = [x, y]; return; }
      if (tool === 'number') {
        const hit = spots.find((s) => Math.hypot(s.x - x, s.y - y) <= disc() * 1.2);
        remember(false);
        if (hit) spots.splice(spots.indexOf(hit), 1);
        else spots.push({ id: newId(), x, y, label: '', note: '' });
        draw();
        side();
        if (!hit) setTimeout(() => panel.querySelector(`tr[data-spot="${spots[spots.length - 1].id}"] input`)?.focus({ preventScroll: true }), 0);
        return;
      }
      canvas.setPointerCapture(e.pointerId);
      if (tool === 'erase') { current = null; rubOut(x, y); return; }
      const w = size * unit * (tool === 'highlight' ? 5 : 1);
      current = { t: tool, c: colour, w, p: tool === 'pen' || tool === 'highlight' ? [x, y] : [x, y, x, y] };
      draw();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!canvas.hasPointerCapture(e.pointerId)) return;
      const [x, y] = at(e);
      if (tool === 'erase') { rubOut(x, y); return; }
      if (!current) return;
      if (current.t === 'pen' || current.t === 'highlight') {
        const n = current.p.length;
        // Skip points closer than half a unit: smoother lines, smaller saves.
        if (Math.hypot(x - current.p[n - 2], y - current.p[n - 1]) < unit / 2) return;
        current.p.push(x, y);
      } else {
        current.p[2] = x;
        current.p[3] = y;
      }
      draw();
    });
    let pendingText = null;
    const finish = () => {
      if (pendingText) { const [x, y] = pendingText; pendingText = null; writeAt(x, y); return; }
      if (current && !current.rubbing) {
        const p = current.p;
        // A click without a drag draws nothing, except a dot with the pen.
        const tiny = p.length === 4 && Math.hypot(p[2] - p[0], p[3] - p[1]) < unit;
        if (!tiny || current.t === 'pen') {
          if (current.p.length === 2) current.p.push(p[0] + 0.1, p[1]);
          remember();
          marks.push(current);
        }
      }
      current = null;
      draw();
    };
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', finish);

    /* the numbered spots: a table beside the photo, to say what each is */
    const panel = el('div', { class: 'markup-side' });
    const side = () => {
      const list = numberedSpots();
      panel.hidden = !list.length && tool !== 'number';
      if (panel.hidden) return;
      const field = (s, key, placeholder) => el('input', { type: 'text', class: 'cell', value: s[key], placeholder,
        oninput: (e) => { s[key] = e.target.value; changed = true; },
        onfocus: () => { lit = s.id; draw(); }, onblur: () => { lit = null; draw(); },
        onkeydown: (e) => {
          e.stopPropagation();
          if (e.key === 'Enter') { e.preventDefault(); panel.querySelector(`tr[data-spot="${list[list.indexOf(s) + 1]?.id}"] input`)?.focus(); }
        } });
      put(panel,
        el('div', { class: 'markup-side-head' }, order === 'rows' ? 'Lanes' : 'Numbered',
          el('span', { class: 'hint' }, order === 'rows' ? ' · numbered by rows, left to right' : ' · in the order clicked')),
        list.length
          ? el('table', { class: 'sheet gel-lanes' },
            el('thead', {}, el('tr', {}, el('th', {}, order === 'rows' ? 'Lane' : 'No.'), el('th', {}, order === 'rows' ? 'Sample' : 'Label'), el('th', {}, 'Notes'))),
            el('tbody', {}, list.map((s, i) => el('tr', { 'data-spot': s.id,
              onmouseenter: () => { lit = s.id; draw(); }, onmouseleave: () => { lit = null; draw(); } },
            el('td', { class: 'gel-lane-no' }, String(i + 1)),
            el('td', {}, field(s, 'label', order === 'rows' ? 'e.g. pGFP clone 3' : 'e.g. Col-0 #1')),
            el('td', {}, field(s, 'note', 'e.g. resistant'))))))
          : el('p', { class: 'hint' }, 'Click on the photo to number the first one.'));
    };

    /* text: typed in a box over the photo, where it was clicked */
    const writeAt = (x, y) => {
      stage.querySelector('.markup-text')?.remove();
      const r = canvas.getBoundingClientRect();
      const scale = r.width / W;
      const px = size * unit * 6;
      const box = el('textarea', { class: 'markup-text', rows: 1, placeholder: 'Type, then Enter',
        style: `left:${canvas.offsetLeft + x * scale}px;top:${canvas.offsetTop + y * scale}px;`
          + `font-size:${Math.max(12, px * scale)}px;color:${colour}` });
      const done = (keep) => {
        const text = box.value.trim();
        box.remove();
        if (keep && text) { remember(); marks.push({ t: 'text', c: colour, w: px, p: [x, y], s: text }); draw(); }
      };
      box.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); done(true); }
        if (e.key === 'Escape') { e.preventDefault(); done(false); }
      });
      box.addEventListener('blur', () => done(true));
      stage.append(box);
      box.focus();
      requestAnimationFrame(() => box.focus());
    };

    /* the bar */
    const choose = (group, value, button) => {
      for (const b of bar.querySelectorAll(`[data-group="${group}"]`)) b.classList.toggle('on', b === button);
      if (group === 'tool') { tool = value; store.set('markupTool', value); canvas.dataset.tool = value; side(); }
      if (group === 'colour') { colour = value; store.set('markupColour', value); }
      if (group === 'size') { size = value; store.set('markupSize', value); }
    };
    const button = (group, value, label, title, on) => {
      const b = el('button', { class: `markup-btn${on ? ' on' : ''}`, 'data-group': group, title, type: 'button',
        onclick: () => choose(group, value, b) }, label);
      return b;
    };
    const step = (from, to) => {
      if (!from.length) return;
      to.push(state());
      ({ marks, spots } = JSON.parse(from.pop()));
      changed = true;
      drawingChanged = true;
      draw();
      side();
    };
    const undoBtn = el('button', { class: 'markup-btn', title: 'Undo (Ctrl+Z)', type: 'button', onclick: () => step(undo, redo) }, '↶');
    const redoBtn = el('button', { class: 'markup-btn', title: 'Redo (Ctrl+Y)', type: 'button', onclick: () => step(redo, undo) }, '↷');
    const bar = el('div', { class: 'markup-bar' },
      el('span', { class: 'markup-group' }, this.TOOLS.map(([v, l, t]) => button('tool', v, l, t, v === tool))),
      el('span', { class: 'markup-group' }, this.COLOURS.map(([v, name]) => {
        const b = button('colour', v, '', name, v === colour);
        b.classList.add('swatch');
        b.style.background = v;
        return b;
      })),
      el('span', { class: 'markup-group' }, this.SIZES.map(([v, name]) => {
        const b = button('size', v, el('span', { class: 'size-dot', style: `width:${4 + v * 3}px;height:${4 + v * 3}px` }), name, v === size);
        return b;
      })),
      el('span', { class: 'markup-group' }, undoBtn, redoBtn,
        el('button', { class: 'markup-btn', title: 'Take away every drawn mark (the numbers stay)', type: 'button', onclick: () => {
          if (!marks.length) return;
          remember();
          marks = [];
          draw();
        } }, 'Clear')),
      el('span', { class: 'markup-spacer' }),
      el('span', { class: 'hint markup-note' }, 'The original photo is kept as it is.'),
      el('button', { class: 'btn btn-secondary btn-sm', type: 'button', onclick: () => leave() }, 'Cancel'),
      el('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: (e) => save(e.currentTarget) }, 'Save'));
    canvas.dataset.tool = tool;

    const backdrop = el('div', { class: 'markup-backdrop', role: 'dialog', 'aria-label': 'Mark up the photo' }, bar,
      el('div', { class: 'markup-body' }, stage, panel));
    const keys = (e) => {
      // Typing a label, or a dialog open over the editor (leave without saving?): not for the editor.
      if (e.target.closest?.('.markup-text') || document.querySelector('.modal-backdrop')) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); step(undo, redo); }
      else if (mod && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) { e.preventDefault(); step(redo, undo); }
      else if (e.key === 'Escape') { e.preventDefault(); leave(); }
    };
    const close = () => { document.removeEventListener('keydown', keys, true); backdrop.remove(); };
    const leave = () => {
      if (!changed) { close(); return; }
      modal({
        title: 'Leave without saving?',
        build: (b) => b.append(el('p', {}, 'The marks you made are not kept. The photo stays as it was.')),
        buttons: [{ label: 'Keep marking', kind: 'secondary' }, { label: 'Leave', kind: 'danger', onClick: close }],
      });
    };
    const save = async (btn) => {
      if (!changed) { close(); return; }
      btn.disabled = true;
      stage.querySelector('.markup-text')?.blur();
      current = null;
      const lanes = numberedSpots().map((s) => ({ id: s.id, x: s.x / W, y: s.y / H, label: s.label, note: s.note }));
      // Only the numbers changed: no new picture, the photo stays as it is.
      if (!drawingChanged) { close(); onSaved?.(null, lanes); return; }
      draw(false);         // the picture is the drawing; the numbers stay the page's
      // The marked-up picture as the original was: a JPEG photo stays a JPEG.
      const jpeg = info.mime === 'image/jpeg';
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, jpeg ? 'image/jpeg' : 'image/png', 0.92));
      const form = new FormData();
      form.append('picture', blob, jpeg ? 'marked.jpg' : 'marked.png');
      form.append('marks', JSON.stringify(marks));
      try {
        const res = await fetch(url(`/api/attachments/${attachmentId}/markup`), { method: 'POST', body: form, credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
        close();
        onSaved?.(data.attachment, lanes);
      } catch (err) {
        draw();
        toast(`Not saved: ${err.message}`, 'error', 7000);
        btn.disabled = false;
      }
    };
    document.addEventListener('keydown', keys, true);
    document.body.append(backdrop);
    side();
    draw();
    // The discs are sized for the screen: once laid out, draw them again at their size.
    requestAnimationFrame(() => draw());
  },

  /** A numbered disc, as the page shows them on gels. */
  number(g, x, y, n, r, lit) {
    g.save();
    const text = String(n);
    g.font = `700 ${r * 1.15}px system-ui, sans-serif`;
    const half = Math.max(r, g.measureText(text).width / 2 + r * 0.35);
    g.beginPath();
    g.roundRect(x - half, y - r, half * 2, r * 2, r);
    g.fillStyle = lit ? '#f97316' : '#fde047';
    g.fill();
    g.lineWidth = Math.max(1.5, r / 6);
    g.strokeStyle = '#111827';
    g.stroke();
    g.fillStyle = lit ? '#ffffff' : '#111827';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, x, y + r * 0.05);
    g.restore();
  },

  /** Draw one mark. */
  paint(g, m) {
    const p = m.p;
    g.save();
    g.strokeStyle = m.c;
    g.fillStyle = m.c;
    g.lineWidth = m.w;
    g.lineCap = 'round';
    g.lineJoin = 'round';
    if (m.t === 'pen' || m.t === 'highlight') {
      if (m.t === 'highlight') { g.globalAlpha = 0.35; g.lineCap = 'butt'; }
      g.beginPath();
      g.moveTo(p[0], p[1]);
      for (let i = 2; i < p.length; i += 2) g.lineTo(p[i], p[i + 1]);
      g.stroke();
    } else if (m.t === 'line' || m.t === 'arrow') {
      g.beginPath();
      g.moveTo(p[0], p[1]);
      g.lineTo(p[2], p[3]);
      g.stroke();
      if (m.t === 'arrow') {
        const angle = Math.atan2(p[3] - p[1], p[2] - p[0]);
        const head = Math.max(m.w * 4, 10);
        g.beginPath();
        g.moveTo(p[2], p[3]);
        g.lineTo(p[2] - head * Math.cos(angle - 0.45), p[3] - head * Math.sin(angle - 0.45));
        g.lineTo(p[2] - head * Math.cos(angle + 0.45), p[3] - head * Math.sin(angle + 0.45));
        g.closePath();
        g.fill();
      }
    } else if (m.t === 'rect') {
      g.strokeRect(Math.min(p[0], p[2]), Math.min(p[1], p[3]), Math.abs(p[2] - p[0]), Math.abs(p[3] - p[1]));
    } else if (m.t === 'ellipse') {
      g.beginPath();
      g.ellipse((p[0] + p[2]) / 2, (p[1] + p[3]) / 2, Math.abs(p[2] - p[0]) / 2 || 0.1, Math.abs(p[3] - p[1]) / 2 || 0.1, 0, 0, Math.PI * 2);
      g.stroke();
    } else if (m.t === 'text') {
      g.font = `600 ${m.w}px system-ui, sans-serif`;
      g.textBaseline = 'top';
      // An outline in the opposite shade, so the words read on any part of the photo.
      g.lineWidth = Math.max(2, m.w / 7);
      g.strokeStyle = this.dark(m.c) ? '#ffffff' : '#000000';
      String(m.s || '').split('\n').forEach((line, i) => {
        g.strokeText(line, p[0], p[1] + i * m.w * 1.2);
        g.fillText(line, p[0], p[1] + i * m.w * 1.2);
      });
    }
    g.restore();
  },

  dark(hex) {
    const n = parseInt(hex.slice(1), 16);
    return ((n >> 16) * 299 + ((n >> 8) & 255) * 587 + (n & 255) * 114) / 1000 < 128;
  },

  /** Whether (x, y) is on a mark, within `tol` pixels: for rubbing out. */
  hits(g, m, x, y, tol) {
    const p = m.p;
    const near = tol + m.w / 2;
    const toSegment = (ax, ay, bx, by) => {
      const dx = bx - ax;
      const dy = by - ay;
      const t = dx || dy ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) : 0;
      return Math.hypot(x - (ax + t * dx), y - (ay + t * dy));
    };
    if (m.t === 'pen' || m.t === 'highlight') {
      for (let i = 2; i < p.length; i += 2) if (toSegment(p[i - 2], p[i - 1], p[i], p[i + 1]) <= near) return true;
      return Math.hypot(x - p[0], y - p[1]) <= near;
    }
    if (m.t === 'line' || m.t === 'arrow') return toSegment(p[0], p[1], p[2], p[3]) <= near;
    if (m.t === 'rect') {
      const [x1, y1, x2, y2] = [Math.min(p[0], p[2]), Math.min(p[1], p[3]), Math.max(p[0], p[2]), Math.max(p[1], p[3])];
      return [[x1, y1, x2, y1], [x2, y1, x2, y2], [x2, y2, x1, y2], [x1, y2, x1, y1]].some((s) => toSegment(...s) <= near);
    }
    if (m.t === 'ellipse') {
      const rx = Math.abs(p[2] - p[0]) / 2 || 1;
      const ry = Math.abs(p[3] - p[1]) / 2 || 1;
      const d = Math.hypot((x - (p[0] + p[2]) / 2) / rx, (y - (p[1] + p[3]) / 2) / ry);
      return Math.abs(d - 1) * Math.min(rx, ry) <= near;
    }
    if (m.t === 'text') {
      g.save();
      g.font = `600 ${m.w}px system-ui, sans-serif`;
      const lines = String(m.s || '').split('\n');
      const width = Math.max(...lines.map((l) => g.measureText(l).width));
      g.restore();
      return x >= p[0] - tol && x <= p[0] + width + tol && y >= p[1] - tol && y <= p[1] + lines.length * m.w * 1.2 + tol;
    }
    return false;
  },
};
