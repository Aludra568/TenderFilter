"""Доменные модели: каноническая закупка, карточка компании, предпочтения профиля."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProcedureType = Literal[
    "e_auction", "open_contest", "quotation_request", "proposal_request", "single_supplier", "other"
]

PROCEDURE_NAMES: dict[str, str] = {
    "e_auction": "Электронный аукцион",
    "open_contest": "Открытый конкурс",
    "quotation_request": "Запрос котировок",
    "proposal_request": "Запрос предложений",
    "single_supplier": "Закупка у единственного поставщика",
    "other": "Иной способ",
}

Verdict = Literal["go", "consider", "skip", "manual"]

VERDICT_NAMES: dict[str, str] = {
    "go": "Участвовать",
    "consider": "Рассмотреть",
    "skip": "Не участвовать",
    "manual": "Проверить вручную",
}


class FieldSource(BaseModel):
    """Откуда взято значение: путь в XML/JSON и исходный фрагмент — основа объяснений."""

    path: str
    raw: str
    extracted_by: Literal["xml", "json", "text", "llm"] = "xml"


class TenderItem(BaseModel):
    name: str
    okpd2: str | None = None
    ktru: str | None = None
    quantity: float | None = None
    unit: str | None = None
    price: float | None = None


class CanonicalTender(BaseModel):
    """Единая модель закупки для 44-ФЗ и 223-ФЗ. Скоринг работает только с ней."""

    purchase_number: str
    law: Literal["44-FZ", "223-FZ"]
    procedure_type: ProcedureType = "other"
    procedure_name: str | None = None
    subject: str
    nmck: float | None = None
    currency: str = "RUB"
    customer_inn: str | None = None
    customer_name: str | None = None
    delivery_place: str | None = None
    delivery_region_code: str | None = None
    delivery_region_name: str | None = None
    published_at: datetime | None = None
    submission_deadline: datetime | None = None
    contract_term_days: int | None = None
    app_guarantee_amount: float | None = None
    contract_guarantee_percent: float | None = None
    contract_guarantee_amount: float | None = None
    advance_percent: float | None = None
    smp_only: bool | None = None
    national_regime: bool | None = None
    requirements: list[str] = Field(default_factory=list)
    okpd2: list[str] = Field(default_factory=list)
    ktru: list[str] = Field(default_factory=list)
    items: list[TenderItem] = Field(default_factory=list)
    url: str | None = None
    sources: dict[str, FieldSource] = Field(default_factory=dict)
    parse_warnings: list[str] = Field(default_factory=list)

    def text_for_matching(self) -> str:
        names = " ".join(i.name for i in self.items[:30])
        return f"{self.subject} {names}"


class OkvedEntry(BaseModel):
    code: str
    name: str | None = None
    main: bool = False


class CompanyCard(BaseModel):
    """Карточка организации из ЕГРЮЛ в нормализованном виде."""

    inn: str
    ogrn: str | None = None
    name: str
    status: Literal["ACTIVE", "LIQUIDATING", "LIQUIDATED", "BANKRUPT", "REORGANIZING", "UNKNOWN"] = "UNKNOWN"
    registration_date: datetime | None = None
    address: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    okveds: list[OkvedEntry] = Field(default_factory=list)
    msp_category: Literal["micro", "small", "medium"] | None = None
    is_msp: bool | None = None
    source: str = "mock"

    @property
    def okved_codes(self) -> list[str]:
        return [o.code for o in self.okveds]


# ---------- Предпочтения профиля (то, что настраивают текстом или ползунками) ----------

MethodPref = Literal["prefer", "neutral", "exclude"]


class FactorSettings(BaseModel):
    importance: int = Field(3, ge=0, le=5, description="0 — фактор отключён, 5 — максимальный вес")
    required: bool = False


class ProfilePrefs(FactorSettings):
    required: bool = True  # закупка не по профилю — стоп-фактор
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    okpd2_prefixes: list[str] = Field(default_factory=list)
    use_okved: bool = True


class PricePrefs(FactorSettings):
    min_rub: float | None = None
    max_rub: float | None = None


class GeoPrefs(FactorSettings):
    regions: dict[str, float] = Field(default_factory=dict, description="код региона → балл 0–1")
    same_district_score: float = 0.5
    excluded: list[str] = Field(default_factory=list)


class TimingPrefs(FactorSettings):
    min_days_to_deadline: int = 3
    min_contract_days: int | None = None


class FinancePrefs(FactorSettings):
    guarantee_limit_rub: float | None = None
    advance: Literal["ignore", "want", "must"] = "ignore"


class ConditionsPrefs(FactorSettings):
    laws: list[Literal["44-FZ", "223-FZ"]] = Field(default_factory=lambda: ["44-FZ", "223-FZ"])
    methods: dict[str, MethodPref] = Field(default_factory=dict)
    prefer_smp: bool = True
    imports_only: bool = False


class CustomerPrefs(FactorSettings):
    importance: int = 2
    excluded_inns: list[str] = Field(default_factory=list)


class CustomRule(BaseModel):
    """Произвольное правило по любому полю канонической модели — расширение без кода."""

    id: str
    label: str
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "not_contains"]
    value: float | str | bool | list[str] | list[float]
    mode: Literal["stop", "bonus", "penalty"] = "stop"
    points: float = 10
    source_text: str | None = None


class Thresholds(BaseModel):
    go: float = 75
    consider: float = 45
    min_completeness: float = 0.7


class Preferences(BaseModel):
    profile: ProfilePrefs = Field(default_factory=ProfilePrefs)
    price: PricePrefs = Field(default_factory=PricePrefs)
    geo: GeoPrefs = Field(default_factory=GeoPrefs)
    timing: TimingPrefs = Field(default_factory=TimingPrefs)
    finance: FinancePrefs = Field(default_factory=FinancePrefs)
    conditions: ConditionsPrefs = Field(default_factory=ConditionsPrefs)
    customer: CustomerPrefs = Field(default_factory=CustomerPrefs)
    custom_rules: list[CustomRule] = Field(default_factory=list)
    thresholds: Thresholds = Field(default_factory=Thresholds)
