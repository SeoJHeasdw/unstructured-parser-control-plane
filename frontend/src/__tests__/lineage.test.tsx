import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LineageView from '../LineageView';
import type { LineageData } from '../api/lineage';
import { installFlowDomMocks, memoryStorage } from './flowTestEnv';
import example from './fixtures/lineage.json';

/** 예시 입력으로 계산한 응답(합성 데이터). */
const EXAMPLE = example as unknown as LineageData;
const EMPTY: LineageData = {
  source: 'live', as_of: '2026-11-17T09:00:00+09:00', generated_at: '2026-11-17T09:00:00+09:00',
  documents: { total: 0, analysed: 0, not_analysed: 0, structure_errors: 0 },
  summary: { families: 0, versioned: 0, hold: 0, contained: 0, duplicates: 0, references: { linked: 0, outdated: 0, missing: 0, ambiguous: 0, external: 0 } },
  families: [], entries: {}, instances: {}, references: [],
};
const SOURCE_KEY = 'document-ops:lineage-source:v1';
const PREFS_KEY = 'document-ops:lineage-ui:v1';
let store: Map<string, string>;

function mockFetch(live: LineageData | null = EMPTY) {
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
    const text = String(url);
    if (!text.startsWith('/api/lineage')) return { ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) };
    if (text.includes('source=example')) return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(EXAMPLE)) };
    if (!live) return { ok: false, status: 404, json: async () => ({ detail: '문서 계보를 계산할 수 없습니다.' }) };
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(live)) };
  }));
}
const fetchUrls = () => vi.mocked(fetch).mock.calls.map(([url]) => String(url));
const list = () => screen.getByRole('complementary', { name: '문서군 목록' });
const lane = () => screen.getByRole('list', { name: /판 순서/ });

beforeEach(() => { installFlowDomMocks(); store = memoryStorage(); mockFetch(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('문서 계보', () => {
  it('화면을 처음 열 때 불러오고, 실제 파일이 없으면 예시 데이터로 바꿀 수 있다', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<LineageView active={false} />);
    expect(fetch).not.toHaveBeenCalled();
    rerender(<LineageView active />);
    expect(await screen.findByText('아직 올린 파일이 없습니다')).toBeTruthy();
    expect(fetchUrls()).toEqual(['/api/lineage?source=live']);
    expect(screen.getByRole('button', { name: '실제 파일' }).getAttribute('aria-pressed')).toBe('true');

    await user.click(screen.getByRole('button', { name: '예시 데이터 보기' }));
    expect(await screen.findByRole('heading', { level: 2, name: EXAMPLE.families[0].title })).toBeTruthy();
    expect(fetchUrls()).toContain('/api/lineage?source=example');
    expect(screen.getByRole('button', { name: '예시 데이터' }).getAttribute('aria-pressed')).toBe('true');
    expect(store.get(SOURCE_KEY)).toBe('example');

    await user.click(screen.getByRole('button', { name: '실제 파일' }));
    expect(await screen.findByText('아직 올린 파일이 없습니다')).toBeTruthy();
    expect(store.get(SOURCE_KEY)).toBe('live');
  });

  it('기본 화면은 문서군 하나만 보여 주고 요약과 상세는 닫혀 있다', async () => {
    store.set(SOURCE_KEY, 'example');
    const user = userEvent.setup();
    render(<LineageView active />);
    expect(await screen.findByRole('heading', { level: 2, name: EXAMPLE.families[0].title })).toBeTruthy();
    expect(within(list()).getAllByRole('listitem')).toHaveLength(EXAMPLE.families.length);
    expect(screen.queryByRole('group', { name: '요약' })).toBeNull();
    expect(screen.queryByRole('complementary', { name: '상세' })).toBeNull();
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(screen.getByText('예시 데이터', { selector: 'em' })).toBeTruthy();

    const toggle = screen.getByRole('button', { name: '요약' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await user.click(toggle);
    const summary = screen.getByRole('group', { name: '요약' });
    expect(summary.textContent).toContain(`문서군${EXAMPLE.summary.families}`);
    expect(JSON.parse(store.get(PREFS_KEY)!).summaryOpen).toBe(true);

    await user.click(within(summary).getByRole('button', { name: /판단 보류/ }));
    expect(within(list()).getAllByRole('listitem')).toHaveLength(EXAMPLE.summary.hold);
  });

  it('마우스를 올리면 설명이 뜨고 이어진 문서군만 또렷하게 남는다', async () => {
    store.set(SOURCE_KEY, 'example');
    const user = userEvent.setup();
    render(<LineageView active />);
    await screen.findByRole('heading', { level: 2, name: EXAMPLE.families[0].title });

    const version = within(lane()).getAllByRole('button')[0];
    await user.hover(version);
    expect((await screen.findByRole('tooltip')).textContent).toContain('설비 점검표.xlsx');
    expect(version.getAttribute('aria-describedby')).toBe('ln-tip');
    await user.unhover(version);
    await user.hover(screen.getByRole('tooltip'));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());

    const sop = within(list()).getByRole('button', { name: /SOP-QC-0040 세척 밸리데이션 절차/ });
    await user.hover(sop);
    expect(sop.className).toContain('is-hl');
    expect(list().querySelectorAll('.ln-fam.is-dim').length).toBeGreaterThan(0);
    expect((await screen.findByRole('tooltip')).textContent).toContain('최신 확정');
    await user.unhover(sop);
    expect(list().querySelectorAll('.ln-fam.is-dim')).toHaveLength(0);
  });

  it('클릭하면 상세 창에 고정되고 Escape나 닫기 단추로 닫힌다', async () => {
    store.set(SOURCE_KEY, 'example');
    const user = userEvent.setup();
    render(<LineageView active />);
    await screen.findByRole('heading', { level: 2, name: EXAMPLE.families[0].title });
    await user.click(within(list()).getByRole('button', { name: /설비점검 관리대장/ }));
    expect(screen.getByRole('heading', { level: 2, name: '설비점검 관리대장' })).toBeTruthy();

    const missing = screen.getByRole('button', { name: /대상 미발견.*SOP-PD-0076/ });
    await user.click(missing);
    const panel = screen.getByRole('complementary', { name: '상세' });
    expect(within(panel).getByText('점검 이력!B20')).toBeTruthy();
    expect(missing.className).toContain('is-pinned');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '상세' })).toBeNull());

    await user.click(within(lane()).getByRole('button', { name: /2026-11-12/ }));
    expect(within(screen.getByRole('complementary', { name: '상세' })).getByText('최신 판단 근거')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '상세 닫기' }));
    expect(screen.queryByRole('complementary', { name: '상세' })).toBeNull();
  });

  it('관계 그래프로 바꾸면 노드에 설명과 고정이 같은 방식으로 동작하고 보기 방식을 기억한다', async () => {
    store.set(SOURCE_KEY, 'example');
    const user = userEvent.setup();
    render(<LineageView active />);
    await screen.findByRole('heading', { level: 2, name: EXAMPLE.families[0].title });
    await user.click(within(list()).getByRole('button', { name: /SOP-QC-0040 세척 밸리데이션 절차/ }));
    await user.click(screen.getByRole('button', { name: /관계 그래프/ }));
    expect(JSON.parse(store.get(PREFS_KEY)!).view).toBe('graph');
    await waitFor(() => expect(document.querySelectorAll('.ln-gnode').length).toBeGreaterThan(1));

    const center = document.querySelector('.ln-gnode.is-center') as HTMLElement;
    await user.hover(center);
    expect((await screen.findByRole('tooltip')).textContent).toContain('Rev5');
    await user.click(center);
    expect(screen.getByRole('complementary', { name: '상세' })).toBeTruthy();
  });

  it('불러오지 못하면 이유와 다시 시도를 보여 준다', async () => {
    mockFetch(null);
    const user = userEvent.setup();
    render(<LineageView active />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('문서 계보를 계산할 수 없습니다.');
    mockFetch(EMPTY);
    await user.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('아직 올린 파일이 없습니다')).toBeTruthy();
  });
});
