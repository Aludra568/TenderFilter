import { useEffect, useState } from "react";
import { api, type Accuracy, type Health, type LogEntry, type Verdict } from "../api";
import { CountUp, ErrorBox, Skeleton, VerdictChip } from "../components/common";

const ORDER: Verdict[] = ["go", "consider", "skip"];

export function AccuracyPage() {
  const [acc, setAcc] = useState<Accuracy | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.accuracy().then(setAcc).catch(setError);
    api.health().then(setHealth).catch(() => {});
    api.logs(40).then(setLogs).catch(() => {});
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!acc) return <Skeleton height={400} />;
  const g = acc.golden;

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h1>Точность скоринга</h1>
          <p className="muted" style={{ margin: 0 }}>Эталонный набор размечен вручную до запуска модели. Отчёт обновляется командой <code>make eval</code>.</p>
        </div>
      </div>

      <section className="summary">
        <div className="card fu lift">
          <span className="muted" style={{ fontWeight: 700 }}>Совпадение вердикта</span>
          <div className="big digits" style={{ fontSize: 52, fontWeight: 800 }}>{g ? <CountUp value={g.accuracy * 100} suffix="%" /> : "—"}</div>
          <span className="muted" style={{ fontSize: 13 }}>{g ? `${g.correct} из ${g.cases} сценариев · порог ТЗ 80%` : "запустите make eval"}</span>
        </div>
        <div className="card fu lift" style={{ animationDelay: "80ms" }}>
          <span className="muted" style={{ fontWeight: 700 }}>Критических ошибок</span>
          <div className="big digits" style={{ fontSize: 52, fontWeight: 800 }}>{g ? <CountUp value={g.critical_errors} /> : "—"}</div>
          <span className="muted" style={{ fontSize: 13 }}>«участвовать» там, где нужно было пропустить</span>
        </div>
        <div className="card fu lift" style={{ animationDelay: "160ms" }}>
          <span className="muted" style={{ fontWeight: 700 }}>Время оценки</span>
          <div className="big digits" style={{ fontSize: 52, fontWeight: 800 }}><CountUp value={acc.timing_ms.avg} decimals={1} suffix=" мс" /></div>
          <span className="muted" style={{ fontSize: 13 }}>в среднем, максимум {acc.timing_ms.max.toFixed(1).replace(".", ",")} мс · лимит ТЗ 10 000 мс</span>
        </div>
        <div className="card fu lift" style={{ animationDelay: "240ms" }}>
          <span className="muted" style={{ fontWeight: 700 }}>Отметки пользователей</span>
          <div className="big digits" style={{ fontSize: 52, fontWeight: 800 }}>{acc.feedback.rate != null ? <CountUp value={acc.feedback.rate * 100} suffix="%" /> : "—"}</div>
          <span className="muted" style={{ fontSize: 13 }}>{acc.feedback.total} отметок «вердикт верный / неверный»</span>
        </div>
      </section>

      {g && (
        <div className="row">
          <section className="card grow fu" style={{ animationDelay: "300ms" }}>
            <h2 style={{ marginBottom: 12 }}>Сценарии</h2>
            <div className="table-wrap">
              <table className="feed" style={{ minWidth: 760 }}>
                <thead><tr><th>Кейс</th><th>Ожидалось</th><th>Получено</th><th>Почему так должно быть</th></tr></thead>
                <tbody>
                  {g.rows.map((r) => (
                    <tr key={r.id} style={{ background: r.ok ? undefined : "#fff4f6" }}>
                      <td className="num" style={{ fontWeight: 700 }}>{r.ok ? "✓" : "✕"} {r.id}</td>
                      <td><VerdictChip verdict={r.expected} /></td>
                      <td><VerdictChip verdict={r.actual} /></td>
                      <td style={{ fontSize: 14 }}>{r.why}{!r.ok && <div className="meta">Модель: {r.reason}</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <div className="side">
            <section className="card fu" style={{ animationDelay: "360ms" }}>
              <h3 style={{ marginBottom: 12 }}>Матрица ошибок</h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr><th style={{ textAlign: "left" }} className="muted">ожид. \ получ.</th>{ORDER.map((v) => <th key={v} style={{ fontSize: 18 }} title={v}>{({ go: "✓", consider: "!", skip: "✕" })[v]}</th>)}</tr>
                </thead>
                <tbody>
                  {ORDER.map((e) => (
                    <tr key={e}>
                      <td style={{ padding: "8px 0" }}><VerdictChip verdict={e} /></td>
                      {ORDER.map((a) => {
                        const n = g.confusion[e][a];
                        return <td key={a} className="digits" style={{ textAlign: "center", fontWeight: 800, background: n ? (e === a ? "var(--go-bg)" : "var(--skip-bg)") : undefined, borderRadius: 10 }}>{n || ""}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            {health && (
              <section className="card fu" style={{ animationDelay: "420ms" }}>
                <h3 style={{ marginBottom: 8 }}>Компоненты</h3>
                <div className="kv"><span>LLM для разбора критериев</span><span>{health.llm.ready ? `${health.llm.provider} · ${health.llm.model}` : "правила (LLM не подключена)"}</span></div>
                <div className="kv"><span>Источник ЕГРЮЛ</span><span>{(health.egrul_chain ?? [health.egrul_provider]).map((x) => ({ dadata: "DaData", mock: "демо-данные", fns: "ФНС без ключа" } as Record<string, string>)[x] ?? x).join(" → ")}</span></div>
                <div className="kv"><span>Очередь задач</span><span>{health.queue === "celery" ? "Celery + Redis" : "в процессе API"}</span></div>
              </section>
            )}
          </div>
        </div>
      )}

      <section className="card fu" style={{ animationDelay: "480ms" }}>
        <div className="field-head" style={{ marginBottom: 8 }}>
          <h2>Журнал событий</h2>
          <span className="muted" style={{ fontSize: 14 }}>хранится в PostgreSQL · GET /api/logs</span>
        </div>
        {logs.length === 0 ? <p className="muted" style={{ margin: 0 }}>Событий пока нет</p> : (
          <div className="table-wrap">
            <table className="feed" style={{ minWidth: 720 }}>
              <thead><tr><th>Время</th><th>Событие</th><th>Что произошло</th><th style={{ textAlign: "right" }}>Длительность</th></tr></thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id}>
                    <td className="num muted" style={{ whiteSpace: "nowrap", fontSize: 13 }}>{new Date(l.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                    <td><span className={`chip ${l.level === "info" ? "manual" : "consider"}`} style={{ fontSize: 12 }}>{l.event_name}</span></td>
                    <td style={{ fontSize: 14 }}>{l.message}</td>
                    <td className="num" style={{ textAlign: "right", whiteSpace: "nowrap", fontSize: 14 }}>{l.duration_ms != null ? `${l.duration_ms.toString().replace(".", ",")} мс` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
