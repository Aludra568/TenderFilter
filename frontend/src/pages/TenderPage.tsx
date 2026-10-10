import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, BID_STATUSES, type BidStatus, type TenderCard, type Verdict } from "../api";
import { useApp } from "../App";
import { Bar, CountUp, ErrorBox, Skeleton, VerdictChip } from "../components/common";
import { Radar, type RadarSeries } from "../components/Radar";
import { WhatIf } from "../components/WhatIf";
import { CompanyBlock, DocList, DocsPicker, FactorList, FindingList, KeyParams, ReviewBlock } from "../components/ResultParts";
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
  const [compare, setCompare] = useState<Record<number, boolean>>({});
  const [replay, setReplay] = useState(0);
  const [vote, setVote] = useState<boolean | null>(null);
  const [voteDone, setVoteDone] = useState(false);
  const [raw, setRaw] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [docs, setDocs] = useState<File[]>([]);
  const [docsBusy, setDocsBusy] = useState(false);
  const [bidNote, setBidNote] = useState<string | null>(null);

  useEffect(() => {
    setCard(null);
    setVote(null);
    setCompare({});
    api.tender(Number(id)).then(setCard).catch(setError);
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

  const reload = () => api.tender(Number(id)).then(setCard).catch(setError);

  const uploadDocs = async () => {
    setDocsBusy(true);
    setError(null);
    try {
      await api.attachDocs(card.tender_id, docs);
      setDocs([]);
      await reload();
    } catch (e) {
      setError(e);
    } finally {
      setDocsBusy(false);
    }
  };

  const changeBid = async (status: BidStatus | null) => {
    try {
      const res = await api.setBid(card.tender_id, status);
      setBidNote(res.committed ? `В обеспечениях сейчас занято ${Math.round(res.committed).toLocaleString("ru-RU")} ₽ по ${res.committed_count} заявк${res.committed_count === 1 ? "е" : "ам"}` : null);
      await reload();
    } catch (e) {
      setError(e);
    }
  };

  const sendVote = async (correct: boolean, expected?: Verdict) => {
    setVote(correct);
    setVoteDone(correct || !!expected);
    await api.feedback(card.score_id, correct, expected).catch(() => setVote(null));
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
            <CountUp value={r.score} suffix="%" />
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
          <FactorList result={r} />
        </section>

        <div className="side">
          <section className="card fu" aria-labelledby="whatif" style={{ display: "flex", flexDirection: "column", gap: 10, animationDelay: "300ms" }}>
            <h3 id="whatif">Что если</h3>
            <WhatIf tenderId={card.tender_id} base={r} />
          </section>

          <section className="card fu" aria-labelledby="bid" style={{ display: "flex", flexDirection: "column", gap: 10, animationDelay: "310ms" }}>
            <h3 id="bid">Ваше участие</h3>
            <div className="seg" role="group" aria-label="Статус участия" style={{ borderRadius: 20 }}>
              {(Object.keys(BID_STATUSES) as BidStatus[]).map((s) => (
                <button key={s} type="button" className={card.bid_status === s ? "on" : ""} onClick={() => changeBid(card.bid_status === s ? null : s)}>
                  {BID_STATUSES[s]}
                </button>
              ))}
            </div>
            <span className="muted" style={{ fontSize: 13 }}>
              {bidNote ?? "Отметки учитываются в лимите обеспечений: деньги, замороженные в других заявках, уменьшают свободный лимит."}
            </span>
          </section>

          <section className="card fu" aria-labelledby="docs" style={{ display: "flex", flexDirection: "column", gap: 12, animationDelay: "320ms" }}>
            <h3 id="docs">Документы закупки</h3>
            {t.contract ? (
              <>
                <span className="muted" style={{ fontSize: 13 }}>Разобрано: {t.contract.files.join(", ") || "—"}</span>
                <DocList docs={t.contract.documents} />
                <FindingList findings={t.contract.findings.filter((f) => f.side !== "customer")} empty="Жёстких условий не найдено" />
              </>
            ) : (
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>Приложите проект контракта и ТЗ — найдём сроки оплаты и приёмки, санкции, аванс и требования к конкретной марке.</p>
            )}
            <DocsPicker files={docs} onChange={setDocs} label={t.contract ? "Добавить документы" : "Выбрать документы"} />
            {docs.length > 0 && (
              <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={uploadDocs} disabled={docsBusy}>
                {docsBusy ? "Разбираю…" : "Разобрать и пересчитать"}
              </button>
            )}
          </section>

          <section className="card fu" aria-labelledby="ai" style={{ animationDelay: "330ms" }}>
            <h3 id="ai" style={{ marginBottom: 8 }}>Проверка ИИ</h3>
            <ReviewBlock review={r.review} running={reviewing} onRun={async () => {
              setReviewing(true);
              setError(null);
              try {
                const res = await api.review(card.score_id);
                setCard((c) => (c ? { ...c, result: res.result } : c));
              } catch (e) {
                setError(e);
              } finally {
                setReviewing(false);
              }
            }} />
          </section>

          <section className="card lift fu" aria-labelledby="params" style={{ animationDelay: "360ms" }}>
            <h3 id="params" style={{ marginBottom: 8 }}>Ключевые параметры</h3>
            <KeyParams t={t} />
          </section>

          <section className="card lift fu" aria-labelledby="cust" style={{ animationDelay: "420ms" }}>
            <h3 id="cust" style={{ marginBottom: 8 }}>Заказчик по ЕГРЮЛ</h3>
            <CompanyBlock company={card.customer} empty={`Нет данных ЕГРЮЛ по ИНН заказчика${t.customer_inn ? ` ${t.customer_inn}` : ""}`} />
          </section>

          <section className="card fu" aria-labelledby="fb" style={{ display: "flex", flexDirection: "column", gap: 12, animationDelay: "480ms" }}>
            <h3 id="fb">Вердикт верный?</h3>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>Отметки копятся в отчёте о точности и помогают настраивать веса.</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className={vote === true ? "btn" : "btn2"} onClick={() => sendVote(true)}>Да, верно</button>
              <button type="button" className={vote === false ? "btn" : "btn2"} onClick={() => { setVote(false); setVoteDone(false); }}>Нет, ошибка</button>
            </div>
            {vote === false && !voteDone && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span className="muted" style={{ fontSize: 14 }}>Правильно было бы:</span>
                {(["go", "consider", "skip"] as Verdict[]).filter((v) => v !== r.verdict).map((v) => (
                  <button key={v} type="button" className="btn2" onClick={() => sendVote(false, v)}><VerdictChip verdict={v} /></button>
                ))}
              </div>
            )}
            {voteDone && <span className="pop" style={{ fontSize: 14, color: "var(--go-fg)", fontWeight: 700 }}>Спасибо, отметка сохранена</span>}
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
