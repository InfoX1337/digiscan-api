"""Walidacja pliku wejściowego: nazwa, rozszerzenie, rozmiar, pusty plik, zgodność zawartości (magic bytes)
i deklarowanego typu MIME (Content-Type) z rozszerzeniem.

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
    "docx": "docx",
    "doc": "doc",
    "xlsx": "xlsx",
    "ods": "ods",
}
ALLOWED_EXTENSIONS = tuple(EXT_FORMAT)

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Zakazane znaki wg wymagań COI: ; : > < / \ | ' * % $ (oraz znaki sterujące, " ? i ścieżki względne).
_BAD_NAME = re.compile(r"""[\x00-\x1f;:<>/\\|'*%$"?]|^\.|\.\.""")
MAX_NAME_LEN = 250
_WORD_STREAM = "WordDocument".encode("utf-16-le")  # nazwa strumienia w katalogu OLE dokumentu Word


def sniff(data: bytes) -> str:
    """Wykrywa typ po magic-bytes (i strukturze ZIP dla OOXML/ODF)."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(_OLE):
        return "doc" if _WORD_STREAM in data else "ole-other"
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

# Ta sama rodzina formatów przy innym rozszerzeniu (np. DOCX zapisany jako .doc, PNG jako .jpg) – częste
# w realnych plikach urzędów. Format przetwarzania wynika wtedy z zawartości, nie z rozszerzenia.
_EXT_SNIFF: dict[str, set[str]] = {
    "pdf": {"pdf"},
    "png": {"png", "jpeg"},
    "jpg": {"jpeg", "png"},
    "jpeg": {"jpeg", "png"},
    "docx": {"docx", "doc"},
    "xlsx": {"xlsx", "ods"},
    "ods": {"ods", "xlsx"},
    "doc": {"doc", "docx"},
}
_SNIFF_FORMAT: dict[str, SourceFormat] = {
    "pdf": "pdf",
    "png": "image",
    "jpeg": "image",
    "docx": "docx",
    "doc": "doc",
    "xlsx": "xlsx",
    "ods": "ods",
}

# Deklarowany Content-Type: typy ogólne (brak / octet-stream) dopuszczamy, bo przeglądarki i klienci HTTP
# często ich używają; konkretny typ musi pasować do rozszerzenia.
_GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream", "application/x-download"}
_ZIP_MIME = {"application/zip", "application/x-zip-compressed"}
_EXT_MIME: dict[str, set[str]] = {
    "pdf": {"application/pdf", "application/x-pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg", "image/pjpeg"},
    "jpeg": {"image/jpeg", "image/pjpeg"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", *_ZIP_MIME},
    "doc": {"application/msword", "application/x-msword", "application/x-ole-storage", "application/x-cfb"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", *_ZIP_MIME},
    "ods": {"application/vnd.oasis.opendocument.spreadsheet", *_ZIP_MIME},
}


@dataclass(frozen=True)
class IngestedFile:
    filename: str
    ext: str
    format: SourceFormat
    detected: str
    data: bytes


def ingest(filename: str | None, data: bytes, max_bytes: int, content_type: str | None = None) -> IngestedFile:
    name = unicodedata.normalize("NFC", (filename or "").strip())
    if not name or len(name) > MAX_NAME_LEN or _BAD_NAME.search(name):
        raise IngestError(
            "BAD_FILENAME",
            f"Niepoprawna nazwa pliku (maks. {MAX_NAME_LEN} znaków, bez znaków ; : > < / \\ | ' * % $).",
        )
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
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared not in _GENERIC_MIME and declared not in _EXT_MIME[ext]:
        raise IngestError("MIME_MISMATCH", f'Typ MIME "{declared}" nie pasuje do rozszerzenia ".{ext}".', 415)
    detected = sniff(data)
    if detected not in _EXT_SNIFF[ext]:
        raise IngestError("MIME_MISMATCH", f'Zawartość pliku ({detected}) nie pasuje do rozszerzenia ".{ext}".', 415)
    return IngestedFile(filename=name, ext=ext, format=_SNIFF_FORMAT.get(detected, fmt), detected=detected, data=data)
