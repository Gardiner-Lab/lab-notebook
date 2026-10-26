"""
Opening a file in the browser without downloading it.

Word, PowerPoint and Excel files (old and new formats, OpenDocument, RTF and
CSV too) are turned into a PDF by the suite's converter, a LibreOffice service
inside the suite with no way out to the internet, and shown in the browser's
PDF viewer. A file is converted once: the PDF is kept beside it, by the file's
checksum. Text files (notes, FASTA, GenBank) are shown as plain text.

Without a converter (CONVERTER_URL unset, as outside the suite) office files
download as before.
"""

import mimetypes
import os
import secrets
import urllib.error
import urllib.request
from typing import Optional

from app.db import connect

TIMEOUT = 120
CONVERTED_KINDS = ('word', 'powerpoint', 'excel')
TEXT_KINDS = ('text', 'sequence')


class ViewerError(Exception):
    """The file could not be shown here; it can still be downloaded."""


def converter() -> str:
    return os.environ.get('CONVERTER_URL', '').rstrip('/')


def converted(kind: str) -> bool:
    return kind in CONVERTED_KINDS and bool(converter())


def as_text(kind: str, data: bytes) -> Optional[str]:
    """A text file's contents, or None: binary files (a SnapGene .dna, say) are not text."""
    if kind not in TEXT_KINDS:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def as_pdf(sha256: str, filename: str, mime: str, data: bytes) -> bytes:
    """The file as a PDF: the one kept from before, or converted now and kept."""
    with connect() as conn:
        row = conn.execute('SELECT pdf FROM file_views WHERE sha256 = ?', (sha256,)).fetchone()
    if row is not None:
        return bytes(row['pdf'])
    pdf = _convert(filename, mime, data)
    with connect() as conn:
        conn.execute('INSERT OR REPLACE INTO file_views (sha256, pdf) VALUES (?, ?)', (sha256, pdf))
    return pdf


def _convert(filename: str, mime: str, data: bytes) -> bytes:
    url = converter()
    if not url:
        raise ViewerError('No converter in this installation')
    # LibreOffice reads the format from the name's ending, so it must have one.
    if '.' not in filename:
        filename += mimetypes.guess_extension(mime) or ''
    name = filename.replace('"', '_').replace('\r', '_').replace('\n', '_')
    boundary = secrets.token_hex(16)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    request = urllib.request.Request(f'{url}/forms/libreoffice/convert', data=body, method='POST',
                                     headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            pdf = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ViewerError(f'The converter could not read it ({exc})') from exc
    if not pdf.startswith(b'%PDF-'):
        raise ViewerError('The converter did not make a PDF of it')
    return pdf
