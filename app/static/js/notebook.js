'use strict';
/*
 * The Lab Notebook page: the trees of notes on the left, the open note on the
 * right, edited as blocks and saved as you go.
 *
 * A note's content is a list of blocks (see app/content.py); this file draws
 * them, lets them be edited, and sends the list back. Tables work their
 * numbers out with sheet.js.
 */

const NB = window.NB;
const url = (path) => `${NB.base}${path}`;

/* --- small helpers ---------------------------------------------------------- */

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'style') node.setAttribute('style', value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== 'string') node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Replace a node's children; nested lists are flattened and empty slots skipped. */
function put(node, ...children) {
  node.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false)
    .map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
  return node;
}

async function api(method, path, body) {
  const res = await fetch(url(`/api${path}`), {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) {
    const err = new Error(data.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

function toast(message, kind = 'info', ms = 3500) {
  const box = el('div', { class: `toast toast-${kind}` }, message);
  document.getElementById('toasts').append(box);
  setTimeout(() => box.remove(), ms);
}

/** A dialog. `buttons`: [{label, kind, onClick({close, body}) -> false keeps it open}]. */
function modal({ title, build, buttons = [{ label: 'Close', kind: 'secondary' }], wide = false, onClose }) {
  const body = el('div', { class: 'modal-body' });
  const backdrop = el('div', { class: 'modal-backdrop' });
  let closed = false;
  const close = () => { if (closed) return; closed = true; backdrop.remove(); onClose?.(); };
  const foot = el('div', { class: 'modal-foot' },
    buttons.map((b) => el('button', {
      class: `btn ${b.kind === 'secondary' ? 'btn-secondary' : b.kind === 'danger' ? 'btn-danger' : 'btn-primary'}`,
      type: 'button',
      onclick: async (ev) => {
        // Kept now: the event forgets its target once the handler awaits.
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          const keep = await b.onClick?.({ close, body });
          if (keep !== false) close();
        } catch (err) {
          toast(err.message, 'error', 6000);
        } finally {
          btn.disabled = false;
        }
      },
    }, b.label)));
  backdrop.append(el('div', { class: `modal ${wide ? 'modal-wide' : ''}`, role: 'dialog' },
    el('div', { class: 'modal-head' }, el('span', { class: 'modal-title', text: title }),
      el('button', { class: 'icon-btn', title: 'Close', onclick: close }, '✕')),
    body, foot));
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
  document.body.append(backdrop);
  build?.(body, close);
  return { close, body };
}

/**
 * A day typed as dd-mm-yyyy (or with / or . between, and one-figure days and months), as "YYYY-MM-DD";
 * null if it is not a real day, or the year is not four figures (a year typed as 6 or 6202 is a typo).
 */
function isoFromDayMonthYear(text) {
  const m = /^\s*(\d{1,2})[-./ ](\d{1,2})[-./ ](\d{4})\s*$/.exec(text || '');
  if (!m) return null;
  const [d, mo, y] = [+m[1], +m[2], +m[3]];
  if (y < 1900 || y > 2200) return null;
  const date = new Date(y, mo - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  const pad = (n) => String(n).padStart(2, '0');
  return `${y}-${pad(mo)}-${pad(d)}`;
}

/**
 * A dd-mm-yyyy box that brings up the browser's calendar when clicked (or from the button beside it);
 * a day can still be typed. The browser's own date box is kept hidden: it shows days in its language's
 * order, often mm/dd/yyyy.
 */
function withCalendar(input) {
  const calendar = el('input', { type: 'date', tabindex: '-1', 'aria-hidden': 'true' });
  const open = () => {
    const iso = isoFromDayMonthYear(input.value);
    if (iso) calendar.value = iso;
    try { calendar.showPicker(); } catch { /* an older browser: type the day */ }
  };
  calendar.addEventListener('change', () => {
    if (!calendar.value) return;
    input.value = dayMonthYear(calendar.value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  input.addEventListener('click', open);
  return el('span', { class: 'date-field' }, input,
    el('button', { type: 'button', class: 'icon-btn', title: 'Choose the day on a calendar',
      onclick: (e) => { e.preventDefault(); open(); } }, glyph('calendar')),
    calendar);
}

/** "YYYY-MM-DD" as dd-mm-yyyy. */
function dayMonthYear(iso) {
  const [y, m, d] = String(iso).split('-');
  return `${d}-${m}-${y}`;
}

/** A person as they are shown: the name they set on the suite's dashboard, or their username. */
function who(username) {
  return (username && NB.names && NB.names[username]) || username;
}

/** A time the server stored (UTC "YYYY-MM-DD HH:MM:SS"), in local time. */
function localTime(stamp) {
  if (!stamp) return '';
  const d = new Date(String(stamp).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(stamp) ? '' : 'Z'));
  if (Number.isNaN(d.getTime())) return String(stamp).slice(0, 16);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const newId = () => Math.random().toString(16).slice(2, 14);
const attachmentUrl = (id, download = false) => url(`/api/attachments/${encodeURIComponent(id)}${download ? '?download' : ''}`);
// Opened in the browser where it can be: an office file as a PDF, a text file as text; anything else as before.
const viewUrl = (id) => url(`/api/attachments/${encodeURIComponent(id)}?view`);
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
const sizeLabel = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`);
/** One of Trellis Tools' small icons (static/trellis/glyphs/), in place of an emoji. */
const glyph = (name) => el('img', { class: 'tt-glyph', src: url(`/static/trellis/glyphs/${name}.svg`), alt: '' });
const FILE_ICONS = { pdf: 'pdf', word: 'doc', powerpoint: 'slides', excel: 'sheet', archive: 'archive', sequence: 'line', text: 'text', image: 'image', file: 'attach' };
/** An attachment as it sits in text: a photo shown, any other file a link (its icon is the stylesheet's, a[data-attachment]). */
const attachmentHtml = (a) => (a.image
  ? `<p><img data-attachment="${a.id}" alt="${escapeHtml(a.filename)}"></p>`
  : `<p><a data-attachment="${a.id}">${escapeHtml(a.filename)}</a></p>`);
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(`nb:${key}`)) ?? fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(`nb:${key}`, JSON.stringify(value)); } catch (e) { /* private window */ } },
};
// Sections other tools put into a day, by their source's kind: its glyph, and where they come from
// (as content.IMPORTED_LABELS says on the server).
const IMPORTED = {
  'virtual-digest': ['cut', 'A virtual digest from the Sequence Editor'],
  'plasmid-map': ['plasmid', 'A plasmid map from the Sequence Editor'],
  'cloning-product': ['plasmid', 'A cloning product from the Sequence Editor'],
  pcr: ['stocks', 'A PCR from the Sequence Editor'],
  primers: ['primer', 'Primers designed in the Sequence Editor'],
  'sequencing-read': ['trace', 'A sequencing read from the Sequence Editor'],
  'moclo-plasmid': ['plasmid', 'A plasmid from the MoClo Library Tool'],
  'moclo-cassette': ['cassette', 'A cassette from the MoClo Library Tool'],
  'moclo-part': ['part', 'A part from the MoClo Library Tool'],
  // Not imported, but kept up by the page: how to get rid of the chemicals linked on it (App.noteDisposal).
  disposal: ['hazard', 'How and where to get rid of the chemicals on this page, from Lab Stocks'],
};
/** The waste disposal box at the foot of a page that links chemicals. */
const isDisposalBox = (b) => !!b && b.type === 'section' && b.source?.kind === 'disposal';
const ICONS = { notebook: 'notebook', library: 'library', year: 'calendar', month: 'calendar', day: 'calendar', page: 'text', folder: 'folder', protocol: 'protocol', todo: 'steps', meeting: 'people', task: 'cube' };   // glyphs
const noteGlyph = (type) => glyph(ICONS[type] || 'text');
const editorLink = (id) => `${NB.editor}/editor?open=${encodeURIComponent(id)}`;
const SEED_KINDS = { L: 'line', S: 'lot', P: 'plant' };
// GL-S-0042 (or S-0042 from before lab codes): the letter before the number says what it is.
// GL-G-0042 a glycerol stock, GL-O-0007 a primer, GL-C-0003 a chemical, GL-A-0005 an antibody, GL-M-0001 plant
// material, in Lab Stocks.
const STOCK_KINDS = { G: 'glycerol', O: 'primer', C: 'chemical', A: 'antibody', M: 'material' };
// A link in a table cell, put there with @ (app/content.py CELL_LINK): [label](stock:GL-C-0003).
const CELL_LINK = /\[([^\]\n]{0,300})\]\((note|plasmid|seed|stock|track|task):([^)\s"]{1,80})\)/g;
const cellToken = (kind, id, label) => `[${String(label).replace(/[[\]\n]/g, ' ')}](${kind}:${id})`;
/** Everything in a box selected, as clicking into an input used to do. */
function selectAll(area) {
  const range = document.createRange();
  range.selectNodeContents(area);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}
/** A piece of a cell, with whatever formatting it carries (cleaned when it was saved). */
function cellPiece(markup) {
  const span = el('span', {});
  span.innerHTML = markup;
  return span;
}
/** A cell with its links as links and its formatting shown, for reading it; null when it has none. */
function cellLinks(text) {
  const s = String(text ?? '');
  const out = [];
  let last = 0;
  CELL_LINK.lastIndex = 0;
  for (let m = CELL_LINK.exec(s); m; m = CELL_LINK.exec(s)) {
    if (m.index > last) out.push(cellPiece(s.slice(last, m.index)));
    out.push(el('a', { [`data-${m[2]}`]: m[3], href: '#', title: 'Open it (click the cell around it to change the cell)' }, m[1]));
    last = m.index + m[0].length;
  }
  if (!out.length) return null;
  if (last < s.length) out.push(cellPiece(s.slice(last)));
  return out;
}
const stockLink = (code) => `${NB.stocks}/#${STOCK_KINDS[code.split('-').slice(-2, -1)[0]] || 'glycerol'}=${encodeURIComponent(code)}`;
const seedLink = (code) => `${NB.seeds}/#${SEED_KINDS[code.split('-').slice(-2, -1)[0]] || 'line'}=${encodeURIComponent(code)}`;
// A Genome Browser track, by its id: the browser opens its genome with it on.
const trackLink = (id) => `${NB.genome}/?track=${encodeURIComponent(id)}`;

/* --- pickers ------------------------------------------------------------------ */

/** Search-as-you-type list in a dialog; resolves with the chosen item, or null. */
function picker({ title, placeholder, search, describe }) {
  return new Promise((resolve) => {
    let chosen = null;
    modal({
      title,
      onClose: () => resolve(chosen),
      build: (body, closeNow) => {
        const input = el('input', { type: 'search', class: 'picker-input', placeholder });
        const list = el('ul', { class: 'picker-list' });
        let ticket = 0;
        const run = async () => {
          const mine = ++ticket;
          let items = [];
          try { items = await search(input.value.trim()); } catch (err) { toast(err.message, 'error'); }
          if (mine !== ticket) return;
          put(list, ...(items.length ? items.map((item) => el('li', {
            class: 'picker-item', tabindex: '0',
            onclick: () => { chosen = item; closeNow(); },
            onkeydown: (e) => { if (e.key === 'Enter') { chosen = item; closeNow(); } },
          }, describe(item))) : [el('li', { class: 'hint' }, 'Nothing found')]));
        };
        input.addEventListener('input', run);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); list.querySelector('.picker-item')?.focus(); }
        });
        body.append(input, list);
        setTimeout(() => input.focus(), 0);
        run();
      },
      buttons: [{ label: 'Cancel', kind: 'secondary' }],
    });
  });
}

/**
 * Move the item at `from` to the gap `slot` (0 = before the first, items.length = after the last), in
 * place. Gives false, and changes nothing, when that would leave it where it is or the numbers are off.
 */
function moveItem(items, from, slot) {
  if (!Number.isInteger(from) || !Number.isInteger(slot) || from < 0 || from >= items.length || slot < 0 || slot > items.length) return false;
  const to = slot > from ? slot - 1 : slot;
  if (to === from) return false;
  items.splice(to, 0, ...items.splice(from, 1));
  return true;
}

/**
 * Choose where a protocol goes: "Add to today" at the top, then the pages and days you may add to (your own,
 * or ones shared with you to work on), newest first, found by title. Gives {today: true} or that page.
 */
const pickProtocolTarget = () => picker({
  title: 'Add this protocol to…', placeholder: 'Search your pages and days by title',
  search: async (q) => {
    const found = (await api('GET', `/search?q=${encodeURIComponent(q)}&types=page,day&editable=1`)).notes;
    return q ? found : [{ today: true, title: 'Add to today' }, ...found];
  },
  describe: (n) => (n.today
    ? [noteGlyph('day'), ' ', el('b', { text: n.title }), el('span', { class: 'hint' }, " · a page under today's day")]
    : [noteGlyph(n.type), ' ', el('b', { text: n.title }),
      n.where ? el('span', { class: 'hint' }, ` · ${n.where}`) : null,
      n.owner && n.owner !== NB.person.username ? el('span', { class: 'hint' }, ` · ${who(n.owner)}`) : null]),
});

const pickPlasmid = () => picker({
  title: 'Link a plasmid', placeholder: 'Search the plasmid library',
  search: async (q) => (await api('GET', `/plasmids?q=${encodeURIComponent(q)}`)).plasmids,
  describe: (p) => [el('b', { text: p.name }), el('span', { class: 'hint' },
    ` · ${p.length.toLocaleString()} bp${p.circular ? ', circular' : ''}${p.owner ? ` · ${who(p.owner)}` : ''}`
    + `${p.confirmed ? ' · ✓ sequenced' : ''}`)],
});

const pickNote = (types, title = 'Choose a note') => picker({
  title, placeholder: 'Search by title',
  search: async (q) => (await api('GET', `/search?q=${encodeURIComponent(q)}&types=${(types || []).join(',')}`)).notes,
  describe: (n) => [noteGlyph(n.type), ' ', el('b', { text: n.title }),
    n.owner && n.owner !== NB.person.username ? el('span', { class: 'hint' }, ` · ${who(n.owner)}`) : null],
});

/** Choose a protocol: your favourites first, then the rest of the library. */
const pickProtocol = () => picker({
  title: 'Use a protocol', placeholder: 'Search the protocol library',
  search: async (q) => {
    const all = (await api('GET', `/protocols?q=${encodeURIComponent(q)}`)).protocols;
    return [...all.filter((p) => p.favorite), ...all.filter((p) => !p.favorite)];
  },
  describe: (p) => [p.favorite ? '★ ' : [glyph('protocol'), ' '], el('b', { text: p.title }),
    el('span', { class: 'hint' }, `${p.folder ? ` · ${p.folder}` : ''} · by ${who(p.created_by) || 'MoClo'}`)],
});

/** Choose a line, seed lot or plant from the seed bank (the lab's own; other labs' are not found). */
const pickSeed = () => picker({
  title: 'Link a seed lot, plant or line', placeholder: 'Search the seed bank by code or name',
  search: async (q) => {
    const res = await fetch(`${NB.seeds}/api/search?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? 'The seed bank is not part of this suite' : `Seed bank: ${res.status}`);
    return (await res.json()).results;
  },
  describe: (r) => [glyph({ line: 'line', lot: 'seedlot', plant: 'plant' }[r.kind] || 'plant'), ' ', el('b', { text: r.code }), ` ${r.label.slice(r.code.length)}`,
    el('span', { class: 'hint' }, ` · ${r.kind === 'lot' ? 'seed lot' : r.kind}`)],
});

/** Choose a glycerol stock, primer, chemical, antibody or plant material from Lab Stocks (the lab's own). */
const pickStock = () => picker({
  title: 'Link a stock, primer, chemical, antibody or plant material', placeholder: 'Search Lab Stocks by code, plasmid, primer, chemical, antibody or tube',
  search: async (q) => {
    const res = await fetch(`${NB.stocks}/api/search?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? 'Lab Stocks is not part of this suite' : `Lab Stocks: ${res.status}`);
    return (await res.json()).results;
  },
  describe: (r) => [glyph({ glycerol: 'stocks', primer: 'primer', chemical: 'protocol', antibody: 'antibody', material: 'leaf' }[r.kind] || 'stocks'), ' ', el('b', { text: r.code }), ` ${r.label.slice(r.code.length)}`,
    el('span', { class: 'hint' }, ` · ${{ glycerol: 'glycerol stock', material: 'plant material' }[r.kind] || r.kind}`)],
});

/** Choose a track in the Genome Browser, among those this person sees there. */
/** Choose a task of one's projects, to tag it with @ (app/projects.py taggable). */
const pickTask = () => picker({
  title: 'Tag a task', placeholder: "Search your projects' tasks",
  search: async (q) => (await api('GET', `/projects/tasks?q=${encodeURIComponent(q)}`)).tasks,
  describe: (t) => [glyph('steps'), ' ', el('b', { text: t.title }),
    el('span', { class: 'hint' }, ` · ${t.where} · ${dayMonthYear(t.start)} – ${dayMonthYear(t.end)}${t.done_on ? ' · done' : ''}`)],
});

const pickTrack = () => picker({
  title: 'Link a genome track', placeholder: 'Search the Genome Browser by track, experiment or genome',
  search: async (q) => {
    const res = await fetch(`${NB.genome}/api/tracks?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? 'The Genome Browser is not part of this suite' : `Genome Browser: ${res.status}`);
    return (await res.json()).tracks;
  },
  describe: (t) => [glyph('trace'), ' ', el('b', { text: t.name }),
    el('span', { class: 'hint' }, ` · ${t.genome}${t.experiment ? ` · ${t.experiment}` : ''}`)],
});

async function pickMocloReaction() {
  const { saved } = await api('GET', '/moclo/reactions');
  if (!saved.length) {
    toast('No saved assemblies in MoClo yet: assemble a plasmid there and save it to your dashboard', 'error', 7000);
    return null;
  }
  const item = await picker({
    title: 'Insert a MoClo reaction', placeholder: 'Filter your saved assemblies',
    search: async (q) => saved.filter((s) => s.title.toLowerCase().includes(q.toLowerCase())),
    describe: (s) => [el('b', { text: s.title }), el('span', { class: 'hint' },
      ` · ${s.reactions.map((r) => `${r.label} (${r.enzyme}, ${r.fragments} DNAs)`).join('; ')} · ${localTime(s.created_at)}`)],
  });
  return item ? (await api('GET', `/moclo/reactions/${encodeURIComponent(item.id)}/section`)).section : null;
}

/* --- the trees ------------------------------------------------------------------ */

const Tree = {
  expanded: new Set(store.get('expanded', [])),

  remember() { store.set('expanded', [...this.expanded]); },

  async mount(container, rootId, { label, editable = false, actions = null } = {}) {
    put(container);
    if (label) {
      const root = this.node({ id: rootId, title: label, type: 'notebook', has_children: true }, true, editable);
      if (actions) root.querySelector('.tree-row').append(...actions);
      container.append(root);
    } else {
      container.append(await this.childList(rootId, editable));
    }
  },

  async childList(parentId, editable = false) {
    const list = el('ul', { class: 'tree-list' });
    try {
      const { children } = await api('GET', `/notes/${parentId}/children`);
      for (const child of children) list.append(this.node(child, false, editable));
      if (!children.length) list.append(el('li', { class: 'tree-empty hint' }, 'Empty'));
    } catch (err) {
      list.append(el('li', { class: 'hint' }, err.message));
    }
    return list;
  },

  node(item, isRoot = false, editable = false) {
    const li = el('li', { class: 'tree-node', 'data-id': item.id });
    const open = this.expanded.has(item.id);
    const toggle = el('span', { class: `tree-toggle ${item.has_children ? '' : 'leaf'}` }, item.has_children ? (open ? '▾' : '▸') : '');
    const row = el('div', {
      class: `tree-row ${App.note?.id === item.id ? 'active' : ''}`,
      draggable: !isRoot && !['year', 'month', 'day'].includes(item.type) ? 'true' : null,
      title: item.cloned ? 'This note is in more than one place' : null,
    }, toggle, el('span', { class: 'tree-icon' }, noteGlyph(item.type)),
    el('span', { class: 'tree-title', text: item.title }), item.cloned ? el('span', { class: 'tree-clone' }, '⧉') : null,
    item.shared ? el('span', { class: 'tree-shared', title: 'Shared to work on together' }, glyph('people')) : null,
    // A page under this one, from right here, as in Trilium.
    editable ? el('button', {
      class: 'tree-add', title: `New page under “${item.title}”`,
      onclick: (e) => { e.stopPropagation(); App.newNote('mine', item.id); },
    }, '＋') : null);
    const kids = el('div', { class: 'tree-kids' });
    li.append(row, kids);

    const expand = async (force) => {
      const now = force ?? !this.expanded.has(item.id);
      if (now) this.expanded.add(item.id); else this.expanded.delete(item.id);
      this.remember();
      toggle.textContent = item.has_children ? (now ? '▾' : '▸') : '';
      put(kids, now ? await this.childList(item.id, editable) : '');
    };
    toggle.addEventListener('click', (e) => { e.stopPropagation(); if (item.has_children) expand(); });
    row.addEventListener('click', () => (isRoot ? expand() : App.open(item.id)));
    if (open && item.has_children) expand(true);

    // Drag a note onto another to move it there.
    row.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/x-branch', item.branch_id || '');
      e.dataTransfer.effectAllowed = 'move';
    });
    row.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/x-branch')) { e.preventDefault(); row.classList.add('drop'); } });
    row.addEventListener('dragleave', () => row.classList.remove('drop'));
    row.addEventListener('drop', async (e) => {
      e.preventDefault();
      row.classList.remove('drop');
      const branch = e.dataTransfer.getData('text/x-branch');
      if (!branch) return;
      try {
        await api('POST', `/branches/${branch}/move`, { parent_id: item.id });
        this.expanded.add(item.id);
        this.remember();
        await App.reloadTrees();
      } catch (err) { toast(err.message, 'error'); }
    });
    return li;
  },

  markActive(id) {
    for (const row of document.querySelectorAll('.tree-row.active')) row.classList.remove('active');
    for (const node of document.querySelectorAll(`.tree-node[data-id="${CSS.escape(id)}"] > .tree-row`)) node.classList.add('active');
  },

  rename(id, title) {
    for (const t of document.querySelectorAll(`.tree-node[data-id="${CSS.escape(id)}"] > .tree-row .tree-title`)) t.textContent = title;
  },
};

/* --- search -------------------------------------------------------------------------- */

const Search = {
  init() {
    const input = document.getElementById('searchInput');
    let timer;
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => this.run(input.value), 250); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { input.value = ''; this.run(''); }
      if (e.key === 'Enter') document.querySelector('.search-hit')?.click();
    });
    // Ctrl+K (or /) jumps to search, from anywhere outside a text field. In a page's text Ctrl+K
    // makes a web link instead (as in a word processor); that handler has taken the key by then.
    document.addEventListener('keydown', (e) => {
      if (e.defaultPrevented) return;
      const typing = e.target.closest('input, textarea, [contenteditable="true"]');
      if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing)) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });
  },

  async run(query) {
    const q = query.trim();
    const results = document.getElementById('searchResults');
    document.getElementById('sidebarTrees').hidden = !!q;
    results.hidden = !q;
    if (!q) return;
    this.ticket = (this.ticket || 0) + 1;
    const mine = this.ticket;
    let notes = [];
    try { notes = (await api('GET', `/search?q=${encodeURIComponent(q)}`)).notes; } catch (err) { toast(err.message, 'error'); }
    if (mine !== this.ticket) return;
    const words = q.startsWith('#') ? [] : q.toLowerCase().split(/\s+/).filter(Boolean);
    const mark = (text) => {
      if (!words.length || !text) return text;
      const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
      return text.split(re).map((part, i) => (i % 2 ? el('mark', {}, part) : part));
    };
    put(results,
      el('div', { class: 'tree-head' }, el('span', {}, `${notes.length}${notes.length === 30 ? '+' : ''} found`),
        el('button', { class: 'icon-btn', title: 'Clear the search (Esc)', onclick: () => {
          const input = document.getElementById('searchInput'); input.value = ''; this.run(''); input.focus();
        } }, '✕')),
      notes.length ? el('ul', { class: 'search-list' }, notes.map((n) => el('li', {
        class: 'search-hit', tabindex: '0', onclick: () => App.open(n.id),
        onkeydown: (e) => { if (e.key === 'Enter') App.open(n.id); },
      }, el('div', { class: 'search-title' }, noteGlyph(n.type), ' ', mark(n.title)),
      el('div', { class: 'hint' }, [n.space === 'library' ? 'Protocol library' : (n.owner !== NB.person.username ? `${who(n.owner)}'s notebook` : ''),
        n.where].filter(Boolean).join(' › ')),
      n.snippet ? el('div', { class: 'search-snippet' }, mark(n.snippet)) : null)))
        : el('p', { class: 'hint', style: 'padding:.4rem' }, q.startsWith('#') ? 'No notes with that label.' : 'Nothing found. Try fewer words.'));
  },
};

/* --- blocks ------------------------------------------------------------------------ */

/**
 * A gel's lanes in rows of wells, top to bottom, each left to right: a gel may
 * have a comb at the top and more further down. A well joins the row above when
 * it is within ROW_GAP of that row's height (a fraction of the photo's), as
 * the server orders them (app/content.py).
 */
const GEL_ROW_GAP = 0.06;
function gelRows(lanes) {
  const rows = [];
  for (const lane of [...lanes].sort((a, b) => a.y - b.y)) {
    const last = rows[rows.length - 1];
    if (last && lane.y - last.reduce((s, l) => s + l.y, 0) / last.length <= GEL_ROW_GAP) last.push(lane);
    else rows.push([lane]);
  }
  return rows.map((row) => row.sort((a, b) => a.x - b.x));
}


// The colours text can have and be marked with: kept as class names (tc-red, hl-yellow), which the
// notebook's styles, its PDF and its Word documents all know (app/export_*.py has the same values).
const TEXT_COLOURS = { red: '#c62828', orange: '#c2570c', green: '#2b8040', blue: '#1d5fa8', purple: '#7b3fa0', grey: '#6b7280' };
const MARKERS = { yellow: '#fef08a', green: '#bbf7d0', blue: '#bfdbfe', pink: '#fbcfe8' };
// What "no colour" is applied as, to be recognised and taken off again.
const NO_COLOUR = '#010203';
// The marker is switched on and off like a pen: on, what is typed is marked; off, it is plain, even next to marked text.
const Marker = { on: false, colour: 'yellow' };

/* --- attached documents, shown in the page ------------------------------------------- */

/**
 * A note's photos, PDFs, Word, PowerPoint and Excel files and text files, opened over the page rather than
 * in another tab: ‹ › (or the arrow keys) go through the others on the note, ⤓ downloads the original, ↗ opens
 * it in a tab of its own. Other files download, as before.
 */
const Viewer = {
  shows: (a) => !!(a && (a.image || a.preview || a.view)),

  /** Open the attachment with this id; false when it is not one the viewer shows (the caller does as before). */
  open(id) {
    const list = (App.note?.attachments || []).filter(Viewer.shows);
    let at = list.findIndex((a) => a.id === id);
    if (at < 0) return false;
    document.getElementById('docViewer')?.remove();
    const title = el('span', { class: 'viewer-title' });
    const count = el('span', { class: 'viewer-count hint' });
    const stage = el('div', { class: 'viewer-stage' });
    const download = el('a', { class: 'btn btn-secondary btn-sm', title: 'Download the original' }, '⤓ Download');
    const tab = el('a', { class: 'btn btn-secondary btn-sm', target: '_blank', rel: 'noopener', title: 'Open it in a tab of its own' }, '↗ New tab');
    const prev = el('button', { class: 'btn btn-secondary btn-sm', title: 'The one before (←)', onclick: () => go(-1) }, '‹');
    const next = el('button', { class: 'btn btn-secondary btn-sm', title: 'The next one (→)', onclick: () => go(1) }, '›');
    const close = () => { box.remove(); document.removeEventListener('keydown', keys); };
    const box = el('div', { class: 'viewer-backdrop', id: 'docViewer', role: 'dialog', 'aria-modal': 'true' },
      el('div', { class: 'viewer' },
        el('div', { class: 'viewer-head' }, title, count,
          el('span', { class: 'viewer-tools' }, list.length > 1 ? [prev, next] : null, download, tab,
            el('button', { class: 'icon-btn', title: 'Close (Esc)', onclick: close }, '✕'))),
        stage));
    const show = () => {
      const a = list[at];
      title.textContent = a.filename;
      count.textContent = list.length > 1 ? ` ${at + 1} of ${list.length}` : '';
      download.href = attachmentUrl(a.id, true);
      tab.href = a.image ? attachmentUrl(a.id) : viewUrl(a.id);
      if (a.image) { put(stage, el('img', { class: 'viewer-image', src: attachmentUrl(a.id), alt: a.filename })); return; }
      // A Word, PowerPoint or Excel file is turned into a PDF the first time, which can take a moment: it is
      // fetched first (and then shown from the browser's cache), or what went wrong said.
      const waiting = el('p', { class: 'viewer-waiting hint' }, 'Preparing the preview…');
      put(stage, waiting);
      const url = viewUrl(a.id);
      fetch(url, { credentials: 'same-origin' }).then(async (r) => {
        if (!stage.contains(waiting)) return;          // moved on to another one meanwhile
        if (!r.ok) { waiting.textContent = (await r.text()).slice(0, 300) || 'It cannot be shown here: download it.'; return; }
        put(stage, el('iframe', { class: 'viewer-frame', src: url, title: a.filename }));
      }).catch(() => { if (stage.contains(waiting)) waiting.textContent = 'It could not be fetched: download it instead.'; });
    };
    const go = (step) => { at = (at + step + list.length) % list.length; show(); };
    const keys = (e) => {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft' && list.length > 1) go(-1);
      else if (e.key === 'ArrowRight' && list.length > 1) go(1);
    };
    box.addEventListener('mousedown', (e) => { if (e.target === box) close(); });
    document.addEventListener('keydown', keys);
    document.body.append(box);
    show();
    return true;
  },
};
// A plain click opens the viewer; Ctrl/⌘- or middle-clicks still open a tab, as links do.
const plainClick = (e) => e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey;

const Blocks = {
  /** Draw a list of blocks into `container`; `list` is edited in place. */
  renderList(list, container, ctx) {
    put(container, ...list.map((block, i) => this.wrap(block, i, list, container, ctx)));
  },

  wrap(block, index, list, container, ctx) {
    const body = this.render(block, ctx);
    const box = el('div', { class: `block block-${block.type}`, 'data-block': block.id }, body);
    if (ctx.editable) {
      const move = (delta) => {
        const j = index + delta;
        if (j < 0 || j >= list.length) return;
        [list[index], list[j]] = [list[j], list[index]];
        this.renderList(list, container, ctx);
        ctx.changed();
      };
      box.prepend(el('div', { class: 'block-gutter' },
        el('button', { class: 'icon-btn', title: 'Move up', onclick: () => move(-1) }, '↑'),
        el('button', { class: 'icon-btn', title: 'Move down', onclick: () => move(1) }, '↓'),
        el('button', {
          class: 'icon-btn', title: 'Remove this block',
          onclick: () => {
            const empty = block.type === 'text' && !(block.html || '').replace(/<[^>]*>/g, '').trim();
            const go = () => { list.splice(index, 1); this.renderList(list, container, ctx); ctx.changed(); };
            if (empty) { go(); return; }
            modal({
              title: 'Remove this block?',
              build: (b) => b.append(el('p', {}, 'It stays in the page\'s history, and can be brought back from there.')),
              buttons: [{ label: 'Cancel', kind: 'secondary' }, { label: 'Remove', kind: 'danger', onClick: go }],
            });
          },
        }, '✕')));
      // A meeting's agenda ends with a button for one more point: under its last point, or under its heading.
      const isPoint = (b) => b?.type === 'section' && b.source?.kind === 'agenda';
      const isAgendaHead = (b) => b?.type === 'text' && App.note?.type === 'meeting' && /^<h3>Agenda<\/h3>/.test(b.html || '');
      // A task or work package put on a meeting's agenda is part of it too.
      const onAgenda = (b) => isPoint(b) || (b?.type === 'section' && App.note?.type === 'meeting'
        && ['task', 'workpackage'].includes(b.source?.kind));
      if ((onAgenda(block) || isAgendaHead(block)) && !onAgenda(list[index + 1])) {
        box.append(el('button', {
          class: 'btn btn-secondary btn-sm agenda-add', title: 'One more point on the agenda, with room under it for its minutes',
          onclick: () => {
            const point = { id: newId(), type: 'section', title: '', source: { kind: 'agenda' }, blocks: [{ id: newId(), type: 'text', html: '' }] };
            list.splice(index + 1, 0, point);
            this.renderList(list, container, ctx);
            ctx.changed();
            container.querySelector(`[data-block="${point.id}"] .section-title`)?.focus();
          },
        }, '＋ Agenda point'));
      }
    }
    return box;
  },

  /** A click on a link in text: open what it points at, in its tool or here. */
  followLink(e) {
    const link = e.target.closest('a');
    if (!link) return;
    e.preventDefault();
    if (link.dataset.attachment) { if (!(plainClick(e) && Viewer.open(link.dataset.attachment))) window.open(viewUrl(link.dataset.attachment), '_blank', 'noopener'); }
    else if (link.dataset.seed) window.open(seedLink(link.dataset.seed), '_blank', 'noopener');
    else if (link.dataset.stock) window.open(stockLink(link.dataset.stock), '_blank', 'noopener');
    else if (link.dataset.track) window.open(trackLink(link.dataset.track), '_blank', 'noopener');
    else if (link.dataset.task) Projects.openSource({ kind: 'task', id: link.dataset.task });
    else if (link.dataset.plasmid) window.open(editorLink(link.dataset.plasmid), '_blank', 'noopener');
    else if (link.dataset.note) App.open(link.dataset.note);
    else if (/^https?:/.test(link.getAttribute('href') || '')) window.open(link.href, '_blank', 'noopener');
  },

  render(block, ctx) {
    switch (block.type) {
      case 'text': return this.text(block, ctx);
      case 'tasks': return this.tasks(block, ctx);
      case 'table': return this.table(block, ctx);
      case 'steps': return this.steps(block, ctx);
      case 'section': return this.section(block, ctx);
      case 'gel': return this.gel(block, ctx);
      default: return el('div', { class: 'hint' }, `(${block.type})`);
    }
  },

  /* tasks: a week's to-do list ------------------------------------------------- */

  /**
   * A to-do list (app/todos.py): a line of text per task, in which @ links a plasmid, stock, seed
   * lot, track or page as in text; ticked by whom and when. Enter starts the next task, Backspace in
   * an empty one removes it. "→ Next week" moves a task on to next week's list; it stays here,
   * marked, and can be brought back while not done there.
   *
   * Each task is high, medium, low or no ('normal') priority (app/content.py PRIORITIES), changed with the marker
   * at its left; the list is kept grouped high first. Within a level, tasks are put in order by
   * dragging the handle or with Alt+↑ / Alt+↓; dragged or stepped into another level, a task takes
   * that level.
   */
  tasks(block, ctx) {
    const list = el('ul', { class: 'task-list' });
    // A meeting's action items carry a title; a week's to-do list is the page itself, and has none.
    const wrap = el('div', { class: 'tasks' }, block.title ? el('div', { class: 'block-title', text: block.title }) : null, list);
    const dmy = (iso) => String(iso || '').split('-').reverse().join('-');
    const RANK = { high: 0, medium: 1, low: 2, normal: 3 };
    // Clicked, the marker goes up a level: none (kept as 'normal'), low, medium, high, and from high back to none.
    const NEXT_LEVEL = { normal: 'low', low: 'medium', medium: 'high', high: 'normal' };
    const LEVEL_NAME = { high: 'High', medium: 'Medium', normal: 'No', low: 'Low' };
    const level = (item) => (item && item.priority in RANK ? item.priority : 'normal');
    // Grouped high, medium, low, none; each group in its own order, as the server keeps it.
    const regroup = () => {
      const sorted = block.items.map((item, n) => [item, n])
        .sort((a, b) => RANK[level(a[0])] - RANK[level(b[0])] || a[1] - b[1]).map(([item]) => item);
      block.items.splice(0, block.items.length, ...sorted);
    };
    regroup();
    const focusEnd = (area) => {
      if (!area) return;
      area.focus();
      const r = document.createRange();
      r.selectNodeContents(area);
      r.collapse(false);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    };
    const focusTask = (id) => focusEnd(list.children[block.items.findIndex((t) => t.id === id)]?.querySelector('.task-text'));
    const changedOrder = (focusId) => {
      regroup();
      draw();
      ctx.changed();
      if (focusId) focusTask(focusId);
    };
    // A new task: of the level asked, at the end of that level unless placed within it.
    const add = (at, priority = 'normal') => {
      const item = { id: newId(), html: '', priority };
      block.items.splice(at, 0, item);
      changedOrder(item.id);
    };
    // Alt+↑ / Alt+↓: one place up or down; at the edge of its level, into the next level instead.
    const step = (i, dir) => {
      const item = block.items[i];
      const other = block.items[i + dir];
      if (!other) return;
      if (level(other) !== level(item)) item.priority = level(other);
      else moveItem(block.items, i, dir < 0 ? i - 1 : i + 2);
      changedOrder(item.id);
    };
    let dragging = null;
    const clearMarks = () => list.querySelectorAll('.dragging, .drop-before, .drop-after')
      .forEach((n) => n.classList.remove('dragging', 'drop-before', 'drop-after'));
    const below = (e, li) => { const r = li.getBoundingClientRect(); return e.clientY > r.top + r.height / 2; };
    // Moving on and back are done by the notebook, on what is saved: save first, then show the list as it is.
    const act = async (item, how) => {
      const note = App.note;
      await App.flush();
      try {
        const { note: fresh } = await api('POST', `/notes/${note.id}/tasks/${item.id}/${how}`);
        App.show(fresh);
        toast(how === 'move' ? "Moved on to next week's list" : 'Back on this week\'s list', 'success', 2500);
      } catch (err) { toast(err.message, 'error', 6000); }
    };
    // A meeting's action item onto one's to-do list: saved first, then the page shown as it is.
    const takeOn = async (item) => {
      if (!(item.html || '').replace(/<[^>]*>/g, '').trim()) { toast('Write the action item first', 'info'); return; }
      await App.flush();
      try {
        const { note: fresh } = await api('POST', `/notes/${ctx.meeting}/tasks/${item.id}/todo`);
        App.show(fresh);
        toast("On your to-do list of this week", 'success', 2500);
      } catch (err) { toast(err.message, 'error', 6000); }
    };
    const draw = () => put(list, ...block.items.map((item, i) => {
      const done = !!(item.by || item.done);
      const moved = !!item.moved;
      const editable = ctx.editable && !moved;
      const tick = el('span', { class: 'tick', 'data-tick': `${block.id}|${item.id}` },
        done && item.by ? `✓ ${who(item.by)} · ${localTime(item.at)}` : '');
      const box = el('input', {
        type: 'checkbox', checked: done, disabled: !editable, title: moved ? 'Moved on to next week' : '',
        onchange: () => {
          item.done = box.checked;
          if (!box.checked) { item.by = null; item.at = null; }
          li.classList.toggle('done', box.checked);
          tick.textContent = box.checked ? (item.by ? `✓ ${who(item.by)} · ${localTime(item.at)}` : '✓ saving…') : '';
          // A task done does not move on: its "→ Next week" goes, and comes back when unticked.
          if (moveBtn) moveBtn.hidden = box.checked;
          ctx.changed();
        },
      });
      const area = el('div', {
        class: 'task-text', contenteditable: editable ? 'true' : 'false',
        'data-placeholder': editable ? 'A task. Type @ to link a plasmid, stock, seed lot or page.' : '',
      });
      area.innerHTML = item.html || '';          // cleaned by the server
      this.decorateLinks(area);
      area.addEventListener('click', (e) => this.followLink(e));
      if (editable) {
        const sync = () => { item.html = this.storable(area); ctx.changed(); };
        area.addEventListener('input', () => {
          sync();
          const sel = window.getSelection();
          if (!sel.rangeCount) return;
          const range = sel.getRangeAt(0);
          const node = range.startContainer;
          if (node.nodeType === Node.TEXT_NODE && range.startOffset > 0 && node.textContent[range.startOffset - 1] === '@') {
            const at = document.createRange();
            at.setStart(node, range.startOffset - 1);
            at.setEnd(node, range.startOffset);
            this.linkAt(area, at, sync);
          }
        });
        area.addEventListener('keydown', (e) => {
          // The next task is of this one's level, just below it.
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); add(i + 1, level(item)); return; }
          if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
            e.preventDefault();
            step(i, e.key === 'ArrowUp' ? -1 : 1);
            return;
          }
          if (e.key === 'Backspace' && !area.textContent.trim() && !area.querySelector('a, img') && block.items.length > 1) {
            e.preventDefault();
            block.items.splice(i, 1);
            draw();
            ctx.changed();
            focusEnd(list.children[Math.max(0, i - 1)]?.querySelector('.task-text'));
          }
        });
        // A task is one line: pasted text comes in as plain text, its lines joined.
        area.addEventListener('paste', (e) => {
          e.preventDefault();
          document.execCommand('insertText', false, e.clipboardData.getData('text/plain').replace(/\s*[\r\n]+\s*/g, ' '));
        });
      }
      const moveBtn = moved || !ctx.editable || !ctx.todo ? null : el('button', { class: 'btn btn-sm btn-secondary', hidden: done || null,
        title: "Move this task on to next week's to-do list", onclick: () => act(item, 'move') }, '→ Next week');
      const marks = el('div', { class: 'task-marks' }, tick,
        // On a week's to-do list a task moves on to next week; a meeting's action item is carried to its next meeting.
        // On a to-do list, an action item taken from a meeting links back to it.
        item.from_note ? el('span', { class: 'hint' }, ' from ', el('a', { href: `#note=${item.from_note}` },
          item.from_week ? `the meeting of ${dmy(item.from_week)}` : 'a meeting')) :
          item.from_week ? el('span', { class: 'hint' }, ctx.todo ? ` from the week of ${dmy(item.from_week)}`
            : ` from the meeting of ${dmy(item.from_week)}`) : null,
        // On a meeting's page: whose to-do list it is on, ticked there or not.
        (ctx.onTodo?.[item.id] || []).length ? el('span', { class: 'hint on-todo' }, ' · on the to-do list of ',
          ctx.onTodo[item.id].map((t, n) => [n ? ', ' : '', `${who(t.username)}${t.done_at ? ' ✓' : ''}`])) : null,
        moved ? el('span', { class: 'hint' }, ctx.todo ? `→ moved on to the week of ${dmy(item.moved)}`
          : `→ carried to the meeting of ${dmy(item.moved)}`) : null);
      const actions = !ctx.editable ? null : el('span', { class: 'task-actions' },
        moved && ctx.todo ? el('button', { class: 'btn btn-sm btn-secondary', title: "Put it back on this week's list, and take it off next week's",
          onclick: () => act(item, 'back') }, 'Bring back')
          : moveBtn,
        // A meeting's action item, onto one's own to-do list of this week.
        ctx.meeting && !moved && !done && !(ctx.onTodo?.[item.id] || []).some((t) => t.username === NB.person.username)
          ? el('button', { class: 'btn btn-sm btn-secondary', title: "Put this on your to-do list of this week; it says which meeting it came from, and ticking it there shows here",
            onclick: () => takeOn(item) }, '→ My to-do') : null,
        moved ? null : el('button', { class: 'icon-btn', title: 'Remove this task', onclick: () => {
          block.items.splice(i, 1);
          draw();
          ctx.changed();
        } }, '✕'));
      // Its priority: a marker that, clicked, goes None → Low → Medium → High → None.
      const lvl = level(item);
      const priority = editable
        ? el('button', {
          type: 'button', class: `task-priority priority-${lvl}`,
          title: `${LEVEL_NAME[lvl]} priority: click for ${NEXT_LEVEL[lvl] === 'normal' ? 'none' : NEXT_LEVEL[lvl]}`,
          'aria-label': `${LEVEL_NAME[lvl]} priority`,
          onclick: () => { item.priority = NEXT_LEVEL[lvl]; changedOrder(); },
        }, lvl === 'normal' ? '•' : LEVEL_NAME[lvl])
        : (lvl === 'normal' ? null
          : el('span', { class: `task-priority priority-${lvl}`, title: `${LEVEL_NAME[lvl]} priority` }, LEVEL_NAME[lvl]));
      const handle = editable ? el('span', {
        class: 'task-handle', draggable: 'true',
        title: 'Drag to put this task in order (or Alt+↑ / Alt+↓ in it); dropped among another level\'s tasks, it takes that level',
        onclick: (e) => e.stopPropagation(),
        ondragstart: (e) => {
          dragging = i;
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/x-task', String(i));
          e.dataTransfer.setDragImage(li, 12, 12);
          setTimeout(() => li.classList.add('dragging'), 0);
        },
        ondragend: () => { dragging = null; clearMarks(); },
      }, '⋮⋮') : null;
      const li = el('li', {
        class: ['task', `priority-${lvl}`, done ? 'done' : '', moved ? 'moved' : ''].filter(Boolean).join(' '),
        // Only a task of this list being dragged is taken, not a file or another list's task.
        ondragover: (e) => {
          if (dragging === null) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          const after = below(e, li);
          clearMarks();
          list.children[dragging]?.classList.add('dragging');
          li.classList.add(after ? 'drop-after' : 'drop-before');
        },
        ondragleave: (e) => { if (!li.contains(e.relatedTarget)) li.classList.remove('drop-before', 'drop-after'); },
        ondrop: (e) => {
          if (dragging === null) return;
          e.preventDefault();
          const from = dragging;
          const slot = i + (below(e, li) ? 1 : 0);
          dragging = null;
          clearMarks();
          const moving = block.items[from];
          if (!moving) return;
          const levelBefore = level(moving);
          // Dropped by a task of another level: it takes that level.
          moving.priority = level(item);
          if (!moveItem(block.items, from, slot) && levelBefore === level(moving)) return;
          changedOrder();
        },
      }, handle, box, priority, el('div', { class: 'task-body' }, area, marks), actions);
      return li;
    }));
    draw();
    if (ctx.editable) wrap.append(el('button', { class: 'btn btn-sm btn-secondary task-add', onclick: () => add(block.items.length) }, '＋ Task'));
    else if (!block.items.length) list.append(el('li', { class: 'hint' }, 'No tasks yet.'));
    return wrap;
  },

  /* gels ---------------------------------------------------------------------- */

  /**
   * A photo with numbered spots, and a table beside it to say what each is.
   * A gel (order 'rows'): click each well used, and lanes are numbered row by
   * row, top to bottom, each row left to right, whatever order they were
   * clicked in. Plants, colonies and the like (order 'clicks'): numbered in the
   * order they are clicked.
   */
  gel(block, ctx) {
    block.lanes = block.lanes || [];
    const gel = block.order !== 'clicks';
    const words = gel
      ? { one: 'Lane', label: 'Sample', labelHint: 'e.g. pGFP clone 3', noteHint: 'e.g. 5 µL, ladder', mark: '＋ Mark wells',
        markTitle: 'Click wells on the photo to add lanes', none: 'No wells marked', clear: 'Take away all the lanes?',
        title: 'Gel, e.g. Colony PCR, 1% agarose',
        prompt: 'Click each well you loaded, in every row of wells. Lanes are numbered row by row, top to bottom, each row left to right; click a number to take it away.' }
      : { one: 'No.', label: 'Label', labelHint: 'e.g. Col-0 #1', noteHint: 'e.g. resistant, flowering', mark: '＋ Number spots',
        markTitle: 'Click on the photo to number more spots', none: 'Nothing numbered', clear: 'Take away all the numbers?',
        title: 'Photo, e.g. T1 plants on hygromycin',
        prompt: 'Click each one to number it: they are numbered in the order you click. Click a number to take it away.' };
    let marking = !!block._marking && ctx.editable;
    const wrap = el('div', { class: 'gel-block' });
    const marks = new Map();       // lane id -> its number on the photo
    const rows = new Map();        // lane id -> its row in the table
    const light = (id, on) => {
      marks.get(id)?.classList.toggle('lit', on);
      rows.get(id)?.classList.toggle('lit', on);
    };

    const draw = () => {
      const rowsOfWells = gel ? gelRows(block.lanes) : [block.lanes];
      block.lanes = rowsOfWells.flat();
      const rowStarts = new Set(rowsOfWells.slice(1).map((row) => row[0].id));
      marks.clear();
      rows.clear();
      const img = el('img', { src: attachmentUrl(block.attachment), alt: block.title || 'Photo', draggable: 'false' });
      const photo = el('div', { class: `gel-photo${marking ? ' marking' : ''}` }, img);
      block.lanes.forEach((lane, i) => {
        const mark = el('span', {
          class: 'gel-mark', style: `left:${lane.x * 100}%;top:${lane.y * 100}%`,
          title: marking ? `${words.one} ${i + 1}: click to take it away` : `${words.one} ${i + 1}${lane.label ? `: ${lane.label}` : ''}`,
          onclick: (e) => {
            e.stopPropagation();
            if (marking) {
              block.lanes.splice(block.lanes.indexOf(lane), 1);
              draw();
              ctx.changed();
            } else rows.get(lane.id)?.querySelector('input')?.focus();
          },
          onmouseenter: () => light(lane.id, true), onmouseleave: () => light(lane.id, false),
        }, String(i + 1));
        marks.set(lane.id, mark);
        photo.append(mark);
      });
      if (marking) {
        photo.addEventListener('click', (e) => {
          const r = img.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width;
          const y = (e.clientY - r.top) / r.height;
          if (!(x >= 0 && x <= 1 && y >= 0 && y <= 1)) return;
          block.lanes.push({ id: newId(), x, y, label: '', note: '' });
          draw();
          ctx.changed();
        });
      }

      const cell = (lane, key, placeholder) => (ctx.editable
        ? el('input', { type: 'text', class: 'cell', value: lane[key] || '', placeholder,
          oninput: (e) => { lane[key] = e.target.value; marks.get(lane.id).title = `${words.one} ${block.lanes.indexOf(lane) + 1}: ${lane.label}`; ctx.changed(); },
          onfocus: () => light(lane.id, true), onblur: () => light(lane.id, false),
          onkeydown: (e) => {
            // Enter goes to the next one's label, as in a spreadsheet.
            if (e.key === 'Enter') { e.preventDefault(); rows.get(block.lanes[block.lanes.indexOf(lane) + 1]?.id)?.querySelector('input')?.focus(); }
          } })
        : el('span', { text: lane[key] || '' }));
      const table = block.lanes.length
        ? el('table', { class: 'sheet gel-lanes' },
          el('thead', {}, el('tr', {}, el('th', {}, words.one), el('th', {}, words.label), el('th', {}, 'Notes'))),
          el('tbody', {}, block.lanes.map((lane, i) => {
            const row = el('tr', { class: rowStarts.has(lane.id) ? 'gel-row-start' : null,
              title: rowStarts.has(lane.id) ? 'The next row of wells starts here' : null,
              onmouseenter: () => light(lane.id, true), onmouseleave: () => light(lane.id, false) },
              el('td', { class: 'gel-lane-no' }, String(i + 1)),
              el('td', {}, cell(lane, 'label', words.labelHint)),
              el('td', {}, cell(lane, 'note', words.noteHint)));
            rows.set(lane.id, row);
            return row;
          })))
        : el('p', { class: 'hint' }, `${words.none}${ctx.editable ? ' yet' : ''}.`);

      put(wrap,
        el('div', { class: 'table-head' },
          ctx.editable
            ? el('input', { type: 'text', class: 'block-title', value: block.title || '', placeholder: words.title,
              oninput: (e) => { block.title = e.target.value; ctx.changed(); } })
            : (block.title ? el('div', { class: 'block-title', text: block.title }) : el('span')),
          ctx.editable ? el('span', { class: 'table-tools' },
            !marking && block.attachment ? el('button', { class: 'btn btn-sm btn-secondary',
              title: 'Draw, write and number on the photo (the photo is kept as it is)',
              onclick: () => App.markUp(block.attachment, { block }) }, glyph('pencil'), ' Mark up') : null,
            el('button', { class: `btn btn-sm ${marking ? 'btn-primary' : 'btn-secondary'}`,
              title: marking ? 'Stop numbering' : words.markTitle,
              onclick: () => { marking = !marking; block._marking = marking; draw(); } }, marking ? 'Done' : words.mark),
            marking && block.lanes.length ? el('button', { class: 'btn btn-sm btn-secondary', title: 'Take away every number',
              onclick: () => {
                modal({ title: words.clear, build: (b) => b.append(el('p', {}, 'What was written for them goes too.')),
                  buttons: [{ label: 'Cancel', kind: 'secondary' }, { label: 'Take them away', kind: 'danger', onClick: () => { block.lanes = []; draw(); ctx.changed(); } }] });
              } }, 'Clear') : null) : null),
        marking ? el('p', { class: 'gel-prompt' }, words.prompt) : null,
        el('div', { class: 'gel-layout' }, photo, el('div', { class: 'gel-side' }, table)));
    };
    draw();
    return wrap;
  },

  /* text --------------------------------------------------------------------- */

  text(block, ctx) {
    const area = el('div', {
      class: 'text-block', contenteditable: ctx.editable ? 'true' : 'false',
      'data-placeholder': ctx.editable ? ctx.placeholder || 'Write here. Type @ to link a plasmid or a note.' : '',
    });
    area.innerHTML = block.html || '';          // cleaned by the server
    this.decorateLinks(area);
    area.addEventListener('click', (e) => {
      const photo = e.target.closest('img[data-attachment]');
      if (photo && ctx.editable) { App.photoMenu(photo); return; }
      if (photo) { if (!Viewer.open(photo.dataset.attachment)) window.open(attachmentUrl(photo.dataset.attachment), '_blank', 'noopener'); return; }
      this.followLink(e);
    });
    if (!ctx.editable) return area;

    const sync = () => { block.html = this.storable(area); ctx.changed(); };
    area.addEventListener('input', () => {
      this.keepTabsAlone(area);
      sync();
      // "@" opens the link picker, as in Trilium's autocomplete.
      const sel = window.getSelection();
      if (!sel.rangeCount) return;
      const range = sel.getRangeAt(0);
      const node = range.startContainer;
      if (node.nodeType === Node.TEXT_NODE && range.startOffset > 0 && node.textContent[range.startOffset - 1] === '@') {
        const at = document.createRange();
        at.setStart(node, range.startOffset - 1);
        at.setEnd(node, range.startOffset);
        this.linkAt(area, at, sync);
      }
    });
    // Pasted text keeps its formatting: paragraphs, headings, lists, bold and the rest of what the
    // notebook itself writes, so a note copied into another page arrives as it was, its links to
    // plasmids, stocks and notes with it. Anything outside that subset is dropped.
    // A table copied from a spreadsheet or a web page becomes a table, where it was pasted.
    // A pasted picture (a screenshot, say) is attached to the note and shown where it was pasted.
    area.addEventListener('paste', (e) => {
      e.preventDefault();
      // First: Excel copies a picture of the cells too, which is not what is meant.
      const grid = Clip.grid(e.clipboardData);
      if (grid && (grid.length > 1 || grid[0].length > 1)) { App.pasteTable(block, area, grid); return; }
      const files = [...(e.clipboardData.files || [])];
      if (files.length) { App.attachHere(area, files, sync); return; }
      const html = e.clipboardData.getData('text/html');
      // An address copied on its own still links what is selected, rather than replacing it.
      if (this.pasteAddress(area, e.clipboardData)) { sync(); return; }
      // A list the copy marks up as one comes through as it is; Word writes its bullets as
      // characters instead, which Clip reads back into a list.
      if (!/<\s*(ul|ol)\b/i.test(html)) {
        const listed = Clip.lists(e.clipboardData.getData('text/plain'));
        if (listed) { document.execCommand('insertHTML', false, this.listHtml(listed)); sync(); return; }
      }
      const rich = this.richerThanText(html) ? this.richFromHtml(html) : null;
      // Links pasted in are shown and opened like the rest at once, not only after the next draw.
      if (rich) { document.execCommand('insertHTML', false, rich); this.decorateLinks(area); sync(); return; }
      // Web links survive: copied from a page or note, or an address pasted on its own.
      if (this.pasteWithLinks(area, e.clipboardData)) { sync(); return; }
      document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
    });
    // Ctrl+K (Cmd+K): a web link for the selected text.
    area.addEventListener('keydown', (e) => {
      if (e.key.toLowerCase() !== 'k' || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
      e.preventDefault();
      const bar = document.getElementById('formatBar');
      if (bar) this.webLinkBox(area, sync, bar);
    });
    // Photos and files dragged in are attached where they are dropped.
    area.addEventListener('dragover', (e) => {
      if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); area.classList.add('drop-files'); }
    });
    area.addEventListener('dragleave', () => area.classList.remove('drop-files'));
    area.addEventListener('drop', (e) => {
      if (!e.dataTransfer.files.length) return;
      e.preventDefault();
      area.classList.remove('drop-files');
      const at = document.caretRangeFromPoint?.(e.clientX, e.clientY);
      if (at) { const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(at); }
      App.attachHere(area, [...e.dataTransfer.files], sync);
    });
    // Tab works as in a word processor: in a list it moves the item in a level (Shift+Tab out),
    // elsewhere it puts in a tab (Shift+Tab takes back the one just before the cursor).
    area.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab' || e.ctrlKey || e.metaKey || e.altKey) return;
      e.preventDefault();
      const sel = window.getSelection();
      if (!sel.rangeCount) return;
      const range = sel.getRangeAt(0);
      const { startContainer: node, startOffset: at } = range;
      const inside = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      const item = inside.closest('li');
      if (item && area.contains(item)) document.execCommand(e.shiftKey ? 'outdent' : 'indent');
      else if (!e.shiftKey) document.execCommand('insertHTML', false, '<span class="tab">\t</span>');
      else {
        // The tab just before the cursor: the cursor at the end of its span, or right after it.
        const before = inside.closest('span.tab')
          || (node.nodeType === Node.TEXT_NODE ? (at === 0 ? node.previousSibling : null) : node.childNodes[at - 1]);
        if (!range.collapsed || !before?.classList?.contains('tab')) return;
        range.selectNode(before);
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand('delete');
      }
      this.keepTabsAlone(area);
      sync();
    });
    // Typing with the marker on marks what is typed; with it off, typing in or next to marked text is plain.
    // A line begun with "- " becomes a bulleted list, and one begun with "1. " a numbered list, as the
    // first character after it is typed.
    area.addEventListener('beforeinput', (e) => {
      if (e.inputType !== 'insertText' || !e.data) return;
      if (Blocks.startBullet(area, e.data)) {
        e.preventDefault();
        if (!Blocks.typeWithMarker(area, e.data)) document.execCommand('insertText', false, e.data);
        sync();
      } else if (Blocks.typeWithMarker(area, e.data)) { e.preventDefault(); sync(); }
    });
    area.addEventListener('focus', () => {
      // New lines as paragraphs, which are kept, rather than the browser's <div>s.
      document.execCommand('defaultParagraphSeparator', false, 'p');
      App.showFormatBar(area, sync);
    });
    return area;
  },

  /**
   * What the browser's own formatting makes, as the notebook keeps it: a colour as <span class="tc-…">,
   * a marker as <mark class="hl-…">, strike-through as <s>. "No colour" inside a coloured stretch keeps the
   * ordinary colour (tc-none, hl-none); elsewhere it is simply taken off.
   */
  tidyFormatting(area) {
    const kept = this.selectionOffsets(area);
    this.tidyNodes(area);
    if (kept) this.selectOffsets(area, kept);
  },

  /**
   * The selected text given one highlight (kind 'mark') or one colour of letters (kind 'colour'), whatever
   * highlights or colours its parts had: each part is taken out of them first, then given the one chosen
   * ('none': left plain), and pieces alike that end up side by side are joined. False without a selection.
   */
  restyle(area, kind, name) {
    const kept = this.selectionOffsets(area);
    if (!kept || kept[0] === kept[1]) return false;
    const [start, end] = kept;
    const is = kind === 'mark' ? (n) => n.tagName === 'MARK' : (n) => n.tagName === 'SPAN' && /(^|\s)tc-/.test(n.className);
    // The selected text, as whole text nodes.
    const all = [];
    const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) all.push(n);
    const nodes = [];
    let pos = 0;
    for (let n of all) {
      const from = pos;
      const to = pos + n.length;
      pos = to;
      if (to <= start || from >= end || !n.length) continue;
      if (end < to) n.splitText(end - from);
      if (start > from) n = n.splitText(start - from);
      nodes.push(n);
    }
    const anything = (fragment) => fragment.textContent || fragment.querySelector('img');
    for (const node of nodes) {
      // Out of every highlight (or colour) around it: what was before and after it in one keeps it.
      for (let m = node.parentElement; m && m !== area; m = node.parentElement) {
        while (m && m !== area && !is(m)) m = m.parentElement;
        if (!m || m === area) break;
        const before = document.createRange();
        before.setStart(m, 0);
        before.setEndBefore(node);
        const head = before.extractContents();
        if (anything(head)) { const c = m.cloneNode(false); c.append(head); m.before(c); }
        const after = document.createRange();
        after.setStartAfter(node);
        after.setEnd(m, m.childNodes.length);
        const tail = after.extractContents();
        if (anything(tail)) { const c = m.cloneNode(false); c.append(tail); m.after(c); }
        m.replaceWith(...m.childNodes);
      }
      if (name !== 'none') {
        const wrap = kind === 'mark' ? el('mark', { class: `hl-${name}` }) : el('span', { class: `tc-${name}` });
        node.before(wrap);
        wrap.append(node);
      }
    }
    // Alike neighbours joined, empty ones gone.
    for (const x of area.querySelectorAll('mark, span[class^="tc-"]')) {
      if (!x.isConnected) continue;
      while (x.nextSibling?.nodeType === Node.ELEMENT_NODE && x.nextSibling.tagName === x.tagName && x.nextSibling.className === x.className) {
        const next = x.nextSibling;
        x.append(...next.childNodes);
        next.remove();
      }
      if (!x.textContent && !x.querySelector('img')) x.remove();
    }
    area.normalize();
    this.selectOffsets(area, kept);
    return true;
  },

  /** The selection in a text area as character counts from its start, to put it back after the text is rebuilt. */
  selectionOffsets(area) {
    const sel = window.getSelection();
    if (!sel.rangeCount || !area.contains(sel.anchorNode)) return null;
    const range = sel.getRangeAt(0);
    const count = (node, offset) => {
      const r = document.createRange();
      r.setStart(area, 0);
      r.setEnd(node, offset);
      return r.toString().length;
    };
    return [count(range.startContainer, range.startOffset), count(range.endContainer, range.endOffset)];
  },

  selectOffsets(area, [start, end]) {
    const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let seen = 0;
    let n;
    let started = false;
    while ((n = walker.nextNode())) {
      const len = n.textContent.length;
      if (!started && start <= seen + len) { range.setStart(n, start - seen); started = true; }
      if (started && end <= seen + len) { range.setEnd(n, end - seen); break; }
      seen += len;
    }
    if (!started) return;
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  },

  tidyNodes(area) {
    const rgb = (value) => {
      const m = String(value || '').match(/\d+/g);
      return m && m.length >= 3 ? `#${m.slice(0, 3).map((n) => Number(n).toString(16).padStart(2, '0')).join('')}` : String(value || '').toLowerCase();
    };
    const named = (hex, colours) => (hex === NO_COLOUR ? 'none' : Object.keys(colours).find((k) => colours[k] === hex) || null);
    const swap = (old, tag, cls, inside) => {
      if (!cls || (cls.endsWith('-none') && !old.parentElement.closest(inside))) { old.replaceWith(...old.childNodes); return; }
      const node = document.createElement(tag);
      node.className = cls;
      node.append(...old.childNodes);
      old.replaceWith(node);
    };
    for (const strike of area.querySelectorAll('strike')) {
      const s = document.createElement('s');
      s.append(...strike.childNodes);
      strike.replaceWith(s);
    }
    for (const font of area.querySelectorAll('font')) {
      const name = named(rgb(font.getAttribute('color')), TEXT_COLOURS);
      swap(font, 'span', name && `tc-${name}`, '[class^="tc-"]:not(.tc-none)');
    }
    // A colour the browser put on an element as a style (on a span of its own, or on what was there already).
    const within = (node, tag, cls) => {
      const inner = document.createElement(tag);
      inner.className = cls;
      inner.append(...node.childNodes);
      node.append(inner);
      return inner;
    };
    for (const node of area.querySelectorAll('[style]')) {
      const fore = node.style.color && named(rgb(node.style.color), TEXT_COLOURS);
      const back = node.style.backgroundColor && named(rgb(node.style.backgroundColor), MARKERS);
      node.removeAttribute('style');
      if (back && node.tagName === 'MARK') {
        if (back === 'none' && !node.parentElement.closest('mark:not(.hl-none)')) { node.replaceWith(...node.childNodes); continue; }
        node.className = `hl-${back}`;
      } else if (back) {
        if (back !== 'none' || node.parentElement.closest('mark:not(.hl-none)')) within(node, 'mark', `hl-${back}`);
      }
      if (fore && node.isConnected) {
        if (node.tagName === 'SPAN' && !node.classList.contains('tab')) node.className = `tc-${fore}`;
        else within(node, 'span', `tc-${fore}`);
        if (fore === 'none' && !node.parentElement.closest('[class^="tc-"]:not(.tc-none)')) {
          const tagged = node.tagName === 'SPAN' ? node : node.lastChild;
          tagged.replaceWith(...tagged.childNodes);
        }
      }
      if (node.isConnected && node.tagName === 'SPAN' && !node.className) node.replaceWith(...node.childNodes);
    }
    // Highlighting taken off part of a highlight: the highlight split around it, that part plain.
    for (const none of area.querySelectorAll('mark.hl-none')) {
      const outer = none.parentElement;
      if (outer.tagName !== 'MARK' || outer.classList.contains('hl-none')) {
        if (!outer.closest('mark:not(.hl-none)')) none.replaceWith(...none.childNodes);
        continue;
      }
      const after = outer.cloneNode(false);
      while (none.nextSibling) after.append(none.nextSibling);
      const plain = [...none.childNodes];
      none.remove();
      outer.after(...plain, after);
    }
    // Nothing left in it: gone.
    for (const node of area.querySelectorAll('mark, span[class^="tc-"]')) if (!node.textContent) node.remove();
  },

  /**
   * Text typed where the marker's being on or off says otherwise than where the cursor is: with the marker on
   * outside marked text, the text goes in marked; with it off inside marked text, the marking is split there
   * and the text goes in between, plain. False when the browser can type it as usual.
   */
  /**
   * With the cursor just after a "- " that begins a line (not already in a list), and something other
   * than a space being typed: takes the "- " away and makes the line a bulleted list item. True if it did.
   */
  startBullet(area, typed) {
    if (/^\s/.test(typed)) return false;
    const sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return false;
    const { startContainer: node, startOffset: at } = sel.getRangeAt(0);
    if (node.nodeType !== Node.TEXT_NODE || !area.contains(node)) return false;
    // "- " starts a bulleted list, "1. " or "1) " a numbered one.
    const begun = node.textContent.slice(0, at);
    const numbered = /^1[.)][  ]$/.test(begun);
    if (!numbered && !/^-[  ]$/.test(begun)) return false;
    if (node.parentElement.closest('li, pre, code, td, th')) return false;
    // The "- " must begin the line: nothing before it but the start of a block or a line break.
    for (let n = node; n !== area; n = n.parentNode) {
      const before = n.previousSibling;
      if (before) { if (before.nodeName !== 'BR') return false; break; }
      if (/^(DIV|P|H[1-6]|BLOCKQUOTE)$/.test(n.parentNode.nodeName)) break;
    }
    const dash = document.createRange();
    dash.setStart(node, 0);
    dash.setEnd(node, at);
    sel.removeAllRanges();
    sel.addRange(dash);
    document.execCommand('delete');
    document.execCommand(numbered ? 'insertOrderedList' : 'insertUnorderedList');
    return true;
  },

  // --- Web links -------------------------------------------------------------

  /** A typed or pasted address as a link target, or null: http(s), mailto, www. and bare emails. */
  webAddress(text) {
    const t = String(text || '').trim();
    if (!t || /\s/.test(t)) return null;
    if (/^https?:\/\/[^\s<>"]+$/i.test(t)) return t;
    if (/^mailto:[^\s@<>"]+@[^\s@<>"]+$/i.test(t)) return t;
    if (/^www\.[^\s<>"]+\.[^\s<>"]+$/i.test(t)) return 'https://' + t;
    if (/^[^\s@<>"/:]+@[^\s@<>"/]+\.[a-z]{2,}$/i.test(t)) return 'mailto:' + t;
    // A bare domain typed into the link box: example.org/path
    if (/^[a-z0-9-]+(\.[a-z0-9-]+)+(\/[^\s<>"]*)?$/i.test(t)) return 'https://' + t;
    return null;
  },

  escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  /**
   * Pasted text with lists in it (Clip.lists) as HTML: each run of items a bulleted or numbered list,
   * nested by level, ordinary lines as paragraphs, and web addresses in either made links.
   */
  listHtml(blocks) {
    const inline = (text) => this.linkifiedHtml(text) || this.escapeHtml(text);
    let html = '';
    for (const block of blocks) {
      if (block.type === 'text') {
        html += block.text.trim() ? `<p>${inline(block.text)}</p>` : '';
        continue;
      }
      // A stack of open lists, one per level; a deeper item opens a list inside the item before it.
      const open = [];
      for (const item of block.items) {
        const level = Math.min(item.level, open.length);   // never skip a level
        while (open.length > level + 1) html += `</li></${open.pop()}>`;
        if (open.length === level + 1) html += '</li>';
        else {
          const tag = (level === 0 ? block.ordered : item.ordered) ? 'ol' : 'ul';
          html += `<${tag}>`;
          open.push(tag);
        }
        html += `<li>${inline(item.text)}`;
      }
      while (open.length) html += `</li></${open.pop()}>`;
    }
    return html;
  },

  /** Plain text with each web address in it made a link, as HTML; null when it has none. */
  linkifiedHtml(text) {
    const pattern = /\b(https?:\/\/[^\s<>"]+|www\.[^\s<>"]+\.[^\s<>"]+|[^\s@<>"()]+@[^\s@<>"()]+\.[a-z]{2,})/gi;
    let found = false;
    const html = String(text).split(/\r?\n/).map((line) => {
      let out = '';
      let from = 0;
      line.replace(pattern, (match, _m, at) => {
        // A full stop or bracket just after an address is the sentence's, not the address's.
        const core = match.replace(/[.,;:!?)\]]+$/, '');
        const href = this.webAddress(core);
        if (!href) return match;
        found = true;
        out += this.escapeHtml(line.slice(from, at)) + `<a href="${this.escapeHtml(href)}">${this.escapeHtml(core)}</a>`;
        from = at + core.length;
        return match;
      });
      return out + this.escapeHtml(line.slice(from));
    }).join('<br>');
    return found ? html : null;
  },

  /**
   * The tags kept from a paste, by what the server keeps (app/content.py TEXT_TAGS): what the
   * clipboard calls them on the left, what the notebook writes on the right. A heading below h3
   * becomes an h3, and a <div> a paragraph, as a line typed here does.
   */
  PASTE_TAGS: {
    P: 'p', DIV: 'p', BR: 'br', HR: 'hr', B: 'b', STRONG: 'strong', I: 'i', EM: 'em', U: 'u',
    S: 's', STRIKE: 's', DEL: 's', SUB: 'sub', SUP: 'sup', H1: 'h1', H2: 'h2', H3: 'h3',
    H4: 'h3', H5: 'h3', H6: 'h3', UL: 'ul', OL: 'ol', LI: 'li', A: 'a', CODE: 'code', TT: 'code',
    PRE: 'pre', BLOCKQUOTE: 'blockquote', SPAN: 'span', FONT: 'span', MARK: 'mark', IMG: 'img',
  },
  // Only the notebook's own classes survive a paste: a colour, a marker, a tab.
  KEPT_CLASS: /^(tc-|hl-)[a-z]+$|^tab$/,

  /**
   * HTML from the clipboard (another note, a web page, an email, Word) as the notebook keeps it:
   * paragraphs, headings, lists, bold, italic and the rest of the subset the server allows, and the
   * notebook's own links to plasmids, notes, stocks and attachments. Scripts, styles, colours from
   * elsewhere and every other attribute are dropped. `inline` leaves out the block tags, for a step
   * or a table cell, which are one line. Null when nothing is left.
   */
  richFromHtml(html, { inline = false } = {}) {
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    const BLOCK = /^(P|DIV|H[1-6]|UL|OL|LI|PRE|BLOCKQUOTE|HR)$/;
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) return this.escapeHtml(node.textContent.replace(/[\t\r\n]+/g, ' '));
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      const name = node.nodeName;
      if (/^(SCRIPT|STYLE|HEAD|TITLE|META|LINK|TEMPLATE|NOSCRIPT)$/.test(name)) return '';
      let inner = [...node.childNodes].map(walk).join('');
      // What the clipboard says with a style rather than a tag: Word and Google Docs both do.
      const style = node.getAttribute?.('style') || '';
      const weight = /font-weight:\s*(bold|[6-9]00)/i.test(style);
      const italic = /font-style:\s*italic/i.test(style);
      const under = /text-decoration[^;]*underline/i.test(style);
      const struck = /text-decoration[^;]*line-through/i.test(style);
      let tag = this.PASTE_TAGS[name];
      if (inline && (!tag || BLOCK.test(name) || tag === 'br' || tag === 'img')) {
        // A step and a cell are one line: a block's words come through, the block itself does not.
        tag = null;
      }
      let out;
      if (!tag) out = inner;
      else if (tag === 'img') {
        // Only a picture already attached to a note: the server names pictures by attachment, never
        // by address, so one from a web page cannot be kept.
        const att = node.getAttribute('data-attachment');
        out = att ? `<img data-attachment="${this.escapeHtml(att)}">` : '';
      } else if (tag === 'br' || tag === 'hr') out = `<${tag}>`;
      else if (tag === 'a') {
        const data = ['note', 'plasmid', 'seed', 'stock', 'track', 'task', 'attachment']
          .filter((k) => node.getAttribute(`data-${k}`))
          .map((k) => ` data-${k}="${this.escapeHtml(node.getAttribute(`data-${k}`))}"`).join('');
        const href = data ? '' : this.webAddress(node.getAttribute('href') || '');
        if (!inner.trim()) out = '';
        else if (data) out = `<a${data}>${inner}</a>`;
        else if (href) out = `<a href="${this.escapeHtml(href)}">${inner}</a>`;
        else out = inner;
      } else {
        const cls = (node.getAttribute('class') || '').split(/\s+/).filter((c) => this.KEPT_CLASS.test(c));
        if ((tag === 'span' || tag === 'mark') && !cls.length && !weight && !italic && !under && !struck) {
          out = inner;                                   // a span carrying nothing is not worth keeping
        } else if (!inner.trim() && tag !== 'li') {
          out = '';
        } else {
          const attr = cls.length ? ` class="${this.escapeHtml(cls.join(' '))}"` : '';
          out = `<${tag}${attr}>${inner}</${tag}>`;
        }
      }
      if (out && tag !== 'img') {
        for (const [on, wrap] of [[weight, 'b'], [italic, 'i'], [under, 'u'], [struck, 's']]) {
          if (on && !new RegExp(`^<${wrap}>`).test(out)) out = `<${wrap}>${out}</${wrap}>`;
        }
      }
      // A block that is not kept still ends what came before it: on its own line in text, and as the
      // space between the words in a step or a cell, which are one line.
      if (!tag && BLOCK.test(name) && out.trim()) out += inline ? ' ' : '<br>';
      return out;
    };
    const out = walk(doc.body).replace(/(\s|<br>)+$/, '').replace(/^(\s|<br>)+/, '');
    return out.trim() ? (inline ? out.replace(/ {2,}/g, ' ') : out) : null;
  },

  /** True when a paste holds more than its plain words: formatting, a list, or a link worth keeping. */
  richerThanText(html) {
    return /<\s*(p|div|h[1-6]|ul|ol|li|b|strong|i|em|u|s|strike|del|sub|sup|code|pre|blockquote|mark|img|a|br|hr)\b/i
      .test(String(html || ''));
  },

  /**
   * HTML from the clipboard (a web page, an email, another note) reduced to its text and its web links,
   * as HTML; null when it holds no link worth keeping. Styles, scripts and everything else are dropped,
   * as with any paste; blocks become line breaks.
   */
  linksFromHtml(html) {
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    let found = false;
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) return this.escapeHtml(node.textContent.replace(/\s+/g, ' '));
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      const tag = node.nodeName;
      if (/^(SCRIPT|STYLE|HEAD|TITLE|META|LINK|TEMPLATE)$/.test(tag)) return '';
      const inner = [...node.childNodes].map(walk).join('');
      if (tag === 'A') {
        const href = this.webAddress(node.getAttribute('href') || '');
        if (href && inner.trim()) { found = true; return `<a href="${this.escapeHtml(href)}">${inner}</a>`; }
        return inner;
      }
      if (tag === 'BR') return '<br>';
      if (/^(P|DIV|LI|TR|H[1-6]|BLOCKQUOTE|PRE|SECTION|ARTICLE|UL|OL|TABLE)$/.test(tag)) return inner.trim() ? inner + '<br>' : inner;
      return inner;
    };
    const out = walk(doc.body).replace(/(<br>\s*)+$/, '').replace(/^\s+/, '');
    return found ? out : null;
  },

  /**
   * Pastes text so that web links survive: links copied from a page or another note stay links, an
   * address pasted alone becomes one (onto the selection, when text is selected), and an address in
   * pasted text is made one. True when it pasted; false leaves the paste to the plain-text default.
   */
  /**
   * An address pasted on its own: a link on the selected text, or the address as a link.
   * True when it pasted. Tried before the formatting, so pasting a link onto a word still
   * links the word rather than replacing it.
   */
  pasteAddress(area, data) {
    const text = data.getData('text/plain');
    const sel = window.getSelection();
    const href = this.webAddress(text);
    if (!href) return false;
    if (sel.rangeCount && !sel.isCollapsed && area.contains(sel.anchorNode)) {
      document.execCommand('createLink', false, href);
      return true;
    }
    document.execCommand('insertHTML', false, `<a href="${this.escapeHtml(href)}">${this.escapeHtml(text.trim())}</a>`);
    return true;
  },

  pasteWithLinks(area, data) {
    const text = data.getData('text/plain');
    if (this.pasteAddress(area, data)) return true;
    const fromHtml = this.linksFromHtml(data.getData('text/html'));
    if (fromHtml) { document.execCommand('insertHTML', false, fromHtml); return true; }
    const linked = this.linkifiedHtml(text);
    if (linked) { document.execCommand('insertHTML', false, linked); return true; }
    return false;
  },

  /**
   * The link box under the formatting bar: an address for the selected text, which adds the link or,
   * on text already linked, changes or removes it. Ctrl+K opens it too.
   */
  webLinkBox(area, sync, bar) {
    const sel = window.getSelection();
    if (!sel.rangeCount || !area.contains(sel.anchorNode)) return;
    const range = sel.getRangeAt(0).cloneRange();
    const inside = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
    const existing = inside.closest('a[href]');
    const linkedHere = existing && area.contains(existing) && !existing.dataset.note && !existing.dataset.task && !existing.dataset.plasmid
      && !existing.dataset.seed && !existing.dataset.stock && !existing.dataset.track && !existing.dataset.attachment ? existing : null;
    bar.querySelector('.link-box')?.remove();
    const input = el('input', { type: 'text', placeholder: 'https://… or an email address', value: linkedHere ? linkedHere.getAttribute('href') : '',
                                'aria-label': 'Web address', spellcheck: 'false' });
    const note = el('span', { class: 'link-box-note' });
    const restore = () => { sel.removeAllRanges(); sel.addRange(range); };
    const close = () => { box.remove(); area.focus({ preventScroll: true }); restore(); };
    const apply = () => {
      const href = this.webAddress(input.value);
      if (!href) { note.textContent = 'Not a web or email address.'; input.focus(); return; }
      area.focus({ preventScroll: true });
      restore();
      if (linkedHere) {
        linkedHere.setAttribute('href', href);
      } else if (range.collapsed) {
        document.execCommand('insertHTML', false, `<a href="${this.escapeHtml(href)}">${this.escapeHtml(input.value.trim())}</a>`);
      } else {
        document.execCommand('createLink', false, href);
      }
      box.remove();
      sync();
    };
    const unlink = () => {
      area.focus({ preventScroll: true });
      if (linkedHere) {
        const r = document.createRange();
        r.selectNodeContents(linkedHere);
        sel.removeAllRanges();
        sel.addRange(r);
      } else restore();
      document.execCommand('unlink');
      box.remove();
      sync();
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); apply(); }
      if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
    const box = el('div', { class: 'link-box' }, input,
      el('button', { type: 'button', class: 'primary', onmousedown: (e) => { e.preventDefault(); apply(); } }, linkedHere ? 'Change' : 'Link'),
      linkedHere ? el('button', { type: 'button', onmousedown: (e) => { e.preventDefault(); unlink(); } }, 'Remove link') : null,
      el('button', { type: 'button', onmousedown: (e) => { e.preventDefault(); close(); } }, 'Cancel'), note);
    bar.append(box);
    input.focus();
    input.select();
  },

  typeWithMarker(area, text) {
    const sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed || !area.contains(sel.anchorNode)) return false;
    const range = sel.getRangeAt(0);
    const inside = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
    const mark = inside.closest('mark:not(.hl-none)');
    const marked = !!(mark && area.contains(mark));
    // Just after marked text (at the end of a line, say), a browser would carry on in it: decided here instead.
    const before = !marked && range.startContainer.nodeType === Node.ELEMENT_NODE && range.startOffset > 0
      ? range.startContainer.childNodes[range.startOffset - 1] : null;
    // A space put in by hand at the end of a line would not show (nor keep the cursor): a fixed one does.
    const typed = document.createTextNode(text.replace(/ /g, '\u00a0'));
    if (before?.nodeType === Node.ELEMENT_NODE && before.matches('mark:not(.hl-none)')) {
      if (Marker.on) before.append(typed); else before.after(typed);
    } else if (Marker.on === marked) return false;
    else if (Marker.on) {
      const node = el('mark', { class: `hl-${Marker.colour}` }, typed);
      range.insertNode(node);
    } else {
      // What comes after the cursor stays marked, in a mark of its own after the typed text.
      const rest = document.createRange();
      rest.setStart(range.startContainer, range.startOffset);
      rest.setEnd(mark, mark.childNodes.length);
      const after = mark.cloneNode(false);
      after.append(rest.extractContents());
      mark.after(typed);
      if (after.textContent) typed.after(after);
      if (!mark.textContent) mark.remove();
    }
    const caret = document.createRange();
    caret.setStart(typed, typed.length);
    caret.collapse(true);
    sel.removeAllRanges();
    sel.addRange(caret);
    for (const node of area.querySelectorAll('mark')) if (!node.textContent) node.remove();
    return true;
  },

  /**
   * One line as it is kept: a step or a table cell. The same letter formatting as text, with no
   * paragraphs, lists or pictures, which the server would drop anyway (app/content.py INLINE_TAGS).
   */
  storableInline(area) {
    const copy = area.cloneNode(true);
    this.tidyNodes(copy);
    // A block the browser made (Enter, or a paste) leaves its words behind, on the one line.
    for (const node of [...copy.querySelectorAll('p, div, li, ul, ol, h1, h2, h3, pre, blockquote, br, img, hr')].reverse()) {
      node.replaceWith(...(node.tagName === 'BR' ? [document.createTextNode(' ')] : node.childNodes));
    }
    for (const a of copy.querySelectorAll('a[data-plasmid], a[data-note], a[data-seed], a[data-stock], a[data-track], a[data-task], a[data-attachment]')) {
      for (const attr of ['href', 'class', 'title']) a.removeAttribute(attr);
    }
    return copy.innerHTML.replace(/\s+/g, ' ').trim();
  },

  /**
   * A one-line box that takes formatting: a step, or a table cell. The same formatting bar as text,
   * and the same paste, kept to one line. `onInput` is given the line as it will be kept.
   */
  inlineEditor(attrs, html, { onInput, editable = true }) {
    const area = el('div', { ...attrs, contenteditable: editable ? 'true' : 'false' });
    area.innerHTML = html || '';
    this.decorateLinks(area);
    area.addEventListener('click', (e) => this.followLink(e));
    if (!editable) return area;
    const sync = () => onInput(this.storableInline(area));
    area.addEventListener('input', sync);
    area.addEventListener('paste', (e) => {
      e.preventDefault();
      const clip = e.clipboardData;
      if (this.pasteAddress(area, clip)) { sync(); return; }
      const rich = this.richerThanText(clip.getData('text/html'))
        ? this.richFromHtml(clip.getData('text/html'), { inline: true }) : null;
      if (rich) { document.execCommand('insertHTML', false, rich); this.decorateLinks(area); sync(); return; }
      // One line: the lines of what was pasted join up, as they did before formatting.
      document.execCommand('insertText', false, clip.getData('text/plain').replace(/\s*[\r\n]+\s*/g, ' '));
      sync();
    });
    area.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) e.preventDefault();
      if (e.key.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey) {
        e.preventDefault();
        const bar = document.getElementById('formatBar');
        if (bar) this.webLinkBox(area, sync, bar);
      }
    });
    area.addEventListener('focus', () => App.showFormatBar(area, sync));
    return area;
  },

  /** The text as kept: links by what they point at, not by this page's address for it. */
  storable(area) {
    const copy = area.cloneNode(true);
    // A line the browser started as a <div> (Enter, in text that is not in a paragraph) is a
    // paragraph: the server keeps <p> but not <div>, which used to run such lines together.
    for (const div of [...copy.querySelectorAll('div')].reverse()) {
      const p = document.createElement('p');
      p.append(...div.childNodes);
      div.replaceWith(p);
    }
    this.tidyNodes(copy);
    for (const a of copy.querySelectorAll('a[data-plasmid], a[data-note], a[data-seed], a[data-stock], a[data-track], a[data-task], a[data-attachment]')) {
      for (const attr of ['href', 'class', 'title']) a.removeAttribute(attr);
    }
    for (const img of copy.querySelectorAll('img[data-attachment]')) {
      for (const attr of ['src', 'loading', 'class']) img.removeAttribute(attr);
    }
    for (const tab of copy.querySelectorAll('span.tab')) tab.removeAttribute('style');
    return copy.innerHTML;
  },

  /** What is typed next to a tab goes into the tab's span; it is taken out again, the cursor with it. */
  keepTabsAlone(area) {
    const sel = window.getSelection();
    for (const span of area.querySelectorAll('span.tab')) {
      const text = span.textContent;
      if (/^\t+$/.test(text)) continue;
      const caret = sel.rangeCount && span.contains(sel.anchorNode) ? sel.anchorOffset : -1;
      let seen = 0;
      let place = null;
      const parts = (text.match(/\t+|[^\t]+/g) || []).map((run) => {
        const part = run[0] === '\t' ? el('span', { class: 'tab' }, run) : document.createTextNode(run);
        const target = part.nodeType === Node.TEXT_NODE ? part : part.firstChild;
        if (caret >= seen && caret <= seen + run.length) place = [target, caret - seen];
        seen += run.length;
        return part;
      });
      span.replaceWith(...parts);
      if (place) sel.collapse(...place);
    }
  },

  decorateLinks(area) {
    for (const a of area.querySelectorAll('a[data-plasmid]')) {
      a.href = editorLink(a.dataset.plasmid);
      a.classList.add('plasmid-link');
      a.title = 'Open in the Sequence Editor';
    }
    for (const a of area.querySelectorAll('a[data-note]')) {
      a.href = `#note=${a.dataset.note}`;
      a.classList.add('note-link');
    }
    for (const a of area.querySelectorAll('a[data-stock]')) {
      a.href = stockLink(a.dataset.stock);
      a.classList.add('stock-link');
      a.title = 'Open in Lab Stocks';
    }
    for (const a of area.querySelectorAll('a[data-seed]')) {
      a.href = seedLink(a.dataset.seed);
      a.classList.add('seed-link');
      a.title = 'Open in the Seed Bank';
    }
    for (const a of area.querySelectorAll('a[data-track]')) {
      a.href = trackLink(a.dataset.track);
      a.classList.add('track-link');
      a.title = 'Open in the Genome Browser';
    }
    for (const a of area.querySelectorAll('a[data-task]')) {
      a.href = '#';
      a.classList.add('task-link-tag');
      a.title = "Open the task's page: this shows there, under Talked about";
    }
    for (const img of area.querySelectorAll('img[data-attachment]')) {
      img.src = attachmentUrl(img.dataset.attachment);
      img.loading = 'lazy';
      img.title = 'Open the full picture';
    }
    for (const a of area.querySelectorAll('a[data-attachment]')) {
      a.href = viewUrl(a.dataset.attachment);
      a.classList.add('file-link');
      a.title = 'Open (PDFs, Word, PowerPoint, Excel and text files open here; Ctrl-click: in a new tab; other files download)';
    }
  },

  /** Ask which plasmid or note "@" means, and put a link to it in place of `range`. */
  async linkAt(area, range, sync) {
    const chosen = await this.chooseLink();
    if (!chosen) return;
    const { kind, target, label } = chosen;
    const link = el('a', { [`data-${kind}`]: ['plasmid', 'track', 'note', 'task'].includes(kind) ? target.id : target.code }, label);
    range.deleteContents();
    range.insertNode(link);
    link.after(document.createTextNode(' '));
    this.decorateLinks(area);
    const sel = window.getSelection();
    sel.removeAllRanges();
    const after = document.createRange();
    after.setStartAfter(link.nextSibling);
    sel.addRange(after);
    area.focus();
    sync();
    // A chemical: how and where to get rid of it goes in the box at the foot of the page.
    if (kind === 'stock') App.noteDisposal(target, true);
  },

  /**
   * What "@" means: a plasmid, seed, stock, track or page, chosen in two steps. Gives {kind, target, label}
   * (kind as in data-<kind> links), or null for "just type @".
   */
  async chooseLink() {
    const kind = await new Promise((resolve) => {
      let choice = null;
      modal({
        title: 'Link to…',
        onClose: () => resolve(choice),
        // Each kind a tile of the same size: what it is, and where it lives.
        build: (body, close) => {
          const tile = (kind, icon, name, where) => el('button', {
            class: 'link-choice', type: 'button', onclick: () => { choice = kind; close(); },
          }, el('span', { class: 'link-choice-icon' }, glyph(icon)),
          el('span', { class: 'link-choice-text' }, el('b', {}, name), el('span', { class: 'hint' }, where)));
          const tiles = el('div', { class: 'link-choices' },
            tile('plasmid', 'plasmid', 'Plasmid', 'Opens in the Sequence Editor'),
            tile('stock', 'stocks', 'Stock', 'Glycerol stock, primer, chemical, antibody or plant material, in Lab Stocks'),
            tile('seed', 'plant', 'Seeds', 'Seed lot, plant or line, in the Seed Bank'),
            tile('track', 'trace', 'Genome track', 'In the Genome Browser'),
            tile('note', 'text', 'Page or protocol', 'In a notebook or the protocol library'),
            tile('task', 'cube', 'Task', 'Of a project you are in'));
          body.append(tiles);
          tiles.querySelector('button').focus();
        },
        buttons: [{ label: 'Just type @', kind: 'secondary' }],
      });
    });
    if (!kind) return null;
    let target;
    try {
      target = kind === 'plasmid' ? await pickPlasmid() : kind === 'seed' ? await pickSeed()
        : kind === 'stock' ? await pickStock() : kind === 'track' ? await pickTrack()
          : kind === 'task' ? await pickTask()
            : await pickNote([], 'Link to a page or protocol');
    } catch (err) { toast(err.message, 'error'); return null; }
    if (!target) return null;
    return { kind, target,
      label: kind === 'plasmid' || kind === 'track' ? target.name : kind === 'seed' || kind === 'stock' ? target.label : target.title };
  },

  /**
   * "@" typed in a table cell: choose what it links to, and put [label](kind:id) in place of the @
   * (at `pos`, just after it). A chemical also goes in the page's waste disposal box.
   */
  async linkCell(row, c, pos, input, changed) {
    const chosen = await this.chooseLink();
    if (!chosen) { input.focus(); return; }
    const { kind, target, label } = chosen;
    const token = cellToken(kind, ['plasmid', 'track', 'note', 'task'].includes(kind) ? target.id : target.code, label);
    const value = String(row.cells[c] ?? '');
    if (pos === null) {
      // From a cell that takes formatting: the "@" that opened this is the last one in the cell,
      // counting only the ones in its words and not any inside a tag.
      const ats = [...value.matchAll(/<[^>]*>|@/g)].filter((m) => m[0] === '@');
      const at = ats.length ? ats[ats.length - 1].index : -1;
      row.cells[c] = at >= 0 ? `${value.slice(0, at)}${token} ${value.slice(at + 1)}` : `${value} ${token}`;
    } else {
      row.cells[c] = value[pos - 1] === '@' ? `${value.slice(0, pos - 1)}${token} ${value.slice(pos)}` : `${value} ${token}`;
    }
    if (document.activeElement === input) input.blur();
    changed();
    if (kind === 'stock') App.noteDisposal(target, true);
  },

  /* steps -------------------------------------------------------------------- */

  steps(block, ctx) {
    const list = el('ol', { class: 'steps-list' });
    // A long step, or title, wraps onto more lines, its box growing to show all of it.
    const fit = (area) => { area.style.height = 'auto'; area.style.height = `${area.scrollHeight}px`; };
    const wrap = el('div', {});
    const fitAll = () => wrap.querySelectorAll('textarea').forEach(fit);
    new ResizeObserver(fitAll).observe(wrap);
    // One paragraph: Enter does not break it, and pasted lines join up.
    const oneLine = (e) => {
      if (/[\r\n]/.test(e.target.value)) e.target.value = e.target.value.replace(/\s*[\r\n]+\s*/g, ' ');
      fit(e.target);
      return e.target.value;
    };
    const noEnter = (e) => { if (e.key === 'Enter') e.preventDefault(); };
    // Steps are moved by dragging the handle at their left, or with Alt+↑ / Alt+↓ in a step; its
    // ticks go with it, as they belong to the step and not to its place.
    let dragging = null;
    const clearMarks = () => list.querySelectorAll('.dragging, .drop-before, .drop-after')
      .forEach((n) => n.classList.remove('dragging', 'drop-before', 'drop-after'));
    const after = (e, li) => { const r = li.getBoundingClientRect(); return e.clientY > r.top + r.height / 2; };
    const moved = (from, slot, focusAt) => {
      if (!moveItem(block.items, from, slot)) return;
      draw();
      ctx.changed();
      if (focusAt !== undefined) list.children[focusAt]?.querySelector('.step-text')?.focus();
    };
    const draw = () => put(list, ...block.items.map((item, i) => {
      const done = !!(item.by || item.done);
      const box = el('input', {
        type: 'checkbox', checked: done, disabled: !ctx.editable,
        onchange: () => {
          item.done = box.checked;
          if (!box.checked) { item.by = null; item.at = null; }
          li.classList.toggle('done', box.checked);
          tick.textContent = box.checked ? (item.by ? `✓ ${who(item.by)} · ${localTime(item.at)}` : '✓ saving…') : '';
          ctx.changed();
        },
      });
      // A step takes the same formatting as text: bold, italic, colour, a marker. Steps written
      // before that was so were kept as plain text, and read back here as what they said.
      const stepHtml = item.html !== undefined && item.html !== null
        ? item.html : escapeHtml(item.text || '');
      const text = Blocks.inlineEditor(
        { class: 'step-text', 'data-placeholder': 'A step' }, stepHtml,
        { editable: ctx.editable, onInput: (line) => { item.html = line; delete item.text; ctx.changed(); } });
      if (ctx.editable) {
        text.addEventListener('keydown', (e) => {
          if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
            e.preventDefault();
            const up = e.key === 'ArrowUp';
            moved(i, up ? i - 1 : i + 2, up ? i - 1 : i + 1);
          }
        });
      }
      const handle = ctx.editable ? el('span', {
        class: 'step-handle', draggable: 'true', title: 'Drag to move this step (or Alt+↑ / Alt+↓ in it)',
        onclick: (e) => e.stopPropagation(),
        ondragstart: (e) => {
          dragging = i;
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/x-step', String(i));
          e.dataTransfer.setDragImage(li, 12, 12);
          setTimeout(() => li.classList.add('dragging'), 0);
        },
        ondragend: () => { dragging = null; clearMarks(); },
      }, '⋮⋮') : null;
      const tick = el('span', { class: 'tick', 'data-tick': `${block.id}|${item.id}` }, done && item.by ? `✓ ${who(item.by)} · ${localTime(item.at)}` : '');
      const li = el('li', { class: done ? 'done' : '',
        // Only a step of this list being dragged is taken, not a file or another list's step.
        ondragover: (e) => {
          if (dragging === null) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          const below = after(e, li);
          clearMarks();
          list.children[dragging]?.classList.add('dragging');
          li.classList.add(below ? 'drop-after' : 'drop-before');
        },
        ondragleave: (e) => { if (!li.contains(e.relatedTarget)) li.classList.remove('drop-before', 'drop-after'); },
        ondrop: (e) => {
          if (dragging === null) return;
          e.preventDefault();
          const from = dragging;
          const slot = i + (after(e, li) ? 1 : 0);
          dragging = null;
          clearMarks();
          moved(from, slot);
        } }, handle, box, text, tick,
      ctx.editable ? el('button', { class: 'icon-btn faint', title: 'Remove this step',
        onclick: () => { block.items.splice(i, 1); draw(); ctx.changed(); } }, '✕') : null);
      return li;
    }));
    draw();
    return put(wrap,
      ctx.editable
        ? el('textarea', { class: 'block-title', rows: 1, placeholder: 'Steps',
          oninput: (e) => { block.title = oneLine(e); ctx.changed(); }, onkeydown: noEnter }, block.title || '')
        : (block.title ? el('div', { class: 'block-title', text: block.title }) : null),
      list,
      ctx.editable ? el('button', { class: 'btn btn-secondary btn-sm', onclick: () => {
        block.items.push({ id: newId(), text: '' });
        draw();
        ctx.changed();
        list.querySelector('li:last-child .step-text')?.focus();
      } }, '＋ Step') : null);
  },

  /* sections ---------------------------------------------------------------- */

  section(block, ctx) {
    const src = block.source || {};
    const origin = src.kind === 'protocol'
      ? el('span', {}, 'Protocol', src.version ? ` · version ${src.version}` : '', ' · ',
        el('a', { href: `#note=${src.id}`, onclick: (e) => { e.preventDefault(); App.open(src.id); } }, 'open it'))
      : src.kind === 'task' || src.kind === 'workpackage'
        ? el('span', {}, src.kind === 'task' ? 'Task' : 'Work package', src.name ? ` of ${src.name}` : '', ' · ',
          el('a', { href: '#', onclick: (e) => { e.preventDefault(); Projects.openSource(src); } }, 'open it'),
          el('span', {}, ' · what is written here shows on it'))
      : src.kind === 'agenda' ? el('span', {}, 'Agenda point · the minutes of it go here')
      : src.kind === 'moclo-reaction' ? el('span', {}, 'From the MoClo Library Tool')
        : IMPORTED[src.kind] ? el('span', {}, IMPORTED[src.kind][1]) : null;
    const inner = el('div', { class: 'section-blocks' });
    // Under an agenda point: what was said and decided about it.
    this.renderList(block.blocks, inner, src.kind === 'agenda'
      ? Object.assign(Object.create(ctx), { placeholder: 'Minutes: what was said and decided on this point. Type @ to link.' }) : ctx);
    return el('div', { class: 'section-box' },
      el('div', { class: 'section-head' },
        el('span', { class: 'section-icon' }, glyph(src.kind === 'moclo-reaction' ? 'cassette' : src.kind === 'task' ? 'steps'
          : src.kind === 'agenda' ? 'pencil'
          : src.kind === 'workpackage' ? 'cube' : IMPORTED[src.kind]?.[0] || 'protocol')),
        ctx.editable
          ? el('input', { type: 'text', class: 'section-title', value: block.title || '',
            oninput: (e) => { block.title = e.target.value; ctx.changed(); } })
          : el('span', { class: 'section-title', text: block.title }),
        el('span', { class: 'hint' }, origin)),
      inner);
  },

  /* tables ------------------------------------------------------------------ */

  table(block, ctx) {
    const wrap = el('div', { class: 'table-block' });
    let design = !!block._design && ctx.editable;
    const cells = [];             // {input, r, c, view}

    const update = () => {
      const computed = Sheet.compute(block);
      for (const cell of cells) {
        if (cell.input === document.activeElement) continue;
        const kind = block.columns[cell.c]?.kind;
        const raw = block.rows[cell.r].cells[cell.c] ?? '';
        const shown = computed[cell.r][cell.c];
        // A cell may carry formatting, so what it says is written as markup, not as a value.
        // A worked-out cell shows its answer instead, and so does one written differently from the
        // way the answer reads ("0,61" shown as 0.61) — there the formatting cannot be kept.
        const plain = Sheet.plain(String(raw));
        const isFormula = !!shown.formula || plain.trim().startsWith('=');
        const written = !isFormula && (kind === 'text' || plain.trim() === String(shown.display));
        cell.input.innerHTML = written ? String(raw) : escapeHtml(shown.display);
        Blocks.decorateLinks(cell.input);
        // Links put in with @ show as links over the cell while it is not being changed.
        const parts = cell.view ? cellLinks(raw) : null;
        if (cell.view) {
          if (parts) put(cell.view, ...parts);
          cell.view.hidden = !parts;
          cell.input.classList.toggle('has-links', !!parts);
        }
        cell.input.classList.toggle('computed', !!shown.formula || kind === 'scaled');
        cell.input.classList.toggle('error', !!shown.error);
        cell.input.title = shown.error ? `Cannot work this out: ${shown.error}` : (shown.formula
          ? `${String(raw).startsWith('=') ? raw : block.columns[cell.c].formula}${shown.display === '' ? ' (waiting for a value)' : ''}`
          : (kind === 'scaled' && raw !== '' ? `${raw} per ${block.scale?.base ?? 1}` : ''));
      }
    };
    const changed = () => { update(); ctx.changed(); };

    const draw = () => {
      cells.length = 0;
      const n = block.columns.length;
      const head = el('tr', {}, block.columns.map((col, c) => el('th', { class: `kind-${col.kind}` },
        design ? this.columnEditor(block, c, () => { draw(); changed(); }) : [
          el('span', { class: 'col-letter' }, Sheet.colName(c)),
          // The name is changed where it is, by clicking it; the rest of a column under ⚙ Columns.
          ctx.editable
            ? el('input', {
              type: 'text', class: 'col-name', value: col.name || '', placeholder: 'Name', title: 'The column\'s name: click to change it',
              style: `width:${Math.max(4, (col.name || '').length + 1)}ch`,
              onfocus: (e) => e.target.select(),
              oninput: (e) => { col.name = e.target.value; e.target.style.width = `${Math.max(4, col.name.length + 1)}ch`; ctx.changed(); },
              onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } },
            })
            : el('span', { text: col.name || '' }),
          col.unit ? el('span', { class: 'col-unit' }, ` (${col.unit})`) : null,
          col.kind === 'formula' && col.formula ? el('div', { class: 'col-formula', text: col.formula }) : null,
          col.kind === 'fill' ? el('div', { class: 'col-formula' }, 'fill in') : null,
        ])), ctx.editable ? el('th', { class: 'row-tools' }) : null);
      const rows = block.rows.map((row, r) => el('tr', {}, block.columns.map((col, c) => {
        if (col.kind === 'check') {
          const value = row.cells[c];
          const box = el('input', {
            type: 'checkbox', checked: !!value, disabled: !ctx.editable,
            onchange: () => {
              row.cells[c] = box.checked ? (value && value.by ? value : { done: true }) : null;
              label.textContent = box.checked ? (row.cells[c].by ? `${who(row.cells[c].by)} · ${localTime(row.cells[c].at)}` : 'saving…') : '';
              changed();
            },
          });
          const label = el('span', { class: 'tick', 'data-tick': `${block.id}|${row.id}|${c}` },
            value && value.by ? `${who(value.by)} · ${localTime(value.at)}` : '');
          return el('td', { class: 'cell-check' }, box, label);
        }
        // Text and fill-in cells take links with @, as text does: a chemical in a protocol's table, say.
        const linkable = col.kind === 'text' || col.kind === 'fill';
        // A cell takes the same formatting as text does: bold, italic, colour, a marker. It stays
        // one line, and what it says is still read as a number or a formula through the formatting.
        const input = el('div', {
          class: `cell kind-${col.kind}`, contenteditable: ctx.editable ? 'true' : 'false',
          'data-placeholder': col.kind === 'fill' ? (App.note?.space === 'library' ? 'on the day' : 'fill in') : '',
          onfocus: () => {
            input.innerHTML = String(row.cells[c] ?? '');
            Blocks.decorateLinks(input);
            if (view) view.hidden = true;
            input.classList.remove('has-links');
            selectAll(input);
            App.showFormatBar(input, () => { row.cells[c] = Blocks.storableInline(input); changed(); });
          },
          onblur: () => update(),
          oninput: (e) => {
            row.cells[c] = Blocks.storableInline(input);
            changed();
            if (linkable && ctx.editable && e.data === '@') this.linkCell(row, c, null, input, changed);
          },
          // Cells copied from a spreadsheet fill the table from here, right and down, with rows and
          // columns added as needed; anything else is pasted into this cell, keeping its formatting.
          onpaste: (e) => {
            if (!ctx.editable) return;
            const grid = Clip.gridOrLines(e.clipboardData);
            if (grid && !(grid.length === 1 && grid[0].length === 1)) {
              e.preventDefault();
              this.fillTable(block, r, c, grid);
              draw(); changed();
              cells.find((x) => x.r === r && x.c === c)?.input.focus();
              return;
            }
            e.preventDefault();
            const clip = e.clipboardData;
            const rich = this.richerThanText(clip.getData('text/html'))
              ? this.richFromHtml(clip.getData('text/html'), { inline: true }) : null;
            if (rich) { document.execCommand('insertHTML', false, rich); Blocks.decorateLinks(input); }
            else document.execCommand('insertText', false, clip.getData('text/plain').replace(/\s*[\r\n]+\s*/g, ' '));
            row.cells[c] = Blocks.storableInline(input);
            changed();
          },
          onkeydown: (e) => {
            // Enter goes down a row, as in a spreadsheet.
            if (e.key === 'Enter') { e.preventDefault(); cells.find((x) => x.r === r + 1 && x.c === c)?.input.focus(); }
          },
        });
        const view = linkable ? el('div', { class: 'cell-view', hidden: true, onclick: (e) => {
          if (e.target.closest('a')) { this.followLink(e); return; }
          if (ctx.editable) input.focus();
        } }) : null;
        cells.push({ input, r, c, view });
        return el('td', { class: linkable ? 'cell-linkable' : null }, input, view);
      }), ctx.editable ? el('td', { class: 'row-tools' }, el('button', {
        class: 'icon-btn faint', title: 'Remove this row',
        onclick: () => { block.rows.splice(r, 1); draw(); changed(); },
      }, '✕')) : null));
      const table = el('table', { class: 'sheet' }, el('thead', {}, head), el('tbody', {}, rows));

      const scale = block.scale
        ? el('label', { class: 'scale' }, `${block.scale.label || 'Reactions'} `,
          el('input', {
            type: 'number', min: '0', step: 'any', value: block.scale.value, disabled: !ctx.editable,
            oninput: (e) => { block.scale.value = Number(e.target.value) || 0; changed(); },
          }), design ? el('span', { class: 'hint' }, ' (N in formulas)') : null)
        : null;
      const tools = ctx.editable ? el('div', { class: 'table-tools' },
        el('button', { class: 'btn btn-secondary btn-sm', onclick: () => {
          block.rows.push({ id: newId(), cells: block.columns.map((col) => (col.kind === 'check' ? null : '')) });
          draw(); changed();
        } }, '＋ Row'),
        design ? el('button', { class: 'btn btn-secondary btn-sm', onclick: () => {
          block.columns.push({ name: `Column ${Sheet.colName(n)}`, kind: 'text', unit: '', formula: '' });
          for (const row of block.rows) row.cells.push('');
          draw(); changed();
        } }, '＋ Column') : null,
        design ? el('button', { class: 'btn btn-secondary btn-sm', onclick: () => {
          block.scale = block.scale ? null : { label: 'Reactions', value: 1, base: 1 };
          draw(); changed();
        } }, block.scale ? 'No scaling' : 'Scale by reactions') : null,
        el('button', { class: `btn btn-sm ${design ? 'btn-primary' : 'btn-secondary'}`,
          title: 'Change the columns: their names, kinds, units and formulas',
          onclick: () => { design = !design; block._design = design; draw(); } }, design ? 'Done' : [glyph('gear'), ' Columns']),
      ) : null;

      put(wrap, 
        el('div', { class: 'table-head' },
          ctx.editable
            ? el('input', { type: 'text', class: 'block-title', value: block.title || '', placeholder: 'Table',
              oninput: (e) => { block.title = e.target.value; ctx.changed(); } })
            : (block.title ? el('div', { class: 'block-title', text: block.title }) : el('span')),
          scale),
        el('div', { class: 'sheet-scroll' }, table),
        design ? el('p', { class: 'hint' },
          'Formulas start with =. Name a column alone (=B*C) for the same row, a cell as A1, a range as A1:A5; ',
          'N is the number of reactions. SUM, MIN, MAX, AVERAGE, ROUND, ABS and IF work. ',
          'A cell of its own starting with = overrides its column\'s formula.') : null,
        tools);
      update();
    };
    draw();
    return wrap;
  },

  /** Copied cells put into a table from row r, column c: rows and (text) columns added where it is too small. */
  fillTable(block, r, c, grid) {
    const cut = grid.cut || r + grid.length > Clip.MAX_ROWS || c + grid[0].length > Clip.MAX_COLUMNS;
    grid = grid.slice(0, Clip.MAX_ROWS - r).map((values) => values.slice(0, Clip.MAX_COLUMNS - c));
    for (let j = block.columns.length; j < c + grid[0].length; j++) {
      block.columns.push({ name: `Column ${Sheet.colName(j)}`, kind: 'text', unit: '', formula: '' });
      for (const row of block.rows) row.cells.push('');
    }
    while (block.rows.length < r + grid.length) {
      block.rows.push({ id: newId(), cells: block.columns.map((col) => (col.kind === 'check' ? null : '')) });
    }
    grid.forEach((values, i) => values.forEach((value, j) => {
      const row = block.rows[r + i];
      // A cell is kept as markup now, so copied words go in as words, not as tags.
      row.cells[c + j] = block.columns[c + j].kind === 'check' ? (Clip.ticked(value) ? { done: true } : null) : escapeHtml(value.trim());
    }));
    if (cut) toast(`A table holds at most ${Clip.MAX_ROWS} rows and ${Clip.MAX_COLUMNS} columns: the rest was left out.`, 'error', 7000);
  },

  columnEditor(block, c, redraw) {
    const col = block.columns[c];
    const set = (key) => (e) => { col[key] = e.target.value; if (key === 'kind') redraw(); else App.changed(); };
    return el('div', { class: 'col-editor' },
      el('input', { type: 'text', value: col.name, placeholder: 'Name', oninput: set('name') }),
      el('select', { onchange: (e) => {
        const before = col.kind;
        col.kind = e.target.value;
        if ((before === 'check') !== (col.kind === 'check')) {
          for (const row of block.rows) row.cells[c] = col.kind === 'check' ? null : '';
        }
        redraw();
      } }, [['text', 'Text'], ['number', 'Number'], ['scaled', 'Scaled by reactions'], ['formula', 'Formula'],
        ['fill', 'Fill in on the day'], ['check', 'Tick off']].map(([v, label]) => el('option', { value: v, selected: col.kind === v }, label))),
      el('input', { type: 'text', value: col.unit, placeholder: 'Unit', class: 'unit', oninput: set('unit') }),
      col.kind === 'formula' ? el('input', { type: 'text', value: col.formula, placeholder: '=B*N', class: 'formula',
        oninput: (e) => { col.formula = e.target.value; App.changed(); } }) : null,
      el('button', { class: 'icon-btn faint', title: 'Remove this column', onclick: () => {
        block.columns.splice(c, 1);
        for (const row of block.rows) row.cells.splice(c, 1);
        redraw();
      } }, '✕'));
  },
};

/* --- exports and shares --------------------------------------------------------- */

const Exports = {
  /** Export a note and what is under it as a PDF or a Word document, following the job until it is ready. */
  open({ id, title, hasChildren = true, kind = 'page' }) {
    let format = store.get('exportFormat', 'pdf');
    let timer = null;
    modal({
      title: `Export “${title}”`,
      onClose: () => clearTimeout(timer),
      build: (body) => {
        const choice = (value, label, hint) => el('label', { class: 'checkbox export-choice' },
          el('input', { type: 'radio', name: 'exportFormat', value, checked: format === value,
            onchange: () => { format = value; store.set('exportFormat', value); } }),
          el('span', {}, el('b', {}, label), el('div', { class: 'hint' }, hint)));
        put(body,
          choice('pdf', 'PDF', 'To keep, print or send. Photos are in the text, an attached PDF\'s pages are put in where it is attached, and other files are embedded in the PDF (open them from its paperclip or attachments panel).'),
          choice('docx', 'Word document (.docx)', 'To edit. Photos and an attached PDF\'s pages are pictures in the document; other files come in a zip beside it, linked from the text.'),
          hasChildren ? el('label', { class: 'checkbox' }, el('input', { type: 'checkbox', id: 'exportChildren', checked: true }),
            ` Include everything under ${kind === 'notebook' ? 'it' : 'this one'}`) : null,
          el('p', { class: 'hint', id: 'exportState' }));
      },
      buttons: [
        { label: 'Close', kind: 'secondary' },
        {
          label: 'Export',
          onClick: async ({ body }) => {
            const state = body.querySelector('#exportState');
            const { job } = await api('POST', `/notes/${id}/export`, {
              format, children: body.querySelector('#exportChildren')?.checked !== false,
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, origin: location.origin,
            });
            const follow = async () => {
              let now;
              try { now = (await api('GET', `/exports/${job.id}`)).job; } catch (err) { put(state, err.message); return; }
              if (now.status === 'done') {
                const link = el('a', { href: url(`/api/exports/${job.id}/file`), download: now.filename }, `⤓ ${now.filename}`);
                put(state, 'Ready: ', link, ' (kept for an hour)');
                link.click();
              } else if (now.status === 'failed') {
                put(state, el('span', { class: 'error-text' }, now.error || 'The export failed'));
              } else {
                put(state, `${now.stage}…${now.total ? ` ${now.done} of ${now.total} pages` : ''}`);
                timer = setTimeout(follow, 1000);
              }
            };
            put(state, 'Starting…');
            follow();
            return false;
          },
        },
      ],
    });
  },
};

const Shares = {
  /** Who a notebook, protocol or page is shared with; share it with more, or retract a share. */
  async open({ id, title, kind, onChange = null }) {
    let data;
    try { data = await api('GET', `/notes/${id}/shares`); } catch (err) { toast(err.message, 'error'); return; }
    const notebook = kind === 'notebook';
    const page = kind === 'page' || kind === 'day';
    modal({
      title: `Share “${title}”`,
      build: (body) => {
        const list = el('div');
        const draw = () => put(list, data.shares.length
          ? el('table', { class: 'library-table share-table' }, el('tbody', {}, data.shares.map((s) => el('tr', {},
            el('td', {}, glyph(s.target_type === 'lab' ? 'lab' : 'person'), ' ', el('b', { text: s.label })),
            el('td', { class: 'hint' }, `by ${who(s.created_by) || '—'} · ${localTime(s.created_at)}`),
            el('td', { class: 'nowrap' }, el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              try { data = await api('DELETE', `/shares/${s.id}`); draw(); onChange?.(); toast(`No longer shared with ${s.label}`, 'success'); } catch (err) { toast(err.message, 'error'); }
            } }, 'Retract'))))))
          : el('p', { class: 'hint' }, notebook ? 'Not shared: only its owner, the lab\'s lead and administrators see it.'
            : page ? 'Not shared: only you (and your lab\'s lead) see it.' : 'Not shared: only its own lab sees it.'));
        const options = [
          ...(data.labs || []).map((lab) => ({ value: `lab:${lab.id}`, label: `${lab.name} (the whole lab)` })),
          ...(data.people || []).map((u) => ({ value: `person:${u}`, label: who(u) })),
        ];
        const select = el('select', { class: 'share-select' }, el('option', { value: '' }, notebook || page ? 'Choose a lab or a person…' : 'Choose a lab…'),
          options.map((o) => el('option', { value: o.value }, o.label)));
        body.append(
          el('p', { class: 'hint' }, page
            ? ['To work on together, with people and labs of your chair group: they open this page and the pages under it, ',
              'change them, add pages under them, and can show it under a page of their own as well. It stays in your notebook, ',
              'every change by anyone shows for everyone, and the history keeps who changed what. ']
            : notebook
              ? 'Whoever it is shared with can open, search and export this notebook. Only its owner changes it. '
              : 'The lab it is shared with can open, use, copy and export this protocol. Only its author, their lead and administrators change it. ',
          'A share stays until it is retracted here.'),
          list,
          el('div', { class: 'form-row' }, select, el('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
            if (!select.value) return;
            const [target_type, ...rest] = select.value.split(':');
            try {
              data = await api('POST', `/notes/${id}/shares`, { target_type, target: rest.join(':') });
              select.value = '';
              draw();
              onChange?.();
            } catch (err) { toast(err.message, 'error'); }
          } }, 'Share')));
        draw();
      },
    });
  },
};

/* --- meetings (app/meetings.py) ------------------------------------------------- */

const Meetings = {
  /** The meetings someone organises or is invited to; set up a new one. */
  async list() {
    let data;
    try { data = await api('GET', '/meetings'); } catch (err) { toast(err.message, 'error'); return; }
    modal({
      title: 'Meetings',
      wide: true,
      build: (body, close) => {
        const row = (m) => el('tr', {},
          el('td', {}, el('b', { text: m.title }), m.ended ? el('span', { class: 'hint' }, ' · ended') : null,
            el('div', { class: 'hint' }, `${m.when} · ${m.start_time}–${m.end_time}${m.location ? ` · ${m.location}` : ''}`)),
          el('td', { class: 'hint nowrap' }, m.next ? `Next: ${dayMonthYear(m.next)}` : 'No more dates'),
          el('td', { class: 'hint' }, m.can_edit
            ? (m.people.length ? `With ${m.people.map(who).join(', ')}` : 'No one invited')
            : `Set up by ${who(m.owner)}`),
          el('td', { class: 'nowrap' }, m.can_edit && !m.ended ? el('button', {
            class: 'btn btn-secondary btn-sm', onclick: () => { close(); this.edit(m, { data }); },
          }, 'Change') : null));
        body.append(
          el('p', { class: 'hint' }, 'A meeting gets a page under the day it falls on, for this week and next, in your notebook ',
            'and in the notebook of everyone invited: one page you all write on, with the agenda, who came, notes and action items.'),
          data.meetings.length
            ? el('table', { class: 'library-table meeting-table' }, el('tbody', {}, data.meetings.map(row)))
            : el('p', { class: 'hint' }, 'No meetings yet.'));
      },
      buttons: [{ label: 'Close', kind: 'secondary' },
        { label: '＋ New meeting', onClick: () => { this.edit(null, { data }); } }],
    });
  },

  /** Set up a meeting (m null), on a day if given, or change one. */
  async edit(m, { day = null, from = null, to = null, data = null } = {}) {
    try { data = data || await api('GET', '/meetings'); } catch (err) { toast(err.message, 'error'); return; }
    const pad = (n) => String(n).padStart(2, '0');
    const now = new Date();
    const todayIso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const text = (html) => {
      const doc = new DOMParser().parseFromString(html || '', 'text/html');
      return [...doc.body.children].map((p) => p.textContent).join('\n') || doc.body.textContent || '';
    };
    const html = (t) => t.split('\n').map((line) => line.trim()).filter(Boolean)
      .map((line) => `<p>${line.replace(/[<>&]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</p>`).join('');
    const field = (label, input, hint) => el('label', { class: 'meeting-field' }, el('span', {}, label), input,
      hint ? el('span', { class: 'hint' }, hint) : null);
    const title = el('input', { type: 'text', value: m?.title || '', placeholder: 'e.g. Lab meeting', maxlength: 120 });
    const first = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'dd-mm-yyyy',
      value: dayMonthYear(m?.starts_on || day || todayIso) });
    const start = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'HH:MM', maxlength: 5, value: m?.start_time || from || '10:00' });
    const end = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'HH:MM', maxlength: 5, value: m?.end_time || to || '11:00' });
    const repeat = el('select', {}, Object.entries(data.repeats).map(([value, label]) =>
      el('option', { value, selected: (m?.repeat || 'weekly') === value || null }, label)));
    const until = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'dd-mm-yyyy, or leave empty',
      value: m?.until ? dayMonthYear(m.until) : '' });
    const untilField = field('Last date', withCalendar(until), 'Empty: it goes on until you end it.');
    const showUntil = () => { untilField.hidden = repeat.value === 'none'; };
    repeat.addEventListener('change', showUntil);
    showUntil();
    const place = el('input', { type: 'text', value: m?.location || '', placeholder: 'e.g. Room 2.12, or a video link', maxlength: 200 });
    const agenda = el('textarea', { rows: 4, placeholder: 'One point per line' }, text(m?.agenda));
    const chosen = new Set(m?.people || []);
    const filter = el('input', { type: 'search', placeholder: 'Find someone…' });
    const boxes = el('div', { class: 'meeting-people' });
    const draw = () => {
      const q = filter.value.trim().toLowerCase();
      put(boxes, data.invitable.length ? data.invitable
        .filter((u) => !q || chosen.has(u) || `${u} ${who(u)}`.toLowerCase().includes(q))
        .map((u) => el('label', { class: 'meeting-person' },
          el('input', { type: 'checkbox', checked: chosen.has(u) || null,
            onchange: (e) => { if (e.target.checked) chosen.add(u); else chosen.delete(u); count.textContent = `${chosen.size} invited`; } }),
          ` ${who(u)}`))
        : el('p', { class: 'hint' }, 'No one else has an account yet.'));
    };
    const count = el('span', { class: 'hint' }, `${chosen.size} invited`);
    filter.addEventListener('input', draw);
    draw();
    const isoOf = (box, what, optional = false) => {
      if (optional && !box.value.trim()) return null;
      const iso = isoFromDayMonthYear(box.value);
      if (!iso) throw new Error(`Type the ${what} as dd-mm-yyyy, for example 05-11-2026`);
      return iso;
    };
    const save = async () => {
      const body = {
        title: title.value, starts_on: isoOf(first, 'first date'), start_time: start.value, end_time: end.value,
        repeat: repeat.value, until: repeat.value === 'none' ? null : isoOf(until, 'last date', true),
        location: place.value, agenda: html(agenda.value), people: [...chosen],
      };
      const { meeting } = m ? await api('PUT', `/meetings/${m.id}`, body) : await api('POST', '/meetings', body);
      toast(m ? 'Meeting changed' : `Meeting set up: ${meeting.when}`, 'success');
      await this.after(m ? null : meeting);
    };
    const buttons = [{ label: 'Cancel', kind: 'secondary' }];
    if (m) {
      buttons.push({ label: 'End meeting…', kind: 'danger', onClick: ({ close }) => { this.end(m, close); return false; } });
    }
    buttons.push({ label: m ? 'Save' : 'Set up meeting', onClick: save });
    modal({
      title: m ? `Change “${m.title}”` : 'New meeting',
      wide: true,
      build: (body) => body.append(el('div', { class: 'meeting-form' },
        field('Title', title),
        el('div', { class: 'meeting-row' }, field('First date', withCalendar(first)), field('From', start, '24-hour clock'), field('To', end)),
        el('div', { class: 'meeting-row' }, field('Repeats', repeat), untilField),
        field('Where', place),
        field('Agenda', agenda, 'One point per line. On each meeting’s page every point gets a box of its own for its minutes; each page can then be written on by itself.'),
        el('div', { class: 'meeting-field' }, el('span', {}, 'Invite ', count), filter, boxes,
          el('span', { class: 'hint' }, 'Anyone in Trellis Tools. Its pages are shared with them and show under their days: they take notes on them, '
            + 'and only you change the meeting itself.')),
        m ? el('p', { class: 'hint' }, 'Changes reach the pages from today on: one nobody has written on is made again; one written on keeps what is written. ',
          'Pages of days gone by stay as they were. To skip one date, delete its page.') : null)),
      buttons,
    });
  },

  /** No more dates after today; pages already written on stay. */
  end(m, closeForm) {
    modal({
      title: `End “${m.title}”?`,
      build: (body) => body.append(el('p', {}, 'No more pages are made after today. Pages to come that nobody has written on go; ',
        'pages with notes on them, and every page of days gone by, stay.')),
      buttons: [{ label: 'Keep it', kind: 'secondary' }, {
        label: 'End meeting', kind: 'danger', onClick: async () => {
          await api('POST', `/meetings/${m.id}/end`);
          closeForm();
          toast('Meeting ended', 'success');
          await this.after();
        },
      }],
    });
  },

  /** After a change: the tree, and the page shown, as they are now. */
  /** After a meeting is set up, changed or ended: what is shown, again. On the Meetings tab its week
   *  schedule at once (for a new meeting, the week of its first date); on a page, the page. */
  async after(meeting = null) {
    if (!document.getElementById('meetingsView').hidden) {
      await App.reloadTrees();
      await MeetingWeek.show(meeting?.starts_on || null);
    } else if (App.note) {
      try { await App.refresh(); } catch { await App.reloadTrees(); }
    } else {
      await App.reloadTrees();
    }
  },
};

/* --- the note ------------------------------------------------------------------- */

const App = {
  me: null,
  note: null,
  dirty: false,
  saving: null,
  timer: null,

  async init() {
    try {
      this.me = await api('GET', '/me');
      NB.names = this.me.names || {};
    } catch (err) {
      put(document.getElementById('main'), el('div', { class: 'empty-state' }, err.message));
      return;
    }
    document.getElementById('btnToday').addEventListener('click', () => this.startDay());
    document.getElementById('btnMeetings').addEventListener('click', () => { location.hash = '#meetings'; });
    // Another day is typed as dd-mm-yyyy (the browser's own date box follows its language, often
    // yyyy-mm-dd or mm/dd/yyyy), or chosen on the browser's calendar from the button beside it.
    const dayBox = document.getElementById('dayPicker');
    const calendar = document.getElementById('dayCalendar');
    const goTo = () => {
      if (!dayBox.value.trim()) return;
      const iso = isoFromDayMonthYear(dayBox.value);
      dayBox.classList.toggle('bad', !iso);
      if (!iso) { toast('Type the day as dd-mm-yyyy, for example 05-11-2026', 'error'); return; }
      dayBox.value = dayMonthYear(iso);
      this.startDay(iso);
    };
    dayBox.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); goTo(); } });
    dayBox.addEventListener('input', () => dayBox.classList.remove('bad'));
    document.getElementById('btnCalendar').addEventListener('click', () => {
      const iso = isoFromDayMonthYear(dayBox.value);
      if (iso) calendar.value = iso;
      try { calendar.showPicker(); } catch { calendar.focus(); calendar.click(); }
    });
    calendar.addEventListener('change', () => {
      if (!calendar.value) return;
      dayBox.value = dayMonthYear(calendar.value);
      dayBox.classList.remove('bad');
      this.startDay(calendar.value);
    });
    document.getElementById('btnNewPage').addEventListener('click', () => this.newNote('mine', this.me.notebook));
    document.getElementById('btnExportMine').addEventListener('click', async () => {
      await this.flush();
      Exports.open({ id: this.me.notebook, title: 'My notebook', kind: 'notebook' });
    });
    const shareMine = document.getElementById('btnShareMine');
    shareMine.hidden = !this.me.can_share_notebook;
    shareMine.addEventListener('click', () => Shares.open({ id: this.me.notebook, title: 'My notebook', kind: 'notebook' }));
    document.getElementById('tabNotebook').addEventListener('click', (e) => {
      e.preventDefault();
      const last = store.get('last', null);
      if (last) this.open(last, { quiet: true }); else this.showEmpty();
    });
    window.addEventListener('hashchange', () => this.route());
    window.addEventListener('beforeunload', () => { if (this.dirty) this.save({ keepalive: true }); });
    Search.init();
    this.watch();
    await Promise.all([this.reloadTrees(), this.loadFavorites()]);
    if (/^#(protocols|deleted|meetings|projects?)/.test(location.hash)) this.route();
    else {
      const start = this.hashNote() || store.get('last', null);
      if (start) this.open(start, { quiet: true });
    }
  },

  /** Follow the address: #note=<id> opens a note, #protocols the library. */
  route() {
    if (location.hash.startsWith('#protocols')) { this.showLibrary(); return; }
    if (location.hash.startsWith('#deleted')) { this.showDeleted(); return; }
    if (location.hash.startsWith('#meetings')) { MeetingWeek.show(); return; }
    const project = (location.hash.match(/^#project=([\w-]+)/) || [])[1];
    if (project) { Projects.showProject(project); return; }
    if (location.hash.startsWith('#projects')) { Projects.showList(); return; }
    const id = this.hashNote();
    if (id && (id !== this.note?.id || document.getElementById('note').hidden)) this.open(id);
  },

  setTab(name) {
    document.getElementById('tabNotebook').classList.toggle('active', name === 'notebook');
    document.getElementById('tabProtocols').classList.toggle('active', name === 'protocols');
    document.getElementById('tabMeetings').classList.toggle('active', name === 'meetings');
    document.getElementById('tabProjects').classList.toggle('active', name === 'projects');
  },

  /** Show one of the main views (note, library, deleted, or none), hiding the others. */
  view(name) {
    for (const [id, key] of [['note', 'note'], ['library', 'library'], ['deletedView', 'deleted'], ['emptyState', 'empty'],
      ['meetingsView', 'meetings'], ['projectsView', 'projects']]) {
      document.getElementById(id).hidden = key !== name;
    }
  },

  showEmpty() {
    this.view('empty');
    this.setTab('notebook');
  },

  async loadFavorites(list) {
    const favs = list || (await api('GET', '/favorites')).favorites;
    this.favorites = new Set(favs.map((f) => f.id));
    put(document.getElementById('favList'), favs.length
      ? favs.map((f) => el('li', { class: `fav-item ${this.note?.id === f.id ? 'active' : ''}`, 'data-id': f.id,
        onclick: () => this.open(f.id) }, el('span', { class: 'tree-icon' }, glyph('protocol')), el('span', { class: 'tree-title', text: f.title })))
      : el('li', { class: 'hint fav-empty' }, 'Star a protocol (☆) to keep it here.'));
  },

  async toggleFavorite(id, on) {
    const { favorites } = await api(on ? 'PUT' : 'DELETE', `/favorites/${id}`);
    await this.loadFavorites(favorites);
    return on;
  },

  hashNote() { return (location.hash.match(/note=([\w-]+)/) || [])[1] || null; },

  async reloadTrees() {
    // What others share may have changed since the page was opened.
    try { this.me = await api('GET', '/me'); NB.names = this.me.names || {}; } catch { /* keep what we had */ }
    await Tree.mount(document.getElementById('treeMine'), this.me.notebook, { editable: true });
    // A notebook's own buttons: export it whole, and share it (its lab's lead, or an admin).
    const actions = (nb) => [
      el('button', { class: 'tree-act', title: `Export ${who(nb.owner)}'s notebook`, onclick: (e) => {
        e.stopPropagation();
        Exports.open({ id: nb.id, title: `${who(nb.owner)}'s notebook`, kind: 'notebook' });
      } }, '⤓'),
      nb.can_share ? el('button', { class: 'tree-act', title: `Share ${who(nb.owner)}'s notebook with a lab or a person`, onclick: (e) => {
        e.stopPropagation();
        Shares.open({ id: nb.id, title: `${who(nb.owner)}'s notebook`, kind: 'notebook' });
      } }, glyph('people')) : null,
    ].filter(Boolean);
    const groups = [['othersSection', 'treeOthers', (this.me.others || []).filter((nb) => !nb.shared)],
      ['sharedSection', 'treeShared', (this.me.others || []).filter((nb) => nb.shared)]];
    const pages = this.me.shared_pages || [];
    for (const [sectionId, boxId, list] of groups) {
      const section = document.getElementById(sectionId);
      section.hidden = !list.length && !(boxId === 'treeShared' && pages.length);
      const box = document.getElementById(boxId);
      put(box);
      for (const nb of list) {
        const holder = el('div');
        box.append(holder);
        await Tree.mount(holder, nb.id, { label: nb.archived ? `${who(nb.owner)} (left)` : who(nb.owner), actions: actions(nb) });
      }
    }
    // Pages shared to work on together: opened, changed and added to right here.
    if (pages.length) {
      document.getElementById('treeShared').append(el('ul', { class: 'tree-list' }, pages.map((p) => {
        const node = Tree.node(p, false, true);
        node.querySelector('.tree-title').after(el('span', { class: 'tree-owner hint' }, ` · ${who(p.owner)}`));
        return node;
      })));
    }
    document.getElementById('othersTitle').textContent = NB.person.role === 'admin' ? 'All notebooks' : 'My lab\'s notebooks';
    if (this.note) Tree.markActive(this.note.id);
  },

  async startDay(date) {
    await this.flush();
    try {
      const { note } = await api('POST', '/days', date ? { date } : {});
      for (const step of note.path.slice(0, -1)) Tree.expanded.add(step.id);
      Tree.remember();
      await this.reloadTrees();
      this.show(note);
    } catch (err) { toast(err.message, 'error'); }
  },

  async newNote(where, parent, type) {
    await this.flush();
    parent = parent || (where === 'library' ? this.me.library : this.me.notebook);
    type = type || (where === 'library' ? 'protocol' : 'page');
    try {
      const { note } = await api('POST', '/notes', {
        parent_id: parent, type,
        title: type === 'protocol' ? 'New protocol' : type === 'folder' ? 'New folder' : 'Untitled',
      });
      Tree.expanded.add(parent);
      Tree.remember();
      await this.reloadTrees();
      this.show(note);
      const title = document.querySelector('.note-title');
      title?.focus();
      title?.select?.();
    } catch (err) { toast(err.message, 'error'); }
  },

  /** The open note again, as saved, where the reader was; and the trees, for what changed in them. */
  async refresh() {
    if (!this.note) return;
    await this.flush();
    const { note } = await api('GET', `/notes/${this.note.id}`);
    const scroll = window.scrollY;
    this.show(note);
    window.scrollTo(0, scroll);
    await this.reloadTrees();
  },

  /**
   * A page others work on too (one shared, or a lab's) is checked now and then,
   * and shown again when someone else saved it: never while it is being
   * changed here, or a field in it is being typed in.
   */
  watch() {
    setInterval(async () => {
      const note = this.note;
      const typing = document.activeElement?.closest?.('#note') && document.activeElement.matches('input, textarea, [contenteditable="true"]');
      if (!note || this.dirty || this.saving || document.hidden || typing || document.querySelector('.modal-backdrop')) return;
      try {
        const { note: now } = await api('GET', `/notes/${note.id}`);
        if (this.note !== note || this.dirty || now.version === note.version) return;
        const scroll = window.scrollY;
        this.show(now);
        window.scrollTo(0, scroll);
        if (now.updated_by && now.updated_by !== NB.person.username) toast(`Updated by ${who(now.updated_by)}`, 'info', 2500);
      } catch { /* gone, or offline for a moment: the next look will tell */ }
    }, 20000);
  },

  async open(id, { quiet = false } = {}) {
    await this.flush();
    try {
      const { note } = await api('GET', `/notes/${id}`);
      this.show(note);
    } catch (err) {
      if (!quiet) toast(err.message, 'error');
      if (err.status === 404 || err.status === 403) store.set('last', null);
    }
  },

  show(note) {
    this.note = note;
    this.dirty = false;
    store.set('last', note.id);
    if (this.hashNote() !== note.id || location.hash.startsWith('#protocols')) {
      history.pushState(null, '', `#note=${note.id}`);
    }
    this.view('note');
    const box = document.getElementById('note');
    this.setTab(note.space === 'library' ? 'protocols' : note.space === 'project' ? 'projects'
      : note.type === 'meeting' ? 'meetings' : 'notebook');
    Tree.markActive(note.id);
    for (const f of document.querySelectorAll('.fav-item')) f.classList.toggle('active', f.dataset.id === note.id);
    const editable = note.can_edit;
    // ctx.todo: a week's to-do list, whose tasks move on to next week; a meeting's action items do not.
    // ctx.onTodo: a meeting's action items on people's to-do lists ({item id: [{username, done_at}]}).
    const ctx = { editable, todo: note.type === 'todo', meeting: note.type === 'meeting' ? note.id : null,
      onTodo: note.on_todo || {}, changed: () => this.changed() };

    const crumbs = el('nav', { class: 'crumbs' }, note.path.slice(0, -1).map((p, i) => [
      i ? el('span', { class: 'crumb-sep' }, '›') : null,
      el('a', { href: p.type === 'library' ? '#protocols' : `#note=${p.id}`, onclick: (e) => {
        if (p.type === 'library') return;          // the Protocols tab, by its address
        e.preventDefault();
        if (p.type !== 'notebook') this.open(p.id);
      } }, p.title)]));

    const fixedTitle = !editable || ['day', 'month', 'year', 'todo', 'meeting', 'task'].includes(note.type);
    const title = fixedTitle
      ? el('h1', { class: 'note-title', text: note.title })
      : el('input', { type: 'text', class: 'note-title', value: note.title,
        oninput: (e) => { note.title = e.target.value; this.changed(); } });

    const owner = note.space === 'notebook' && note.owner !== NB.person.username;
    const meta = el('div', { class: 'note-meta' },
      el('span', { class: `badge badge-${note.type}` }, noteGlyph(note.type), ` ${note.type}`),
      owner ? el('span', { class: 'badge badge-owner' }, `${who(note.owner)}'s notebook`) : null,
      !editable ? el('span', { class: 'badge badge-readonly' }, 'read only') : null,
      ...(note.shared_in || []).map((r) => el('span', {
        class: 'badge badge-shared',
        title: r.id === note.id ? 'Shared to work on together' : `Part of “${r.title}”, shared to work on together`,
      }, note.owner === NB.person.username
        ? [glyph('people'), ` shared with ${r.with.join(', ')}${r.id === note.id ? '' : ` (in ${r.title})`}`]
        : [glyph('people'), ` shared by ${who(note.owner)}${r.id === note.id ? '' : ` (in ${r.title})`}`])),
      el('span', { class: 'hint' }, note.updated_by || note.created_by
        ? `Last saved by ${who(note.updated_by || note.created_by)} · ${localTime(note.updated_at)}`
        : `Supplied with the Lab Notebook · ${localTime(note.updated_at)}`),
      el('span', { class: 'save-state', id: 'saveState' }),
      el('span', { class: 'note-actions' },
        note.type === 'protocol' ? el('button', {
          class: `btn btn-sm star ${note.favorite ? 'on' : 'btn-secondary'}`,
          title: note.favorite ? 'Remove from your favourite protocols' : 'Add to your favourite protocols, listed on the left',
          onclick: async (e) => {
            const btn = e.currentTarget;
            note.favorite = await this.toggleFavorite(note.id, !note.favorite);
            btn.textContent = note.favorite ? '★ Favourite' : '☆ Favourite';
            btn.className = `btn btn-sm star ${note.favorite ? 'on' : 'btn-secondary'}`;
          },
        }, note.favorite ? '★ Favourite' : '☆ Favourite') : null,
        note.space === 'notebook' || note.type !== 'protocol' ? null : el('button', {
          class: 'btn btn-secondary btn-sm',
          title: "Use this protocol: a page of its own under today's day, or under any page you choose",
          onclick: () => this.addToPage(note.id),
        }, '＋ Add to page…'),
        note.type === 'day' && (note.todo || editable) ? el('button', {
          class: 'btn btn-sm btn-secondary',
          title: note.todo ? "This week's to-do list, under every day of the week"
            : "Make this week's to-do list: one list under every day of the week, with the tasks moved on from last week",
          onclick: async () => {
            if (note.todo) { this.open(note.todo); return; }
            await this.flush();
            try {
              const { note: todo } = await api('POST', `/notes/${note.id}/todo`);
              await this.reloadTrees();
              this.show(todo);
            } catch (err) { toast(err.message, 'error'); }
          },
        }, glyph('steps'), note.todo ? " Week's to-do" : " ＋ Week's to-do") : null,
        note.type === 'day' && editable && note.owner === NB.person.username ? el('button', {
          class: 'btn btn-sm btn-secondary',
          title: 'Set up a meeting on this day, once or repeating, and invite people: it is shared with them and shows under their days too',
          onclick: () => Meetings.edit(null, { day: (note.attributes.find((a) => a.name === 'dateNote') || {}).value }),
        }, glyph('people'), ' ＋ Meeting') : null,
        note.can_share ? el('button', {
          class: 'btn btn-secondary btn-sm',
          title: note.space === 'library' ? 'Share this protocol with other labs'
            : 'Share this page and the pages under it with people of your chair group, to work on together',
          onclick: () => Shares.open({ id: note.id, title: note.title, kind: note.type, onChange: () => this.refresh() }),
        }, glyph('people'), ' Share') : null,
        el('button', {
          class: 'btn btn-secondary btn-sm', title: note.has_children ? 'Export this page and everything under it, as a PDF or a Word document' : 'Export as a PDF or a Word document',
          onclick: async () => { await this.flush(); Exports.open({ id: note.id, title: note.title, hasChildren: note.has_children, kind: note.type }); },
        }, '⤓ Export'),
        el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.history() }, glyph('history'), ' History'),
        el('button', { class: 'btn btn-secondary btn-sm', title: 'Copy, move, place elsewhere, delete', onclick: () => this.moreMenu() }, '⋯')));

    const blocks = el('div', { class: 'blocks' });
    Blocks.renderList(note.content, blocks, ctx);

    this._blocks = { blocks, ctx };
    put(box, crumbs, el('div', { class: 'note-head' }, title), meta, this.attributeBar(note), this.bookingsPanel(note),
      this.meetingPanel(note), Projects.taskPanel(note), blocks, editable ? this.insertBar(note, blocks, ctx) : null, note.has_children ? this.childCards(note) : null,
      this.attachmentPanel(note), this.linksPanel(note));
  },

  /** What is under this page, as cards with the start of each one, as Trilium shows a note's children. */
  childCards(note) {
    const grid = el('div', { class: 'child-cards' }, el('p', { class: 'hint' }, 'Loading…'));
    const head = el('h3', { class: 'children-head' }, glyph('folder'), ' Under this page');
    api('GET', `/notes/${note.id}/children?previews=1`).then(({ children }) => {
      if (this.note?.id !== note.id) return;
      head.append(` (${children.length})`);
      put(grid, children.length ? children.map((c) => el('a', {
        class: 'child-card', href: `#note=${c.id}`,
        onclick: (e) => { if (plainClick(e)) { e.preventDefault(); this.open(c.id); } },
      },
      c.picture ? el('img', { class: 'child-picture', src: attachmentUrl(c.picture), alt: '', loading: 'lazy' }) : null,
      el('div', { class: 'child-title' }, noteGlyph(c.type), el('span', { text: c.title })),
      c.preview ? el('p', { class: 'child-text', text: c.preview }) : null,
      el('div', { class: 'child-meta hint' }, [
        c.child_count ? `${c.child_count} note${c.child_count === 1 ? '' : 's'} under it` : '',
        c.updated_at ? `${c.updated_by ? `${who(c.updated_by)} · ` : ''}${localTime(c.updated_at).slice(0, 10)}` : '',
      ].filter(Boolean).join(' · ')))) : el('p', { class: 'hint' }, 'Nothing you can open is under it.'));
    }).catch((err) => put(grid, el('p', { class: 'hint' }, err.message)));
    return el('section', { class: 'children-panel' }, head, grid);
  },

  /**
   * A chemical linked on the page: how and where to get rid of it, as Lab Stocks has it, in a box at the
   * foot of the page (a section marked source.kind 'disposal'), a line per chemical, which people may edit.
   * Each chemical is listed once. keepCaret: linked from inside a text block (@), so only the box is drawn
   * again and the caret stays where it is.
   */
  noteDisposal(stock, keepCaret = false) {
    if (!stock || stock.kind !== 'chemical') return;
    const esc = (t) => String(t).replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
    const how = stock.disposal ? esc(stock.disposal)
      : '<em>not recorded in Lab Stocks yet: ask your lab admin, or see section 13 of its safety data sheet</em>';
    this.addDisposalLines([{ code: stock.code, html: `<p><a data-stock="${esc(stock.code)}">${esc(stock.label)}</a>: ${how}</p>` }], keepCaret);
  },

  /** A protocol put into the page brings its waste disposal box: its lines join the page's own. */
  mergeDisposal(box) {
    const lines = [];
    for (const b of box?.blocks || []) {
      const doc = new DOMParser().parseFromString(b.html || '', 'text/html');
      for (const p of doc.body.querySelectorAll('p')) {
        const code = p.querySelector('a[data-stock]')?.dataset.stock;
        if (code) lines.push({ code, html: p.outerHTML });
      }
    }
    this.addDisposalLines(lines);
  },

  /** Lines [{code, html}] into the box at the foot of the page, made when there is none; one per chemical. */
  addDisposalLines(lines, keepCaret = false) {
    const note = this.note;
    if (!note || !lines.length || !this._blocks || !this._blocks.ctx.editable) return;
    if (note.type === 'todo') return;       // a week's to-do list is no place for it
    let box = note.content.find(isDisposalBox);
    const fresh = !box;
    if (fresh) {
      box = { id: newId(), type: 'section', title: 'Waste disposal',
        source: { kind: 'disposal', id: '', version: null, name: '' }, blocks: [] };
    }
    let text = box.blocks.find((b) => b.type === 'text');
    if (!text) { text = { id: newId(), type: 'text', html: '' }; box.blocks.push(text); }
    const added = lines.filter((l) => !(text.html || '').includes(`data-stock="${l.code}"`));
    if (!added.length) return;
    text.html = `${text.html || ''}${added.map((l) => l.html).join('')}`;
    const { blocks, ctx } = this._blocks;
    const index = fresh ? note.content.push(box) - 1 : note.content.indexOf(box);
    const shown = blocks.querySelector(`[data-block="${box.id}"]`);
    if (keepCaret) {
      // Only the box: the rest of the page, and the caret in it, stay as they are.
      const drawn = Blocks.wrap(box, index, note.content, blocks, ctx);
      if (shown) shown.replaceWith(drawn); else blocks.append(drawn);
    } else {
      Blocks.renderList(note.content, blocks, ctx);
    }
    this.changed();
    if (fresh) toast('Added a waste disposal box at the foot of the page', 'success', 3000);
  },

  insertBar(note, blocks, ctx) {
    const add = (block) => {
      // Above the waste disposal box, which stays at the foot of the page.
      const foot = note.content.findIndex(isDisposalBox);
      if (foot >= 0) note.content.splice(foot, 0, block); else note.content.push(block);
      Blocks.renderList(note.content, blocks, ctx);
      this.changed();
      const added = blocks.querySelector(`[data-block="${block.id}"]`);
      added?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      added?.querySelector('.text-block, input')?.focus();
    };
    // On a meeting's page a point or an item of the agenda goes with the agenda: before the attendance list.
    const withAgenda = (block) => {
      const at = note.type === 'meeting' ? note.content.findIndex((b) => b.type === 'steps' && b.title === 'Attendance') : -1;
      const now = note.content.indexOf(block);
      if (at < 0 || now < at) return;
      note.content.splice(now, 1);
      note.content.splice(at, 0, block);
      Blocks.renderList(note.content, blocks, ctx);
      this.changed();
      blocks.querySelector(`[data-block="${block.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };
    return el('div', { class: 'insert-bar' },
      el('span', { class: 'hint' }, 'Add:'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: () => add({ id: newId(), type: 'text', html: '' }) }, '¶ Text'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: () => add({
        id: newId(), type: 'table', title: '', scale: { label: 'Reactions', value: 1, base: 1 },
        columns: [{ name: 'Component', kind: 'text' }, { name: 'Per reaction', kind: 'number', unit: 'µL' },
          { name: 'Total', kind: 'formula', unit: 'µL', formula: '=B*N' }, { name: 'Added', kind: 'check' }],
        rows: [0, 1, 2].map(() => ({ id: newId(), cells: ['', '', '', null] })),
      }) }, '▦ Table'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: () => add({ id: newId(), type: 'steps', title: '', items: [{ id: newId(), text: '' }] }) }, glyph('steps'), ' Steps'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'A gel photo: click the wells you used, and name the sample in each',
        onclick: () => this.addGel(note, add) }, '▥ Gel photo…'),
      note.type === 'meeting' ? el('button', {
        class: 'btn btn-secondary btn-sm', title: 'A point of the agenda, with room under it for its minutes',
        onclick: () => {
          const point = { id: newId(), type: 'section', title: '', source: { kind: 'agenda' }, blocks: [{ id: newId(), type: 'text', html: '' }] };
          add(point);
          withAgenda(point);
          blocks.querySelector(`[data-block="${point.id}"] .section-title`)?.focus();
        },
      }, glyph('pencil'), ' Agenda point') : null,
      note.space === 'notebook' ? el('button', {
        class: 'btn btn-secondary btn-sm',
        title: note.type === 'meeting' ? 'Put a task or work package of your projects on the agenda: what is written under it shows on the task'
          : 'Put a task or work package of your projects on this page: what is written under it shows on the task',
        onclick: async () => {
          let section;
          try { section = await Projects.pickSection(); } catch (err) { toast(err.message, 'error'); return; }
          if (!section) return;
          add(section);
          withAgenda(section);
        },
      }, glyph('cube'), note.type === 'meeting' ? ' Agenda item…' : ' Task…') : null,
      note.space !== 'library' ? el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
        const protocol = await pickProtocol();
        if (!protocol) return;
        try {
          const { section } = await api('GET', `/protocols/${protocol.id}/snapshot`);
          const disposal = section.disposal;
          delete section.disposal;
          add(section);
          // The chemicals it uses, and how to get rid of them, join the page's waste disposal box.
          if (disposal) this.mergeDisposal(disposal);
        } catch (err) { toast(err.message, 'error'); }
      } }, glyph('protocol'), ' Protocol…') : null,
      el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
        try { const section = await pickMocloReaction(); if (section) add(section); } catch (err) { toast(err.message, 'error'); }
      } }, glyph('cassette'), ' MoClo reaction…'),
      el('label', { class: 'btn btn-secondary btn-sm', title: 'Attach photos or files: they are shown or linked here, and listed under Attachments. You can also paste or drop them into text.' },
        glyph('attach'), ' Attach…', el('input', { type: 'file', multiple: true, hidden: true, onchange: async (e) => {
          const files = [...e.target.files];
          e.target.value = '';
          const added = await this.upload(note, files);
          if (!added.length) return;
          const html = added.map(attachmentHtml).join('');
          const last = note.content[note.content.length - 1];
          if (last && last.type === 'text' && (last.html || '').trim()) {
            last.html = `${last.html}${html}`;
            Blocks.renderList(note.content, blocks, ctx);
            this.changed();
          } else if (last && last.type === 'text') {
            last.html = html;
            Blocks.renderList(note.content, blocks, ctx);
            this.changed();
          } else add({ id: newId(), type: 'text', html });
        } })),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'Add a link to a seed lot, plant or line in the Seed Bank', onclick: async () => {
        let s;
        try { s = await pickSeed(); } catch (err) { toast(err.message, 'error'); return; }
        if (!s) return;
        const html = `<a data-seed="${s.code}">${s.label.replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</a>`;
        const last = note.content[note.content.length - 1];
        if (last && last.type === 'text') {
          last.html = `${last.html || ''}${/<\/p>\s*$/.test(last.html || '') ? `<p>${html}</p>` : ` ${html}`}`;
          Blocks.renderList(note.content, blocks, ctx);
          this.changed();
        } else add({ id: newId(), type: 'text', html: `<p>${html}</p>` });
      } }, glyph('plant'), ' Seed…'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'Add a link to a glycerol stock, primer, chemical, antibody or plant material in Lab Stocks', onclick: async () => {
        let s;
        try { s = await pickStock(); } catch (err) { toast(err.message, 'error'); return; }
        if (!s) return;
        const html = `<a data-stock="${s.code}">${s.label.replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</a>`;
        const last = note.content.filter((b) => !isDisposalBox(b)).pop();
        if (last && last.type === 'text') {
          last.html = `${last.html || ''}${/<\/p>\s*$/.test(last.html || '') ? `<p>${html}</p>` : ` ${html}`}`;
          Blocks.renderList(note.content, blocks, ctx);
          this.changed();
        } else add({ id: newId(), type: 'text', html: `<p>${html}</p>` });
        // A chemical: how and where to get rid of it goes in the box at the foot of the page.
        this.noteDisposal(s);
      } }, glyph('stocks'), ' Stock…'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'Add a link to a plasmid, which opens it in the Sequence Editor', onclick: async () => {
        const p = await pickPlasmid();
        if (!p) return;
        const link = `<a data-plasmid="${p.id}">${p.name.replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</a>`;
        const last = note.content[note.content.length - 1];
        if (last && last.type === 'text') {
          last.html = `${last.html || ''}${/<\/p>\s*$/.test(last.html || '') ? `<p>${link}</p>` : ` ${link}`}`;
          Blocks.renderList(note.content, blocks, ctx);
          this.changed();
        } else add({ id: newId(), type: 'text', html: `<p>${link}</p>` });
      } }, glyph('plasmid'), ' Plasmid…'));
  },

  /** A photo clicked in text: offer to mark it up, or to open it. */
  photoMenu(img) {
    document.getElementById('photoMenu')?.remove();
    const r = img.getBoundingClientRect();
    const id = img.dataset.attachment;
    const menu = el('div', { class: 'photo-menu', id: 'photoMenu',
      style: `top:${r.top + window.scrollY + 8}px;left:${r.left + window.scrollX + 8}px` },
    el('button', { class: 'btn btn-primary btn-sm', title: 'Draw and write on it (the photo is kept as it is)',
      onclick: () => { menu.remove(); this.markUp(id); } }, glyph('pencil'), ' Mark up'),
    el('button', { class: 'btn btn-secondary btn-sm', onclick: () => { menu.remove(); if (!Viewer.open(id)) window.open(attachmentUrl(id), '_blank', 'noopener'); } }, '↗ Open'));
    document.body.append(menu);
    const away = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('mousedown', away, true); } };
    setTimeout(() => document.addEventListener('mousedown', away, true), 0);
  },

  /**
   * Mark up a photo of the open note: draw on it, and number spots on it.
   * From a numbered photo (a gel block), the editor numbers its spots; from a
   * photo in the text or under Attachments, numbering it makes it a numbered
   * photo, put where the photo was.
   */
  async markUp(attachmentId, { block = null } = {}) {
    await this.flush();
    const note = this.note;
    const spots = block ? { order: block.order === 'clicks' ? 'clicks' : 'rows', lanes: block.lanes || [] }
      : { order: 'clicks', lanes: [] };
    Markup.open({
      attachmentId,
      spots,
      onSaved: (att, lanes) => {
        if (this.note !== note) return;
        const shown = att ? att.id : attachmentId;
        if (att) {
          const swap = (blocks) => {
            for (const b of blocks || []) {
              if (b.type === 'text' && b.html) b.html = b.html.split(`data-attachment="${attachmentId}"`).join(`data-attachment="${att.id}"`);
              if (b.type === 'gel' && b.attachment === attachmentId) b.attachment = att.id;
              if (b.type === 'section') swap(b.blocks);
            }
          };
          swap(note.content);
          // A marked-up picture marked up again leaves the list; the original stays.
          const old = (note.attachments || []).find((a) => a.id === attachmentId);
          note.attachments = [...(note.attachments || []).filter((a) => !(old?.source_id && a.id === attachmentId)), att];
        }
        if (block) block.lanes = lanes;
        else if (lanes.length) this.numberedPhoto(note, shown, lanes);
        const { blocks, ctx } = this._blocks;
        Blocks.renderList(note.content, blocks, ctx);
        document.getElementById('attachmentPanel')?.replaceWith(this.attachmentPanel(note));
        this.changed();
        if (att) toast('Marked up. The original photo is kept, under Attachments.', 'success', 5000);
      },
    });
  },

  /**
   * A table pasted into text: the text splits where it was pasted, into what came before it, the table,
   * and what came after. Text that was empty is replaced by the table.
   */
  pasteTable(block, area, grid) {
    const sel = window.getSelection();
    const after = document.createElement('div');
    if (sel.rangeCount && area.contains(sel.getRangeAt(0).startContainer)) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      const rest = document.createRange();
      rest.setStart(range.startContainer, range.startOffset);
      rest.setEnd(area, area.childNodes.length);
      after.append(rest.extractContents());
    }
    const empty = (html) => !html.replace(/<(?!img)[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim();
    block.html = Blocks.storable(area);
    const table = Clip.table(grid);
    const rest = Blocks.storable(after);
    const place = (list) => {
      const i = list.indexOf(block);
      if (i >= 0) {
        const added = [table, ...(empty(rest) ? [] : [{ id: newId(), type: 'text', html: rest }])];
        if (empty(block.html)) list.splice(i, 1, ...added); else list.splice(i + 1, 0, ...added);
        return true;
      }
      return list.some((b) => b.type === 'section' && place(b.blocks || []));
    };
    if (!place(this.note.content)) return;
    const { blocks, ctx } = this._blocks;
    Blocks.renderList(this.note.content, blocks, ctx);
    this.changed();
    blocks.querySelector(`[data-block="${table.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    toast(`Pasted as a table: ${table.rows.length} row${table.rows.length === 1 ? '' : 's'}, ${table.columns.length} column${table.columns.length === 1 ? '' : 's'}.`
      + (grid.cut ? ` A table holds at most ${Clip.MAX_ROWS} rows and ${Clip.MAX_COLUMNS} columns: the rest was left out.` : ''),
    grid.cut ? 'error' : 'success', grid.cut ? 7000 : 3500);
  },

  /** A photo numbered from the text: a numbered photo in its place (just after its text), else at the end. */
  numberedPhoto(note, attachmentId, lanes) {
    const photo = { id: newId(), type: 'gel', order: 'clicks', title: '', attachment: attachmentId, lanes };
    const place = (list) => {
      for (let i = 0; i < list.length; i++) {
        const b = list[i];
        if (b.type === 'section' && place(b.blocks || [])) return true;
        if (b.type !== 'text' || !(b.html || '').includes(`data-attachment="${attachmentId}"`)) continue;
        // The text splits where the photo was: what came before it, the numbered photo, what came after.
        const box = document.createElement('div');
        box.innerHTML = b.html;
        const img = box.querySelector(`img[data-attachment="${CSS.escape(attachmentId)}"]`);
        let top = img;
        while (top.parentNode !== box) top = top.parentNode;
        const after = document.createElement('div');
        while (top.nextSibling) after.append(top.nextSibling);
        // Its paragraph goes with it when that held only the photo; otherwise the rest of it stays.
        if (top !== img && top.textContent.trim() === '' && top.querySelectorAll('img').length === 1) top.remove();
        else img.remove();
        b.html = box.innerHTML;
        list.splice(i + 1, 0, photo);
        if (after.innerHTML.trim()) list.splice(i + 2, 0, { id: newId(), type: 'text', html: after.innerHTML });
        return true;
      }
      return false;
    };
    if (!place(note.content)) note.content.push(photo);
  },

  /** A gel block: a photo already on the page, or a new one, ready to have its wells clicked. */
  addGel(note, add) {
    const start = (a) => add({ id: newId(), type: 'gel', title: '', attachment: a.id, lanes: [], _marking: true });
    const upload = () => {
      const input = el('input', { type: 'file', accept: 'image/*', hidden: true, onchange: async () => {
        const files = [...input.files];
        input.remove();
        const added = await this.upload(note, files);
        if (!added.length) return;
        if (!added[0].image) { toast('That is not a photo the notebook can show (PNG, JPEG, GIF, WebP or BMP)', 'error', 6000); return; }
        start(added[0]);
      } });
      document.body.append(input);
      input.click();
    };
    const photos = (note.attachments || []).filter((a) => a.image);
    if (!photos.length) { upload(); return; }
    modal({
      title: 'Which gel photo?',
      build: (body, close) => body.append(
        el('div', { class: 'gel-choices' }, photos.map((a) => el('button', { class: 'gel-choice', title: a.filename,
          onclick: () => { close(); start(a); } },
          el('img', { src: attachmentUrl(a.id), alt: '', loading: 'lazy' }), el('span', { class: 'hint', text: a.filename })))),
        el('button', { class: 'btn btn-primary', onclick: () => { close(); upload(); } }, glyph('camera'), ' Upload a new photo')),
      buttons: [{ label: 'Cancel', kind: 'secondary' }],
    });
  },

  /** Send files to be attached to a note; resolves with what was attached. */
  async upload(note, files) {
    if (!files.length) return [];
    const form = new FormData();
    for (const f of files) form.append('file', f, f.name || `pasted-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`);
    this.setState(`Attaching ${files.length} file${files.length > 1 ? 's' : ''}…`);
    try {
      const res = await fetch(url(`/api/notes/${note.id}/attachments`), { method: 'POST', body: form, credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || (res.status === 413 ? 'Too large to send at once' : `${res.status} ${res.statusText}`));
      note.attachments = [...(note.attachments || []), ...data.attachments];
      document.getElementById('attachmentPanel')?.replaceWith(this.attachmentPanel(note));
      this.setState('Attached', 'ok');
      return data.attachments;
    } catch (err) {
      this.setState(`Not attached: ${err.message}`, 'error');
      toast(`Not attached: ${err.message}`, 'error', 7000);
      return [];
    }
  },

  /** Attach files and show them at the caret in this text. */
  async attachHere(area, files, sync) {
    const note = this.note;
    if (!note?.can_edit) return;
    const sel = window.getSelection();
    const range = sel.rangeCount && area.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    const added = await this.upload(note, files);
    if (!added.length) return;
    area.focus();
    if (range) { sel.removeAllRanges(); sel.addRange(range); }
    document.execCommand('insertHTML', false, added.map(attachmentHtml).join(''));
    Blocks.decorateLinks(area);
    sync();
  },

  /** The note's photos and files, with a way to open, put in the text, or remove each. */
  attachmentPanel(note) {
    const list = note.attachments || [];
    if (!list.length) return el('span', { id: 'attachmentPanel' });
    const insert = (a) => {
      const { blocks, ctx } = this._blocks;
      const last = note.content[note.content.length - 1];
      if (last && last.type === 'text') last.html = `${last.html || ''}${attachmentHtml(a)}`;
      else note.content.push({ id: newId(), type: 'text', html: attachmentHtml(a) });
      Blocks.renderList(note.content, blocks, ctx);
      this.changed();
    };
    return el('section', { class: 'attachments-panel', id: 'attachmentPanel' },
      el('div', { class: 'tree-head' }, glyph('attach'), ` Attachments (${list.length})`),
      el('ul', { class: 'attachment-list' }, list.map((a) => el('li', { class: 'attachment' },
        a.image
          ? el('img', { class: 'attachment-thumb', src: attachmentUrl(a.id), alt: '', loading: 'lazy',
            onclick: () => { if (!Viewer.open(a.id)) window.open(attachmentUrl(a.id), '_blank', 'noopener'); } })
          : el('span', { class: 'attachment-icon', title: a.kind }, glyph(FILE_ICONS[a.kind] || 'attach')),
        el('div', { class: 'attachment-info' },
          el('a', { href: a.view ? viewUrl(a.id) : attachmentUrl(a.id), target: '_blank', rel: 'noopener', text: a.filename,
            title: Viewer.shows(a) ? 'Open it here (Ctrl-click: in a new tab)' : 'Download, to open in its program',
            onclick: (e) => { if (plainClick(e) && Viewer.open(a.id)) e.preventDefault(); } }),
          el('div', { class: 'hint' }, `${sizeLabel(a.size)} · ${who(a.created_by) || '—'} · ${localTime(a.created_at)}`)),
        el('span', { class: 'attachment-actions' },
          el('a', { class: 'btn btn-secondary btn-sm', href: attachmentUrl(a.id, true), title: 'Download' }, '⤓'),
          note.can_edit && a.image ? el('button', { class: 'btn btn-secondary btn-sm', title: 'Draw and write on it (the photo is kept as it is)',
            onclick: () => this.markUp(a.id) }, glyph('pencil')) : null,
          note.can_edit ? el('button', { class: 'btn btn-secondary btn-sm', title: 'Show it at the end of the page',
            onclick: () => insert(a) }, 'Insert') : null,
          note.can_edit ? el('button', { class: 'btn btn-secondary btn-sm', title: 'Remove from this note (earlier versions keep it)',
            onclick: () => modal({
              title: `Remove “${a.filename}”?`,
              build: (b) => b.append(el('p', {}, 'It leaves this note and its list. Earlier versions in the history still show it. ',
                'Take it out of the text as well if it is shown there.')),
              buttons: [{ label: 'Cancel', kind: 'secondary' }, {
                label: 'Remove', kind: 'danger',
                onClick: async () => {
                  await api('DELETE', `/attachments/${a.id}`);
                  note.attachments = note.attachments.filter((x) => x.id !== a.id);
                  document.getElementById('attachmentPanel')?.replaceWith(this.attachmentPanel(note));
                },
              }],
            }) }, '✕') : null)))));
  },

  attributeBar(note) {
    const bar = el('div', { class: 'attributes' });
    for (const a of note.attributes) {
      // The notebook's own bookkeeping: which version of a supplied protocol this is. It says
      // nothing to anyone reading the protocol, so it is not shown.
      if (a.name === 'seedVersion') continue;
      // A day's or month's own label shown day-first (30-10-2026, 10-2026); it is kept as it is (2026-10-30).
      const shown = ['dateNote', 'monthNote', 'weekNote'].includes(a.name) && /^\d{4}-\d\d(-\d\d)?$/.test(a.value || '')
        ? a.value.split('-').reverse().join('-') : a.value;
      const text = a.type === 'label' ? `#${a.name}${shown ? `=${shown}` : ''}` : `~${a.name}=`;
      bar.append(el('span', { class: `attr attr-${a.type}` }, text,
        a.type === 'relation' ? el('a', { href: `#note=${a.value}`, onclick: (e) => { e.preventDefault(); this.open(a.value); } },
          a.target_title || 'a deleted note') : null,
        note.can_edit && !['dateNote', 'monthNote', 'yearNote', 'weekNote', 'notebookRoot', 'protocolLibrary',
                           'seed', 'seedVersion'].includes(a.name)
          ? el('button', { class: 'attr-x', title: 'Remove', onclick: async () => {
            try { await api('DELETE', `/attributes/${a.id}`); note.attributes = note.attributes.filter((x) => x !== a); bar.replaceWith(this.attributeBar(note)); } catch (err) { toast(err.message, 'error'); }
          } }, '×') : null));
    }
    if (note.can_edit) {
      bar.append(el('button', { class: 'attr-add', title: 'Add a label (#project=GFP) or a relation to another note (~usesProtocol)', onclick: () => this.addAttribute(note, bar) }, '＋ label'));
    }
    return bar;
  },

  addAttribute(note, bar) {
    modal({
      title: 'Add a label or relation',
      build: (body) => body.append(
        el('p', { class: 'hint' }, 'A label tags the page (#project=GFP); a relation points at another note (~usesProtocol → a protocol). ',
          'Labels can be searched for and make pages easy to group.'),
        el('div', { class: 'form-row' },
          el('select', { id: 'attrType' }, el('option', { value: 'label' }, '# label'), el('option', { value: 'relation' }, '~ relation')),
          el('input', { type: 'text', id: 'attrName', placeholder: 'name, e.g. project' }),
          el('input', { type: 'text', id: 'attrValue', placeholder: 'value (labels)' }))),
      buttons: [{ label: 'Cancel', kind: 'secondary' }, {
        label: 'Add',
        onClick: async ({ body }) => {
          const type = body.querySelector('#attrType').value;
          let value = body.querySelector('#attrValue').value;
          if (type === 'relation') {
            const target = await pickNote([], 'Relation to which note?');
            if (!target) return false;
            value = target.id;
          }
          const { attribute } = await api('POST', `/notes/${note.id}/attributes`, {
            type, name: body.querySelector('#attrName').value, value,
          });
          if (type === 'relation') attribute.target_title = (await api('GET', `/notes/${value}`)).note.title;
          note.attributes.push(attribute);
          bar.replaceWith(this.attributeBar(note));
          return true;
        },
      }],
    });
  },

  /**
   * A day's bookings in the Booking tool: whoever the notebook belongs to booked them, or is in them.
   * Live while the day is today or ahead; kept as they stood once it is over. Under each, what was
   * done with the time, written here and kept with the day.
   */
  bookingsPanel(note) {
    const data = note.bookings;
    if (!data || (!data.items.length && !data.upcoming.length)) return null;
    const time = (s) => new Date(s).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const dayOf = (s) => new Date(s).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
    const ymd = (s) => { const d = new Date(s); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
    const span = (b) => {
      const sameDay = ymd(b.start) === ymd(b.end) || (time(b.end) === '00:00' && new Date(b.end) - new Date(b.start) <= 864e5);
      return sameDay ? `${time(b.start)}–${time(b.end) === '00:00' ? '24:00' : time(b.end)}`
        : `${dayOf(b.start)} ${time(b.start)} – ${dayOf(b.end)} ${time(b.end)}`;
    };
    const open = (b) => `${data.link}/#calendar=${encodeURIComponent(b.resource.id)}&d=${ymd(b.start)}`;
    const others = (b) => [b.booked_by, ...b.people].filter((p) => p !== note.owner);
    const row = (b) => {
      const notes = note.can_edit ? el('textarea', {
        class: 'booking-notes', rows: 1, placeholder: 'What was done: e.g. imaged 12 seedlings, 488 nm at 4%',
        onchange: async (e) => {
          try { await api('PUT', `/notes/${note.id}/bookings/${b.id}`, { text: e.target.value }); b.notes = e.target.value; toast('Saved', 'success', 1500); }
          catch (err) { toast(err.message, 'error'); }
        },
      }, b.notes || '') : (b.notes ? el('div', { class: 'booking-notes-text' }, b.notes) : null);
      return el('li', { class: 'booking' },
        el('span', { class: 'booking-dot', style: `background:${b.resource.colour}` }),
        el('div', { class: 'booking-body' },
          el('div', {}, el('b', {}, span(b)), ' · ', el('a', { href: open(b), target: '_blank', rel: 'noopener' }, b.resource.name),
            b.resource.location ? el('span', { class: 'hint' }, ` (${b.resource.location})`) : null,
            b.title ? ` · ${b.title}` : null),
          others(b).length ? el('div', { class: 'hint' }, b.role === 'tagged' ? `Booked by ${who(b.booked_by)}${b.people.length > 1 ? `, with ${others(b).filter((p) => p !== b.booked_by).map(who).join(', ')}` : ''}`
            : `With ${others(b).map(who).join(', ')}`) : null,
          notes));
    };
    const panel = el('details', { class: 'bookings-panel', open: !store.get('hideBookings', false),
      ontoggle: (e) => store.set('hideBookings', !e.target.open) },
    el('summary', {}, glyph('calendar'), ` Bookings${data.items.length ? ` (${data.items.length})` : ''}`,
      data.items.length && !data.live ? el('span', { class: 'hint' }, ' · as booked; kept with the day') : null),
    data.items.length ? el('ul', { class: 'booking-list' }, data.items.map(row)) : el('p', { class: 'hint' }, 'Nothing booked today.'),
    data.upcoming.length ? el('div', { class: 'booking-upcoming' }, el('span', { class: 'hint' }, 'Coming up: '),
      data.upcoming.map((b, i) => [i ? ' · ' : '', el('a', { href: open(b), target: '_blank', rel: 'noopener' },
        `${dayOf(b.start)} ${time(b.start)} ${b.resource.name}`)])) : null);
    return panel;
  },

  /** A meeting's page (app/meetings.py): when and where, how often, and who is invited. */
  meetingPanel(note) {
    const m = note.meeting;
    if (!m) return null;
    return el('div', { class: 'meeting-panel' },
      el('div', {}, glyph('people'), ' ', el('b', {}, `${dayMonthYear(m.date)} · ${m.start_time}–${m.end_time}`),
        m.location ? ` · ${m.location}` : null, el('span', { class: 'hint' }, ` · ${m.when}${m.ended ? ' (ended)' : ''}`)),
      el('div', { class: 'hint' }, `Set up by ${who(m.owner)}`,
        m.people.length ? `, with ${m.people.map(who).join(', ')}` : '',
        '. Everyone invited has this page under their day and takes notes on it; only the organiser changes the meeting.'),
      m.can_edit && !m.ended ? el('div', { class: 'meeting-actions' },
        el('button', { class: 'btn btn-secondary btn-sm', title: 'Change the time, the place, how often or who is invited',
          onclick: () => Meetings.edit(m) }, glyph('pencil'), ' Change meeting')) : null);
  },

  linksPanel(note) {
    const parts = [];
    if (note.placements.length + (note.other_places || 0) > 1) {
      parts.push(el('div', {}, el('b', {}, 'In: '), note.placements.map((p, i) => [i ? ', ' : '',
        el('a', { href: `#note=${p.parent_id}`, onclick: (e) => { e.preventDefault(); this.open(p.parent_id); } },
          p.parent_owner && p.parent_owner !== note.owner ? `${p.parent_title} (${who(p.parent_owner)}'s notebook)` : p.parent_title)]),
      note.other_places ? el('span', { class: 'hint' },
        `${note.placements.length ? ', and ' : ''}${note.other_places} place${note.other_places > 1 ? 's' : ''} in someone else's notebook`) : null));
    }
    if (note.backlinks.length) {
      parts.push(el('div', {}, el('b', {}, note.type === 'protocol' ? 'Used on: ' : 'Linked from: '),
        note.backlinks.map((b, i) => [i ? ', ' : '', el('a', { href: `#note=${b.id}`,
          onclick: (e) => { e.preventDefault(); this.open(b.id); } }, b.owner && b.owner !== NB.person.username ? `${b.title} (${who(b.owner)})` : b.title)])));
    }
    return parts.length ? el('footer', { class: 'links-panel' }, parts) : null;
  },

  moreMenu() {
    const note = this.note;
    modal({
      title: note.title,
      build: (body, close) => body.append(el('div', { class: 'menu' },
        note.can_edit && !['day', 'month', 'year'].includes(note.type) ? el('button', { class: 'menu-item', onclick: async () => {
          close();
          const where = await pickNote(note.space === 'library' ? ['protocol', 'folder'] : ['page', 'folder', 'day'], 'Show this note also under…');
          if (!where) return;
          try {
            const { note: updated } = await api('POST', `/notes/${note.id}/placements`, { parent_id: where.id });
            Tree.expanded.add(where.id); Tree.remember();
            await this.reloadTrees();
            this.show(updated);
            toast(`Now also under ${where.title}`, 'success');
          } catch (err) { toast(err.message, 'error'); }
        } }, '⧉ Show also under another page…', el('div', { class: 'hint' }, note.owner && note.owner !== NB.person.username
          ? 'Under a page of your own too, as in Trilium: one page, two places, and a change shows in both.'
          : 'One note in two places, as in Trilium: a change shows in both.')) : null,
        !['month', 'year'].includes(note.type) ? el('button', { class: 'menu-item', onclick: async () => {
          close();
          try {
            const { note: copy } = await api('POST', `/notes/${note.id}/copy`);
            for (const step of copy.path.slice(0, -1)) Tree.expanded.add(step.id);
            Tree.remember();
            await this.reloadTrees();
            this.show(copy);
            toast(`Copied: this is your own “${copy.title}” to change`, 'success', 5000);
            document.querySelector('input.note-title')?.select();
          } catch (err) { toast(err.message, 'error'); }
        } }, '⧉ Make a copy', el('div', { class: 'hint' }, note.space === 'library'
          ? 'A protocol of your own to start from, in the library.' : 'A new page with the same content, in your notebook.')) : null,
        note.can_edit && !['day', 'month', 'year'].includes(note.type) ? el('button', { class: 'menu-item', onclick: async () => {
          close();
          await this.moveNote(note);
        } }, '↪ Move to…', el('div', { class: 'hint' }, note.space === 'library' ? 'Into a folder of the library.' : 'Under another page or day.')) : null,
        note.can_add && !(note.space === 'library' && note.type === 'protocol') ? el('button', { class: 'menu-item', onclick: async () => {
          close();
          this.newNote(note.space === 'library' ? 'library' : 'mine', note.id, note.space === 'library' ? 'protocol' : 'page');
        } }, note.space === 'library' ? '＋ New protocol in this folder' : '＋ New page under this one') : null,
        note.can_delete ? el('button', { class: 'menu-item danger', onclick: () => {
          close();
          const dated = ['day', 'month', 'year'].includes(note.type);
          modal({
            title: `Delete “${note.title}”?`,
            build: (b) => b.append(el('p', {}, note.type === 'year' || note.type === 'month'
              ? 'It, and every day and page under it, go to Deleted, at the bottom of the left-hand side, '
              : 'It and the pages under it go to Deleted, at the bottom of the left-hand side, ',
            'where you (or an administrator) can bring them back.'),
            dated ? el('p', { class: 'hint' }, 'Starting that date again later makes a new page. The old one can only come back once the new one is gone.') : null),
            buttons: [{ label: 'Cancel', kind: 'secondary' }, {
              label: 'Delete', kind: 'danger',
              onClick: async () => {
                await api('DELETE', `/notes/${note.id}`);
                const parent = note.path[note.path.length - 2];
                this.note = null;
                await this.reloadTrees();
                if (parent && !['notebook', 'library'].includes(parent.type)) this.open(parent.id);
                else this.showEmpty();
                toast('Deleted: it can be brought back from Deleted', 'success', 5000);
              },
            }],
          });
        } }, glyph('trash'), ' Delete') : null)),
    });
  },

  /** Move a note under another (or to the top), by its first place. */
  async moveNote(note) {
    const top = { id: note.space === 'library' ? this.me.library : this.me.notebook,
      title: note.space === 'library' ? 'The top of the library' : 'The top of my notebook', type: 'notebook' };
    const target = await picker({
      title: `Move “${note.title}” to…`, placeholder: 'Search by title',
      search: async (q) => {
        const types = note.space === 'library' ? ['folder'] : ['page', 'folder', 'day', 'month', 'year'];
        const found = (await api('GET', `/search?q=${encodeURIComponent(q)}&types=${types.join(',')}`)).notes
          .filter((n) => n.space === note.space && n.id !== note.id && (note.space === 'library' || n.owner === note.owner));
        return q || (note.space === 'notebook' && note.owner !== NB.person.username) ? found : [top, ...found];
      },
      describe: (n) => [noteGlyph(n.type), ' ', el('b', { text: n.title }), n.where ? el('span', { class: 'hint' }, ` · ${n.where}`) : null],
    });
    if (!target) return;
    try {
      await api('POST', `/branches/${note.placements[0].branch_id}/move`, { parent_id: target.id });
      Tree.expanded.add(target.id); Tree.remember();
      await this.reloadTrees();
      await this.open(note.id);
      toast(`Moved to ${target.title}`, 'success');
    } catch (err) { toast(err.message, 'error'); }
  },

  /**
   * Use a protocol: ask where (today, at the top of the list, or any page you may add to), and make it a
   * page of its own under that one, as it is now, to tick off there. Opens the new page.
   */
  async addToPage(protocolId) {
    await this.flush();
    const target = await pickProtocolTarget();
    if (!target) return;
    try {
      const { note } = await api('POST', `/protocols/${protocolId}/use`, target.today ? {} : { parent_id: target.id });
      for (const step of note.path.slice(0, -1)) Tree.expanded.add(step.id);
      Tree.remember();
      await this.reloadTrees();
      this.show(note);
      const under = note.path[note.path.length - 2];
      toast(`Added as a page under ${under ? under.title : 'your notebook'}`, 'success');
    } catch (err) { toast(err.message, 'error'); }
  },

  /** The whole protocol library: search, folders, favourites. */
  async showLibrary() {
    await this.flush();
    this.note = null;
    Tree.markActive('');
    this.setTab('protocols');
    this.view('library');
    const box = document.getElementById('library');
    const query = el('input', { type: 'search', class: 'library-search', placeholder: 'Search protocols by name or by what is in them',
      value: this._libraryQuery || '' });
    const onlyFav = el('input', { type: 'checkbox', checked: !!this._onlyFav });
    const list = el('div', { class: 'library-list' });
    const draw = async () => {
      this._libraryQuery = query.value;
      this._onlyFav = onlyFav.checked;
      let protocols = (await api('GET', `/protocols?q=${encodeURIComponent(query.value.trim())}`)).protocols;
      if (onlyFav.checked) protocols = protocols.filter((p) => p.favorite);
      const groups = new Map();
      for (const p of protocols) {
        if (!groups.has(p.folder)) groups.set(p.folder, []);
        groups.get(p.folder).push(p);
      }
      const folders = [...groups.keys()].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)));
      put(list, protocols.length ? folders.map((folder) => el('div', { class: 'library-group' },
        folder ? el('h3', { class: 'library-folder' }, glyph('folder'), ` ${folder}`) : null,
        el('table', { class: 'library-table' }, el('tbody', {}, groups.get(folder).map((p) => el('tr', {},
          el('td', { class: 'star-cell' }, el('button', {
            class: `star-btn ${p.favorite ? 'on' : ''}`, title: p.favorite ? 'Remove from favourites' : 'Add to favourites',
            onclick: async (e) => {
              const star = e.currentTarget;
              p.favorite = await this.toggleFavorite(p.id, !p.favorite);
              star.textContent = p.favorite ? '★' : '☆';
              star.classList.toggle('on', p.favorite);
              star.title = p.favorite ? 'Remove from favourites' : 'Add to favourites';
            },
          }, p.favorite ? '★' : '☆')),
          el('td', {}, el('a', { href: `#note=${p.id}`, class: 'library-title', onclick: (e) => { e.preventDefault(); this.open(p.id); } }, p.title),
            el('div', { class: 'hint' }, `by ${who(p.created_by) || 'the MoClo Library Tool'}`,
              p.updated_by && p.updated_by !== p.created_by ? ` · changed by ${who(p.updated_by)}` : '', ` · ${localTime(p.updated_at).slice(0, 10)}`,
              p.shared && p.lab ? el('span', { class: 'badge badge-shared', title: 'Shared with your lab by another lab' }, ` shared by ${p.lab}`) : null,
              !p.shared && p.shares ? el('span', { class: 'badge badge-shared', title: 'Shared with other labs' }, ` shared with ${p.shares} lab${p.shares > 1 ? 's' : ''}`) : null,
              !p.lab && !p.shared ? el('span', { class: 'hint' }, ' · every lab') : null)),
          el('td', { class: 'hint nowrap uses-cell' }, p.uses ? `used ${p.uses}×` : 'not used yet'),
          el('td', { class: 'nowrap use-cell' }, el('button', { class: 'btn btn-secondary btn-sm',
            title: "Use it: a page of its own under today's day, or under any page you choose",
            onclick: () => this.addToPage(p.id) }, '＋ Add to page…'))))))))
        : el('p', { class: 'hint' }, query.value || onlyFav.checked ? 'No protocols match.' : 'No protocols yet: add the first.'));
    };
    let timer;
    query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(draw, 250); });
    onlyFav.addEventListener('change', draw);
    put(box,
      el('div', { class: 'library-head' },
        el('h1', {}, glyph('protocol'), ' Protocol library'),
        el('span', { class: 'note-actions' },
          el('button', { class: 'btn btn-primary btn-sm', onclick: () => this.newNote('library', this.me.library, 'protocol') }, '＋ New protocol'),
          el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.newNote('library', this.me.library, 'folder') }, '＋ New folder'),
          el('button', { class: 'btn btn-secondary btn-sm', title: 'Every protocol you can see, as a PDF or a Word document',
            onclick: () => Exports.open({ id: this.me.library, title: 'Protocol library', kind: 'notebook' }) }, '⤓ Export'))),
      el('p', { class: 'hint' }, 'Your lab\'s protocols, the ones other labs share with it, and those supplied with the notebook. ',
        'Anyone can add a protocol; its author, their lab lead and administrators can change it, and share it with other labs (Share, on the protocol). ',
        'Star the ones you use most: they are listed on the left, and offered first when you add a protocol to a page.'),
      el('div', { class: 'library-filters' }, query, el('label', { class: 'checkbox' }, onlyFav, ' Favourites only')),
      list);
    query.focus();
    await draw();
  },

  /** Deleted pages and protocols this person may bring back. */
  async showDeleted() {
    await this.flush();
    this.note = null;
    Tree.markActive('');
    this.setTab('notebook');
    this.view('deleted');
    const box = document.getElementById('deletedView');
    const draw = async () => {
      const { deleted } = await api('GET', '/deleted');
      put(box,
        el('div', { class: 'library-head' }, el('h1', {}, glyph('trash'), ' Deleted')),
        el('p', { class: 'hint' }, NB.person.role === 'admin'
          ? 'Everything deleted from any notebook or the protocol library. Restoring brings back what was deleted with it, to where it was.'
          : 'What you deleted from your notebook, and protocols you may change. Restoring brings back what was deleted with it, to where it was.'),
        deleted.length ? el('table', { class: 'library-table deleted-table' }, el('tbody', {}, deleted.map((d) => el('tr', {},
          el('td', {}, el('div', { class: 'library-title' }, noteGlyph(d.type), ` ${d.title}`),
            el('div', { class: 'hint' },
              d.space === 'library' ? 'Protocol library' : (d.owner !== NB.person.username ? `${d.owner}'s notebook` : 'My notebook'),
              d.was_under ? ` › ${d.was_under}${d.parent_deleted ? ' (deleted too)' : ''}` : '',
              d.pages > 1 ? ` · with ${d.pages - 1} page${d.pages > 2 ? 's' : ''} under it` : '')),
          el('td', { class: 'hint' }, `deleted by ${d.deleted_by || '—'}`, el('div', {}, localTime(d.deleted_at))),
          el('td', { class: 'nowrap use-cell' },
            el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              const { note } = await api('GET', `/deleted/${d.id}`);
              const inner = el('div', { class: 'blocks' });
              Blocks.renderList(note.content, inner, { editable: false, changed() {} });
              modal({ title: `${note.title} (deleted)`, wide: true, build: (b) => b.append(inner) });
            } }, 'View'), ' ',
            el('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
              try {
                const res = await api('POST', `/deleted/${d.id}/restore`);
                await this.reloadTrees();
                await this.loadFavorites();
                toast(`Restored “${d.title}”${d.parent_deleted ? ', to the top, as its old place is deleted too' : ''}`, 'success', 6000);
                if (res.note) this.show(res.note); else draw();
              } catch (err) { toast(err.message, 'error'); }
            } }, 'Restore'))))))
          : el('p', { class: 'hint' }, 'Nothing deleted.'));
    };
    await draw();
  },

  async history() {
    await this.flush();
    const note = this.note;
    const data = await api('GET', `/notes/${note.id}/revisions`);
    modal({
      title: `History of “${note.title}”`, wide: true,
      build: (body) => {
        const preview = el('div', { class: 'revision-preview' }, el('p', { class: 'hint' }, 'Choose a version to see it.'));
        const rows = data.revisions.map((r) => el('tr', { class: r.number === data.current ? 'current' : '' },
          el('td', {}, String(r.number)),
          el('td', { class: 'nowrap' }, localTime(r.updated_at || r.created_at)),
          el('td', {}, r.changed_by || '—'),
          el('td', {}, { created: 'Created', edited: 'Edited', restored: 'Rolled back' }[r.kind] || r.kind, r.note ? el('div', { class: 'hint' }, r.note) : null),
          el('td', { class: 'nowrap' },
            el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              const { revision } = await api('GET', `/notes/${note.id}/revisions/${r.number}`);
              const inner = el('div', { class: 'blocks' });
              Blocks.renderList(revision.content, inner, { editable: false, changed() {} });
              put(preview, el('h3', {}, `Version ${r.number}: ${revision.title}`), inner);
            } }, 'View'),
            r.number !== data.current && data.can_restore ? el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              const { note: restored } = await api('POST', `/notes/${note.id}/revisions/${r.number}/restore`);
              document.querySelector('.modal-backdrop')?.remove();
              this.show(restored);
              Tree.rename(restored.id, restored.title);
              toast(`Rolled back to version ${r.number}; that is kept as a version too`, 'success', 5000);
            } }, 'Roll back') : null)));
        body.append(el('p', { class: 'hint' }, 'Every saved version, newest first. Edits made within a few minutes of each other are one version.'),
          el('div', { class: 'history-scroll' }, el('table', { class: 'history-table' },
            el('thead', {}, el('tr', {}, ['#', 'When', 'Who', 'What', ''].map((h) => el('th', {}, h)))), el('tbody', {}, rows))),
          preview);
      },
    });
  },

  /* saving ------------------------------------------------------------------- */

  setState(text, kind = '') {
    const s = document.getElementById('saveState');
    if (s) { s.textContent = text; s.className = `save-state ${kind}`; }
  },

  changed() {
    if (!this.note || !this.note.can_edit) return;
    this.dirty = true;
    this.setState('Unsaved changes…');
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.save(), 1200);
  },

  async flush() {
    clearTimeout(this.timer);
    if (this.saving) await this.saving;
    if (this.dirty) await this.save();
  },

  /** What the server keeps: the blocks without anything only the page uses. */
  payload(note) {
    const strip = (blocks) => blocks.map((b) => {
      const { _design, ...rest } = b;
      return rest.type === 'section' ? { ...rest, blocks: strip(rest.blocks || []) } : rest;
    });
    return { title: note.title, content: strip(note.content) };
  },

  async save({ keepalive = false, overwrite = false } = {}) {
    const note = this.note;
    if (!note || !this.dirty) return;
    if (this.saving && !keepalive) { await this.saving; return this.save({ overwrite }); }
    clearTimeout(this.timer);
    this.dirty = false;
    const body = { ...this.payload(note), ...(overwrite ? {} : { base_version: note.version }) };
    if (keepalive) {
      fetch(url(`/api/notes/${note.id}`), { method: 'PUT', keepalive: true, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return;
    }
    this.setState('Saving…');
    this.saving = (async () => {
      try {
        const { note: saved } = await api('PUT', `/notes/${note.id}`, body);
        if (this.note !== note) return;
        note.version = saved.version;
        note.revision = saved.revision;
        note.updated_at = saved.updated_at;
        note.updated_by = saved.updated_by;
        this.stampTicks(saved.content);
        Tree.rename(note.id, saved.title);
        this.setState(this.dirty ? 'Unsaved changes…' : `Saved ${localTime(saved.updated_at).slice(11)}`, 'ok');
      } catch (err) {
        this.dirty = true;
        if (err.payload?.stale) { this.setState('Changed elsewhere', 'error'); this.stale(note, err.payload.note); return; }
        this.setState(`Not saved: ${err.message}`, 'error');
        toast(`Not saved: ${err.message}`, 'error', 7000);
      } finally {
        this.saving = null;
      }
    })();
    await this.saving;
  },

  /** Who ticked what, and when, as the server recorded it. */
  stampTicks(content) {
    const stamps = new Map();
    const walk = (blocks) => {
      for (const b of blocks || []) {
        if (b.type === 'section') walk(b.blocks);
        if (b.type === 'steps' || b.type === 'tasks') for (const i of b.items) if (i.by) stamps.set(`${b.id}|${i.id}`, i);
        if (b.type === 'table') {
          for (const row of b.rows) row.cells.forEach((cell, c) => { if (cell && cell.by) stamps.set(`${b.id}|${row.id}|${c}`, cell); });
        }
      }
    };
    walk(content);
    const apply = (blocks) => {
      for (const b of blocks || []) {
        if (b.type === 'section') apply(b.blocks);
        if (b.type === 'steps' || b.type === 'tasks') {
          for (const i of b.items) {
            const s = stamps.get(`${b.id}|${i.id}`);
            if (s && (i.done || i.by)) { i.by = s.by; i.at = s.at; }
          }
        }
        if (b.type === 'table') {
          for (const row of b.rows) {
            row.cells.forEach((cell, c) => {
              const s = stamps.get(`${b.id}|${row.id}|${c}`);
              if (s && cell) row.cells[c] = { by: s.by, at: s.at };
            });
          }
        }
      }
    };
    apply(this.note.content);
    for (const [key, s] of stamps) {
      for (const label of document.querySelectorAll(`[data-tick="${CSS.escape(key)}"]`)) {
        label.textContent = key.split('|').length === 2 ? `✓ ${who(s.by)} · ${localTime(s.at)}` : `${who(s.by)} · ${localTime(s.at)}`;
      }
    }
  },

  stale(mine, theirs) {
    modal({
      title: 'Changed since you opened it',
      build: (body) => body.append(el('div', { class: 'alert' },
        `“${theirs.title}” was saved again by ${theirs.updated_by || 'someone'} at ${localTime(theirs.updated_at)}, `,
        'perhaps in another window.'),
      el('p', { class: 'hint' }, 'Keep yours (the other stays in the history), or open the saved version instead.')),
      buttons: [
        { label: 'Open the saved version', kind: 'secondary', onClick: () => { this.dirty = false; this.show(theirs); } },
        { label: 'Keep mine', onClick: async () => { this.dirty = true; await this.save({ overwrite: true }); } },
      ],
    });
  },

  /* the formatting bar for text ---------------------------------------------- */

  /**
   * The marker: its button switches it on and off, for what is typed next; with text selected, it marks the
   * selection, or takes the marking off when it is all marked already. ▾ chooses its colour.
   */
  markerTool(area, sync, cmd, bar) {
    const pen = el('span', { class: 'marker-a', style: `background:${MARKERS[Marker.colour]}` }, '✎');
    const button = el('button', { class: Marker.on ? 'on' : '', title: 'Marker: switch it on or off (with text selected, mark it or unmark it)',
      'aria-pressed': String(Marker.on) });
    const show = () => { button.classList.toggle('on', Marker.on); button.setAttribute('aria-pressed', String(Marker.on)); pen.style.background = MARKERS[Marker.colour]; };
    const selected = () => {
      const sel = window.getSelection();
      return sel.rangeCount && !sel.isCollapsed && area.contains(sel.anchorNode) ? sel.getRangeAt(0) : null;
    };
    // Whether all the selected text is highlighted in the marker's colour already.
    const allMarked = (range) => {
      const walker = document.createTreeWalker(range.commonAncestorContainer, NodeFilter.SHOW_TEXT);
      let n = walker.currentNode.nodeType === Node.TEXT_NODE ? walker.currentNode : walker.nextNode();
      let any = false;
      for (; n; n = walker.nextNode()) {
        if (!range.intersectsNode(n) || !n.textContent.trim()) continue;
        any = true;
        if (n.parentElement.closest('mark')?.className !== `hl-${Marker.colour}`) return false;
      }
      return any;
    };
    const mark = (e, name) => { e.preventDefault(); if (Blocks.restyle(area, 'mark', name)) sync(); };
    button.append(pen);
    button.addEventListener('mousedown', (e) => {
      const range = selected();
      if (range) mark(e, allMarked(range) ? 'none' : Marker.colour);
      else { e.preventDefault(); Marker.on = !Marker.on; show(); }
    });
    const menu = el('div', { class: 'format-swatches', hidden: true },
      Object.entries(MARKERS).map(([name, hex]) => el('button', {
        class: 'swatch', title: name, style: `background:${hex}`,
        onmousedown: (e) => {
          Marker.colour = name;
          menu.hidden = true;
          if (selected()) mark(e, name);
          else { e.preventDefault(); Marker.on = true; }
          show();
        },
      })),
      // No highlight: off the selection; else off the highlighted stretch the cursor is in. The marker goes off too.
      el('button', { class: 'swatch none', title: 'No highlight', onmousedown: (e) => {
        menu.hidden = true;
        Marker.on = false;
        show();
        if (selected()) { mark(e, 'none'); return; }
        e.preventDefault();
        const sel = window.getSelection();
        const at = sel.rangeCount && area.contains(sel.anchorNode) ? sel.anchorNode : null;
        const stretch = (at?.nodeType === Node.ELEMENT_NODE ? at : at?.parentElement)?.closest('mark');
        if (!stretch || !area.contains(stretch)) return;
        const kept = Blocks.selectionOffsets(area);
        stretch.replaceWith(...stretch.childNodes);
        for (const inner of area.querySelectorAll('mark.hl-none')) if (!inner.parentElement.closest('mark')) inner.replaceWith(...inner.childNodes);
        if (kept) Blocks.selectOffsets(area, kept);
        sync();
      } }, '⌀'));
    const more = el('button', { class: 'format-more', title: 'The marker\'s colour', onmousedown: (e) => {
      e.preventDefault();
      for (const m of bar.querySelectorAll('.format-swatches')) if (m !== menu) m.hidden = true;
      menu.hidden = !menu.hidden;
    } }, '▾');
    return el('span', { class: 'format-menu' }, button, more, menu);
  },

  showFormatBar(area, sync) {
    let bar = document.getElementById('formatBar');
    if (!bar) {
      bar = el('div', { class: 'format-bar', id: 'formatBar' });
      document.body.append(bar);
    }
    const cmd = (command, value) => (e) => {
      e.preventDefault();
      document.execCommand('styleWithCSS', false, false);
      document.execCommand(command, false, value);
      Blocks.tidyFormatting(area);
      sync();
    };
    // A colour chosen with text selected: all of it that colour, whatever colours its parts had. Without a
    // selection, the colour of what is typed next.
    const restyle = (e, name, hex) => {
      if (Blocks.restyle(area, 'colour', name)) { e.preventDefault(); sync(); } else cmd('foreColor', hex)(e);
    };
    // A row of colours under the bar, opened by a button on it.
    const swatches = (title, glyphText, colours, command, none) => {
      const menu = el('div', { class: 'format-swatches', hidden: true },
        Object.entries(colours).map(([name, hex]) => el('button', {
          class: 'swatch', title: name, style: command === 'foreColor' ? `color:${hex}` : `background:${hex}`,
          onmousedown: (e) => { restyle(e, name, hex); menu.hidden = true; },
        }, command === 'foreColor' ? 'A' : '')),
        el('button', { class: 'swatch none', title: none, onmousedown: (e) => { restyle(e, 'none', NO_COLOUR); menu.hidden = true; } }, '⌀'));
      const button = el('button', { title, onmousedown: (e) => {
        e.preventDefault();
        for (const m of bar.querySelectorAll('.format-swatches')) if (m !== menu) m.hidden = true;
        menu.hidden = !menu.hidden;
      } }, glyphText);
      return el('span', { class: 'format-menu' }, button, menu);
    };
    put(bar, 
      el('button', { title: 'Bold (Ctrl+B)', onmousedown: cmd('bold') }, el('b', {}, 'B')),
      el('button', { title: 'Italic (Ctrl+I)', onmousedown: cmd('italic') }, el('i', {}, 'I')),
      el('button', { title: 'Underline (Ctrl+U)', onmousedown: cmd('underline') }, el('u', {}, 'U')),
      el('button', { title: 'Strike through', onmousedown: cmd('strikethrough') }, el('s', {}, 'S')),
      swatches('Colour of the letters', el('span', { class: 'colour-a' }, 'A'), TEXT_COLOURS, 'foreColor', 'No colour'),
      this.markerTool(area, sync, cmd, bar),
      el('span', { class: 'format-sep' }),
      el('button', { title: 'Heading 1: a title', onmousedown: cmd('formatBlock', 'h1') }, 'H1'),
      el('button', { title: 'Heading 2', onmousedown: cmd('formatBlock', 'h2') }, 'H2'),
      el('button', { title: 'Heading 3', onmousedown: cmd('formatBlock', 'h3') }, 'H3'),
      el('button', { title: 'Paragraph', onmousedown: cmd('formatBlock', 'p') }, '¶'),
      el('button', { title: 'Bulleted list', onmousedown: cmd('insertUnorderedList') }, '•'),
      el('button', { title: 'Numbered list (or type "1. " at the start of a line)', onmousedown: cmd('insertOrderedList') }, '1.'),
      el('button', { title: 'Web link: add, change or remove one on the selected text (Ctrl+K)', onmousedown: (e) => {
        e.preventDefault();
        Blocks.webLinkBox(area, sync, bar);
      } }, '🔗'),
      el('button', { title: 'Link a plasmid or note (or type @)', onmousedown: (e) => {
        e.preventDefault();
        const sel = window.getSelection();
        if (!sel.rangeCount || !area.contains(sel.anchorNode)) return;
        Blocks.linkAt(area, sel.getRangeAt(0), sync);
      } }, '@'));
    /**
     * Just above the line being written on - where the caret is, not the top of the section, which in a
     * long section may be far up the page or off the screen - and below that line when there is no room
     * above it. Always in sight: never above the page's own bar, nor off the sides of the window.
     */
    const place = () => {
      const box = area.getBoundingClientRect();
      const gap = (bar.offsetHeight || 34) + 6;
      // Under the page's own bar, measured rather than assumed: it is sticky, and grows taller when
      // its buttons wrap, so a fixed number hides this bar behind it.
      const head = document.querySelector('header.tt-bar');
      const under = (head ? head.getBoundingClientRect().bottom : 52) + 4;
      let line = null;
      const sel = window.getSelection();
      if (sel.rangeCount && area.contains(sel.anchorNode)) {
        const range = sel.getRangeAt(0).cloneRange();
        range.collapse(false);
        const rects = range.getClientRects();
        line = rects.length ? rects[rects.length - 1] : null;
        // An empty line has no box of its own: the element the caret is in has one.
        if (!line || (!line.height && !line.top)) {
          const node = sel.focusNode?.nodeType === Node.ELEMENT_NODE ? sel.focusNode : sel.focusNode?.parentElement;
          line = node && area.contains(node) ? node.getBoundingClientRect() : null;
        }
      }
      const top = line ? line.top : box.top;
      const bottom = line ? line.bottom : box.top + 24;
      let y = top - gap;
      if (y < under) y = Math.min(bottom + 6, window.innerHeight - gap);
      bar.style.top = `${Math.max(y, under)}px`;
      const width = bar.offsetWidth || 420;
      const x = Math.min(Math.max((line ? line.left : box.left) - 12, box.left, 8), window.innerWidth - width - 8);
      bar.style.left = `${Math.max(x, 8)}px`;
    };
    // One bar for the page, and one section it belongs to at a time: moving from one section to the next,
    // the first one's leaving must not hide the bar the second has just shown.
    bar._owner = area;
    bar.hidden = false;
    place();
    if (bar._follow) {
      window.removeEventListener('scroll', bar._follow, true);
      window.removeEventListener('resize', bar._follow);
      document.removeEventListener('selectionchange', bar._follow);
    }
    // Scrolling, resizing, and the caret moving (a click further down, typing onto a new line) keep it
    // with the line being written on.
    const follow = () => { if (!bar.hidden && bar._owner === area) place(); };
    bar._follow = follow;
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', follow);
    document.addEventListener('selectionchange', follow);
    const hide = () => {
      setTimeout(() => {
        if (bar._owner !== area) return;            // another section has it now
        if (bar.matches(':hover') || document.activeElement === area || bar.contains(document.activeElement)) return;
        bar.hidden = true;
        window.removeEventListener('scroll', follow, true);
        window.removeEventListener('resize', follow);
        document.removeEventListener('selectionchange', follow);
        bar._follow = null;
      }, 150);
    };
    area.addEventListener('blur', hide, { once: true });
    // Clicked in again while still being written in, and the bar is gone for any reason: back it comes.
    if (!area._barOnClick) {
      area._barOnClick = true;
      area.addEventListener('mouseup', () => {
        if (document.activeElement === area && (bar.hidden || bar._owner !== area)) App.showFormatBar(area, sync);
      });
    }
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
