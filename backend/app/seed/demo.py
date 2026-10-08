"""Демо-извещения в структуре реальных выгрузок ЕИС.

44-ФЗ повторяет структуру epNotificationEF2020 (schemeVersion 16.2), сверенную с реальным
файлом из samples/. Сроки считаются от текущей даты, поэтому демо не «протухает».
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

TZ = timezone(timedelta(hours=3))


@dataclass
class Spec:
    number: str
    subject: str
    customer_inn: str
    customer_name: str
    address: str
    nmck: float
    deadline_days: float
    items: list[tuple[str, str, float]]  # (наименование, ОКПД2, количество)
    method: str = "EAP20"  # EAP20 — аукцион, ZKP20 — котировки, OKP20 — конкурс
    smp: bool = False
    national: bool = False
    app_part: float = 1.0
    contract_part: float = 5.0
    term_days: int = 45
    law: str = "44"


METHOD_NAMES = {
    "EAP20": ("epNotificationEF2020", "Электронный аукцион"),
    "ZKP20": ("epNotificationEZK2020", "Запрос котировок в электронной форме"),
    "OKP20": ("epNotificationEOK2020", "Открытый конкурс в электронной форме"),
}

C_OBL = ("7017987652", "ОГБОУ «Областной лицей»", "Томская обл., г. Томск")
C_KEM = ("4205123459", "ГБУЗ «Областная больница»", "Кемеровская обл. — Кузбасс, г. Кемерово")
C_OMSK = ("5504123459", "Администрация района", "Омская обл., г. Омск")
C_MAG = ("4909123455", "МКУ «Центр закупок»", "Магаданская обл., г. Магадан")
C_ALT = ("2221123452", "КГБУ «Краевой центр»", "Алтайский край, г. Барнаул")
C_MSK = ("7710987659", "ФГБУ «Научный центр»", "г. Москва")
C_SAM = ("6312123457", "ГКУ «Управление информатизации»", "Самарская обл., г. Самара")
C_BANK = ("4205987650", "МУП «Горсервис»", "Кемеровская обл. — Кузбасс, г. Новокузнецк")
C_NSK = ("5406987651", "ООО «Закрываемся»", "Новосибирская обл., г. Новосибирск")
C_NSK_GOV = ("5504123459", "Администрация района", "Новосибирская обл., г. Новосибирск")


def _s(n: int, subject: str, cust: tuple, nmck: float, days: float, items, **kw) -> Spec:
    inn, name, addr = cust
    return Spec(number=f"03652000001260{n:05d}", subject=subject, customer_inn=inn, customer_name=name,
                address=addr, nmck=nmck, deadline_days=days, items=items, **kw)


SPECS: list[Spec] = [
    _s(1, "Поставка ноутбуков для образовательных учреждений", C_OBL, 4_200_000, 6, [("Ноутбук", "26.20.11.110", 120)], smp=True, national=True, contract_part=10),
    _s(2, "Поставка серверного оборудования", C_NSK_GOV, 18_700_000, 9, [("Сервер", "26.20.14.000", 6)], national=True, contract_part=5),
    _s(3, "Поставка МФУ и расходных материалов", C_NSK_GOV, 2_100_000, 4, [("МФУ", "26.20.18.000", 20), ("Картридж", "20.59.12.120", 200)], method="ZKP20", smp=True),
    _s(4, "Поставка комплектующих для персональных компьютеров", C_ALT, 1_300_000, 12, [("Твердотельный накопитель", "26.20.21.110", 80), ("Модуль памяти", "26.20.30.000", 60)], smp=True),
    _s(5, "Поставка сетевого оборудования", C_KEM, 36_000_000, 15, [("Коммутатор", "26.30.11.110", 40)], method="OKP20", contract_part=10),
    _s(6, "Поставка неисключительных лицензий на офисное программное обеспечение", C_NSK_GOV, 3_400_000, 8, [("Лицензия на программное обеспечение", "58.29.29.000", 300)], national=True),
    _s(7, "Поставка ноутбуков для администрации района", C_OMSK, 2_800_000, 1, [("Ноутбук", "26.20.11.110", 30)], smp=True),
    _s(8, "Поставка медицинского оборудования", C_MAG, 12_500_000, 13, [("Аппарат ультразвуковой диагностики", "26.60.12.129", 2)]),
    _s(9, "Поставка мониторов", C_OBL, 950_000, 7, [("Монитор", "26.20.17.110", 45)], method="ZKP20", smp=True),
    _s(10, "Поставка компьютерной техники", C_MSK, 54_000_000, 10, [("Персональный компьютер", "26.20.15.000", 400)], national=True, contract_part=10),
    _s(11, "Поставка картриджей для принтеров", C_ALT, 420_000, 5, [("Картридж", "20.59.12.120", 300)], method="ZKP20", smp=True),
    _s(12, "Поставка ноутбуков", C_KEM, 6_300_000, 11, [("Ноутбук", "26.20.11.110", 90)], smp=True),
    _s(13, "Поставка продуктов питания для школьных столовых", C_OBL, 8_800_000, 9, [("Молоко питьевое", "10.51.11.110", 4000), ("Хлеб", "10.71.11.110", 6000)], smp=True),
    _s(14, "Выполнение работ по капитальному ремонту кровли", C_OMSK, 23_000_000, 14, [("Ремонт кровли", "43.91.19.110", 1)], contract_part=30),
    _s(15, "Поставка серверов и систем хранения данных", C_SAM, 120_000_000, 18, [("Сервер", "26.20.14.000", 30), ("Система хранения данных", "26.20.40.120", 4)], method="OKP20", national=True, contract_part=30),
    _s(16, "Поставка планшетных компьютеров", C_OBL, 1_900_000, 3, [("Планшетный компьютер", "26.20.11.110", 40)], method="ZKP20", smp=True),
    _s(17, "Поставка источников бесперебойного питания", C_NSK_GOV, 780_000, 8, [("Источник бесперебойного питания", "27.90.11.000", 25)], smp=True),
    _s(18, "Оказание услуг по уборке помещений", C_KEM, 5_600_000, 10, [("Услуги по уборке", "81.21.10.000", 1)], smp=True),
    _s(19, "Поставка ноутбуков и периферийного оборудования", C_BANK, 3_100_000, 9, [("Ноутбук", "26.20.11.110", 25), ("Мышь компьютерная", "26.20.16.170", 25)], smp=True),
    _s(20, "Поставка проекторов и интерактивных панелей", C_ALT, 4_700_000, 6, [("Интерактивная панель", "26.20.17.110", 15)]),
    _s(21, "Поставка строительных материалов", C_OBL, 3_300_000, 7, [("Цемент", "23.51.12.110", 200), ("Кирпич", "23.32.11.110", 50000)], smp=True),
    _s(22, "Поставка расходных материалов для оргтехники", C_MAG, 610_000, 6, [("Тонер-картридж", "20.59.12.120", 150)], method="ZKP20", smp=True),
    _s(23, "Поставка персональных компьютеров", C_OBL, 2_450_000, 2, [("Персональный компьютер", "26.20.15.000", 35)], method="ZKP20", smp=True),
    _s(24, "Поставка лекарственных препаратов", C_KEM, 9_900_000, 8, [("Лекарственный препарат", "21.20.10.190", 1000)]),
    _s(25, "Поставка ноутбуков для нужд учреждения", C_NSK_GOV, 380_000, 10, [("Ноутбук", "26.20.11.110", 5)], method="ZKP20", smp=True),
    _s(26, "Поставка многофункциональных устройств", C_OMSK, 1_150_000, 9, [("МФУ", "26.20.18.000", 18)], smp=True),
    _s(27, "Поставка компьютерного оборудования для центра обработки данных", C_MSK, 280_000_000, 20, [("Сервер", "26.20.14.000", 80)], method="OKP20", national=True, contract_part=30),
    _s(28, "Поставка ноутбуков", C_NSK_GOV, 5_500_000, -1, [("Ноутбук", "26.20.11.110", 70)], smp=True),
    _s(29, "Поставка оргтехники", C_KEM, 2_000_000, 6, [("Принтер", "26.20.16.120", 30)], smp=True),
    _s(30, "Поставка мебели для кабинетов", C_OBL, 1_700_000, 9, [("Стол письменный", "31.01.12.160", 60)], smp=True),
    _s(31, "Поставка жёстких дисков и накопителей", C_SAM, 890_000, 8, [("Жёсткий диск", "26.20.21.120", 120)], method="ZKP20", smp=True),
    _s(32, "Поставка телекоммуникационного оборудования", C_ALT, 7_800_000, 12, [("Маршрутизатор", "26.30.11.120", 20)]),
    _s(33, "Поставка системных блоков", C_NSK_GOV, 3_900_000, 5, [("Системный блок", "26.20.15.000", 60)], smp=True, national=True),
    _s(34, "Оказание услуг по техническому обслуживанию компьютерной техники", C_OBL, 1_200_000, 9, [("Услуги по ремонту компьютеров", "95.11.10.000", 1)], smp=True),
    _s(35, "Поставка автомобиля", C_OMSK, 4_100_000, 7, [("Автомобиль легковой", "29.10.22.000", 1)]),
    _s(36, "Поставка ноутбуков", C_NSK, 1_100_000, 8, [("Ноутбук", "26.20.11.110", 15)], smp=True),
]


def notice_xml(spec: Spec, now: datetime) -> str:
    root, method_name = METHOD_NAMES[spec.method]
    published = now - timedelta(days=2)
    deadline = (now + timedelta(days=spec.deadline_days)).replace(minute=0, second=0, microsecond=0)
    end_date = (deadline + timedelta(days=10 + spec.term_days)).date()
    app_amount = round(spec.nmck * spec.app_part / 100, 2)
    contract_amount = round(spec.nmck * spec.contract_part / 100, 2)
    total_qty = sum(q for _, _, q in spec.items) or 1
    price_per_unit = spec.nmck / total_qty

    objects = []
    for name, okpd, qty in spec.items:
        objects.append(f"""                <ns3:purchaseObject>
                    <ns3:OKPD2>
                        <ns2:OKPDCode>{okpd}</ns2:OKPDCode>
                        <ns2:OKPDName>{escape(name)}</ns2:OKPDName>
                    </ns3:OKPD2>
                    <ns3:name>{escape(name)}</ns3:name>
                    <ns3:price>{price_per_unit:.2f}</ns3:price>
                    <ns3:quantity>
                        <ns3:value>{qty:.11f}</ns3:value>
                    </ns3:quantity>
                    <ns3:sum>{price_per_unit * qty:.2f}</ns3:sum>
                    <ns3:type>PRODUCT</ns3:type>
                    <ns3:restrictionsInfo>
                        <ns3:isProhibitionForeignPurchaseObjects>false</ns3:isProhibitionForeignPurchaseObjects>
                        <ns3:isRestrictForeignPurchaseObjects>{"true" if spec.national else "false"}</ns3:isRestrictForeignPurchaseObjects>
                        <ns3:isPreferenseRFPurchaseObjects>false</ns3:isPreferenseRFPurchaseObjects>
                    </ns3:restrictionsInfo>
                </ns3:purchaseObject>""")
    preferences = ""
    if spec.smp:
        preferences = """        <preferensesInfo>
            <preferenseInfo>
                <ns3:preferenseRequirementInfo>
                    <ns2:shortName>PVS33044</ns2:shortName>
                    <ns2:name>Преимущество в соответствии с ч. 3 ст. 30 Закона № 44-ФЗ</ns2:name>
                </ns3:preferenseRequirementInfo>
            </preferenseInfo>
        </preferensesInfo>
"""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!-- Демо-извещение в структуре ЕИС; организации и номера вымышлены. -->
<ns7:{root} xmlns="http://zakupki.gov.ru/oos/EPtypes/1" xmlns:ns7="http://zakupki.gov.ru/oos/printform/1" xmlns:ns2="http://zakupki.gov.ru/oos/base/1" xmlns:ns3="http://zakupki.gov.ru/oos/common/1" schemeVersion="16.2">
    <commonInfo>
        <purchaseNumber>{spec.number}</purchaseNumber>
        <publishDTInEIS>{published.isoformat()}</publishDTInEIS>
        <href>https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={spec.number}</href>
        <placingWay>
            <ns2:code>{spec.method}</ns2:code>
            <ns2:name>{method_name}</ns2:name>
        </placingWay>
        <purchaseObjectInfo>{escape(spec.subject)}</purchaseObjectInfo>
    </commonInfo>
    <purchaseResponsibleInfo>
        <responsibleOrgInfo>
            <fullName>{escape(spec.customer_name)}</fullName>
            <factAddress>{escape(spec.address)}</factAddress>
            <INN>{spec.customer_inn}</INN>
        </responsibleOrgInfo>
        <responsibleRole>CU</responsibleRole>
    </purchaseResponsibleInfo>
    <notificationInfo>
        <procedureInfo>
            <collectingInfo>
                <startDT>{published.isoformat()}</startDT>
                <endDT>{deadline.isoformat()}</endDT>
            </collectingInfo>
        </procedureInfo>
        <contractConditionsInfo>
            <maxPriceInfo>
                <maxPrice>{spec.nmck:.2f}</maxPrice>
                <currency><ns2:code>RUB</ns2:code></currency>
            </maxPriceInfo>
        </contractConditionsInfo>
        <customerRequirementsInfo>
            <customerRequirementInfo>
                <applicationGuarantee>
                    <amount>{app_amount:.2f}</amount>
                    <part>{spec.app_part}</part>
                </applicationGuarantee>
                <contractGuarantee>
                    <amount>{contract_amount:.2f}</amount>
                    <part>{spec.contract_part}</part>
                </contractGuarantee>
                <contractConditionsInfo>
                    <contractExecutionPaymentPlan>
                        <contractExecutionTermsInfo>
                            <notRelativeTermsInfo>
                                <isFromConclusionDate>true</isFromConclusionDate>
                                <endDate>{end_date.isoformat()}+03:00</endDate>
                            </notRelativeTermsInfo>
                        </contractExecutionTermsInfo>
                    </contractExecutionPaymentPlan>
                    <deliveryPlacesInfo>
                        <byGARInfo>
                            <ns3:GARInfo>
                                <ns3:GARAddress>{escape(spec.address)}</ns3:GARAddress>
                            </ns3:GARInfo>
                        </byGARInfo>
                    </deliveryPlacesInfo>
                </contractConditionsInfo>
            </customerRequirementInfo>
        </customerRequirementsInfo>
        <purchaseObjectsInfo>
            <notDrugPurchaseObjectsInfo>
{chr(10).join(objects)}
                <ns3:totalSum>{spec.nmck:.2f}</ns3:totalSum>
            </notDrugPurchaseObjectsInfo>
        </purchaseObjectsInfo>
{preferences}        <requirementsInfo>
            <requirementInfo>
                <ns3:preferenseRequirementInfo>
                    <ns2:shortName>ET44</ns2:shortName>
                    <ns2:name>Единые требования к участникам закупок в соответствии с ч. 1 ст. 31 Закона № 44-ФЗ</ns2:name>
                </ns3:preferenseRequirementInfo>
            </requirementInfo>
        </requirementsInfo>
    </notificationInfo>
</ns7:{root}>
"""


def notice_223_xml(now: datetime) -> str:
    """Извещение 223-ФЗ (запрос предложений госкомпании) — для проверки второй схемы."""
    deadline = (now + timedelta(days=9)).replace(minute=0, second=0, microsecond=0)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Демо-извещение 223-ФЗ; структура упрощена, организации вымышлены. -->
<ns2:purchaseNoticeZPESMBO xmlns:ns2="http://zakupki.gov.ru/223fz/purchase/1" xmlns="http://zakupki.gov.ru/223fz/types/1">
    <ns2:body>
        <ns2:item>
            <ns2:purchaseNoticeZPESMBOData>
                <registrationNumber>32615000412</registrationNumber>
                <name>Поставка ноутбуков и мониторов для нужд АО «Демо-энерго»</name>
                <purchaseCodeName>Запрос предложений в электронной форме, участниками которого могут быть только субъекты МСП</purchaseCodeName>
                <publicationDateTime>{(now - timedelta(days=1)).isoformat()}</publicationDateTime>
                <customer>
                    <mainInfo>
                        <fullName>АО «Демо-энерго»</fullName>
                    </mainInfo>
                </customer>
                <submissionCloseDateTime>{deadline.isoformat()}</submissionCloseDateTime>
                <lots>
                    <lot>
                        <lotData>
                            <subject>Поставка ноутбуков и мониторов</subject>
                            <currency><code>RUB</code></currency>
                            <initialSum>3150000.00</initialSum>
                            <forSmallOrMiddle>true</forSmallOrMiddle>
                            <deliveryPlace>
                                <address>Новосибирская обл., г. Новосибирск</address>
                            </deliveryPlace>
                            <lotItems>
                                <lotItem>
                                    <okpd2><code>26.20.11.110</code><name>Компьютеры портативные</name></okpd2>
                                    <qty>30</qty>
                                </lotItem>
                                <lotItem>
                                    <okpd2><code>26.20.17.110</code><name>Мониторы</name></okpd2>
                                    <qty>30</qty>
                                </lotItem>
                            </lotItems>
                        </lotData>
                    </lot>
                </lots>
            </ns2:purchaseNoticeZPESMBOData>
        </ns2:item>
    </ns2:body>
</ns2:purchaseNoticeZPESMBO>
"""


def demo_files(now: datetime | None = None) -> list[tuple[str, bytes]]:
    now = now or datetime.now(TZ)
    files = [(f"notice_{s.number}.xml", notice_xml(s, now).encode("utf-8")) for s in SPECS]
    files.append(("notice_223fz_32615000412.xml", notice_223_xml(now).encode("utf-8")))
    return files


DEMO_COMPANY_INN = "5406123450"
DEMO_CRITERIA = (
    "Работаем в Новосибирской и Томской областях, в Алтайском крае и Кемеровской области — если выгодно. "
    "НМЦК от 500 тыс. до 30 млн. На обеспечения готовы отвлечь не больше 2 млн. "
    "На заявку нужно минимум 3 дня. Конкурсы не любим. Аванс важен. "
    "Поставляем ноутбуки, компьютеры, серверы, МФУ, картриджи и сетевое оборудование."
)
