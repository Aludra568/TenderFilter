"""Текст из вложений закупки: проект контракта, ТЗ, обоснование НМЦК (.docx, .pdf, .txt, .html, .xml).

DOCX разбирается как ZIP с XML без сторонних библиотек, PDF — через pypdf (только текстовый слой;
сканы без OCR дадут пустой текст, и это честно показывается пользователю).
"""

import io
import re
import zipfile

from lxml import etree

MAX_CHARS = 2_000_000


class DocumentError(ValueError):
    pass


def _docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise DocumentError("Файл .docx повреждён или это не документ Word") from exc
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        paragraphs.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(paragraphs)


def _pdf(content: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:300])
    except (PdfReadError, ValueError, KeyError) as exc:
        raise DocumentError("PDF не читается") from exc


def _decode(content: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def extract_text(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        text = _docx(content)
    elif name.endswith(".pdf") or content[:5] == b"%PDF-":
        text = _pdf(content)
    elif name.endswith((".html", ".htm", ".xml")):
        text = re.sub(r"<[^>]+>", " ", _decode(content))
    elif name.endswith((".txt", ".md", ".csv")):
        text = _decode(content)
    elif name.endswith(".doc") or name.endswith(".rtf"):
        raise DocumentError("Формат .doc/.rtf не поддерживается — сохраните документ как .docx или .pdf")
    else:
        raise DocumentError(f"Неизвестный формат документа: {filename}")
    return text[:MAX_CHARS]
