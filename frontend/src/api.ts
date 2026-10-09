export type Verdict = "go" | "consider" | "skip";

export interface FactorBrief {
  key: string;
  label: string;
  score: number | null;
}

export interface FeedItem {
  tender_id: number;
  score_id: number;
  purchase_number: string;
  subject: string;
  law: string;
  procedure_name: string | null;
  customer_name: string | null;
  region_name: string | null;
  nmck: number | null;
  submission_deadline: string | null;
  smp_only: boolean | null;
  score: number;
  verdict: Verdict;
  completeness: number;
  main_reason: string;
  bid_status?: BidStatus | null;
  factors: FactorBrief[];
  relevance: number | null;
}

export interface Feed {
  profile_id: number;
  profile_version: number;
  total: number;
  counts: Record<Verdict, number>;
  stop_count: number;
  items: FeedItem[];
  filtered: number;
}

export interface Source {
  field: string;
  path: string;
  raw: string;
}

export interface Factor {
  key: string;
  label: string;
  score: number | null;
  active: boolean;
  weight: number;
  points: number;
  max_points: number;
  value: string;
  reasons: string[];
  stop: string | null;
  sources: Source[];
  fuzzy?: FuzzyData | null;
}

export interface FuzzyData {
  variable: "price" | "time_left" | "guarantee_load";
  x: number;
  unit: string;
  score: number;
  memberships: Record<string, number>;
  points: Record<string, number>[];
}

export interface ScoreResult {
  score: number;
  verdict: Verdict;
  verdict_name: string;
  completeness: number;
  stops: string[];
  flags: string[];
  main_reason: string;
  factors: Factor[];
  rules: { id: string; label: string; effect: string; points: number }[];
  elapsed_ms: number;
  review?: Review;
}

export interface Review {
  status: "agree" | "doubt" | "unconfirmed" | "unavailable";
  status_name: string;
  algorithm_verdict: Verdict;
  final_verdict: Verdict;
  changed: boolean;
  suggested_verdict: Verdict | null;
  issues: { factor: string; problem: string; quote: string; verified: boolean }[];
  note: string;
  elapsed_ms: number;
}

export interface Company {
  inn: string;
  ogrn: string | null;
  name: string;
  status: string;
  registration_date: string | null;
  address: string | null;
  region_code: string | null;
  region_name: string | null;
  okveds: { code: string; name: string | null; main: boolean }[];
  msp_category: string | null;
  is_msp: boolean | null;
  source: string;
}

export interface Tender {
  purchase_number: string;
  law: string;
  procedure_type: string;
  procedure_name: string | null;
  subject: string;
  nmck: number | null;
  customer_inn: string | null;
  customer_name: string | null;
  delivery_place: string | null;
  delivery_region_name: string | null;
  published_at: string | null;
  submission_deadline: string | null;
  contract_term_days: number | null;
  app_guarantee_amount: number | null;
  contract_guarantee_percent: number | null;
  contract_guarantee_amount: number | null;
  advance_percent: number | null;
  smp_only: boolean | null;
  national_regime: boolean | null;
  okpd2: string[];
  items: { name: string; okpd2: string | null; quantity: number | null; price: number | null }[];
  url: string | null;
  parse_warnings: string[];
  contract?: ContractTerms | null;
}

export interface Finding {
  code: string;
  side: "supplier" | "customer" | "both";
  severity: "info" | "warn" | "high";
  title: string;
  detail: string;
  quote: string | null;
  law: string | null;
}

export interface ContractTerms {
  files: string[];
  payment_days: number | null;
  acceptance_days: number | null;
  advance_percent: number | null;
  supplier_penalty: "standard" | "elevated" | null;
  max_fine_percent: number | null;
  warranty_months: number | null;
  brands_without_equivalent: string[];
  findings: Finding[];
}

export type BidStatus = "preparing" | "submitted" | "won" | "lost" | "declined";

export const BID_STATUSES: Record<BidStatus, string> = {
  preparing: "Готовим заявку",
  submitted: "Заявка подана",
  won: "Выиграли — исполняем",
  lost: "Не выиграли",
  declined: "Отказались",
};

export interface Interest {
  profiles: { profile: string; score: number; verdict: Verdict; verdict_name: string; reason: string }[];
  counts: Record<Verdict, number>;
  total: number;
  note: string;
}

export interface CustomerCheck {
  tender: Tender;
  findings: Finding[];
  summary: { high: number; warn: number; info: number };
  interest: Interest;
  elapsed_ms: number;
}

export interface ParticipantCheck {
  inn: string;
  price: number | null;
  company: Company | null;
  risk: "high" | "warn" | "low";
  risk_name: string;
  findings: Finding[];
}

export interface TenderCard {
  tender: Tender;
  tender_id: number;
  score_id: number;
  result: ScoreResult;
  rank: number;
  customer: Company | null;
  similar: FeedItem[];
  profile_version: number;
  bid_status: BidStatus | null;
}

// Предпочтения профиля — свободная структура: схема приходит с бэкенда (/api/factors).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Prefs = Record<string, any>;

export interface Control {
  param: string;
  type: "tags" | "money" | "regions" | "region_list" | "ratio" | "int" | "segmented" | "multi" | "methods" | "toggle";
  label: string;
  min?: number;
  max?: number;
  options?: [string, string][];
}

export interface FactorSchema {
  key: string;
  label: string;
  base_weight: number;
  description: string;
  controls: Control[];
}

export interface Schema {
  factors: FactorSchema[];
  regions: { code: string; name: string; district: string }[];
  districts: Record<string, string>;
  procedures: Record<string, string>;
  verdicts: Record<Verdict, string>;
  defaults: Prefs;
}

export interface Profile {
  id: number;
  name: string;
  company_inn: string;
  company: Company | null;
  version: number;
  criteria_text: string | null;
  preferences: Prefs;
  versions: { version: number; created_at: string }[];
}

export interface ParseOutcome {
  preferences: Prefs;
  recognized: { factor: string; label: string; source_text: string }[];
  unparsed: string[];
  engine: string;
}

export interface Preview {
  counts: Record<Verdict, number>;
  total: number;
  example: ScoreResult | null;
}

export interface Batch {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  total: number;
  processed: number;
  failed: number;
  errors: { file: string; error: string }[];
  items: FeedItem[];
}

export interface Accuracy {
  feedback: { total: number; correct: number; rate: number | null };
  golden: {
    cases: number;
    correct: number;
    accuracy: number;
    critical_errors: number;
    confusion: Record<Verdict, Record<Verdict, number>>;
    timing_ms: { avg: number; max: number };
    rows: { id: string; expected: Verdict; actual: Verdict; score: number; ok: boolean; why: string; reason: string }[];
    generated_at: string;
  } | null;
  timing_ms: { avg: number; max: number };
}

export interface QuickResult {
  tender: Tender;
  tender_id: number | null;
  company: Company | null;
  customer: Company | null;
  criteria: ParseOutcome & { elapsed_ms: number } | null;
  preferences: Prefs;
  result: ScoreResult;
  timings: { parse_ms: number; egrul_ms: number; criteria_ms: number; scoring_ms: number; review_ms?: number; documents_ms?: number; total_ms: number };
}

export interface LogEntry {
  id: number;
  created_at: string;
  event: string;
  event_name: string;
  level: string;
  message: string;
  duration_ms: number | null;
  detail: Record<string, unknown>;
}

export interface Health {
  status: string;
  llm: { provider: string; model: string | null; ready: boolean; detail: string | null };
  egrul_provider: string;
  egrul_chain?: string[];
  queue: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface WeightsResult {
  method: "roc" | "ahp";
  weights: Record<string, number>;
  cr: number | null;
  consistent: boolean;
  advice: string[];
}

export interface WeightQuestion { a: string; b: string; a_label: string; b_label: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  schema: () => request<Schema>("/api/factors"),
  feed: (params: Record<string, string | undefined>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<Feed>(`/api/feed?${q}`);
  },
  tender: (id: number) => request<TenderCard>(`/api/tenders/${id}`),
  raw: (id: number) => fetch(`/api/tenders/${id}/raw`).then((r) => r.text()),
  profile: (id = 1) => request<Profile>(`/api/profiles/${id}`),
  parseText: (id: number, text: string) => request<ParseOutcome>(`/api/profiles/${id}/parse`, json("POST", { text })),
  saveProfile: (id: number, preferences: Prefs, criteria_text: string | null) =>
    request<Profile & { rescored: number }>(`/api/profiles/${id}`, json("PUT", { preferences, criteria_text })),
  preview: (preferences: Prefs, tender_id?: number) =>
    request<Preview>("/api/score/preview", json("POST", { preferences, tender_id })),
  company: (inn: string) => request<Company>(`/api/companies/${inn}`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ tender_id: number; score_id: number; result: ScoreResult }>("/api/tenders", { method: "POST", body: fd });
  },
  batch: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ batch_id: number; total: number; queue: string }>("/api/batches", { method: "POST", body: fd });
  },
  batchStatus: (id: number) => request<Batch>(`/api/batches/${id}`),
  feedback: (scoreId: number, correct: boolean, expected?: Verdict) =>
    request<{ ok: boolean }>(`/api/scores/${scoreId}/feedback`, json("POST", { correct, expected_verdict: expected ?? null })),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  learningSuggest: () => request<any>("/api/learning/suggest"),
  accuracy: () => request<Accuracy>("/api/accuracy"),
  weightQuestions: () => request<{ pairs: WeightQuestion[] }>("/api/weights/questions"),
  weights: (body: { method: "roc"; ranking: string[] } | { method: "ahp"; pairs: { a: string; b: string; value: number }[] }) =>
    request<WeightsResult>("/api/weights", json("POST", body)),
  whatIf: (tenderId: number, nmckChangePct: number, daysLeft: number | null) =>
    request<{ nmck: number | null; result: ScoreResult }>("/api/score/whatif", json("POST", { tender_id: tenderId, nmck_change_pct: nmckChangePct, days_left: daysLeft })),
  review: (scoreId: number) => request<{ review: Review; result: ScoreResult }>(`/api/scores/${scoreId}/review`, { method: "POST" }),
  logs: (limit = 30) => request<LogEntry[]>(`/api/logs?limit=${limit}`),
  quickScore: (file: File, inn: string, criteriaText: string, docs: File[] = []) => {
    const fd = new FormData();
    fd.append("file", file);
    docs.forEach((d) => fd.append("documents", d));
    if (inn.trim()) fd.append("inn", inn.trim());
    if (criteriaText.trim()) fd.append("criteria_text", criteriaText);
    return request<QuickResult>("/api/quick-score", { method: "POST", body: fd });
  },
  attachDocs: (tenderId: number, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ contract: ContractTerms; result: ScoreResult }>(`/api/tenders/${tenderId}/documents`, { method: "POST", body: fd });
  },
  setBid: (tenderId: number, status: BidStatus | null) =>
    request<{ status: BidStatus | null; committed: number; committed_count: number }>(`/api/tenders/${tenderId}/bid`, json("PUT", { status })),
  bids: () => request<{ bids: { tender_id: number; purchase_number: string; subject: string; status: BidStatus; status_name: string; hold: number }[]; committed: number; committed_count: number }>("/api/bids"),
  customerCheck: (file: File, docs: File[]) => {
    const fd = new FormData();
    fd.append("file", file);
    docs.forEach((d) => fd.append("documents", d));
    return request<CustomerCheck>("/api/customer/check", { method: "POST", body: fd });
  },
  customerParticipants: (tender: Tender, participants: { inn: string; price: number | null }[]) =>
    request<{ participants: ParticipantCheck[] }>("/api/customer/participants", json("POST", { tender, participants })),
};
