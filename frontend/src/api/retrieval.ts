/** 청킹 벤치·임베딩 평가 API. 외부 모델 호출(토큰 측정·평가 실행)은 사용자가 누를 때만 보낸다. */
export type Unit = 'chars' | 'tokens';
/** fixed·recursive·markdown·sentence는 텍스트만 보는 기준선. element·parent_child·page는 비정형 요소(표·그림·캡션·반복 머리말)를 구분한다. */
export type StrategyKind = 'fixed' | 'recursive' | 'markdown' | 'sentence' | 'element' | 'parent_child' | 'page';
export type TablePolicy = 'whole' | 'rows' | 'row_text';
export type ImagePolicy = 'drop' | 'caption';
export type StrategyParams = {
  unit: Unit; size: number; overlap?: number; merge_small?: boolean; min_size?: number; overlap_sentences?: number;
  /** element·parent_child·page: 표는 통째(넘치면 행 묶음) / 행 묶음마다 머리행 반복 / 행마다 '열: 값' 문장 */
  table?: TablePolicy; table_rows?: number;
  /** element·parent_child·page: 그림은 버림 / 캡션·대체 텍스트로 청크 */
  image?: ImagePolicy; attach_caption?: boolean; drop_furniture?: boolean;
  /** parent_child: 검색은 size(자식), 답변 맥락은 parent_size(부모) */
  parent_size?: number;
};
export type Preset = { id: string; name: string; kind: StrategyKind; params: StrategyParams };
export type ChunkKind = 'text' | 'table' | 'mixed';
/** 원문을 이루는 요소. 위치는 원문 텍스트(source.text)의 문자 오프셋. */
export type ElementKind = 'heading' | 'text' | 'list' | 'table' | 'image' | 'caption' | 'code' | 'furniture';
export type DocElement = {
  id: string; kind: ElementKind; start: number; end: number; page: number | null; heading_path: string[];
  /** 사람이 읽는 이름: '표 2 · 14행 × 5열', '그림 1 · 냉장고 배치도', '반복 머리말' */
  label: string; chars: number; est_tokens: number;
  rows?: number; cols?: number;
  /** caption: 설명하는 표·그림의 id. image: 딸린 캡션 id */
  caption_of?: string | null; caption?: string | null;
  /** image: 대체 텍스트·캡션 없이 자리 표시만 있음(OCR 꺼짐 등) */
  empty?: boolean;
};
/**
 * whole 한 청크에 온전히 / rows 행 묶음마다 머리행을 붙여 의도적으로 나눔 / split 머리행 없이 잘림
 * caption 그림이 캡션·대체 텍스트로 들어감 / attached·detached 캡션이 대상과 같은 청크·다른 청크
 * missing 어느 청크에도 의미 있게 들어가지 않음(버린 그림, 제거한 머리말, 자리 표시만 남은 그림)
 */
export type ElementOutcome = 'whole' | 'rows' | 'split' | 'caption' | 'attached' | 'detached' | 'missing';
export type KindTally = Partial<Record<ElementKind, Partial<Record<ElementOutcome, number>>>>;
export type Chunk = {
  index: number; text: string; start: number; end: number; heading_path: string[]; kind: ChunkKind; chars: number; est_tokens: number; flags: string[];
  /** 이 청크가 덮는 요소 id(원문 순서) */
  elements: string[]; element_kinds: ElementKind[]; page: number | null;
  /** parent_child: 부모 청크 번호(StrategyResult.parents의 index) */
  parent: number | null;
};
export type ParentChunk = { index: number; start: number; end: number; chars: number; est_tokens: number; heading_path: string[] };
export type Dist = { min: number; median: number; p95: number; max: number; mean: number };
export type ChunkStats = { count: number; chars: Dist; tokens: Dist; over_limit: number; coverage: number; duplication: number; tables_total: number; tables_split: number; total_chars: number; total_tokens: number; flags: Record<string, number> };
export type StrategyResult = {
  id: string; name?: string; kind?: StrategyKind; params?: StrategyParams; chunks: Chunk[]; stats: ChunkStats | null; error?: string;
  parents?: ParentChunk[]; outcomes: Record<string, ElementOutcome>; by_kind: KindTally;
};
export type ChunkSource = {
  doc_id: string | null; sample: string | null; name: string; is_stale: boolean; chars: number; est_tokens: number; tables: number; headings: number; sections: number; text: string;
  elements: DocElement[]; pages: number | null; composition: Partial<Record<ElementKind, number>>;
};
/** 합성 예시 문서. 실제 조직·제품과 무관하다. */
export type Sample = { id: string; name: string; description: string; composition: Partial<Record<ElementKind, number>>; pages: number | null };
export type ChunkResponse = { source: ChunkSource; results: StrategyResult[] };

export type ModelSpec = { id: string; dims: number; dims_note: string; max_tokens: number; arch: string; pooling: string; query_prefix: string; doc_prefix: string; prefix_note: string; languages: string; note: string };
export type EmbedConnection = { key: string; label: string; base_url: string; api_key_set: boolean; configured: boolean; models: string[]; source: 'embed' | 'model' };
export type Caps = { max_chunks: number; max_questions: number; max_presets: number; max_candidates: number; max_documents: number; max_question_rows: number; top_k_min: number; top_k_max: number; max_source_chars: number; max_bench_chunks: number };
export type RetrievalConfig = { connections: EmbedConnection[]; configured: boolean; specs: ModelSpec[]; strategies: Record<string, string>; caps: Caps; cache: { entries: number; bytes: number } };
export type RetrievalDoc = { id: string; name: string; format: string; status: string; updated_at: string; is_stale: boolean };
/** 질문 유형: 정답이 본문·표·그림(캡션) 중 어디에 있는가. 비우면 서버가 정답 위치로 판단한다. */
export type QuestionKind = 'text' | 'table' | 'image';
export type Question = { id?: string; question: string; doc_id: string; answer: string; kind?: QuestionKind | null };
export type TokenMeasure = { model: string; connection: string; dims: number | null; usage_reported: boolean; items: { tokens: number | null; est_tokens: number; error: string | null; over_limit?: boolean; latency_ms?: number }[] };

export type Candidate = { id: string; connection: string; model: string; query_prefix: string; doc_prefix: string; max_tokens: number | null; batch_size: number };
export type Metrics = { 'hit@1': number; 'hit@3': number; 'hit@5': number; 'hit@10': number; 'mrr@10': number; 'ndcg@10': number };
export type QuestionOutcome = { failed?: boolean; doc_rank: number | null; span_rank: number | null; top_score?: number | null; phrase_found?: boolean };
export type Combo = {
  key: string; candidate_id: string; preset_id: string; model: string; connection: string; connection_label: string; preset_name: string; preset_kind: StrategyKind;
  status: 'ok' | 'failed'; error: string | null; errors?: string[]; doc: Metrics | null; span: Metrics | null; questions?: number; span_questions?: number; phrase_missing?: number;
  /** 질문 유형별 지표. 해당 유형 질문이 없으면 questions 0, 지표 null */
  by_kind?: Record<QuestionKind, { questions: number; doc: Metrics | null; span: Metrics | null }>;
  chunks: number; documents: number; dims?: number | null; dims_consistent?: boolean; latency_ms?: number | null; requests?: number; chunks_per_sec?: number | null;
  throughput_source?: 'measured' | 'previous' | null; embedded?: number; cached?: number; failures?: number; query_failures?: number; over_limit?: number;
  over_limit_failed?: number; max_tokens?: number | null; token_ratio?: number | null; storage_bytes?: number; per_question: QuestionOutcome[];
};
export type RunQuestion = { index: number; id: string; question: string; doc_id: string; answer: string; kind: QuestionKind };
/** 실행 전 계획: 고른 청킹으로 나눈 결과와 모델별 입력 한도 초과·벡터 용량. 외부 호출 없음. */
export type PlanModel = { model: string; max_tokens: number | null; dims: number | null; over_limit: number; storage_bytes: number | null };
export type PlanResult = {
  documents: number; chunks: number; max_chunk_tokens: number; median_chunk_tokens: number;
  models: PlanModel[]; questions: { total: number; by_kind: Record<QuestionKind, number> }; errors: string[];
};
export type Run = {
  id: string; status: 'running' | 'completed' | 'cancelled' | 'failed'; created_at: string; finished_at: string | null; error: string | null;
  progress: { done: number; total: number; phase: string; detail: string }; drilldown: boolean; caps: Caps;
  request: { documents: { id: string; name: string }[]; presets: Preset[]; candidates: (Candidate & { connection_label: string })[]; questions: number; skipped: { no_document: number; not_selected: number }; top_k: number; chunks: Record<string, number> };
  questions: RunQuestion[]; results: Combo[];
};
export type DrillResult = { rank: number; score: number; doc_id: string; doc_name: string; chunk_index: number; heading_path: string[]; chars: number; est_tokens: number; text: string; hit_doc: boolean; hit_span: boolean };
export type Drilldown = { combo: string; question: RunQuestion; failed: boolean; results: DrillResult[] };

const BASE = '/api/retrieval';

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `요청을 처리하지 못했습니다. (HTTP ${response.status})`;
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === 'string') message = body.detail; } catch { /* 상태 코드만 보여 준다. */ }
    throw new Error(message);
  }
  return await response.json() as T;
}
const json = (method: string, body: unknown, signal?: AbortSignal): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });

export const getConfig = async (): Promise<RetrievalConfig> => read(await fetch(`${BASE}/config`));
export const listDocuments = async (): Promise<RetrievalDoc[]> => (await read<{ documents: RetrievalDoc[] }>(await fetch(`${BASE}/documents`))).documents;
export const getSamples = async (): Promise<Sample[]> => (await read<{ samples: Sample[] }>(await fetch(`${BASE}/samples`))).samples;
/** 평가 문서 id: 실제 문서는 그대로, 합성 예시는 'sample:<id>' */
export const sampleDocId = (id: string) => `sample:${id}`;
export async function chunkSource(source: { doc_id?: string; sample?: string; text?: string; name?: string }, strategies: Preset[], limitTokens: number | null, signal?: AbortSignal): Promise<ChunkResponse> {
  return read(await fetch(`${BASE}/chunk`, json('POST', { source, strategies, limit_tokens: limitTokens }, signal)));
}
export async function measureTokens(connection: string, model: string, texts: string[]): Promise<TokenMeasure> {
  return read(await fetch(`${BASE}/tokens`, json('POST', { connection, model, texts })));
}
export const getQuestions = async (): Promise<{ questions: Question[]; updated_at: string | null }> => read(await fetch(`${BASE}/questions`));
export async function saveQuestions(questions: Question[]): Promise<{ questions: Question[]; updated_at: string | null }> {
  return read(await fetch(`${BASE}/questions`, json('PUT', { questions })));
}
export async function parseQuestions(format: 'csv' | 'jsonl', text: string): Promise<{ questions: Question[]; errors: string[]; error_count: number }> {
  return read(await fetch(`${BASE}/questions/parse`, json('POST', { format, text })));
}
export const exportUrl = (format: 'csv' | 'jsonl') => `${BASE}/questions/export?format=${format}`;
/** 합성 예시 문서에 맞춘 예시 질문(저장하지 않음). */
export const getExampleQuestions = async (): Promise<Question[]> => (await read<{ questions: Question[] }>(await fetch(`${BASE}/questions/example`))).questions;
export async function planRun(body: { doc_ids: string[]; preset: Preset; models: string[] }, signal?: AbortSignal): Promise<PlanResult> {
  return read(await fetch(`${BASE}/plan`, json('POST', body, signal)));
}
export async function startRun(body: { doc_ids: string[]; presets: Preset[]; candidates: Candidate[]; top_k: number }): Promise<Run> {
  return read(await fetch(`${BASE}/runs`, json('POST', body)));
}
export const getRun = async (signal?: AbortSignal): Promise<Run | null> => (await read<{ run: Run | null }>(await fetch(`${BASE}/runs/current`, { signal }))).run;
export const cancelRun = async (): Promise<boolean> => (await read<{ cancelled: boolean }>(await fetch(`${BASE}/runs/current/cancel`, { method: 'POST' }))).cancelled;
export async function getDrilldown(combo: string, index: number, signal?: AbortSignal): Promise<Drilldown> {
  return read(await fetch(`${BASE}/runs/current/questions/${index}?combo=${encodeURIComponent(combo)}`, { signal }));
}
