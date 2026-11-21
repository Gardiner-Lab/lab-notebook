// Active-table arithmetic (app/static/js/sheet.js). Run with: node tests/js/sheet.test.js
const assert = require('assert');
const Sheet = require('../../app/static/js/sheet.js');

const table = (columns, rows, scale = null) => ({
  columns: columns.map((c) => (typeof c === 'string' ? { name: c, kind: c } : c)), rows: rows.map((cells) => ({ cells })), scale,
});
const shown = (t) => Sheet.compute(t).map((row) => row.map((c) => c.display));

// Plain numbers, cell formulas, ranges and functions.
assert.deepStrictEqual(shown(table(['number', 'number'], [['2', '=A1*3'], ['0.5', '=SUM(A1:A2)+ROUND(1.236,2)']])),
  [['2', '6'], ['0.5', '3.74']]);

// A column formula names columns alone, meaning the same row; N is the scale.
const mix = table([{ kind: 'text' }, { kind: 'number' }, { kind: 'formula', formula: '=B*N' }],
  [['Buffer', '2', ''], ['Water', '=20-SUM(B1:B1)', '']], { label: 'Reactions', value: 3, base: 1 });
assert.deepStrictEqual(shown(mix), [['Buffer', '2', '6'], ['Water', '18', '54']]);

// A scaled column multiplies what is typed by the scale.
assert.deepStrictEqual(shown(table(['scaled'], [['1.5']], { value: 4, base: 2 })), [['3']]);

// MoClo: volume from size, fmol and concentration; blank until the concentration is in.
const moclo = table([
  { kind: 'text' }, { kind: 'number' }, { kind: 'number' }, { kind: 'fill' },
  { kind: 'formula', formula: '=B*C*660/1000000' }, { kind: 'formula', formula: '=E/D' }, { kind: 'check' }],
[['vector', '5000', '40', '', '', '', null], ['insert', '3500', '80', '100', '', '', null],
  ['Buffer', '', '', '', '', '2', null], ['Water', '', '', '', '', '=20-SUM(F1:F3)', null]]);
let out = shown(moclo);
assert.strictEqual(out[0][4], '132');          // 40 fmol × 5000 bp × 660 / 10⁶
assert.strictEqual(out[0][5], '');             // no concentration yet: nothing to show
assert.strictEqual(out[1][5], '1.85');         // 184.8 ng ÷ 100 ng/µL
assert.strictEqual(out[3][5], '');             // water waits for every volume
moclo.rows[0].cells[3] = '66';
out = shown(moclo);
assert.strictEqual(out[0][5], '2');
assert.strictEqual(out[3][5], '14.15');        // 20 − (2 + 1.848 + 2)

// A blank amount in a row that is in use is still to come: the total waits for it.
const protocol = table([{ kind: 'text' }, { kind: 'number' }],
  [['Buffer', '2'], ['Vector', ''], ['', ''], ['Water', '=20-SUM(B1:B3)']]);
assert.deepStrictEqual(shown(protocol).map((r) => r[1]), ['2', '', '', '']);
protocol.rows[1].cells[1] = '3';
assert.deepStrictEqual(shown(protocol).map((r) => r[1]), ['2', '3', '', '15']);   // the empty row is ignored

// Errors say what is wrong instead of a number.
assert.deepStrictEqual(shown(table(['number'], [['=A1']])), [['#CYCLE']]);
assert.deepStrictEqual(shown(table(['number', 'number'], [['1', '=A1/0']])), [['1', '#DIV/0']]);
assert.deepStrictEqual(shown(table(['number'], [['=Z9']])), [['#REF']]);
assert.ok(shown(table(['number'], [['=1+']]))[0][0].startsWith('#'));

// Ticks count as 1, so they can be counted.
assert.deepStrictEqual(shown(table(['check', 'number'], [[{ by: 'ana' }, '=SUM(A1:A2)'], [null, '']])), [['1', '1'], ['0', '']]);

// A cell may carry formatting (bold, a colour, a marker), which is not part of what it says: the
// number is still a number, and a formula still works out. Kept the same as app/content.py strip_tags.
assert.strictEqual(Sheet.plain('<b>5</b>'), '5');
assert.strictEqual(Sheet.plain('<span class="tc-red">2,5</span>'), '2,5');
assert.strictEqual(Sheet.plain('a &amp; b'), 'a & b');
assert.deepStrictEqual(shown(table(['number', 'number'], [['<b>2</b>', '<i>3</i>']])), [['2', '3']]);
// A column formula reads a formatted cell as its number too.
assert.deepStrictEqual(shown(table(
  [{ name: 'A', kind: 'number' }, { name: 'B', kind: 'formula', formula: '=A*2' }],
  [['<span class="tc-red">4</span>', '']])), [['4', '8']]);
// A formula someone has made bold is still a formula.
assert.deepStrictEqual(shown(table(['number', 'number'], [['3', '<b>=A1*3</b>']])), [['3', '9']]);
// Formatted numbers add up with the rest.
assert.deepStrictEqual(shown(table(['number', 'number'],
  [['<b>2</b>', ''], ['<mark class="hl-yellow">3</mark>', '=SUM(A1:A2)']]))[1][1], '5');

assert.strictEqual(Sheet.show(0.1 + 0.2), '0.3');
assert.strictEqual(Sheet.show(0.004321), '0.0043');
assert.strictEqual(Sheet.colName(27), 'AB');
console.log('sheet.js: all checks passed');
