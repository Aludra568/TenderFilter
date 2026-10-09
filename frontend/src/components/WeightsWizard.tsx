import { useEffect, useState } from "react";
import { api, type FactorSchema, type Prefs, type WeightQuestion, type WeightsResult } from "../api";
import { ErrorBox } from "./common";

/** Позиция ползунка −8…8 → шкала Саати: 0 — равны, +k — левый важнее в k+1 раз, −k — правый важнее. */
const saaty = (s: number) => (s >= 0 ? s + 1 : 1 / (1 - s));

function pairLabel(q: WeightQuestion, s: number): string {
  if (s === 0) return "одинаково важны";
  const times = Math.abs(s) + 1;
  const word = times >= 2 && times <= 4 ? "раза" : "раз";
  return `${s > 0 ? q.a_label : q.b_label} важнее в ${times} ${word}`;
}

interface Props {
  factors: FactorSchema[];
  draft: Prefs;
  onApply: (weights: Record<string, number>, method: "roc" | "ahp") => void;
  onReset: () => void;
}

export function WeightsWizard({ factors, draft, onApply, onReset }: Props) {
  const [mode, setMode] = useState<"roc" | "ahp">("roc");
  const [ranking, setRanking] = useState<string[]>(() => {
    const w = (f: FactorSchema) => draft.weights?.[f.key] ?? f.base_weight * (draft[f.key]?.importance ?? 3);
    return [...factors].sort((a, b) => w(b) - w(a)).map((f) => f.key);
  });
  const [questions, setQuestions] = useState<WeightQuestion[]>([]);
  const [answers, setAnswers] = useState<number[]>([]);
  const [result, setResult] = useState<WeightsResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const label = (k: string) => factors.find((f) => f.key === k)?.label ?? k;

  useEffect(() => {
    if (mode === "ahp" && !questions.length) {
      api.weightQuestions().then((r) => { setQuestions(r.pairs); setAnswers(r.pairs.map(() => 0)); }).catch(setError);
    }
  }, [mode, questions.length]);

  const move = (i: number, d: number) => {
    const next = [...ranking];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setRanking(next);
    setResult(null);
  };

  const compute = async () => {
    setError(null);
    try {
      setResult(mode === "roc"
        ? await api.weights({ method: "roc", ranking })
        : await api.weights({ method: "ahp", pairs: questions.map((q, i) => ({ a: q.a, b: q.b, value: saaty(answers[i]) })) }));
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="field">
      <div className="field-head">
        <div>
          <div className="lbl-big">Мастер весов</div>
          <div className="help">
            {draft.weights && Object.keys(draft.weights).length
              ? `Сейчас веса заданы мастером (${draft.weights_method === "ahp" ? "МАИ" : "ранжирование"}) и заменяют ползунки важности.`
              : "Вместо ползунков: расставьте факторы по порядку или ответьте, что важнее и во сколько раз."}
          </div>
        </div>
        <div className="seg" role="group" aria-label="Метод весов">
          <button type="button" className={mode === "roc" ? "on" : ""} onClick={() => { setMode("roc"); setResult(null); }}>По порядку</button>
          <button type="button" className={mode === "ahp" ? "on" : ""} onClick={() => { setMode("ahp"); setResult(null); }}>Попарно (МАИ)</button>
        </div>
      </div>

      {mode === "roc" ? (
        <ol style={{ margin: 0, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 6 }}>
          {ranking.map((k, i) => (
            <li key={k} style={{ fontWeight: 600 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8, width: "100%" }}>
                <span style={{ flex: 1 }}>{label(k)}</span>
                <button type="button" className="btn2" style={{ minHeight: 36, padding: "0 12px" }} disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Поднять «${label(k)}»`}>↑</button>
                <button type="button" className="btn2" style={{ minHeight: 36, padding: "0 12px" }} disabled={i === ranking.length - 1} onClick={() => move(i, 1)} aria-label={`Опустить «${label(k)}»`}>↓</button>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        questions.map((q, i) => (
          <label key={`${q.a}-${q.b}`} style={{ display: "grid", gridTemplateColumns: "1fr", gap: 4, fontSize: 14 }}>
            <span style={{ display: "flex", justifyContent: "space-between", gap: 8, fontWeight: 600 }}>
              <span>{q.a_label}</span><span>{q.b_label}</span>
            </span>
            <input type="range" min={-8} max={8} step={1} value={-(answers[i] ?? 0)} style={{ direction: "ltr" }}
                   onChange={(e) => { const next = [...answers]; next[i] = -Number(e.target.value); setAnswers(next); setResult(null); }} />
            <span className="muted" style={{ textAlign: "center" }}>{pairLabel(q, answers[i] ?? 0)}</span>
          </label>
        ))
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="btn" onClick={compute}>Рассчитать веса</button>
        {result && <button type="button" className="btn2" onClick={() => onApply(result.weights, result.method)}>Применить</button>}
        {draft.weights && Object.keys(draft.weights).length > 0 && (
          <button type="button" className="btn2" onClick={onReset}>Вернуть ползунки</button>
        )}
      </div>
      <ErrorBox error={error} />

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {Object.entries(result.weights).sort((a, b) => b[1] - a[1]).map(([k, w]) => (
            <div key={k} style={{ display: "grid", gridTemplateColumns: "minmax(110px, 1fr) 3fr 48px", alignItems: "center", gap: 10, fontSize: 14 }}>
              <span>{label(k)}</span>
              <span style={{ height: 10, borderRadius: 5, background: "var(--line)", overflow: "hidden" }}>
                <span style={{ display: "block", height: "100%", width: `${w * 100}%`, background: "var(--grad)", borderRadius: 5, transition: "width .45s cubic-bezier(.34,1.3,.64,1)" }} />
              </span>
              <span className="digits" style={{ textAlign: "right", fontWeight: 700 }}>{Math.round(w * 100)}%</span>
            </div>
          ))}
          {result.cr !== null && (
            <span className={`chip ${result.consistent ? "go" : "consider"}`} style={{ alignSelf: "flex-start", whiteSpace: "normal" }}>
              Согласованность ответов CR = {result.cr.toFixed(2).replace(".", ",")} {result.consistent ? "≤ 0,10 — ответы согласованы" : ""}
            </span>
          )}
          {result.advice.map((a) => <div key={a} className="help">{a}</div>)}
        </div>
      )}
    </div>
  );
}
