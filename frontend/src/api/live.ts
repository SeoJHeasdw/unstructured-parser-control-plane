/** API boundary for explicit local file operations. No request runs until called. */
export type LiveStatus = 'uploaded' | 'processing' | 'completed' | 'failed' | 'unsupported';
export type LiveDoc = { id: string; name: string; format: string; size_bytes: number; status: LiveStatus; created_at: string; updated_at: string; parser: string | null; error: string | null };
export type LiveResult = { id: string; markdown: string; parser: string; parser_version: string; is_stale: boolean; warnings: string[] };

const DOCUMENTS_URL = '/api/live/documents';
const documentUrl = (id:string) => `${DOCUMENTS_URL}/${encodeURIComponent(id)}`;

async function readResponse<T>(response:Response):Promise<T> {
 if (!response.ok) {
  let message = `요청을 처리하지 못했습니다. (HTTP ${response.status})`;
  try { const body = await response.json() as {detail?:unknown;message?:unknown}; const detail = body.detail ?? body.message; if(typeof detail === 'string')message = detail; } catch { /* Keep the status-only message. */ }
  throw new Error(message);
 }
 return await response.json() as T;
}

export async function listLiveDocuments():Promise<LiveDoc[]> {
 const body = await readResponse<{documents:LiveDoc[]}>(await fetch(DOCUMENTS_URL));
 if(!Array.isArray(body.documents))throw new Error('문서 목록의 응답 형식을 확인할 수 없습니다.');
 return body.documents;
}

export async function getLiveDocument(id:string, signal:AbortSignal):Promise<LiveDoc> {
 return readResponse<LiveDoc>(await fetch(documentUrl(id),{signal}));
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
