import { useRef, useState } from "react";
import { api, type CustomerCheck, type ParticipantCheck } from "../api";
import { ErrorBox, VerdictChip } from "../components/common";
import { DocsPicker, FindingList } from "../components/ResultParts";
import { rub } from "../format";

const RISK_CHIP = { high: "skip", warn: "consider", low: "go" } as const;

function parseParticipants(text: string): { inn: string; price: number | null }[] {
  return text.split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [inn, ...rest] = line.split(/[\s;,]+/);
    const price = Number(rest.join("").replace(/[^\d.]/g, ""));
    return { inn: inn.replace(/\D/g, ""), price: price > 0 ? price : null };
  }).filter((p) => p.inn.length >= 10);
}

export function CustomerPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docs, setDocs] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [res, setRes] = useState<CustomerCheck | null>(null);
  const [participantsText, setParticipantsText] = useState("");
  const [participants, setParticipants] = useState<ParticipantCheck[] | null>(null);
  const [pBusy, setPBusy] = useState(false);

  const takeExample = async () => {
    const xml = await fetch("/api/demo/sample.xml").then((r) => r.text());
    setFile(new File([xml], "real_44fz_ef2020_0173100008726000065.xml", { type: "application/xml" }));
  };

  const check = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setParticipants(null);
    try {
      setRes(await api.customerCheck(file, docs));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const checkParticipants = async () => {
    if (!res) return;
    setPBusy(true);
    setError(null);
    try {
      setParticipants((await api.customerParticipants(res.tender, parseParticipants(participantsText))).participants);
    } catch (e) {
      setError(e);
    } finally {
      setPBusy(false);
    }
  };

  const customerFindings = res?.findings ?? [];

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <h1>Заказчику</h1>
            <span className="sticker">защита обеих сторон</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            Проверьте закупку до публикации: что могут обжаловать в ФАС, что отпугнёт поставщиков и насколько надёжны участники.
          </p>
        </div>
      </div>

      <ErrorBox error={error} />

      <section className="card fu" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24, animationDelay: "80ms" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <span className="lbl-big">Извещение и документы</span>
          <button type="button" className="dropzone" style={{ padding: "22px 16px" }} onClick={() => fileInput.current?.click()}>
            <div style={{ fontWeight: 800, wordBreak: "break-all" }}>{file ? file.name : "Выбрать .xml или .json извещения"}</div>
            <div className="muted" style={{ fontSize: 13 }}>{file ? "нажмите, чтобы заменить" : "выгрузка из ЕИС"}</div>
          </button>
          <input ref={fileInput} type="file" accept=".xml,.json" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={takeExample}>Взять реальное извещение из ЕИС</button>
          <DocsPicker files={docs} onChange={setDocs} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, justifyContent: "space-between" }}>
          <div className="muted" style={{ fontSize: 14, display: "flex", flexDirection: "column", gap: 6 }}>
            <span>Что проверяем:</span>
            <span>• срок подачи заявок против минимума 44-ФЗ для способа закупки;</span>
            <span>• сроки оплаты и приёмки, пени и штрафы в проекте контракта;</span>
            <span>• товарные знаки без «или эквивалент» и «только оригинал»;</span>
            <span>• сколько типовых поставщиков захотят участвовать.</span>
          </div>
          <button type="button" className="btn" style={{ minHeight: 56 }} onClick={check} disabled={!file || busy}>
            {busy ? "Проверяю…" : "Проверить закупку"}
          </button>
        </div>
      </section>

      {res && (
        <div className="row">
          <section className="card grow fu" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              <h2 style={{ marginRight: "auto" }}>Риски закупки</h2>
              <span className="chip skip">✕ рисков: {res.summary.high}</span>
              <span className="chip consider">! замечаний: {res.summary.warn}</span>
            </div>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>
              № {res.tender.purchase_number} · {res.tender.subject} · НМЦК {rub(res.tender.nmck)} · проверено за {Math.round(res.elapsed_ms)} мс
            </p>
            <FindingList findings={customerFindings} empty="Нарушений не найдено" />
            {!res.tender.contract && (
              <p className="muted" style={{ margin: 0, fontSize: 13 }}>Проект контракта не приложен — проверены только данные извещения.</p>
            )}
          </section>

          <div className="side">
            <section className="card fu" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <h3>Интерес поставщиков</h3>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className="chip go">✓ {res.interest.counts.go}</span>
                <span className="chip consider">! {res.interest.counts.consider}</span>
                <span className="chip skip">✕ {res.interest.counts.skip}</span>
                <span className="muted" style={{ fontSize: 13, alignSelf: "center" }}>из {res.interest.total} профилей</span>
              </div>
              {res.interest.profiles.map((p) => (
                <div key={p.profile} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                    <b>{p.profile}</b><VerdictChip verdict={p.verdict} />
                  </div>
                  <span className="muted" style={{ fontSize: 13 }}>{p.reason}</span>
                </div>
              ))}
              <span className="muted" style={{ fontSize: 12 }}>{res.interest.note}</span>
            </section>

            <section className="card fu" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <h3>Проверка участников</h3>
              <label htmlFor="parts" className="muted" style={{ fontSize: 14 }}>ИНН и предложенная цена, по одному на строку</label>
              <textarea id="parts" rows={4} value={participantsText} onChange={(e) => setParticipantsText(e.target.value)}
                        placeholder={"5406123450 3900000\n7017123451"} />
              <button type="button" className="btn2" style={{ alignSelf: "flex-start" }} onClick={checkParticipants}
                      disabled={pBusy || !parseParticipants(participantsText).length}>
                {pBusy ? "Проверяю…" : "Проверить участников"}
              </button>
              {participants?.map((p) => (
                <div key={p.inn} style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <b style={{ fontSize: 14 }}>{p.company?.name ?? `ИНН ${p.inn}`}</b>
                    <span className={`chip ${RISK_CHIP[p.risk]}`} style={{ fontSize: 12 }}>{p.risk_name}</span>
                  </div>
                  <span className="muted" style={{ fontSize: 13 }}>ИНН {p.inn}{p.price ? ` · цена ${rub(p.price)}` : ""}</span>
                  <FindingList findings={p.findings} showSide={false} />
                </div>
              ))}
            </section>
          </div>
        </div>
      )}
    </>
  );
}
