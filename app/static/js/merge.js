// A page saved by someone else while it was being written on here, put together with what was changed here
// (a three-way merge, against the content as last stored). Used on a meeting's page, written on by several
// people at once (notebook.js App.absorb). The page uses it as window.Merge; Node's tests require it.
(function (root) {
  const CLASH = { clash: true };

  // What is only on the page (a table being designed, _design) is not content.
  const json = (x) => JSON.stringify(x ?? null, (k, v) => (k.startsWith('_') ? undefined : v));
  const same = (a, b) => json(a) === json(b);

  /** One value: changed on one side only takes that side's; changed on both, the same way or a clash. */
  const leaf = (b, m, t) => {
    if (same(m, b)) return t;
    if (same(t, b) || same(m, t)) return m;
    throw CLASH;
  };

  /**
   * A list of things with ids (blocks, steps, tasks), in their order there, with what was added here put
   * after what it followed here. One deleted on one side and changed on the other is a clash.
   */
  const list = (base, mine, them, one) => {
    const B = new Map((base || []).map((x) => [x.id, x]));
    const M = new Map((mine || []).map((x) => [x.id, x]));
    const T = new Set((them || []).map((x) => x.id));
    const out = [];
    for (const t of them || []) {
      const b = B.get(t.id);
      const m = M.get(t.id);
      if (!m) {
        if (b && !same(b, t)) throw CLASH;       // deleted here, changed there
        if (!b) out.push(t);                     // new there
        continue;                                // deleted here
      }
      out.push(b ? one(b, m, t) : m);
    }
    (mine || []).forEach((m, i) => {
      if (T.has(m.id)) return;
      const b = B.get(m.id);
      if (b) {
        if (!same(b, m)) throw CLASH;            // deleted there, changed here
        return;                                  // deleted there
      }
      const before = (mine || []).slice(0, i).reverse().find((x) => out.some((o) => o.id === x.id));
      out.splice(before ? out.findIndex((o) => o.id === before.id) + 1 : 0, 0, m);
    });
    return out;
  };

  /** A block: a section's blocks, and the steps or tasks of a list, are put together one by one. */
  const block = (b, m, t) => {
    if (same(m, b)) return t;
    if (same(t, b) || same(m, t)) return m;
    if (m.type !== t.type || b.type !== t.type) throw CLASH;
    if (t.type === 'section') {
      return { ...t, title: leaf(b.title, m.title, t.title), blocks: list(b.blocks, m.blocks, t.blocks, block) };
    }
    if (t.type === 'steps' || t.type === 'tasks') {
      return { ...t, title: leaf(b.title, m.title, t.title), items: list(b.items, m.items, t.items, leaf) };
    }
    throw CLASH;
  };

  const Merge = {
    /** The content put together, or null when the same thing was changed on both sides. */
    content(base, mine, theirs) {
      try {
        return list(base, mine, theirs, block);
      } catch (err) {
        if (err === CLASH) return null;
        throw err;
      }
    },
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = Merge;
  else root.Merge = Merge;
})(this);
