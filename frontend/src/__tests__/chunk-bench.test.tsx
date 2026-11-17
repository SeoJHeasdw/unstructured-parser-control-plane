import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChunkBench from '../ChunkBench';
import { STORE } from '../retrieval/shared';

/* 합성 문서만 쓴다: 반복 머리말 · 제목 · 본문 · 표 · 캡션 · 그림 · 2쪽의 글자 없는 그림. */
const PARTS: [string, string, string, number][] = [
  ['f1', 'furniture', '합성 점검 보고서 · 예시', 1],
  ['h1', 'heading', '# 점검 개요', 1],
  ['t1', 'text', '가상의 보관 장비를 점검했습니다. 온도와 습도를 기록합니다.', 1],
  ['tb1', 'table', '| 항목 | 값 |\n| --- | --- |\n| 온도 | 5도 |\n| 습도 | 40% |', 1],
  ['c1', 'caption', '표 1. 보관 조건', 1],
  ['i1', 'image', '[그림 1]', 1],
  ['c2', 'caption', '그림 1. 장비 배치도', 1],
  ['f2', 'furniture', '합성 점검 보고서 · 예시', 2],
  ['i2', 'image', '', 2],
  ['t2', 'text', '둘째 쪽 문단입니다. 예시 기록을 남깁니다.', 2],
];
let TEXT = '';
const ELEMENTS = PARTS.map(([id, kind, body, page]) => {
  if (TEXT) TEXT += '\n\n';
  const start = TEXT.length;
  TEXT += body;
  const label = { f1: '반복 머리말', f2: '반복 머리말', h1: '점검 개요', t1: '본문', t2: '본문', tb1: '표 1 · 2행 × 2열', c1: '캡션', c2: '캡션', i1: '그림 1 · 장비 배치도', i2: '그림 2' }[id]!;
  return { id, kind, start, end: TEXT.length, page, heading_path: ['점검 개요'], label, chars: body.length, est_tokens: body.length,
    ...(kind === 'table' ? { rows: 2, cols: 2 } : {}), ...(id === 'c1' ? { caption_of: 'tb1' } : id === 'c2' ? { caption_of: 'i1' } : {}),
    ...(id === 'i1' ? { caption: '그림 1. 장비 배치도' } : {}), ...(id === 'i2' ? { empty: true } : {}) };
});
const el = (id: string) => ELEMENTS.find(e => e.id === id)!;
const COMPOSITION = { furniture: 2, heading: 1, text: 2, table: 1, caption: 2, image: 2 };
const dist = (v: number) => ({ min: v, median: v, p95: v, max: v, mean: v });

function makeChunks(spans: [number, number][], keep: (id: string) => boolean, flagAt?: number) {
  return spans.map(([start, end], index) => {
    const els = ELEMENTS.filter(e => keep(e.id) && (e.start < end && e.end > start || (e.start === e.end && e.start >= start && e.start <= end)));
    const text = TEXT.slice(start, end);
    return { index, text, start, end, heading_path: ['점검 개요'], kind: els.some(e => e.kind === 'table') ? 'mixed' : 'text', chars: text.length, est_tokens: text.length,
      flags: index === flagAt ? ['over-limit'] : [], elements: els.map(e => e.id), element_kinds: els.map(e => e.kind), page: els[0]?.page ?? 1, parent: null as number | null };
  });
}
function result(s: { id: string; name: string; kind: string; params: { table?: string } }) {
  const baseline = s.kind === 'fixed' || s.kind === 'recursive';
  if (baseline) {
    const cut = el('tb1').start + 20;
    const chunks = makeChunks([[0, cut], [cut, el('f2').start], [el('f2').start, TEXT.length]], () => true, s.kind === 'fixed' ? 0 : undefined);
    return { id: s.id, name: s.name, kind: s.kind, params: s.params, chunks, parents: [],
      stats: { count: chunks.length, chars: dist(120), tokens: dist(120), over_limit: s.kind === 'fixed' ? 1 : 0, coverage: 1, duplication: 0, tables_total: 1, tables_split: 1, total_chars: TEXT.length, total_tokens: TEXT.length, flags: {} },
      outcomes: { f1: 'whole', h1: 'whole', t1: 'whole', tb1: 'split', c1: 'detached', i1: 'missing', c2: 'detached', f2: 'whole', i2: 'missing', t2: 'whole' },
      by_kind: { table: { split: 1 }, image: { missing: 2 }, caption: { detached: 2 }, furniture: { whole: 2 }, text: { whole: 2 } } };
  }
  const rows = s.params.table === 'rows';
  const chunks = makeChunks([[el('h1').start, el('t1').end], [el('tb1').start, el('c1').end], [el('i1').start, el('c2').end], [el('t2').start, el('t2').end]], id => !['f1', 'f2', 'i2'].includes(id));
  const parentChild = s.kind === 'parent_child';
  if (parentChild) chunks.forEach((c, i) => { c.parent = i < 2 ? 0 : 1; });
  return { id: s.id, name: s.name, kind: s.kind, params: s.params, chunks,
    parents: parentChild ? [{ index: 0, start: el('h1').start, end: el('c1').end, chars: 90, est_tokens: 90, heading_path: [] }, { index: 1, start: el('i1').start, end: TEXT.length, chars: 60, est_tokens: 60, heading_path: [] }] : [],
    stats: { count: chunks.length, chars: dist(rows ? 60 : 80), tokens: dist(60), over_limit: 0, coverage: 0.9, duplication: 0, tables_total: 1, tables_split: 0, total_chars: TEXT.length, total_tokens: TEXT.length, flags: {} },
    outcomes: { f1: 'missing', h1: 'whole', t1: 'whole', tb1: rows ? 'rows' : 'whole', c1: 'attached', i1: 'caption', c2: 'attached', f2: 'missing', i2: 'missing', t2: 'whole' },
    by_kind: { table: { [rows ? 'rows' : 'whole']: 1 }, image: { caption: 1, missing: 1 }, caption: { attached: 2 }, furniture: { missing: 2 }, text: { whole: 2 } } };
}
const SAMPLES = [
  { id: 'sop', name: '합성 절차서', description: '본문과 목록 위주', composition: { text: 12, list: 4, table: 1 }, pages: 4 },
  { id: 'report', name: '합성 점검 보고서', description: '그림이 많고 스캔 쪽이 하나 있음', composition: COMPOSITION, pages: 2 },
  { id: 'coa', name: '합성 시험 성적서', description: '표 위주', composition: { text: 3, table: 6, caption: 6 }, pages: 3 },
];
const CONFIG = { connections: [], configured: false, specs: [{ id: '예시 모델', dims: 8, dims_note: '', max_tokens: 512, arch: '', pooling: '', query_prefix: '', doc_prefix: '', prefix_note: '', languages: '', note: '' }], strategies: {}, caps: { max_source_chars: 400000, max_bench_chunks: 10000 }, cache: { entries: 0, bytes: 0 } };

let fetchMock: ReturnType<typeof vi.fn>;
let store: Map<string, string>;
const calls = (part: string) => fetchMock.mock.calls.filter(([url]) => String(url).includes(part));
const lastChunkBody = () => JSON.parse(String(calls('/chunk').at(-1)![1].body)) as { source: { sample?: string }; strategies: { id: string; params: Record<string, unknown> }[]; limit_tokens: number | null };
beforeEach(() => {
  store = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => store.set(key, String(value)), removeItem: (key: string) => store.delete(key), clear: () => store.clear(), key: (index: number) => [...store.keys()][index] ?? null, get length() { return store.size; } });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (url.endsWith('/config')) return reply(CONFIG);
    if (url.endsWith('/documents')) return reply({ documents: [] });
    if (url.endsWith('/samples')) return reply({ samples: SAMPLES });
    if (url.endsWith('/chunk')) {
      const body = JSON.parse(String(init?.body));
      const sample = SAMPLES.find(s => s.id === body.source.sample)!;
      return reply({ source: { doc_id: null, sample: sample.id, name: sample.name, is_stale: false, chars: TEXT.length, est_tokens: TEXT.length, tables: 1, headings: 1, sections: 1, text: TEXT, elements: ELEMENTS, pages: 2, composition: COMPOSITION },
        results: body.strategies.map(result) });
    }
    return new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const rowOf = (name: string) => screen.getByRole('button', { name }).closest('tr')!;
async function ready() {
  render(<ChunkBench active />);
  await screen.findByRole('table', { name: '전략 비교' });
}

describe('청킹 벤치', () => {
  it('첫 화면은 머리줄과 비교 표 하나이고, 표에는 요소 종류별 보존 수가 나온다', async () => {
    await ready();
    expect(lastChunkBody().source).toEqual({ sample: 'report' });
    expect(lastChunkBody().strategies).toHaveLength(6);
    expect(lastChunkBody().limit_tokens).toBe(512);
    expect(screen.getByRole('button', { name: '원문: 합성 점검 보고서' })).toBeTruthy();
    expect(screen.getAllByText('예시 데이터')).toHaveLength(1);
    const comp = screen.getByRole('list', { name: /문서 구성/ }).textContent!;
    for (const part of ['본문2', '표1', '그림2', '캡션2', '반복 머리말2']) expect(comp).toContain(part);
    expect(screen.getByRole('tab', { name: '전략 비교' }).getAttribute('aria-selected')).toBe('true');

    const table = screen.getByRole('table', { name: '전략 비교' });
    expect(within(table).getAllByRole('row')).toHaveLength(7);
    const head = within(table).getAllByRole('columnheader');
    expect(head.map(th => th.textContent)).toEqual(['전략', '청크 수', '길이 중앙값(자)', '표 보존', '그림', '캡션 함께', '머리말 제거', '한도 초과512토큰']);
    expect(head.every(th => !th.hasAttribute('title') && !th.querySelector('[title]'))).toBe(true);

    const whole = rowOf('요소 인지 · 표 통째');
    const cells = within(whole).getAllByRole('cell');
    expect(cells[0].textContent).toBe('4');
    expect(cells[2].textContent).toBe('1/1');
    expect(cells[2].querySelector('.is-best')).toBeTruthy();
    expect(cells[3].textContent).toBe('1/2');
    expect(cells[3].querySelector('.is-bad')).toBeNull();
    expect(cells[5].textContent).toBe('2/2');

    const fixed = rowOf('고정 500자');
    expect(within(fixed).getByText('기준선')).toBeTruthy();
    const f = within(fixed).getAllByRole('cell');
    expect(f[2].textContent).toBe('0/11개 잘림');
    expect(f[2].querySelector('.cb-ratio.is-bad')).toBeTruthy();
    expect(f[3].textContent).toBe('0/21개 빠짐');
    expect(f[4].textContent).toBe('0/22개 떨어짐');
    expect(f[5].textContent).toBe('0/22개 남음');
    expect(f[6].textContent).toBe('1');
    expect(within(rowOf('부모-자식')).getAllByRole('cell')[0].textContent).toBe('4맥락 2');
    expect(screen.getByText(/2쪽 그림은 글자가 없어/)).toBeTruthy();

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(calls('/tokens')).toHaveLength(0);
  });

  it('줄을 누르면 그 전략의 팝업: 청크 목록 + 상세, 문서 위 청크, 설정. Escape로 닫으면 그 줄로 초점이 돌아온다', async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(screen.getByRole('button', { name: '고정 500자' }));
    const dialog = screen.getByRole('dialog', { name: /고정 500자/ });
    const list = within(dialog).getByRole('listbox', { name: '청크 목록' });
    expect(within(list).getAllByRole('option')).toHaveLength(3);
    expect(within(list).getAllByRole('option')[0].textContent).toContain('한도 초과');
    expect(within(dialog).getByRole('heading', { name: '1번 청크' })).toBeTruthy();
    expect(within(dialog).getByText('2조각으로 잘림 · 머리행 없음').className).toContain('is-bad');

    await user.keyboard('{ArrowDown}');
    expect(within(dialog).getByRole('heading', { name: '2번 청크' })).toBeTruthy();
    expect(within(dialog).getAllByText('대상과 다른 청크')).toHaveLength(2);
    /* 잘린 표 조각은 머리행 없이 그린다. */
    expect(within(within(dialog).getByRole('table')).queryAllByRole('columnheader')).toHaveLength(0);
    expect(within(within(dialog).getByRole('table')).getAllByRole('row')).toHaveLength(2);

    await user.click(within(dialog).getByRole('tab', { name: '문서 위 청크' }));
    const brackets = within(dialog).getByRole('group', { name: '고정 500자 청크' });
    expect(within(brackets).getAllByRole('button')).toHaveLength(3);
    await user.click(within(brackets).getByRole('button', { name: /^3번 청크/ }));
    expect(within(dialog).getByRole('tab', { name: /청크/, selected: true }).textContent).toContain('3');
    expect(within(dialog).getByRole('heading', { name: '3번 청크' })).toBeTruthy();

    await user.click(within(dialog).getByRole('tab', { name: '설정' }));
    expect(within(dialog).getByText('구분하지 않고 글자로만 자름')).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: '토큰 실측' }) as HTMLButtonElement).disabled).toBe(true);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '고정 500자' }));
  });

  it('요소 인지 전략의 청크는 표를 표로 보여 준다', async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(within(rowOf('요소 인지 · 표 통째')).getAllByRole('cell')[1]);
    const dialog = screen.getByRole('dialog', { name: '요소 인지 · 표 통째' });
    await user.click(within(dialog).getAllByRole('option')[1]);
    const table = within(dialog).getByRole('table');
    expect(within(table).getAllByRole('columnheader').map(th => th.textContent)).toEqual(['항목', '값']);
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(within(dialog).getByText('대상과 같은 청크')).toBeTruthy();
  });

  it('원문 구성 탭은 요소를 종류별 목록으로 보여 주고, 고른 요소의 전략별 결과를 보여 준다', async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(screen.getByRole('tab', { name: '원문 구성' }));
    const list = screen.getByRole('listbox', { name: '원문 요소' });
    expect(list.textContent!.indexOf('표 1')).toBeLessThan(list.textContent!.indexOf('그림 2'));
    expect(within(list).queryByText('점검 개요')).toBeNull();
    const pane = screen.getByLabelText('요소 상세');
    expect(within(pane).getByRole('table')).toBeTruthy();
    const results = within(pane).getAllByRole('listitem');
    expect(results).toHaveLength(6);
    expect(results.find(li => li.textContent!.startsWith('요소 인지 · 표 통째'))!.textContent).toContain('온전');
    expect(results.find(li => li.textContent!.startsWith('요소 인지 · 행 묶음'))!.textContent).toContain('행 묶음(머리행 반복)');
    const cut = results.find(li => li.textContent!.startsWith('고정 500자'))!;
    expect(cut.textContent).toContain('잘림');
    expect(cut.querySelector('b')!.className).toContain('is-bad');

    await user.click(within(list).getByText('그림 2'));
    expect(within(screen.getByLabelText('요소 상세')).getByText('글자 없는 그림')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('전략 설정 팝업: 비교 포함은 6개까지, 표·그림 처리는 말로 고르고, 바꾸면 다시 나눈다', async () => {
    const user = userEvent.setup();
    await ready();
    const opener = screen.getByRole('button', { name: '전략 설정' });
    await user.click(opener);
    const dialog = screen.getByRole('dialog', { name: '전략 설정' });
    const list = within(dialog).getByRole('listbox', { name: '전략 목록' });
    expect(within(list).getAllByRole('option')).toHaveLength(6);
    expect(within(list).getAllByRole('checkbox').every(box => (box as HTMLInputElement).checked)).toBe(true);
    expect(within(dialog).getByText('비교에 6개 포함 · 최대 6개')).toBeTruthy();

    await user.click(within(dialog).getByRole('button', { name: /전략 추가/ }));
    expect((within(list).getByRole('checkbox', { name: '요소 인지 7 비교에 포함' }) as HTMLInputElement).disabled).toBe(true);
    expect((within(dialog).getByRole('textbox', { name: '전략 이름' }) as HTMLInputElement).value).toBe('요소 인지 7');
    expect(within(dialog).queryByRole('spinbutton', { name: '행 묶음 크기' })).toBeNull();
    await user.click(within(dialog).getByRole('radio', { name: '행 묶음마다 머리행 반복' }));
    expect(within(dialog).getByRole('spinbutton', { name: '행 묶음 크기' })).toBeTruthy();
    expect((within(dialog).getByRole('radio', { name: /그림 설명 생성/ }) as HTMLInputElement).disabled).toBe(true);
    expect(within(dialog).getByText('시각 모델 연결 필요')).toBeTruthy();
    await user.selectOptions(within(dialog).getByRole('combobox', { name: '나누는 방식' }), 'fixed');
    expect(within(dialog).queryByRole('radiogroup', { name: '표 처리' })).toBeNull();

    const before = calls('/chunk').length;
    await user.click(within(list).getByRole('checkbox', { name: '재귀 500자 비교에 포함' }));
    await waitFor(() => expect(calls('/chunk').length).toBeGreaterThan(before));
    expect(lastChunkBody().strategies.map(s => s.id)).not.toContain('builtin-recursive');
    expect(JSON.parse(store.get(STORE.presets)!)).toHaveLength(7);
    expect(STORE.presets).toBe('document-ops:chunk-presets-v3');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('원문 팝업에서 다른 예시 문서를 고르면 그 문서로 다시 나눈다', async () => {
    const user = userEvent.setup();
    await ready();
    await user.click(screen.getByRole('button', { name: '원문: 합성 점검 보고서' }));
    const dialog = screen.getByRole('dialog', { name: '원문' });
    const list = within(dialog).getByRole('listbox', { name: '원문 목록' });
    expect(within(list).getAllByRole('option')).toHaveLength(3);
    expect(within(list).getByText('예시 문서')).toBeTruthy();
    await user.click(within(list).getByText('합성 시험 성적서'));
    await user.click(within(dialog).getByRole('button', { name: '이 문서로 나누기' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(lastChunkBody().source).toEqual({ sample: 'coa' }));
  });
});
