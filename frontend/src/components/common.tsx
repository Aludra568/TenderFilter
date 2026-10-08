import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import type { Verdict } from "../api";
import { VERDICT } from "../format";

const reduceMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Число, которое «набегает» от прошлого значения к новому. */
export function useCountUp(target: number, duration = 1100): number {
  const [value, setValue] = useState(reduceMotion() ? target : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduceMotion()) {
      setValue(target);
      return;
    }
    const start = performance.now();
    const begin = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(begin + (target - begin) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    // Страховка: в фоновой вкладке requestAnimationFrame не вызывается — показываем итог по таймеру.
    const done = setTimeout(() => { setValue(target); from.current = target; }, duration + 150);
    return () => { cancelAnimationFrame(raf); clearTimeout(done); };
  }, [target, duration]);
  return value;
}

export function CountUp({ value, decimals = 0, suffix = "" }: { value: number; decimals?: number; suffix?: string }) {
  const v = useCountUp(value);
  return <>{v.toFixed(decimals).replace(".", ",")}{suffix}</>;
}

export function VerdictChip({ verdict, big = false }: { verdict: Verdict; big?: boolean }) {
  const v = VERDICT[verdict];
  return (
    <span className={`chip ${verdict}`} style={big ? { fontSize: 17, padding: "10px 18px" } : undefined}>
      <span aria-hidden="true">{v.icon}</span>
      {v.label}
    </span>
  );
}

export function ScoreRing({ score, verdict, manual = false }: { score: number; verdict: Verdict; manual?: boolean }) {
  const shown = useCountUp(manual ? 0 : score, 1200);
  return (
    <span
      className="ring"
      style={{ background: `conic-gradient(${VERDICT[verdict].color} ${shown}%, #eceaf5 0)` }}
      aria-label={manual ? "Оценка не рассчитана" : `Оценка ${Math.round(score)} из 100`}
    >
      <span className="num">{manual ? "—" : Math.round(shown)}</span>
    </span>
  );
}

export function Bar({ value, gradient, delay = 0 }: { value: number; gradient?: string; delay?: number }) {
  const color =
    gradient ??
    (value >= 0.8
      ? "linear-gradient(90deg,#12a06a,#3ddc97)"
      : value >= 0.5
        ? "linear-gradient(90deg,#e5a100,#ffc93d)"
        : "linear-gradient(90deg,#e8003d,#ff6a3d)");
  return (
    <span className="bar" aria-hidden="true">
      <span style={{ width: `${Math.max(2, value * 100)}%`, background: color, animationDelay: `${delay}ms` }} />
    </span>
  );
}

export function Layout({ children, company }: { children: React.ReactNode; company?: { name: string; inn: string; is_msp: boolean | null } | null }) {
  const initials = (company?.name || "ТФ").replace(/[«»"()]/g, "").replace(/^ООО\s+|^АО\s+|^ИП\s+/, "").slice(0, 2).toUpperCase();
  return (
    <div className="page">
      <div className="blob b1" />
      <div className="blob b2" />
      <div className="blob b3" />
      <header className="header">
        <div className="header-in">
          <NavLink to="/" className="logo">
            <span className="logo-mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                <path d="M4 6h16M7 12h10M10 18h4" />
              </svg>
            </span>
            тендерный фильтр
          </NavLink>
          <nav className="nav" aria-label="Основное меню">
            <NavLink to="/" end>Лента</NavLink>
            <NavLink to="/profile">Профиль</NavLink>
            <NavLink to="/upload">Загрузка</NavLink>
            <NavLink to="/accuracy">Точность</NavLink>
          </nav>
          {company && (
            <div className="who">
              <div>
                <div style={{ fontSize: 14, fontWeight: 700 }}>{company.name}</div>
                <div className="num muted" style={{ fontSize: 12 }}>
                  ИНН {company.inn}{company.is_msp ? " · МСП" : ""}
                </div>
              </div>
              <span className="avatar"><span>{initials}</span></span>
            </div>
          )}
        </div>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="error" role="alert">{msg || "Что-то пошло не так"}</div>;
}

export function Skeleton({ height = 120 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} aria-hidden="true" />;
}
