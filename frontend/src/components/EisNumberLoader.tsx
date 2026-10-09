import { useState } from "react";

/** Загрузка извещения 44-ФЗ из ЕИС по реестровому номеру (публичная печатная форма, без токена). */
export function EisNumberLoader({ onFile }: { onFile: (f: File) => void }) {
  const [num, setNum] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ok = /^\d{19}$/.test(num);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/eis/notice/${num}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? "ЕИС не ответила");
      }
      onFile(new File([await res.text()], `${num}.xml`, { type: "application/xml" }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Не удалось загрузить");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="input num" inputMode="numeric" maxLength={19} placeholder="или номер закупки, 19 цифр" value={num}
               aria-label="Реестровый номер закупки в ЕИС" style={{ flex: "1 1 200px" }}
               onChange={(e) => setNum(e.target.value.replace(/\D/g, ""))} onKeyDown={(e) => e.key === "Enter" && ok && load()} />
        <button type="button" className="btn2" onClick={load} disabled={!ok || busy}>{busy ? "Загружаю…" : "Из ЕИС"}</button>
      </div>
      {err && <span className="unparsed">{err}</span>}
    </div>
  );
}
