"""Walidacja pliku wejściowego: nazwa, rozszerzenie, rozmiar, pusty plik, zgodność magic-bytes z rozszerzeniem.

Pliki nie są zapisywane na dysk.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from ..types.report import ApiErrorCode
from ..types.source import SourceFormat


class IngestError(Exception):
    def __init__(self, code: ApiErrorCode, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code: ApiErrorCode = code
        self.message = message
        self.status = status


EXT_FORMAT: dict[str, SourceFormat] = {
    "pdf": "pdf",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "tif": "image",
    "tiff": "image",
    "docx": "docx",
    "doc": "doc",
    "xlsx": "xlsx",
    "ods": "ods",
}
ALLOWED_EXTENSIONS = tuple(EXT_FORMAT)

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_BAD_NAME = re.compile(r'[\x00-\x1f<>:"|?*\\/]|^\.|\.\.')


def sniff(data: bytes) -> str:
    """Wykrywa typ po magic-bytes (i strukturze ZIP dla OOXML/ODF)."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data.startswith(_OLE):
        return "ole"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
                    return "zip-bomb"
                names = {i.filename for i in infos}
                if "mimetype" in names:
                    with z.open("mimetype") as fh:
                        mt = fh.read(128).decode("ascii", "replace").strip()
                    if mt == "application/vnd.oasis.opendocument.spreadsheet":
                        return "ods"
                    return "odf-other"
                if "word/document.xml" in names:
                    return "docx"
                if "xl/workbook.xml" in names:
                    return "xlsx"
        except zipfile.BadZipFile:
            return "unknown"
        return "zip"
    return "unknown"


MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024  # ochrona przed zip bomb (DOCX/XLSX/ODS)

_EXT_SNIFF: dict[str, set[str]] = {
    "pdf": {"pdf"},
    "png": {"png"},
    "jpg": {"jpeg"},
    "jpeg": {"jpeg"},
    "tif": {"tiff"},
    "tiff": {"tiff"},
    "docx": {"docx"},
    "xlsx": {"xlsx"},
    "ods": {"ods"},
    "doc": {"ole"},
}


@dataclass(frozen=True)
class IngestedFile:
    filename: str
    ext: str
    format: SourceFormat
    detected: str
    data: bytes


def ingest(filename: str | None, data: bytes, max_bytes: int) -> IngestedFile:
    name = unicodedata.normalize("NFC", (filename or "").strip())
    if not name or len(name) > 255 or _BAD_NAME.search(name):
        raise IngestError("BAD_FILENAME", "Niepoprawna nazwa pliku.")
    ext = name.rsplit(".", 1)[1].lower() if "." in name[1:] else ""
    fmt = EXT_FORMAT.get(ext)
    if fmt is None:
        raise IngestError(
            "BAD_EXTENSION", f'Nieobsługiwane rozszerzenie ".{ext}". Dozwolone: {", ".join(ALLOWED_EXTENSIONS)}.', 415
        )
    if not data:
        raise IngestError("EMPTY", "Plik jest pusty.")
    if len(data) > max_bytes:
        raise IngestError("FILE_TOO_LARGE", f"Plik przekracza limit {max_bytes // (1024 * 1024)} MB.", 413)
    detected = sniff(data)
    if detected not in _EXT_SNIFF[ext]:
        raise IngestError("MIME_MISMATCH", f'Zawartość pliku ({detected}) nie pasuje do rozszerzenia ".{ext}".', 415)
    return IngestedFile(filename=name, ext=ext, format=fmt, detected=detected, data=data)
