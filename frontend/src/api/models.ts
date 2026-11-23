/** 모델 연결 API. API 키는 보내기만 하고 응답에는 설정 여부(api_key_set)만 온다. */
export type ChatConnection = { key: 'primary' | 'secondary'; label: string; base_url: string; model_id: string; api_key_set: boolean; configured: boolean; saved?: boolean };
export type EmbeddingConnection = { key: string; label: string; base_url: string; models: string[]; api_key_set: boolean; configured: boolean; saved?: boolean };
export type Listing = { connections: ChatConnection[]; embedding: EmbeddingConnection | null };
export type Check = { ok: boolean; status: number | null; latency_ms: number; reply?: string; model?: string; models?: string[]; dims?: number; tokens?: number | null; error?: string };
/** 편집 중인 값. api_key가 비어 있으면 저장된 키를 그대로 둔다. */
export type Draft = { label: string; base_url: string; model_id: string; models: string[]; api_key: string; clear_api_key: boolean };

async function readError(response: Response) {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null;
  return typeof body?.detail === 'string' ? body.detail : `HTTP ${response.status}`;
}

async function send<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}

const jsonInit = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

/** 연결 확인·목록 조회는 실패도 결과(ok:false)로 돌려준다. */
export async function runCheck(url: string, body?: unknown): Promise<Check> {
  const response = await fetch(url, body === undefined ? { method: 'POST' } : jsonInit('POST', body)).catch(() => null);
  if (!response) return { ok: false, status: null, latency_ms: 0, error: '로컬 서버에 연결하지 못했습니다.' };
  const payload = await response.json().catch(() => null) as (Partial<Check> & { detail?: string }) | null;
  if (typeof payload?.ok !== 'boolean') return { ok: false, status: response.status, latency_ms: 0, error: payload?.detail ?? (response.ok ? '응답 형식을 확인할 수 없습니다.' : `HTTP ${response.status}`) };
  return payload as Check;
}

export const saveConnection = (slot: 'primary' | 'secondary' | 'embedding', draft: Draft) => send<Listing>(`/api/models/${slot}`, jsonInit('PUT', {
  label: draft.label, base_url: draft.base_url, ...(slot === 'embedding' ? { models: draft.models } : { model_id: draft.model_id }),
  ...(draft.clear_api_key ? { clear_api_key: true } : draft.api_key.trim() ? { api_key: draft.api_key } : {}),
}));
export const forgetConnection = (slot: 'primary' | 'secondary' | 'embedding') => send<Listing>(`/api/models/${slot}/saved`, { method: 'DELETE' });
export const draftBody = (slot: 'primary' | 'secondary' | 'embedding', draft: Draft, model?: string) => ({
  kind: slot === 'embedding' ? 'embed' : 'chat', key: slot === 'embedding' ? undefined : slot, base_url: draft.base_url,
  model_id: draft.model_id, models: draft.models, model, ...(draft.clear_api_key ? { clear_api_key: true } : draft.api_key.trim() ? { api_key: draft.api_key } : {}),
});
