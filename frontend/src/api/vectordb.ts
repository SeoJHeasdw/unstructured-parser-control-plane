/** 벡터 DB 읽기 전용 API. 예시 데이터(example)와 Milvus(milvus)가 같은 형태로 응답한다. */
export type SourceKey = 'example' | 'milvus';
export type MilvusPublic = { configured: boolean; uri: string; db: string; token_set: boolean; ca_bundle_set: boolean; timeout: number; unreachable?: { retry_in: number; error: string } | null };
export type SourcesInfo = { default: SourceKey; sources: { key: SourceKey; label: string; available: boolean }[]; milvus: MilvusPublic; max_window: number };
export type CheckResult = { ok: boolean; status: number | null; latency_ms: number; databases?: string[]; db?: string; db_found?: boolean; note?: string | null; error?: string };

export type PartitionNode = { name: string; row_count: number | null; error: string | null };
export type CollectionNode = { name: string; row_count: number | null; dim: number | null; vector_field: string | null; vector_fields: number; metric: string | null; load_state: string | null; description?: string; partitions: PartitionNode[]; error: string | null };
export type DatabaseNode = { name: string; error: string | null; collections: CollectionNode[] };
export type Tree = { source: SourceKey; databases: DatabaseNode[]; warnings: string[]; totals: { databases: number; collections: number; partitions: number; rows: number } };

export type FieldInfo = { name: string; type: string; element_type: string | null; dim: number | null; max_length: number | null; max_capacity: number | null; primary_key: boolean; auto_id: boolean; nullable: boolean | null; partition_key: boolean; description: string; is_vector: boolean; index_type: string | null };
export type VectorField = { name: string; type: string; dim: number | null; description: string; index_name: string | null; index_type: string | null; metric: string | null; index_params: Record<string, unknown> | null; index_state: string | null; indexed_rows: number | null; total_rows: number | null; pending_rows: number | null; fail_reason: string | null };
export type Detected = { pk: string | null; text: string | null; doc: string | null; order: string | null; source: string | null; page: string | null; vector: string | null };
export type EmbeddingRecord = { model: string | null; recorded_in: string | null; dim: number | null; recorded_dim: number | null; dim_mismatch: boolean };
export type CollectionDetail = {
  db: string; name: string; description: string; row_count: number | null; load_state: string | null; load_progress: number | null; consistency_level: string | null;
  shards: number | null; partitions_num: number | null; auto_id: boolean; enable_dynamic_field: boolean; aliases: string[]; properties: { key: string; value: unknown }[];
  fields: FieldInfo[]; vector_fields: VectorField[]; partitions: PartitionNode[]; detected: Detected; embedding: EmbeddingRecord; warnings: string[];
};

export type VectorSummary = { kind: 'dense' | 'sparse' | 'opaque'; type: string; dim: number | null; norm?: number; min?: number; max?: number; mean?: number; head?: number[]; nnz?: number };
export type ChunkRow = { pk: string; text: string | null; fields: Record<string, unknown>; vector: VectorSummary | null; partition: string | null };
export type BrowseQuery = { filter: string; partition: string | null; output_fields: string[] | null; text_field: string | null; limit: number; offset: number; include_vector: boolean };
export type BrowseResult = { rows: ChunkRow[]; total: number | null; total_basis: 'count' | 'stats' | null; effective_filter: string; user_filter: string; text_field: string | null; output_fields: string[]; limit: number; offset: number; partition: string | null; max_window: number };
export type ChunkDetail = ChunkRow & { text_field: string | null; detected: Detected };
export type SimilarHit = { rank: number; pk: string; score: number | null; text: string | null; doc: unknown; order: unknown; page: unknown; same_document: boolean | null };
export type SimilarResult = { pk: string; metric: string | null; higher_is_closer: boolean | null; vector_field: string; doc_field: string | null; doc: unknown; text_field: string | null; hits: SimilarHit[] };
export type DocValues = { doc_field: string; values: { value: string; count: number }[]; scanned: number; truncated: boolean };
export type DocChunk = { index: number; pk: string; order: unknown; page: unknown; text: string | null; head_skip: number; overlap: number; tail: [number, number] | null };
export type DocumentRead = { doc_field: string; value: string; order_field: string | null; ordered_by: string; text_field: string | null; chunks: DocChunk[]; total: number; truncated: boolean; overlaps: number; overlap_avg: number };
export type Target = { db: string; collection: string };

const BASE = '/api/vectordb';

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `요청을 처리하지 못했습니다. (HTTP ${response.status})`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) message = '요청 값을 확인해 주세요.';
    } catch { /* 상태 코드만 보여 준다 */ }
    throw new Error(message);
  }
  return await response.json() as T;
}
const post = <T,>(path: string, body: unknown) => fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(response => read<T>(response));

export const getSources = () => fetch(`${BASE}/sources`).then(response => read<SourcesInfo>(response));
export async function checkMilvus(): Promise<CheckResult> {
  const response = await fetch(`${BASE}/milvus/check`, { method: 'POST' });
  const body = await response.json().catch(() => ({})) as Partial<CheckResult> & { detail?: string };
  if (!response.ok && body.ok === undefined) return { ok: false, status: response.status, latency_ms: 0, error: body.detail ?? `HTTP ${response.status}` };
  return body as CheckResult;
}
export const getTree = (source: SourceKey) => fetch(`${BASE}/${source}/tree`).then(response => read<Tree>(response));
export const getCollection = (source: SourceKey, db: string, name: string) =>
  fetch(`${BASE}/${source}/collection?db=${encodeURIComponent(db)}&name=${encodeURIComponent(name)}`).then(response => read<CollectionDetail>(response));
export const browseChunks = (source: SourceKey, target: Target, query: BrowseQuery) => post<BrowseResult>(`/${source}/browse`, { ...target, ...query });
export const getChunk = (source: SourceKey, target: Target, pk: string, textField: string | null) => post<ChunkDetail>(`/${source}/chunk`, { ...target, pk, text_field: textField });
export const findSimilar = (source: SourceKey, target: Target, pk: string, textField: string | null) => post<SimilarResult>(`/${source}/similar`, { ...target, pk, text_field: textField, limit: 10 });
export const listDocuments = (source: SourceKey, target: Target, docField: string) => post<DocValues>(`/${source}/documents`, { ...target, doc_field: docField });
/** orderField: null이면 자동 감지, 빈 문자열이면 pk 순서. */
export const readDocument = (source: SourceKey, target: Target, docField: string, value: string, orderField: string | null, textField: string | null) =>
  post<DocumentRead>(`/${source}/document`, { ...target, doc_field: docField, value, order_field: orderField, text_field: textField });
