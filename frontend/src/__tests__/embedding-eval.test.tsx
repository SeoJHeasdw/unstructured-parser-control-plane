import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EmbeddingEval from '../EmbeddingEval';
import { STORE } from '../retrieval/shared';
import type { Combo, Metrics, PlanResult, Preset, QuestionKind, RetrievalConfig, Run } from '../api/retrieval';

/* 합성 데이터만 쓴다. */
const DOC_A = 'a'.repeat(32);
const CAPS = { max_chunks: 5000, max_questions: 500, max_presets: 4, max_candidates: 6, max_documents: 200, max_question_rows: 2000, top_k_min: 10, top_k_max: 50, max_source_chars: 2_000_000, max_bench_chunks: 5000 };
const spec = (id: string, dims: number, max_tokens: number, languages: string) => ({ id, dims, dims_note: '', max_tokens, arch: '', pooling: '', query_prefix: '', doc_prefix: '', prefix_note: '', languages, note: '' });
const SPECS = [
  spec('microsoft/harrier-oss-v1-0.6b', 1024, 32768, '다국어(한국어 포함)'), spec('Qwen/Qwen3-Embedding-0.6B', 1024, 32768, '다국어'), spec('BAAI/bge-m3', 1024, 8192, '다국어'),
  spec('intfloat/multilingual-e5-large', 1024, 512, '다국어'), spec('ibm/granite-embedding-278m-multilingual', 768, 512, '다국어(한국어 포함)'), spec('ibm/slate-125m-english-rtrvr', 768, 512, '영어 전용'),
];
const config = (configured = true): RetrievalConfig => ({
  connections: [{ key: 'embed', label: '임베딩 게이트웨이', base_url: configured ? 'http://gateway.test' : '', api_key_set: configured, configured, models: [], source: 'embed' }],
  configured, specs: SPECS, strategies: {}, caps: CAPS, cache: { entries: 0, bytes: 0 },
});
const DOCS = [{ id: DOC_A, name: '합성 절차서 A.md', format: 'md', status: 'completed', updated_at: '2026-11-17T09:00:00Z', is_stale: false }];
const SAMPLES = [
  { id: 'sop', name: '합성 절차서', description: '표와 그림이 섞인 절차서', composition: { table: 3, image: 2 }, pages: 6 },
  { id: 'spec', name: '합성 규격서', description: '큰 표 중심', composition: { table: 5 }, pages: 4 },
  { id: 'deck', name: '합성 발표 자료', description: '그림 위주', composition: { image: 6 }, pages: 8 },
];
const QUESTIONS = [
  { id: 'q1', question: '세척 허용 기준은?', doc_id: 'sample:sop', answer: '10 ppm 이하', kind: 'text' as QuestionKind },
  { id: 'q2', question: '보관 온도 범위는?', doc_id: 'sample:spec', answer: '2~8도', kind: 'table' as QuestionKind },
  { id: 'q3', question: '배치도에서 냉장고 위치는?', doc_id: 'sample:deck', answer: '', kind: 'image' as QuestionKind },
  { id: 'q4', question: '시험 주기는?', doc_id: 'sample:spec', answer: '분기', kind: 'table' as QuestionKind },
];
const PRESETS: Preset[] = [
  { id: 'p-el', name: '요소 인지 · 표 통째', kind: 'element', params: { unit: 'chars', size: 800, table: 'whole', image: 'caption' } },
  { id: 'p-fx', name: '고정 500자', kind: 'fixed', params: { unit: 'chars', size: 500, overlap: 50 } },
];
const MODELS = SPECS.slice(0, 5).map(s => s.id);
const PLAN: PlanResult = {
  documents: 3, chunks: 31, max_chunk_tokens: 1240, median_chunk_tokens: 210, errors: [],
  models: MODELS.map(m => { const s = SPECS.find(x => x.id === m)!; return { model: m, max_tokens: s.max_tokens, dims: s.dims, over_limit: s.max_tokens <= 512 ? 7 : 0, storage_bytes: s.dims * 4 * 31 }; }),
  questions: { total: 4, by_kind: { text: 1, table: 2, image: 1 } },
};
const M = (h1: number, h3: number, h5: number, h10: number, mrr: number, ndcg: number): Metrics => ({ 'hit@1': h1, 'hit@3': h3, 'hit@5': h5, 'hit@10': h10, 'mrr@10': mrr, 'ndcg@10': ndcg });
const CANDS = MODELS.map((model, i) => ({ id: `c${i + 1}`, connection: 'embed', connection_label: '임베딩 게이트웨이', model, query_prefix: '', doc_prefix: '', max_tokens: null, batch_size: 16 }));
function combo(i: number, extra: Partial<Combo> = {}): Combo {
  const c = CANDS[i];
  return {
    key: `${c.id}::p-el`, candidate_id: c.id, preset_id: 'p-el', model: c.model, connection: 'embed', connection_label: '임베딩 게이트웨이', preset_name: PRESETS[0].name, preset_kind: 'element',
    status: 'ok', error: null, doc: M(0.5, 0.75, 0.75, 1, 0.6, 0.7), span: M(0.25, 0.5, 0.5, 0.5, 0.4, 0.45), questions: 4, span_questions: 3,
    by_kind: { text: { questions: 1, doc: M(1, 1, 1, 1, 1, 1), span: M(1, 1, 1, 1, 1, 1) }, table: { questions: 2, doc: M(0.5, 0.5, 0.5, 1, 0.62, 0.66), span: M(0, 0.5, 0.5, 0.5, 0.25, 0.3) }, image: { questions: 1, doc: M(0, 0, 0, 0, 0, 0), span: null } },
    chunks: 31, documents: 3, dims: 1024, latency_ms: 38, chunks_per_sec: 35.5, throughput_source: 'measured', embedded: 31, cached: 0, failures: 0, query_failures: 0, over_limit: 0, storage_bytes: 1024 * 4 * 31,
    per_question: [{ doc_rank: 1, span_rank: 1 }, { doc_rank: 3, span_rank: null }, { doc_rank: null, span_rank: null }, { doc_rank: 1, span_rank: 2 }],
    ...extra,
  };
}
const run = (status: Run['status'] = 'completed', results?: Combo[]): Run => ({
  id: 'r1', status, created_at: '2026-11-17T10:00:00Z', finished_at: status === 'running' ? null : '2026-11-17T10:05:00Z', error: null,
  progress: { done: status === 'running' ? 3 : 10, total: 10, phase: 'BAAI/bge-m3', detail: '청크 임베딩' }, drilldown: true, caps: CAPS,
  request: { documents: SAMPLES.map(s => ({ id: `sample:${s.id}`, name: s.name })), presets: [PRESETS[0]], candidates: CANDS, questions: 4, skipped: { no_document: 0, not_selected: 0 }, top_k: 10, chunks: { 'p-el': 31 } },
  questions: QUESTIONS.map((q, index) => ({ index, id: q.id, question: q.question, doc_id: q.doc_id, answer: q.answer, kind: q.kind })),
  results: results ?? [
    combo(0, { by_kind: { ...combo(0).by_kind!, table: { questions: 2, doc: M(1, 1, 1, 1, 1, 1), span: M(0.5, 1, 1, 1, 0.75, 0.8) } } }),
    combo(1), combo(2),
    combo(3, { over_limit: 7, over_limit_failed: 2 }),
    { ...combo(4), status: 'failed', error: '게이트웨이가 응답하지 않습니다.', doc: null, span: null, by_kind: undefined },
  ],
});
const DRILL = {
  combo: 'c1::p-el', question: { index: 1, id: 'q2', question: '보관 온도 범위는?', doc_id: 'sample:spec', answer: '2~8도', kind: 'table' }, failed: false,
  results: [
    { rank: 1, score: 0.81, doc_id: 'sample:spec', doc_name: '합성 규격서', chunk_index: 4, heading_path: ['3. 보관'], chars: 320, est_tokens: 180, text: '| 항목 | 기준 |\n| 보관 온도 | 2~8도 |', hit_doc: true, hit_span: true },
    { rank: 2, score: 0.62, doc_id: 'sample:sop', doc_name: '합성 절차서', chunk_index: 1, heading_path: [], chars: 210, est_tokens: 120, text: '세척은 매 배치 후 한다.', hit_doc: false, hit_span: false },
  ],
};

type Api = { configured?: boolean; runs?: (Run | null)[]; planDelay?: number };
function mockApi({ configured = true, runs = [run()], planDelay = 0 }: Api = {}) {
  let runCall = 0;
  const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/config')) return reply(config(configured));
    if (url.endsWith('/documents')) return reply({ documents: DOCS });
    if (url.endsWith('/samples')) return reply({ samples: SAMPLES });
    if (url.endsWith('/questions') && init?.method === 'PUT') return reply({ questions: JSON.parse(String(init.body)).questions.map((q: object, i: number) => ({ id: `s${i}`, ...q })), updated_at: '2026-11-17T11:00:00Z' });
    if (url.endsWith('/questions')) return reply({ questions: QUESTIONS, updated_at: null });
    if (url.endsWith('/questions/example')) return reply({ questions: QUESTIONS.map(({ id: _id, ...q }) => q) });
    if (url.endsWith('/plan')) { if (planDelay) await new Promise(resolve => setTimeout(resolve, planDelay)); return reply(PLAN); }
    if (url.endsWith('/runs/current')) { const r = runs[Math.min(runCall, runs.length - 1)]; runCall++; return reply({ run: r }); }
    if (url.includes('/runs/current/questions/')) return reply(DRILL);
    return reply({ detail: '없음' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  const store = new Map<string, string>([[STORE.presets, JSON.stringify(PRESETS)]]);
  vi.stubGlobal('localStorage', { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => store.set(key, String(value)), removeItem: (key: string) => store.delete(key), clear: () => store.clear(), key: (index: number) => [...store.keys()][index] ?? null, get length() { return store.size; } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const board = () => screen.getByRole('region', { name: '모델 비교' });
const rowOf = (name: string) => within(board()).getByRole('rowheader', { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) }).closest('tr')!;
const cells = (row: HTMLElement) => [...row.querySelectorAll('td')].map(td => td.textContent);
const planCalls = (f: ReturnType<typeof mockApi>) => f.mock.calls.filter(([url]) => String(url).endsWith('/plan'));

describe('임베딩 평가', () => {
  it('처음 활성화될 때만 불러오고, 기본 화면은 다섯 모델과 보이는 사양, 고른 청킹 설명을 보여 준다', async () => {
    const fetchMock = mockApi({ runs: [null] });
    const { rerender } = render(<EmbeddingEval active={false} />);
    expect(fetchMock).not.toHaveBeenCalled();
    rerender(<EmbeddingEval active />);
    await screen.findByText('Harrier-OSS-v1 0.6B');
    const rows = within(board()).getAllByRole('rowheader');
    expect(rows.map(r => r.querySelector('b')!.textContent)).toEqual(['Harrier-OSS-v1 0.6B', 'Qwen3-Embedding 0.6B', 'BGE-M3', 'multilingual-e5-large', 'Granite Embedding 278M']);
    await waitFor(() => expect(rows[0].textContent).toContain('1024차원 · 입력 32K · 다국어'));
    expect(within(rows[3]).getByText('입력 512')).toBeTruthy();
    expect(within(rows[4]).getByText('입력 512')).toBeTruthy();
    expect(within(rows[0]).queryByText('입력 512')).toBeNull();
    expect(screen.queryByText('Slate 125M')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect((screen.getByRole('combobox', { name: '청킹' }) as HTMLSelectElement).value).toBe('p-el');
    expect(screen.getByText('800자 · 표 통째 · 그림 캡션')).toBeTruthy();
    expect(within(board()).getAllByRole('columnheader').map(h => h.textContent!.replace(/\d+$/, ''))).toEqual(['모델', '본문 질문', '표 질문', '그림 질문', '전체', '입력 한도 초과 청크', '벡터 용량', '지연']);
  });

  it('머리글·모델 이름·구성 버튼에는 말풍선이 없다', async () => {
    mockApi();
    render(<EmbeddingEval active />);
    await screen.findByRole('button', { name: /Harrier-OSS-v1 0\.6B · 표 · Hit@5/ });
    const hover = (el: HTMLElement) => { fireEvent.mouseEnter(el); fireEvent.focus(el); expect(screen.queryByRole('tooltip')).toBeNull(); expect(el.getAttribute('title')).toBeNull(); };
    within(board()).getAllByRole('columnheader').forEach(hover);
    within(board()).getAllByRole('rowheader').forEach(hover);
    [/^문서/, /^질문/, /^모델/, /평가 실행/].forEach(name => hover(screen.getByRole('button', { name })));
    hover(screen.getByRole('combobox', { name: '청킹' }));
  });

  it('실행 전에도 계획으로 입력 한도 초과·벡터 용량을 채우고 정확도는 비워 둔다', async () => {
    const fetchMock = mockApi({ runs: [null] });
    render(<EmbeddingEval active />);
    await waitFor(() => expect(cells(rowOf('multilingual-e5-large'))[4]).toBe('7'));
    const body = JSON.parse(String((planCalls(fetchMock)[0][1] as RequestInit).body));
    expect(body.preset.id).toBe('p-el');
    expect(body.models).toEqual(MODELS);
    expect(body.doc_ids).toEqual(['sample:sop', 'sample:spec', 'sample:deck']);
    expect(cells(rowOf('Harrier-OSS-v1 0.6B'))).toEqual(['—', '—', '—', '—', '0', '124 KB', '—']);
    expect(screen.queryByRole('button', { name: /Hit@5/ })).toBeNull();
    expect(screen.getByRole('columnheader', { name: /표 질문/ }).textContent).toBe('표 질문2');
    expect(screen.getByRole('button', { name: /^질문/ }).textContent).toBe('질문4');
    expect(screen.getByRole('button', { name: /^문서/ }).textContent).toBe('문서예시 3');
    expect(screen.getByRole('button', { name: /^모델/ }).textContent).toBe('모델5');
    expect(screen.getByText('청크 31개 · 중앙값 210토큰 · 가장 긴 청크 1,240토큰')).toBeTruthy();
  });

  it('청킹을 바꾸면 계획을 다시 묻고 이전 요청은 끊는다', async () => {
    const fetchMock = mockApi({ runs: [null], planDelay: 80 });
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await waitFor(() => expect(planCalls(fetchMock)).toHaveLength(1));
    await user.selectOptions(screen.getByRole('combobox', { name: '청킹' }), 'p-fx');
    expect(((planCalls(fetchMock)[0][1] as RequestInit).signal as AbortSignal).aborted).toBe(true);
    expect(screen.getByText('500자 · 겹침 50자')).toBeTruthy();
    await waitFor(() => expect(planCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((planCalls(fetchMock)[1][1] as RequestInit).body)).preset.id).toBe('p-fx');
  });

  it('지표와 기준을 바꾸면 모든 정확도 칸이 바뀌고 열마다 가장 높은 값이 굵다', async () => {
    mockApi();
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    const top = await screen.findByRole('button', { name: 'Harrier-OSS-v1 0.6B · 표 · Hit@5 100%' });
    expect(top.className).toContain('is-best');
    expect(screen.getByRole('button', { name: 'Qwen3-Embedding 0.6B · 표 · Hit@5 50%' }).className).not.toContain('is-best');
    expect(within(rowOf('Granite Embedding 278M')).getByText(/평가하지 못했습니다 · 게이트웨이가 응답하지 않습니다/)).toBeTruthy();
    await user.click(screen.getByRole('radio', { name: 'MRR@10' }));
    expect(screen.getByRole('button', { name: 'Qwen3-Embedding 0.6B · 표 · MRR@10 0.62' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Qwen3-Embedding 0.6B · 전체 · MRR@10 0.60' })).toBeTruthy();
    await user.click(screen.getByRole('radio', { name: '정답 구절' }));
    expect(screen.getByRole('button', { name: 'Qwen3-Embedding 0.6B · 표 · MRR@10 0.25' })).toBeTruthy();
    expect(within(rowOf('Qwen3-Embedding 0.6B')).getByText('구절 없음')).toBeTruthy();
    expect(cells(rowOf('Qwen3-Embedding 0.6B'))[6]).toBe('38 ms');
  });

  it('칸 말풍선은 칸에 없는 지표·질문 수·실패만 보여 준다', async () => {
    mockApi();
    render(<EmbeddingEval active />);
    fireEvent.mouseEnter(await screen.findByRole('button', { name: 'multilingual-e5-large · 표 · Hit@5 50%' }));
    const tip = screen.getByRole('tooltip');
    for (const label of ['Hit@1', 'Hit@3', 'Hit@10', 'MRR@10', 'nDCG@10']) expect(within(tip).getByText(label)).toBeTruthy();
    expect(within(tip).queryByText('Hit@5')).toBeNull();
    expect(tip.textContent).toContain('질문 2개');
    expect(tip.textContent).toContain('한도 초과로 실패 2건');
    expect(tip.textContent).not.toContain('multilingual-e5-large');
  });

  it('칸을 누르면 모델 · 질문 유형 팝업이 열리고, 질문을 고르면 검색된 청크를 보여 주며, Escape로 닫으면 칸으로 초점이 돌아온다', async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    const cell = await screen.findByRole('button', { name: 'Qwen3-Embedding 0.6B · 표 · Hit@5 50%' });
    await user.click(cell);
    const dialog = screen.getByRole('dialog', { name: 'Qwen3-Embedding 0.6B · 표 질문' });
    expect(dialog.className).toContain('is-xl');
    expect(dialog.textContent).toContain('Hit@5 50% · 정답 문서 기준');
    const list = within(dialog).getByRole('listbox', { name: '질문 목록' });
    expect(within(list).getAllByRole('option').map(o => o.textContent)).toEqual(['3위보관 온도 범위는?', '1위시험 주기는?']);
    await user.click(within(dialog).getByRole('radio', { name: /놓친 질문/ }));
    expect(within(dialog).getByText('놓친 질문이 없습니다.')).toBeTruthy();
    await user.click(within(dialog).getByRole('radio', { name: /전체/ }));
    const hits = await within(dialog).findByRole('list', { name: '검색된 청크' });
    expect(within(dialog).getByText('2~8도')).toBeTruthy();
    expect(within(hits).getAllByText('정답 구절')).toHaveLength(1);
    expect(within(hits).getAllByText('정답 문서')).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/runs/current/questions/1?combo=c2%3A%3Ap-el'))).toBe(true);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(cell);
  });

  it('Hit@1에서는 2위 이하도 놓친 질문으로 센다', async () => {
    mockApi();
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await user.click(await screen.findByRole('radio', { name: 'Hit@1' }));
    await user.click(screen.getByRole('button', { name: 'Qwen3-Embedding 0.6B · 표 · Hit@1 50%' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('radio', { name: /놓친 질문/ }));
    expect(within(within(dialog).getByRole('listbox')).getAllByRole('option').map(o => o.textContent)).toEqual(['3위보관 온도 범위는?']);
  });

  it('임베딩 연결이 없으면 실행을 막고 이유는 한 번만 보이며, 표는 모델·계획 열을 그대로 보여 준다', async () => {
    mockApi({ configured: false, runs: [null] });
    render(<EmbeddingEval active />);
    await waitFor(() => expect(screen.getAllByText('임베딩 연결이 없습니다')).toHaveLength(1));
    const button = screen.getByRole('button', { name: /평가 실행/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBeNull();
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(within(board()).getAllByRole('rowheader')).toHaveLength(5);
    await waitFor(() => expect(cells(rowOf('Granite Embedding 278M'))[4]).toBe('7'));
    expect(cells(rowOf('Granite Embedding 278M')).slice(0, 4)).toEqual(['—', '—', '—', '—']);
  });

  it('모델 팝업에서 모델을 더하고 빼며, Escape로 닫으면 모델 버튼으로 초점이 돌아온다', async () => {
    mockApi({ runs: [null] });
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await screen.findByText('Harrier-OSS-v1 0.6B');
    const opener = screen.getByRole('button', { name: /^모델/ });
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: '모델' });
    expect(within(within(dialog).getByRole('listbox', { name: '비교할 모델' })).getAllByRole('option')).toHaveLength(5);
    await user.click(within(dialog).getByRole('button', { name: /Slate 125M/ }));
    expect(within(board()).getAllByRole('rowheader')).toHaveLength(6);
    expect((within(dialog).getByRole('combobox', { name: '모델 ID' }) as HTMLInputElement).value).toBe('ibm/slate-125m-english-rtrvr');
    await user.click(within(dialog).getByRole('option', { name: /BGE-M3/ }));
    await user.click(within(dialog).getByRole('button', { name: 'BGE-M3 빼기' }));
    expect(within(board()).queryByText('BGE-M3')).toBeNull();
    await user.click(within(dialog).getByRole('option', { name: /multilingual-e5-large/ }));
    expect((within(dialog).getByRole('textbox', { name: '질의 접두어' }) as HTMLInputElement).value).toBe('');
    await user.clear(within(dialog).getByRole('textbox', { name: '질의 접두어' }));
    await user.type(within(dialog).getByRole('textbox', { name: '질의 접두어' }), 'query: ');
    await user.click(within(dialog).getByRole('button', { name: '기본 모델로 되돌리기' }));
    expect(within(board()).getAllByRole('rowheader')).toHaveLength(5);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('문서 팝업은 예시·실제 문서를 체크 목록으로 보여 주고, 고르면 버튼과 계획 요청이 바뀐다', async () => {
    const fetchMock = mockApi({ runs: [null] });
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await waitFor(() => expect(planCalls(fetchMock)).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: /^문서/ }));
    const dialog = screen.getByRole('dialog', { name: '문서' });
    expect(within(dialog).getByRole('region', { name: '예시 문서' })).toBeTruthy();
    await user.click(within(dialog).getByRole('checkbox', { name: /합성 발표 자료/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: /합성 절차서 A\.md/ }));
    await user.click(within(dialog).getByRole('button', { name: '완료' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: /^문서/ }).textContent).toBe('문서예시 2 · 실제 1');
    await waitFor(() => expect(planCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String((planCalls(fetchMock)[1][1] as RequestInit).body)).doc_ids).toEqual(['sample:sop', 'sample:spec', DOC_A]);
  });

  it('질문 팝업은 목록 + 편집이고, 예시 질문을 더해도 저장 전에는 서버에 쓰지 않는다', async () => {
    const fetchMock = mockApi({ runs: [null] });
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await screen.findByText('Harrier-OSS-v1 0.6B');
    await user.click(screen.getByRole('button', { name: /^질문/ }));
    const dialog = screen.getByRole('dialog', { name: '질문' });
    expect(dialog.className).toContain('is-xl');
    const list = within(dialog).getByRole('listbox', { name: '질문 목록' });
    expect(within(list).getAllByRole('option')).toHaveLength(4);
    await user.click(within(list).getByRole('option', { name: /보관 온도 범위는/ }));
    expect((within(dialog).getByRole('textbox', { name: '질문' }) as HTMLTextAreaElement).value).toBe('보관 온도 범위는?');
    expect(within(dialog).getByRole('radio', { name: '표' }).getAttribute('aria-checked')).toBe('true');
    await user.click(within(dialog).getByRole('radio', { name: /^표 2/ }));
    expect(within(list).getAllByRole('option')).toHaveLength(2);
    await user.click(within(dialog).getByRole('button', { name: '예시 질문 불러오기' }));
    await user.click(await within(dialog).findByRole('button', { name: '기존에 추가' }));
    expect(within(list).getAllByRole('option')).toHaveLength(8);
    expect(within(dialog).getByText('저장하지 않은 변경이 있습니다.')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')).toBe(false);
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: /^질문/ }));
    expect(within(screen.getByRole('listbox', { name: '질문 목록' })).getAllByRole('option')).toHaveLength(8);
    await user.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByText('8개 저장했습니다.')).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')).toHaveLength(1);
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: /^질문/ }).textContent).toBe('질문8');
  });

  it('다른 청킹의 결과는 칸에 채우지 않고 그 청킹으로 돌아가는 길만 준다', async () => {
    mockApi();
    const user = userEvent.setup();
    render(<EmbeddingEval active />);
    await screen.findByRole('button', { name: /Harrier-OSS-v1 0\.6B · 표 · Hit@5/ });
    await user.selectOptions(screen.getByRole('combobox', { name: '청킹' }), 'p-fx');
    expect(screen.queryByRole('button', { name: /· Hit@5/ })).toBeNull();
    await user.click(screen.getByRole('button', { name: '그 청킹으로 보기' }));
    expect(screen.getByRole('button', { name: /Harrier-OSS-v1 0\.6B · 표 · Hit@5/ })).toBeTruthy();
  });

  it('실행 중이면 진행 상태를 다시 물어 끝나면 멈춘다', async () => {
    const fetchMock = mockApi({ runs: [run('running', []), run()] });
    render(<EmbeddingEval active />);
    expect(await screen.findByText(/BGE-M3 청크 임베딩/)).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('3 / 10');
    expect(screen.getByRole('button', { name: /취소/ })).toBeTruthy();
    await screen.findByRole('button', { name: /Harrier-OSS-v1 0\.6B · 표 · Hit@5/ }, { timeout: 4000 });
    const count = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/runs/current')).length;
    const polls = count();
    await new Promise(resolve => setTimeout(resolve, 1700));
    expect(count()).toBe(polls);
  });

  it('화면이 비활성이 되거나 사라지면 폴링을 멈춘다', async () => {
    const fetchMock = mockApi({ runs: [run('running', [])] });
    const { rerender, unmount } = render(<EmbeddingEval active />);
    await screen.findByText(/BGE-M3 청크 임베딩/);
    rerender(<EmbeddingEval active={false} />);
    const count = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/runs/current')).length;
    const polls = count();
    await new Promise(resolve => setTimeout(resolve, 1700));
    expect(count()).toBe(polls);
    rerender(<EmbeddingEval active />);
    await waitFor(() => expect(count()).toBeGreaterThan(polls), { timeout: 2500 });
    unmount();
    const after = count();
    await new Promise(resolve => setTimeout(resolve, 1700));
    expect(count()).toBe(after);
  });
});
