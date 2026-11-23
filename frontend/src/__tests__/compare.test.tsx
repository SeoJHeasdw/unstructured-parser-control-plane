import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CompareView } from '../CompareView';
import { useState } from 'react';
import type { LiveDoc } from '../api/live';
import { DocumentRuns } from '../compare/LiveCompare';
import { alignResults, highlightParts } from '../compare/diff';
import { ResultReview } from '../compare/ResultReview';
import sample from '../../../mock-data/data.json';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderSample(selectedId: string) {
  return render(<CompareView docs={sample.documents} selectedId={selectedId} onChange={vi.fn()} onOpenDoc={vi.fn()} />);
}

describe('비교 원본 파일', () => {
  it('예시 파싱문을 원본에 복제하지 않고 실제 PDF 파일을 열며 변경 근거 페이지를 확대한다', async () => {
    const user = userEvent.setup();
    renderSample('DOC-0842');
    const original = within(screen.getByRole('region', { name: '원본 문서' }));
    expect(original.getByTitle('PDF 원문').getAttribute('src')).toContain('bmr-2026-0842');
    expect(original.queryByText(/문서별 기록|공정별 기록/)).toBeNull();
    await user.click(screen.getByRole('button', {name:'실행 비교'}));
    await user.click(screen.getByRole('button', { name: '다음 차이' }));
    await user.click(screen.getByRole('button', { name: '원문 3쪽' }));
    expect(original.getByTitle('PDF 원문').getAttribute('src')).toContain('#page=3');
    await user.click(original.getByRole('button', { name: '크게 보기' }));
    const expanded = within(screen.getByRole('dialog', { name: '원본 문서' }));
    expect(expanded.getByTitle('PDF 원문').getAttribute('src')).toContain('#page=3');
    await user.keyboard('{Escape}');
    expect(original.getByTitle('PDF 원문').getAttribute('src')).toContain('#page=3');
  });

  it('예시 XLSX의 원본 셀로 이동하고 같은 워크북을 다운로드한다', async () => {
    const user = userEvent.setup();
    renderSample('DOC-0841');
    const original = within(screen.getByRole('region', { name: '원본 문서' }));
    const address = original.getByRole('textbox', { name: '원본 셀 주소' });
    await user.clear(address);
    await user.type(address, 'b12');
    await user.click(original.getByRole('button', { name: '이동' }));
    expect(original.getByRole('cell', { name: 'SOP-QC-0040 Rev.5 참조' }).classList.contains('is-cell')).toBe(true);
    const download = original.getByRole('link', { name: '원본 다운로드' });
    expect(download.getAttribute('href')).toContain('.xlsx');
    expect(download.getAttribute('download')).toBe('설비점검_관리대장_2026.xlsx');
  });
});

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

    render(<ResultReview onEvidence={onLocation}
      baseline={{ text: '| 검사 | 7.2 mg |', meta: null, locations: [{ start_line: 1, end_line: 1, page: null, sheet: '시험', row: 7, column: 2, columns: 2 }] }}
      candidate={{ text: '| 검사 | 7.8 g |', meta: null }} />);
    await user.click(screen.getByRole('button', { name: '다음 차이' }));
    expect(screen.getByText('수치·단위', {exact: true}).parentElement?.textContent).toContain('7.2 mg → 7.8 g');
    expect(onLocation).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '시험!C7' }));
    expect(onLocation).toHaveBeenCalledWith({ location: { page: null, sheet: '시험', cell: 'C7' }, side: 'left', line: 1 });
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
    function Review() {
      const [mode,setMode] = useState<'source'|'runs'>('source');
      return <DocumentRuns active doc={{id:'doc', name:'test.txt', format:'TXT', status:'completed'} as LiveDoc} mode={mode} onMode={setMode}/>;
    }
    render(<Review/>);
    expect(await screen.findByText('평가 원본')).toBeTruthy();
    await user.click(screen.getByRole('button', {name:'실행 비교'}));
    await screen.findByText('차이 1곳');
    await user.click(screen.getByText('비교할 실행 선택'));
    const baseline = within(screen.getByRole('region', { name: '이전 실행' }));
    expect(baseline.getByText('python-text · 1')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '이전과 현재 바꾸기' }));
    await waitFor(() => expect(within(screen.getByRole('region', {name: '이전 실행'})).getByText('python-text · 2')).toBeTruthy());
  });

  it.each([0, 1])('성공본 %i개로 직접 들어오면 가능한 검수만 표시한다', async count => {
    const run = {run_id:'one', parser:'text', parser_version:'1', warnings:[], locations:[], markdown:'저장된 본문'};
    vi.stubGlobal('fetch', vi.fn(async (path: string) => ({ok:true, json:async () =>
      path.endsWith('/runs') ? {runs:count ? [run] : []} : path.includes('source-preview') ? {kind:'text', text:'원본', truncated:false} : run})));
    render(<DocumentRuns active mode="runs" onMode={vi.fn()} doc={{id:'demo', format:'TXT', name:'one.txt'} as LiveDoc}/>);
    if (!count) {
      expect(await screen.findByText('성공한 파싱 실행이 없습니다')).toBeTruthy();
    } else {
      expect(await screen.findByText('저장된 본문')).toBeTruthy();
      expect(screen.getByRole('button', {name:'실행 비교'})).toHaveProperty('disabled', true);
      expect(screen.getByRole('button', {name:'원문 대조'}).getAttribute('aria-pressed')).toBe('true');
    }
  });

  it('이전 실행의 뒤쪽에만 남은 근거를 열고 같은 차이로 돌아온다', async () => {
    const common = Array.from({length:121}, (_, i) => '문단 ' + i).join('\n');
    const before = {run_id:'old', markdown:common + '\n5 mg', locations:[{start_line:122, end_line:122, page:3}], warnings:[]};
    const after = {run_id:'new', markdown:common + '\n7 mg', locations:[], warnings:[]};
    vi.stubGlobal('fetch', vi.fn(async (path: string) => ({ok:true, json:async () =>
      path.endsWith('/runs') ? {runs:[after,before]} : path.endsWith('/old') ? before : after})));
    function Review() {
      const [mode,setMode] = useState<'runs'|'source'>('runs');
      return <DocumentRuns active doc={{id:'demo',format:'PDF',name:'source.pdf'} as LiveDoc} mode={mode} onMode={setMode}/>;
    }
    const user = userEvent.setup();
    render(<Review/>);
    await user.click(await screen.findByRole('button',{name:'다음 차이'}));
    const evidence = screen.getByRole('button',{name:'원문 3쪽'});
    await user.click(evidence);
    expect(screen.getByRole('combobox', {name:'성공 실행'})).toHaveProperty('value','old');
    expect(document.querySelector('.source-line.is-evidence')?.textContent).toContain('5 mg');
    expect(screen.getByTitle('PDF 원문').getAttribute('src')).toContain('#page=3');
    await user.click(screen.getByRole('button',{name:'실행 비교'}));
    await waitFor(() => expect(document.activeElement).toBe(evidence));
  });

  it('출력의 한 줄이 PDF 두 페이지를 잇는 경우 변경된 구절의 페이지를 연다', async () => {
    const onLocation = vi.fn(), user = userEvent.setup();
    const page = { start_line: 1, end_line: 1, sheet: null, row: null, column: null, columns: null };
    render(<ResultReview onEvidence={onLocation}
      baseline={{ text: 'Page one. Page two.', meta: null, locations: [
        { ...page, page: 1, start_offset: 0, end_offset: 9 }, { ...page, page: 2, start_offset: 10, end_offset: 19 },
      ] }}
      candidate={{ text: 'Page one. Page changed.', meta: null }} />);
    await user.click(screen.getByRole('button', { name: '다음 차이' }));
    await user.click(screen.getByRole('button', { name: '원문 2쪽' }));
    expect(onLocation).toHaveBeenCalledWith({ location: { page: 2, sheet: null }, side: 'left', line: 1 });
    expect(screen.getByRole('button', { name: '원문 2쪽' })).toBeTruthy();
  });
});
