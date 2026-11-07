// Tables copied from a spreadsheet (Excel, Google Sheets, LibreOffice), Word or a web page, pasted into
// the notebook: the copied cells as rows of text, and a table block made from them. The page uses it as
// window.Clip; Node's tests require it.
(function (root) {
  const Sheet = typeof module !== 'undefined' && module.exports ? require('./sheet.js') : root.Sheet;
  const newId = () => Math.random().toString(16).slice(2, 14);

  const Clip = {
    // As many as the server keeps of a table (app/content.py).
    MAX_ROWS: 500,
    MAX_COLUMNS: 40,

    /** The copied table, or null when what was copied is not one. */
    grid(data) {
      const text = data.getData('text/plain') || '';
      const html = data.getData('text/html') || '';
      // A bulleted or numbered list copied from Word or a web page puts a tab after each bullet: that
      // is a list, not a table of two columns, unless the copy says itself that it is a table.
      if (text.includes('\t') && !/<table/i.test(html) && this.lists(text)) return null;
      if (text.includes('\t')) return this.tsv(text);
      return /<table/i.test(html) ? this.html(html) : null;
    },

    // A list item's marker at the start of a line: a bullet, or a number or letter with . or ).
    // The marker kinds Word uses for its levels (•, then o, then ▪ or §) give the level when the copied
    // text has lost its indentation.
    BULLETS: { '•': 0, '●': 0, '∙': 0, '·': 0, '-': 0, '–': 0, '—': 0, '*': 0, '‣': 0, '⁃': 0,
               'o': 1, '◦': 1, '○': 1, '▪': 2, '▫': 2, '■': 2, '□': 2, '§': 2 },

    /** One line as a list item, {level, ordered, text}, or null when it is not one. */
    listItem(line) {
      const m = /^([ \t ]*)(\S+?)(\t|[  ]+)(.*)$/.exec(line);
      if (!m) return null;
      const [, indent, marker, gap, text] = m;
      const tabbed = gap.includes('\t');
      let level;
      let ordered = false;
      if (marker in this.BULLETS) {
        // "o" and the rarer bullets count only before a tab: "o well" is a sentence.
        if (!tabbed && !/^[•●∙·\-–—*‣⁃]$/.test(marker)) return null;
        level = this.BULLETS[marker];
      } else if (/^\d{1,3}[.)]$/.test(marker) || /^\(\d{1,3}\)$/.test(marker)) {
        ordered = true; level = 0;
      } else if (tabbed && (/^[a-z][.)]$/i.test(marker) || /^[ivx]{1,5}[.)]$/i.test(marker))) {
        ordered = true; level = /^[ivx]{1,5}[.)]$/.test(marker) && marker.length > 2 ? 2 : 1;
      } else return null;
      if (!text.trim()) return null;
      // Indentation, when the copy kept it, says the level: a tab or four spaces a step.
      const steps = (indent.match(/\t/g) || []).length + Math.floor(indent.replace(/\t/g, '').length / 4);
      return { level: steps || level, ordered, text: text.trim() };
    },

    /**
     * Copied text holding a list, as blocks in order: {type: 'text', text} for ordinary lines and
     * {type: 'list', ordered, items: [{level, text}]} for a run of list items. Null when it holds no
     * list, or when it is a table after all: a line with a tab that is not a list item.
     */
    lists(text) {
      const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
      while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
      const blocks = [];
      let found = 0;
      for (const line of lines) {
        const item = line.trim() ? this.listItem(line) : null;
        if (!item) {
          if (line.includes('\t')) return null;       // a row of cells
          blocks.push({ type: 'text', text: line });
          continue;
        }
        found++;
        const last = blocks[blocks.length - 1];
        if (last && last.type === 'list' && (last.ordered === item.ordered || item.level > 0)) last.items.push(item);
        else blocks.push({ type: 'list', ordered: item.ordered, items: [item] });
      }
      // One "- " line alone is as likely a sentence as a list; a tab after the marker is a list.
      if (!found || (found < 2 && !/\t/.test(text))) return null;
      return blocks;
    },

    /** A table, or else lines of text taken as one column (to paste down a table's column). */
    gridOrLines(data) {
      const text = data.getData('text/plain') || '';
      return this.grid(data) || (text.trim().includes('\n') ? this.tsv(text) : null);
    },

    /** Tab-separated rows, as spreadsheets copy them: a cell holding a tab, a line break or a quote is in quotes. */
    tsv(text) {
      text = text.replace(/\r\n?/g, '\n');
      const rows = [];
      let row = [];
      let cell = '';
      let quoted = false;
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (quoted) {
          if (ch !== '"') cell += ch;
          else if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
        } else if (ch === '"' && cell === '') quoted = true;
        else if (ch === '\t') { row.push(cell); cell = ''; } else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; } else cell += ch;
      }
      if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
      return this.square(rows);
    },

    /** The first table in copied HTML, a cell spanning columns taking them all (its text in the first). */
    html(html) {
      const table = new DOMParser().parseFromString(html, 'text/html').querySelector('table');
      if (!table) return null;
      const rows = [...table.rows].map((tr) => [...tr.cells].flatMap((td) => [
        td.innerText ?? td.textContent, ...Array(Math.max(0, (td.colSpan || 1) - 1)).fill('')]));
      return this.square(rows.map((r) => r.map((v) => (v || '').replace(/\s+/g, ' ').trim())));
    },

    /**
     * Rows all as wide as the widest, without the empty lines at the end; no more than a table holds,
     * marked cut when there was more.
     */
    square(rows) {
      while (rows.length && rows[rows.length - 1].every((v) => v === '')) rows.pop();
      const width = Math.max(0, ...rows.map((r) => r.length));
      if (!rows.length || !width) return null;
      const grid = rows.slice(0, this.MAX_ROWS).map((r) => [...r, ...Array(width - r.length).fill('')].slice(0, this.MAX_COLUMNS));
      if (rows.length > this.MAX_ROWS || width > this.MAX_COLUMNS) grid.cut = true;
      return grid;
    },

    number: (v) => v.trim() !== '' && Number.isFinite(Number(v.trim().replace(',', '.'))),
    ticked: (v) => /^(true|yes|ja|waar|x|✓|✔|1|done)$/i.test(v.trim()),

    /**
     * A table block from copied rows. A first row of names over the rest (none of them a number) names
     * the columns; a column of numbers only is a number column, so formulas can use it.
     */
    table(grid) {
      const named = grid.length > 1 && grid[0].every((v) => v.trim() && !this.number(v));
      const body = named ? grid.slice(1) : grid;
      const columns = grid[0].map((v, c) => ({
        name: named ? v.trim() : `Column ${Sheet.colName(c)}`,
        kind: body.some((row) => this.number(row[c])) && body.every((row) => !row[c].trim() || this.number(row[c])) ? 'number' : 'text',
        unit: '', formula: '',
      }));
      return { id: newId(), type: 'table', title: '', scale: null, columns,
        rows: body.map((row) => ({ id: newId(), cells: row.map((v) => v.trim()) })) };
    },
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = Clip;
  else root.Clip = Clip;
}(typeof window !== 'undefined' ? window : globalThis));
