import { useEffect, useState } from "react";
import { api, type ScoreResult } from "../api";
import { VerdictChip } from "./common";
import { rub } from "../format";

/** «Что если»: насколько устойчив вердикт к другой НМЦК и другому сроку подачи. */
export function WhatIf({ tenderId, base }: { tenderId: number; base: ScoreResult }) {
  const [pct, setPct] = useState(0);
  const [days, setDays] = useState<number | null>(null);
  const [res, setRes] = useState<{ nmck: number | null; result: ScoreResult } | null>(null);

  useEffect(() => {
    if (pct === 0 && days === null) { setRes(null); return; }
    const t = setTimeout(() => { api.whatIf(tenderId, pct, days).then(setRes).catch(() => setRes(null)); }, 250);
    return () => clearTimeout(t);
  }, [tenderId, pct, days]);

  const r = res?.result ?? base;
  const delta = Math.round(r.score - base.score);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
        <span className="muted">НМЦК {pct > 0 ? "+" : ""}{pct}%{res?.nmck ? ` → ${rub(res.nmck)}` : ""}</span>
        <input type="range" min={-50} max={150} step={10} value={pct} onChange={(e) => setPct(Number(e.target.value))} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
        <span className="muted">До окончания подачи: {days === null ? "как в извещении" : `${days} дн.`}</span>
        <input type="range" min={0} max={20} step={1} value={days ?? 20} onChange={(e) => setDays(Number(e.target.value))} />
      </label>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="digits" style={{ fontSize: 28, fontWeight: 800 }}>{Math.round(r.score)}%</span>
        <VerdictChip verdict={r.verdict} />
        {res && <span className="muted" style={{ fontSize: 14 }}>{delta === 0 ? "без изменений" : `${delta > 0 ? "+" : ""}${delta} п.`}</span>}
      </div>
      {(pct !== 0 || days !== null) && (
        <button type="button" className="btn3" style={{ alignSelf: "flex-start" }} onClick={() => { setPct(0); setDays(null); }}>Вернуть как есть</button>
      )}
    </div>
  );
}
