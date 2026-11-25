import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LiveWorkspace from '../LiveWorkspace';
import ParserWorkspace from '../ParserWorkspace';
import { StructurePanel } from '../StructurePanel';
import { parseDocNumber } from '../LiveDocumentView';

/* 합성 문서만 쓴다. seq가 없는 문서는 예전 서버의 응답이다. */
type Doc = { id: string; name: string; format: string; size_bytes: number; status: string; created_at: string; updated_at: string; parser: string | null; error: string | null; error_code?: string | null; seq?: number | null };
const base = { size_bytes: 1024, created_at: '2026-11-20T00:00:00Z', updated_at: '2026-11-20T00:00:00Z', parser: null, error: null };
const checklist: Doc = { ...base, id: 'a1', name: '점검표.pdf', format: 'PDF', status: 'uploaded', seq: 12 };
const yearly: Doc = { ...base, id: 'b2', name: '보고서-2012.docx', format: 'DOCX', status: 'completed', seq: 3 };
const legacy: Doc = { ...base, id: 'c3', name: '메모.txt', format: 'TXT', status: 'uploaded' };
const photo: Doc = { ...base, id: 'd4', name: '현장사진.png', format: 'PNG', status: 'failed', error_code: 'no_text', error: '추출된 글자가 없습니다.', seq: 120 };
const scan: Doc = { ...base, id: 'e5', name: '스캔본.pdf', format: 'PDF', status: 'failed', error_code: 'no_text', error: '추출된 글자가 없습니다.', seq: 7 };
const lowerJpeg: Doc = { ...photo, id: 'f6', name: '빈벽.jpeg', format: 'jpeg', seq: 8 };
const NOTE = '이미지에서 글자를 찾지 못했습니다. 글자 없는 사진이면 정상이고, 글자가 보이는 이미지라면 OCR이 놓친 것입니다.';

const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
function serve(docs: Doc[], extra: (path: string) => Response | undefined = () => undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method && init.method !== 'GET') throw new Error('예상하지 못한 변경 요청 ' + path);
    const handled = extra(path);
    if (handled) return handled;
    if (path === '/api/live/documents') return json({ documents: docs });
    const doc = docs.find(item => path === `/api/live/documents/${item.id}`);
    if (doc) return json(doc);
    if (path.endsWith('/result')) return json({ detail: '완료된 파싱 결과가 없습니다.' }, 409);
    throw new Error('예상하지 못한 호출 ' + path);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const rows = () => within(document.querySelector('.live-list') as HTMLElement).queryAllByRole('link');
const names = () => rows().map(row => row.querySelector('.lw-file-copy strong')?.textContent);

beforeEach(() => { history.replaceState(null, '', '/'); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('문서 번호(D번호)', () => {
  it('번호 모양의 검색어를 읽는다', () => {
    expect(['D12', 'd12', 'D-12', 'd - 12', '#12', '12', ' 012 '].map(parseDocNumber)).toEqual([12, 12, 12, 12, 12, 12, 12]);
    expect(['D', 'D12a', '보고서', 'x12', ''].map(parseDocNumber)).toEqual([null, null, null, null, null]);
  });

  it('목록 행에 D번호를 보이고, 번호가 없는 예전 문서는 번호 없이 보인다', async () => {
    serve([checklist, yearly, legacy]);
    render(<LiveWorkspace />);
    await waitFor(() => expect(rows()).toHaveLength(3));
    const [first, second, third] = rows();
    expect(first.querySelector('.lw-seq')?.textContent).toBe('D12');
    expect(second.querySelector('.lw-seq')?.textContent).toBe('D3');
    expect(third.querySelector('.lw-seq')).toBeNull();
    expect(third.textContent).not.toMatch(/D\d/);
  });

  it('D12·d12·D-12·12로 문서 번호를 찾고, 이름 검색도 그대로 맞는다', async () => {
    const user = userEvent.setup();
    serve([checklist, yearly, legacy, photo]);
    render(<LiveWorkspace />);
    await waitFor(() => expect(rows()).toHaveLength(4));
    const search = screen.getByRole('textbox', { name: '실제 문서 검색' });
    expect(search.getAttribute('placeholder')).toContain('D번호');
    for (const term of ['D12', 'd12', 'D-12']) {
      await user.clear(search); await user.type(search, term);
      expect(names()).toEqual(['점검표.pdf']);
    }
    await user.clear(search); await user.type(search, '12');
    expect(names()).toEqual(['점검표.pdf', '보고서-2012.docx']);
    await user.clear(search); await user.type(search, 'D120');
    expect(names()).toEqual(['현장사진.png']);
    await user.clear(search); await user.type(search, 'docx');
    expect(names()).toEqual(['보고서-2012.docx']);
    await user.clear(search); await user.type(search, 'D99');
    expect(screen.getByText('조건에 맞는 문서가 없습니다')).toBeTruthy();
  });

  it('문서 상세 머리에 D번호를 보인다', async () => {
    serve([checklist]);
    render(<LiveWorkspace route={{ page: 'live', doc: checklist.id }} />);
    expect(await screen.findByRole('heading', { level: 1, name: checklist.name })).toBeTruthy();
    expect(document.querySelector('.lw-subline .lw-seq')?.textContent).toBe('D12');
  });
});

describe('글자 없음', () => {
  it('글자를 찾지 못한 이미지는 실패가 아니라 글자 없음으로 보이고, 다른 실패는 그대로다', async () => {
    const user = userEvent.setup();
    serve([photo, scan, lowerJpeg]);
    render(<LiveWorkspace />);
    await waitFor(() => expect(rows()).toHaveLength(3));
    const [photoRow, scanRow, jpegRow] = rows();
    expect(within(photoRow).getByText('글자 없음')).toBeTruthy();
    expect(within(photoRow).queryByText('처리 실패')).toBeNull();
    expect(photoRow.textContent).toContain(NOTE);
    expect(within(jpegRow).getByText('글자 없음')).toBeTruthy();
    expect(within(scanRow).getByText('처리 실패')).toBeTruthy();
    expect(within(scanRow).getByText(/추출할 수 있는 텍스트를 찾지 못했습니다/)).toBeTruthy();
    const filter = screen.getByRole('combobox', { name: '처리 상태 필터' });
    expect(within(filter).getByRole('option', { name: '실패 · 미지원 (1)' })).toBeTruthy();
    expect(within(filter).getByRole('option', { name: '글자 없음 (이미지) (2)' })).toBeTruthy();
    await user.selectOptions(filter, 'attention');
    expect(names()).toEqual(['스캔본.pdf']);
    await user.selectOptions(filter, 'no_text');
    expect(names()).toEqual(['현장사진.png', '빈벽.jpeg']);
  });

  it('상세에서 중립 설명을 한 줄로 보이고 실패 경고를 띄우지 않는다', async () => {
    serve([photo]);
    render(<LiveWorkspace route={{ page: 'live', doc: photo.id }} />);
    expect(await screen.findByRole('heading', { level: 1, name: photo.name })).toBeTruthy();
    const head = document.querySelector('.lw-subline') as HTMLElement;
    expect(within(head).getByText('글자 없음')).toBeTruthy();
    expect(within(head).queryByText('처리 실패')).toBeNull();
    expect(screen.getByText(NOTE)).toBeTruthy();
    expect(document.querySelector('.lw-message.is-error')).toBeNull();
    expect(screen.getByRole('button', { name: '다시 파싱 실행' })).toBeTruthy();
  });

  it('스캔 PDF의 글자 없음은 실패 경고를 그대로 보인다', async () => {
    serve([scan]);
    render(<LiveWorkspace route={{ page: 'live', doc: scan.id }} />);
    expect(await screen.findByRole('heading', { level: 1, name: scan.name })).toBeTruthy();
    expect(within(document.querySelector('.lw-subline') as HTMLElement).getByText('처리 실패')).toBeTruthy();
    expect(document.querySelector('.lw-message.is-error')?.textContent).toContain('추출할 수 있는 텍스트를 찾지 못했습니다.');
    expect(screen.queryByText(NOTE)).toBeNull();
  });
});

describe('파서 플로우의 OCR 모델', () => {
  const catalog = { routes: { PNG: 'ocr-model', PDF: 'docling' }, docling_installed: true, pdf_model_directory: true, ocr_enabled: true };
  it('연결된 OCR 모델의 ID를 함께 보이고, 글자 없는 이미지는 실패 목록에서 뺀다', async () => {
    serve([photo, { ...photo, id: 'g7', name: '손상.png', error_code: 'parse_failed', seq: 9 }], path => path === '/api/live/parsers'
      ? json({ ...catalog, ocr_models_found: true, ocr_model: { label: 'OCR 모델', model_id: 'PaddleOCR-VL-1.5', mode: 'region', configured: true } }) : undefined);
    render(<ParserWorkspace format="PNG" onNavigate={vi.fn()} />);
    expect(await screen.findByText('OCR 모델 연결됨')).toBeTruthy();
    expect(screen.getByText('PaddleOCR-VL-1.5')).toBeTruthy();
    const docs = await screen.findByRole('region', { name: /PNG 문서/ });
    await waitFor(() => expect(within(docs).getByText('현장사진.png')).toBeTruthy());
    expect(within(docs).getByText('D120')).toBeTruthy();
    expect(within(docs).getByText('글자 없음')).toBeTruthy();
    expect(within(docs).getByRole('button', { name: /실패 · 미지원 1/ })).toBeTruthy();
  });

  it('PDF 모델이 일부만 있으면 누락 파일과 설치 방법을 보여 준다', async () => {
    const missing = 'tableformer/accurate/tm_config.json';
    serve([], path => path === '/api/live/parsers' ? json({ ...catalog, ocr_models_found: false,
      pdf_models_ready: false, pdf_missing_files: [missing] }) : undefined);
    render(<ParserWorkspace format="PDF" onNavigate={vi.fn()} />);
    const summary = await screen.findByText('PDF 모델 없음 · 누락 1개 · 글자 층만 읽는 중');
    await userEvent.setup().click(summary);
    expect(screen.getByText(missing)).toBeTruthy();
    expect(screen.getByText('python scripts/prepare-offline.py --models-only')).toBeTruthy();
    expect(screen.getByText('setup.cmd --models <ZIP 경로>')).toBeTruthy();
    expect(screen.queryByText('PDF 모델 파일 확인')).toBeNull();
  });

  it('OCR 모델이 없으면 미연결만 보인다', async () => {
    serve([], path => path === '/api/live/parsers' ? json({ ...catalog, ocr_models_found: false, ocr_model: { label: 'OCR 모델', model_id: '', mode: 'region', configured: false } }) : undefined);
    render(<ParserWorkspace format="PNG" onNavigate={vi.fn()} />);
    expect(await screen.findByText('OCR 모델 미연결')).toBeTruthy();
    expect(document.querySelector('.pr-ocr-model')).toBeNull();
  });
});

describe('XLSM(매크로 사용 통합문서)', () => {
  const book: Doc = { ...base, id: 'x9', name: '점검기록.xlsm', format: 'XLSM', status: 'completed', seq: 31 };
  it('파서 플로우에서 Docling 워크시트 경로와 매크로 미실행을 보여 준다', async () => {
    serve([book], path => path === '/api/live/parsers' ? json({ routes: { XLSM: 'docling' }, docling_installed: true, pdf_model_directory: true, ocr_enabled: true, ocr_models_found: false }) : undefined);
    render(<ParserWorkspace format="XLSM" onNavigate={vi.fn()} />);
    expect(await screen.findByText('워크시트 추출 · 매크로 미실행')).toBeTruthy();
    expect(screen.getByText('Docling 설치됨')).toBeTruthy();
  });

  it('구조 분석에서 매크로 모듈 수와 자동 실행을 표시하고 매크로 속 경로를 링크 후보로 보인다', async () => {
    const root = { name: book.name, ext: 'XLSM', size: 2048, kind: 'file', location: '', detected: 'xlsx', flags: ['macro', 'macro-autorun'],
      stats: { sheets: 1, macro: { modules: 2, code_modules: 1, code_lines: 5, auto_run: ['Auto_Open'], stripped_modules: 0, items: [] } },
      links: [{ kind: 'unc-path', target: '\\\\fs01\\qc\\점검표.xlsx', location: '매크로 점검자동화 5행', evidence: '' }], children: [], hash: null, duplicate_of: null };
    serve([book], path => path === '/api/live/documents/x9/structure' ? json({ id: book.id, name: book.name, format: 'XLSM', inspected_at: '2026-11-25T00:00:00Z', root,
      summary: { documents: 1, derived: 0, max_depth: 0, links: 1, by_child_kind: {}, by_link_kind: { 'unc-path': 1 }, flags: { macro: 1, 'macro-autorun': 1 }, detected: { xlsx: 1 } } }) : undefined);
    render(<StructurePanel doc={{ ...book, size_bytes: 2048 } as never} />);
    expect(await screen.findByText('매크로 모듈 1 · 5줄')).toBeTruthy();
    expect(screen.getAllByText(/열 때 자동 실행 매크로/).length).toBeGreaterThan(0);
    await userEvent.setup().click(screen.getByRole('tab', { name: /링크 · 참조/ }));
    expect(screen.getByText('매크로 점검자동화 5행')).toBeTruthy();
  });
});
