import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PipelineStudio from '../PipelineStudio';
import { FlowSimulator } from '../flow/flowSim';
import { addFormatRoute, defaultLibrary, formatRoutes, OVERVIEW_ID } from '../flow/flowTemplates';
import { installFlowDomMocks, memoryStorage } from './flowTestEnv';

// 사용자가 제공한 초기 19종. 목록이 닫힌 집합이라는 의미는 아니다.
const reported = ['PDF', 'DOCX', 'DOCM', 'DOC', 'PPTX', 'PPT', 'XLSX', 'XLSM', 'XLS', 'CSV', 'EML', 'MSG', 'MHT', 'HTM', 'PNG', 'JPG', 'TXT', 'LOG', 'ZIP'];
let store: Map<string, string>;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  installFlowDomMocks();
  store = memoryStorage();
  fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ documents: [] }) });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const onlyGets = () => fetchMock.mock.calls.every(([, options]) => !options?.method || options.method === 'GET');
const openFormats = async (user: ReturnType<typeof userEvent.setup>) => { await user.click(screen.getByRole('button', { name: /형식 · 경로/ })); return screen.getByRole('dialog', { name: '형식과 경로' }); };

describe('흐름 이동', () => {
  it('형식별 흐름에서 Esc 또는 뒤로가기로 전체 처리 흐름으로 돌아간다', async () => {
    const user = userEvent.setup();
    render(<PipelineStudio formats={[]} initialFormat="PDF" onOpenDocuments={() => {}} />);
    expect(screen.getByRole('heading', { name: 'PDF 문서' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '뒤로가기' }).getAttribute('aria-keyshortcuts')).toBe('Escape');
    await user.keyboard('{Escape}');
    expect(screen.getByRole('heading', { name: '전체 처리 흐름' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '뒤로가기' })).toBeNull();

    const pages = screen.getByRole('navigation', { name: '흐름 페이지' });
    await user.click(within(pages).getByRole('button', { name: /PDF 문서/ }));
    await user.click(screen.getByRole('button', { name: '뒤로가기' }));
    expect(screen.getByRole('heading', { name: '전체 처리 흐름' })).toBeTruthy();
  });

  it('형식과 경로를 먼저 닫고 비활성 탭에서는 Esc로 흐름을 바꾸지 않는다', async () => {
    const user = userEvent.setup();
    const props = { formats: [], initialFormat: 'PDF', onOpenDocuments: () => {} };
    const { rerender } = render(<PipelineStudio {...props} />);
    const panel = await openFormats(user);
    await user.click(within(panel).getByRole('textbox', { name: '확장자 검색' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '형식과 경로' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'PDF 문서' })).toBeTruthy();

    rerender(<PipelineStudio {...props} active={false} />);
    await user.keyboard('{Escape}');
    expect(screen.getByRole('heading', { name: 'PDF 문서' })).toBeTruthy();
  });
});

describe('형식과 경로', () => {
  it('사용자가 제공한 19종을 모두 경로에 연결하고 미제공 HWP를 임의로 끼워 넣지 않는다', async () => {
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} />);
    const panel = await openFormats(user);
    for (const ext of reported) expect(within(panel).getByRole('button', { name: `.${ext.toLowerCase()} 경로 열기` })).toBeTruthy();
    expect(within(panel).queryByText('.hwp')).toBeNull();
    expect(within(panel).queryByText('.hwpx')).toBeNull();
    expect(Object.keys(formatRoutes(defaultLibrary())).sort()).toEqual([...reported].sort());
    await within(panel).findByText('로컬 형식 0종 확인');
  });

  it('로컬에서 관찰된 새 형식과 Mock 예시를 구분하고, 경로를 만들면 전체 흐름의 라우팅에 연결한다', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ documents: [{ format: 'TIFF' }, { format: 'TIFF' }] }) });
    const user = userEvent.setup(); render(<PipelineStudio formats={['HEIC']} onOpenDocuments={() => {}} />);
    const panel = await openFormats(user);
    expect(await within(panel).findByText('로컬 2건')).toBeTruthy();
    expect(within(panel).getByText('Mock 예시')).toBeTruthy();
    expect(within(panel).getByRole('button', { name: '.tiff 경로 만들기' })).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: '.heic 경로 만들기' }));
    expect(screen.getByRole('heading', { name: '.heic 처리' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '설계' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText(/실제 파서는 등록되지 않습니다/)).toBeTruthy();
    await waitFor(() => expect(store.get('document-ops:flows:v3')).toContain('custom-heic'));
    expect(onlyGets()).toBe(true);
  });

  it('로컬 목록 오류를 0종 관측으로 표시하지 않고 다시 확인할 수 있다', async () => {
    fetchMock.mockRejectedValueOnce(new Error('연결 실패')).mockResolvedValueOnce({ ok: true, json: async () => ({ documents: [{ format: 'HEIC' }] }) });
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} />);
    const panel = await openFormats(user);
    expect(await within(panel).findByText('로컬 목록을 불러오지 못함')).toBeTruthy();
    expect(within(panel).queryByText('로컬 형식 0종 확인')).toBeNull();
    await user.click(within(panel).getByRole('button', { name: '로컬 형식 새로고침' }));
    expect(await within(panel).findByRole('button', { name: '.heic 경로 만들기' })).toBeTruthy();
    expect(within(panel).getByText('로컬 형식 1종 확인')).toBeTruthy();
  });

  it('경로가 없는 형식만 확인하고 경로 이름으로 찾을 수 있다', async () => {
    const user = userEvent.setup(); render(<PipelineStudio formats={['HEIC']} onOpenDocuments={() => {}} />);
    const panel = await openFormats(user);
    await user.click(within(panel).getByRole('radio', { name: '경로 없음' }));
    expect(within(panel).getByRole('button', { name: '.heic 경로 만들기' })).toBeTruthy();
    expect(within(panel).queryByRole('button', { name: '.pdf 경로 열기' })).toBeNull();
    await user.click(within(panel).getByRole('radio', { name: '경로 있음' }));
    await user.type(within(panel).getByRole('textbox', { name: '확장자 검색' }), 'PDF 문서');
    expect(within(panel).getByRole('button', { name: '.pdf 경로 열기' })).toBeTruthy();
    expect(within(panel).queryByRole('button', { name: '.docx 경로 열기' })).toBeNull();
  });

  it('직접 추가한 형식은 입력을 검증하고 브라우저에만 저장한다', async () => {
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} />);
    const panel = await openFormats(user);
    const input = within(panel).getByLabelText('형식 직접 추가');
    await user.type(input, '한글'); await user.click(within(panel).getByRole('button', { name: '추가' }));
    expect(within(panel).getByRole('alert').textContent).toContain('영문과 숫자');
    await user.clear(input); await user.type(input, 'hwpx'); await user.click(within(panel).getByRole('button', { name: '추가' }));
    expect(within(panel).getByText('수동 추가')).toBeTruthy();
    expect(within(panel).getByRole('button', { name: '.hwpx 경로 만들기' })).toBeTruthy();
    expect(store.get('document-ops:manual-formats:v1')).toContain('HWPX');
    expect(onlyGets()).toBe(true);
  });
});

describe('설계 모드', () => {
  it('도형을 추가하고 연결 사이에 단계를 넣고, 지우면 앞뒤를 다시 잇고, 되돌릴 수 있다', async () => {
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} />);
    await user.click(screen.getByRole('button', { name: '설계' }));
    await user.click(screen.getByRole('button', { name: '작업 추가' }));
    expect(screen.getByRole('heading', { name: '새 작업' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /검증 \d/ })).toBeTruthy();

    fireEvent.click(screen.getByLabelText('문서 참조 연결 → 검색 인덱스 적재 연결'));
    const inserts = screen.getByText('중간에 단계 삽입').closest('section')!;
    await user.click(within(inserts as HTMLElement).getByRole('button', { name: /사람 검토/ }));
    expect(screen.getByRole('heading', { name: '사람 검토' })).toBeTruthy();
    expect(screen.queryByLabelText('문서 참조 연결 → 검색 인덱스 적재 연결')).toBeNull();

    await user.click(within(screen.getByRole('complementary', { name: '속성' })).getByRole('button', { name: /삭제/ }));
    expect(screen.getByLabelText('문서 참조 연결 → 검색 인덱스 적재 연결')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '되돌리기' }));
    expect(screen.queryByLabelText('문서 참조 연결 → 검색 인덱스 적재 연결')).toBeNull();
    expect(onlyGets()).toBe(true);
  });

  it('하위 흐름 페이지로 이동하고 자동 정렬 방향을 바꿀 수 있다', async () => {
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} />);
    await user.click(within(screen.getByRole('navigation', { name: '흐름 페이지' })).getByRole('button', { name: /PDF 문서/ }));
    expect(screen.getByRole('heading', { name: 'PDF 문서' })).toBeTruthy();
    expect(screen.getByText('OCR 인식')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '설계' }));
    await user.click(screen.getByRole('button', { name: '가로 자동 정렬' }));
    await waitFor(() => expect(JSON.parse(store.get('document-ops:flows:v3')!).flows.pdf.direction).toBe('LR'));
  });
});

describe('운영 모드', () => {
  it('단계 목록에서 상세를 열고 현재 흐름의 상태 집계에서 문서 추적에 접근한다', async () => {
    const simulator = new FlowSimulator(defaultLibrary(), 300);
    simulator.setRunning(false);
    const user = userEvent.setup();
    render(<PipelineStudio formats={[]} initialFormat="PDF" onOpenDocuments={() => {}} simulator={simulator} />);
    await user.click(screen.getByRole('button', { name: '단계 목록' }));
    const stages = within(screen.getByRole('region', { name: '처리 단계 목록' }));
    await user.click(stages.getByRole('button', { name: 'OCR 인식' }));
    expect(within(screen.getByRole('complementary', { name: '운영 상세' })).getByRole('heading', { name: 'OCR 인식' })).toBeTruthy();
    const metrics = within(screen.getByRole('group', { name: 'PDF 문서 상태 요약' }));
    await user.click(metrics.getByRole('button', { name: /^보류/ }));
    const dock = within(screen.getByRole('region', { name: '운영 기록' }));
    expect(dock.getByRole('tab', { name: /^문서 추적/, selected: true })).toBeTruthy();
    expect(dock.getByRole('button', { name: '보류', pressed: true })).toBeTruthy();
    expect(dock.getByText('PDF 문서', { exact: true })).toBeTruthy();
  });

  it('주의 단계에서 해당 노드로 이동하고 하위 흐름에서는 다른 흐름의 주의를 제외한다', async () => {
    const simulator = new FlowSimulator(defaultLibrary(), 0);
    simulator.pauseNode('overview::review', true);
    simulator.pauseNode('pdf::ocr', true);
    const user = userEvent.setup();
    render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} simulator={simulator} />);

    await user.click(screen.getByRole('button', { name: '주의 단계 2개' }));
    const panel = within(screen.getByRole('complementary', { name: '운영 상세' }));
    expect(panel.getByRole('button', { name: /품질 검토.*일시정지/ })).toBeTruthy();
    await user.click(panel.getByRole('button', { name: /OCR 인식.*PDF 문서.*일시정지/ }));
    expect(screen.getByRole('heading', { name: 'PDF 문서' })).toBeTruthy();
    expect(panel.getByRole('heading', { name: 'OCR 인식' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '주의 단계 1개' }));
    expect(panel.queryByRole('button', { name: /품질 검토/ })).toBeNull();
    await user.click(panel.getByRole('button', { name: /OCR 인식.*일시정지/ }));
    await user.click(panel.getByRole('button', { name: '재개' }));
    expect(screen.queryByRole('button', { name: /주의 단계/ })).toBeNull();
  });

  it('단계를 선택해 일시정지하고 보류 문서를 승인하며 실제 처리 요청을 보내지 않는다', async () => {
    const simulator = new FlowSimulator(defaultLibrary());
    const user = userEvent.setup(); render(<PipelineStudio formats={[]} onOpenDocuments={() => {}} simulator={simulator} />);
    expect(screen.getByRole('button', { name: '운영' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByText('품질 검토'));
    const panel = screen.getByRole('complementary', { name: '운영 상세' });
    expect(within(panel).getByRole('heading', { name: '품질 검토' })).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: /일시정지/ }));
    expect(within(panel).getByRole('button', { name: /재개/ })).toBeTruthy();
    expect(simulator.getSnapshot().metrics[`${OVERVIEW_ID}::review`].paused).toBe(true);
    const held = simulator.getSnapshot().metrics[`${OVERVIEW_ID}::review`].held;
    expect(held).toBeGreaterThan(0);
    await user.click(within(panel).getByRole('button', { name: new RegExp(`보류 ${held}건 승인`) }));
    expect(simulator.getSnapshot().metrics[`${OVERVIEW_ID}::review`].held).toBe(0);
    expect(simulator.getSnapshot().events[0].text).toContain('보류');
    expect(onlyGets()).toBe(true);
  });
});

describe('모의 운영 엔진', () => {
  it('형식별 라우팅을 따르고, 경로가 없는 형식은 확인 대기열에 모으며, 새 경로로 옮길 수 있다', () => {
    const library = defaultLibrary();
    const sim = new FlowSimulator(library, 300);
    expect(sim.getSnapshot().metrics[`${OVERVIEW_ID}::unrouted`].held).toBeGreaterThan(0);
    const heldExts = new Set(sim.getSnapshot().docs.filter(doc => doc.node === `${OVERVIEW_ID}::unrouted`).map(doc => doc.ext));
    for (const ext of heldExts) expect(['HEIC', 'TIFF']).toContain(ext);
    const { library: next, flowId } = addFormatRoute(library, 'HEIC');
    sim.setLibrary(next);
    const doc = sim.getSnapshot().docs.find(item => item.ext === 'HEIC' && item.node === `${OVERVIEW_ID}::unrouted`);
    expect(doc).toBeTruthy();
    sim.moveDoc(doc!.id, sim.entryOf(flowId)!);
    expect(sim.getSnapshot().docs.find(item => item.id === doc!.id)?.node.startsWith(`${flowId}::`)).toBe(true);
  });

  it('압축·첨부·내장 개체 단계는 상위 문서와 연결된 하위 문서를 만들어 형식 판별로 다시 보낸다', () => {
    const sim = new FlowSimulator(defaultLibrary(), 300);
    const { totals, docs, metrics } = sim.getSnapshot();
    expect(totals.derived).toBeGreaterThan(0);
    expect(totals.maxDepth).toBeGreaterThanOrEqual(1);
    const child = docs.find(doc => doc.depth > 0)!;
    expect(child.parent && child.parentName && child.root !== child.id).toBeTruthy();
    expect(metrics['zip::extract'].spawned + metrics['mail::attach'].spawned).toBeGreaterThan(0);
    expect(docs.filter(doc => doc.depth > 4)).toHaveLength(0);
  });

  it('실패가 쌓인 단계를 재시도하고, 우회하면 처리 없이 다음 단계로 넘긴다', () => {
    const library = defaultLibrary();
    const ocr = library.flows.image.nodes.find(node => node.id === 'ocr')!;
    ocr.data = { ...ocr.data, failRate: 1, retries: 0 };
    library.flows.image.edges = library.flows.image.edges.filter(edge => edge.data?.kind !== 'exception');
    const sim = new FlowSimulator(library, 300);
    const id = 'image::ocr';
    expect(sim.getSnapshot().metrics[id].failed).toBeGreaterThan(0);
    sim.setBypass(id, true);
    sim.retryFailed(id);
    expect(sim.getSnapshot().metrics[id].failed).toBe(0);
    expect(sim.getSnapshot().metrics[id].bypass).toBe(true);
  });
});
