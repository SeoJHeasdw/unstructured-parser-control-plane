/** 검수 요청(V번호): 사람이 원문 대조로 확인할 곳과 그 판정. 작업 에이전트(flag)나 원문 대조 화면이 만든다. */
export type ReviewStatus = 'open' | 'correct' | 'wrong' | 'unclear';
export const reviewStatusLabels: Record<ReviewStatus, string> = { open: '확인 전', correct: '맞음', wrong: '틀림', unclear: '보류' };
export type Review = {
  id: number; document_id: string; document_seq: number | null; document_name: string; document_format: string; document_status: string;
  run_id: string | null; is_latest_run: boolean | null; created_at: string; updated_at: string; decided_at: string | null;
  origin: 'agent' | 'console' | string; spot: string | null; kind: string; severity: 'high' | 'medium' | 'low' | null;
  page: number | null; sheet: string | null; cell: string | null; line: number | null; line_end: number | null; ref: string | null;
  note: string; source_text: string | null; source_hit: string | null; result_text: string | null; result_hit: string | null;
  status: ReviewStatus; comment: string | null; batch: number | null;
  /** 자동 대조 원장의 finding ID와 규칙 버전(V를 만들 때의 스냅샷). 예전 서버·직접 올린 요청은 없다. */
  finding_id?: string | null; rule_version?: string | null;
};
export type ReviewList = { reviews: Review[]; counts: Partial<Record<ReviewStatus, number>> };
export type ReviewDraft = Partial<Pick<Review, 'run_id' | 'spot' | 'kind' | 'severity' | 'page' | 'sheet' | 'cell' | 'line' | 'line_end' | 'ref' |
  'note' | 'source_text' | 'source_hit' | 'result_text' | 'result_hit' | 'status' | 'comment' | 'finding_id'>> & { document_id: string; origin?: 'agent' | 'console' };

const URL_BASE = '/api/live/reviews';

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `검수 요청을 처리하지 못했습니다. (HTTP ${response.status})`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === 'string') message = body.detail;
    } catch { /* 상태 번호만 남긴다 */ }
    if (response.status === 404 && message.startsWith('검수 요청을 처리하지')) message = '이 서버에는 검수 요청 기능이 없습니다. 서버를 최신 버전으로 다시 시작해 주세요.';
    throw new Error(message);
  }
  return await response.json() as T;
}

export async function listReviews(options: { doc?: string; status?: ReviewStatus | 'all'; limit?: number } = {}, signal?: AbortSignal): Promise<ReviewList> {
  const params = new URLSearchParams();
  if (options.doc) params.set('doc', options.doc);
  if (options.status && options.status !== 'all') params.set('status', options.status);
  params.set('limit', String(options.limit ?? 500));
  const body = await read<ReviewList>(await fetch(`${URL_BASE}?${params}`, signal ? { signal } : undefined));
  if (!Array.isArray(body.reviews)) throw new Error('검수 요청 목록의 응답 형식을 확인할 수 없습니다.');
  return { reviews: body.reviews, counts: body.counts ?? {} };
}

export async function createReview(draft: ReviewDraft): Promise<Review & { created: boolean }> {
  return read(await fetch(URL_BASE, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ origin: 'console', ...draft }) }));
}

export async function updateReview(id: number, patch: { status?: ReviewStatus; comment?: string }): Promise<Review> {
  return read(await fetch(`${URL_BASE}/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }));
}

/** V12 → 사람이 읽는 위치 이름: '3쪽 · 결과 줄 120', '시트 요약!B5' */
export function reviewWhere(item: { page?: number | null; sheet?: string | null; cell?: string | null; line?: number | null; line_end?: number | null; ref?: string | null },
  unit: 'page' | 'slide' = 'page') {
  const parts = [] as string[];
  if (item.page) parts.push(unit === 'slide' ? `슬라이드 ${item.page}` : `${item.page}쪽`);
  if (item.sheet) parts.push(item.cell ? `${item.sheet}!${item.cell}` : `시트 ${item.sheet}`);
  if (!item.page && !item.sheet && item.ref) parts.push(item.ref);
  if (item.line) parts.push(`결과 줄 ${item.line}${item.line_end && item.line_end !== item.line ? `-${item.line_end}` : ''}`);
  return parts.join(' · ');
}
