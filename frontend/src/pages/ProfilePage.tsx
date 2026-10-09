import { useEffect, useRef, useState } from "react";
import { api, type ParseOutcome, type Prefs, type Preview, type Verdict } from "../api";
import { useApp } from "../App";
import { ControlView } from "../components/Controls";
import { CountUp, ErrorBox, Skeleton, VerdictChip } from "../components/common";
import { Radar } from "../components/Radar";
import { WeightsWizard } from "../components/WeightsWizard";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

const PRESETS: Record<string, (p: Prefs) => Prefs> = {
  "Осторожный": (p) => ({ ...p, timing: { ...p.timing, min_days_to_deadline: 7, required: true },
    finance: { ...p.finance, advance: "want", importance: 5 }, geo: { ...p.geo, importance: 5, required: true },
    conditions: { ...p.conditions, methods: { ...p.conditions.methods, open_contest: "exclude" } } }),
  "Рост": (p) => ({ ...p, geo: { ...p.geo, importance: 1, required: false, same_district_score: 0.8 },
    price: { ...p.price, max_rub: null }, timing: { ...p.timing, min_days_to_deadline: 2, required: false } }),
};

function summary(p: Prefs, regionName: (c: string) => string): string {
  const parts: string[] = [];
  const methods = Object.entries(p.conditions?.methods ?? {}).filter(([, v]) => v === "prefer").map(([k]) => ({ e_auction: "аукционы", open_contest: "конкурсы", quotation_request: "котировки", proposal_request: "запросы предложений", single_supplier: "ед. поставщика" } as Record<string, string>)[k]);
  parts.push(`Ищем ${methods.length ? methods.join(", ") : "закупки любым способом"}`);
  const lo = p.price?.min_rub, hi = p.price?.max_rub;
  if (lo || hi) parts.push(`с НМЦК ${lo ? `от ${(lo / 1e6).toLocaleString("ru-RU")}` : ""}${hi ? ` до ${(hi / 1e6).toLocaleString("ru-RU")}` : ""} млн ₽`);
  const regs = Object.entries(p.geo?.regions ?? {}) as [string, number][];
  if (regs.length) parts.push(`в регионах: ${regs.slice(0, 4).map(([c, w]) => regionName(c) + (w < 1 ? " (½)" : "")).join(", ")}${regs.length > 4 ? ` и ещё ${regs.length - 4}` : ""}`);
  parts.push(`${p.timing?.required ? "строго" : "желательно"} от ${p.timing?.min_days_to_deadline ?? 3} дн. на заявку`);
  parts.push({ ignore: "аванс не учитываем", want: "аванс важен", must: "только с авансом" }[p.finance?.advance as string] ?? "");
  return parts.filter(Boolean).join(", ") + ".";
}

export function ProfilePage() {
  const { profile, schema, reloadProfile } = useApp();
  const [mode, setMode] = useState<"ui" | "text">("ui");
  const [draft, setDraft] = useState<Prefs | null>(null);
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParseOutcome | null>(null);
  const [parsing, setParsing] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [exampleId, setExampleId] = useState<number | undefined>();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const firstPreview = useRef(true);

  useEffect(() => {
    if (profile && !draft) {
      setDraft(clone(profile.preferences));
      setText(profile.criteria_text ?? "");
    }
  }, [profile, draft]);

  useEffect(() => {
    api.feed({ verdict: "go", limit: "1" }).then((f) => setExampleId(f.items[0]?.tender_id)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(() => {
      api.preview(draft, exampleId).then(setPreview).catch(setError);
      firstPreview.current = false;
    }, firstPreview.current ? 0 : 350);
    return () => clearTimeout(t);
  }, [draft, exampleId]);

  if (!profile || !schema || !draft) return <><Skeleton height={140} /><Skeleton height={520} /></>;

  const regionName = (c: string) => schema.regions.find((r) => r.code === c)?.name.replace(" область", " обл.") ?? c;
  const set = (factor: string, param: string, value: unknown) => setDraft((d) => ({ ...d!, [factor]: { ...d![factor], [param]: value } }));

  const recognize = async () => {
    setParsing(true);
    setError(null);
    try {
      setParsed(await api.parseText(profile.id, text));
    } catch (e) {
      setError(e);
    } finally {
      setParsing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await api.saveProfile(profile.id, draft, text || null);
      await reloadProfile();
      setSaved(`Сохранено как версия ${res.version}, пересчитано ${res.rescored} закупок`);
      setTimeout(() => setSaved(null), 4000);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  const ex = preview?.example;
  const total = preview?.total || 1;
  const counts = preview?.counts ?? { go: 0, consider: 0, skip: 0 };

  return (
    <>
      <div className="page-head fu">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h1>{profile.name}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {profile.company?.name} · ИНН {profile.company_inn}
            {profile.company?.okveds?.[0] ? ` · ОКВЭД ${profile.company.okveds[0].code}` : ""} · версия {profile.version}
          </p>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="muted" style={{ fontSize: 14, fontWeight: 700 }}>Шаблоны:</span>
          {Object.entries(PRESETS).map(([name, fn]) => (
            <button key={name} type="button" className="btn2" style={{ minHeight: 44 }} onClick={() => setDraft((d) => fn(clone(d!)))}>{name}</button>
          ))}
          <button type="button" className="btn2" style={{ minHeight: 44 }} onClick={() => setDraft(clone(profile.preferences))}>Сбросить</button>
        </div>
      </div>

      <ErrorBox error={error} />

      <div className="row">
        <section className="card grow fu" aria-label="Настройки профиля" style={{ paddingTop: 10, animationDelay: "100ms" }}>
          <div className="field-head" style={{ padding: "16px 0", borderBottom: "1px solid var(--line)" }}>
            <h2>Предпочтения</h2>
            <div className="seg" role="group" aria-label="Способ настройки">
              <button type="button" className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Текстом</button>
              <button type="button" className={mode === "ui" ? "on" : ""} onClick={() => setMode("ui")}>Настройками</button>
            </div>
          </div>

          {mode === "text" ? (
            <div className="field fu" style={{ border: "none" }}>
              <label className="lbl-big" htmlFor="crit">Опишите обычными словами, какие закупки вам подходят</label>
              <textarea id="crit" rows={6} value={text} onChange={(e) => setText(e.target.value)}
                        placeholder="Работаем в Новосибирской и Томской областях. НМЦК от 1 до 30 млн. Конкурсы не любим. Аванс важен." />
              <div className="help">Каждое понятое правило покажется ниже вместе с фразой-источником. Непонятые фразы подсвечиваются — их можно переформулировать.</div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" className="btn" onClick={recognize} disabled={parsing || !text.trim()}>{parsing ? "Разбираю…" : "Распознать"}</button>
                {parsed && <button type="button" className="btn2" onClick={() => { setDraft(clone(parsed.preferences)); setMode("ui"); }}>Применить и открыть настройки</button>}
              </div>
              {parsed && (
                <div className="recognized">
                  <span className="muted" style={{ fontSize: 13 }}>Движок: {parsed.engine === "rules+llm" ? "правила + LLM" : "правила"}</span>
                  {parsed.recognized.map((r, i) => (
                    <div key={i} style={{ animationDelay: `${i * 60}ms` }}>
                      <span className="chip go" style={{ fontSize: 12 }}>✓</span>
                      <span><b>{r.label}</b> <span className="muted">← «{r.source_text}»</span></span>
                    </div>
                  ))}
                  {parsed.unparsed.map((u) => <div key={u} className="unparsed">Не понял: «{u}»</div>)}
                </div>
              )}
            </div>
          ) : (
            schema.factors.map((f) => {
              const settings = draft[f.key] ?? {};
              return (
                <div className="field" key={f.key}>
                  <div className="field-head">
                    <div>
                      <div className="lbl-big">{f.label}</div>
                      <div className="help">{f.description}</div>
                    </div>
                    <label className="switch" title="Если условие не выполнено — стоп-фактор">
                      <input type="checkbox" checked={!!settings.required} onChange={(e) => set(f.key, "required", e.target.checked)} />
                      Обязательно
                    </label>
                  </div>
                  <label style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 14, fontWeight: 600 }} className="muted">
                    <span style={{ minWidth: 82 }}>Важность</span>
                    <input type="range" min={0} max={5} step={1} value={settings.importance ?? 3} onChange={(e) => set(f.key, "importance", Number(e.target.value))} />
                    <span className="digits" style={{ color: "var(--ink)", minWidth: 36, textAlign: "right" }}>{settings.importance ?? 3}/5</span>
                  </label>
                  {f.controls.map((c) => (
                    <ControlView key={c.param} control={c} schema={schema} value={settings[c.param]} onChange={(v) => set(f.key, c.param, v)} />
                  ))}
                </div>
              );
            })
          )}
          {mode === "ui" && (
            <WeightsWizard factors={schema.factors} draft={draft}
                           onApply={(weights, method) => setDraft((d) => ({ ...d!, weights, weights_method: method }))}
                           onReset={() => setDraft((d) => ({ ...d!, weights: {}, weights_method: null }))} />
          )}
          {mode === "ui" && (
            <div className="field">
              <div className="lbl-big">Пороги вердиктов</div>
              {(["go", "consider"] as const).map((k) => (
                <label key={k} style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 14, fontWeight: 600 }} className="muted">
                  <span style={{ minWidth: 150 }}>{k === "go" ? "«Участвовать» от" : "«Рассмотреть» от"}</span>
                  <input type="range" min={10} max={95} step={5} value={draft.thresholds[k]}
                         onChange={(e) => setDraft((d) => ({ ...d!, thresholds: { ...d!.thresholds, [k]: Number(e.target.value) } }))} />
                  <span className="digits" style={{ color: "var(--ink)", minWidth: 44, textAlign: "right" }}>{draft.thresholds[k]}</span>
                </label>
              ))}
            </div>
          )}
        </section>

        <aside className="side" aria-label="Предпросмотр" style={{ position: "sticky", top: 96 }}>
          <section className="card dark fu" style={{ display: "flex", flexDirection: "column", gap: 12, animationDelay: "180ms" }}>
            <div aria-hidden="true" style={{ position: "absolute", width: 240, height: 240, borderRadius: "50%", right: -80, top: -90, background: "radial-gradient(circle, rgba(124,92,255,.7), rgba(124,92,255,0) 70%)" }} />
            <h3 style={{ position: "relative" }}>Предпросмотр</h3>
            {ex ? (
              <>
                <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                  <span className="digits" style={{ fontSize: 56, lineHeight: 1, fontWeight: 800 }}><CountUp value={ex.score} suffix="%" /></span>
                  <VerdictChip verdict={ex.verdict} big />
                </div>
                {ex.stops[0] && <span style={{ position: "relative", color: "#ffb3c1", fontWeight: 700, fontSize: 14 }}>Стоп-фактор: {ex.stops[0]}</span>}
                <div style={{ position: "relative", background: "rgba(255,255,255,0.96)", borderRadius: 20, padding: "8px 4px" }}>
                  <Radar size="sm" labels={ex.factors.map((f) => f.label)} values={ex.factors.map((f) => f.score)} threshold={draft.thresholds.go / 100} />
                </div>
              </>
            ) : <Skeleton height={200} />}
          </section>

          <section className="card fu" style={{ display: "flex", flexDirection: "column", gap: 14, animationDelay: "260ms" }}>
            <h3>Лента: {preview?.total ?? "…"} извещений</h3>
            <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", background: "var(--line)", gap: 3 }} aria-hidden="true">
              {(["go", "consider", "skip"] as Verdict[]).map((v) => (
                <span key={v} style={{ width: `${(counts[v] / total) * 100}%`, background: `var(--${v})`, borderRadius: 7, transition: "width .45s cubic-bezier(.34,1.3,.64,1)" }} />
              ))}
            </div>
            {(["go", "consider", "skip"] as Verdict[]).map((v) => (
              <div key={v} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <VerdictChip verdict={v} />
                <span className="digits" style={{ fontWeight: 800 }}><CountUp value={counts[v]} /></span>
              </div>
            ))}
            <p style={{ margin: 0, fontSize: 14, background: "var(--tint)", borderRadius: 16, padding: "14px 16px", color: "var(--ink-2)" }}>{summary(draft, regionName)}</p>
          </section>

          <button type="button" className="btn fu" style={{ minHeight: 56, fontSize: 16, animationDelay: "320ms" }} onClick={save} disabled={saving}>
            {saving ? "Сохраняю…" : `Сохранить как версию ${profile.version + 1}`}
          </button>
          {saved && <div className="chip go pop" style={{ justifyContent: "center", whiteSpace: "normal" }}>{saved}</div>}
        </aside>
      </div>
    </>
  );
}
