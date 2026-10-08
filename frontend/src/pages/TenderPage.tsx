import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TenderCard } from "../api";
import { useApp } from "../App";
import { Bar, CountUp, ErrorBox, Skeleton, VerdictChip } from "../components/common";
import { Radar, type RadarSeries } from "../components/Radar";
import { LAW, deadlineInfo, rub } from "../format";

const COMPARE_STYLE = [
  { color: "#0E8A5A", dash: "10 6" },
  { color: "#C2410C", dash: "2 6" },
];

export function TenderPage() {
  const { id } = useParams();
  const { profile } = useApp();
  const [card, setCard] = useState<TenderCard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [compare, setCompare] = useState<Record<number, boolean>>({});
  const [replay, setReplay] = useState(0);
  const [vote, setVote] = useState<boolean | null>(null);
  const [raw, setRaw] = useState<string | null>(null);

  useEffect(() => {
    setCard(null);
    setVote(null);
    setCompare({});
    api.tender(Number(id)).then((c) => { setCard(c); setOpen(c.result.factors.find((f) => f.sources.length)?.key ?? null); }).catch(setError);
  }, [id, profile?.version]);

  if (error) return <ErrorBox error={error} />;
  if (!card) return <><Skeleton height={220} /><Skeleton height={480} /></>;

  const { tender: t, result: r } = card;
  const dl = deadlineInfo(t.submission_deadline);
  const labels = r.factors.map((f) => f.label);
  const values = r.factors.map((f) => f.score);
  const weights = r.factors.map((f) => f.weight);
  const series: RadarSeries[] = card.similar.slice(0, 2).filter((s) => compare[s.tender_id]).map((s) => {
    const idx = card.similar.indexOf(s);
    return { key: String(s.tender_id), values: r.factors.map((f) => s.factors.find((x) => x.key === f.key)?.score ?? 0), ...COMPARE_STYLE[idx] };
  });

  const sendVote = async (correct: boolean) => {
    setVote(correct);
    await api.feedback(card.score_id, correct).catch(() => setVote(null));
  };

  return (
    <>
      <nav aria-label="Навигация" className="fu muted" style={{ fontSize: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Link to="/" className="muted">← Лента закупок</Link><span aria-hidden="true">·</span><span className="num">№ {t.purchase_number}</span>
      </nav>

      <div className="row" style={{ alignItems: "stretch" }}>
        <div className="card grow fu" style={{ display: "flex", flexDirection: "column", gap: 18, animationDelay: "60ms" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <span className="tag">{LAW(t.law)}</span>
            {t.procedure_name && <span className="tag">{t.procedure_name}</span>}
            {t.smp_only && <span className="tag" style={{ background: "var(--go-bg)", color: "var(--go-fg)" }}>Только для СМП</span>}
            {t.national_regime && <span className="tag">Нацрежим</span>}
            <span className={dl.urgent ? "sticker" : "tag"} style={{ marginLeft: 6 }}>{dl.expired ? "срок истёк" : `подача до ${dl.date} · ${dl.left.replace("горит · ", "")}`}</span>
          </div>
          <h1 style={{ fontSize: "clamp(26px, 3vw, 34px)", lineHeight: 1.2, fontWeight: 800 }}>{t.subject}</h1>
          <p style={{ margin: 0, fontSize: 17, color: "var(--ink-2)" }}>
            Заказчик: {t.customer_name || "не указан"}{t.delivery_region_name ? `, ${t.delivery_region_name}` : ""}.{" "}
            НМЦК {rub(t.nmck)}{t.okpd2.length ? `, ОКПД 2 ${t.okpd2.slice(0, 3).join(", ")}` : ""}
            {t.contract_term_days ? `. Исполнение ~${t.contract_term_days} дн.` : ""}
          </p>
          {t.parse_warnings.length > 0 && <div className="unparsed">Не найдено в извещении: {t.parse_warnings.join("; ").toLowerCase()}</div>}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 4 }}>
            {t.url && (
              <a href={t.url} target="_blank" rel="noreferrer" className="btn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3h7v7M10 14L21 3M21 14v7H3V3h7" /></svg>
                Открыть в ЕИС
              </a>
            )}
            <button type="button" className="btn2" onClick={async () => setRaw(await api.raw(card.tender_id))}>Исходный файл</button>
            <Link to="/profile" className="btn2">Изменить правила</Link>
          </div>
        </div>

        <aside className="card dark side fu lift" aria-label="Итоговая оценка" style={{ animationDelay: "140ms", gap: 14 }}>
          <div aria-hidden="true" style={{ position: "absolute", width: 260, height: 260, borderRadius: "50%", right: -80, top: -90, background: "radial-gradient(circle, rgba(124,92,255,.75), rgba(124,92,255,0) 70%)" }} />
          <div aria-hidden="true" style={{ position: "absolute", width: 220, height: 220, borderRadius: "50%", left: -70, bottom: -100, background: "radial-gradient(circle, rgba(232,0,61,.55), rgba(232,0,61,0) 70%)" }} />
          <div className="muted" style={{ position: "relative", fontWeight: 600 }}>Итоговая оценка</div>
          <span className="digits" style={{ position: "relative", fontSize: 88, lineHeight: 1, fontWeight: 800 }}>
            {r.verdict === "manual" ? "—" : <CountUp value={r.score} suffix="%" />}
          </span>
          <span className="pop" style={{ position: "relative", alignSelf: "flex-start", animationDelay: "0.9s" }}><VerdictChip verdict={r.verdict} big /></span>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }} className="muted">
            {r.stops.length > 0 && <span style={{ color: "#ffb3c1", fontWeight: 700 }}>Стоп-фактор: {r.stops[0]}</span>}
            {r.flags.map((f) => <span key={f} style={{ color: "#ffe08a", fontWeight: 600 }}>⚑ {f}</span>)}
            <span>Полнота данных: {Math.round(r.completeness * 100)}%</span>
            <span className="num">Место в ленте: {card.rank} · рассчитано за {r.elapsed_ms.toString().replace(".", ",")} мс · профиль v{card.profile_version}</span>
          </div>
        </aside>
      </div>

      <section className="card fu" aria-labelledby="radar-h" style={{ display: "flex", flexWrap: "wrap", gap: 32, alignItems: "center", animationDelay: "220ms" }}>
        <div className="grow" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <h2 id="radar-h">Профиль закупки</h2>
            <button type="button" className="btn3" onClick={() => setReplay((x) => x + 1)}>↻ Распустить заново</button>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 15 }}>7 групп факторов. Чем ближе к краю, тем лучше. Зелёный пунктир — порог «Участвовать».</p>
          <Radar labels={labels} values={values} weights={weights} compare={series} threshold={(profile?.preferences?.thresholds?.go ?? 75) / 100} replayKey={replay} />
        </div>
        <div className="side" style={{ gap: 18 }}>
          {card.similar.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span className="muted" style={{ fontSize: 14, fontWeight: 700 }}>Сравнить с похожими (поиск по смыслу)</span>
              {card.similar.slice(0, 2).map((s, i) => (
                <button key={s.tender_id} type="button" className={`cmp-btn${compare[s.tender_id] ? " on" : ""}`} aria-pressed={!!compare[s.tender_id]}
                        onClick={() => setCompare((c) => ({ ...c, [s.tender_id]: !c[s.tender_id] }))}>
                  <svg width="30" height="12" aria-hidden="true" style={{ flex: "none" }}><line x1="0" y1="6" x2="30" y2="6" stroke={COMPARE_STYLE[i].color} strokeWidth="3.5" strokeDasharray={COMPARE_STYLE[i].dash} strokeLinecap="round" /></svg>
                  <span style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontWeight: 700 }}>{s.subject}</span>
                    <span className="muted" style={{ fontSize: 13 }}>{s.region_name} · {Math.round(s.score)}%</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {r.factors.map((f, i) => (
              <div key={f.key} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 64px", gap: "4px 12px", alignItems: "center", fontSize: 14, opacity: f.active ? 1 : 0.5 }}>
                <span style={{ fontWeight: 600 }}>{f.label} <span className="muted" style={{ fontWeight: 500 }}>· вес {Math.round(f.weight)}</span></span>
                <span className="num" style={{ textAlign: "right", fontWeight: 800 }}>{f.score == null ? "—" : `${Math.round(f.score * 100)}%`}</span>
                <span style={{ gridColumn: "1 / -1" }}><Bar value={f.score ?? 0} gradient="linear-gradient(90deg,#e8003d,#ff4fa3,#7c5cff)" delay={600 + i * 70} /></span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="row">
        <section className="card grow fu" aria-labelledby="why" style={{ animationDelay: "300ms" }}>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
            <h2 id="why">Почему такая оценка</h2>
            <span className="muted" style={{ fontSize: 14 }}>баллы из веса фактора</span>
          </div>
          {r.factors.map((f, i) => (
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
          {r.rules.map((rule) => (
            <div key={rule.id} className="kv"><span>Правило: {rule.label}</span><span>{rule.effect === "stop" ? "стоп" : `${rule.points > 0 ? "+" : ""}${rule.points}`}</span></div>
          ))}
          <div style={{ display: "flex", justifyContent: "space-between", paddingTop: 14 }}>
            <span style={{ fontSize: 18, fontWeight: 800 }}>Итого</span>
            <span className="digits" style={{ fontSize: 18, fontWeight: 800 }}>{r.verdict === "manual" ? "—" : `${Math.round(r.score)} из 100`}</span>
          </div>
        </section>

        <div className="side">
          <section className="card lift fu" aria-labelledby="params" style={{ animationDelay: "360ms" }}>
            <h3 id="params" style={{ marginBottom: 8 }}>Ключевые параметры</h3>
            <div className="kv"><span>НМЦК</span><span className="num">{rub(t.nmck)}</span></div>
            <div className="kv"><span>Обеспечение заявки</span><span className="num">{rub(t.app_guarantee_amount)}</span></div>
            <div className="kv"><span>Обеспечение контракта</span><span className="num">{t.contract_guarantee_percent != null ? `${t.contract_guarantee_percent}% · ${rub(t.contract_guarantee_amount)}` : "—"}</span></div>
            <div className="kv"><span>Аванс</span><span>{t.advance_percent != null ? `${t.advance_percent}%` : "в проекте контракта"}</span></div>
            <div className="kv"><span>Место поставки</span><span>{t.delivery_place || "—"}</span></div>
            <div className="kv"><span>Позиций</span><span className="num">{t.items.length}</span></div>
          </section>

          <section className="card lift fu" aria-labelledby="cust" style={{ animationDelay: "420ms" }}>
            <h3 id="cust" style={{ marginBottom: 8 }}>Заказчик по ЕГРЮЛ</h3>
            {card.customer ? (
              <>
                <div className="kv"><span>Организация</span><span>{card.customer.name}</span></div>
                <div className="kv"><span>Статус</span>
                  <span style={{ color: card.customer.status === "ACTIVE" ? "var(--go-fg)" : "var(--skip-fg)" }}>
                    {card.customer.status === "ACTIVE" ? "Действующая" : card.customer.status === "LIQUIDATING" ? "Ликвидируется" : card.customer.status === "BANKRUPT" ? "Банкротство" : card.customer.status}
                  </span>
                </div>
                <div className="kv"><span>ИНН</span><span className="num">{card.customer.inn}</span></div>
                {card.customer.registration_date && <div className="kv"><span>Зарегистрирована</span><span className="num">{new Date(card.customer.registration_date).getFullYear()} г.</span></div>}
                <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>Источник: {card.customer.source === "dadata" ? "DaData" : "демо-данные"}</p>
              </>
            ) : <p className="muted" style={{ margin: 0 }}>Нет данных ЕГРЮЛ по ИНН заказчика{t.customer_inn ? ` ${t.customer_inn}` : ""}</p>}
          </section>

          <section className="card fu" aria-labelledby="fb" style={{ display: "flex", flexDirection: "column", gap: 12, animationDelay: "480ms" }}>
            <h3 id="fb">Вердикт верный?</h3>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>Отметки копятся в отчёте о точности и помогают настраивать веса.</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className={vote === true ? "btn" : "btn2"} onClick={() => sendVote(true)}>Да, верно</button>
              <button type="button" className={vote === false ? "btn" : "btn2"} onClick={() => sendVote(false)}>Нет, ошибка</button>
            </div>
            {vote !== null && <span className="pop" style={{ fontSize: 14, color: "var(--go-fg)", fontWeight: 700 }}>Спасибо, отметка сохранена</span>}
          </section>
        </div>
      </div>

      {raw !== null && (
        <div className="modal-bg" role="dialog" aria-modal="true" aria-label="Исходный файл извещения" onClick={() => setRaw(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid var(--line)" }}>
              <h3>Исходный файл</h3>
              <button type="button" className="btn3" onClick={() => setRaw(null)}>Закрыть</button>
            </div>
            <pre>{raw}</pre>
          </div>
        </div>
      )}
    </>
  );
}
