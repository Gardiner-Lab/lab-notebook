// A meeting's page saved by two people at once (app/static/js/merge.js). Run with: node tests/js/merge.test.js
const assert = require('assert');
const Merge = require('../../app/static/js/merge.js');

const copy = (x) => JSON.parse(JSON.stringify(x));
const point = (id, blocks) => ({ id, type: 'section', title: 'Updates', source: { kind: 'agenda' }, blocks });
const box = (id, by, html) => ({ id, type: 'text', html, by });
const base = [
  { id: 'h', type: 'text', html: '<h3>Agenda</h3>' },
  point('p1', []),
  { id: 'att', type: 'steps', title: 'Attendance', items: [{ id: 'i1', html: 'ana' }, { id: 'i2', html: 'ben' }] },
  { id: 'n', type: 'text', html: '<h3>Notes</h3>' },
  { id: 'act', type: 'tasks', title: 'Action items', items: [] },
];

// Ana and Ben each write their minutes of the point, and each ticks someone present: all of it is kept.
const ana = copy(base);
ana[1].blocks.push(box('p1.ana', 'ana', '<p>seeds sown</p>'));
ana[2].items[0].done = true;
const ben = copy(base);
ben[1].blocks.push(box('p1.ben', 'ben', '<p>primers ordered</p>'));
ben[2].items[1].done = true;
ben[4].items.push({ id: 't1', html: 'Order oligos' });
const merged = Merge.content(base, ana, ben);              // ana's page, ben saved first
assert.deepStrictEqual(merged[1].blocks.map((b) => [b.id, b.html]),
  [['p1.ana', '<p>seeds sown</p>'], ['p1.ben', '<p>primers ordered</p>']]);
assert.deepStrictEqual(merged[2].items.map((i) => !!i.done), [true, true]);
assert.deepStrictEqual(merged[4].items.map((i) => i.html), ['Order oligos']);
assert.strictEqual(merged.length, 5);

// What only one side changed: theirs where only they changed it, mine where only I did.
const mine = copy(base);
mine[3].html = '<h3>Notes</h3><p>mine</p>';
const theirs = copy(base);
theirs[0].html = '<h3>Agenda</h3><p>theirs</p>';
const both = Merge.content(base, mine, theirs);
assert.strictEqual(both[0].html, '<h3>Agenda</h3><p>theirs</p>');
assert.strictEqual(both[3].html, '<h3>Notes</h3><p>mine</p>');

// The same shared box changed on both sides: they cannot be put together.
const a2 = copy(base); a2[3].html = '<p>one</p>';
const b2 = copy(base); b2[3].html = '<p>two</p>';
assert.strictEqual(Merge.content(base, a2, b2), null);
// Deleted on one side and changed on the other: neither.
const a3 = copy(base); a3.splice(3, 1);
assert.strictEqual(Merge.content(base, a3, b2), null);
// Deleted on one side, untouched on the other: gone.
assert.deepStrictEqual(Merge.content(base, a3, copy(base)).map((b) => b.id), ['h', 'p1', 'att', 'act']);

// A point added here goes after the block it followed here; one added there stays where it was.
const a4 = copy(base); a4.splice(2, 0, point('p2', []));
const b4 = copy(base); b4.splice(1, 0, point('p0', []));
assert.deepStrictEqual(Merge.content(base, a4, b4).map((b) => b.id), ['h', 'p0', 'p1', 'p2', 'att', 'n', 'act']);

// What is only on the page (a table being designed) does not count as a change.
const a5 = copy(base); a5[3]._design = true;
const b5 = copy(base); b5[3].html = '<p>theirs</p>';
assert.strictEqual(Merge.content(base, a5, b5)[3].html, '<p>theirs</p>');

console.log('merge: all passed');
