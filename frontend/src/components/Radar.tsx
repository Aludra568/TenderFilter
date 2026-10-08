import { useEffect, useRef, useState } from "react";

export interface RadarSeries {
  key: string;
  values: (number | null)[]; // 0..1 по каждой оси
  color: string;
  dash?: string;
}

interface Props {
  labels: string[];
  values: (number | null)[]; // основная закупка, 0..1
  weights?: number[];
  compare?: RadarSeries[];
  threshold?: number; // 0..1, пунктирное кольцо
  size?: "lg" | "sm";
  replayKey?: number;
}

const CX = 280, CY = 240, R = 150;

/** Паутинка: фигура вырастает из центра, затем рисуется контур, точки и подписи. */
export function Radar({ labels, values, weights, compare = [], threshold = 0.75, size = "lg", replayKey = 0 }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const [on, setOn] = useState(false);

  useEffect(() => {
    setOn(false);
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      const t = setTimeout(() => setOn(true), 60);
      return () => clearTimeout(t);
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && (setOn(true), io.disconnect())),
      { threshold: 0.3 },
    );
    const t = setTimeout(() => io.observe(el), 40);
    return () => { clearTimeout(t); io.disconnect(); };
  }, [replayKey]);

  const n = labels.length;
  const ang = (i: number) => ((-90 + (i * 360) / n) * Math.PI) / 180;
  const pt = (i: number, v: number) => [CX + R * v * Math.cos(ang(i)), CY + R * v * Math.sin(ang(i))];
  const poly = (vals: (number | null)[]) =>
    vals.map((v, i) => pt(i, Math.max(0.03, v ?? 0)).map((x) => x.toFixed(1)).join(",")).join(" ");
  const ring = (f: number) => poly(labels.map(() => f));

  return (
    <svg
      ref={ref}
      className={`radar${on ? " on" : ""}`}
      viewBox="0 0 560 480"
      role="img"
      aria-label={"Паутинка оценки: " + labels.map((l, i) => `${l} ${values[i] == null ? "нет данных" : Math.round((values[i] as number) * 100) + "%"}`).join(", ")}
      style={{ width: "100%", maxWidth: size === "lg" ? 620 : 340, height: "auto", overflow: "visible", display: "block", margin: "0 auto" }}
    >
      <defs>
        <linearGradient id="radarG" gradientUnits="userSpaceOnUse" x1="140" y1="90" x2="420" y2="390">
          <stop offset="0" stopColor="#E8003D" />
          <stop offset="0.5" stopColor="#FF4FA3" />
          <stop offset="1" stopColor="#7C5CFF" />
        </linearGradient>
      </defs>
      {[0.2, 0.4, 0.6, 0.8, 1].map((f, i) => (
        <polygon key={f} className="ring-r" points={ring(f)} fill="none" stroke="#E4E0F2" strokeWidth={1.2} style={{ animationDelay: `${i * 60}ms` }} />
      ))}
      <polygon className="ring-r" points={ring(threshold)} fill="none" stroke="#12A06A" strokeWidth={2} strokeDasharray="6 5" />
      {labels.map((_, i) => {
        const [x, y] = pt(i, 1);
        return <line key={i} className="ring-r" x1={CX} y1={CY} x2={x} y2={y} stroke="#DCD8EE" strokeWidth={1.5} strokeLinecap="round" />;
      })}
      {compare.map((s) => (
        <polygon key={s.key} className="cmp" points={poly(s.values)} fill="none" stroke={s.color} strokeWidth={3} strokeDasharray={s.dash} strokeLinejoin="round" />
      ))}
      <polygon className="shape" points={poly(values)} fill="url(#radarG)" fillOpacity={0.28} />
      <polygon className="outline" points={poly(values)} pathLength={1} fill="none" stroke="#0B0B2B" strokeWidth={3} strokeLinejoin="round" />
      {values.map((v, i) => {
        if (v == null) return null;
        const [x, y] = pt(i, Math.max(0.03, v));
        return <circle key={i} className="vdot" cx={x} cy={y} r={6} fill="#0B0B2B" stroke="#fff" strokeWidth={2.5} style={{ animationDelay: `${1700 + i * 70}ms` }} />;
      })}
      {labels.map((label, i) => {
        const c = Math.cos(ang(i)), s = Math.sin(ang(i));
        const bx = CX + (R + 22) * c, by = CY + (R + 22) * s;
        const anchor = c > 0.3 ? "start" : c < -0.3 ? "end" : "middle";
        let ly = by - 2, vy = by + 17;
        if (s < -0.5) { ly = by - 22; vy = by - 4; }
        if (s > 0.5) { ly = by + 16; vy = by + 34; }
        const v = values[i];
        const sub = (v == null ? "нет данных" : `${Math.round(v * 100)}%`) + (weights ? ` · вес ${Math.round(weights[i])}` : "");
        const halo = { stroke: "#F6F5FF", paintOrder: "stroke" as const };
        return (
          <g key={label} className="lbl" style={{ animationDelay: `${1500 + i * 90}ms` }}>
            <text x={bx} y={ly} textAnchor={anchor} fontSize={size === "lg" ? 16 : 20} fontWeight={800} fill="#0B0B2B" strokeWidth={5} {...halo}>{label}</text>
            {size === "lg" && <text x={bx} y={vy} textAnchor={anchor} fontSize={14} fontWeight={600} fill="#4A4C6E" strokeWidth={4} {...halo}>{sub}</text>}
          </g>
        );
      })}
    </svg>
  );
}
