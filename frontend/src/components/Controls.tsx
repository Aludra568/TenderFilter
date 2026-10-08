import { useMemo, useState } from "react";
import type { Control, Schema } from "../api";

type Setter = (value: unknown) => void;

function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: Setter; placeholder: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const items = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (items.length) onChange([...value, ...items.filter((i) => !value.includes(i))]);
    setDraft("");
  };
  return (
    <div className="tagbox">
      {value.map((tag) => (
        <span key={tag} className="tag">
          {tag}
          <button type="button" aria-label={`Удалить ${tag}`} onClick={() => onChange(value.filter((t) => t !== tag))}>×</button>
        </span>
      ))}
      <input value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} onBlur={add} />
    </div>
  );
}

const MONEY_STEPS = [0, 100e3, 250e3, 500e3, 1e6, 2e6, 3e6, 5e6, 7.5e6, 10e6, 15e6, 20e6, 30e6, 50e6, 75e6, 100e6, 200e6, 500e6, 1e9];

function moneyLabel(v: number | null, empty: string) {
  if (v == null) return empty;
  if (v >= 1e6) return `${(v / 1e6).toLocaleString("ru-RU")} млн ₽`;
  if (v > 0) return `${(v / 1e3).toLocaleString("ru-RU")} тыс. ₽`;
  return "0 ₽";
}

function Money({ value, onChange, label, isMax }: { value: number | null; onChange: Setter; label: string; isMax: boolean }) {
  const idx = value == null ? (isMax ? MONEY_STEPS.length : 0) : MONEY_STEPS.reduce((best, s, i) => (Math.abs(s - value) < Math.abs(MONEY_STEPS[best] - value) ? i : best), 0);
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14, fontWeight: 600 }} className="muted">
      <span style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>{label}</span>
        <span className="digits" style={{ color: "var(--ink)", fontSize: 15 }}>{moneyLabel(value, isMax ? "без ограничения" : "не задано")}</span>
      </span>
      <input type="range" min={0} max={MONEY_STEPS.length} step={1} value={idx}
             onChange={(e) => {
               const i = Number(e.target.value);
               onChange(i >= MONEY_STEPS.length ? null : i === 0 && !isMax ? null : MONEY_STEPS[i]);
             }} />
    </label>
  );
}

function Regions({ value, onChange, schema, weighted }: { value: Record<string, number> | string[]; onChange: Setter; schema: Schema; weighted: boolean }) {
  const [q, setQ] = useState("");
  const selected: Record<string, number> = weighted ? (value as Record<string, number>) : Object.fromEntries((value as string[]).map((c) => [c, 1]));
  const byCode = useMemo(() => Object.fromEntries(schema.regions.map((r) => [r.code, r])), [schema]);
  const emit = (next: Record<string, number>) => onChange(weighted ? next : Object.keys(next));
  const matches = q.length >= 2 ? schema.regions.filter((r) => r.name.toLowerCase().includes(q.toLowerCase()) && !(r.code in selected)).slice(0, 6) : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="tagbox">
        {Object.entries(selected).map(([code, w]) => (
          <span key={code} className="tag" style={w < 1 ? { background: "var(--consider-bg)", color: "var(--consider-fg)" } : weighted ? undefined : { background: "var(--skip-bg)", color: "var(--skip-fg)" }}>
            {weighted ? (
              <button type="button" title="Переключить приоритет 100% / 50%" onClick={() => emit({ ...selected, [code]: w < 1 ? 1 : 0.5 })}>
                {byCode[code]?.name ?? code} · {w < 1 ? "50%" : "100%"}
              </button>
            ) : byCode[code]?.name ?? code}
            <button type="button" aria-label="Убрать регион" onClick={() => { const n = { ...selected }; delete n[code]; emit(n); }}>×</button>
          </span>
        ))}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="+ регион: начните вводить" aria-label="Добавить регион" />
      </div>
      {matches.length > 0 && (
        <div className="tagbox">
          {matches.map((r) => (
            <button key={r.code} type="button" className="mchip neutral" onClick={() => { emit({ ...selected, [r.code]: 1 }); setQ(""); }}>+ {r.name}</button>
          ))}
        </div>
      )}
      {weighted && (
        <div className="tagbox">
          <span className="help">Целым округом:</span>
          {Object.entries(schema.districts).map(([code, name]) => (
            <button key={code} type="button" className="btn3" title={name}
                    onClick={() => emit({ ...selected, ...Object.fromEntries(schema.regions.filter((r) => r.district === code && !(r.code in selected)).map((r) => [r.code, 1])) })}>
              {code}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const NEXT = { prefer: "neutral", neutral: "exclude", exclude: "prefer" } as const;
const MARK = { prefer: "✓", neutral: "·", exclude: "✕" } as const;

export function ControlView({ control, value, onChange, schema }: { control: Control; value: unknown; onChange: Setter; schema: Schema }) {
  switch (control.type) {
    case "tags":
      return (
        <div className="field" style={{ padding: "10px 0", border: "none" }}>
          <span className="help">{control.label}</span>
          <TagInput value={(value as string[]) ?? []} onChange={onChange} placeholder="добавить и Enter" />
        </div>
      );
    case "money":
      return <Money value={(value as number | null) ?? null} onChange={onChange} label={control.label} isMax={control.param.startsWith("max") || control.param.includes("limit")} />;
    case "regions":
    case "region_list":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="help">{control.label}</span>
          <Regions value={(value as Record<string, number>) ?? (control.type === "regions" ? {} : [])} onChange={onChange} schema={schema} weighted={control.type === "regions"} />
        </div>
      );
    case "ratio":
    case "int": {
      const v = Number(value ?? (control.type === "ratio" ? 0.5 : control.min ?? 0));
      return (
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 14, fontWeight: 600 }} className="muted">
          <span style={{ display: "flex", justifyContent: "space-between" }}>
            <span>{control.label}</span>
            <span className="digits" style={{ color: "var(--ink)", fontSize: 15 }}>{control.type === "ratio" ? `${Math.round(v * 100)}%` : v || "не задано"}</span>
          </span>
          <input type="range" min={control.type === "ratio" ? 0 : control.min ?? 0} max={control.type === "ratio" ? 1 : control.max ?? 30}
                 step={control.type === "ratio" ? 0.1 : 1} value={v}
                 onChange={(e) => onChange(control.type === "int" && Number(e.target.value) === 0 ? null : Number(e.target.value))} />
        </label>
      );
    }
    case "segmented":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="help">{control.label}</span>
          <div className="seg" role="group" aria-label={control.label}>
            {control.options!.map(([k, label]) => (
              <button key={k} type="button" className={value === k ? "on" : ""} aria-pressed={value === k} onClick={() => onChange(k)}>{label}</button>
            ))}
          </div>
        </div>
      );
    case "multi": {
      const list = (value as string[]) ?? [];
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="help">{control.label}</span>
          <div className="tagbox">
            {control.options!.map(([k, label]) => {
              const on = list.includes(k);
              return (
                <button key={k} type="button" className={`mchip ${on ? "prefer" : "neutral"}`} aria-pressed={on}
                        onClick={() => onChange(on ? list.filter((x) => x !== k) : [...list, k])}>
                  {on ? "✓ " : ""}{label}
                </button>
              );
            })}
          </div>
        </div>
      );
    }
    case "methods": {
      const map = (value as Record<string, "prefer" | "neutral" | "exclude">) ?? {};
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="help">{control.label}: нажатие переключает ✓ предпочитаю → · нейтрально → ✕ исключить</span>
          <div className="tagbox">
            {control.options!.map(([k, label]) => {
              const state = map[k] ?? "neutral";
              return (
                <button key={k} type="button" className={`mchip ${state}`} onClick={() => onChange({ ...map, [k]: NEXT[state] })}>
                  {MARK[state]} {label}
                </button>
              );
            })}
          </div>
        </div>
      );
    }
    case "toggle":
      return (
        <label className="switch">
          <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
          {control.label}
        </label>
      );
    default:
      return null;
  }
}
