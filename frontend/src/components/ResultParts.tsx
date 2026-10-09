import { useRef, useState } from "react";
import type { Company, Finding, Review, ScoreResult, Tender } from "../api";
import { rub } from "../format";
import { Bar, VerdictChip } from "./common";

const STATUS: Record<string, string> = {
  ACTIVE: "Действующая",
  LIQUIDATING: "Ликвидируется",
  LIQUIDATED: "Прекратила деятельность",
  BANKRUPT: "Банкротство",
  REORGANIZING: "Реорганизация",
  UNKNOWN: "Неизвестно",
};
const SOURCE: Record<string, string> = { dadata: "DaData", fns: "ФНС: ЕГРЮЛ и реестр МСП", mock: "демо-данные" };

/** Разбор оценки по факторам: баллы, причины, источник в извещении по клику. */
export function FactorList({ result }: { result: ScoreResult }) {
  const [open, setOpen] = useState<string | null>(result.factors.find((f) => f.sources.length)?.key ?? null);
  return (
    <>
      {result.factors.map((f, i) => (
        <div className="factor" key={f.key} style={{ opacity: f.active ? 1 : 0.55 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <span className="name">{f.label}{f.stop && <span className="chip skip" style={{ marginLeft: 8, fontSize: 12 }}>стоп</span>}</span>
            {f.value && <span className="muted" style={{ fontSize: 14 }}>{f.value}</span>}
            {f.reasons.map((reason) => <span key={reason} className="why">{reason}</span>)}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
            <span className="num" style={{ fontSize: 17, fontWeight: 800 }}>
              {f.score == null ? "нет данных" : f.active ? `+${f.points.toString().replace(".", ",")} из ${f.max_points.toString().replace(".", ",")}` : "не учитывается"}
            </span>
            <span style={{ width: 140 }}><Bar value={f.score ?? 0} delay={400 + i * 70} /></span>
          </div>
          {f.sources.length > 0 && (
            <button type="button" className="btn3" style={{ gridColumn: "1 / -1", justifySelf: "start" }} aria-expanded={open === f.key}
                    onClick={() => setOpen(open === f.key ? null : f.key)}>
              Источник в извещении: {f.sources.map((s) => s.path.split("/").slice(-2).join("/")).join(", ")}
            </button>
          )}
          {open === f.key && (
            <div className="quote">
              {f.sources.map((s) => (
                <div key={s.field + s.path} style={{ marginBottom: 6 }}>
                  <code>{s.path}</code>
                  <div>{s.raw}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      {result.rules.map((rule) => (
        <div key={rule.id} className="kv"><span>Правило: {rule.label}</span><span>{rule.effect === "stop" ? "стоп" : `${rule.points > 0 ? "+" : ""}${rule.points}`}</span></div>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", paddingTop: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 800 }}>Итого</span>
        <span className="digits" style={{ fontSize: 18, fontWeight: 800 }}>{`${Math.round(result.score)} из 100`}</span>
      </div>
    </>
  );
}

export function KeyParams({ t }: { t: Tender }) {
  return (
    <>
      <div className="kv"><span>НМЦК</span><span className="num">{rub(t.nmck)}</span></div>
      <div className="kv"><span>Способ</span><span>{t.procedure_name ?? "—"}</span></div>
      <div className="kv"><span>Подача до</span><span className="num">{t.submission_deadline ? new Date(t.submission_deadline).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "—"}</span></div>
      <div className="kv"><span>Регион поставки</span><span>{t.delivery_region_name ?? t.delivery_place ?? "—"}</span></div>
      <div className="kv"><span>Обеспечение заявки</span><span className="num">{rub(t.app_guarantee_amount)}</span></div>
      <div className="kv"><span>Обеспечение контракта</span><span className="num">{t.contract_guarantee_percent != null ? `${t.contract_guarantee_percent}% · ${rub(t.contract_guarantee_amount)}` : "—"}</span></div>
      <div className="kv"><span>Аванс</span><span>{t.advance_percent != null ? `${t.advance_percent}%` : "в проекте контракта"}</span></div>
      <div className="kv"><span>Только для СМП</span><span>{t.smp_only == null ? "—" : t.smp_only ? "да" : "нет"}</span></div>
      <div className="kv"><span>ОКПД 2</span><span className="num">{t.okpd2.slice(0, 3).join(", ") || "—"}</span></div>
    </>
  );
}

export function CompanyBlock({ company, empty }: { company: Company | null; empty: string }) {
  if (!company) return <p className="muted" style={{ margin: 0 }}>{empty}</p>;
  const msp = company.is_msp == null ? "неизвестно" : company.is_msp ? `да, ${({ micro: "микро", small: "малое", medium: "среднее" } as Record<string, string>)[company.msp_category ?? ""] ?? "МСП"}` : "нет";
  return (
    <>
      <div className="kv"><span>Организация</span><span>{company.name}</span></div>
      <div className="kv"><span>Статус</span><span style={{ color: company.status === "ACTIVE" ? "var(--go-fg)" : "var(--skip-fg)" }}>{STATUS[company.status] ?? company.status}</span></div>
      <div className="kv"><span>ИНН / ОГРН</span><span className="num">{company.inn}{company.ogrn ? ` / ${company.ogrn}` : ""}</span></div>
      {company.region_name && <div className="kv"><span>Регион</span><span>{company.region_name}</span></div>}
      {company.registration_date && <div className="kv"><span>Зарегистрирована</span><span className="num">{new Date(company.registration_date).toLocaleDateString("ru-RU")}</span></div>}
      <div className="kv"><span>Реестр МСП</span><span>{msp}</span></div>
      {company.okveds.length > 0 && (
        <div className="kv"><span>ОКВЭД</span><span>{company.okveds.slice(0, 3).map((o) => o.code).join(", ")}{company.okveds.length > 3 ? ` и ещё ${company.okveds.length - 3}` : ""}</span></div>
      )}
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>Источник: {SOURCE[company.source] ?? company.source}</p>
    </>
  );
}

const REVIEW_CHIP: Record<Review["status"], string> = { agree: "go", doubt: "consider", unconfirmed: "manual", unavailable: "manual" };

/** Проверка оценки нейросетью: согласна / скорректировала вердикт / не подтвердила / не подключена. */
export function ReviewBlock({ review, onRun, running }: { review?: Review; onRun?: () => void; running?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {review ? (
        <>
          <span className={`chip ${REVIEW_CHIP[review.status]}`} style={{ alignSelf: "flex-start", whiteSpace: "normal" }}>{review.status_name}</span>
          {review.changed && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 14 }}>
              <span className="muted">Алгоритм</span><VerdictChip verdict={review.algorithm_verdict} />
              <span aria-hidden="true">→</span>
              <span className="muted">после проверки</span><VerdictChip verdict={review.final_verdict} />
            </div>
          )}
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>{review.note}</p>
          {review.issues.map((i, k) => (
            <div key={k} style={{ background: "var(--tint)", borderRadius: 14, padding: "10px 12px", fontSize: 14, display: "flex", flexDirection: "column", gap: 4 }}>
              <b>{i.problem}</b>
              <span className="muted">«{i.quote}» — {i.verified ? "цитата найдена в извещении" : "цитата не найдена, замечание не учтено"}</span>
            </div>
          ))}
          {review.status !== "unavailable" && (
            <span className="muted" style={{ fontSize: 12 }}>Процент считает алгоритм; нейросеть меняет вердикт не больше чем на ступень и только с цитатой · {Math.round(review.elapsed_ms)} мс</span>
          )}
        </>
      ) : (
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>Нейросеть перепроверит разбор алгоритма и при подтверждённом замечании скорректирует вердикт.</p>
      )}
      {onRun && (
        <button type="button" className="btn2" onClick={onRun} disabled={running} style={{ alignSelf: "flex-start" }}>
          {running ? "Проверяю…" : review ? "Проверить ещё раз" : "Проверить нейросетью"}
        </button>
      )}
    </div>
  );
}

const SEVERITY: Record<Finding["severity"], { chip: string; icon: string; label: string }> = {
  high: { chip: "skip", icon: "✕", label: "Риск" },
  warn: { chip: "consider", icon: "!", label: "Внимание" },
  info: { chip: "manual", icon: "i", label: "Инфо" },
};
const SIDE: Record<Finding["side"], string> = { supplier: "поставщику", customer: "заказчику", both: "обеим сторонам" };

/** Риски из документов закупки: сначала серьёзные; у каждого — кого касается, цитата и норма закона. */
export function FindingList({ findings, empty, showSide = true }: { findings: Finding[]; empty?: string; showSide?: boolean }) {
  const order = { high: 0, warn: 1, info: 2 };
  const sorted = [...findings].sort((a, b) => order[a.severity] - order[b.severity]);
  if (!sorted.length) return <p className="muted" style={{ margin: 0, fontSize: 14 }}>{empty ?? "Замечаний нет"}</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {sorted.map((f, i) => (
        <div key={`${f.code}-${i}`} style={{ background: "var(--tint)", borderRadius: 16, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className={`chip ${SEVERITY[f.severity].chip}`} style={{ fontSize: 12 }}>{SEVERITY[f.severity].icon} {SEVERITY[f.severity].label}</span>
            {showSide && <span className="muted" style={{ fontSize: 12 }}>важно {SIDE[f.side]}</span>}
          </div>
          <b>{f.title}</b>
          <span className="muted">{f.detail}</span>
          {f.quote && <span style={{ fontSize: 13, borderLeft: "3px solid var(--line)", paddingLeft: 10 }}>«{f.quote}»</span>}
          {f.law && <span className="muted" style={{ fontSize: 12 }}>Норма: {f.law}</span>}
        </div>
      ))}
    </div>
  );
}

/** Выбор вложений закупки: проект контракта, ТЗ (.docx, .pdf, .txt). */
export function DocsPicker({ files, onChange, label = "Приложить проект контракта и ТЗ" }: { files: File[]; onChange: (f: File[]) => void; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={() => input.current?.click()}>
        📎 {label}
      </button>
      <input ref={input} type="file" multiple accept=".docx,.pdf,.txt,.html,.htm" hidden
             onChange={(e) => onChange([...files, ...Array.from(e.target.files ?? [])])} />
      {files.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {files.map((f, i) => (
            <span key={`${f.name}-${i}`} className="chip manual" style={{ fontSize: 12 }}>
              {f.name}
              <button type="button" aria-label={`Убрать ${f.name}`} onClick={() => onChange(files.filter((_, k) => k !== i))}
                      style={{ border: "none", background: "transparent", cursor: "pointer", marginLeft: 4, color: "inherit" }}>×</button>
            </span>
          ))}
        </div>
      )}
      <span className="muted" style={{ fontSize: 12 }}>Необязательно. .docx, .pdf (с текстом), .txt — найдём сроки оплаты, санкции, аванс, марки без эквивалента.</span>
    </div>
  );
}
