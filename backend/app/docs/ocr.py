"""Распознавание сканов: Tesseract (русский + английский), без облачных сервисов.

Сканы встречаются постоянно: лицензии, выписки СРО, сертификаты, подписанные проекты контрактов.
PDF без текстового слоя рендерится постранично (pypdfium2), картинки и сканы внутри .docx
распознаются напрямую. Tesseract — системная программа: в Docker-образ ставится автоматически,
локально — отдельно (см. README). Нет Tesseract — честная ошибка «скан не распознан», без выдумок.
"""

import io
from functools import lru_cache

MAX_PAGES = 20


class OcrUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return "rus" in pytesseract.get_languages(config="")
    except Exception:  # noqa: BLE001 — нет программы, нет русского словаря и т. п.
        return False


def _ocr(image) -> str:
    import pytesseract

    if not available():
        raise OcrUnavailable("Распознавание сканов недоступно: не установлен Tesseract с русским языком")
    gray = image.convert("L")
    if gray.width < 1500:  # мелкий скан — увеличиваем, Tesseract любит ~300 dpi
        k = 1500 / gray.width
        gray = gray.resize((int(gray.width * k), int(gray.height * k)))
    return pytesseract.image_to_string(gray, lang="rus+eng", config="--psm 3")


def image_text(content: bytes) -> str:
    from PIL import Image, ImageSequence

    img = Image.open(io.BytesIO(content))
    pages = [frame.copy() for frame in ImageSequence.Iterator(img)][:MAX_PAGES]  # многостраничный TIFF
    return "\n".join(_ocr(p) for p in pages)


def pdf_text(content: bytes) -> str:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(content)
    parts = []
    for i in range(min(len(pdf), MAX_PAGES)):
        bitmap = pdf[i].render(scale=2.5)  # ≈ 180–200 dpi для A4
        parts.append(_ocr(bitmap.to_pil()))
    return "\n".join(parts)
