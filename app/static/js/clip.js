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
      if (text.includes('\t')) return this.tsv(text);
      const html = data.getData('text/html') || '';
      return /<table/i.test(html) ? this.html(html) : null;
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
