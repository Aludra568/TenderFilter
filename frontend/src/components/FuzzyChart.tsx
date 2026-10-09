import type { FuzzyData } from "../api";

const TERM_COLOR: Record<string, string> = {
  "подходит": "var(--violet)",
  "мало": "var(--skip)", "нормально": "var(--consider)", "достаточно": "var(--go)",
  "лёгкая": "var(--go)", "заметная": "var(--consider)", "тяжёлая": "var(--skip)",
};
const TITLE: Record<string, string> = {
  price: "Нечёткое множество «цена подходит»",
  time_left: "Время на заявку: мало / нормально / достаточно",
  guarantee_load: "Нагрузка обеспечений: лёгкая / заметная / тяжёлая",
};

function fmt(x: number, unit: string) {
  if (unit === "₽") return x >= 1e6 ? `${(x / 1e6).toFixed(x >= 1e7 ? 0 : 1).replace(".", ",")} млн` : `${Math.round(x / 1e3)} тыс.`;
  if (unit === "дн.") return `${x.toFixed(x < 10 ? 1 : 0).replace(".", ",")} дн.`;
  return `${Math.round(x * 100)}% лимита`;
}

/** График функций принадлежности: как алгоритм «размыто» оценил значение текущей закупки. */
export function FuzzyChart({ data }: { data: FuzzyData }) {
  const W = 320, H = 110, L = 6, R = 6, T = 10, B = 22;
  const xs = data.points.map((p) => p.x);
  const max = Math.max(...xs) || 1;
  const X = (x: number) => L + (x / max) * (W - L - R);
  const Y = (mu: number) => T + (1 - mu) * (H - T - B);
  const terms = Object.keys(data.points[0] ?? {}).filter((k) => k !== "x");
  const cx = X(Math.min(data.x, max));
  const mu = Object.entries(data.memberships).filter(([, v]) => v > 0.001)
    .map(([k, v]) => `«${k}» ${v.toFixed(2).replace(".", ",")}`).join(", ");
  return (
    <figure style={{ margin: "6px 0 0", maxWidth: W }}>
      <figcaption className="muted" style={{ fontSize: 12, marginBottom: 2 }}>{TITLE[data.variable]}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${TITLE[data.variable]}: ${mu}`}>
        <line x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} stroke="var(--line)" />
        <line x1={L} x2={W - R} y1={Y(1)} y2={Y(1)} stroke="var(--line)" strokeDasharray="2 4" />
        {terms.map((term) => (
          <polyline key={term} fill="none" stroke={TERM_COLOR[term] ?? "var(--muted)"} strokeWidth={2} strokeLinejoin="round"
                    points={data.points.map((p) => `${X(p.x).toFixed(1)},${Y(Number(p[term])).toFixed(1)}`).join(" ")}>
            <title>{term}</title>
          </polyline>
        ))}
        <line x1={cx} x2={cx} y1={T - 4} y2={Y(0)} stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="3 3" />
        <circle cx={cx} cy={Y(data.score)} r={4} fill="var(--ink)" />
        <text x={L} y={H - 6} fontSize={10} fill="var(--muted)">0</text>
        <text x={W - R} y={H - 6} fontSize={10} fill="var(--muted)" textAnchor="end">{fmt(max, data.unit)}</text>
        <text x={Math.min(Math.max(cx, 40), W - 40)} y={H - 6} fontSize={10} fill="var(--ink)" textAnchor="middle" fontWeight={700}>
          {fmt(data.x, data.unit)}
        </text>
      </svg>
      <div className="muted" style={{ fontSize: 12 }}>μ: {mu} → балл {data.score.toFixed(2).replace(".", ",")}</div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11 }} aria-hidden="true">
        {terms.map((t) => <span key={t} style={{ color: TERM_COLOR[t] }}>━ {t}</span>)}
      </div>
    </figure>
  );
}
