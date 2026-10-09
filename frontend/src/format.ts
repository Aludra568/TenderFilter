import type { Verdict } from "./api";

export const VERDICT: Record<Verdict, { label: string; icon: string; color: string; glow: string }> = {
  go: { label: "Участвовать", icon: "✓", color: "var(--go)", glow: "#3ddc97" },
  consider: { label: "Рассмотреть", icon: "!", color: "var(--consider)", glow: "#ffc93d" },
  skip: { label: "Не участвовать", icon: "✕", color: "var(--skip)", glow: "#ff4fa3" },
};

export function rub(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(1).replace(".", ",")} млрд ₽`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1).replace(".", ",").replace(",0", "")} млн ₽`;
  if (v >= 1e3) return `${Math.round(v / 1e3)} тыс. ₽`;
  return `${Math.round(v)} ₽`;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export function deadlineInfo(iso: string | null): { date: string; left: string; urgent: boolean; expired: boolean } {
  if (!iso) return { date: "—", left: "срок не указан", urgent: false, expired: false };
  const d = new Date(iso);
  const days = (d.getTime() - Date.now()) / 86400000;
  const date = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  if (days < 0) return { date, left: "срок истёк", urgent: true, expired: true };
  if (days < 1) return { date, left: "горит · сегодня", urgent: true, expired: false };
  const n = Math.floor(days);
  if (n <= 4) return { date, left: `горит · ${n} ${plural(n, "день", "дня", "дней")}`, urgent: true, expired: false };
  return { date, left: `через ${n} ${plural(n, "день", "дня", "дней")}`, urgent: false, expired: false };
}

export const LAW = (law: string) => law.replace("-FZ", "-ФЗ");
