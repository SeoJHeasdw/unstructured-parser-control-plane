import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import AgentActivity from '../AgentActivity';

/* 합성 기록만 쓴다. 목록은 서버와 같이 최신이 먼저다. */
const RUN = 'a'.repeat(32);
const base = { size_bytes: 10, created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z', parser: null, error: null };
const docs = [
  { ...base, id: 'doc-a', name: '점검표.pdf', format: 'PDF', status: 'completed', seq: 12 },
  { ...base, id: 'doc-b', name: '손상.xlsx', format: 'XLSX', status: 'failed', error_code: 'parse_failed', seq: 13 },
];
const review = (over: Record<string, unknown>) => ({
  id: 1, document_id: 'doc-a', document_seq: 12, document_name: '점검표.pdf', document_format: 'PDF', document_status: 'completed',
  run_id: RUN, is_latest_run: true, created_at: '2026-11-24T04:45:00Z', updated_at: '2026-11-24T04:45:00Z', decided_at: null,
  origin: 'agent', spot: 'S1', kind: 'changed', severity: 'high', page: 3, sheet: null, cell: null, line: 120, line_end: 120, ref: '3쪽 2줄',
  note: '원본 0.5 mL가 결과에서 05 mL로 보임', source_text: '검체 0.5 mL를 취한다', source_hit: '0.5', result_text: '검체 05 mL를 취한다', result_hit: '05',
  status: 'open', comment: null, batch: 5, ...over,
});
const reviews = [
  review({ id: 2 }),
  review({ id: 1, document_id: 'doc-b', document_seq: 13, document_name: '손상.xlsx', document_format: 'XLSX', document_status: 'failed', page: null,
    sheet: '요약', cell: 'B5', line: 9, line_end: 9, kind: 'cell_missing', note: 'B5 값이 결과에 없음', source_hit: '98.5', result_hit: '', status: 'wrong', comment: '행 밀림', origin: 'console' }),
];
const activity = {
  available: true,
  batches: [
    { n: 5, target: 'C:/docs/*.pdf', reparse: false, started: '2026-11-24T04:40:00Z', finished: '2026-11-24T04:43:12Z', error: '', total: 4,
      counts: { done: 3, error: 1 }, docs: [12, 13, 99], skips: { 'ext-hwp': 3, lock: 1 }, errors: ['missing'] },
    { n: 4, target: 'D12', reparse: true, started: '2026-11-24T04:00:00Z', finished: null, error: '', total: 2, counts: { done: 1, queued: 1 }, docs: [12], skips: {}, errors: [] },
  ],
  documents: [
    { id: 'doc-a', seq: 12, name: '점검표.pdf', format: 'PDF', status: 'completed', error_code: null, updated_at: base.updated_at, last_agent_at: '2026-11-24T04:45:00Z',
      batches: [5, 4], calls: 3, reviews: { open: 1, correct: 0, wrong: 0, unclear: 0 } },
    { id: 'doc-b', seq: 13, name: '손상.xlsx', format: 'XLSX', status: 'failed', error_code: 'parse_failed', updated_at: base.updated_at, last_agent_at: '2026-11-24T04:43:12Z',
      batches: [5], calls: 0, reviews: { open: 0, correct: 0, wrong: 1, unclear: 0 } },
  ],
  calls: [
    { ts: '2026-11-24T04:45:00Z', tool: 'flag', args: { id: 'D12', spot: 'S1' }, kind: null, repeat: false, ms: 18, result: '결과: 검수 요청을 올렸습니다 — V2 · D12 3쪽 결과 줄 120',
      text: '결과: 검수 요청을 올렸습니다 — V2 · D12 3쪽 결과 줄 120\n확인할 것: 원본 0.5 mL가 결과에서 05 mL로 보임', docs: [12], session: 'c0ffee01' },
    { ts: '2026-11-24T04:44:00Z', tool: 'verify', args: { id: 'D12', page: 3 }, kind: null, repeat: false, ms: 41, result: '결과: D12 원본 대조 — 의심 1곳', text: '결과: D12 원본 대조 — 의심 1곳\nS1 [높음] 3쪽 2줄', docs: [12], session: 'c0ffee01' },
    { ts: '2026-11-24T04:42:00Z', tool: 'doc', args: { id: 'D77' }, kind: 'not-found', repeat: true, ms: 3, result: '결과: 실패 (not-found)', text: '결과: 실패 (not-found)\n원인: D77 문서가 없습니다.', docs: [], session: 'beefcafe' },
    { ts: '2026-11-24T04:40:00Z', tool: 'parse', args: { target: 'C:/docs/*.pdf', reparse: false }, kind: null, repeat: false, ms: 1204, result: '결과: B5 끝 — 4건', text: '', docs: [], session: null },
  ],
};
const ACTIVITY = '/api/agent/activity?limit=200';
const REVIEWS = '/api/live/reviews?limit=500';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const counts = (items: { status: string }[]) => items.reduce<Record<string, number>>((all, item) => ({ ...all, [item.status]: (all[item.status] ?? 0) + 1 }), {});

function serve(body: unknown = activity, status = 200) {
  let stored = reviews.map(item => ({ ...item }));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'PATCH' && path.startsWith('/api/live/reviews/')) {
      const id = Number(path.split('/').pop());
      stored = stored.map(item => item.id === id ? { ...item, ...JSON.parse(String(init?.body)), decided_at: '2026-11-24T05:00:00Z' } : item);
      return json(stored.find(item => item.id === id));
    }
    if (method !== 'GET') throw new Error('예상하지 못한 변경 요청 ' + method + ' ' + path);
    if (path === ACTIVITY) return json(body, status);
    if (path === REVIEWS) return json({ reviews: stored, counts: counts(stored) });
    if (path.startsWith('/api/live/reviews?doc=doc-a')) return json({ reviews: stored.filter(item => item.document_id === 'doc-a'), counts: {} });
    if (path === '/api/live/documents') return json({ documents: docs });
    const doc = docs.find(item => path === `/api/live/documents/${item.id}`);
    if (doc) return json(doc);
    if (path === '/api/live/documents/doc-a/runs') return json({ runs: [{ run_id: RUN, completed_at: '2026-11-24T04:41:00Z', parser: 'docling', parser_version: '2.150.0', ocr_enabled: false, is_latest: true }] });
    if (path === `/api/live/documents/doc-a/runs/${RUN}`) return json({ run_id: RUN, completed_at: '2026-11-24T04:41:00Z', parser: 'docling', parser_version: '2.150.0',
      ocr_enabled: false, is_latest: true, markdown: Array.from({ length: 130 }, (_, i) => `줄 ${i + 1}`).join('\n'), warnings: [], locations: [] });
    if (path.startsWith('/api/live/documents/doc-a/verify')) return json({ detail: '자동 대조 없음' }, 409);
    if (path.endsWith('/result')) return json({ detail: '완료된 파싱 결과가 없습니다.' }, 409);
    return json({ detail: '없음' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const activityCalls = (mock: ReturnType<typeof serve>) => mock.mock.calls.filter(([url]) => String(url) === ACTIVITY).length;

beforeEach(() => { history.replaceState(null, '', '/'); localStorage.clear(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); Reflect.deleteProperty(document, 'visibilityState'); });

describe('에이전트 작업 화면', () => {
  it('업무 메뉴에서 열면 검수 요청이 먼저 보이고, 원문 대조 링크는 그 위치와 V번호를 연다', async () => {
    const user = userEvent.setup();
    serve();
    render(<App />);
    await user.click(within(screen.getByRole('navigation', { name: '업무 메뉴' })).getByRole('link', { name: '에이전트 작업' }));
    expect(location.search).toBe('?view=agent');
    const tabs = await screen.findByRole('tablist', { name: '에이전트 기록' });
    expect(within(tabs).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['검수 요청확인 전 1', '문서2', '묶음2', '호출 기록4']);
    expect(within(tabs).getByRole('tab', { name: /검수 요청/ }).getAttribute('aria-selected')).toBe('true');
    const open = screen.getByRole('listitem', { name: '검수 요청 V2' });
    expect(within(open).getByText('원본 0.5 mL가 결과에서 05 mL로 보임')).toBeTruthy();
    expect(within(open).getByText('3쪽 · 결과 줄 120')).toBeTruthy();
    expect(screen.queryByRole('listitem', { name: '검수 요청 V1' })).toBeNull(); // 처음에는 확인 전만
    const link = within(open).getByRole('link', { name: /원문 대조에서 보기/ });
    const href = new URL(link.getAttribute('href')!, location.origin);
    expect(Object.fromEntries(href.searchParams)).toEqual({ view: 'live', doc: 'doc-a', review: 'source', page: '3', line: '120', check: 'V2', run: RUN });
    await user.click(link);
    expect(location.search).toContain('review=source');
    expect(await screen.findByRole('heading', { level: 1, name: /점검표\.pdf/ })).toBeTruthy();
    const bar = await screen.findByRole('region', { name: '확인할 곳' });
    expect(await within(bar).findByText('원본 0.5 mL가 결과에서 05 mL로 보임')).toBeTruthy();
    expect(within(bar).getByText('V2')).toBeTruthy();
    await waitFor(() => expect(document.querySelector('.source-line.is-evidence')?.textContent).toContain('줄 120'));
    expect(document.querySelector<HTMLIFrameElement>('iframe[title="PDF 원문"]')?.getAttribute('src')).toContain('#page=3');
  });

  it('판정 단추로 상태를 바꾸고, 틀림으로 판정한 곳을 글로 복사한다', async () => {
    const user = userEvent.setup();
    const fetchMock = serve();
    render(<AgentActivity onNavigate={vi.fn()} />);
    const open = await screen.findByRole('listitem', { name: '검수 요청 V2' });
    await user.click(within(open).getByRole('button', { name: '틀림' }));
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(String(patch?.[0])).toBe('/api/live/reviews/2');
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ status: 'wrong' });
    expect(await screen.findByText('확인 전인 검수 요청이 없습니다.')).toBeTruthy();
    await user.click(within(screen.getByRole('group', { name: '검수 요청 상태' })).getByRole('button', { name: /^틀림/ }));
    expect(screen.getAllByRole('listitem', { name: /검수 요청 V/ })).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: '틀림 정리 복사' }));
    expect(await screen.findByText('틀림으로 판정한 곳을 복사했습니다.')).toBeTruthy();
    const text = await navigator.clipboard.readText();
    expect(text).toMatch(/^파싱 오류\(사람이 원문 대조로 확인\) 2건/);
    expect(text).toContain("V2 D12 PDF · 3쪽 · 결과 줄 120 · changed · 원본 '0.5' → 결과 '05'");
    expect(text).toContain("V1 D13 XLSX · 요약!B5 · 결과 줄 9 · cell_missing · 원본 '98.5' → 결과 없음");
    expect(text).toContain('메모: 행 밀림');
  });

  it('클립보드를 쓸 수 없으면 정리 글을 선택해 두고 직접 복사하도록 안내한다', async () => {
    const user = userEvent.setup();
    serve();
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    try {
      render(<AgentActivity onNavigate={vi.fn()} />);
      await screen.findByRole('listitem', { name: '검수 요청 V2' });
      await user.click(screen.getByRole('button', { name: '틀림 정리 복사' }));
      expect(await screen.findByText(/자동 복사를 쓸 수 없어 정리 글을 선택해 두었습니다/)).toBeTruthy();
      expect(window.getSelection()?.toString()).toContain('V1 D13');
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original); else Reflect.deleteProperty(navigator, 'clipboard');
    }
  });

  it('문서 탭은 에이전트가 다룬 문서와 검수 요청 수를 보이고, 파싱된 문서는 원문 대조로 연다', async () => {
    const user = userEvent.setup();
    serve();
    const onNavigate = vi.fn();
    render(<AgentActivity onNavigate={onNavigate} />);
    await user.click(await screen.findByRole('tab', { name: /^문서/ }));
    const table = screen.getByRole('region', { name: '에이전트가 다룬 문서' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map(row => row.querySelector('.ag-doc-name')?.textContent)).toEqual(['D12 점검표.pdf', 'D13 손상.xlsx']);
    expect(within(rows[0]).getByText('확인 전 1')).toBeTruthy();
    expect(within(rows[1]).getByText('틀림 1')).toBeTruthy();
    expect(within(rows[0]).getByText('B5')).toBeTruthy();
    expect(within(rows[1]).queryByRole('link', { name: /원문 대조/ })).toBeNull(); // 실패한 문서는 대조할 결과가 없다
    await user.click(within(rows[0]).getByRole('link', { name: 'D12 점검표.pdf 원문 대조' }));
    expect(onNavigate).toHaveBeenCalledWith({ page: 'live', doc: 'doc-a', review: 'source', focus: undefined });
  });

  it('묶음 탭은 B번호·건너뜀·오류와 D번호 칩을 보이고, 칩은 문서 상세로 간다', async () => {
    const user = userEvent.setup();
    serve();
    const onNavigate = vi.fn();
    render(<AgentActivity onNavigate={onNavigate} />);
    await user.click(await screen.findByRole('tab', { name: /묶음/ }));
    const batch = screen.getByRole('listitem', { name: '묶음 B5' });
    expect(within(batch).getByText('C:/docs/*.pdf')).toBeTruthy();
    expect(within(batch).getByText('3/4')).toBeTruthy();
    expect(within(batch).getByText('끝남 · 오류 있음')).toBeTruthy();
    expect(within(batch).getByText('ext-hwp 3')).toBeTruthy();
    expect(within(batch).getByText('missing')).toBeTruthy();
    expect(within(batch).getByText('D99').tagName).toBe('SPAN');
    expect(within(batch).getByRole('link', { name: 'D13 손상.xlsx' }).className).toContain('is-failed');
    expect(within(screen.getByRole('listitem', { name: '묶음 B4' })).getByText('진행 중')).toBeTruthy();
    await user.click(within(batch).getByRole('link', { name: 'D12 점검표.pdf' }));
    expect(onNavigate).toHaveBeenCalledWith({ page: 'live', doc: 'doc-a' });
  });

  it('호출 기록은 연결별로 묶고, 펼치면 에이전트가 받은 결과 전체를 보이며, 오류만 걸러 본다', async () => {
    const user = userEvent.setup();
    serve();
    const onNavigate = vi.fn();
    render(<AgentActivity onNavigate={onNavigate} />);
    await user.click(await screen.findByRole('tab', { name: /호출 기록/ }));
    const table = screen.getByRole('table');
    const groups = Array.from(table.querySelectorAll('tr.ag-group')).map(row => row.textContent);
    expect(groups).toHaveLength(1); // 호출이 1건뿐인 연결(CLI 한 번 등)은 머리줄을 달지 않는다
    expect(groups[0]).toContain('연결 c0ffee01');
    expect(groups[0]).toContain('호출 2');
    expect(table.querySelectorAll('tbody')).toHaveLength(3);
    expect(within(table).getByText('원본과 자동 대조')).toBeTruthy();
    expect(within(table).getByText('target=C:/docs/*.pdf reparse=false')).toBeTruthy();
    expect(within(table).getByText('1,204')).toBeTruthy();
    expect(within(table).getByText('반복')).toBeTruthy();
    // verify 호출의 D번호는 그 쪽을 짚어 원문 대조로 연다
    const verifyRow = within(table).getByText('원본과 자동 대조').closest('tr')!;
    await user.click(within(verifyRow).getByRole('link', { name: 'D12 점검표.pdf' }));
    expect(onNavigate).toHaveBeenCalledWith({ page: 'live', doc: 'doc-a', review: 'source', focus: { page: 3, sheet: undefined, line: undefined, check: undefined } });
    await user.click(within(verifyRow).getByRole('button', { name: '에이전트가 받은 결과 전체 보기' }));
    expect(screen.getByLabelText('verify 결과 전체').textContent).toBe('결과: D12 원본 대조 — 의심 1곳\nS1 [높음] 3쪽 2줄');
    const toggle = screen.getByRole('button', { name: /오류만/ });
    await user.click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    const rows = Array.from(screen.getByRole('table').querySelectorAll('tbody tr:not(.ag-group)'));
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('id=D77');
    expect(screen.getByText('표시 설명')).toBeTruthy();
  });

  it('에이전트가 실행된 적이 없고 검수 요청도 없으면 안내만 보인다', async () => {
    const fetchMock = serve({ available: false, batches: [], documents: [], calls: [] });
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => String(input) === ACTIVITY ? json({ available: false, batches: [], documents: [], calls: [] })
      : String(input) === REVIEWS ? json({ reviews: [], counts: {} }) : json({ documents: [] }));
    render(<AgentActivity onNavigate={vi.fn()} />);
    expect(await screen.findByText('작업 에이전트가 아직 실행되지 않았습니다')).toBeTruthy();
    expect(screen.getByText('docs/AGENT_TOOLS.md')).toBeTruthy();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('예전 서버(문서·검수 요청 없음)여도 묶음과 호출 기록을 보인다', async () => {
    const fetchMock = serve();
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => String(input) === ACTIVITY ? json({ ...activity, documents: undefined, reports: [] })
      : String(input) === REVIEWS ? json({ detail: 'Not Found' }, 404) : json({ documents: docs }));
    render(<AgentActivity onNavigate={vi.fn()} />);
    const tabs = await screen.findByRole('tablist', { name: '에이전트 기록' });
    expect(within(tabs).getByRole('tab', { name: /묶음/ }).getAttribute('aria-selected')).toBe('true');
    expect(within(tabs).getByRole('tab', { name: /^문서/ }).textContent).toBe('문서0');
  });

  it('조회 실패는 화면 안에 보이고 메뉴는 그대로 쓸 수 있으며, 다시 시도하면 기록을 보인다', async () => {
    const user = userEvent.setup();
    let fail = true;
    const fetchMock = serve();
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => String(input) === ACTIVITY
      ? (fail ? json({ detail: '기록 파일을 읽지 못했습니다.' }, 500) : json(activity))
      : String(input) === REVIEWS ? json({ reviews: [], counts: {} }) : json({ documents: docs }));
    history.replaceState(null, '', '?view=agent');
    render(<App />);
    expect((await screen.findByRole('alert')).textContent).toContain('기록 파일을 읽지 못했습니다.');
    expect(within(screen.getByRole('navigation', { name: '업무 메뉴' })).getByRole('link', { name: '문서함' })).toBeTruthy();
    fail = false;
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('tablist', { name: '에이전트 기록' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('화면이 보일 때만 10초마다 다시 읽고, 떠나면 멈춘다', async () => {
    vi.useFakeTimers();
    let visibility: DocumentVisibilityState = 'visible';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
    const fetchMock = serve();
    const { rerender, unmount } = render(<AgentActivity onNavigate={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(activityCalls(fetchMock)).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(activityCalls(fetchMock)).toBe(2);
    visibility = 'hidden';
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(activityCalls(fetchMock)).toBe(2);
    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(0); });
    expect(activityCalls(fetchMock)).toBe(3);
    rerender(<AgentActivity active={false} onNavigate={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(activityCalls(fetchMock)).toBe(3);
    rerender(<AgentActivity active onNavigate={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(activityCalls(fetchMock)).toBe(4);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(activityCalls(fetchMock)).toBe(4);
  });
});

describe('수동 새로고침', () => {
  it('새로고침 버튼으로 바로 다시 읽는다', async () => {
    const user = userEvent.setup();
    const fetchMock = serve();
    render(<AgentActivity onNavigate={vi.fn()} />);
    await screen.findByRole('tablist', { name: '에이전트 기록' });
    await waitFor(() => expect(screen.getByRole('button', { name: '새로고침' })).toHaveProperty('disabled', false));
    await user.click(screen.getByRole('button', { name: '새로고침' }));
    await waitFor(() => expect(activityCalls(fetchMock)).toBe(2));
  });
});
