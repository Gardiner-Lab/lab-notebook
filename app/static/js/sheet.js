/**
 * The arithmetic of active tables.
 *
 * A table has columns, each of a kind:
 *   text      words, as typed
 *   number    a number, as typed
 *   scaled    an amount for the table's base (one reaction), shown multiplied
 *             by the scale (the number of reactions set above the table)
 *   formula   worked out from other cells by the column's formula
 *   fill      left blank in a protocol, filled in when it is used
 *   check     ticked off (who and when is recorded by the server)
 *
 * Any cell starting with "=" is a formula of its own, over the cells of the
 * table: A1 is column A of the first row, A1:A5 a range, and a column formula
 * may name a column alone (=B*C) to mean that column in the same row. N is the
 * scale's value (the number of reactions); a scaled column multiplies by N
 * divided by the scale's base itself.
 * Functions: SUM, MIN, MAX, AVERAGE (AVG), ROUND(x, digits), ABS, IF(c, a, b).
 *
 * A formula waiting on a cell nobody has filled in yet shows nothing, rather
 * than a number worked out from a blank. A blank number or fill-in cell in a
 * row that has something else in it counts as not filled in yet, so a SUM over
 * it waits too (the water to make up 20 µL waits for every DNA volume); rows
 * left empty altogether are ignored.
 *
 * Works in the browser (window.Sheet) and in Node (require), for the tests.
 */
(function (root) {
  const PENDING = { pending: true };
  class SheetError extends Error {}

  const colIndex = (letters) => {
    let n = 0;
    for (const ch of letters.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  };
  const colName = (index) => {
    let s = '';
    for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    return s;
  };

  function tokenize(src) {
    const tokens = [];
    const re = /(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z]+)(\d+)?(?::([A-Za-z]+)(\d+))?|(<=|>=|<>|[-+*/^(),;<>=])/y;
    let pos = 0;
    while (pos < src.length) {
      if (/\s/.test(src[pos])) { pos += 1; continue; }
      re.lastIndex = pos;
      const m = re.exec(src);
      if (!m) throw new SheetError(`cannot read "${src.slice(pos).trim()}"`);
      pos = re.lastIndex;
      if (m[1] !== undefined) tokens.push({ t: 'num', v: parseFloat(m[1]) });
      else if (m[2] !== undefined) {
        if (m[4] !== undefined) tokens.push({ t: 'range', c1: colIndex(m[2]), r1: +m[3] - 1, c2: colIndex(m[4]), r2: +m[5] - 1 });
        else if (m[3] !== undefined) tokens.push({ t: 'ref', c: colIndex(m[2]), r: +m[3] - 1 });
        else tokens.push({ t: 'name', v: m[2].toUpperCase() });
      } else tokens.push({ t: 'op', v: m[6] === ';' ? ',' : m[6] });
    }
    return tokens;
  }

  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  function arith(a, b, f) {
    if (a === PENDING || b === PENDING || a === null || b === null) return PENDING;
    if (!isNum(a) || !isNum(b)) throw new SheetError('not a number');
    return f(a, b);
  }

  const FUNCTIONS = {
    SUM: (args) => { let s = 0; for (const v of args.flat()) { if (v === PENDING) return PENDING; if (isNum(v)) s += v; } return s; },
    MIN: (args) => { const xs = []; for (const v of args.flat()) { if (v === PENDING) return PENDING; if (isNum(v)) xs.push(v); } return xs.length ? Math.min(...xs) : PENDING; },
    MAX: (args) => { const xs = []; for (const v of args.flat()) { if (v === PENDING) return PENDING; if (isNum(v)) xs.push(v); } return xs.length ? Math.max(...xs) : PENDING; },
    AVERAGE: (args) => { const xs = []; for (const v of args.flat()) { if (v === PENDING) return PENDING; if (isNum(v)) xs.push(v); } return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : PENDING; },
    ROUND: ([x, d]) => { if (x === PENDING || x === null) return PENDING; const k = 10 ** (isNum(d) ? d : 0); return Math.round(x * k) / k; },
    ABS: ([x]) => (x === PENDING || x === null ? PENDING : Math.abs(x)),
    IF: ([c, a, b]) => (c === PENDING ? PENDING : (c ? a : b ?? '')),
  };
  FUNCTIONS.AVG = FUNCTIONS.AVERAGE;

  /** Evaluate one formula (without its "="), reading cells through `get(row, col)`. */
  function evaluate(src, ctx) {
    const tokens = tokenize(src);
    let i = 0;
    const peek = () => tokens[i];
    const take = (v) => { if (tokens[i] && tokens[i].v === v) { i += 1; return true; } return false; };

    function primary() {
      const tok = tokens[i++];
      if (!tok) throw new SheetError('formula ends too soon');
      if (tok.t === 'num') return tok.v;
      if (tok.t === 'ref') return ctx.get(tok.r, tok.c);
      if (tok.t === 'range') {
        const out = [];
        for (let r = Math.min(tok.r1, tok.r2); r <= Math.max(tok.r1, tok.r2); r++) {
          for (let c = Math.min(tok.c1, tok.c2); c <= Math.max(tok.c1, tok.c2); c++) out.push(ctx.get(r, c));
        }
        return out;
      }
      if (tok.t === 'name') {
        if (take('(')) {
          const fn = FUNCTIONS[tok.v];
          if (!fn) throw new SheetError(`no function ${tok.v}`);
          const args = [];
          if (!take(')')) {
            do { args.push(comparison()); } while (take(','));
            if (!take(')')) throw new SheetError('missing )');
          }
          return fn(args);
        }
        if (tok.v === 'N') return ctx.scale;
        // A column alone: that column, in the row being worked out.
        if (ctx.row === undefined) throw new SheetError(`${tok.v} needs a row number`);
        return ctx.get(ctx.row, colIndex(tok.v));
      }
      if (tok.t === 'op' && tok.v === '(') {
        const v = comparison();
        if (!take(')')) throw new SheetError('missing )');
        return v;
      }
      if (tok.t === 'op' && tok.v === '-') return arith(0, unaryOperand(), (a, b) => a - b);
      if (tok.t === 'op' && tok.v === '+') return unaryOperand();
      throw new SheetError(`unexpected ${tok.v}`);
    }
    function unaryOperand() { return power(); }
    function power() {
      let v = primary();
      while (peek() && peek().v === '^') { i++; const r = primary(); v = arith(v, r, (a, b) => a ** b); }
      return v;
    }
    function term() {
      let v = power();
      while (peek() && (peek().v === '*' || peek().v === '/')) {
        const op = tokens[i++].v;
        const r = power();
        v = arith(v, r, (a, b) => {
          if (op === '/' && b === 0) throw new SheetError('#DIV/0');
          return op === '*' ? a * b : a / b;
        });
      }
      return v;
    }
    function sum() {
      let v = term();
      while (peek() && (peek().v === '+' || peek().v === '-')) {
        const op = tokens[i++].v;
        const r = term();
        v = arith(v, r, (a, b) => (op === '+' ? a + b : a - b));
      }
      return v;
    }
    function comparison() {
      let v = sum();
      while (peek() && ['<', '>', '<=', '>=', '=', '<>'].includes(peek().v)) {
        const op = tokens[i++].v;
        const r = sum();
        v = arith(v, r, (a, b) => ({ '<': a < b, '>': a > b, '<=': a <= b, '>=': a >= b, '=': a === b, '<>': a !== b }[op] ? 1 : 0));
      }
      return v;
    }
    const value = comparison();
    if (i < tokens.length) throw new SheetError(`unexpected ${tokens[i].v ?? 'text'}`);
    return value;
  }

  const literal = (raw) => {
    const s = String(raw ?? '').trim();
    if (s === '') return null;
    const n = Number(s.replace(',', '.'));
    return Number.isFinite(n) && /^[-+]?(\d|\.\d)/.test(s) ? n : s;
  };

  /**
   * Work out every cell of a table. Returns rows of {value, display, error,
   * formula}: value a number, text, null (empty) or PENDING; display the text
   * to show.
   */
  function compute(table) {
    const columns = table.columns || [];
    const rows = table.rows || [];
    const scale = table.scale ? Number(table.scale.value) || 0 : 1;
    const base = table.scale ? Number(table.scale.base) || 1 : 1;
    const factor = scale / base;
    const memo = new Map();
    const busy = new Set();
    const NUMERIC = new Set(['number', 'scaled', 'fill']);
    const rowUsed = rows.map((row) => columns.some((col, c) => col.kind !== 'check'
      && String((row.cells || [])[c] ?? '').trim() !== ''));

    function cellFormula(r, c) {
      const col = columns[c] || {};
      const raw = (rows[r]?.cells || [])[c];
      if (typeof raw === 'string' && raw.trim().startsWith('=')) return raw.trim().slice(1);
      if ((raw === '' || raw === null || raw === undefined) && col.kind === 'formula' && col.formula) {
        return String(col.formula).trim().replace(/^=/, '');
      }
      return null;
    }

    function get(r, c) {
      if (r < 0 || c < 0 || r >= rows.length || c >= columns.length) throw new SheetError('#REF');
      const key = `${r}:${c}`;
      if (memo.has(key)) {
        const m = memo.get(key);
        if (m.error) throw new SheetError(m.error);
        return m.value;
      }
      if (busy.has(key)) throw new SheetError('#CYCLE');
      busy.add(key);
      let result;
      try {
        const col = columns[c] || {};
        const raw = (rows[r]?.cells || [])[c];
        const formula = cellFormula(r, c);
        if (col.kind === 'check') result = { value: raw ? 1 : 0 };
        else if (formula !== null) {
          let v = evaluate(formula, { get, row: r, scale });
          if (Array.isArray(v)) throw new SheetError('a range needs a function, e.g. SUM');
          if (col.kind === 'scaled' && isNum(v)) v *= factor;
          result = { value: v, formula: true };
        } else {
          let v = literal(raw);
          if (col.kind === 'scaled' && isNum(v)) v *= factor;
          // Still to be filled in: whatever adds it up waits for it.
          if (v === null && NUMERIC.has(col.kind) && rowUsed[r]) v = PENDING;
          result = { value: v };
        }
      } catch (err) {
        result = { value: null, error: err instanceof SheetError ? err.message : String(err) };
      }
      busy.delete(key);
      memo.set(key, result);
      if (result.error) throw new SheetError(result.error);
      return result.value;
    }

    return rows.map((row, r) => columns.map((col, c) => {
      try { get(r, c); } catch (e) { /* recorded in memo */ }
      const m = memo.get(`${r}:${c}`) || { value: null };
      return { ...m, display: m.error ? `#${m.error.replace(/^#/, '')}` : show(m.value) };
    }));
  }

  /** A number as people write it: no float noise, a sensible number of decimals. */
  function show(value) {
    if (value === null || value === undefined || value === PENDING) return '';
    if (typeof value !== 'number') return String(value);
    if (!Number.isFinite(value)) return '#NUM';
    const abs = Math.abs(value);
    if (abs !== 0 && abs < 0.1) return String(Number(value.toPrecision(2)));
    return String(Math.round(value * 100) / 100);
  }

  const Sheet = { compute, evaluate, show, colName, colIndex, PENDING };
  if (typeof module !== 'undefined' && module.exports) module.exports = Sheet;
  else root.Sheet = Sheet;
}(typeof window !== 'undefined' ? window : globalThis));
