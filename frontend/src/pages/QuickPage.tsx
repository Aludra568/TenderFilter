import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Company, type QuickResult } from "../api";
import { CountUp, ErrorBox, VerdictChip } from "../components/common";
import { Radar } from "../components/Radar";
import { EisNumberLoader } from "../components/EisNumberLoader";
import { CompanyBlock, DocsPicker, FactorList, FindingList, KeyParams, ReviewBlock } from "../components/ResultParts";

const EXAMPLE_CRITERIA =
  "Работаем в Москве и Московской области. НМЦК от 1 до 150 млн. На обеспечения готовы отвлечь не больше 15 млн. " +
  "На заявку нужно минимум 3 дня. Конкурсы не любим. Поставляем ноутбуки, компьютеры и серверы.";
const DEMO_INN = "5406123450";
const LIMIT_MS = 10_000;

const STEPS: [keyof QuickResult["timings"], string][] = [
  ["parse_ms", "Разбор XML"],
  ["documents_ms", "Документы"],
  ["egrul_ms", "ЕГРЮЛ"],
  ["criteria_ms", "Критерии"],
  ["scoring_ms", "Скоринг"],
  ["review_ms", "Проверка ИИ"],
];

function innValid(inn: string) {
  return /^\d{10}$|^\d{12}$/.test(inn.trim());
}

export function QuickPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docs, setDocs] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [inn, setInn] = useState("");
  const [company, setCompany] = useState<Company | null>(null);
  const [innError, setInnError] = useState<string | null>(null);
  const [innLoading, setInnLoading] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [res, setRes] = useState<QuickResult | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCompany(null);
    setInnError(null);
    if (!inn.trim()) return;
    if (!innValid(inn)) {
      if (inn.trim().length >= 10) setInnError("ИНН — 10 цифр у организации или 12 у ИП");
      return;
    }
    setInnLoading(true);
    const t = setTimeout(() => {
      api.company(inn.trim())
        .then(setCompany)
        .catch((e) => setInnError(e instanceof ApiError ? e.message : "Не удалось получить данные ЕГРЮЛ"))
        .finally(() => setInnLoading(false));
    }, 400);
    return () => { clearTimeout(t); setInnLoading(false); };
  }, [inn]);

  const takeExample = async () => {
    const xml = await fetch("/api/demo/sample.xml").then((r) => r.text());
    setFile(new File([xml], "real_44fz_ef2020_0173100008726000065.xml", { type: "application/xml" }));
  };

  const run = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.quickScore(file, inn, text, docs);
      setRes(r);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const r = res?.result;
  const total = res?.timings.total_ms ?? 0;

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <h1>Быстрая оценка</h1>
            <span className="sticker">3 шага · &lt; 10 с</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>Выгрузка из ЕИС, ИНН вашей компании и параметры обычным текстом — оценка и рекомендация с обоснованием.</p>
        </div>
      </div>

      <section className="card fu" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24, animationDelay: "80ms" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <span className="lbl-big"><span className="digits" style={{ color: "var(--violet)" }}>1</span> · Извещение ЕИС</span>
          <div
            className={`dropzone${over ? " over" : ""}`}
            style={{ padding: "26px 16px" }}
            role="button"
            tabIndex={0}
            aria-label="Выбрать файл извещения"
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); setFile(e.dataTransfer.files[0] ?? null); }}
          >
            {file ? (
              <>
                <div style={{ fontWeight: 800, wordBreak: "break-all" }}>{file.name}</div>
                <div className="muted" style={{ fontSize: 13 }}>{(file.size / 1024).toFixed(0)} КБ · нажмите, чтобы заменить</div>
              </>
            ) : (
              <>
                <div style={{ fontWeight: 800 }}>Перетащите .xml или .json</div>
                <div className="muted" style={{ fontSize: 13 }}>44-ФЗ и 223-ФЗ · или нажмите для выбора</div>
              </>
            )}
            <input ref={fileInput} type="file" accept=".xml,.json" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <EisNumberLoader onFile={setFile} />
          <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={takeExample}>Взять реальное извещение из ЕИС</button>
          <DocsPicker files={docs} onChange={setDocs} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label className="lbl-big" htmlFor="inn"><span className="digits" style={{ color: "var(--violet)" }}>2</span> · ИНН вашей компании</label>
          <input id="inn" className="input num" inputMode="numeric" maxLength={12} placeholder="10 или 12 цифр" value={inn}
                 onChange={(e) => setInn(e.target.value.replace(/\D/g, ""))} />
          {innLoading && <span className="muted" style={{ fontSize: 14 }}>Ищу в ЕГРЮЛ…</span>}
          {innError && <span className="unparsed">{innError}</span>}
          {company && (
            <div className="pop" style={{ background: "var(--tint)", borderRadius: 16, padding: "12px 16px", fontSize: 14 }}>
              <div style={{ fontWeight: 800 }}>{company.name}</div>
              <div className="muted">
                {company.status === "ACTIVE" ? "действующая" : "недействующая"}
                {company.region_name ? ` · ${company.region_name}` : ""}
                {company.is_msp ? " · в реестре МСП" : company.is_msp === false ? " · не МСП" : ""}
                {company.okveds[0] ? ` · ОКВЭД ${company.okveds[0].code}` : ""}
              </div>
            </div>
          )}
          <div className="help">Без ИНН возьмём компанию из вашего профиля. Данные — ЕГРЮЛ и реестр МСП ФНС.</div>
          <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={() => setInn(DEMO_INN)}>Демо-компания</button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label className="lbl-big" htmlFor="crit"><span className="digits" style={{ color: "var(--violet)" }}>3</span> · Параметры скоринга</label>
          <textarea id="crit" rows={6} value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="Например: работаем в Сибири, НМЦК до 30 млн, конкурсы не берём, аванс важен" />
          <div className="help">Пусто — используем настройки профиля.</div>
          <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={() => setText(EXAMPLE_CRITERIA)}>Пример формулировки</button>
        </div>

        <div style={{ gridColumn: "1 / -1", display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn" style={{ minHeight: 56, fontSize: 17, padding: "0 32px" }} onClick={run} disabled={!file || busy || !!innError}>
            {busy ? "Оцениваю…" : "Оценить закупку"}
          </button>
          {!file && <span className="muted" style={{ fontSize: 14 }}>Сначала выберите файл извещения</span>}
        </div>
      </section>

      <ErrorBox error={error} />

      {res && r && (
        <div ref={resultRef} style={{ display: "flex", flexDirection: "column", gap: 24, scrollMarginTop: 96 }}>
          <div className="row" style={{ alignItems: "stretch" }}>
            <section className="card dark side fu" style={{ gap: 14 }} aria-label="Итоговая оценка">
              <div aria-hidden="true" style={{ position: "absolute", width: 260, height: 260, borderRadius: "50%", right: -80, top: -90, background: "radial-gradient(circle, rgba(124,92,255,.75), rgba(124,92,255,0) 70%)" }} />
              <div className="muted" style={{ position: "relative", fontWeight: 600 }}>{res.tender.subject}</div>
              <span className="digits" style={{ position: "relative", fontSize: 88, lineHeight: 1, fontWeight: 800 }}>
                <CountUp value={r.score} suffix="%" />
              </span>
              <span className="pop" style={{ position: "relative", alignSelf: "flex-start", animationDelay: ".9s" }}><VerdictChip verdict={r.verdict} big /></span>
              <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }} className="muted">
                <span style={{ color: "#fff", fontWeight: 600 }}>{r.main_reason}</span>
                {r.stops.slice(1).map((s) => <span key={s} style={{ color: "#ffb3c1", fontWeight: 700 }}>Стоп-фактор: {s}</span>)}
                {r.flags.map((f) => <span key={f} style={{ color: "#ffe08a", fontWeight: 600 }}>⚑ {f}</span>)}
                <span>Полнота данных: {Math.round(r.completeness * 100)}%</span>
              </div>
              <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                <span style={{ fontWeight: 700, fontSize: 14 }}>
                  Время: <span className="digits">{(total / 1000).toFixed(2).replace(".", ",")} с</span> <span className="muted">из 10 с по ТЗ</span>
                </span>
                <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: "rgba(255,255,255,.15)" }} aria-hidden="true">
                  {STEPS.map(([k], i) => (
                    <span key={k} style={{ width: `${Math.max(0.5, ((res.timings[k] ?? 0) / LIMIT_MS) * 100)}%`, background: ["#3ddc97", "#94a3b8", "#ffc93d", "#ff4fa3", "#7c5cff", "#38bdf8"][i] }} />
                  ))}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 13 }} className="muted">
                  {STEPS.filter(([k]) => res.timings[k] !== undefined).map(([k, label]) => <span key={k}>{label}: {(res.timings[k] ?? 0).toString().replace(".", ",")} мс</span>)}
                </div>
              </div>
            </section>
            <section className="card grow fu" style={{ animationDelay: "120ms" }}>
              <h2 style={{ marginBottom: 4 }}>Профиль закупки</h2>
              <p className="muted" style={{ margin: "0 0 8px", fontSize: 15 }}>7 групп факторов. Зелёный пунктир — порог «Участвовать».</p>
              <Radar labels={r.factors.map((f) => f.label)} values={r.factors.map((f) => f.score)} weights={r.factors.map((f) => f.weight)}
                     threshold={(res.preferences?.thresholds?.go ?? 75) / 100} replayKey={total} />
            </section>
          </div>

          <div className="row">
            <section className="card grow fu" style={{ animationDelay: "200ms" }}>
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                <h2>Почему такая оценка</h2>
                {res.tender_id && <Link to={`/tenders/${res.tender_id}`} className="btn3">Добавлено в ленту →</Link>}
              </div>
              <FactorList result={r} />
            </section>
            <div className="side">
              {res.tender.contract && (
                <section className="card fu" style={{ animationDelay: "210ms" }}>
                  <h3 style={{ marginBottom: 8 }}>Риски контракта</h3>
                  <FindingList findings={res.tender.contract.findings.filter((f) => f.side !== "customer")}
                               empty="Жёстких условий в документах не найдено" />
                </section>
              )}
              {r.review && (
                <section className="card fu" style={{ animationDelay: "220ms" }}>
                  <h3 style={{ marginBottom: 8 }}>Проверка ИИ</h3>
                  <ReviewBlock review={r.review} />
                </section>
              )}
              {res.criteria && (
                <section className="card fu" style={{ animationDelay: "240ms" }}>
                  <h3 style={{ marginBottom: 8 }}>Как поняты параметры</h3>
                  <div className="recognized">
                    <span className="muted" style={{ fontSize: 13 }}>
                      {res.criteria.engine.startsWith("rules+llm") ? "Правила + LLM" : res.criteria.engine === "rules" ? "Правила" : res.criteria.engine}
                      {" · "}{res.criteria.elapsed_ms.toString().replace(".", ",")} мс
                    </span>
                    {res.criteria.recognized.map((x, i) => (
                      <div key={i}><span className="chip go" style={{ fontSize: 12 }}>✓</span><span><b>{x.label}</b> <span className="muted">← «{x.source_text}»</span></span></div>
                    ))}
                    {res.criteria.unparsed.map((u) => <div key={u} className="unparsed">Не понял: «{u}»</div>)}
                  </div>
                </section>
              )}
              <section className="card lift fu" style={{ animationDelay: "280ms" }}>
                <h3 style={{ marginBottom: 8 }}>Параметры закупки</h3>
                <KeyParams t={res.tender} />
              </section>
              <section className="card lift fu" style={{ animationDelay: "320ms" }}>
                <h3 style={{ marginBottom: 8 }}>Ваша компания по ЕГРЮЛ</h3>
                <CompanyBlock company={res.company} empty="Компания не указана" />
              </section>
              <section className="card lift fu" style={{ animationDelay: "360ms" }}>
                <h3 style={{ marginBottom: 8 }}>Заказчик по ЕГРЮЛ</h3>
                <CompanyBlock company={res.customer} empty={`Нет данных по ИНН заказчика${res.tender.customer_inn ? ` ${res.tender.customer_inn}` : ""}`} />
              </section>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
