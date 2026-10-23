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

/** A time the server stored (UTC "YYYY-MM-DD HH:MM:SS"), in local time. */
function localTime(stamp) {
  if (!stamp) return '';
  const d = new Date(String(stamp).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(stamp) ? '' : 'Z'));
  if (Number.isNaN(d.getTime())) return String(stamp).slice(0, 16);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const newId = () => Math.random().toString(16).slice(2, 14);
const attachmentUrl = (id, download = false) => url(`/api/attachments/${encodeURIComponent(id)}${download ? '?download' : ''}`);
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
const sizeLabel = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`);
const FILE_ICONS = { pdf: '📕', word: '📝', powerpoint: '📽️', excel: '📊', archive: '🗜️', sequence: '🧬', text: '📄', image: '🖼️', file: '📎' };
/** An attachment as it sits in text: a photo shown, any other file a link with its icon. */
const attachmentHtml = (a) => (a.image
  ? `<p><img data-attachment="${a.id}" alt="${escapeHtml(a.filename)}"></p>`
  : `<p><a data-attachment="${a.id}">${FILE_ICONS[a.kind] || '📎'} ${escapeHtml(a.filename)}</a></p>`);
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(`nb:${key}`)) ?? fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(`nb:${key}`, JSON.stringify(value)); } catch (e) { /* private window */ } },
};
// Sections other tools put into a day, by their source's kind: an icon, and where they come from
// (as content.IMPORTED_LABELS says on the server).
const IMPORTED = {
  'virtual-digest': ['✂️', 'A virtual digest from the Plasmid Editor'],
  'plasmid-map': ['🧬', 'A plasmid map from the Plasmid Editor'],
  'cloning-product': ['🔗', 'A cloning product from the Plasmid Editor'],
  pcr: ['🧪', 'A PCR from the Plasmid Editor'],
  primers: ['🧷', 'Primers designed in the Plasmid Editor'],
  'sequencing-read': ['📈', 'A sequencing read from the Plasmid Editor'],
  'moclo-plasmid': ['🧬', 'A plasmid from the MoClo Library Tool'],
  'moclo-cassette': ['🧩', 'A cassette from the MoClo Library Tool'],
  'moclo-part': ['🧱', 'A part from the MoClo Library Tool'],
};
const ICONS = { notebook: '📓', library: '📚', year: '🗓️', month: '📆', day: '📅', page: '📄', folder: '📁', protocol: '🧪' };
const editorLink = (id) => `${NB.editor}/editor?open=${encodeURIComponent(id)}`;
const SEED_KINDS = { L: 'line', S: 'lot', P: 'plant' };
// GL-S-0042 (or S-0042 from before lab codes): the letter before the number says what it is.
// GL-G-0042 a glycerol stock, GL-O-0007 a primer, GL-C-0003 a chemical, GL-A-0005 an antibody, GL-M-0001 plant
// material, in Lab Stocks.
const STOCK_KINDS = { G: 'glycerol', O: 'primer', C: 'chemical', A: 'antibody', M: 'material' };
const stockLink = (code) => `${NB.stocks}/#${STOCK_KINDS[code.split('-').slice(-2, -1)[0]] || 'glycerol'}=${encodeURIComponent(code)}`;
const seedLink = (code) => `${NB.seeds}/#${SEED_KINDS[code.split('-').slice(-2, -1)[0]] || 'line'}=${encodeURIComponent(code)}`;

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

const pickPlasmid = () => picker({
  title: 'Link a plasmid', placeholder: 'Search the plasmid library',
  search: async (q) => (await api('GET', `/plasmids?q=${encodeURIComponent(q)}`)).plasmids,
  describe: (p) => [el('b', { text: p.name }), el('span', { class: 'hint' },
    ` · ${p.length.toLocaleString()} bp${p.circular ? ', circular' : ''}${p.owner ? ` · ${p.owner}` : ''}`
    + `${p.confirmed ? ' · ✓ sequenced' : ''}`)],
});

const pickNote = (types, title = 'Choose a note') => picker({
  title, placeholder: 'Search by title',
  search: async (q) => (await api('GET', `/search?q=${encodeURIComponent(q)}&types=${(types || []).join(',')}`)).notes,
  describe: (n) => [`${ICONS[n.type] || '📄'} `, el('b', { text: n.title }),
    n.owner && n.owner !== NB.person.username ? el('span', { class: 'hint' }, ` · ${n.owner}`) : null],
});

/** Choose a protocol: your favourites first, then the rest of the library. */
const pickProtocol = () => picker({
  title: 'Use a protocol', placeholder: 'Search the protocol library',
  search: async (q) => {
    const all = (await api('GET', `/protocols?q=${encodeURIComponent(q)}`)).protocols;
    return [...all.filter((p) => p.favorite), ...all.filter((p) => !p.favorite)];
  },
  describe: (p) => [p.favorite ? '★ ' : '🧪 ', el('b', { text: p.title }),
    el('span', { class: 'hint' }, `${p.folder ? ` · ${p.folder}` : ''} · by ${p.created_by || 'MoClo'}`)],
});

/** Choose a line, seed lot or plant from the seed bank (the lab's own; other labs' are not found). */
const pickSeed = () => picker({
  title: 'Link a seed lot, plant or line', placeholder: 'Search the seed bank by code or name',
  search: async (q) => {
    const res = await fetch(`${NB.seeds}/api/search?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? 'The seed bank is not part of this suite' : `Seed bank: ${res.status}`);
    return (await res.json()).results;
  },
  describe: (r) => [{ line: '🧬 ', lot: '🫘 ', plant: '🌱 ' }[r.kind], el('b', { text: r.code }), ` ${r.label.slice(r.code.length)}`,
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
  describe: (r) => [{ glycerol: '🧫 ', primer: '🧬 ', chemical: '⚗️ ', antibody: '🔬 ', material: '🌿 ' }[r.kind] || '🧫 ', el('b', { text: r.code }), ` ${r.label.slice(r.code.length)}`,
    el('span', { class: 'hint' }, ` · ${{ glycerol: 'glycerol stock', material: 'plant material' }[r.kind] || r.kind}`)],
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
    }, toggle, el('span', { class: 'tree-icon' }, ICONS[item.type] || '📄'),
    el('span', { class: 'tree-title', text: item.title }), item.cloned ? el('span', { class: 'tree-clone' }, '⧉') : null,
    item.shared ? el('span', { class: 'tree-shared', title: 'Shared to work on together' }, '👥') : null,
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
    // Ctrl+K (or /) jumps to search, from anywhere outside a text field.
    document.addEventListener('keydown', (e) => {
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
      }, el('div', { class: 'search-title' }, `${ICONS[n.type] || '📄'} `, mark(n.title)),
      el('div', { class: 'hint' }, [n.space === 'library' ? 'Protocol library' : (n.owner !== NB.person.username ? `${n.owner}'s notebook` : ''),
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
    }
    return box;
  },

  render(block, ctx) {
    switch (block.type) {
      case 'text': return this.text(block, ctx);
      case 'table': return this.table(block, ctx);
      case 'steps': return this.steps(block, ctx);
      case 'section': return this.section(block, ctx);
      case 'gel': return this.gel(block, ctx);
      default: return el('div', { class: 'hint' }, `(${block.type})`);
    }
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
      ? { one: 'Lane', label: 'Sample', labelHint: 'e.g. pGFP clone 3', noteHint: 'e.g. 5 µL, ladder', mark: '✚ Mark wells',
        markTitle: 'Click wells on the photo to add lanes', none: 'No wells marked', clear: 'Take away all the lanes?',
        title: 'Gel, e.g. Colony PCR, 1% agarose',
        prompt: '👆 Click each well you loaded, in every row of wells. Lanes are numbered row by row, top to bottom, each row left to right; click a number to take it away.' }
      : { one: 'No.', label: 'Label', labelHint: 'e.g. Col-0 #1', noteHint: 'e.g. resistant, flowering', mark: '✚ Number spots',
        markTitle: 'Click on the photo to number more spots', none: 'Nothing numbered', clear: 'Take away all the numbers?',
        title: 'Photo, e.g. T1 plants on hygromycin',
        prompt: '👆 Click each one to number it: they are numbered in the order you click. Click a number to take it away.' };
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
              onclick: () => App.markUp(block.attachment, { block }) }, '✏️ Mark up') : null,
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
      'data-placeholder': ctx.editable ? 'Write here. Type @ to link a plasmid or a note.' : '',
    });
    area.innerHTML = block.html || '';          // cleaned by the server
    this.decorateLinks(area);
    area.addEventListener('click', (e) => {
      const photo = e.target.closest('img[data-attachment]');
      if (photo && ctx.editable) { App.photoMenu(photo); return; }
      if (photo) { window.open(attachmentUrl(photo.dataset.attachment), '_blank', 'noopener'); return; }
      const link = e.target.closest('a');
      if (!link) return;
      e.preventDefault();
      if (link.dataset.attachment) window.open(attachmentUrl(link.dataset.attachment), '_blank', 'noopener');
      else if (link.dataset.seed) window.open(seedLink(link.dataset.seed), '_blank', 'noopener');
      else if (link.dataset.stock) window.open(stockLink(link.dataset.stock), '_blank', 'noopener');
      else if (link.dataset.plasmid) window.open(editorLink(link.dataset.plasmid), '_blank', 'noopener');
      else if (link.dataset.note) App.open(link.dataset.note);
      else if (/^https?:/.test(link.getAttribute('href') || '')) window.open(link.href, '_blank', 'noopener');
    });
    if (!ctx.editable) return area;

    const sync = () => { block.html = this.storable(area); ctx.changed(); };
    area.addEventListener('input', () => {
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
    // Pasted text comes in as plain text: what else a page holds is added with the tools.
    // A pasted picture (a screenshot, say) is attached to the note and shown where it was pasted.
    area.addEventListener('paste', (e) => {
      e.preventDefault();
      const files = [...(e.clipboardData.files || [])];
      if (files.length) { App.attachHere(area, files, sync); return; }
      document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
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
    area.addEventListener('focus', () => App.showFormatBar(area, sync));
    return area;
  },

  /** The text as kept: links by what they point at, not by this page's address for it. */
  storable(area) {
    const copy = area.cloneNode(true);
    for (const a of copy.querySelectorAll('a[data-plasmid], a[data-note], a[data-seed], a[data-stock], a[data-attachment]')) {
      for (const attr of ['href', 'class', 'title']) a.removeAttribute(attr);
    }
    for (const img of copy.querySelectorAll('img[data-attachment]')) {
      for (const attr of ['src', 'loading', 'class']) img.removeAttribute(attr);
    }
    return copy.innerHTML;
  },

  decorateLinks(area) {
    for (const a of area.querySelectorAll('a[data-plasmid]')) {
      a.href = editorLink(a.dataset.plasmid);
      a.classList.add('plasmid-link');
      a.title = 'Open in the Plasmid Editor';
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
    for (const img of area.querySelectorAll('img[data-attachment]')) {
      img.src = attachmentUrl(img.dataset.attachment);
      img.loading = 'lazy';
      img.title = 'Open the full picture';
    }
    for (const a of area.querySelectorAll('a[data-attachment]')) {
      a.href = attachmentUrl(a.dataset.attachment);
      a.classList.add('file-link');
      a.title = 'Open (PDFs open in the browser; other files download, to open in Word, PowerPoint…)';
    }
  },

  /** Ask which plasmid or note "@" means, and put a link to it in place of `range`. */
  async linkAt(area, range, sync) {
    const kind = await new Promise((resolve) => {
      let choice = null;
      modal({
        title: 'Link to…',
        onClose: () => resolve(choice),
        build: (body, close) => body.append(el('div', { class: 'choice-row' },
          el('button', { class: 'btn btn-primary', onclick: () => { choice = 'plasmid'; close(); } }, '🧬 A plasmid'),
          el('button', { class: 'btn btn-secondary', onclick: () => { choice = 'seed'; close(); } }, '🌱 A seed lot, plant or line'),
          el('button', { class: 'btn btn-secondary', onclick: () => { choice = 'stock'; close(); } }, '🧫 A stock, primer, chemical, antibody or plant material'),
          el('button', { class: 'btn btn-secondary', onclick: () => { choice = 'note'; close(); } }, '📄 A page or protocol'))),
        buttons: [{ label: 'Just type @', kind: 'secondary' }],
      });
    });
    if (!kind) return;
    let target;
    try {
      target = kind === 'plasmid' ? await pickPlasmid() : kind === 'seed' ? await pickSeed()
        : kind === 'stock' ? await pickStock() : await pickNote([], 'Link to a page or protocol');
    } catch (err) { toast(err.message, 'error'); return; }
    if (!target) return;
    const link = el('a', kind === 'plasmid' ? { 'data-plasmid': target.id } : kind === 'seed' ? { 'data-seed': target.code }
      : kind === 'stock' ? { 'data-stock': target.code } : { 'data-note': target.id },
    kind === 'plasmid' ? target.name : kind === 'seed' || kind === 'stock' ? target.label : target.title);
    range.deleteContents();
    range.insertNode(link);
    link.after(document.createTextNode(' '));
    this.decorateLinks(area);
    const sel = window.getSelection();
    sel.removeAllRanges();
    const after = document.createRange();
    after.setStartAfter(link.nextSibling);
    sel.addRange(after);
    area.focus();
    sync();
  },

  /* steps -------------------------------------------------------------------- */

  steps(block, ctx) {
    const list = el('ol', { class: 'steps-list' });
    const draw = () => put(list, ...block.items.map((item, i) => {
      const done = !!(item.by || item.done);
      const box = el('input', {
        type: 'checkbox', checked: done, disabled: !ctx.editable,
        onchange: () => {
          item.done = box.checked;
          if (!box.checked) { item.by = null; item.at = null; }
          li.classList.toggle('done', box.checked);
          tick.textContent = box.checked ? (item.by ? `✓ ${item.by} · ${localTime(item.at)}` : '✓ saving…') : '';
          ctx.changed();
        },
      });
      const text = ctx.editable
        ? el('input', { type: 'text', class: 'step-text', value: item.text || '', placeholder: 'A step',
          oninput: (e) => { item.text = e.target.value; ctx.changed(); } })
        : el('span', { class: 'step-text', text: item.text });
      const tick = el('span', { class: 'tick', 'data-tick': `${block.id}|${item.id}` }, done && item.by ? `✓ ${item.by} · ${localTime(item.at)}` : '');
      const li = el('li', { class: done ? 'done' : '' }, box, text, tick,
        ctx.editable ? el('button', { class: 'icon-btn faint', title: 'Remove this step',
          onclick: () => { block.items.splice(i, 1); draw(); ctx.changed(); } }, '✕') : null);
      return li;
    }));
    draw();
    return el('div', {},
      ctx.editable
        ? el('input', { type: 'text', class: 'block-title', value: block.title || '', placeholder: 'Steps',
          oninput: (e) => { block.title = e.target.value; ctx.changed(); } })
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
      : src.kind === 'moclo-reaction' ? el('span', {}, 'From the MoClo Library Tool')
        : IMPORTED[src.kind] ? el('span', {}, IMPORTED[src.kind][1]) : null;
    const inner = el('div', { class: 'section-blocks' });
    this.renderList(block.blocks, inner, ctx);
    return el('div', { class: 'section-box' },
      el('div', { class: 'section-head' },
        el('span', { class: 'section-icon' }, src.kind === 'moclo-reaction' ? '🧬' : IMPORTED[src.kind]?.[0] || '🧪'),
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
    const cells = [];             // {input, r, c}

    const update = () => {
      const computed = Sheet.compute(block);
      for (const cell of cells) {
        if (cell.input === document.activeElement) continue;
        const kind = block.columns[cell.c]?.kind;
        const raw = block.rows[cell.r].cells[cell.c] ?? '';
        const shown = computed[cell.r][cell.c];
        cell.input.value = (kind === 'text' && !String(raw).startsWith('=')) ? raw : shown.display;
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
          el('span', { text: col.name || '' }),
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
              label.textContent = box.checked ? (row.cells[c].by ? `${row.cells[c].by} · ${localTime(row.cells[c].at)}` : 'saving…') : '';
              changed();
            },
          });
          const label = el('span', { class: 'tick', 'data-tick': `${block.id}|${row.id}|${c}` },
            value && value.by ? `${value.by} · ${localTime(value.at)}` : '');
          return el('td', { class: 'cell-check' }, box, label);
        }
        const input = el('input', {
          type: 'text', class: `cell kind-${col.kind}`, readonly: !ctx.editable,
          placeholder: col.kind === 'fill' ? (App.note?.space === 'library' ? 'on the day' : 'fill in') : '',
          onfocus: () => { input.value = row.cells[c] ?? ''; input.select(); },
          onblur: () => update(),
          oninput: () => { row.cells[c] = input.value; changed(); },
          onkeydown: (e) => {
            // Enter goes down a row, as in a spreadsheet.
            if (e.key === 'Enter') { e.preventDefault(); cells.find((x) => x.r === r + 1 && x.c === c)?.input.focus(); }
          },
        });
        cells.push({ input, r, c });
        return el('td', {}, input);
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
          onclick: () => { design = !design; block._design = design; draw(); } }, design ? 'Done' : '⚙ Columns'),
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
            el('td', {}, s.target_type === 'lab' ? '🏛 ' : '👤 ', el('b', { text: s.label })),
            el('td', { class: 'hint' }, `by ${s.created_by || '—'} · ${localTime(s.created_at)}`),
            el('td', { class: 'nowrap' }, el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              try { data = await api('DELETE', `/shares/${s.id}`); draw(); onChange?.(); toast(`No longer shared with ${s.label}`, 'success'); } catch (err) { toast(err.message, 'error'); }
            } }, 'Retract'))))))
          : el('p', { class: 'hint' }, notebook ? 'Not shared: only its owner, the lab\'s lead and administrators see it.'
            : page ? 'Not shared: only you (and your lab\'s lead) see it.' : 'Not shared: only its own lab sees it.'));
        const options = [
          ...(data.labs || []).map((lab) => ({ value: `lab:${lab.id}`, label: `🏛 ${lab.name} (the whole lab)` })),
          ...(data.people || []).map((u) => ({ value: `person:${u}`, label: `👤 ${u}` })),
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
    } catch (err) {
      put(document.getElementById('main'), el('div', { class: 'empty-state' }, err.message));
      return;
    }
    document.getElementById('btnToday').addEventListener('click', () => this.startDay());
    document.getElementById('dayPicker').addEventListener('change', (e) => { if (e.target.value) this.startDay(e.target.value); });
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
    if (location.hash.startsWith('#protocols') || location.hash.startsWith('#deleted')) this.route();
    else {
      const start = this.hashNote() || store.get('last', null);
      if (start) this.open(start, { quiet: true });
    }
  },

  /** Follow the address: #note=<id> opens a note, #protocols the library. */
  route() {
    if (location.hash.startsWith('#protocols')) { this.showLibrary(); return; }
    if (location.hash.startsWith('#deleted')) { this.showDeleted(); return; }
    const id = this.hashNote();
    if (id && (id !== this.note?.id || !document.getElementById('library').hidden)) this.open(id);
  },

  setTab(name) {
    document.getElementById('tabNotebook').classList.toggle('active', name === 'notebook');
    document.getElementById('tabProtocols').classList.toggle('active', name === 'protocols');
  },

  /** Show one of the main views (note, library, deleted, or none), hiding the others. */
  view(name) {
    for (const [id, key] of [['note', 'note'], ['library', 'library'], ['deletedView', 'deleted'], ['emptyState', 'empty']]) {
      document.getElementById(id).hidden = key !== name;
    }
  },

  showEmpty() {
    document.getElementById('note').hidden = true;
    document.getElementById('library').hidden = true;
    document.getElementById('deletedView').hidden = true;
    document.getElementById('emptyState').hidden = false;
    this.setTab('notebook');
  },

  async loadFavorites(list) {
    const favs = list || (await api('GET', '/favorites')).favorites;
    this.favorites = new Set(favs.map((f) => f.id));
    put(document.getElementById('favList'), favs.length
      ? favs.map((f) => el('li', { class: `fav-item ${this.note?.id === f.id ? 'active' : ''}`, 'data-id': f.id,
        onclick: () => this.open(f.id) }, el('span', { class: 'tree-icon' }, '🧪'), el('span', { class: 'tree-title', text: f.title })))
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
    try { this.me = await api('GET', '/me'); } catch { /* keep what we had */ }
    await Tree.mount(document.getElementById('treeMine'), this.me.notebook, { editable: true });
    // A notebook's own buttons: export it whole, and share it (its lab's lead, or an admin).
    const actions = (nb) => [
      el('button', { class: 'tree-act', title: `Export ${nb.owner}'s notebook`, onclick: (e) => {
        e.stopPropagation();
        Exports.open({ id: nb.id, title: `${nb.owner}'s notebook`, kind: 'notebook' });
      } }, '⤓'),
      nb.can_share ? el('button', { class: 'tree-act', title: `Share ${nb.owner}'s notebook with a lab or a person`, onclick: (e) => {
        e.stopPropagation();
        Shares.open({ id: nb.id, title: `${nb.owner}'s notebook`, kind: 'notebook' });
      } }, '👥') : null,
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
        await Tree.mount(holder, nb.id, { label: nb.archived ? `${nb.owner} (left)` : nb.owner, actions: actions(nb) });
      }
    }
    // Pages shared to work on together: opened, changed and added to right here.
    if (pages.length) {
      document.getElementById('treeShared').append(el('ul', { class: 'tree-list' }, pages.map((p) => {
        const node = Tree.node(p, false, true);
        node.querySelector('.tree-title').after(el('span', { class: 'tree-owner hint' }, ` · ${p.owner}`));
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
        if (now.updated_by && now.updated_by !== NB.person.username) toast(`Updated by ${now.updated_by}`, 'info', 2500);
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
    this.setTab(note.space === 'library' ? 'protocols' : 'notebook');
    Tree.markActive(note.id);
    for (const f of document.querySelectorAll('.fav-item')) f.classList.toggle('active', f.dataset.id === note.id);
    const editable = note.can_edit;
    const ctx = { editable, changed: () => this.changed() };

    const crumbs = el('nav', { class: 'crumbs' }, note.path.slice(0, -1).map((p, i) => [
      i ? el('span', { class: 'crumb-sep' }, '›') : null,
      el('a', { href: p.type === 'library' ? '#protocols' : `#note=${p.id}`, onclick: (e) => {
        if (p.type === 'library') return;          // the Protocols tab, by its address
        e.preventDefault();
        if (p.type !== 'notebook') this.open(p.id);
      } }, p.title)]));

    const fixedTitle = !editable || ['day', 'month', 'year'].includes(note.type);
    const title = fixedTitle
      ? el('h1', { class: 'note-title', text: note.title })
      : el('input', { type: 'text', class: 'note-title', value: note.title,
        oninput: (e) => { note.title = e.target.value; this.changed(); } });

    const owner = note.space === 'notebook' && note.owner !== NB.person.username;
    const meta = el('div', { class: 'note-meta' },
      el('span', { class: `badge badge-${note.type}` }, `${ICONS[note.type] || ''} ${note.type}`),
      owner ? el('span', { class: 'badge badge-owner' }, `${note.owner}'s notebook`) : null,
      !editable ? el('span', { class: 'badge badge-readonly' }, 'read only') : null,
      ...(note.shared_in || []).map((r) => el('span', {
        class: 'badge badge-shared',
        title: r.id === note.id ? 'Shared to work on together' : `Part of “${r.title}”, shared to work on together`,
      }, note.owner === NB.person.username
        ? `👥 shared with ${r.with.join(', ')}${r.id === note.id ? '' : ` (in ${r.title})`}`
        : `👥 shared by ${note.owner}${r.id === note.id ? '' : ` (in ${r.title})`}`)),
      el('span', { class: 'hint' }, note.updated_by || note.created_by
        ? `Last saved by ${note.updated_by || note.created_by} · ${localTime(note.updated_at)}`
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
          class: 'btn btn-secondary btn-sm', title: "Put this protocol into today's page",
          onclick: () => this.useToday(note.id),
        }, '＋ Use today'),
        note.can_share ? el('button', {
          class: 'btn btn-secondary btn-sm',
          title: note.space === 'library' ? 'Share this protocol with other labs'
            : 'Share this page and the pages under it with people of your chair group, to work on together',
          onclick: () => Shares.open({ id: note.id, title: note.title, kind: note.type, onChange: () => this.refresh() }),
        }, '👥 Share') : null,
        el('button', {
          class: 'btn btn-secondary btn-sm', title: note.has_children ? 'Export this page and everything under it, as a PDF or a Word document' : 'Export as a PDF or a Word document',
          onclick: async () => { await this.flush(); Exports.open({ id: note.id, title: note.title, hasChildren: note.has_children, kind: note.type }); },
        }, '⤓ Export'),
        el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.history() }, '🕘 History'),
        el('button', { class: 'btn btn-secondary btn-sm', title: 'Copy, move, place elsewhere, delete', onclick: () => this.moreMenu() }, '⋯')));

    const blocks = el('div', { class: 'blocks' });
    Blocks.renderList(note.content, blocks, ctx);

    this._blocks = { blocks, ctx };
    put(box, crumbs, el('div', { class: 'note-head' }, title), meta, this.attributeBar(note), this.bookingsPanel(note),
      blocks, editable ? this.insertBar(note, blocks, ctx) : null, this.attachmentPanel(note), this.linksPanel(note));
  },

  insertBar(note, blocks, ctx) {
    const add = (block) => {
      note.content.push(block);
      Blocks.renderList(note.content, blocks, ctx);
      this.changed();
      blocks.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      blocks.lastElementChild?.querySelector('.text-block, input')?.focus();
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
      el('button', { class: 'btn btn-secondary btn-sm', onclick: () => add({ id: newId(), type: 'steps', title: '', items: [{ id: newId(), text: '' }] }) }, '☑ Steps'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'A gel photo: click the wells you used, and name the sample in each',
        onclick: () => this.addGel(note, add) }, '▥ Gel photo…'),
      note.space === 'notebook' ? el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
        const protocol = await pickProtocol();
        if (!protocol) return;
        try { add((await api('GET', `/protocols/${protocol.id}/snapshot`)).section); } catch (err) { toast(err.message, 'error'); }
      } }, '🧪 Protocol…') : null,
      el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
        try { const section = await pickMocloReaction(); if (section) add(section); } catch (err) { toast(err.message, 'error'); }
      } }, '🧬 MoClo reaction…'),
      el('label', { class: 'btn btn-secondary btn-sm', title: 'Attach photos or files: they are shown or linked here, and listed under Attachments. You can also paste or drop them into text.' },
        '📎 Attach…', el('input', { type: 'file', multiple: true, hidden: true, onchange: async (e) => {
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
      } }, '🌱 Seed…'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'Add a link to a glycerol stock, primer, chemical, antibody or plant material in Lab Stocks', onclick: async () => {
        let s;
        try { s = await pickStock(); } catch (err) { toast(err.message, 'error'); return; }
        if (!s) return;
        const html = `<a data-stock="${s.code}">${s.label.replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</a>`;
        const last = note.content[note.content.length - 1];
        if (last && last.type === 'text') {
          last.html = `${last.html || ''}${/<\/p>\s*$/.test(last.html || '') ? `<p>${html}</p>` : ` ${html}`}`;
          Blocks.renderList(note.content, blocks, ctx);
          this.changed();
        } else add({ id: newId(), type: 'text', html: `<p>${html}</p>` });
      } }, '🧫 Stock…'),
      el('button', { class: 'btn btn-secondary btn-sm', title: 'Add a link to a plasmid, which opens it in the Plasmid Editor', onclick: async () => {
        const p = await pickPlasmid();
        if (!p) return;
        const link = `<a data-plasmid="${p.id}">${p.name.replace(/[<>&"]/g, (ch) => `&#${ch.charCodeAt(0)};`)}</a>`;
        const last = note.content[note.content.length - 1];
        if (last && last.type === 'text') {
          last.html = `${last.html || ''}${/<\/p>\s*$/.test(last.html || '') ? `<p>${link}</p>` : ` ${link}`}`;
          Blocks.renderList(note.content, blocks, ctx);
          this.changed();
        } else add({ id: newId(), type: 'text', html: `<p>${link}</p>` });
      } }, '🔗 Plasmid…'));
  },

  /** A photo clicked in text: offer to mark it up, or to open it. */
  photoMenu(img) {
    document.getElementById('photoMenu')?.remove();
    const r = img.getBoundingClientRect();
    const id = img.dataset.attachment;
    const menu = el('div', { class: 'photo-menu', id: 'photoMenu',
      style: `top:${r.top + window.scrollY + 8}px;left:${r.left + window.scrollX + 8}px` },
    el('button', { class: 'btn btn-primary btn-sm', title: 'Draw and write on it (the photo is kept as it is)',
      onclick: () => { menu.remove(); this.markUp(id); } }, '✏️ Mark up'),
    el('button', { class: 'btn btn-secondary btn-sm', onclick: () => { menu.remove(); window.open(attachmentUrl(id), '_blank', 'noopener'); } }, '↗ Open'));
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
        el('button', { class: 'btn btn-primary', onclick: () => { close(); upload(); } }, '📷 Upload a new photo')),
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
      el('div', { class: 'tree-head' }, `📎 Attachments (${list.length})`),
      el('ul', { class: 'attachment-list' }, list.map((a) => el('li', { class: 'attachment' },
        a.image
          ? el('img', { class: 'attachment-thumb', src: attachmentUrl(a.id), alt: '', loading: 'lazy',
            onclick: () => window.open(attachmentUrl(a.id), '_blank', 'noopener') })
          : el('span', { class: 'attachment-icon', title: a.kind }, FILE_ICONS[a.kind] || '📎'),
        el('div', { class: 'attachment-info' },
          el('a', { href: attachmentUrl(a.id), target: '_blank', rel: 'noopener', text: a.filename,
            title: a.image || a.preview ? 'Open it in a new tab' : 'Download, to open in its program' }),
          el('div', { class: 'hint' }, `${sizeLabel(a.size)} · ${a.created_by || '—'} · ${localTime(a.created_at)}`)),
        el('span', { class: 'attachment-actions' },
          el('a', { class: 'btn btn-secondary btn-sm', href: attachmentUrl(a.id, true), title: 'Download' }, '⤓'),
          note.can_edit && a.image ? el('button', { class: 'btn btn-secondary btn-sm', title: 'Draw and write on it (the photo is kept as it is)',
            onclick: () => this.markUp(a.id) }, '✏️') : null,
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
      const text = a.type === 'label' ? `#${a.name}${a.value ? `=${a.value}` : ''}` : `~${a.name}=`;
      bar.append(el('span', { class: `attr attr-${a.type}` }, text,
        a.type === 'relation' ? el('a', { href: `#note=${a.value}`, onclick: (e) => { e.preventDefault(); this.open(a.value); } },
          a.target_title || 'a deleted note') : null,
        note.can_edit && !['dateNote', 'monthNote', 'yearNote', 'notebookRoot', 'protocolLibrary', 'seed'].includes(a.name)
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
          others(b).length ? el('div', { class: 'hint' }, b.role === 'tagged' ? `Booked by ${b.booked_by}${b.people.length > 1 ? `, with ${others(b).filter((p) => p !== b.booked_by).join(', ')}` : ''}`
            : `With ${others(b).join(', ')}`) : null,
          notes));
    };
    const panel = el('details', { class: 'bookings-panel', open: !store.get('hideBookings', false),
      ontoggle: (e) => store.set('hideBookings', !e.target.open) },
    el('summary', {}, `📅 Bookings${data.items.length ? ` (${data.items.length})` : ''}`,
      data.items.length && !data.live ? el('span', { class: 'hint' }, ' · as booked; kept with the day') : null),
    data.items.length ? el('ul', { class: 'booking-list' }, data.items.map(row)) : el('p', { class: 'hint' }, 'Nothing booked today.'),
    data.upcoming.length ? el('div', { class: 'booking-upcoming' }, el('span', { class: 'hint' }, 'Coming up: '),
      data.upcoming.map((b, i) => [i ? ' · ' : '', el('a', { href: open(b), target: '_blank', rel: 'noopener' },
        `${dayOf(b.start)} ${time(b.start)} ${b.resource.name}`)])) : null);
    return panel;
  },

  linksPanel(note) {
    const parts = [];
    if (note.placements.length + (note.other_places || 0) > 1) {
      parts.push(el('div', {}, el('b', {}, 'In: '), note.placements.map((p, i) => [i ? ', ' : '',
        el('a', { href: `#note=${p.parent_id}`, onclick: (e) => { e.preventDefault(); this.open(p.parent_id); } },
          p.parent_owner && p.parent_owner !== note.owner ? `${p.parent_title} (${p.parent_owner}'s notebook)` : p.parent_title)]),
      note.other_places ? el('span', { class: 'hint' },
        `${note.placements.length ? ', and ' : ''}${note.other_places} place${note.other_places > 1 ? 's' : ''} in someone else's notebook`) : null));
    }
    if (note.backlinks.length) {
      parts.push(el('div', {}, el('b', {}, note.type === 'protocol' ? 'Used on: ' : 'Linked from: '),
        note.backlinks.map((b, i) => [i ? ', ' : '', el('a', { href: `#note=${b.id}`,
          onclick: (e) => { e.preventDefault(); this.open(b.id); } }, b.owner && b.owner !== NB.person.username ? `${b.title} (${b.owner})` : b.title)])));
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
        note.can_delete && !['day', 'month', 'year'].includes(note.type) ? el('button', { class: 'menu-item danger', onclick: () => {
          close();
          modal({
            title: `Delete “${note.title}”?`,
            build: (b) => b.append(el('p', {}, 'It and the pages under it go to 🗑 Deleted, at the bottom of the left-hand side, ',
              'where you (or an administrator) can bring them back.')),
            buttons: [{ label: 'Cancel', kind: 'secondary' }, {
              label: 'Delete', kind: 'danger',
              onClick: async () => {
                await api('DELETE', `/notes/${note.id}`);
                const parent = note.path[note.path.length - 2];
                this.note = null;
                await this.reloadTrees();
                if (parent && !['notebook', 'library'].includes(parent.type)) this.open(parent.id);
                else this.showEmpty();
                toast('Deleted: it can be brought back from 🗑 Deleted', 'success', 5000);
              },
            }],
          });
        } }, '🗑 Delete') : null)),
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
      describe: (n) => [`${ICONS[n.type] || '📄'} `, el('b', { text: n.title }), n.where ? el('span', { class: 'hint' }, ` · ${n.where}`) : null],
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

  /** Today's page, with this protocol put at its end. */
  async useToday(protocolId) {
    await this.flush();
    try {
      const { section } = await api('GET', `/protocols/${protocolId}/snapshot`);
      const { note: day } = await api('POST', '/days', {});
      const { note: saved } = await api('PUT', `/notes/${day.id}`, {
        content: [...day.content.filter((b) => b.type !== 'text' || (b.html || '').trim()), section],
        base_version: day.version,
      });
      for (const step of saved.path.slice(0, -1)) Tree.expanded.add(step.id);
      Tree.remember();
      await this.reloadTrees();
      this.show(saved);
      document.querySelector('.blocks')?.lastElementChild?.scrollIntoView({ block: 'start', behavior: 'smooth' });
      toast(`Added to ${saved.title}`, 'success');
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
        folder ? el('h3', { class: 'library-folder' }, `📁 ${folder}`) : null,
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
            el('div', { class: 'hint' }, `by ${p.created_by || 'the MoClo Library Tool'}`,
              p.updated_by && p.updated_by !== p.created_by ? ` · changed by ${p.updated_by}` : '', ` · ${localTime(p.updated_at).slice(0, 10)}`,
              p.shared && p.lab ? el('span', { class: 'badge badge-shared', title: 'Shared with your lab by another lab' }, ` shared by ${p.lab}`) : null,
              !p.shared && p.shares ? el('span', { class: 'badge badge-shared', title: 'Shared with other labs' }, ` shared with ${p.shares} lab${p.shares > 1 ? 's' : ''}`) : null,
              !p.lab && !p.shared ? el('span', { class: 'hint' }, ' · every lab') : null)),
          el('td', { class: 'hint nowrap uses-cell' }, p.uses ? `used ${p.uses}×` : 'not used yet'),
          el('td', { class: 'nowrap use-cell' }, el('button', { class: 'btn btn-secondary btn-sm', title: "Put it into today's page",
            onclick: () => this.useToday(p.id) }, '＋ Use today'))))))))
        : el('p', { class: 'hint' }, query.value || onlyFav.checked ? 'No protocols match.' : 'No protocols yet: add the first.'));
    };
    let timer;
    query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(draw, 250); });
    onlyFav.addEventListener('change', draw);
    put(box,
      el('div', { class: 'library-head' },
        el('h1', {}, '🧪 Protocol library'),
        el('span', { class: 'note-actions' },
          el('button', { class: 'btn btn-primary btn-sm', onclick: () => this.newNote('library', this.me.library, 'protocol') }, '＋ New protocol'),
          el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.newNote('library', this.me.library, 'folder') }, '＋ New folder'),
          el('button', { class: 'btn btn-secondary btn-sm', title: 'Every protocol you can see, as a PDF or a Word document',
            onclick: () => Exports.open({ id: this.me.library, title: 'Protocol library', kind: 'notebook' }) }, '⤓ Export'))),
      el('p', { class: 'hint' }, 'Your lab\'s protocols, the ones other labs share with it, and those supplied with the notebook. ',
        'Anyone can add a protocol; its author, their lab lead and administrators can change it, and share it with other labs (👥 Share, on the protocol). ',
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
        el('div', { class: 'library-head' }, el('h1', {}, '🗑 Deleted')),
        el('p', { class: 'hint' }, NB.person.role === 'admin'
          ? 'Everything deleted from any notebook or the protocol library. Restoring brings back what was deleted with it, to where it was.'
          : 'What you deleted from your notebook, and protocols you may change. Restoring brings back what was deleted with it, to where it was.'),
        deleted.length ? el('table', { class: 'library-table deleted-table' }, el('tbody', {}, deleted.map((d) => el('tr', {},
          el('td', {}, el('div', { class: 'library-title' }, `${ICONS[d.type] || '📄'} ${d.title}`),
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
        if (b.type === 'steps') for (const i of b.items) if (i.by) stamps.set(`${b.id}|${i.id}`, i);
        if (b.type === 'table') {
          for (const row of b.rows) row.cells.forEach((cell, c) => { if (cell && cell.by) stamps.set(`${b.id}|${row.id}|${c}`, cell); });
        }
      }
    };
    walk(content);
    const apply = (blocks) => {
      for (const b of blocks || []) {
        if (b.type === 'section') apply(b.blocks);
        if (b.type === 'steps') {
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
        label.textContent = key.split('|').length === 2 ? `✓ ${s.by} · ${localTime(s.at)}` : `${s.by} · ${localTime(s.at)}`;
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

  showFormatBar(area, sync) {
    let bar = document.getElementById('formatBar');
    if (!bar) {
      bar = el('div', { class: 'format-bar', id: 'formatBar' });
      document.body.append(bar);
    }
    const cmd = (command, value) => (e) => { e.preventDefault(); document.execCommand(command, false, value); sync(); };
    put(bar, 
      el('button', { title: 'Bold (Ctrl+B)', onmousedown: cmd('bold') }, el('b', {}, 'B')),
      el('button', { title: 'Italic (Ctrl+I)', onmousedown: cmd('italic') }, el('i', {}, 'I')),
      el('button', { title: 'Underline (Ctrl+U)', onmousedown: cmd('underline') }, el('u', {}, 'U')),
      el('button', { title: 'Heading', onmousedown: cmd('formatBlock', 'h3') }, 'H'),
      el('button', { title: 'Paragraph', onmousedown: cmd('formatBlock', 'p') }, '¶'),
      el('button', { title: 'Bulleted list', onmousedown: cmd('insertUnorderedList') }, '•'),
      el('button', { title: 'Numbered list', onmousedown: cmd('insertOrderedList') }, '1.'),
      el('button', { title: 'Link a plasmid or note (or type @)', onmousedown: (e) => {
        e.preventDefault();
        const sel = window.getSelection();
        if (!sel.rangeCount || !area.contains(sel.anchorNode)) return;
        Blocks.linkAt(area, sel.getRangeAt(0), sync);
      } }, '@'));
    const place = () => {
      const r = area.getBoundingClientRect();
      bar.style.top = `${Math.max(56, r.top + window.scrollY - 38)}px`;
      bar.style.left = `${r.left + window.scrollX}px`;
    };
    place();
    bar.hidden = false;
    const hide = () => { setTimeout(() => { if (!bar.matches(':hover') && document.activeElement !== area) bar.hidden = true; }, 150); };
    area.addEventListener('blur', hide, { once: true });
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
