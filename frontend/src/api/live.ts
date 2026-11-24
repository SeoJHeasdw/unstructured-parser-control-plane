/** API boundary for explicit local file operations. No request runs until called. */
export type LiveStatus = 'uploaded' | 'processing' | 'completed' | 'failed' | 'unsupported';
/** seq: 문서 번호. 화면과 작업 에이전트가 'D12'처럼 부른다. 예전 서버는 보내지 않는다. */
export type LiveDoc = { id: string; name: string; format: string; size_bytes: number; status: LiveStatus; created_at: string; updated_at: string; parser: string | null; error: string | null; error_code?: string | null; seq?: number | null };
export type LiveResult = { id: string; markdown: string; parser: string; parser_version: string; is_stale: boolean; fidelity?: {findings?: {message: string}[]} | null; warnings: string[] };
export type ResultLocation = { start_line: number; end_line: number; page: number | null; start_offset?: number | null; end_offset?: number | null; sheet: string | null; row: number | null; column: number | null; columns: number | null };
export type ParseRun = { run_id: string; completed_at: string | null; parser: string | null; parser_version: string | null; ocr_enabled: boolean | null; is_latest: boolean; duration_ms?: number | null };
export type StoredParseRun = ParseRun & { markdown: string; warnings: string[]; locations: ResultLocation[] };
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

export async function processLiveDocument(id:string):Promise<LiveDoc> {
 return readResponse<LiveDoc>(await fetch(`${documentUrl(id)}/process`,{method:'POST'}));
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
