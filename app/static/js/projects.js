/*
 * The Meetings tab (a week of meetings on a schedule) and the Projects tab (work packages, tasks and subtasks,
 * what waits for what, and a Gantt chart of it all): app/meetings.py and app/projects.py.
 * Uses notebook.js's helpers (el, put, api, modal, toast, glyph, who, picker, dayMonthYear, isoFromDayMonthYear).
 */

/* --- dates ----------------------------------------------------------------------------------------- */

const DAY_MS = 864e5;
/** A "YYYY-MM-DD" as a whole number of days, for arithmetic. */
const dayNo = (iso) => { const [y, m, d] = String(iso).split('-').map(Number); return Math.round(Date.UTC(y, m - 1, d) / DAY_MS); };
const isoOf = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);
const addDays = (iso, n) => isoOf(dayNo(iso) + n);
const weekdayOf = (iso) => (new Date(dayNo(iso) * DAY_MS).getUTCDay() + 6) % 7;         // Monday 0
const mondayOf = (iso) => addDays(iso, -weekdayOf(iso));
const isoWeek = (iso) => {
  const thursday = dayNo(iso) - weekdayOf(iso) + 3;
  const jan4 = dayNo(`${isoOf(thursday).slice(0, 4)}-01-04`);
  return 1 + Math.round((thursday - (jan4 - ((new Date(jan4 * DAY_MS).getUTCDay() + 6) % 7))) / 7);
};
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const shortDay = (iso) => `${iso.slice(8, 10)}-${iso.slice(5, 7)}`;
const todayIso = () => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`; };
const minutes = (hhmm) => { const [h, m] = String(hhmm).split(':').map(Number); return h * 60 + m; };
/** A colour of its own for each meeting, from its id. */
const MEETING_COLOURS = ['#2e7d5b', '#3867b5', '#b5562e', '#7a4bb0', '#a07a12', '#2b8a99', '#b03a6f', '#5c6b2e'];
const colourFor = (id) => MEETING_COLOURS[[...String(id)].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7) % MEETING_COLOURS.length];

/* --- the Meetings tab ------------------------------------------------------------------------------ */

const MeetingWeek = {
  start: null,

  async show(start) {
    await App.flush();
    App.note = null;
    Tree.markActive('');
    App.setTab('meetings');
    App.view('meetings');
    if (start) this.start = mondayOf(start);
    const box = document.getElementById('meetingsView');
    let data;
    try { data = await api('GET', `/meetings/week${this.start ? `?start=${this.start}` : ''}`); }
    catch (err) { put(box, el('p', { class: 'hint' }, err.message)); return; }
    this.start = data.start;
    const days = [...Array(7).keys()].map((i) => addDays(data.start, i));
    const go = (iso) => { this.start = iso; this.show(); };
    put(box,
      el('div', { class: 'library-head week-head' },
        el('h1', {}, glyph('calendar'), ' Meetings'),
        el('span', { class: 'week-nav' },
          el('button', { class: 'btn btn-secondary btn-sm', title: 'The week before', onclick: () => go(addDays(data.start, -7)) }, '‹'),
          el('button', { class: 'btn btn-secondary btn-sm', onclick: () => go(mondayOf(data.today)) }, 'This week'),
          el('button', { class: 'btn btn-secondary btn-sm', title: 'The week after', onclick: () => go(addDays(data.start, 7)) }, '›'),
          el('b', { class: 'week-label' }, `Week ${isoWeek(data.start)} · ${dayMonthYear(data.start)} – ${dayMonthYear(data.end)}`)),
        el('span', { class: 'week-actions' },
          el('button', { class: 'btn btn-secondary btn-sm', onclick: () => Meetings.list() }, 'All meetings…'),
          el('button', { class: 'btn btn-primary btn-sm', onclick: () => Meetings.edit(null, { day: data.start <= data.today && data.today <= data.end ? data.today : data.start }) },
            '＋ New meeting'))),
      el('p', { class: 'hint' }, 'The meetings you set up or are invited to. Click one to open its page: the agenda, who came, notes and action items. Drag over a day’s time to set up a new one then.'),
      this.grid(days, data));
  },

  grid(days, data) {
    const items = data.items;
    const HOUR = 46;
    const first = Math.min(8, ...items.map((m) => Math.floor(minutes(m.start_time) / 60)));
    const last = Math.max(18, ...items.map((m) => Math.ceil(minutes(m.end_time) / 60)));
    const hours = [...Array(last - first).keys()].map((i) => first + i);
    const column = (iso) => {
      const mine = items.filter((m) => m.date === iso);
      // Side by side when they overlap: each takes the first lane free at its start.
      const lanes = [];
      const placed = mine.map((m) => {
        const s = minutes(m.start_time); const e = minutes(m.end_time);
        let lane = lanes.findIndex((end) => end <= s);
        if (lane < 0) { lane = lanes.length; lanes.push(e); } else lanes[lane] = e;
        return { m, s, e, lane };
      });
      const width = 100 / Math.max(1, lanes.length);
      const col = el('div', { class: `week-day ${iso === data.today ? 'is-today' : ''}`, style: `height:${hours.length * HOUR}px`,
        title: 'Drag over the time (or click it) to set up a meeting then' },
        hours.map((h, i) => el('div', { class: 'week-hour-line', style: `top:${i * HOUR}px` })),
        placed.map(({ m, s, e, lane }) => el('button', {
          class: `week-event ${m.skipped ? 'skipped' : ''}`,
          style: `top:${(s - first * 60) / 60 * HOUR}px;height:${Math.max(22, (e - s) / 60 * HOUR - 2)}px;`
            + `left:calc(${lane * width}% + 2px);width:calc(${width}% - 4px);--c:${colourFor(m.id)}`,
          title: `${m.title}\n${m.start_time}–${m.end_time}${m.location ? ` · ${m.location}` : ''}\n${m.when}`
            + `${m.people.length ? `\nWith ${[m.owner, ...m.people].map(who).join(', ')}` : ''}${m.skipped ? '\nSkipped: its page was deleted' : ''}`,
          onclick: () => this.open(m),
          onpointerdown: (e) => e.stopPropagation(),
        }, el('b', {}, m.title), el('span', {}, `${m.start_time}–${m.end_time}`),
        m.location ? el('span', { class: 'week-where' }, m.location) : null,
        m.skipped ? el('span', {}, 'skipped') : null)));
      this.pickOn(col, iso, first * 60, hours.length * 60, HOUR / 60);
      return col;
    };
    return el('div', { class: 'week-wrap' }, el('div', { class: 'week-grid' },
      el('div', { class: 'week-corner' }),
      days.map((iso, i) => el('div', { class: `week-day-head ${iso === data.today ? 'is-today' : ''}` },
        el('b', {}, DAY_NAMES[i]), ` ${shortDay(iso)}`)),
      el('div', { class: 'week-hours', style: `height:${hours.length * HOUR}px` },
        hours.map((h, i) => el('span', { style: `top:${i * HOUR}px` }, `${String(h).padStart(2, '0')}:00`))),
      days.map(column)),
    items.length ? null : el('p', { class: 'hint week-empty' }, 'No meetings this week.'));
  },

  /** Drag over free time in a day (or click it) to set up a meeting then: in steps of a quarter, an hour if only clicked. */
  pickOn(col, iso, dayStart, dayLength, pxPerMin) {
    const STEP = 15;
    const hm = (min) => `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;
    const at = (e) => Math.max(0, Math.min(dayLength, (e.clientY - col.getBoundingClientRect().top) / pxPerMin));
    let from = null;
    let sel = null;
    let moved = false;
    const span = (to) => {
      const a = Math.floor(Math.min(from, to) / STEP) * STEP;
      const b = moved ? Math.max(a + STEP, Math.ceil(Math.max(from, to) / STEP) * STEP) : a + 60;
      return [a, Math.min(b, dayLength)];
    };
    const draw = (to) => {
      const [a, b] = span(to);
      sel.style.top = `${a * pxPerMin}px`;
      sel.style.height = `${(b - a) * pxPerMin}px`;
      sel.textContent = `${hm(dayStart + a)}–${hm(dayStart + b)}`;
    };
    col.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      from = at(e);
      moved = false;
      col.setPointerCapture(e.pointerId);
      sel = el('div', { class: 'week-sel' });
      col.append(sel);
      draw(from);
    });
    col.addEventListener('pointermove', (e) => {
      if (!sel) return;
      if (Math.abs(at(e) - from) >= STEP / 2) moved = true;
      draw(at(e));
    });
    col.addEventListener('pointerup', (e) => {
      if (!sel) return;
      const [a, b] = span(at(e));
      sel.remove();
      sel = null;
      Meetings.edit(null, { day: iso, from: hm(dayStart + a), to: hm(dayStart + b) });
    });
    col.addEventListener('pointercancel', () => { if (sel) { sel.remove(); sel = null; } });
  },

  async open(m) {
    if (m.skipped) { toast('This date was skipped: its page is in Deleted, to bring back', 'info', 5000); return; }
    if (m.note_id) { App.open(m.note_id); return; }
    try {
      const { note } = await api('POST', `/meetings/${m.id}/dates/${m.date}`);
      await App.reloadTrees();
      App.show(note);
    } catch (err) { toast(err.message, 'error'); }
  },
};

/* --- the Projects tab ---------------------------------------------------------------------------- */

const Projects = {
  current: null,

  async showList() {
    await App.flush();
    App.note = null;
    Tree.markActive('');
    App.setTab('projects');
    App.view('projects');
    const box = document.getElementById('projectsView');
    let data;
    try { data = await api('GET', '/projects'); } catch (err) { put(box, el('p', { class: 'hint' }, err.message)); return; }
    put(box,
      el('div', { class: 'library-head' }, el('h1', {}, glyph('cube'), ' Projects'),
        el('button', { class: 'btn btn-primary btn-sm', onclick: () => this.editProject(null, data.invitable) }, '＋ New project')),
      el('p', { class: 'hint' }, 'Work packages and their tasks, what waits for what, and a Gantt chart of it. ',
        'Everyone in a project adds and changes its tasks, and can put them on a meeting\'s agenda or a day of their notebook.'),
      data.projects.length ? el('div', { class: 'project-cards' }, data.projects.map((p) => el('a', {
        class: 'project-card', href: `#project=${p.id}`,
      }, el('div', { class: 'project-card-title' }, glyph('cube'), el('b', { text: p.title })),
      el('div', { class: 'hint' }, p.start ? `${dayMonthYear(p.start)} – ${dayMonthYear(p.end)}` : 'No tasks yet'),
      el('div', { class: 'progress' }, el('span', { style: `width:${p.tasks ? Math.round(100 * p.done / p.tasks) : 0}%` })),
      el('div', { class: 'hint' }, `${p.done} of ${p.tasks} task${p.tasks === 1 ? '' : 's'} done · ${p.members.map(who).join(', ')}`)))) :
        el('p', { class: 'hint' }, 'No projects yet. Set one up, and invite the people working on it.'));
  },

  async showProject(id) {
    await App.flush();
    App.note = null;
    Tree.markActive('');
    App.setTab('projects');
    App.view('projects');
    try {
      const { project } = await api('GET', `/projects/${id}`);
      this.render(project);
    } catch (err) {
      put(document.getElementById('projectsView'), el('p', { class: 'hint' }, err.message));
    }
  },

  /** After a change: the project as it is now, and which tasks moved with it. */
  changed(res, message) {
    const project = res.project || res;
    if (document.getElementById('projectsView').hidden) {
      if (App.note) App.refresh();
    } else this.render(project);
    const moved = res.moved || [];
    if (moved.length) {
      const said = (m) => (m.from === m.to ? `${m.title} now ends ${dayMonthYear(m.end)}` : `${m.title} → ${dayMonthYear(m.to)}`);
      toast(`${message ? `${message}. ` : ''}Moved with it: ${moved.slice(0, 4).map(said).join('; ')}`
        + `${moved.length > 4 ? ` and ${moved.length - 4} more` : ''}`, 'success', 7000);
    } else if (message) toast(message, 'success');
  },

  /** A project's tasks in the order they are shown: each work package's, each task followed by its subtasks. */
  ordered(project) {
    const rows = [];
    const kids = (pid, wp) => project.tasks.filter((t) => t.wp_id === wp && (t.parent_id || null) === pid);
    const walk = (t, depth) => { rows.push({ t, depth }); kids(t.id, t.wp_id).forEach((k) => walk(k, depth + 1)); };
    for (const wp of project.workpackages) {
      rows.push({ wp });
      kids(null, wp.id).forEach((t) => walk(t, 0));
    }
    return rows;
  },

  render(project) {
    this.current = project;
    const box = document.getElementById('projectsView');
    const titleOf = Object.fromEntries(project.tasks.map((t) => [t.id, t.title]));
    const wpOf = Object.fromEntries(project.workpackages.map((w) => [w.id, w]));
    const rows = this.ordered(project);
    const taskRow = (t, depth) => el('tr', { class: t.done_on ? 'done' : '' },
      el('td', { class: 'task-check' }, t.subtasks ? null : el('input', {
        type: 'checkbox', checked: !!t.done_on || null, title: t.done_on ? `Done ${dayMonthYear(t.done_on)} by ${who(t.done_by)}` : 'Tick when done: what waits for it moves to start the day after',
        onchange: async (e) => {
          try { this.changed(await api('PUT', `/tasks/${t.id}`, { done: e.target.checked }), e.target.checked ? 'Done' : 'Not done after all'); }
          catch (err) { toast(err.message, 'error'); e.target.checked = !e.target.checked; }
        },
      })),
      el('td', { style: `padding-left:${0.6 + depth * 1.3}rem` },
        el('a', { href: `#note=${t.note_id}`, class: 'task-link' }, t.subtasks ? el('b', { text: t.title }) : t.title),
        t.people.length ? el('div', { class: 'hint' }, t.people.map(who).join(', ')) : null),
      el('td', { class: 'nowrap' }, dayMonthYear(t.start)),
      el('td', { class: 'nowrap' }, dayMonthYear(t.end)),
      el('td', { class: 'nowrap hint' }, `${dayNo(t.end) - dayNo(t.start) + 1} d`),
      el('td', { class: 'hint' }, t.after.map((a) => `${titleOf[a.id] || '?'}${a.lag ? ` +${a.lag} d` : ''}`).join(', ')),
      el('td', { class: 'nowrap' },
        el('button', { class: 'icon-btn', title: 'Change this task', onclick: () => this.editTask(project, t) }, glyph('pencil')),
        el('button', { class: 'icon-btn', title: 'Add a subtask', onclick: () => this.editTask(project, null, { wp_id: t.wp_id, parent_id: t.id }) }, '＋')));
    const wpBlock = (wp) => {
      const mine = rows.filter((r) => r.t && r.t.wp_id === wp.id);
      return el('section', { class: 'wp-card', style: `--c:${wp.colour}` },
        el('div', { class: 'wp-head' },
          el('span', { class: 'wp-dot' }), el('b', { class: 'wp-title', text: wp.title }),
          el('span', { class: 'hint' }, wp.start ? ` ${dayMonthYear(wp.start)} – ${dayMonthYear(wp.end)} · ${wp.done} of ${wp.tasks} done` : ' no tasks yet'),
          el('span', { class: 'wp-actions' },
            el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.editTask(project, null, { wp_id: wp.id }) }, '＋ Task'),
            el('button', { class: 'btn btn-secondary btn-sm', title: 'The meeting agendas and pages this work package was put on, and what was written there',
              onclick: () => this.discussedWp(wp) }, 'Talked about…'),
            el('button', { class: 'icon-btn', title: 'Rename or describe this work package', onclick: () => this.editWp(project, wp) }, glyph('pencil')),
            el('button', { class: 'icon-btn', title: 'Delete this work package and its tasks', onclick: () => this.deleteWp(wp) }, glyph('trash')))),
        wp.description ? el('p', { class: 'hint wp-description', text: wp.description }) : null,
        mine.length ? el('table', { class: 'library-table task-table' },
          el('thead', {}, el('tr', {}, el('th', { class: 'task-check' }), el('th', {}, 'Task'), el('th', {}, 'Start'),
            el('th', {}, 'End'), el('th', {}, 'Days'), el('th', {}, 'Waits for'), el('th', {}))),
          el('tbody', {}, mine.map((r) => taskRow(r.t, r.depth)))) : null);
    };
    put(box,
      el('nav', { class: 'crumbs' }, el('a', { href: '#projects' }, 'Projects')),
      el('div', { class: 'library-head' }, el('h1', {}, glyph('cube'), ` ${project.title}`),
        el('span', { class: 'wp-actions' },
          el('button', { class: 'btn btn-secondary btn-sm', onclick: () => this.members(project) }, glyph('people'), ` Members (${project.members.length})`),
          project.can_manage ? el('button', { class: 'icon-btn', title: 'Rename or describe the project', onclick: () => this.editProject(project) }, glyph('pencil')) : null,
          project.can_manage ? el('button', { class: 'icon-btn', title: 'Delete the project', onclick: () => this.deleteProject(project) }, glyph('trash')) : null)),
      project.description ? el('p', { class: 'project-description', text: project.description }) : null,
      el('p', { class: 'hint' }, `${project.members.map(who).join(', ')}. `,
        'A task that waits for others starts the day after they finish; change when one finishes, or tick it done, and what waits for it moves too.'),
      project.tasks.length ? Gantt.render(project, wpOf) : null,
      project.workpackages.map(wpBlock),
      el('div', { class: 'wp-add' }, el('button', { class: 'btn btn-primary btn-sm', onclick: () => this.editWp(project, null) }, '＋ Work package')));
  },

  editProject(project, invitable = []) {
    const title = el('input', { type: 'text', value: project?.title || '', placeholder: 'e.g. Petunia CRISPR lines', maxlength: 120 });
    const description = el('textarea', { rows: 3, placeholder: 'What it is for (optional)' }, project?.description || '');
    const chosen = new Set();
    const people = project ? null : el('div', { class: 'meeting-people' }, invitable.filter((u) => u !== NB.person.username)
      .map((u) => el('label', { class: 'meeting-person' }, el('input', { type: 'checkbox', onchange: (e) => (e.target.checked ? chosen.add(u) : chosen.delete(u)) }), ` ${who(u)}`)));
    modal({
      title: project ? `Change “${project.title}”` : 'New project',
      wide: true,
      build: (body) => body.append(el('div', { class: 'meeting-form' },
        el('label', { class: 'meeting-field' }, el('span', {}, 'Title'), title),
        el('label', { class: 'meeting-field' }, el('span', {}, 'Description'), description),
        people ? el('div', { class: 'meeting-field' }, el('span', {}, 'Members'), people,
          el('span', { class: 'hint' }, 'Anyone in Trellis Tools. Members add and change work packages and tasks; you can invite more later.')) : null)),
      buttons: [{ label: 'Cancel', kind: 'secondary' }, { label: project ? 'Save' : 'Set up project', onClick: async () => {
        if (project) {
          const res = await api('PUT', `/projects/${project.id}`, { title: title.value, description: description.value });
          this.render(res.project);
        } else {
          const res = await api('POST', '/projects', { title: title.value, description: description.value, members: [...chosen] });
          location.hash = `#project=${res.project.id}`;
        }
      } }],
    });
  },

  deleteProject(project) {
    modal({
      title: `Delete “${project.title}”?`,
      build: (body) => body.append(el('p', {}, 'Its work packages, tasks and their pages go with it, for every member. ',
        'What was written about its tasks on meeting pages and days stays there.')),
      buttons: [{ label: 'Keep it', kind: 'secondary' }, { label: 'Delete project', kind: 'danger', onClick: async () => {
        await api('DELETE', `/projects/${project.id}`);
        toast('Project deleted', 'success');
        location.hash = '#projects';
      } }],
    });
  },

  async members(project) {
    let invitable = [];
    try { invitable = (await api('GET', '/projects')).invitable; } catch { /* the list only */ }
    modal({
      title: `Members of “${project.title}”`,
      build: (body, close) => {
        const list = el('div');
        const draw = () => put(list, el('table', { class: 'library-table' }, el('tbody', {}, project.members.map((u) => el('tr', {},
          el('td', {}, glyph('person'), ' ', el('b', { text: who(u) }), u === project.owner ? el('span', { class: 'hint' }, ' · set it up') : null),
          el('td', { class: 'nowrap' }, u !== project.owner && (project.can_manage || u === NB.person.username)
            ? el('button', { class: 'btn btn-secondary btn-sm', onclick: async () => {
              try {
                const res = await api('DELETE', `/projects/${project.id}/members/${encodeURIComponent(u)}`);
                if (!res.project) { close(); location.hash = '#projects'; toast('You left the project', 'success'); return; }
                project = res.project; draw(); this.render(project);
              } catch (err) { toast(err.message, 'error'); }
            } }, u === NB.person.username ? 'Leave' : 'Take off') : null))))));
        const select = el('select', { class: 'share-select' }, el('option', { value: '' }, 'Invite someone…'),
          invitable.filter((u) => !project.members.includes(u)).map((u) => el('option', { value: u }, who(u))));
        body.append(el('p', { class: 'hint' }, 'Members open the project, add and change its work packages and tasks, write on the tasks\' pages, ',
          'and put tasks on meeting agendas and days of their notebook. ', project.can_manage ? 'Only you rename, invite to and delete the project.' : ''),
        list,
        project.can_manage ? el('div', { class: 'form-row' }, select, el('button', { class: 'btn btn-primary btn-sm', onclick: async () => {
          if (!select.value) return;
          try {
            project = (await api('POST', `/projects/${project.id}/members`, { username: select.value })).project;
            select.querySelector(`option[value="${CSS.escape(select.value)}"]`)?.remove();
            select.value = '';
            draw();
            this.render(project);
          } catch (err) { toast(err.message, 'error'); }
        } }, 'Invite')) : null);
        draw();
      },
    });
  },

  editWp(project, wp) {
    const title = el('input', { type: 'text', value: wp?.title || '', placeholder: 'e.g. WP1 Constructs', maxlength: 160 });
    const description = el('textarea', { rows: 3, placeholder: 'What it covers (optional)' }, wp?.description || '');
    modal({
      title: wp ? `Change “${wp.title}”` : 'New work package',
      build: (body) => body.append(el('div', { class: 'meeting-form' },
        el('label', { class: 'meeting-field' }, el('span', {}, 'Title'), title),
        el('label', { class: 'meeting-field' }, el('span', {}, 'Description'), description))),
      buttons: [{ label: 'Cancel', kind: 'secondary' }, { label: wp ? 'Save' : 'Add work package', onClick: async () => {
        const res = wp ? await api('PUT', `/workpackages/${wp.id}`, { title: title.value, description: description.value })
          : await api('POST', `/projects/${project.id}/workpackages`, { title: title.value, description: description.value });
        this.changed(res);
      } }],
    });
  },

  deleteWp(wp) {
    modal({
      title: `Delete “${wp.title}”?`,
      build: (body) => body.append(el('p', {}, `Its ${wp.tasks} task${wp.tasks === 1 ? '' : 's'} and their pages go with it; `,
        'tasks of other work packages waiting for them no longer wait.')),
      buttons: [{ label: 'Keep it', kind: 'secondary' }, { label: 'Delete work package', kind: 'danger', onClick: async () => {
        this.changed(await api('DELETE', `/workpackages/${wp.id}`), 'Work package deleted');
      } }],
    });
  },

  async discussedWp(wp) {
    let found;
    try { found = (await api('GET', `/workpackages/${wp.id}/discussed`)).discussed; } catch (err) { toast(err.message, 'error'); return; }
    modal({ title: `“${wp.title}” was talked about`, wide: true, build: (body, close) => body.append(Projects.discussedList(found, close,
      'Not on any meeting agenda or page yet. On a meeting\'s page (or a day), press Task… and choose the work package.')) });
  },

  discussedList(found, close, empty) {
    return found.length ? el('ul', { class: 'discussed' }, found.map((d) => el('li', {},
      el('div', {}, noteGlyph(d.type), ' ', el('a', { href: `#note=${d.id}`, onclick: () => close?.() }, d.title),
        el('span', { class: 'hint' }, ` · ${dayMonthYear(d.date)}${d.owner && d.owner !== NB.person.username ? ` · ${who(d.owner)}'s notebook` : ''}`)),
      d.text ? el('blockquote', { text: d.text }) : el('div', { class: 'hint' }, 'Nothing written under it.'))))
      : el('p', { class: 'hint' }, empty);
  },

  /** Add a task (task null; wp_id and parent_id given) or change one. */
  editTask(project, task, { wp_id = null, parent_id = null } = {}) {
    const below = new Set();
    if (task) {
      const walk = (id) => project.tasks.filter((t) => t.parent_id === id).forEach((k) => { below.add(k.id); walk(k.id); });
      walk(task.id);
    }
    const above = new Set();
    for (let p = task?.parent_id || parent_id; p; p = project.tasks.find((t) => t.id === p)?.parent_id) above.add(p);
    const title = el('input', { type: 'text', value: task?.title || '', placeholder: 'e.g. Design guide RNAs', maxlength: 200 });
    const wp = el('select', {}, project.workpackages.map((w) => el('option', { value: w.id, selected: (task?.wp_id || wp_id) === w.id || null }, w.title)));
    const parentPick = el('select', {}, el('option', { value: '' }, '— none: a task of its own —'),
      this.ordered(project).filter((r) => r.t && r.t.id !== task?.id && !below.has(r.t.id))
        .map((r) => el('option', { value: r.t.id, selected: (task?.parent_id || parent_id) === r.t.id || null },
          `${'  '.repeat(r.depth)}${r.t.title} (${project.workpackages.find((w) => w.id === r.t.wp_id)?.title || ''})`)));
    const start = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'dd-mm-yyyy',
      value: dayMonthYear(task?.start_on || task?.start || project.today) });
    const days = el('input', { type: 'number', min: 1, max: 3650, value: task?.duration || 5 });
    const waits = new Map((task?.after || []).map((a) => [a.id, a.lag]));
    const candidates = this.ordered(project).filter((r) => r.t && r.t.id !== task?.id && !below.has(r.t.id) && !above.has(r.t.id));
    const startNote = el('span', { class: 'hint' });
    const byTask = (id) => project.tasks.find((x) => x.id === id);
    const inherited = () => {
      for (let p = parentPick.value || null; p; p = byTask(p)?.parent_id) if (byTask(p)?.after.length) return byTask(p);
      return null;
    };
    const showStart = () => {
      const from = inherited();
      const waiting = waits.size > 0 || !!from;
      start.disabled = waiting;
      startNote.textContent = waits.size ? 'Set by what it waits for: it starts the day after the last of them finishes, plus any lag.'
        : from ? `Set by what “${from.title}” waits for, as it is one of its subtasks.`
          : 'It keeps this start until it is given something to wait for.';
    };
    parentPick.addEventListener('change', showStart);
    const waitList = el('div', { class: 'wait-list' }, candidates.length ? candidates.map((r) => {
      const lag = el('input', { type: 'number', class: 'lag', min: -365, max: 3650, value: waits.get(r.t.id) || 0,
        title: 'Days to wait after it finishes (0: the next day)', disabled: !waits.has(r.t.id) || null,
        oninput: (e) => { if (waits.has(r.t.id)) waits.set(r.t.id, Number(e.target.value) || 0); } });
      return el('label', { class: 'wait-item' },
        el('input', { type: 'checkbox', checked: waits.has(r.t.id) || null, onchange: (e) => {
          if (e.target.checked) waits.set(r.t.id, Number(lag.value) || 0); else waits.delete(r.t.id);
          lag.disabled = !e.target.checked;
          showStart();
        } }),
        el('span', { class: 'wait-title', style: `padding-left:${r.depth}rem` }, r.t.title,
          el('span', { class: 'hint' }, ` · ends ${dayMonthYear(r.t.end)}`)),
        el('span', { class: 'hint' }, '+'), lag, el('span', { class: 'hint' }, 'd'));
    }) : el('p', { class: 'hint' }, 'No other tasks in the project yet.'));
    showStart();
    const people = new Set(task?.people || []);
    const peopleBox = el('div', { class: 'meeting-people' }, project.members.map((u) => el('label', { class: 'meeting-person' },
      el('input', { type: 'checkbox', checked: people.has(u) || null, onchange: (e) => (e.target.checked ? people.add(u) : people.delete(u)) }),
      ` ${who(u)}`)));
    const done = el('input', { type: 'checkbox', checked: !!task?.done_on || null });
    const doneOn = el('input', { type: 'text', inputmode: 'numeric', placeholder: 'dd-mm-yyyy',
      value: dayMonthYear(task?.done_on || todayIso()), disabled: !task?.done_on || null });
    done.addEventListener('change', () => { doneOn.disabled = !done.checked; });
    const hasKids = !!task?.subtasks;
    const save = async () => {
      const iso = (box, what) => { const v = isoFromDayMonthYear(box.value); if (!v) throw new Error(`Type ${what} as dd-mm-yyyy`); return v; };
      const body = {
        title: title.value, wp_id: wp.value, parent_id: parentPick.value || null,
        start_on: start.disabled ? undefined : iso(start, 'the start'), duration: Number(days.value),
        after: [...waits].map(([id, lag]) => ({ id, lag })), people: [...people],
      };
      if (!hasKids) Object.assign(body, { done: done.checked, done_on: done.checked ? iso(doneOn, 'the day it was done') : null });
      const res = task ? await api('PUT', `/tasks/${task.id}`, body) : await api('POST', `/projects/${project.id}/tasks`, body);
      this.changed(res, task ? 'Task changed' : 'Task added');
    };
    const buttons = [{ label: 'Cancel', kind: 'secondary' }];
    if (task) buttons.push({ label: 'Delete task…', kind: 'danger', onClick: ({ close }) => { this.deleteTask(task, close); return false; } });
    buttons.push({ label: task ? 'Save' : 'Add task', onClick: save });
    const field = (label, input, hint) => el('label', { class: 'meeting-field' }, el('span', {}, label), input, hint ? el('span', { class: 'hint' }, hint) : null);
    modal({
      title: task ? `Change “${task.title}”` : (parent_id ? 'New subtask' : 'New task'),
      wide: true,
      build: (body) => body.append(el('div', { class: 'meeting-form' },
        field('Title', title),
        el('div', { class: 'meeting-row' }, field('Work package', wp), field('Subtask of', parentPick)),
        hasKids ? el('p', { class: 'hint' }, `Its dates are those of its ${task.subtasks} subtasks: ${dayMonthYear(task.start)} – ${dayMonthYear(task.end)}.`)
          : el('div', { class: 'meeting-row' }, field('Start', start, startNote), field('Length (days)', days, 'Calendar days, the start day counted.')),
        el('div', { class: 'meeting-field' }, el('span', {}, 'Waits for'), waitList,
          el('span', { class: 'hint' }, 'Tick the tasks that must finish first. A lag adds days after one finishes (e.g. 2 for seeds to dry).')),
        el('div', { class: 'meeting-field' }, el('span', {}, 'People working on it'), peopleBox),
        hasKids ? null : el('div', { class: 'meeting-row' },
          el('label', { class: 'meeting-person' }, done, ' Done'), field('Done on', doneOn, 'Done on another day than planned: what waits for it moves to follow.')))),
      buttons,
    });
  },

  deleteTask(task, closeForm) {
    modal({
      title: `Delete “${task.title}”?`,
      build: (body) => body.append(el('p', {}, task.subtasks ? `Its ${task.subtasks} subtasks, ` : '',
        'its page and what is written on it go too; tasks waiting for it no longer wait. ',
        'What was written about it on meeting pages and days stays there.')),
      buttons: [{ label: 'Keep it', kind: 'secondary' }, { label: 'Delete task', kind: 'danger', onClick: async () => {
        const res = await api('DELETE', `/tasks/${task.id}`);
        closeForm();
        if (App.note && App.note.task?.id === task.id) { location.hash = `#project=${res.project.id}`; return; }
        this.changed(res, 'Task deleted');
      } }],
    });
  },

  /** A task's page: where it is, its dates, what it waits for and what waits for it, and where it was talked about. */
  taskPanel(note) {
    const t = note.task;
    if (!t) return null;
    const link = (x) => el('a', { href: `#note=${x.note_id}` }, x.title);
    const open = async () => {
      try { const { project } = await api('GET', `/projects/${t.project.id}`); this.editTask(project, project.tasks.find((x) => x.id === t.id)); }
      catch (err) { toast(err.message, 'error'); }
    };
    return el('div', { class: 'task-panel' },
      el('div', { class: 'crumbs' }, el('a', { href: `#project=${t.project.id}` }, t.project.title), ' › ',
        t.workpackage ? t.workpackage.title : '', t.parent ? [' › ', link(t.parent)] : null),
      el('div', { class: 'task-dates' },
        t.subtasks.length ? null : el('label', { class: 'meeting-person' }, el('input', {
          type: 'checkbox', checked: !!t.done_on || null,
          onchange: async (e) => {
            try { this.changed(await api('PUT', `/tasks/${t.id}`, { done: e.target.checked }), e.target.checked ? 'Done' : 'Not done after all'); }
            catch (err) { toast(err.message, 'error'); e.target.checked = !e.target.checked; }
          },
        }), t.done_on ? ` Done ${dayMonthYear(t.done_on)} by ${who(t.done_by)}` : ' Done'),
        el('b', {}, `${dayMonthYear(t.start)} → ${dayMonthYear(t.end)}`),
        el('span', { class: 'hint' }, ` · ${dayNo(t.end) - dayNo(t.start) + 1} days`),
        t.people.length ? el('span', {}, ' · ', glyph('people'), ` ${t.people.map(who).join(', ')}`) : null,
        el('button', { class: 'btn btn-secondary btn-sm', onclick: open }, glyph('pencil'), ' Change task')),
      t.after.length ? el('div', {}, el('span', { class: 'hint' }, 'Waits for: '), t.after.map((a, i) => [i ? ', ' : '', link(a),
        el('span', { class: 'hint' }, ` (${a.done_on ? 'done' : 'ends'} ${dayMonthYear(a.done_on || a.end)}${a.lag ? `, +${a.lag} d` : ''})`)])) : null,
      t.waiting.length ? el('div', {}, el('span', { class: 'hint' }, 'Waiting for it: '), t.waiting.map((a, i) => [i ? ', ' : '', link(a)])) : null,
      t.subtasks.length ? el('div', {}, el('span', { class: 'hint' }, 'Subtasks: '), t.subtasks.map((a, i) => [i ? ', ' : '', link(a),
        a.done_on ? ' ✓' : ''])) : null,
      el('details', { class: 'task-discussed', open: t.discussed.length > 0 || null },
        el('summary', {}, `Talked about (${t.discussed.length})`),
        this.discussedList(t.discussed, null, 'Not on any meeting agenda or page yet. On a meeting\'s page (or a day), press Task… and choose it.')),
      el('p', { class: 'hint' }, 'Write the description and notes below: @ links protocols, stocks, seeds and plasmids, as on any page.'));
  },

  /** Choose a task or work package of one's projects, as a section for a page. */
  async pickSection() {
    const { projects } = await api('GET', '/projects/pick');
    if (!projects.length) { toast('You are not in any project yet: set one up in the Projects tab', 'info', 5000); return null; }
    const all = [];
    for (const p of projects) {
      for (const w of p.workpackages) {
        all.push({ kind: 'workpackage', id: w.id, title: w.title, where: p.title });
        const walk = (pid, depth) => w.tasks.filter((t) => (t.parent_id || null) === pid).forEach((t) => {
          all.push({ kind: 'task', id: t.id, title: t.title, where: `${p.title} › ${w.title}`, depth, t });
          walk(t.id, depth + 1);
        });
        walk(null, 1);
      }
    }
    const chosen = await picker({
      title: 'Put a task or work package on this page',
      placeholder: 'Search your projects\' tasks and work packages',
      search: async (q) => all.filter((x) => !q || `${x.title} ${x.where}`.toLowerCase().includes(q.toLowerCase())),
      describe: (x) => [el('span', { style: `padding-left:${(x.depth || 0) * 0.8}rem` }), glyph(x.kind === 'task' ? 'steps' : 'cube'), ' ',
        el('b', { text: x.title }), el('span', { class: 'hint' }, ` · ${x.kind === 'task'
          ? `${x.where} · ${dayMonthYear(x.t.start)} – ${dayMonthYear(x.t.end)}${x.t.done_on ? ' · done' : ''}` : `work package of ${x.where}`}`)],
    });
    if (!chosen) return null;
    return (await api('GET', `/projects/section?kind=${chosen.kind}&id=${chosen.id}`)).section;
  },

  /** A task or work package's section on a page: open it. */
  async openSource(src) {
    if (src.kind === 'task') {
      try { const { task } = await api('GET', `/tasks/${src.id}`); App.open(task.note_id); }
      catch (err) { toast(err.message, 'error'); }
    } else {
      try { const { workpackage } = await api('GET', `/workpackages/${src.id}`); location.hash = `#project=${workpackage.project_id}`; }
      catch (err) { toast(err.message, 'error'); }
    }
  },
};

/* --- the Gantt chart ------------------------------------------------------------------------------- */

/** The chart's look, inside the chart: an SVG or PNG exported from it looks as it does here. */
const GANTT_STYLE = `
text { font-family: "Segoe UI", system-ui, -apple-system, Helvetica, Arial, sans-serif; font-size: 12px; fill: #2b2620; }
.gantt-tick, .gantt-month { fill: #6f665c; font-size: 11px; }
.gantt-month { font-weight: 600; }
.gantt-wp-label { font-weight: 700; }
.gantt-parent { font-weight: 600; }
.gantt-title { font-size: 15px; font-weight: 700; }
.gantt-bg { fill: #ffffff; }
.gantt-weekend { fill: #f6f2ec; }
.gantt-week { stroke: #efe9df; }
.gantt-axis { stroke: #e6dfd4; }
.gantt-wp-row { fill: #f3efe8; }
.gantt-summary { fill: #2b2620; }
.gantt-links path { fill: none; stroke: #6f665c; stroke-width: 1.2; }
.gantt-arrowhead { fill: #6f665c; }
.gantt-today { stroke: #c0392b; stroke-width: 1.5; stroke-dasharray: 3 2; }
.gantt-label:hover text, a:hover .gantt-bar { text-decoration: underline; opacity: 1; }
`;

/** A name for a file: the project's title and today's date, without characters a file name cannot hold. */
const fileName = (title, what, ext) => `${String(title).replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim() || 'Project'} - ${what} ${todayIso()}.${ext}`;

function download(blob, name) {
  const a = el('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

const Gantt = {
  render(project, wpOf) {
    const rows = Projects.ordered(project);
    const ROW = 26; const LABEL = 250; const HEAD = 38;
    const starts = project.tasks.map((t) => dayNo(t.start)); const ends = project.tasks.map((t) => dayNo(t.end));
    const today = dayNo(project.today);
    const d0 = Math.min(...starts, today) - 2;
    const d1 = Math.max(...ends, today) + 3;
    const span = d1 - d0 + 1;
    const avail = Math.max(600, (document.getElementById('projectsView').clientWidth || 1000) - LABEL - 20);
    const DAY = Math.max(3, Math.min(30, avail / span));
    const W = LABEL + span * DAY; const H = HEAD + rows.length * ROW + 6;
    const NS = 'http://www.w3.org/2000/svg';
    const s = (tag, attrs = {}, ...kids) => {
      const n = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
      for (const k of kids.flat()) if (k !== null && k !== undefined) n.append(typeof k === 'string' ? document.createTextNode(k) : k);
      return n;
    };
    const x = (n) => LABEL + (n - d0) * DAY;
    const svg = s('svg', { class: 'gantt', xmlns: NS, width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img',
      'aria-label': `Gantt chart of ${project.title}` });
    svg.append(s('style', {}, GANTT_STYLE));
    svg.append(s('rect', { x: 0, y: 0, width: W, height: H, class: 'gantt-bg' }));
    svg.append(s('defs', {}, s('marker', { id: 'gantt-arrow', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto' },
      s('path', { d: 'M0,0 L8,4 L0,8 z', class: 'gantt-arrowhead' }))));
    // Weekends, weeks and months.
    const grid = s('g', { class: 'gantt-grid' });
    for (let n = d0; n <= d1; n++) {
      const iso = isoOf(n); const wd = weekdayOf(iso);
      if (wd >= 5 && DAY >= 6) grid.append(s('rect', { x: x(n), y: HEAD, width: DAY, height: H - HEAD, class: 'gantt-weekend' }));
      if (wd === 0) {
        grid.append(s('line', { x1: x(n), x2: x(n), y1: HEAD - 14, y2: H, class: 'gantt-week' }));
        if (DAY * 7 >= 36) grid.append(s('text', { x: x(n) + 3, y: HEAD - 4, class: 'gantt-tick' }, shortDay(iso)));
      }
      if (iso.endsWith('-01') || n === d0) {
        grid.append(s('text', { x: x(n) + 3, y: 13, class: 'gantt-month' },
          new Date(n * DAY_MS).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })));
        grid.append(s('line', { x1: x(n), x2: x(n), y1: 0, y2: 18, class: 'gantt-week' }));
      }
    }
    svg.append(grid);
    svg.append(s('line', { x1: LABEL, x2: W, y1: HEAD, y2: HEAD, class: 'gantt-axis' }));
    const at = {};                    // task id -> {y, x1, x2}
    rows.forEach((r, i) => {
      const y = HEAD + i * ROW;
      const mid = y + ROW / 2;
      if (r.wp) {
        const wp = r.wp;
        svg.append(s('rect', { x: 0, y, width: W, height: ROW, class: 'gantt-wp-row' }));
        svg.append(s('text', { x: 6, y: mid + 4, class: 'gantt-wp-label' }, wp.title.length > 34 ? `${wp.title.slice(0, 33)}…` : wp.title));
        if (wp.start) {
          svg.append(s('rect', { x: x(dayNo(wp.start)), y: y + 8, width: (dayNo(wp.end) - dayNo(wp.start) + 1) * DAY, height: ROW - 16,
            rx: 2, fill: wp.colour, opacity: 0.35 }, s('title', {}, `${wp.title}: ${dayMonthYear(wp.start)} – ${dayMonthYear(wp.end)}`)));
        }
        return;
      }
      const t = r.t;
      const colour = wpOf[t.wp_id]?.colour || '#2e7d5b';
      const x1 = x(dayNo(t.start)); const x2 = x(dayNo(t.end) + 1);
      at[t.id] = { y: mid, x1, x2 };
      const label = s('a', { href: `#note=${t.note_id}`, class: 'gantt-label' },
        s('text', { x: 10 + r.depth * 12, y: mid + 4, class: t.subtasks ? 'gantt-parent' : '' },
          `${t.done_on ? '✓ ' : ''}${t.title.length > 30 - r.depth * 2 ? `${t.title.slice(0, 29 - r.depth * 2)}…` : t.title}`));
      svg.append(label);
      const tip = s('title', {}, `${t.title}\n${dayMonthYear(t.start)} – ${dayMonthYear(t.end)} (${dayNo(t.end) - dayNo(t.start) + 1} days)`
        + `${t.people.length ? `\n${t.people.map(who).join(', ')}` : ''}${t.done_on ? `\nDone ${dayMonthYear(t.done_on)}` : ''}`);
      if (t.subtasks) {
        svg.append(s('path', { d: `M${x1},${y + 8} H${x2} V${y + 15} L${x2 - 5},${y + 11} H${x1 + 5} L${x1},${y + 15} Z`, class: 'gantt-summary' }, tip));
      } else {
        svg.append(s('a', { href: `#note=${t.note_id}` }, s('rect', { x: x1, y: y + 5, width: Math.max(3, x2 - x1), height: ROW - 10, rx: 3,
          fill: colour, opacity: t.done_on ? 0.45 : 0.9, class: 'gantt-bar' }, tip)));
      }
    });
    // What waits for what: from the end of one to the start of the other.
    const links = s('g', { class: 'gantt-links' });
    for (const t of project.tasks) {
      for (const a of t.after) {
        const from = at[a.id]; const to = at[t.id];
        if (!from || !to) continue;
        const xa = from.x2; const xb = to.x1;
        const d = xb - xa >= 10
          ? `M${xa},${from.y} H${xa + 5} V${to.y} H${xb - 1}`
          : `M${xa},${from.y} H${xa + 5} V${(from.y + to.y) / 2} H${xb - 8} V${to.y} H${xb - 1}`;
        links.append(s('path', { d, 'marker-end': 'url(#gantt-arrow)' }));
      }
    }
    svg.append(links);
    if (today >= d0 && today <= d1) {
      svg.append(s('line', { x1: x(today) + DAY / 2, x2: x(today) + DAY / 2, y1: HEAD - 6, y2: H, class: 'gantt-today' }, s('title', {}, 'Today')));
    }
    return el('section', { class: 'gantt-box' },
      el('div', { class: 'gantt-head' }, el('b', {}, 'Gantt chart'),
        el('span', { class: 'hint' }, `${dayMonthYear(isoOf(Math.min(...starts)))} – ${dayMonthYear(isoOf(Math.max(...ends)))}`),
        el('button', { class: 'btn btn-secondary btn-sm', title: 'Save the chart as a PDF (with a table of the tasks), a picture or a drawing',
          onclick: () => this.exportDialog(project, svg) }, '⤓ Export chart')),
      el('div', { class: 'gantt-scroll' }, svg),
      el('p', { class: 'hint' }, 'Bars are tasks, coloured by work package (paler when done), black brackets tasks with subtasks; arrows run from a task to what waits for it. Today is the red line.'));
  },

  /**
   * The chart as it is drawn, as a standalone SVG: links left out, and with the project's name and the date above it
   * (titled false: without, for the PDF, whose page says so already).
   */
  standalone(project, svg, { titled = true } = {}) {
    const copy = svg.cloneNode(true);
    copy.removeAttribute('class');
    // Links lead nowhere outside the notebook: their text and bars stay.
    for (const a of [...copy.querySelectorAll('a')]) a.replaceWith(...a.childNodes);
    const W = Number(svg.getAttribute('width')); const H = Number(svg.getAttribute('height'));
    const TOP = titled ? 34 : 0;
    copy.setAttribute('height', H + TOP);
    copy.setAttribute('viewBox', `0 ${-TOP} ${W} ${H + TOP}`);
    const NS = 'http://www.w3.org/2000/svg';
    const bg = document.createElementNS(NS, 'rect');
    Object.entries({ x: 0, y: -TOP, width: W, height: TOP, class: 'gantt-bg' }).forEach(([k, v]) => bg.setAttribute(k, v));
    const title = document.createElementNS(NS, 'text');
    Object.entries({ x: 8, y: -12, class: 'gantt-title' }).forEach(([k, v]) => title.setAttribute(k, v));
    title.textContent = `${project.title} · Gantt chart · ${dayMonthYear(todayIso())}`;
    if (titled) copy.querySelector('.gantt-bg').before(bg, title);
    return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(copy)}`;
  },

  exportDialog(project, svg) {
    const choice = (label, what, run) => el('button', { class: 'export-choice', onclick: async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try { await run(); } catch (err) { toast(err.message, 'error', 6000); } finally { btn.disabled = false; }
    } }, el('b', {}, label), el('span', { class: 'hint' }, what));
    modal({
      title: `Export the Gantt chart of “${project.title}”`,
      build: (body) => body.append(el('div', { class: 'export-choices' },
        choice('PDF', 'The chart on a landscape page, then a table of the tasks: dates, what they wait for, who, done. For reports and printing.',
          () => this.pdf(project, svg)),
        choice('PNG', 'A picture, sharp at twice the size on screen: for slides and e-mail.', () => this.png(project, svg)),
        choice('SVG', 'A drawing that stays sharp at any size and can be changed in Inkscape or Illustrator: for papers and posters.',
          async () => download(new Blob([this.standalone(project, svg)], { type: 'image/svg+xml' }), fileName(project.title, 'Gantt chart', 'svg'))))),
    });
  },

  async png(project, svg) {
    const text = this.standalone(project, svg);
    const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
    try {
      const img = new Image();
      await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error('The chart could not be drawn as a picture')); img.src = url; });
      const SCALE = 2;
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth * SCALE;
      canvas.height = img.naturalHeight * SCALE;
      const ctx2d = canvas.getContext('2d');
      ctx2d.fillStyle = '#ffffff';
      ctx2d.fillRect(0, 0, canvas.width, canvas.height);
      ctx2d.drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((ok) => canvas.toBlob(ok, 'image/png'));
      download(blob, fileName(project.title, 'Gantt chart', 'png'));
    } finally { URL.revokeObjectURL(url); }
  },

  async pdf(project, svg) {
    const res = await fetch(url(`/api/projects/${project.id}/gantt.pdf`), {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ svg: this.standalone(project, svg, { titled: false }) }),
    });
    if (!res.ok) {
      let message = `The PDF could not be made (${res.status})`;
      try { message = (await res.json()).error || message; } catch { /* not JSON */ }
      throw new Error(message);
    }
    download(await res.blob(), fileName(project.title, 'Gantt chart', 'pdf'));
  },
};
