/** API boundary for explicit local file operations. No request runs until called. */
export type LiveStatus = 'uploaded' | 'processing' | 'completed' | 'failed' | 'unsupported';
/** seq: 문서 번호. 화면과 작업 에이전트가 'D12'처럼 부른다. 예전 서버는 보내지 않는다. */
/** 자동 대조 판정 상태(최신 성공 실행, 사람 판정 합침). pending: 미평가 · unavailable: 원본을 읽을 수 없어 대조 못 함 */
export type QcState = 'pending' | 'needs_review' | 'undetermined' | 'pass_candidate' | 'unavailable';
/** previous: 지금 처리 중이거나 실패해서, 이 판정은 이전 성공본의 것(label에 '이전 성공본 · …'). 현재 판정 수에 넣지 않는다. */
export type DocQc = { state: QcState; label: string; unresolved: number | null; previous?: boolean };
/** qc: 목록 질의(쪽 단위)에만 붙는다. 전체 목록(예전 호환)에는 없다. */
export type LiveDoc = { id: string; name: string; format: string; size_bytes: number; status: LiveStatus; created_at: string; updated_at: string; parser: string | null; error: string | null; error_code?: string | null; seq?: number | null; qc?: DocQc | null };
export type LiveResult = { id: string; markdown: string; parser: string; parser_version: string; is_stale: boolean; fidelity?: {findings?: {message: string}[]} | null; warnings: string[] };
export type ResultLocation = { start_line: number; end_line: number; page: number | null; start_offset?: number | null; end_offset?: number | null; sheet: string | null; row: number | null; column: number | null; columns: number | null };
export type ParseRun = { run_id: string; completed_at: string | null; parser: string | null; parser_version: string | null; ocr_enabled: boolean | null; is_latest: boolean; duration_ms?: number | null };
export type StoredParseRun = ParseRun & { markdown: string; warnings: string[]; locations: ResultLocation[]; evidence?: Record<string, unknown> | null; options?: ProcessOptions | null };
/** 텍스트·CSV의 원천 계약. 지정하면 파서가 고르지 않고 이 값으로 읽는다(실행에 기록). */
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
  try { const body = await response.json() as {detail?:unknown;message?:unknown}; const detail = body.detail ?? body.message; if(typeof detail === 'string')message = detail; } catch { /* Keep the status-only message. */ }
  throw new LiveRequestError(message, response.status);
 }
 return await response.json() as T;
}

/** ocr_models_found: OCR 모델 연결 설정 여부(호출해 보지는 않음). ocr_model은 예전 서버에 없다. */
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

/** 자동 대조(GET …/verify): 원본 글자와 결과를 비교한 원장. 의심 지점(S번호)은 우선순위 순으로 한 쪽씩 온다. 판정이 아니라 사람이 볼 곳의 후보다.
 * id: finding ID(규칙이 바뀌어도 같은 사실을 가리킴). rank: 검수 우선순위(0부터). 예전 서버는 id·rank를 보내지 않는다. */
export type VerifySpot = {
 key: string; id?: string; rank?: number; severity: 'high' | 'medium' | 'low'; kind: string; message: string; unit: string; label: string;
 page: number | null; sheet: string | null; cell: string | null; ref: string; line: number | null; line_end: number | null;
 source: string; source_hit: string; result: string; result_hit: string; result_role?: 'same' | 'before'; source_layer?: string;
};
export type VerifyUnit = { key: string; label: string; page: number | null; sheet: string | null; kind: string; note: string; source_chars: number;
 matched_chars: number; coverage: number | null; numbers_missing: number; numbers_extra: number; spots: number; state: string; result_lines: number[] };
/** 판정 근거 한 줄. blocking이면 그것만으로 통과 후보가 될 수 없다. */
export type QcReason = { code: string; message: string; blocking: boolean; [key: string]: unknown };
export type QcCheck = { id: string; label: string; state: 'done' | 'partial' | 'unverified' | string; detail?: string; method?: string;
 source_layer?: string; derived_from?: string; units?: number; checked?: number; excluded?: number; unverified?: number };
export type QcGate = { state: Exclude<QcState, 'pending' | 'unavailable'>; label: string; reasons: QcReason[]; unresolved: number; unresolved_high: number;
 open_reviews: number; wrong_reviews: number; note?: string };
export type VerifyResult = {
 id: string; run_id: string; is_latest: boolean; method: string; format: string; parser: string;
 summary: { units: number; checked: number; source_chars: number; matched_chars: number; coverage: number | null; spots: number; high: number; medium: number; low: number; scan_units: number };
 units: VerifyUnit[]; spots: VerifySpot[]; spots_total: number; top: string[]; notes: string[];
 /* 원장(2026-11-27). 예전 서버에는 없다. */
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
/** 의심점 하나(S번호 또는 finding ID). 받은 쪽에 없는 지점(주소의 check=S441)을 열 때 쓴다. */
export async function getVerifySpot(id: string, ref: string, run: string | undefined, signal?: AbortSignal): Promise<VerifySpot & { run_id: string }> {
 const query = run ? `?run=${encodeURIComponent(run)}` : '';
 return readResponse(await fetch(`${documentUrl(id)}/verify/spots/${encodeURIComponent(ref)}${query}`, signal ? {signal} : undefined));
}

/** 처리 깔때기: 반입 전체 → 파싱 완료 → 자동 대조 → 판정 상태. not_parsed: 파싱하지 못한 사유(오류 코드·상태)별 수. */
export type QcSummary = { rule_version: string; documents: number; parsed: number; qc_done: number; qc_pending: number; qc_unavailable: number;
 states: Record<'needs_review' | 'undetermined' | 'pass_candidate', number>; not_parsed: Record<string, number>; human_decided: number; processing: number;
 /** 대조 규칙이 바뀌어 이전 규칙의 원장만 있는 실행 수와, 서버 시작 때의 다시 대조 진행(예전 서버는 없다) */
 /** 지금 처리 중·실패지만 이전 성공본이 있는 문서(상태별). 파싱 완료·판정 수에 들어가지 않는다. */
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

/** 문서함 한 쪽(서버가 검색·상태·확장자·정렬을 처리). facets.formats: 확장자('' = 확장자 없음) → 수, facets.statuses: 화면 상태 → 수. */
export type DocSort = 'recent' | 'updated' | 'name';
export type DocPage = { documents: LiveDoc[]; total: number; next_cursor: string | null; facets: { formats: Record<string, number>; statuses: Record<string, number> };
 /** 예전 서버: 조건을 모르고 전체 목록만 준다(화면이 거르고 센다). */
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
/** 지정한 문서들만(지금 쪽 밖에서 처리 중인 문서의 완료 알림). */
export async function getDocumentsByIds(ids: string[], signal?: AbortSignal): Promise<LiveDoc[]> {
 if (!ids.length) return [];
 const body = await readResponse<{documents: LiveDoc[]}>(await fetch(`${DOCUMENTS_URL}?ids=${encodeURIComponent(ids.join(','))}`, signal ? {signal} : undefined));
 return Array.isArray(body.documents) ? body.documents : [];
}

export async function getLiveResult(id:string, signal:AbortSignal):Promise<LiveResult|null> {
 const response = await fetch(`${documentUrl(id)}/result`,{signal});
 if (response.status !== 409) return readResponse<LiveResult>(response);
 let detail: unknown;
 try { detail = ((await response.json()) as {detail?:unknown}).detail; } catch { /* An unreadable response is an error, not an empty result. */ }
 // The current API lacks an error code for this case; isolate the message dependency here.
 if (detail === '완료된 파싱 결과가 없습니다.') return null;
 throw new Error(typeof detail === 'string' ? detail : '결과를 불러오지 못했습니다. (HTTP 409)');
}

/* ----- 구조 분석: 하위 문서와 링크. 사용자가 요청할 때만 실행한다. ----- */
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

/* ----- 허용 폴더에서 가져오기. 브라우저는 허용 폴더 기준 상대 경로만 보내고, 서버가 이 컴퓨터의 파일을 직접 읽어 저장한다. ----- */
export type ImportRoot = { index: number; path: string; name: string };
/** default: 설정이 비어 프로젝트 samples 폴더를 쓰는 중. setting: 허용 폴더를 정하는 .env 항목 이름 */
export type ImportRoots = { roots: ImportRoot[]; notes: string[]; default: boolean; setting: string; max_bytes: number };
/** ready: 파서 있음 · no_parser: 저장만(파싱 경로 없음) · empty·too_large: 가져오지 않음 */
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

/** 고른 파일을 로컬 저장소에 복사한다. 파싱은 시작하지 않는다. */
export async function importFromFolder(root: number, paths: string[]): Promise<ImportItem[]> {
 const body = await readResponse<{items: ImportItem[]}>(await fetch(IMPORT_URL, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root, paths})}));
 if (!Array.isArray(body.items)) throw new Error('가져오기 응답 형식을 확인할 수 없습니다.');
 return body.items;
}
