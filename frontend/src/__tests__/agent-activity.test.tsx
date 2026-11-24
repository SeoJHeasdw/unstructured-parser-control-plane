import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import AgentActivity from '../AgentActivity';

/* 합성 기록만 쓴다. 목록은 서버와 같이 최신이 먼저다. */
const base = { size_bytes: 10, created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z', parser: null, error: null };
const docs = [
  { ...base, id: 'doc-a', name: '점검표.pdf', format: 'PDF', status: 'uploaded', seq: 12 },
  { ...base, id: 'doc-b', name: '손상.xlsx', format: 'XLSX', status: 'failed', error_code: 'parse_failed', seq: 13 },
];
const reportR3 = 'DOCOPS R3 today 11-24 13:42 build fa3d7b\nsum 2 ok1 fail1\nfail parse-err1 D13';
const reportB5 = 'DOCOPS B5 11-24 13:40 build fa3d7b\nsum 3 ok2 fail1';
const activity = {
  available: true,
  batches: [
    { n: 5, target: 'C:/docs/*.pdf', reparse: false, started: '2026-11-24T04:40:00Z', finished: '2026-11-24T04:43:12Z', error: '', total: 4,
      counts: { done: 3, error: 1 }, docs: [12, 13, 99], skips: { 'ext-hwp': 3, lock: 1 }, errors: ['missing'] },
    { n: 4, target: 'D12', reparse: true, started: '2026-11-24T04:00:00Z', finished: null, error: '', total: 2, counts: { done: 1, queued: 1 }, docs: [12], skips: {}, errors: [] },
  ],
  reports: [{ name: 'R3', modified: '2026-11-24T04:44:00Z', text: reportR3 }, { name: 'B5', modified: '2026-11-24T04:43:12Z', text: reportB5 }],
  calls: [
    { ts: '2026-11-24T04:44:00Z', tool: 'report', args: { scope: 'today' }, kind: null, repeat: false, ms: 41, result: '결과: 보고서 R3' },
    { ts: '2026-11-24T04:42:00Z', tool: 'doc', args: { id: 'D77' }, kind: 'not-found', repeat: true, ms: 3, result: '결과: 실패 (not-found)' },
    { ts: '2026-11-24T04:40:00Z', tool: 'parse', args: { target: 'C:/docs/*.pdf', reparse: false }, kind: null, repeat: false, ms: 1204, result: '결과: 묶음 B5 등록' },
  ],
};
const ACTIVITY = '/api/agent/activity?limit=200';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function serve(body: unknown = activity, status = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method && init.method !== 'GET') throw new Error('읽기 전용 화면에서 변경 요청 ' + path);
    if (path === ACTIVITY) return json(body, status);
    if (path === '/api/live/documents') return json({ documents: docs });
    const doc = docs.find(item => path === `/api/live/documents/${item.id}`);
    if (doc) return json(doc);
    if (path.endsWith('/result')) return json({ detail: '완료된 파싱 결과가 없습니다.' }, 409);
    return json({ detail: '없음' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const activityCalls = (mock: ReturnType<typeof serve>) => mock.mock.calls.filter(([url]) => String(url) === ACTIVITY).length;

beforeEach(() => { history.replaceState(null, '', '/'); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); Reflect.deleteProperty(document, 'visibilityState'); });

describe('에이전트 작업 화면', () => {
  it('업무 메뉴에서 열고, 묶음의 D번호 칩으로 문서 상세에 간다', async () => {
    const user = userEvent.setup();
    const fetchMock = serve();
    render(<App />);
    await user.click(within(screen.getByRole('navigation', { name: '업무 메뉴' })).getByRole('link', { name: '에이전트 작업' }));
    expect(location.search).toBe('?view=agent');
    expect(screen.getByRole('heading', { level: 1, name: '에이전트 작업' })).toBeTruthy();
    const tabs = await screen.findByRole('tablist', { name: '에이전트 기록' });
    expect(within(tabs).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['묶음2', '보고서2', '호출 기록3']);
    const batch = screen.getByRole('listitem', { name: '묶음 B5' });
    expect(within(batch).getByText('C:/docs/*.pdf')).toBeTruthy();
    expect(within(batch).getByText('3/4')).toBeTruthy();
    expect(within(batch).getByText('끝남 · 오류 있음')).toBeTruthy();
    expect(within(batch).getByText('ext-hwp 3')).toBeTruthy();
    expect(within(batch).getByText('lock 1')).toBeTruthy();
    expect(within(batch).getByText('missing')).toBeTruthy();
    expect(within(batch).getByText('D99').tagName).toBe('SPAN');
    expect(within(batch).getByRole('link', { name: 'D13 손상.xlsx' }).className).toContain('is-failed');
    const running = screen.getByRole('listitem', { name: '묶음 B4' });
    expect(within(running).getByText('진행 중')).toBeTruthy();
    expect(within(running).getByText('다시 파싱')).toBeTruthy();
    await user.click(within(batch).getByRole('link', { name: 'D12 점검표.pdf' }));
    expect(location.search).toBe('?view=live&doc=doc-a');
    expect(await screen.findByRole('heading', { level: 1, name: '점검표.pdf' })).toBeTruthy();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  });

  it('보고서를 골라 고정폭 본문으로 읽고 복사한다', async () => {
    const user = userEvent.setup();
    serve();
    render(<AgentActivity onNavigate={vi.fn()} />);
    await user.click(await screen.findByRole('tab', { name: /보고서/ }));
    const list = screen.getByRole('listbox', { name: '보고서 목록' });
    expect(within(list).getAllByRole('option').map(option => option.querySelector('code')?.textContent)).toEqual(['R3', 'B5']);
    expect(screen.getByLabelText('R3 본문').textContent).toBe(reportR3);
    expect(within(screen.getByRole('group', { name: 'R3에 나온 문서' })).getByRole('link', { name: 'D13 손상.xlsx' })).toBeTruthy();
    await user.click(within(list).getByText('B5'));
    const body = screen.getByLabelText('B5 본문');
    expect(body.tagName).toBe('PRE');
    expect(body.textContent).toBe(reportB5);
    await user.click(screen.getByRole('button', { name: '복사' }));
    expect(await screen.findByText('보고서를 복사했습니다.')).toBeTruthy();
    expect(await navigator.clipboard.readText()).toBe(reportB5);
  });

  it('클립보드를 쓸 수 없으면 본문을 선택해 두고 직접 복사하도록 안내한다', async () => {
    const user = userEvent.setup();
    serve();
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    try {
      render(<AgentActivity onNavigate={vi.fn()} />);
      await user.click(await screen.findByRole('tab', { name: /보고서/ }));
      await user.click(screen.getByRole('button', { name: '복사' }));
      expect(await screen.findByText(/자동 복사를 쓸 수 없어 본문을 선택해 두었습니다/)).toBeTruthy();
      expect(window.getSelection()?.toString()).toBe(reportR3);
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original); else Reflect.deleteProperty(navigator, 'clipboard');
    }
  });

  it('호출 기록을 표로 보이고 오류만 걸러 본다', async () => {
    const user = userEvent.setup();
    serve();
    render(<AgentActivity onNavigate={vi.fn()} />);
    await user.click(await screen.findByRole('tab', { name: /호출 기록/ }));
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(within(table).getByText('target=C:/docs/*.pdf reparse=false')).toBeTruthy();
    expect(within(table).getByText('1,204')).toBeTruthy();
    expect(within(table).getByText('not-found')).toBeTruthy();
    expect(within(table).getByText('반복')).toBeTruthy();
    const toggle = screen.getByRole('button', { name: /오류만/ });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    await user.click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(rows[1].textContent).toContain('id=D77');
    expect(screen.getByText('표시 설명')).toBeTruthy();
  });

  it('에이전트가 실행된 적이 없으면 안내만 보인다', async () => {
    serve({ available: false, batches: [], reports: [], calls: [] });
    render(<AgentActivity onNavigate={vi.fn()} />);
    expect(await screen.findByText('작업 에이전트가 아직 실행되지 않았습니다')).toBeTruthy();
    expect(screen.getByText('docs/AGENT_TOOLS.md')).toBeTruthy();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('조회 실패는 화면 안에 보이고 메뉴는 그대로 쓸 수 있으며, 다시 시도하면 기록을 보인다', async () => {
    const user = userEvent.setup();
    let fail = true;
    const fetchMock = serve();
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => String(input) === ACTIVITY
      ? (fail ? json({ detail: '기록 파일을 읽지 못했습니다.' }, 500) : json(activity))
      : json({ documents: docs }));
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
