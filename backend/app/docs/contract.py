"""Разбор проекта контракта и ТЗ: условия оплаты и приёмки, аванс, пени и штрафы, марки без эквивалента.

Правила работают на тексте документа без нейросети. Каждая находка помечена стороной:
поставщику важен кассовый разрыв и жёсткость санкций, заказчику — нарушения 44-ФЗ,
из-за которых закупку обжалуют в ФАС. Нормы:
  • ч. 13.1 ст. 34 44-ФЗ — оплата не позднее 7 рабочих дней с даты подписания документа о приёмке;
  • ст. 94 44-ФЗ — документ о приёмке подписывается не позднее 20 рабочих дней;
  • ч. 7 ст. 34 44-ФЗ — пени поставщику: 1/300 ключевой ставки ЦБ от цены за каждый день просрочки;
  • ПП РФ № 1042 — штраф поставщику от 10% цены контракта (до 3 млн ₽) и меньше для дорогих контрактов;
  • п. 1 ч. 1 ст. 33 44-ФЗ — товарный знак в описании объекта закупки только со словами «или эквивалент».
Нормы указаны в редакции, действовавшей на момент разработки; перед защитой их стоит сверить с юристом.
"""

import re

from app.domain import CanonicalTender, ContractTerms, FieldSource, Finding

BRANDS = [
    "HP", "Hewlett-Packard", "Canon", "Xerox", "Kyocera", "Brother", "Epson", "Ricoh", "Konica Minolta", "Pantum",
    "Samsung", "Lenovo", "Dell", "Asus", "Acer", "Apple", "iPhone", "iPad", "MacBook", "Huawei", "Xiaomi", "Honor",
    "Cisco", "Juniper", "MikroTik", "Intel", "AMD", "NVIDIA", "Microsoft", "Windows", "Oracle", "VMware",
    "Kingston", "Seagate", "Western Digital", "Toshiba", "Logitech", "Philips", "Panasonic", "Sony", "LG",
    "Bosch", "Makita", "Siemens", "Schneider Electric", "ABB", "Legrand", "Grundfos", "Danfoss", "Daikin",
    "Mercedes", "Toyota", "Volkswagen", "Hyundai", "Kia", "Skoda", "Lada", "КАМАЗ", "ГАЗ", "Kaspersky", "Касперск",
    "1С", "Astra Linux", "РЕД ОС", "Yandex", "Яндекс",
]
_BRAND_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")(?![\w-])")

_NUM_WORDS = re.compile(r"\(\s*[а-яё\s-]{2,40}\s*\)", re.I)
WORD_DAYS = {"одного": 1, "двух": 2, "трех": 3, "трёх": 3, "четырех": 4, "пяти": 5, "шести": 6, "семи": 7,
             "восьми": 8, "девяти": 9, "десяти": 10, "пятнадцати": 15, "двадцати": 20, "тридцати": 30,
             "пять": 5, "семь": 7, "десять": 10, "пятнадцать": 15, "двадцать": 20, "тридцать": 30}
_DAYS = re.compile(
    r"(?:в\s+течени[еи]|не\s+позднее|не\s+более(?:\s+чем)?(?:\s+в\s+течени[еи])?|не\s+превышающ\w*|"
    r"не\s+(?:может|должен|должна)\s+превышать|"
    r"в\s+срок(?:,?\s+не\s+более|,?\s+не\s+превышающ\w*|\s+до)?|до)\s+"
    r"(\d{1,3}|" + "|".join(WORD_DAYS) + r")\s*(рабоч\w*|календарн\w*)?\s*(?:дн|день|дня)", re.I)
_PAYMENT_BY_CUSTOMER = re.compile(
    r"оплат\w*\s+(?:\S+\s+){0,8}?(?:осуществля|производ|выполня|перечисля)|"
    r"(?:осуществля|производ)\w*\s+(?:\S+\s+){0,3}?оплат|заказчик\w*\s+оплачива|"
    r"оплата\s+(?:за|по\s+контракт|поставленн|выполненн|оказанн|указанн|товар|работ|услуг)|"
    r"срок\w*\s+оплат|оплатить\s+(?:\S+\s+){0,2}?(?:выполненн|поставленн|оказанн|товар|работ|услуг)|"
    r"расчет\w*\s+(?:\S+\s+){0,5}?(?:производ|осуществля)")
_PAYMENT_NOISE = re.compile(r"субподряд|соисполнител|штраф|пен[иья]\b|неусто|требовани\w*\s+(?:об|о)\s+уплат|нарушен\w*\s+срок")
_COMPAT = re.compile(r"совместим|работ\w*\s+(?:\S+\s+){0,3}?с\s+(?:операционн|по\b|програм)|поддерж\w*|"
                     r"под\s+управлением|операционн\w*\s+систем|для\s+(?:принтер|мфу|копир|аппарат)")
_PERCENT = re.compile(r"(\d{1,3}(?:[.,]\d{1,3})?)\s*%")


def _norm(text: str) -> str:
    text = text.replace("ё", "е").replace("Ё", "Е").replace("\xa0", " ")
    text = _NUM_WORDS.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+(?=[А-ЯA-Z0-9«])|\n+", _norm(text))
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _days(sentence: str) -> tuple[int, bool] | None:
    m = _DAYS.search(sentence)
    if not m:
        return None
    unit = (m.group(2) or "").lower()
    raw = m.group(1).lower()
    n = int(raw) if raw.isdigit() else WORD_DAYS[raw]
    return n, not unit.startswith("календар")  # по умолчанию в 44-ФЗ — рабочие дни


def _percents(sentence: str) -> list[float]:
    return [float(x.replace(",", ".")) for x in _PERCENT.findall(sentence) if float(x.replace(",", ".")) <= 100]


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def _short(s: str, limit: int = 220) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def analyze(text: str, law: str = "44-FZ", files: list[str] | None = None) -> ContractTerms:
    terms = ContractTerms(files=files or [], chars=len(text))
    f = terms.findings
    if len(text.strip()) < 200:
        f.append(Finding(code="no_text", side="both", severity="info", title="В документах почти нет текста",
                         detail="Возможно, это скан без текстового слоя — условия контракта не разобраны."))
        return terms
    is44 = law == "44-FZ"
    sents = sentences(text)
    pay_from_acceptance = False
    compat: list[str] = []

    for s in sents:
        low = s.lower()
        # Оплата заказчиком за товар (не аванс, не штрафы, не расчёты поставщика с субподрядчиками)
        advance_only = "аванс" in low and not re.search(r"приемк|по\s+факту|оставш|окончательн", low)
        if ("оплат" in low or "расчет" in low) and _PAYMENT_BY_CUSTOMER.search(low) and not _PAYMENT_NOISE.search(low) \
                and not advance_only:
            d = _days(s)
            # Приоритет — фразе, где срок оплаты считается от приёмки: это и есть основной срок.
            if d and (terms.payment_days is None or ("приемк" in low and not pay_from_acceptance)):
                terms.payment_days, terms.payment_working = d
                pay_q = s
                pay_from_acceptance = "приемк" in low
        # Приёмка
        if terms.acceptance_days is None and "приемк" in low and "оплат" not in low and \
                any(w in low for w in ("подписыва", "осуществля", "провод", "срок приемки")):
            d = _days(s)
            if d:
                terms.acceptance_days, terms.acceptance_working = d
                acc_q = s
        # Аванс
        if terms.advance_percent is None and "аванс" in low:
            if re.search(r"не\s+предусмотрен|не\s+выплачива|не\s+осуществля|без\s+аванс", low):
                terms.advance_percent = 0.0
            elif p := _percents(s):
                if p[0] <= 90:
                    terms.advance_percent = p[0]
                    adv_q = s
        # Пени поставщику
        if "пен" in low and any(w in low for w in ("поставщик", "подрядчик", "исполнител")) \
                and not re.search(r"(?:исполнени\w*|просрочк\w*)\s+заказчик", low):
            if re.search(r"1\s*/\s*300|одн\w*\s+трехсот", low):
                terms.supplier_penalty = terms.supplier_penalty or "standard"
            elif _percents(s) and re.search(r"кажд\w*\s+(?:календарн\w*\s+)?д(ень|н)", low):
                terms.supplier_penalty = "elevated"
                pen_q = s
        # Штрафы
        if "штраф" in low and (p := _percents(s)):
            if terms.max_fine_percent is None or max(p) > terms.max_fine_percent:
                terms.max_fine_percent = max(p)
                fine_q = s
        # Гарантия
        if terms.warranty_months is None and "гаранти" in low and "срок" in low:
            m = re.search(r"(\d{1,3})\s*(месяц|мес|год|лет)", low)
            if m:
                n = int(m.group(1))
                terms.warranty_months = n * 12 if m.group(2) in ("год", "лет") else n
        # Марки без «или эквивалент»
        for b in _BRAND_RE.findall(s):
            if "эквивалент" in low:
                continue
            if _COMPAT.search(low):
                # «работа с ОС Windows», «совместим с принтерами HP» — требование совместимости, а не марка товара
                if b not in compat:
                    compat.append(b)
                    compat_q = s
            elif b not in terms.brands_without_equivalent:
                terms.brands_without_equivalent.append(b)
                brand_q = s
        # «оригинальные картриджи», но не «оригинальная выписка из банка»
        if re.search(r"оригинальн\w*\s+(?:\S+\s+){0,2}?(?:расходн|картридж|тонер|запасн|запчаст|комплектующ|"
                     r"чернил|фотобарабан|деталей|детали|продукци)|(?:картридж|расходн|запасн|тонер)\w*\s+(?:\S+\s+){0,3}?"
                     r"(?:только\s+)?оригинальн", low) and not re.search(r"эквивалент|совместим", low):
            if not any(x.code == "original_only" for x in f):
                f.append(Finding(code="original_only", side="both", severity="warn",
                                 title="Требуются только оригинальные расходные материалы",
                                 detail="Без допуска совместимых аналогов круг поставщиков сужается; для заказчика — риск жалобы.",
                                 quote=_short(s), law="ст. 33 44-ФЗ"))

    # ---------- находки ----------
    if terms.payment_days is not None:
        n, working = terms.payment_days, terms.payment_working
        unit = "рабочих" if working else "календарных"
        too_long = is44 and ((working and n > 7) or (not working and n > 10))
        if too_long:
            f.append(Finding(code="payment_late", side="both", severity="high",
                             title=f"Оплата через {n} {unit} дней — дольше нормы 44-ФЗ",
                             detail="Поставщику — кассовый разрыв; заказчику — нарушение срока оплаты, риск жалобы и предписания ФАС.",
                             quote=_short(pay_q), law="ч. 13.1 ст. 34 44-ФЗ: не более 7 рабочих дней"))
        else:
            f.append(Finding(code="payment", side="supplier", severity="info",
                             title=f"Оплата в течение {n} {unit} дней", detail="Срок оплаты в пределах нормы.",
                             quote=_short(pay_q)))
    if terms.acceptance_days is not None and is44:
        n, working = terms.acceptance_days, terms.acceptance_working
        if (working and n > 20) or (not working and n > 28):
            f.append(Finding(code="acceptance_late", side="both", severity="high",
                             title=f"Приёмка до {n} {'рабочих' if working else 'календарных'} дней — дольше нормы",
                             detail="Затягивает оплату поставщику; для заказчика — нарушение срока приёмки.",
                             quote=_short(acc_q), law="ст. 94 44-ФЗ: не более 20 рабочих дней"))
    if terms.payment_days is not None and terms.acceptance_days is not None:
        cal = lambda n, w: round(n * 1.4) if w else n  # noqa: E731 — рабочие дни в календарные
        gap = cal(terms.acceptance_days, terms.acceptance_working) + cal(terms.payment_days, terms.payment_working)
        f.append(Finding(code="cash_gap", side="supplier", severity="warn" if gap > 30 else "info",
                         title=f"Деньги придут примерно через {gap} {_plural(gap, 'день', 'дня', 'дней')} после поставки",
                         detail="Приёмка плюс оплата: столько дней средства на товар будут заморожены (кассовый разрыв)."))
    if terms.advance_percent:
        f.append(Finding(code="advance", side="supplier", severity="info", title=f"Аванс {terms.advance_percent:g}%".replace(".", ","),
                         detail="Аванс найден в проекте контракта.", quote=_short(adv_q)))
    elif terms.advance_percent == 0:
        f.append(Finding(code="no_advance", side="supplier", severity="info", title="Аванс не предусмотрен",
                         detail="Поставку придётся финансировать из своих средств."))
    if terms.supplier_penalty == "elevated":
        f.append(Finding(code="penalty_high", side="both", severity="high",
                         title="Пени поставщику выше типовых",
                         detail="Вместо 1/300 ключевой ставки за день установлен процент от цены — санкции жёстче закона.",
                         quote=_short(pen_q), law="ч. 7 ст. 34 44-ФЗ: 1/300 ключевой ставки ЦБ"))
    if terms.max_fine_percent is not None and terms.max_fine_percent > 10:
        f.append(Finding(code="fine_high", side="both", severity="warn",
                         title=f"Штраф {terms.max_fine_percent:g}% цены контракта".replace(".", ","),
                         detail="Выше максимального размера по правилам расчёта штрафов.",
                         quote=_short(fine_q), law="ПП РФ № 1042: не более 10% цены контракта"))
    if terms.brands_without_equivalent:
        names = ", ".join(terms.brands_without_equivalent[:5])
        f.append(Finding(code="brand_no_equivalent", side="customer", severity="high",
                         title=f"Марка без «или эквивалент»: {names}",
                         detail="Указание товарного знака без эквивалента ограничивает конкуренцию — частая причина жалоб в ФАС.",
                         quote=_short(brand_q), law="п. 1 ч. 1 ст. 33 44-ФЗ"))
        f.append(Finding(code="brand_required", side="supplier", severity="warn",
                         title=f"Нужна конкретная марка: {names}",
                         detail="Аналог не подойдёт — проверьте, можете ли поставить именно этот товар.",
                         quote=_short(brand_q)))
    if compat:
        f.append(Finding(code="compat_required", side="supplier", severity="info",
                         title="Требуется совместимость: " + ", ".join(compat[:5]),
                         detail="Это требование к среде работы, а не к марке товара — проверьте, что ваш товар его выполняет.",
                         quote=_short(compat_q)))
    if terms.warranty_months:
        f.append(Finding(code="warranty", side="supplier", severity="info",
                         title=f"Гарантийный срок {terms.warranty_months} мес.", detail="Учтите в цене гарантийное обслуживание."))
    return terms


def attach(tender: CanonicalTender, terms: ContractTerms) -> CanonicalTender:
    """Добавить условия контракта в закупку; аванс из контракта закрывает пробел XML ЕИС."""
    tender = tender.model_copy(deep=True)
    tender.contract = terms
    if tender.advance_percent is None and terms.advance_percent is not None:
        tender.advance_percent = terms.advance_percent
        quote = next((x.quote for x in terms.findings if x.code == "advance"), None)
        tender.sources["advance_percent"] = FieldSource(path="проект контракта", raw=quote or "аванс не предусмотрен", extracted_by="text")
    return tender


def supplier_findings(tender: CanonicalTender) -> list[Finding]:
    return [x for x in (tender.contract.findings if tender.contract else []) if x.side in ("supplier", "both")]
