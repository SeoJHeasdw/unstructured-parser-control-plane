import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import LiveWorkspace from '../LiveWorkspace';
import { headingOf, lineKinds, parseMarkdown } from '../markdown';

/* 자동 대조 원장(우선순위 쪽·단건 조회·finding ID)과 문서함 서버 목록. 합성 응답만 쓴다. */
const RUN = 'c'.repeat(32);
const doc = { id: 'doc-q', name: '압력기록.xlsx', format: 'XLSX', size_bytes: 10, status: 'completed', seq: 9,
  created_at: '2026-11-27T00:00:00Z', updated_at: '2026-11-27T00:00:00Z', parser: 'docling', error: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const low = (n: number) => ({ key: `S${n}`, id: `F${String(n).padStart(12, '0')}`, rank: n, severity: 'low', kind: 'cell_moved', message: `열 밀림 ${n}`,
  unit: 'sheet:S01', label: '시트 S01', page: null, sheet: 'S01', cell: `A${n}`, ref: `S01!A${n}`, line: n, line_end: n,
  source: '', source_hit: '', result: '', result_hit: '', result_role: 'same' });
const high = { ...low(441), rank: 0, severity: 'high', kind: 'cell_changed', message: "시트 S12 2행: 원본 칸 B2 '17'→'999' 결과의 같은 칸과 다릅니다.",
  unit: 'sheet:S12', label: '시트 S12', sheet: 'S12', cell: 'B2', ref: 'S12!B2', line: 500, line_end: 500 };
const gate = { state: 'needs_review', label: '검수 필요', unresolved: 441, unresolved_high: 1, open_reviews: 0, wrong_reviews: 0,
  reasons: [{ code: 'findings', message: '확인하지 않은 의심점 441곳(높음 1)이 있습니다.', blocking: true },
    { code: 'shared_layer', message: '파서와 대조 기준이 같은 저장 값입니다.', blocking: false }] };
const base = { id: doc.id, run_id: RUN, is_latest: true, document_status: 'completed', method: '저장된 셀 값', format: 'XLSX', parser: 'docling',
  rule_version: 'verify-test', summary: { units: 12, checked: 12, source_chars: 100, matched_chars: 99, coverage: 0.99, spots: 441, high: 1, medium: 0, low: 440, scan_units: 0 },
  units: [], top: ['S441'], notes: [], spots_total: 441, gate, reasons: gate.reasons,
  checks: [{ id: 'preserved', label: '제자리 셀 값', state: 'done', derived_from: 'same_layer', units: 12, checked: 12, excluded: 0, unverified: 0 }] };

function serveReview(firstPage: unknown[], secondPage: unknown[], posted: Record<string, unknown>[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'POST' && path === '/api/live/reviews') {
      const body = JSON.parse(String(init?.body));
      posted.push(body);
      return json({ id: 1, document_id: doc.id, document_seq: 9, document_name: doc.name, document_format: 'XLSX', document_status: 'completed',
        run_id: RUN, is_latest_run: true, created_at: '', updated_at: '', decided_at: '', origin: 'console', spot: 'S441', finding_id: body.finding_id,
        kind: 'cell_changed', severity: 'high', page: null, sheet: 'S12', cell: 'B2', line: 500, line_end: 500, ref: 'S12!B2', note: high.message,
        source_text: '', source_hit: '17', result_text: '', result_hit: '999', status: body.status, comment: null, batch: null, created: true }, 201);
    }
    if (method !== 'GET') throw new Error(`예상하지 못한 요청 ${method} ${path}`);
    if (path.split('?')[0] === '/api/live/documents') return json({ documents: [doc] });
    if (path === `/api/live/documents/${doc.id}`) return json(doc);
    if (path === `/api/live/documents/${doc.id}/runs`) return json({ runs: [{ run_id: RUN, completed_at: '', parser: 'docling', parser_version: '2', ocr_enabled: null, is_latest: true }] });
    if (path === `/api/live/documents/${doc.id}/runs/${RUN}`) return json({ run_id: RUN, completed_at: '', parser: 'docling', parser_version: '2', ocr_enabled: null, is_latest: true,
      markdown: Array.from({ length: 520 }, (_, i) => `| 줄 ${i + 1} |`).join('\n'), warnings: [], locations: [] });
    if (path.startsWith('/api/live/reviews?')) return json({ reviews: [], counts: {} });
    if (path === `/api/live/documents/${doc.id}/verify/spots/S441?run=${RUN}`) return json({ ...high, run_id: RUN });
    if (path.startsWith(`/api/live/documents/${doc.id}/verify?`)) {
      const params = new URLSearchParams(path.split('?')[1]);
      const spots = params.get('offset') ? secondPage : firstPage;
      const matched = firstPage.length + secondPage.length;
      return json({ ...base, spots, spots_matched: matched, page: { offset: Number(params.get('offset') ?? 0), limit: 400, order: 'priority', next: params.get('offset') ? null : firstPage.length } });
    }
    if (path.endsWith('/result')) return json({ id: doc.id, markdown: '', parser: 'docling', parser_version: '2', is_stale: false, warnings: [] });
    if (path === '/api/live/qc-summary') return json({ detail: '없음' }, 404);
    return json({ detail: '없음' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/'); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('자동 대조 원장', () => {
  it('받은 쪽에 없는 S번호도 주소로 열고, finding ID로 검수 요청을 만들며, 판정 상태와 이유를 펼친다', async () => {
    const user = userEvent.setup();
    const posted: Record<string, unknown>[] = [];
    // 첫 쪽에 S441이 없는 예전 절단을 흉내 낸다: 주소의 check=S441은 원장에서 하나만 받아 연다.
    const fetchMock = serveReview(Array.from({ length: 3 }, (_, i) => low(i + 1)), [], posted);
    history.replaceState(null, '', `/?view=live&doc=${doc.id}&review=source&check=S441`);
    render(<App />);
    const bar = await screen.findByRole('region', { name: '확인할 곳' });
    expect(await within(bar).findByText(high.message)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/verify/spots/S441'))).toBe(true);
    await user.click(within(within(bar).getByRole('group', { name: 'S441 판정' })).getByRole('button', { name: '틀림' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ origin: 'console', document_id: doc.id, run_id: RUN, finding_id: high.id, status: 'wrong' });
    const chip = within(bar).getByRole('button', { name: /검수 필요/ });
    await user.click(chip);
    const panel = within(bar).getByRole('dialog', { name: '문서 판정: 검수 필요' });
    expect(within(panel).getByText('확인하지 않은 의심점 441곳(높음 1)이 있습니다.')).toBeTruthy();
    expect(within(panel).getByText('제자리 셀 값')).toBeTruthy();
    expect(within(panel).getByText(/파서와 같은 원천/)).toBeTruthy();
  });

  it('우선순위 다음 쪽은 목록 끝의 더 보기로 이어 받는다', async () => {
    const user = userEvent.setup();
    const fetchMock = serveReview([high, low(1)], [low(2), low(3)], []);
    history.replaceState(null, '', `/?view=live&doc=${doc.id}&review=source`);
    render(<App />);
    const bar = await screen.findByRole('region', { name: '확인할 곳' });
    await waitFor(() => expect(within(bar).getByText('할 일 4')).toBeTruthy());  // 받은 2곳 + 남은 2곳
    await user.click(within(bar).getByRole('button', { name: /^목록/ }));
    const list = within(bar).getByRole('list', { name: '확인할 곳 목록' });
    expect(within(list).getAllByRole('button')[0].textContent).toContain('S441');  // 높음이 먼저
    await user.click(within(list).getByRole('button', { name: /다음 2곳 더 보기/ }));
    await waitFor(() => expect(within(list).getByText('열 밀림 3')).toBeTruthy());
    const more = fetchMock.mock.calls.map(([path]) => String(path)).find(path => path.includes('offset=2'));
    expect(more).toContain('unreviewed=true');
    expect(within(list).queryByRole('button', { name: /더 보기/ })).toBeNull();
  });
});

describe('문서함 서버 목록', () => {
  type Doc = typeof doc & { qc?: unknown };
  const make = (n: number, format: string): Doc => ({ ...doc, id: `id${n}`, name: `문서${n}.${format.toLowerCase()}`, format, seq: n, updated_at: `2026-11-27T00:00:${String(n % 60).padStart(2, '0')}Z` });
  function servePages() {
    const all = [...Array.from({ length: 60 }, (_, i) => make(i + 1, i % 2 ? 'XLSX' : 'XLSM'))].reverse();
    all[0] = { ...all[0], qc: { state: 'needs_review', label: '검수 필요', unresolved: 3 } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/live/qc-summary') return json({ rule_version: 'v', documents: 60, parsed: 58, qc_done: 57, qc_pending: 1, qc_unavailable: 0,
        states: { needs_review: 3, undetermined: 50, pass_candidate: 4 }, not_parsed: { unsupported_format: 2 }, human_decided: 1, processing: 0 });
      if (path.split('?')[0] !== '/api/live/documents') return json({ detail: '없음' }, 404);
      const params = new URLSearchParams(path.split('?')[1] ?? '');
      const format = params.get('format');
      const matching = format ? all.filter(item => item.format === format) : all;
      const start = params.get('cursor') ? Number(params.get('cursor')) : 0;
      const limit = Number(params.get('limit') ?? 50);
      const page = matching.slice(start, start + limit);
      return json({ documents: page, total: matching.length, next_cursor: start + limit < matching.length ? String(start + limit) : null,
        facets: { formats: { XLSX: 30, XLSM: 30 }, statuses: { completed: matching.length } } });
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('확장자로 거르면 서버에 그 확장자만 묻고, 더 보기로 이어 받으며, 판정 상태와 깔때기를 보인다', async () => {
    const user = userEvent.setup();
    const fetchMock = servePages();
    render(<LiveWorkspace />);
    await screen.findByText('문서60.xlsx');
    expect(screen.getByText('50 / 60개 문서')).toBeTruthy();
    const funnel = screen.getByRole('region', { name: '처리 깔때기' });
    expect(within(funnel).getByText('반입 전체')).toBeTruthy();
    expect(within(funnel).getByText('못 함 2')).toBeTruthy();
    expect(within(funnel).getByText('통과 후보')).toBeTruthy();
    const firstRow = screen.getByRole('link', { name: /문서60\.xlsx/ });
    expect(firstRow.querySelector('.lw-status-cell .qc-badge')?.textContent).toBe('검수 필요3');
    await user.click(screen.getByRole('button', { name: /10개 더 보기/ }));
    await screen.findByText('문서1.xlsm');
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('cursor=50'))).toBe(true);
    await user.selectOptions(screen.getByRole('combobox', { name: '확장자 필터' }), 'XLSM');
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes('format=XLSM'))).toBe(true));
    await waitFor(() => expect(screen.queryByText('문서60.xlsx')).toBeNull());
    expect(screen.getByText('문서59.xlsm')).toBeTruthy();
    expect(screen.getByText('30개 문서')).toBeTruthy();
  });
});

describe('제목 해석(CommonMark ATX)', () => {
  it('닫는 #·들여쓰기·이스케이프·코드 블록·#LOT-7을 규격대로 가른다', () => {
    expect(headingOf('# C#')).toEqual({ level: 1, text: 'C#' });
    expect(headingOf('  ## 들여 쓴 제목')).toEqual({ level: 2, text: '들여 쓴 제목' });
    expect(headingOf('    # 코드')).toBeNull();
    expect(headingOf('## 제목 ##')).toEqual({ level: 2, text: '제목' });
    expect(headingOf('### foo \\###')).toEqual({ level: 3, text: 'foo \\###' });
    expect(headingOf('#LOT-7 입고')).toBeNull();
    expect(headingOf('\\# 1 리터럴')).toBeNull();
    const markdown = ['```', '# 코드 안의 주석', '```', '# C#', '  ## 둘째'].join('\n');
    expect(parseMarkdown(markdown).map(block => block.kind)).toEqual(['code', 'heading', 'heading']);
    const kinds = lineKinds(markdown);
    expect(kinds.get(2)).toEqual({ role: 'code' });
    expect(kinds.get(4)).toEqual({ role: 'heading', level: 1, text: 'C#' });
    expect(kinds.get(5)).toEqual({ role: 'heading', level: 2, text: '둘째' });
  });
});

describe('청크의 검수 판정', () => {
  it("'틀림'은 확인된 오류, '보류'는 미해결로 보이고 각 판정을 원문 위치와 함께 연다", async () => {
    const { StrategyModal } = await import('../retrieval/chunk-detail');
    const text = 'PRESSURE 71 bar';
    const chunk = { index: 0, text, start: 0, end: text.length, heading_path: [], kind: 'text', chars: text.length, est_tokens: 6, elements: [], element_kinds: [],
      page: 1, parent: null, flags: ['confirmed-wrong', 'unverified'], regions: [{ page: 1 }], qc_total: 2, qc_counts: { wrong: 1, unclear: 1, open: 0 },
      qc: [
        { key: 'V3', severity: 'high', kind: 'manual', message: '단위 bar 확인', page: 1, sheet: null, cell: null, line: 1, line_end: 1,
          review: { id: 3, status: 'wrong', comment: '화면은 17 bar' } },
        { key: 'S1', id: 'F0123456789ab', severity: 'high', kind: 'hidden_layer', message: '보이지 않는 글자 층의 값 71', page: 1, sheet: null, cell: null,
          line: 1, line_end: 1, source_hit: '71', result_hit: '71', source_layer: 'pdf_hidden_layer', review: { id: 4, status: 'unclear', comment: null } },
      ] };
    const source = { doc_id: 'doc-p', sample: null, name: '압력.pdf', is_stale: false, chars: text.length, est_tokens: 6, tables: 0, headings: 0, sections: 1, text,
      elements: [], pages: 1, composition: {}, run_id: RUN, text_sha256: 'a'.repeat(64), qc: { state: 'needs_review', label: '검수 필요', wrong: 1, unclear: 1 } };
    const column = { id: 'fixed', name: '고정 길이', kind: 'fixed', params: { size: 64 }, result: { id: 'fixed', chunks: [chunk], stats: null, outcomes: {}, by_kind: {} } };
    render(<StrategyModal source={source as never} column={column as never} tab="chunks" index={0} onTab={() => {}} onIndex={() => {}} onClose={() => {}} onEdit={() => {}} measure={null} />);
    const block = screen.getByRole('region', { name: '검수할 곳' });
    expect(within(block).getByText('틀림 확인 · V3')).toBeTruthy();
    expect(within(block).getByText('보류 · V4')).toBeTruthy();
    expect(within(block).getByText('검수 메모: 화면은 17 bar')).toBeTruthy();
    expect(within(block).getByText(/틀림 확인 1 · 보류 1/)).toBeTruthy();
    const links = within(block).getAllByRole('link', { name: /판정·원문 위치/ }).map(link => link.getAttribute('href') ?? '');
    expect(links[0]).toContain('check=V3'); expect(links[1]).toContain('check=V4');
    expect(links[1]).toContain('page=1'); expect(links[1]).toContain(`run=${RUN}`); expect(links[1]).toContain('line=1');
    expect(screen.getAllByText('틀림 확인').length).toBeGreaterThan(0);  // 목록·표시 설명에도 '틀림 확인'
  });
});
