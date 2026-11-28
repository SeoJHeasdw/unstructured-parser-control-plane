export type AgentBatch = {
  n: number; target: string; reparse: boolean; started: string | null; finished: string | null; error: string;
  /** counts 키: file(등록 전) · pending(접수 전) · queued(처리 대기·중) · done(처리 끝) · error */
  total: number; counts: Record<string, number>;
  docs: number[];
  skips: Record<string, number>;
  /** 오류 항목의 짧은 메모(missing, upload-413 등) */
  errors: string[];
};
export type AgentDocument = {
  id: string; seq: number | null; name: string; format: string; status: string; error_code: string | null; updated_at: string;
  last_agent_at: string | null; batches: number[]; calls: number; reviews: { open: number; correct: number; wrong: number; unclear: number };
};
export type AgentCall = { ts: string; tool: string; args: Record<string, unknown>; kind: string | null; repeat: boolean; ms: number | null; result: string;
  text: string; docs: number[]; session: string | null };
export type AgentActivity = { available: boolean; batches: AgentBatch[]; documents: AgentDocument[]; calls: AgentCall[] };

const ACTIVITY_URL = '/api/agent/activity';
const list = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const record = (value: unknown): Record<string, number> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, number> : {};
const count = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : 0;

/** 서버 기록 파일이 일부 깨져 있을 수 있어 빠진 값을 채운다. */
function normalize(body: Partial<AgentActivity>): AgentActivity {
  return {
    available: !!body.available,
    batches: list<Partial<AgentBatch>>(body.batches).map(batch => ({
      n: Number(batch.n) || 0, target: String(batch.target ?? ''), reparse: !!batch.reparse,
      started: batch.started ?? null, finished: batch.finished ?? null, error: batch.error ?? '',
      total: Number(batch.total) || 0, counts: record(batch.counts), docs: list<number>(batch.docs).filter(Number.isInteger),
      skips: record(batch.skips), errors: list<unknown>(batch.errors).map(note => String(note ?? '')),
    })),
    documents: list<Partial<AgentDocument>>(body.documents).filter(doc => typeof doc.id === 'string').map(doc => ({
      id: doc.id!, seq: typeof doc.seq === 'number' ? doc.seq : null, name: String(doc.name ?? ''), format: String(doc.format ?? ''),
      status: String(doc.status ?? ''), error_code: doc.error_code ?? null, updated_at: String(doc.updated_at ?? ''), last_agent_at: doc.last_agent_at ?? null,
      batches: list<number>(doc.batches).filter(Number.isInteger), calls: count(doc.calls),
      reviews: { open: count(doc.reviews?.open), correct: count(doc.reviews?.correct), wrong: count(doc.reviews?.wrong), unclear: count(doc.reviews?.unclear) },
    })),
    calls: list<Partial<AgentCall>>(body.calls).map(call => ({
      ts: String(call.ts ?? ''), tool: String(call.tool ?? ''),
      args: call.args && typeof call.args === 'object' && !Array.isArray(call.args) ? call.args : {},
      kind: call.kind || null, repeat: !!call.repeat, ms: typeof call.ms === 'number' ? call.ms : null, result: String(call.result ?? ''),
      text: typeof call.text === 'string' ? call.text : '', docs: list<number>(call.docs).filter(Number.isInteger),
      session: typeof call.session === 'string' && call.session ? call.session : null,
    })),
  };
}

export async function getAgentActivity(signal?: AbortSignal, limit = 200): Promise<AgentActivity> {
  const response = await fetch(`${ACTIVITY_URL}?limit=${limit}`, signal ? { signal } : undefined);
  if (response.status === 404) throw new Error('이 서버에는 에이전트 활동 조회가 없습니다. 서버를 최신 버전으로 다시 시작해 주세요.');
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === 'string' ? body.detail : `에이전트 활동을 불러오지 못했습니다. (HTTP ${response.status})`);
  }
  const body = await response.json().catch(() => null) as Partial<AgentActivity> | null;
  if (!body || typeof body.available !== 'boolean') throw new Error('에이전트 활동의 응답 형식을 확인할 수 없습니다.');
  return normalize(body);
}
