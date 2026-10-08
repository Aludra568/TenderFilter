import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Feed, type Verdict } from "../api";
import { useApp } from "../App";
import { CountUp, ErrorBox, ScoreRing, Skeleton, VerdictChip } from "../components/common";
import { LAW, VERDICT, deadlineInfo, rub } from "../format";

const TABS: [Verdict | "", string][] = [["", "Все"], ["go", "Участвовать"], ["consider", "Рассмотреть"], ["skip", "Не участвовать"], ["manual", "Вручную"]];
const HINT: Record<Verdict, string> = {
  go: "можно подавать заявку",
  consider: "есть оговорки — посмотрите причины",
  skip: "стоп-факторы или слабое совпадение",
  manual: "не хватает данных в извещении",
};

export function FeedPage() {
  const { profile } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const verdict = (params.get("verdict") || "") as Verdict | "";
  const sort = params.get("sort") || "score";
  const [q, setQ] = useState(params.get("q") || "");
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (q) next.set("q", q); else next.delete("q");
      if (next.toString() !== params.toString()) setParams(next, { replace: true });
    }, 300);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setError(null);
    api.feed({ verdict: verdict || undefined, sort, q: params.get("q") || undefined, limit: "200" })
      .then(setFeed)
      .catch(setError);
  }, [verdict, sort, params, profile?.version]);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  };

  const updated = useMemo(() => new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }), [feed]);

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <h1>Лента закупок</h1>
            {feed && <span className="sticker">{feed.counts.go} к подаче</span>}
          </div>
          <p className="muted" style={{ margin: 0 }}>
            {profile ? `Профиль «${profile.name}» · версия ${profile.version}` : "Профиль загружается"}
            {feed ? ` · ${feed.total} извещений · пересчитано в ${updated}` : ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <a className="btn2" href="/api/feed/export?format=xlsx">Экспорт в XLSX</a>
          <Link className="btn" to="/upload">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 20h16" /></svg>
            Загрузить извещения
          </Link>
        </div>
      </div>

      <ErrorBox error={error} />

      <section className="summary" aria-label="Сводка по вердиктам">
        {(["go", "consider", "skip", "manual"] as Verdict[]).map((v, i) => (
          <button
            key={v}
            type="button"
            className={`card sum-card fu${verdict === v ? " on" : ""}`}
            style={{ animationDelay: `${80 + i * 70}ms` }}
            aria-pressed={verdict === v}
            onClick={() => set("verdict", verdict === v ? "" : v)}
          >
            <span className="glow" style={{ background: `radial-gradient(circle, ${VERDICT[v].glow}, transparent 70%)` }} />
            <span style={{ position: "relative", display: "flex", alignItems: "center", gap: 8, fontWeight: 700, color: "var(--ink-2)" }}>
              <span className={`dot chip ${v}`} style={{ padding: 0 }}>{VERDICT[v].icon}</span>
              {VERDICT[v].label}
            </span>
            <span className="big digits">{feed ? <CountUp value={feed.counts[v]} /> : "·"}</span>
            <span className="muted" style={{ position: "relative", fontSize: 13 }}>
              {v === "skip" && feed ? `из них ${feed.stop_count} — стоп-факторы` : HINT[v]}
            </span>
          </button>
        ))}
      </section>

      <section className="card fu" style={{ padding: 0, overflow: "hidden", animationDelay: "300ms" }}>
        <div className="toolbar">
          <label className="search">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#55577A" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
            <span className="sr-only">Поиск по закупкам</span>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер, предмет, заказчик — поиск понимает смысл" />
          </label>
          <div className="seg" role="group" aria-label="Фильтр по вердикту">
            {TABS.map(([key, label]) => (
              <button key={key} type="button" className={verdict === key ? "on" : ""} aria-pressed={verdict === key} onClick={() => set("verdict", key)}>
                {label}
              </button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Сортировка">
            {[["score", "По оценке"], ["deadline", "По сроку"], ["nmck", "По НМЦК"]].map(([key, label]) => (
              <button key={key} type="button" className={sort === key ? "on" : ""} onClick={() => set("sort", key === "score" ? "" : key)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="table-wrap">
          {!feed ? (
            <div style={{ padding: 18, display: "grid", gap: 12 }}>
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={64} />)}
            </div>
          ) : feed.items.length === 0 ? (
            <p className="muted" style={{ padding: "24px 18px", margin: 0 }}>Ничего не нашлось. Попробуйте другой фильтр или запрос.</p>
          ) : (
            <table className="feed">
              <thead>
                <tr>
                  <th style={{ width: 96 }}>Оценка</th>
                  <th style={{ width: 190 }}>Вердикт</th>
                  <th>Закупка</th>
                  <th style={{ textAlign: "right" }}>НМЦК</th>
                  <th>Подача до</th>
                  <th style={{ width: 280 }}>Главная причина</th>
                </tr>
              </thead>
              <tbody>
                {feed.items.map((item, i) => {
                  const dl = deadlineInfo(item.submission_deadline);
                  return (
                    <tr key={item.tender_id} style={{ animationDelay: `${Math.min(i, 15) * 45}ms`, cursor: "pointer" }}
                        onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/tenders/${item.tender_id}`); }}>
                      <td><ScoreRing score={item.score} verdict={item.verdict} manual={item.verdict === "manual"} /></td>
                      <td><VerdictChip verdict={item.verdict} /></td>
                      <td>
                        <Link className="subject" to={`/tenders/${item.tender_id}`}>{item.subject}</Link>
                        <div className="meta num">
                          № {item.purchase_number} · {LAW(item.law)} · {item.procedure_name}{item.region_name ? ` · ${item.region_name}` : ""}
                          {item.smp_only ? " · только СМП" : ""}
                        </div>
                      </td>
                      <td className="num" style={{ textAlign: "right", whiteSpace: "nowrap", fontWeight: 800 }}>{rub(item.nmck)}</td>
                      <td className="num" style={{ whiteSpace: "nowrap" }}>
                        {dl.date}
                        <div style={{ marginTop: 4 }}>
                          {dl.urgent ? <span className="sticker" style={{ fontSize: 12, padding: "3px 8px", transform: "rotate(-3deg)" }}>{dl.left}</span>
                            : <span className="muted" style={{ fontSize: 13 }}>{dl.left}</span>}
                        </div>
                      </td>
                      <td style={{ color: "var(--ink-2)", fontSize: 14 }}>{item.main_reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        {feed && (
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "16px 18px", fontSize: 14, borderTop: "1px solid var(--line)" }} className="muted">
            <span>Показано {feed.items.length} из {feed.total} · оценки пересчитываются при каждом изменении профиля</span>
            <a href="/api/feed/export?format=csv" className="btn3">CSV</a>
          </div>
        )}
      </section>
    </>
  );
}
