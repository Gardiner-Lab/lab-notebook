"""
An export as a PDF, made with WeasyPrint from HTML written here.

    Photos      shown where they are in the text, or under the note's files.
    PDFs        their pages, placed into the document where the PDF is attached.
                The export saves a page for each, with its header and page
                number, and the PDF's page is drawn onto it.
    Other files embedded in the PDF (a paperclip a PDF reader opens). Text,
                CSV and sequence files are also printed, as text or a table.

Nothing is fetched from anywhere but the notebook's own attachments.
"""

import csv
import html
import io
from urllib.parse import quote, unquote
from typing import Callable, Dict, List, Optional

from app import content, exporting, richtext, sheet
from app.exporting import Context, Entry

ATTACHMENT_URL = 'https://attachment.invalid/'
MAX_PDF_PAGES = 100
MAX_TEXT_LINES = 400
MAX_TABLE_ROWS = 300
# A4, in PDF points, and the room left for an attached PDF's page on one of ours.
PAGE_W, PAGE_H = 595.28, 841.89
MM = 72 / 25.4
INSET_LEFT, INSET_RIGHT, INSET_TOP, INSET_BOTTOM = 16 * MM, 16 * MM, 30 * MM, 20 * MM

esc = html.escape

CSS = """
@page {
  size: A4; margin: 18mm 16mm 20mm 16mm;
  @bottom-left { content: string(doc-title) " · exported " string(doc-stamp); font-size: 7.5pt; color: #6b7280; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 7.5pt; color: #6b7280; }
}
@page :first { @bottom-left { content: none; } @bottom-right { content: none; } }
html { font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; color: #111827; line-height: 1.4; }
.doc-title { string-set: doc-title content(); }
.doc-stamp { string-set: doc-stamp content(); visibility: hidden; height: 0; margin: 0; }
a { color: #1d4ed8; text-decoration: none; }
.cover { break-after: page; padding-top: 60mm; }
.cover h1 { font-size: 24pt; margin: 0 0 4mm; bookmark-level: none; }
.cover .sub { font-size: 12pt; color: #374151; margin-bottom: 14mm; }
.cover table { border-collapse: collapse; font-size: 9.5pt; }
.cover td { padding: 1.2mm 6mm 1.2mm 0; vertical-align: top; }
.cover td:first-child { color: #6b7280; white-space: nowrap; }
.toc { break-after: page; }
.toc h2 { bookmark-level: none; font-size: 14pt; }
.toc ol { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 0.6mm 0; }
.toc a::after { content: leader('.') target-counter(attr(href), page); color: #6b7280; }
.toc .t-day, .toc .t-page, .toc .t-protocol { font-size: 9pt; }
.note { margin: 0 0 8mm; }
.note.break { break-before: page; }
.note-title { font-size: 15pt; margin: 0 0 1mm; color: #111827; }
.depth-1 .note-title { font-size: 13.5pt; }
.depth-2 .note-title, .depth-3 .note-title, .depth-4 .note-title { font-size: 12pt; }
.note-meta { font-size: 8pt; color: #6b7280; margin-bottom: 1mm; }
.labels { font-size: 8pt; color: #4338ca; margin-bottom: 2mm; }
.empty { color: #9ca3af; font-style: italic; }
.text h1, .text h2, .text h3 { bookmark-level: none; }
.text h1 { font-size: 13pt; } .text h2 { font-size: 12pt; } .text h3 { font-size: 11pt; }
.text img, figure img { max-width: 100%; max-height: 200mm; }
.text mark { background: #fef08a; }
pre, code { font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; }
pre { white-space: pre-wrap; background: #f3f4f6; padding: 2mm; border-radius: 1mm; }
blockquote { border-left: 2pt solid #d1d5db; margin-left: 0; padding-left: 3mm; color: #374151; }
.block-title { font-weight: bold; margin: 3mm 0 1mm; }
.steps ol { padding-left: 6mm; margin: 0; }
.steps li { margin: 0.6mm 0; }
.box { font-family: "DejaVu Sans"; }
.tick { color: #047857; font-size: 7.5pt; margin-left: 2mm; }
.scale { font-size: 8.5pt; color: #374151; margin-bottom: 1mm; }
table.sheet { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin-bottom: 2mm; }
table.sheet th, table.sheet td { border: 0.6pt solid #d1d5db; padding: 1mm 1.5mm; vertical-align: top; }
table.sheet th { background: #f3f4f6; text-align: left; }
table.sheet .letter { color: #9ca3af; font-weight: normal; margin-right: 1mm; }
table.sheet .unit, table.sheet .formula { color: #6b7280; font-weight: normal; }
table.sheet .formula { display: block; font-size: 7pt; }
table.sheet td.num { text-align: right; }
table.sheet td.error { color: #b91c1c; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
.section { border: 0.8pt solid #c7d2fe; border-radius: 1.5mm; padding: 2mm 3mm; margin: 3mm 0; }
.section-head { font-weight: bold; color: #3730a3; margin-bottom: 1mm; }
.section-head .origin { font-weight: normal; color: #6b7280; font-size: 8pt; margin-left: 2mm; }
.files-head { font-weight: bold; margin: 4mm 0 1mm; border-top: 0.6pt solid #e5e7eb; padding-top: 2mm; }
figure { margin: 2mm 0; break-inside: avoid; }
figcaption { font-size: 7.5pt; color: #6b7280; }
.file { margin: 1.5mm 0; padding: 1.5mm 2mm; background: #f9fafb; border: 0.6pt solid #e5e7eb; border-radius: 1mm; }
.file .what { color: #6b7280; font-size: 8pt; }
.repeat { color: #6b7280; }
.pdf-page { break-before: page; break-after: page; height: 10mm; }
.pdf-caption { font-size: 8pt; color: #6b7280; border-bottom: 0.6pt solid #e5e7eb; padding-bottom: 1mm; bookmark-level: none; }
table.csv { border-collapse: collapse; font-size: 7.5pt; margin: 1mm 0; }
table.csv td { border: 0.5pt solid #e5e7eb; padding: 0.6mm 1.2mm; }
.gel { break-inside: avoid; margin: 3mm 0; }
table.gel-layout { width: 100%; border-collapse: collapse; }
td.gel-photo { width: 60%; vertical-align: top; padding-right: 4mm; }
td.gel-photo img { width: 100%; }
td.gel-side { vertical-align: top; }
td.lane { text-align: center; font-weight: bold; width: 10mm; }
"""


class _Builder:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.files: Dict[str, dict] = {}            # attachment id -> what WeasyPrint fetches
        self.placements: List[tuple] = []           # (anchor id, attachment id, page index in it)
        self.readers: Dict[str, object] = {}
        self.generated: Dict[str, bytes] = {}       # pictures made here (gels with their numbers)
        self.counter = 0
        self.mentioned = set()

    # --- attachments -------------------------------------------------------------

    def _file(self, att_id: str) -> Optional[dict]:
        if att_id not in self.files:
            self.files[att_id] = exporting.load(self.ctx.person, att_id)
        return self.files[att_id]

    @staticmethod
    def url(f: dict) -> str:
        # Its name last: WeasyPrint names an embedded file after the end of its address.
        return f'{ATTACHMENT_URL}{f["id"]}/{quote(f["filename"])}'

    def image(self, att_id: str, alt: str = '') -> str:
        f = self._file(att_id)
        if not f or f['mime'] not in exporting.IMAGE_TYPES:
            return f'<span class="empty">[picture not available: {esc(alt or "removed")}]</span>'
        return f'<img src="{esc(self.url(f))}" alt="{esc(alt or f["filename"])}">'

    def embedded(self, f: dict) -> str:
        return (f'<a rel="attachment" href="{esc(self.url(f))}" title="Open it from the PDF">'
                f'📎 {esc(f["filename"])}</a>')

    def shown(self, att_id: str) -> str:
        """A file as it goes into the document below its mention: its pages, its text, or a note it is embedded."""
        f = self._file(att_id)
        if not f:
            return '<p class="file empty">A file that is no longer available.</p>'
        what = f'{exporting.kind_name(f["mime"], f["filename"])}, {exporting.size_label(f["size"])}'
        if f['mime'] in exporting.IMAGE_TYPES:
            return f'<figure>{self.image(att_id)}<figcaption>{esc(f["filename"])}</figcaption></figure>'
        if f['mime'] == 'application/pdf':
            reader = self.readers.get(att_id) or exporting.pdf_reader(f['data'])
            if reader is None:
                return (f'<p class="file">{self.embedded(f)} <span class="what">{esc(what)} · its pages could not be '
                        'read (damaged, or locked with a password); it is embedded in this PDF</span></p>')
            self.readers[att_id] = reader
            n = len(reader.pages)
            shown = min(n, MAX_PDF_PAGES)
            parts = [f'<p class="file">{self.embedded(f)} <span class="what">{esc(what)} · '
                     f'{n} page{"s" if n != 1 else ""}, shown on the next {"page" if shown == 1 else f"{shown} pages"}'
                     f'{f" (the first {shown}; all of it is embedded)" if shown < n else ""}</span></p>']
            for k in range(shown):
                self.counter += 1
                anchor = f'pdfpage-{self.counter}'
                self.placements.append((anchor, att_id, k))
                parts.append(f'<div class="pdf-page"><div class="pdf-caption" id="{anchor}">{esc(f["filename"])} · '
                             f'page {k + 1} of {n}</div></div>')
            return ''.join(parts)
        line = f'<p class="file">{self.embedded(f)} <span class="what">{esc(what)} · embedded in this PDF</span></p>'
        if exporting.is_text(f['mime']):
            text = exporting.text_of(f['data'])
            if f['mime'] in exporting.TABLE_TYPES or f['filename'].lower().endswith(('.csv', '.tsv')):
                return line + self._csv(text, '\t' if f['mime'].endswith('tab-separated-values')
                                        or f['filename'].lower().endswith('.tsv') else None)
            lines = text.splitlines()
            more = f'\n… {len(lines) - MAX_TEXT_LINES} more lines in the embedded file' if len(lines) > MAX_TEXT_LINES else ''
            return line + f'<pre>{esc(chr(10).join(lines[:MAX_TEXT_LINES]) + more)}</pre>'
        return line

    def _csv(self, text: str, delimiter: Optional[str]) -> str:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=delimiter or ',;\t') if not delimiter else None
        except csv.Error:
            dialect = None
        rows = list(csv.reader(io.StringIO(text), dialect=dialect) if dialect else
                    csv.reader(io.StringIO(text), delimiter=delimiter or ','))
        body = ''.join('<tr>' + ''.join(f'<td>{esc(c)}</td>' for c in r) + '</tr>' for r in rows[:MAX_TABLE_ROWS])
        more = f'<p class="what">… {len(rows) - MAX_TABLE_ROWS} more rows in the embedded file</p>' if len(rows) > MAX_TABLE_ROWS else ''
        return f'<table class="csv">{body}</table>{more}'

    # --- blocks ---------------------------------------------------------------------

    def text(self, block: dict) -> str:
        tree = richtext.parse(block.get('html') or '')
        after: List[str] = []
        for node in list(tree.walk()):
            if node.tag == 'img':
                att = node.attrs.get('data-attachment')
                if att:
                    self.mentioned.add(att)
                node.tag, node.attrs = 'span', {}
                node.children = [_Raw(self.image(att, '') if att else '')]
            elif node.tag == 'a':
                attrs = node.attrs
                if attrs.get('data-attachment'):
                    f = self._file(attrs['data-attachment'])
                    node.attrs = {'href': f'#att-{attrs["data-attachment"]}'} if f else {}
                    if f:
                        node.children = [f'📎 {f["filename"]}']
                        after.append(attrs['data-attachment'])
                    continue
                href = (self.ctx.note_link(attrs['data-note']) if attrs.get('data-note') else
                        self.ctx.plasmid_link(attrs['data-plasmid']) if attrs.get('data-plasmid') else
                        self.ctx.seed_link(attrs['data-seed']) if attrs.get('data-seed') else
                        self.ctx.stock_link(attrs['data-stock']) if attrs.get('data-stock') else
                        attrs.get('href') if (attrs.get('href') or '').startswith(('http://', 'https://', 'mailto:')) else None)
                node.attrs = {'href': href} if href else {}
            else:
                node.attrs = {k: v for k, v in node.attrs.items() if k == 'class'}
        out = f'<div class="text">{_html(tree)}</div>'
        for att in dict.fromkeys(after):
            self.mentioned.add(att)
            out += f'<div id="att-{att}">{self.shown(att)}</div>'
        return out

    def steps(self, block: dict) -> str:
        items = ''.join(
            f'<li><span class="box">{"☑" if i.get("by") else "☐"}</span> {esc(i.get("text") or "")}'
            + (f'<span class="tick">✓ {esc(i["by"])} · {esc(self.ctx.when(i.get("at")))}</span>' if i.get('by') else '')
            + '</li>' for i in block.get('items') or [])
        title = f'<div class="block-title">{esc(block["title"])}</div>' if block.get('title') else ''
        return f'<div class="steps">{title}<ol>{items}</ol></div>'

    def table(self, block: dict) -> str:
        columns = block.get('columns') or []
        rows = block.get('rows') or []
        computed = sheet.compute(block)
        head = ''.join(
            f'<th><span class="letter">{sheet.col_name(c)}</span>{esc(col.get("name") or "")}'
            + (f' <span class="unit">({esc(col["unit"])})</span>' if col.get('unit') else '')
            + (f'<span class="formula">{esc(col["formula"])}</span>' if col.get('kind') == 'formula' and col.get('formula') else '')
            + ('<span class="formula">filled in on the day</span>' if col.get('kind') == 'fill' else '')
            + '</th>' for c, col in enumerate(columns))
        body = []
        for r, row in enumerate(rows):
            cells = []
            for c, col in enumerate(columns):
                raw = (row.get('cells') or [None] * len(columns))[c] if c < len(row.get('cells') or []) else None
                shown = computed[r][c]
                if col.get('kind') == 'check':
                    cells.append('<td><span class="box">☑</span>' + (
                        f'<span class="tick">{esc(raw["by"])} · {esc(self.ctx.when(raw.get("at")))}</span>'
                        if isinstance(raw, dict) and raw.get('by') else '') + '</td>' if raw else '<td><span class="box">☐</span></td>')
                    continue
                text = raw if col.get('kind') == 'text' and not str(raw or '').startswith('=') else shown['display']
                css = 'error' if shown.get('error') else ('num' if sheet._is_num(shown.get('value')) else '')
                cells.append(f'<td class="{css}">{esc(str(text or ""))}</td>')
            body.append('<tr>' + ''.join(cells) + '</tr>')
        title = f'<div class="block-title">{esc(block["title"])}</div>' if block.get('title') else ''
        scale = block.get('scale')
        scale_line = (f'<div class="scale">{esc(scale.get("label") or "Reactions")}: '
                      f'{esc(sheet.show(sheet._number(scale.get("value"), 0)))}</div>' if scale else '')
        return f'{title}{scale_line}<table class="sheet"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    def gel(self, block: dict) -> str:
        att = block.get('attachment') or ''
        lanes = content.numbered(block)
        first = 'Lane' if block.get('order') != 'clicks' else 'No.'
        second = 'Sample' if block.get('order') != 'clicks' else 'Label'
        self.mentioned.add(att)
        f = self._file(att) if att else None
        picture = exporting.gel_picture(f['data'], lanes, ordered=True) if f and f['mime'] in exporting.IMAGE_TYPES else None
        if picture:
            key = f'gel{len(self.generated) + 1}'
            self.generated[key] = picture
            image = f'<img src="{ATTACHMENT_URL}{key}/gel.png" alt="{esc(block.get("title") or "Gel")}">'
        else:
            image = '<span class="empty">[photo not available]</span>'
        rows = ''.join(f'<tr><td class="lane">{n}</td><td>{esc(lane.get("label") or "")}</td>'
                       f'<td>{esc(lane.get("note") or "")}</td></tr>' for n, lane in enumerate(lanes, 1))
        table = (f'<table class="sheet"><thead><tr><th>{first}</th><th>{second}</th><th>Notes</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>' if lanes else '<p class="empty">Nothing numbered.</p>')
        title = f'<div class="block-title">{esc(block["title"])}</div>' if block.get('title') else ''
        return f'<div class="gel">{title}<table class="gel-layout"><tr><td class="gel-photo">{image}</td><td class="gel-side">{table}</td></tr></table></div>'

    def section(self, block: dict) -> str:
        src = block.get('source') or {}
        origin = (f'Protocol{f" · version {src["version"]}" if src.get("version") else ""}'
                  if src.get('kind') == 'protocol' else 'From the MoClo Library Tool' if src.get('kind') == 'moclo-reaction' else '')
        if src.get('kind') == 'protocol' and src.get('id'):
            origin = f'<a href="{esc(self.ctx.note_link(src["id"]))}">{esc(origin)}</a>'
        else:
            origin = esc(origin)
        inner = ''.join(self.block(b) for b in block.get('blocks') or [])
        return (f'<div class="section"><div class="section-head">{esc(block.get("title") or "")}'
                f'<span class="origin">{origin}</span></div>{inner}</div>')

    def block(self, block: dict) -> str:
        kind = block.get('type')
        if kind == 'text':
            return self.text(block)
        if kind == 'steps':
            return self.steps(block)
        if kind == 'table':
            return self.table(block)
        if kind == 'section':
            return self.section(block)
        if kind == 'gel':
            return self.gel(block)
        return ''

    # --- notes ------------------------------------------------------------------------

    def entry(self, e: Entry, breaks: bool) -> str:
        ctx = self.ctx
        self.mentioned = set()
        meta = [exporting.TYPE_NAMES.get(e.type, e.type)]
        if e.where:
            meta.append(e.where)
        if e.created_by:
            meta.append(f'created by {e.created_by} · {ctx.when(e.created_at)}')
        if e.updated_by and (e.updated_by != e.created_by or e.updated_at != e.created_at):
            meta.append(f'last saved by {e.updated_by} · {ctx.when(e.updated_at)}')
        if not e.created_by:
            meta.append('supplied with the Lab Notebook')
        meta.append(f'version {e.revision}')
        head = (f'<section class="note depth-{min(e.depth, 4)}{" break" if breaks else ""}" id="n-{e.id}">'
                f'<h1 class="note-title" style="bookmark-level: {min(e.depth + 1, 6)}">{esc(e.title)}</h1>'
                f'<div class="note-meta">{esc(" · ".join(meta))}</div>')
        if e.repeat_of:
            return head + (f'<p class="repeat">This page is in more than one place; it is printed '
                           f'<a href="#n-{e.repeat_of}">here</a>.</p></section>')
        labels = f'<div class="labels">{esc("  ".join(e.labels))}</div>' if e.labels else ''
        body = ''.join(self.block(b) for b in e.content)
        if not body.strip() and not e.has_children and e.type not in ('year', 'month'):
            body = '<p class="empty">Nothing written here.</p>'
        files = [a for a in e.attachments if not a['deleted_at'] and a['id'] not in self.mentioned]
        if files:
            body += '<div class="files-head">Files</div>' + ''.join(
                f'<div id="att-{a["id"]}">{self.shown(a["id"])}</div>' for a in files)
        return head + labels + body + '</section>'

    def document(self, step: Callable) -> str:
        ctx = self.ctx
        person = ctx.person
        pages = sum(1 for e in ctx.entries if not e.repeat_of)
        files = sum(len([a for a in e.attachments if not a['deleted_at']]) for e in ctx.entries)
        cover = (f'<div class="cover"><h1 class="doc-title">{esc(ctx.title)}</h1>'
                 f'<div class="doc-stamp">{esc(ctx.stamp)} by {esc(person.username)}</div>'
                 f'<div class="sub">{esc(ctx.subtitle)}</div><table>'
                 f'<tr><td>Exported by</td><td>{esc(person.username)}{f" ({esc(person.lab)})" if person.lab else ""}</td></tr>'
                 f'<tr><td>On</td><td>{esc(ctx.stamp)}</td></tr>'
                 f'<tr><td>Contains</td><td>{pages} page{"s" if pages != 1 else ""}, {files} file{"s" if files != 1 else ""}</td></tr>'
                 f'<tr><td>From</td><td>the Lab Notebook of the Gardiner Lab suite. Every version of each page is '
                 f'kept in the notebook; this is the current one.</td></tr></table></div>')
        toc = ''
        if len(ctx.entries) > 1:
            toc = '<div class="toc"><h2>Contents</h2><ol>' + ''.join(
                f'<li class="t-{e.type}" style="padding-left: {min(e.depth, 6) * 4}mm">'
                f'<a href="#n-{e.id}">{esc(e.title)}</a></li>' for e in ctx.entries if not e.repeat_of) + '</ol></div>'
        parts = []
        previous_had_content = False
        for i, e in enumerate(ctx.entries):
            # Each page starts a page of its own, unless what came before was only a heading above it.
            parts.append(self.entry(e, breaks=i > 0 and previous_had_content))
            previous_had_content = bool(e.content or e.attachments) or e.type not in ('year', 'month', 'folder')
            step(i + 1)
        return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(ctx.title)}</title>'
                f'<style>{CSS}</style></head><body>{cover}{toc}{"".join(parts)}</body></html>')


class _Raw(str):
    """HTML written here, put into a text's tree as it is."""


def _html(node) -> str:
    if isinstance(node, _Raw):
        return str(node)
    if isinstance(node, str):
        return esc(node, quote=False)
    inner = ''.join(_html(c) for c in node.children)
    if node.tag == 'root':
        return inner
    attrs = ''.join(f' {k}="{esc(v)}"' for k, v in node.attrs.items() if v is not None)
    if node.tag in richtext.VOID:
        return f'<{node.tag}{attrs}>'
    return f'<{node.tag}{attrs}>{inner}</{node.tag}>'


def render(ctx: Context, step: Callable) -> bytes:
    from weasyprint import HTML

    builder = _Builder(ctx)
    source = builder.document(step)
    step(len(ctx.entries), 'Laying out the pages')

    def fetch(url: str, *args, **kwargs):
        if url.startswith(ATTACHMENT_URL):
            key = unquote(url[len(ATTACHMENT_URL):].split('/')[0])
            if key in builder.generated:
                return {'string': builder.generated[key], 'mime_type': 'image/png', 'filename': 'gel.png'}
            f = builder._file(key)
            if f:
                return {'string': f['data'], 'mime_type': f['mime'], 'filename': f['filename']}
        raise ValueError(f'Not fetched: {url}')        # only the notebook's own files

    document = HTML(string=source, url_fetcher=fetch, base_url=ATTACHMENT_URL).render()
    where = {}
    for index, page in enumerate(document.pages):
        for anchor in page.anchors:
            where.setdefault(anchor, index)
    data = document.write_pdf()
    if not builder.placements:
        return data
    step(len(ctx.entries), 'Putting in the attached PDFs')
    return _place_pages(data, builder, where)


def _place_pages(data: bytes, builder: _Builder, where: Dict[str, int]) -> bytes:
    """Draw each attached PDF's page onto the page saved for it."""
    from pypdf import PdfReader, PdfWriter, Transformation

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    for anchor, att_id, k in builder.placements:
        index = where.get(anchor)
        if index is None or index >= len(writer.pages):
            continue
        source = builder.readers[att_id].pages[k]
        try:
            source.transfer_rotation_to_content()
            box = source.mediabox
            w, h = float(box.width), float(box.height)
            if w <= 0 or h <= 0:
                continue
            room_w = PAGE_W - INSET_LEFT - INSET_RIGHT
            room_h = PAGE_H - INSET_TOP - INSET_BOTTOM
            s = min(room_w / w, room_h / h)
            tx = INSET_LEFT + (room_w - w * s) / 2 - float(box.left) * s
            ty = INSET_BOTTOM + (room_h - h * s) - float(box.bottom) * s
            writer.pages[index].merge_transformed_page(source, Transformation().scale(s, s).translate(tx, ty))
        except Exception:      # one unreadable page leaves its caption, and the file is still embedded
            continue
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
