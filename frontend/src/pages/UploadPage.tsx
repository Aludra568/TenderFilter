import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Batch } from "../api";
import { ErrorBox, ScoreRing, VerdictChip } from "../components/common";
import { rub } from "../format";

export function UploadPage() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [started, setStarted] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let stop = false;
    const poll = async () => {
      try {
        const b = await api.batchStatus(batchId);
        if (stop) return;
        setBatch(b);
        if (b.status !== "done" && b.status !== "failed") setTimeout(poll, 600);
      } catch (e) {
        setError(e);
      }
    };
    poll();
    return () => { stop = true; };
  }, [batchId]);

  const handle = async (files: File[]) => {
    if (!files.length) return;
    setError(null);
    setBusy(true);
    setBatch(null);
    try {
      const single = files.length === 1 && !files[0].name.toLowerCase().endsWith(".zip");
      if (single) {
        const res = await api.upload(files[0]);
        navigate(`/tenders/${res.tender_id}`);
      } else {
        setStarted(Date.now());
        const res = await api.batch(files);
        setBatchId(res.batch_id);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const pct = batch ? Math.round((batch.processed / Math.max(1, batch.total)) * 100) : 0;
  const seconds = batch?.status === "done" && started ? ((Date.now() - started) / 1000).toFixed(1).replace(".", ",") : null;

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h1>Загрузка извещений</h1>
          <p className="muted" style={{ margin: 0 }}>XML или JSON из ЕИС (44-ФЗ и 223-ФЗ) — по одному или пачкой в ZIP. Пачка обрабатывается в очереди.</p>
        </div>
        <a className="btn2" href="/api/demo/batch.zip">Скачать демо-пакет</a>
      </div>

      <ErrorBox error={error} />

      <div
        className={`dropzone fu${over ? " over" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Выбрать файлы извещений"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handle(Array.from(e.dataTransfer.files)); }}
        style={{ animationDelay: "80ms" }}
      >
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="url(#ug)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <defs><linearGradient id="ug" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#E8003D" /><stop offset="1" stopColor="#7C5CFF" /></linearGradient></defs>
          <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
        </svg>
        <h2 style={{ fontSize: 24, fontWeight: 800, margin: "12px 0 6px" }}>{busy ? "Загружаю…" : "Перетащите файлы сюда"}</h2>
        <p className="muted" style={{ margin: 0 }}>или нажмите, чтобы выбрать · .xml, .json, .zip до 100 МБ</p>
        <input ref={input} type="file" multiple accept=".xml,.json,.zip" hidden onChange={(e) => handle(Array.from(e.target.files ?? []))} />
      </div>

      {batch && (
        <section className="card fu" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="field-head">
            <h2>Пакет № {batch.id}</h2>
            <span className="muted num">
              {batch.processed} из {batch.total}{batch.failed ? ` · ошибок: ${batch.failed}` : ""}{seconds ? ` · ${seconds} с` : ""}
            </span>
          </div>
          <div className="progress" aria-label={`Обработано ${pct}%`}><span style={{ width: `${pct}%` }} /></div>
          {batch.errors.map((e) => <div key={e.file} className="unparsed"><b>{e.file}</b>: {e.error}</div>)}
          {batch.status === "done" && (
            <div className="table-wrap">
              <table className="feed">
                <thead><tr><th>Оценка</th><th>Вердикт</th><th>Закупка</th><th style={{ textAlign: "right" }}>НМЦК</th><th>Причина</th></tr></thead>
                <tbody>
                  {batch.items.map((item, i) => (
                    <tr key={item.tender_id} style={{ animationDelay: `${Math.min(i, 15) * 45}ms` }}>
                      <td><ScoreRing score={item.score} verdict={item.verdict} manual={item.verdict === "manual"} /></td>
                      <td><VerdictChip verdict={item.verdict} /></td>
                      <td><Link className="subject" to={`/tenders/${item.tender_id}`}>{item.subject}</Link><div className="meta">{item.region_name}</div></td>
                      <td className="num" style={{ textAlign: "right", fontWeight: 800 }}>{rub(item.nmck)}</td>
                      <td style={{ fontSize: 14 }}>{item.main_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
