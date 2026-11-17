import type { Candidate, Combo, Metrics, ModelSpec, Preset, QuestionKind, QuestionOutcome, RetrievalConfig, RunQuestion } from '../api/retrieval';

/** 임베딩 평가 화면이 함께 쓰는 값과 표시 규칙. */
export type MetricKey = keyof Metrics;
export type Basis = 'doc' | 'span';
export type KindKey = QuestionKind | 'all';

export const METRICS: { key: MetricKey; label: string }[] = [
  { key: 'hit@1', label: 'Hit@1' }, { key: 'hit@3', label: 'Hit@3' }, { key: 'hit@5', label: 'Hit@5' }, { key: 'hit@10', label: 'Hit@10' },
  { key: 'mrr@10', label: 'MRR@10' }, { key: 'ndcg@10', label: 'nDCG@10' },
];
export const BASIS_LABEL: Record<Basis, string> = { doc: '정답 문서', span: '정답 구절' };
export const metricLabel = (key: MetricKey) => METRICS.find(m => m.key === key)?.label ?? key;
/** 지표가 보는 순위 한계: Hit@5 → 5, MRR@10 → 10 */
export const cutoffOf = (key: MetricKey) => Number(/@(\d+)$/.exec(key)?.[1] ?? 10);
export const KIND_SHORT: Record<QuestionKind, string> = { text: '본문', table: '표', image: '그림' };
export const fmtMetric = (key: MetricKey, value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value) ? '—' : key.startsWith('hit') ? `${Math.round(value * 100)}%` : value.toFixed(2);

/** 기본 비교 대상: 다국어 모델 다섯. 영어 전용 모델은 모델 목록에서 더할 수 있다. */
export const DEFAULT_MODELS = ['microsoft/harrier-oss-v1-0.6b', 'Qwen/Qwen3-Embedding-0.6B', 'BAAI/bge-m3', 'intfloat/multilingual-e5-large', 'ibm/granite-embedding-278m-multilingual'];
const NAMES: Record<string, string> = {
  'harrier-oss-v1-0.6b': 'Harrier-OSS-v1 0.6B', 'qwen3-embedding-0.6b': 'Qwen3-Embedding 0.6B', 'bge-m3': 'BGE-M3', 'multilingual-e5-large': 'multilingual-e5-large',
  'granite-embedding-278m-multilingual': 'Granite Embedding 278M', 'granite-embedding-107m-multilingual': 'Granite Embedding 107M',
  'slate-125m-english-rtrvr': 'Slate 125M', 'slate-30m-english-rtrvr': 'Slate 30M',
};
const tail = (id: string) => (id.trim().split('/').pop() || id).toLowerCase();
export const modelName = (id: string) => NAMES[tail(id)] ?? (id.trim().split('/').pop() || id.trim() || '모델 미지정');
export function specFor(specs: ModelSpec[] | undefined, model: string) {
  if (!model.trim()) return null;
  const key = model.trim().toLowerCase(), t = tail(model);
  return specs?.find(s => s.id.toLowerCase() === key || tail(s.id) === t) ?? null;
}
export const fmtTokens = (n: number) => n >= 1024 && n % 1024 === 0 ? `${n / 1024}K` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n);
export const shortLang = (languages: string) => languages.replace(/\s*\(.*\)\s*/, '').trim();
export const SHORT_INPUT = 512;

export function isCandidate(value: unknown): value is Candidate {
  const c = value as Candidate;
  return !!c && typeof c === 'object' && typeof c.id === 'string' && typeof c.connection === 'string' && typeof c.model === 'string';
}
export const normalizeCandidate = (c: Candidate): Candidate => ({
  id: c.id, connection: c.connection, model: c.model, query_prefix: typeof c.query_prefix === 'string' ? c.query_prefix : '', doc_prefix: typeof c.doc_prefix === 'string' ? c.doc_prefix : '',
  max_tokens: typeof c.max_tokens === 'number' && c.max_tokens > 0 ? c.max_tokens : null, batch_size: typeof c.batch_size === 'number' && c.batch_size > 0 ? c.batch_size : 16,
});
export function defaultConnection(config: RetrievalConfig | null) {
  return (config?.connections.find(c => c.configured) ?? config?.connections[0])?.key ?? 'embed';
}
export function candidateFor(config: RetrievalConfig | null, id: string, model: string): Candidate {
  const conn = config?.connections.find(c => c.key === defaultConnection(config));
  const served = conn?.models.find(m => tail(m) === tail(model)) ?? model;
  const spec = specFor(config?.specs, served);
  return { id, connection: defaultConnection(config), model: served, query_prefix: spec?.query_prefix ?? '', doc_prefix: spec?.doc_prefix ?? '', max_tokens: null, batch_size: 16 };
}
export const defaultCandidates = (config: RetrievalConfig | null) => DEFAULT_MODELS.map((m, i) => candidateFor(config, `c${i + 1}`, m));
export const nextId = (list: Candidate[]) => `c${list.reduce((max, c) => Math.max(max, Number(/^c(\d+)$/.exec(c.id)?.[1] ?? 0)), 0) + 1}`;

/** 같은 청킹인지: 이름이 아니라 방식과 값으로 본다(키 순서 무관). */
export function samePreset(a: Preset | null | undefined, b: Preset | null | undefined) {
  if (!a || !b || a.kind !== b.kind) return false;
  const pa = a.params as Record<string, unknown>, pb = b.params as Record<string, unknown>;
  return [...new Set([...Object.keys(pa), ...Object.keys(pb)])].every(k => pa[k] === pb[k]);
}

/** 한 조합의 질문 유형별(또는 전체) 지표. */
export function metricsOf(combo: Combo | undefined, kind: KindKey, basis: Basis) {
  if (!combo || combo.status !== 'ok') return { questions: null as number | null, metrics: null as Metrics | null };
  if (kind === 'all') return { questions: combo.questions ?? null, metrics: basis === 'doc' ? combo.doc : combo.span };
  const k = combo.by_kind?.[kind];
  return k ? { questions: k.questions, metrics: basis === 'doc' ? k.doc : k.span } : { questions: null, metrics: null };
}

/** 질문 하나의 결과: 정답이 몇 위에 나왔는지. */
export type Outcome = { tone: 'top' | 'good' | 'low' | 'miss' | 'fail' | 'na'; label: string; rank: number | null };
export function outcomeOf(o: QuestionOutcome | undefined, basis: Basis, q: RunQuestion): Outcome {
  if (!o || o.failed) return { tone: 'fail', label: '실패', rank: null };
  if (basis === 'span' && (!q.answer || o.phrase_found === false)) return { tone: 'na', label: '구절 없음', rank: null };
  const rank = basis === 'doc' ? o.doc_rank : o.span_rank;
  if (rank === null || rank === undefined) return { tone: 'miss', label: '못 찾음', rank: null };
  return { tone: rank === 1 ? 'top' : rank <= 5 ? 'good' : 'low', label: `${rank}위`, rank };
}
/** 지표 기준으로 놓친 질문: 못 찾음·실패, 또는 지표가 보는 순위 밖. */
export const isMissed = (o: Outcome, cutoff: number) => o.tone === 'miss' || o.tone === 'fail' || (o.rank !== null && o.rank > cutoff);
