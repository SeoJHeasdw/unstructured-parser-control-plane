import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';

/* 원문 대조(문서 상세의 결과 검수)와 셸. 합성 응답만 쓴다. */
const RUN = 'b'.repeat(32);
const doc = { id: 'doc-a', name: '교정 기준.pdf', format: 'PDF', size_bytes: 10, status: 'completed', seq: 7,
  created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z', parser: 'pdf-text', error: null };
const spot = (over: Record<string, unknown>) => ({ key: 'S1', severity: 'medium', kind: 'missing', message: '원본 1쪽 3줄의 글이 결과에 없습니다.', unit: 'p1', label: '1쪽',
  page: 1, sheet: null, cell: null, ref: '1쪽 3줄', line: 3, line_end: 3, source: '보관 온도 2~8℃', source_hit: '보관 온도 2~8℃', result: '줄 2', result_hit: '',
  result_role: 'before', ...over });
const verify = {
  id: doc.id, run_id: RUN, is_latest: true, method: 'PDF 글자 층(pypdfium2, 파서와 별개로 읽음)', format: 'PDF', parser: 'pdf-text',
  summary: { units: 2, checked: 2, source_chars: 100, matched_chars: 97, coverage: 0.97, spots: 2, high: 1, medium: 1, low: 0, scan_units: 0 },
  units: [], top: ['S2', 'S1'], notes: [], spots_total: 2,
  spots: [spot({}), spot({ key: 'S2', severity: 'high', kind: 'changed', message: "원본 '0.5'이(가) 결과에서 '05'(으)로 다릅니다.", unit: 'p2', label: '2쪽', page: 2,
    ref: '2쪽 1줄', line: 5, line_end: 5, source: '검체 0.5 mL', source_hit: '0.5', result: '검체 05 mL', result_hit: '05', result_role: 'same' })],
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function serve() {
  const saved: Record<string, unknown>[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'POST' && path === '/api/live/reviews') {
      const body = JSON.parse(String(init?.body));
      const review = { id: 7 + saved.length, document_id: doc.id, document_seq: 7, document_name: doc.name, document_format: 'PDF', document_status: 'completed',
        run_id: body.run_id, is_latest_run: true, created_at: '2026-11-26T00:00:00Z', updated_at: '2026-11-26T00:00:00Z', decided_at: null, origin: 'console',
        spot: body.spot, kind: 'missing', severity: 'medium', page: 1, sheet: null, cell: null, line: 3, line_end: 3, ref: '1쪽 3줄',
        note: '원본 1쪽 3줄의 글이 결과에 없습니다.', source_text: '보관 온도 2~8℃', source_hit: '보관 온도 2~8℃', result_text: '줄 2', result_hit: '',
        status: body.status, comment: body.comment ?? null, batch: null, created: true };
      saved.push(review);
      return json(review, 201);
    }
    if (method === 'PATCH' && path.startsWith('/api/live/reviews/')) {
      const review = saved.find(item => item.id === Number(path.split('/').pop()))!;
      Object.assign(review, JSON.parse(String(init?.body)));
      return json(review);
    }
    if (method !== 'GET') throw new Error(`예상하지 못한 요청 ${method} ${path}`);
    if (path === '/api/live/documents') return json({ documents: [doc] });
    if (path === `/api/live/documents/${doc.id}`) return json(doc);
    if (path === `/api/live/documents/${doc.id}/runs`) return json({ runs: [{ run_id: RUN, completed_at: '2026-11-24T01:00:00Z', parser: 'pdf-text', parser_version: 'pypdfium2 5', ocr_enabled: false, is_latest: true }] });
    if (path === `/api/live/documents/${doc.id}/runs/${RUN}`) return json({ run_id: RUN, completed_at: '2026-11-24T01:00:00Z', parser: 'pdf-text', parser_version: 'pypdfium2 5',
      ocr_enabled: false, is_latest: true, markdown: ['줄 1', '줄 2', '줄 3', '줄 4', '검체 05 mL', '줄 6'].join('\n'), warnings: [],
      locations: [{ start_line: 1, end_line: 3, page: 1 }, { start_line: 4, end_line: 6, page: 2 }] });
    if (path.startsWith(`/api/live/reviews?doc=${doc.id}`)) return json({ reviews: saved, counts: {} });
    if (path === `/api/live/documents/${doc.id}/verify?run=${RUN}`) return json(verify);
    if (path.endsWith('/result')) return json({ id: doc.id, markdown: '줄 1', parser: 'pdf-text', parser_version: '5', is_stale: false, warnings: [] });
    return json({ detail: '없음' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const iframePage = () => document.querySelector<HTMLIFrameElement>('iframe[title="PDF 원문"]')?.getAttribute('src')?.match(/#page=(\d+)/)?.[1];
const litLines = () => Array.from(document.querySelectorAll('.source-line.is-evidence')).map(line => line.querySelector('small')?.textContent);

beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/'); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('원문 대조', () => {
  it('주소의 위치·S번호로 열고 화면 폭·높이를 채우며, 확인할 곳을 넘기면 원본 쪽과 결과 줄이 따라간다', async () => {
    const user = userEvent.setup();
    serve();
    history.replaceState(null, '', `/?view=live&doc=${doc.id}&review=source&page=2&line=5&check=S2`);
    render(<App />);
    expect(await screen.findByRole('heading', { level: 1, name: /교정 기준\.pdf/ })).toBeTruthy();
    expect(document.querySelector('.shell-content')?.className).toContain('is-review');
    const bar = await screen.findByRole('region', { name: '확인할 곳' });
    expect(await within(bar).findByText("원본 '0.5'이(가) 결과에서 '05'(으)로 다릅니다.")).toBeTruthy();
    expect(within(bar).getByText('2쪽 · 결과 줄 5')).toBeTruthy();
    expect(within(bar).getByText('0.5').tagName).toBe('MARK');
    await waitFor(() => expect(litLines()).toEqual(['5']));
    expect(iframePage()).toBe('2');
    await user.click(within(bar).getByRole('button', { name: '다음 확인할 곳' }));
    expect(within(bar).getByText('원본 1쪽 3줄의 글이 결과에 없습니다.')).toBeTruthy();
    expect(within(bar).getByText('결과(있어야 할 자리 앞 줄)')).toBeTruthy();
    await waitFor(() => expect(iframePage()).toBe('1'));
    expect(litLines()).toEqual(['3']);
  });

  it('자동 대조 지점에 판정을 누르면 검수 요청(V번호)으로 남고, 할 일에서 빠지며 메모를 붙인다', async () => {
    const user = userEvent.setup();
    const fetchMock = serve();
    history.replaceState(null, '', `/?view=live&doc=${doc.id}&review=source&check=S1`);
    render(<App />);
    const bar = await screen.findByRole('region', { name: '확인할 곳' });
    await within(bar).findByText('원본 1쪽 3줄의 글이 결과에 없습니다.');
    expect(within(bar).getByText('할 일 2')).toBeTruthy();
    await user.click(within(within(bar).getByRole('group', { name: 'S1 판정' })).getByRole('button', { name: '틀림' }));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ origin: 'console', document_id: doc.id, run_id: RUN, spot: 'S1', status: 'wrong' });
    await waitFor(() => expect(within(bar).getByText('할 일 1')).toBeTruthy());
    expect(within(bar).getByText('S2')).toBeTruthy(); // 다음 할 일로 넘어간다
    await user.click(within(bar).getByRole('button', { name: /^목록/ }));
    const list = within(bar).getByRole('list', { name: '확인할 곳 목록' });
    expect(within(list).queryByText('V7')).toBeNull(); // 할 일만 보일 때는 판정한 곳이 없다
    await user.click(within(bar).getByRole('button', { name: /^전체/ }));
    await user.click(within(within(bar).getByRole('list', { name: '확인할 곳 목록' })).getByText('V7'));
    expect(within(bar).getAllByText('틀림').length).toBeGreaterThan(0);
    await user.click(within(bar).getByRole('button', { name: '메모' }));
    await user.type(within(bar).getByLabelText('메모'), '℃ 앞 범위 빠짐');
    await user.click(within(bar).getByRole('button', { name: '메모 저장' }));
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(String(patch?.[0])).toBe('/api/live/reviews/7');
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ comment: '℃ 앞 범위 빠짐' });
    expect(await within(bar).findByText('℃ 앞 범위 빠짐')).toBeTruthy();
  });

  it('원본과 추출 결과 사이 폭을 키보드로 바꾸고 기억한다', async () => {
    serve();
    history.replaceState(null, '', `/?view=live&doc=${doc.id}&review=source`);
    render(<App />);
    const handle = await screen.findByRole('separator', { name: '원본과 추출 결과 폭' });
    expect(handle.getAttribute('aria-valuenow')).toBe('50');
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(handle.getAttribute('aria-valuenow')).toBe('54');
    expect(localStorage.getItem('docops.review.split')).toBe('54');
    expect(document.querySelector<HTMLElement>('.source-pair')?.style.getPropertyValue('--split')).toBe('54%');
    fireEvent.keyDown(handle, { key: 'End' });
    expect(handle.getAttribute('aria-valuenow')).toBe('75');
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(handle.getAttribute('aria-valuenow')).toBe('50');
  });
});

describe('사이드바', () => {
  it('접으면 기억하고, 마우스를 올리면 겹쳐 펼쳤다가 벗어나면 다시 접힌다', async () => {
    const user = userEvent.setup();
    serve();
    render(<App />);
    const root = document.querySelector('.shell-root')!;
    await user.click(screen.getByRole('button', { name: '사이드바 접기' }));
    expect(root.className).toContain('shell-collapsed');
    expect(localStorage.getItem('docops.sidebar')).toBe('collapsed');
    const sidebar = screen.getByRole('complementary', { name: '주 탐색 메뉴' });
    // 접기 단추를 누른 직후에는 마우스가 아직 위에 있어도 펼치지 않는다. 나갔다 들어오면 펼친다.
    await user.unhover(sidebar);
    await user.hover(sidebar);
    await waitFor(() => expect(root.className).toContain('shell-peek'));
    expect(screen.getByRole('button', { name: '사이드바 펼친 채 고정' })).toBeTruthy();
    expect(root.className).toContain('shell-collapsed'); // 본문 폭은 접힌 기준 그대로
    await user.unhover(sidebar);
    await waitFor(() => expect(root.className).not.toContain('shell-peek'));
    cleanup();
    render(<App />);
    expect(document.querySelector('.shell-root')!.className).toContain('shell-collapsed');
  });

  it('키보드 초점이 들어가면 펼치고, Esc나 초점이 나가면 접는다. 고정 단추로 펼친 채 둔다', async () => {
    const user = userEvent.setup();
    serve();
    localStorage.setItem('docops.sidebar', 'collapsed');
    render(<App />);
    const root = document.querySelector('.shell-root')!;
    expect(root.className).toContain('shell-collapsed');
    const link = within(screen.getByRole('navigation', { name: '업무 메뉴' })).getByRole('link', { name: '에이전트 작업' });
    link.focus();
    await waitFor(() => expect(root.className).toContain('shell-peek'));
    await user.keyboard('{Escape}');
    expect(root.className).not.toContain('shell-peek');
    link.focus();
    await waitFor(() => expect(root.className).toContain('shell-peek'));
    await user.click(screen.getByRole('button', { name: '사이드바 펼친 채 고정' }));
    expect(root.className).not.toContain('shell-collapsed');
    expect(localStorage.getItem('docops.sidebar')).toBe('open');
  });
});
