import { useState } from "react";
import { api, type Prefs } from "../api";
import { useApp } from "../App";

interface Suggestion {
  labels: number;
  enough: boolean;
  baseline?: number;
  suggested?: number;
  steps?: { label: string; from: number; to: number; agreement: number }[];
  preferences?: Prefs | null;
  message?: string | null;
}

/** Подстройка весов и порогов по отметкам «вердикт верный / неверный». */
export function LearningCard() {
  const { profile, reloadProfile } = useApp();
  const [s, setS] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setApplied(null);
    try {
      setS(await api.learningSuggest());
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!s?.preferences || !profile) return;
    const res = await api.saveProfile(profile.id, s.preferences, profile.criteria_text ?? null);
    await reloadProfile();
    setApplied(`Применено: профиль версии ${res.version}, пересчитано ${res.rescored} закупок`);
  };

  return (
    <section className="card fu" style={{ display: "flex", flexDirection: "column", gap: 12, animationDelay: "440ms" }}>
      <h2>Подстройка по вашим отметкам</h2>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>
        Отметки «вердикт верный / неверный» в карточках закупок — обучающие примеры. Система пробует изменить важность факторов
        и пороги и предлагает только то, что увеличивает совпадение с вашими решениями.
      </p>
      <button type="button" className="btn2" style={{ alignSelf: "flex-start" }} onClick={run} disabled={busy}>
        {busy ? "Считаю…" : "Подобрать настройки"}
      </button>
      {s && !s.enough && <p className="muted" style={{ margin: 0 }}>{s.message}</p>}
      {s && s.enough && (
        <>
          <div style={{ fontSize: 15 }}>
            Совпадение с вашими отметками: <b>{s.baseline} из {s.labels}</b>
            {s.steps?.length ? <> → <b style={{ color: "var(--go-fg)" }}>{s.suggested} из {s.labels}</b></> : null}
          </div>
          {s.steps?.map((st, i) => (
            <div key={i} className="kv"><span>{st.label}: {String(st.from).replace(".", ",")} → {String(st.to).replace(".", ",")}</span><span>{st.agreement} из {s.labels}</span></div>
          ))}
          {s.message && <p className="muted" style={{ margin: 0 }}>{s.message}</p>}
          {s.preferences && <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={apply}>Применить к профилю</button>}
          {applied && <span className="chip go" style={{ alignSelf: "flex-start", whiteSpace: "normal" }}>{applied}</span>}
        </>
      )}
    </section>
  );
}
