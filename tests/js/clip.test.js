// Tables copied from a spreadsheet (app/static/js/clip.js). Run with: node tests/js/clip.test.js
const assert = require('assert');
const Clip = require('../../app/static/js/clip.js');

const data = (plain, html = '') => ({ getData: (type) => (type === 'text/plain' ? plain : type === 'text/html' ? html : '') });

// Excel copies rows of tab-separated cells, a line break after the last; a cell with a line break,
// a tab or a quote in it is put in quotes.
assert.deepStrictEqual(Clip.grid(data('Sample\tOD600\r\nA\t0,61\r\n"B ""2""\nrepeat"\t0.58\r\n')),
  [['Sample', 'OD600'], ['A', '0,61'], ['B "2"\nrepeat', '0.58']]);
// Short rows are filled out, and empty rows at the end dropped.
assert.deepStrictEqual(Clip.tsv('a\tb\tc\nd\n\t\n'), [['a', 'b', 'c'], ['d', '', '']]);
// Plain text without tabs is not a table, but lines go down a column of one.
assert.strictEqual(Clip.grid(data('just a sentence\nand another')), null);
assert.deepStrictEqual(Clip.gridOrLines(data('12\n15\n')), [['12'], ['15']]);
assert.strictEqual(Clip.gridOrLines(data('one value')), null);

// A first row of names over numbers names the columns; columns of numbers only (decimal commas too)
// are number columns, so formulas work on them.
const t = Clip.table([['Sample', 'OD600', 'Note'], ['A', '0,61', 'ok'], ['B', '0.58', '']]);
assert.deepStrictEqual(t.columns.map((c) => [c.name, c.kind]), [['Sample', 'text'], ['OD600', 'number'], ['Note', 'text']]);
assert.deepStrictEqual(t.rows.map((r) => r.cells), [['A', '0,61', 'ok'], ['B', '0.58', '']]);
assert.strictEqual(t.type, 'table');
// Without such a row, every row is kept and the columns are lettered.
const plain = Clip.table([['1', '2'], ['3', '4']]);
assert.deepStrictEqual(plain.columns.map((c) => [c.name, c.kind]), [['Column A', 'number'], ['Column B', 'number']]);
assert.strictEqual(plain.rows.length, 2);

// Ticks pasted into a tick-off column.
assert.ok(['TRUE', 'yes', 'x', '✓'].every(Clip.ticked) && !['', 'no', 'FALSE'].some(Clip.ticked));

// No more than a table holds (the server keeps 500 rows of 40 columns), marked as cut.
const big = Clip.tsv(Array.from({ length: 600 }, () => Array(45).fill('1').join('\t')).join('\n'));
assert.ok(big.cut && big.length === 500 && big[0].length === 40);
assert.ok(!Clip.tsv('a\tb').cut);

// A bulleted or numbered list copied from Word or a web page has a tab after each bullet: a list,
// not a table of two columns.
const wordBullets = '•\tExtract DNA\r\no\tGrind leaves\r\no\tAdd buffer\r\n•\tRun PCR\r\n';
assert.strictEqual(Clip.grid(data(wordBullets)), null, 'bullets are not a table');
assert.deepStrictEqual(Clip.lists(wordBullets), [{ type: 'list', ordered: false, items: [
  { level: 0, ordered: false, text: 'Extract DNA' }, { level: 1, ordered: false, text: 'Grind leaves' },
  { level: 1, ordered: false, text: 'Add buffer' }, { level: 0, ordered: false, text: 'Run PCR' }] }]);
const numbered = '1.\tSow seeds\n2.\tWater\n3.\tWait two weeks\n';
assert.strictEqual(Clip.grid(data(numbered)), null, 'a numbered list is not a table');
assert.strictEqual(Clip.lists(numbered)[0].ordered, true);
assert.deepStrictEqual(Clip.lists(numbered)[0].items.map((i) => i.text), ['Sow seeds', 'Water', 'Wait two weeks']);
// Text around the list stays text.
const mixed = 'Plan for Monday:\n•\tbuy tips\n•\tbook the confocal\nThanks';
assert.deepStrictEqual(Clip.lists(mixed).map((b) => b.type), ['text', 'list', 'text']);
assert.strictEqual(Clip.grid(data(mixed)), null);
// Dashes and numbers with a space, as typed in an email.
assert.strictEqual(Clip.lists('- one\n- two').length, 1);
assert.strictEqual(Clip.lists('1. one\n2. two')[0].ordered, true);
// Indentation kept in the copy gives the level.
assert.deepStrictEqual(Clip.lists('- top\n\t- under').length && Clip.lists('- top\n\t- under')[0].items.map((i) => i.level), [0, 1]);
// Still tables: real cells, a table in the copied HTML, a line of cells beside a bullet line.
assert.deepStrictEqual(Clip.grid(data('Sample\tOD600\nA\t0.61')), [['Sample', 'OD600'], ['A', '0.61']]);
assert.ok(Clip.grid(data('•\ta\n•\tb', '<table><tr><td>•</td><td>a</td></tr><tr><td>•</td><td>b</td></tr></table>')),
  'a copy that says it is a table is one');
assert.ok(Clip.grid(data('•\ta\nx\ty')), 'a row of cells among bullets makes it a table');
// Not lists: a sentence, one dashed line, "o" without a tab.
assert.strictEqual(Clip.lists('just a sentence'), null);
assert.strictEqual(Clip.lists('- only one'), null);
assert.strictEqual(Clip.lists('o well\no dear'), null);

console.log('clip: all passed');
