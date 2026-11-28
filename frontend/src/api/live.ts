export type LiveStatus = 'uploaded' | 'processing' | 'completed' | 'failed' | 'unsupported';
export type QcState = 'pending' | 'needs_review' | 'undetermined' | 'pass_candidate' | 'unavailable';
export type DocQc = { state: QcState; label: string; unresolved: number | null; previous?: boolean;
 wrong?: number };
export type LiveDoc = { id: string; name: string; format: string; size_bytes: number; status: LiveStatus; created_at: string; updated_at: string; parser: string | null; error: string | null; error_code?: string | null; seq?: number | null; qc?: DocQc | null };
export type LiveResult = { id: string; markdown: string; parser: string; parser_version: string; is_stale: boolean; fidelity?: {findings?: {message: string}[]} | null; warnings: string[] };
export type ResultLocation = { start_line: number; end_line: number; page: number | null; start_offset?: number | null; end_offset?: number | null; sheet: string | null; row: number | null; column: number | null; columns: number | null };
export type ParseRun = { run_id: string; completed_at: string | null; parser: string | null; parser_version: string | null; ocr_enabled: boolean | null; is_latest: boolean; duration_ms?: number | null };
export type StoredParseRun = ParseRun & { markdown: string; warnings: string[]; locations: ResultLocation[]; evidence?: Record<string, unknown> | null; options?: ProcessOptions | null };
export type ProcessOptions = { csv_delimiter?: ',' | ';' | '\t' | '|'; encoding?: 'utf-8' | 'utf-8-sig' | 'cp949' | 'utf-16' | 'utf-16-le' | 'utf-16-be' | 'utf-32' };
export type SourcePreview =
 | { kind: 'text'; text: string; truncated: boolean }
 | { kind: 'sheet'; sheets: string[]; sheet: string; first_row: number; cell: string; columns: string[]; rows: string[][] };

const DOCUMENTS_URL = '/api/live/documents';
const documentUrl = (id:string) => `${DOCUMENTS_URL}/${encodeURIComponent(id)}`;
export const liveSourceUrl = (id: string) => `${documentUrl(id)}/source`;

export class LiveRequestError extends Error {
 constructor(message: string, readonly status: number) { super(message); }
}

async function readResponse<T>(response:Response):Promise<T> {
 if (!response.ok) {
  let message = `요청을 처리하지 못했습니다. (HTTP ${response.status})`;
  try { const body = await response.json() as {detail?:unknown;message?:unknown}; const detail = body.detail ?? body.message; if(typeof detail === 'string')message = detail; } catch { }
  throw new LiveRequestError(message, response.status);
 }
 return await response.json() as T;
}

export type ParserCatalog = {
 routes: Record<string, string>; docling_installed: boolean; pdf_model_directory: boolean;
 pdf_models_ready?: boolean; pdf_missing_files?: string[];
 ocr_enabled: boolean; ocr_models_found: boolean;
 ocr_model?: { label: string; model_id: string; mode: 'region' | 'page'; configured: boolean } | null;
};
export async function getParserCatalog(signal: AbortSignal): Promise<ParserCatalog> {
 const catalog = await readResponse<ParserCatalog>(await fetch('/api/live/parsers', { signal }));
 if (!catalog?.routes || typeof catalog.routes !== 'object' || Array.isArray(catalog.routes)) {
  throw new Error('파서 목록의 응답 형식을 확인할 수 없습니다.');
 }
 return catalog;
}

export async function listLiveDocuments(signal?: AbortSignal):Promise<LiveDoc[]> {
 const body = await readResponse<{documents:LiveDoc[]}>(await (signal ? fetch(DOCUMENTS_URL, {signal}) : fetch(DOCUMENTS_URL)));
 if(!Array.isArray(body.documents))throw new Error('문서 목록의 응답 형식을 확인할 수 없습니다.');
 return body.documents;
}

export async function listParseRuns(id: string, signal: AbortSignal): Promise<ParseRun[]> {
 const body = await readResponse<{runs: ParseRun[]}>(await fetch(`${documentUrl(id)}/runs`, {signal}));
 if (!Array.isArray(body.runs)) throw new Error('성공 실행 목록을 확인할 수 없습니다.');
 return body.runs;
}

export async function getParseRun(id: string, runId: string, signal: AbortSignal): Promise<StoredParseRun> {
 return readResponse<StoredParseRun>(await fetch(`${documentUrl(id)}/runs/${encodeURIComponent(runId)}`, {signal}));
}

export async function getSourcePreview(id: string, signal: AbortSignal, sheet?: string, cell?: string): Promise<SourcePreview> {
 const params = new URLSearchParams();
 if (sheet) params.set('sheet', sheet);
 if (cell) params.set('cell', cell);
 return readResponse<SourcePreview>(await fetch(`${documentUrl(id)}/source-preview?${params}`, {signal}));
}

export type VerifySpot = {
 key: string; id?: string; rank?: number; severity: 'high' | 'medium' | 'low'; kind: string; message: string; unit: string; label: string;
 page: number | null; sheet: string | null; cell: string | null; ref: string; line: number | null; line_end: number | null;
 source: string; source_hit: string; result: string; result_hit: string; result_role?: 'same' | 'before'; source_layer?: string;
};
export type VerifyUnit = { key: string; label: string; page: number | null; sheet: string | null; kind: string; note: string; source_chars: number;
 matched_chars: number; coverage: number | null; numbers_missing: number; numbers_extra: number; spots: number; state: string; result_lines: number[] };
export type QcReason = { code: string; message: string; blocking: boolean; [key: string]: unknown };
export type QcCheck = { id: string; label: string; state: 'done' | 'partial' | 'unverified' | string; detail?: string; method?: string;
 source_layer?: string; derived_from?: string; units?: number; checked?: number; excluded?: number; unverified?: number };
export type QcGate = { state: Exclude<QcState, 'pending' | 'unavailable'>; label: string; reasons: QcReason[]; unresolved: number; unresolved_high: number;
 open_reviews: number; wrong_reviews: number; note?: string };
export type VerifyResult = {
 id: string; run_id: string; is_latest: boolean; method: string; format: string; parser: string;
 summary: { units: number; checked: number; source_chars: number; matched_chars: number; coverage: number | null; spots: number; high: number; medium: number; low: number; scan_units: number };
 units: VerifyUnit[]; spots: VerifySpot[]; spots_total: number; top: string[]; notes: string[];
 rule_version?: string; document_status?: string; spots_matched?: number; page?: { offset: number; limit: number; order: string; next: number | null };
 top_spots?: VerifySpot[]; gate?: QcGate; reasons?: QcReason[]; checks?: QcCheck[]; verdicts?: Record<string, string>;
};
export type VerifyQuery = { severity?: ('high' | 'medium' | 'low')[]; unit?: string; order?: 'priority' | 'document'; offset?: number; limit?: number; unreviewed?: boolean };
export async function getVerify(id: string, run: string | undefined, signal?: AbortSignal, query: VerifyQuery = {}): Promise<VerifyResult> {
 const params = new URLSearchParams();
 if (run) params.set('run', run);
 if (query.severity?.length) params.set('severity', query.severity.join(','));
 if (query.unit) params.set('unit', query.unit);
 if (query.order) params.set('order', query.order);
 if (query.offset) params.set('offset', String(query.offset));
 if (query.limit) params.set('limit', String(query.limit));
 if (query.unreviewed) params.set('unreviewed', 'true');
 const text = params.toString();
 const body = await readResponse<VerifyResult>(await fetch(`${documentUrl(id)}/verify${text ? `?${text}` : ''}`, signal ? {signal} : undefined));
 if (!Array.isArray(body.spots)) throw new Error('자동 대조의 응답 형식을 확인할 수 없습니다.');
 return body;
}
export async function getVerifySpot(id: string, ref: string, run: string | undefined, signal?: AbortSignal): Promise<VerifySpot & { run_id: string }> {
 const query = run ? `?run=${encodeURIComponent(run)}` : '';
 return readResponse(await fetch(`${documentUrl(id)}/verify/spots/${encodeURIComponent(ref)}${query}`, signal ? {signal} : undefined));
}

export type QcSummary = { rule_version: string; documents: number; parsed: number; qc_done: number; qc_pending: number; qc_unavailable: number;
 states: Record<'needs_review' | 'undetermined' | 'pass_candidate', number>; not_parsed: Record<string, number>; human_decided: number; processing: number;
 previous_results?: Record<string, number>;
 qc_stale?: number; reverify?: { state: 'idle' | 'running' | 'done' | 'failed' | 'stopped'; total: number; stale: number; done: number; failed: number; rule_version: string } };
export async function getQcSummary(signal?: AbortSignal): Promise<QcSummary> {
 return readResponse<QcSummary>(await fetch('/api/live/qc-summary', signal ? {signal} : undefined));
}

export async function getLiveDocument(id:string, signal:AbortSignal):Promise<LiveDoc> {
 return readResponse<LiveDoc>(await fetch(documentUrl(id),{signal}));
}

export type HistoryEntry = { created_at: string; status: string; message: string };
export async function getDocumentHistory(id: string, signal: AbortSignal): Promise<HistoryEntry[]> {
 const body = await readResponse<{history: HistoryEntry[]}>(await fetch(`${documentUrl(id)}/history`, {signal}));
 return body.history;
}

export async function uploadLiveDocument(file:File):Promise<LiveDoc> {
 const form=new FormData();
 form.append('file',file);
 return readResponse<LiveDoc>(await fetch(DOCUMENTS_URL,{method:'POST',body:form}));
}

export async function processLiveDocument(id:string, options?: ProcessOptions):Promise<LiveDoc> {
 const body = options && Object.keys(options).length ? { headers: {'Content-Type': 'application/json'}, body: JSON.stringify(options) } : {};
 return readResponse<LiveDoc>(await fetch(`${documentUrl(id)}/process`,{method:'POST', ...body}));
}

export type DocSort = 'recent' | 'updated' | 'name';
/** facets.formats의 키 ''는 확장자 없음 */
export type DocPage = { documents: LiveDoc[]; total: number; next_cursor: string | null; facets: { formats: Record<string, number>; statuses: Record<string, number> };
 legacy?: boolean };
export type DocQuery = { q?: string; status?: string; format?: string | null; sort?: DocSort; cursor?: string | null; limit?: number };
export async function listDocumentPage(query: DocQuery, signal?: AbortSignal): Promise<DocPage> {
 const params = new URLSearchParams();
 if (query.q?.trim()) params.set('q', query.q.trim());
 params.set('status', query.status || 'all');
 if (query.format !== null && query.format !== undefined) params.set('format', query.format === '' ? '-' : query.format);
 params.set('sort', query.sort ?? 'recent');
 if (query.cursor) params.set('cursor', query.cursor);
 params.set('limit', String(query.limit ?? 50));
 const body = await readResponse<DocPage>(await fetch(`${DOCUMENTS_URL}?${params}`, signal ? {signal} : undefined));
 if (!Array.isArray(body.documents)) throw new Error('문서 목록의 응답 형식을 확인할 수 없습니다.');
 if (typeof body.total !== 'number') return { documents: body.documents, total: body.documents.length, next_cursor: null, facets: { formats: {}, statuses: {} }, legacy: true };
 return body;
}
export async function getDocumentsByIds(ids: string[], signal?: AbortSignal): Promise<LiveDoc[]> {
 if (!ids.length) return [];
 const body = await readResponse<{documents: LiveDoc[]}>(await fetch(`${DOCUMENTS_URL}?ids=${encodeURIComponent(ids.join(','))}`, signal ? {signal} : undefined));
 return Array.isArray(body.documents) ? body.documents : [];
}

export async function getLiveResult(id:string, signal:AbortSignal):Promise<LiveResult|null> {
 const response = await fetch(`${documentUrl(id)}/result`,{signal});
 if (response.status !== 409) return readResponse<LiveResult>(response);
 let detail: unknown;
 try { detail = ((await response.json()) as {detail?:unknown}).detail; } catch { }
 // The current API lacks an error code for this case; isolate the message dependency here.
 if (detail === '완료된 파싱 결과가 없습니다.') return null;
 throw new Error(typeof detail === 'string' ? detail : '결과를 불러오지 못했습니다. (HTTP 409)');
}

/* 구조 분석은 사용자가 요청할 때만 실행한다. */
export type StructLink = { kind: string; target: string; location: string; evidence: string };
export type StructNode = { name: string; ext: string; size: number; kind: string; location: string; detected: string | null; flags: string[]; stats: Record<string, unknown>; links: StructLink[]; children: StructNode[]; hash: string | null; duplicate_of: string | null };
export type StructSummary = { documents: number; derived: number; max_depth: number; links: number; by_child_kind: Record<string, number>; by_link_kind: Record<string, number>; flags: Record<string, number>; detected: Record<string, number> };
export type LiveStructure = { id: string; name: string; format: string; inspected_at: string; root: StructNode; summary: StructSummary };
export type StructureOverview = { documents_total: number; inspected: number; documents: number; derived: number; max_depth: number; links: number; with_children: number; with_links: number; expansion: number | null; by_child_kind: Record<string, number>; by_link_kind: Record<string, number>; flags: Record<string, number> };

export async function inspectLiveDocument(id:string):Promise<LiveStructure> {
 return readResponse<LiveStructure>(await fetch(`${documentUrl(id)}/structure`,{method:'POST'}));
}
export async function getLiveStructure(id:string, signal?:AbortSignal):Promise<LiveStructure|null> {
 const response = await fetch(`${documentUrl(id)}/structure`,{signal});
 if (response.status === 409) return null;
 return readResponse<LiveStructure>(response);
}
export async function getStructureOverview():Promise<StructureOverview> {
 return readResponse<StructureOverview>(await fetch('/api/live/structure-summary'));
}

export type ImportRoot = { index: number; path: string; name: string };
/** setting: 허용 폴더를 정하는 .env 항목 이름 */
export type ImportRoots = { roots: ImportRoot[]; notes: string[]; default: boolean; setting: string; max_bytes: number };
export type ImportFileState = 'ready' | 'no_parser' | 'empty' | 'too_large';
export type ImportExisting = { id: string; seq: number | null; status: string };
export type ImportFile = { path: string; name: string; format: string; size_bytes: number; modified_at: string; state: ImportFileState; existing: ImportExisting[] };
export type ImportListing = { root: number; path: string; parent: string | null; recursive: boolean; folders: {name: string; path: string}[]; files: ImportFile[]; truncated: boolean };
export type ImportItem = { path: string; outcome: 'imported' | 'reused' | 'failed'; document?: LiveDoc | null; reason?: string | null };
const IMPORT_URL = '/api/live/import';

export async function getImportRoots(signal?: AbortSignal): Promise<ImportRoots> {
 const body = await readResponse<ImportRoots>(await fetch(`${IMPORT_URL}/roots`, {signal}));
 if (!Array.isArray(body.roots)) throw new Error('허용 폴더 응답 형식을 확인할 수 없습니다.');
 return body;
}

export async function listImportEntries(root: number, path: string, recursive: boolean, signal?: AbortSignal): Promise<ImportListing> {
 const params = new URLSearchParams({root: String(root), path, recursive: String(recursive)});
 const body = await readResponse<ImportListing>(await fetch(`${IMPORT_URL}/entries?${params}`, {signal}));
 if (!Array.isArray(body.files) || !Array.isArray(body.folders)) throw new Error('폴더 목록 응답 형식을 확인할 수 없습니다.');
 return body;
}

export async function importFromFolder(root: number, paths: string[]): Promise<ImportItem[]> {
 const body = await readResponse<{items: ImportItem[]}>(await fetch(IMPORT_URL, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root, paths})}));
 if (!Array.isArray(body.items)) throw new Error('가져오기 응답 형식을 확인할 수 없습니다.');
 return body.items;
}
