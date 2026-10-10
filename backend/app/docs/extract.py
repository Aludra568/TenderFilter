"""Текст из вложений закупки: проект контракта, ТЗ (.docx, .doc, .pdf, .zip, .txt, .html, .xml).

DOCX разбирается как ZIP с XML без сторонних библиотек, старый .doc — через olefile, PDF — через pypdf
(только текстовый слой; сканы без OCR дадут пустой текст, и это честно показывается пользователю),
архивы .zip — рекурсивно. Форматы подобраны по корпусу ЕИС: из 186 проектов контрактов
46% — .docx, 34% — .pdf, 11% — .doc, 7% — .zip.
"""

import io
import re
import zipfile
from dataclasses import dataclass

from lxml import etree

MAX_CHARS = 2_000_000
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
# Символы UTF-16LE в потоке .doc: ASCII (байт 0x00 вторым), кириллица (0x04), кавычки «», тире.
_DOC_RUN = re.compile(rb"(?:[\x09\x0a\x0d\x20-\x7e]\x00|[\x01-\x5f]\x04|\xab\x00|\xbb\x00|[\x13\x14\x1c\x1d]\x20){12,}")


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


def _doc(content: bytes) -> str:
    """Старый Word (.doc): текст лежит в потоке WordDocument, русский — в UTF-16LE.

    Для поиска условий правилами полный разбор таблицы кусков не нужен: берём длинные
    последовательности символов UTF-16LE.
    """
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(content))
        stream = ole.openstream("WordDocument").read()
    except (OSError, ValueError) as exc:
        raise DocumentError("Файл .doc повреждён") from exc
    text = "\n".join(r.decode("utf-16-le", errors="ignore") for r in _DOC_RUN.findall(stream))
    return text.replace("\r", "\n")


def _zip(content: bytes, depth: int) -> str:
    """Архив вложений: разбираем всё, что внутри умеем читать."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise DocumentError("Архив повреждён") from exc
    parts = []
    for info in zf.infolist()[:50]:
        if info.is_dir() or info.file_size > 50 * 2**20:
            continue
        name = info.filename
        if not info.flag_bits & 0x800:  # имя не в UTF-8 — архиватор Windows с кодировкой cp866
            try:
                name = name.encode("cp437").decode("cp866")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        try:
            parts.append(extract_text(name, zf.read(info), depth + 1))
        except DocumentError:
            continue
    if not parts:
        raise DocumentError("В архиве нет читаемых документов")
    return "\n".join(parts)


def _decode(content: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


IMAGE_MAGIC = (bytes.fromhex("89504e47"), bytes.fromhex("49492a00"), bytes.fromhex("4d4d002a"))  # PNG, TIFF
JPEG_MAGIC = bytes.fromhex("ffd8ff")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif")


@dataclass
class Extracted:
    name: str
    text: str
    method: str  # text | ocr


def _ocr_or_error(fn, content: bytes) -> str:
    from app.docs import ocr

    try:
        return fn(content)
    except ocr.OcrUnavailable as exc:
        raise DocumentError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — битая картинка/PDF
        raise DocumentError("Скан не удалось распознать") from exc


def _docx_images(content: bytes) -> list[bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return [zf.read(n) for n in zf.namelist()
                if n.startswith("word/media/") and n.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"))][:20]


def extract_document(filename: str, content: bytes, depth: int = 0) -> Extracted:
    """Текст документа любого формата; сканы — через OCR. method показывает, как получен текст."""
    from app.docs import ocr

    name = (filename or "").lower()
    method = "text"
    if name.endswith(IMAGE_EXT) or content[:4] in IMAGE_MAGIC or content[:3] == JPEG_MAGIC:
        text, method = _ocr_or_error(ocr.image_text, content), "ocr"
    elif name.endswith(".zip") or (content[:2] == b"PK" and not name.endswith((".docx", ".xlsx"))):
        if depth > 1:
            raise DocumentError("Слишком глубоко вложенный архив")
        text = _zip(content, depth)
    elif name.endswith(".docx"):
        text = _docx(content)
        if len(text.strip()) < 200:  # в Word вставлены сканы страниц
            images = _docx_images(content)
            if images:
                text, method = "\n".join(_ocr_or_error(ocr.image_text, img) for img in images), "ocr"
    elif name.endswith(".pdf") or content[:5] == b"%PDF-":
        text = _pdf(content)
        if len(text.strip()) < 200:  # PDF без текстового слоя — скан
            text, method = _ocr_or_error(ocr.pdf_text, content), "ocr"
    elif name.endswith(".doc") or content[:8] == OLE_MAGIC:
        text = _doc(content)
    elif name.endswith((".html", ".htm", ".xml")):
        text = re.sub(r"<[^>]+>", " ", _decode(content))
    elif name.endswith((".txt", ".md", ".csv")):
        text = _decode(content)
    elif name.endswith(".rtf"):
        raise DocumentError("Формат .rtf не поддерживается — сохраните документ как .docx или .pdf")
    else:
        raise DocumentError(f"Неизвестный формат документа: {filename}")
    return Extracted(filename, text[:MAX_CHARS], method)


def extract_text(filename: str, content: bytes, depth: int = 0) -> str:
    return extract_document(filename, content, depth).text
