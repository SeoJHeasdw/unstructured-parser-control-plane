import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveCompare } from '../compare/LiveCompare';
import { alignResults, highlightParts } from '../compare/diff';
import { ResultReview } from '../compare/ResultReview';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('파싱 차이', () => {
  it('순서와 반복을 비교하고 변경된 구절만 표시한다', () => {
    const rows = alignResults(['헤더', '반복', '반복', '합계', '검토'], ['헤더', '반복', '검토', '합계']);
    expect(rows.filter(row => row.kind !== 'same')).toHaveLength(3);
    expect(rows.filter(row => row.kind === 'removed').some(row => row.left?.text === '반복')).toBe(true);
    const [before, after] = highlightParts('검사 완료. 공정 결과는 표를 참조.', '검사 완료.');
    expect(before.filter(part => part.changed).map(part => part.text).join('')).toContain('공정 결과');
    expect(after.every(part => !part.changed)).toBe(true);
  });

  it('표 셀과 수치·단위를 구별하고 검수 근거 위치로 이동한다', async () => {
    const onLocation = vi.fn();
    const user = userEvent.setup();
    const result = '| SOP-QC-0040 Rev.5 | 7.2 mg | 결과 확인 |';
    const different = '| SOP-QC-0040 Rev.6 | 7.8 g | |';
    const changed = alignResults([result], [different])[0];
    expect(changed.notes?.map(note => note.label)).toEqual(['표 셀 누락', '문서번호·Rev', '수치·단위']);

    render(<ResultReview original={<div>원문</div>} showOriginal showAlternative highlight onLocation={onLocation}
      baseline={{ text: '| 검사 | 7.2 mg |', meta: null, locations: [{ start_line: 1, end_line: 1, page: null, sheet: '시험', row: 7, column: 2, columns: 2 }] }}
      candidate={{ text: '| 검사 | 7.8 g |', meta: null }} />);
    await user.click(screen.getByRole('button', { name: '다음 차이' }));
    expect(screen.getByText('수치·단위', {exact: true}).parentElement?.textContent).toContain('7.2 mg → 7.8 g');
    expect(onLocation).toHaveBeenCalledWith({ page: null, sheet: '시험', cell: 'C7' });
    expect(screen.getByRole('button', { name: '시험!C7' })).toBeTruthy();
  });

  it('동일 원본의 두 저장 실행을 조회하고 순서를 바꾼다', async () => {
    const previous = { run_id: 'previous', parser: 'python-text', parser_version: '1', ocr_enabled: null, completed_at: null, is_latest: false };
    const latest = { ...previous, run_id: 'latest', parser_version: '2', is_latest: true };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const body = url.endsWith('/source-preview?') ? { kind: 'text', text: '평가 원본', truncated: false }
        : url.endsWith('/runs') ? { runs: [latest, previous] }
        : url.endsWith('/runs/latest') ? { ...latest, markdown: '7.8 mg', warnings: [], locations: [] }
        : url.endsWith('/runs/previous') ? { ...previous, markdown: '7.2 mg', warnings: [], locations: [] }
        : { documents: [{ id: 'doc', name: 'test.txt', format: 'TXT', status: 'completed' }] };
      return { ok: true, json: async () => body };
    }));
    const user = userEvent.setup();
    render(<LiveCompare active selectedId="doc" onChange={() => {}} sourceTabs={null} switches={null}
      options={{showOriginal: true, showAlternative: true, highlight: true}} onShowOriginal={() => {}} />);
    await screen.findByText('차이 1곳');
    expect(screen.getByText('평가 원본')).toBeTruthy();
    const baseline = within(screen.getByRole('region', { name: '이전 실행' }));
    expect(baseline.getByText('python-text · 1')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '이전과 현재 바꾸기' }));
    await waitFor(() => expect(within(screen.getByRole('region', {name: '이전 실행'})).getByText('python-text · 2')).toBeTruthy());
  });

  it('출력의 한 줄이 PDF 두 페이지를 잇는 경우 변경된 구절의 페이지를 연다', async () => {
    const onLocation = vi.fn(), user = userEvent.setup();
    const page = { start_line: 1, end_line: 1, sheet: null, row: null, column: null, columns: null };
    render(<ResultReview original={<div>원문</div>} showOriginal showAlternative highlight onLocation={onLocation}
      baseline={{ text: 'Page one. Page two.', meta: null, locations: [
        { ...page, page: 1, start_offset: 0, end_offset: 9 }, { ...page, page: 2, start_offset: 10, end_offset: 19 },
      ] }}
      candidate={{ text: 'Page one. Page changed.', meta: null }} />);
    await user.click(screen.getByRole('button', { name: '다음 차이' }));
    expect(onLocation).toHaveBeenCalledWith({ page: 2, sheet: null });
    expect(screen.getByRole('button', { name: '원문 2쪽' })).toBeTruthy();
  });
});
