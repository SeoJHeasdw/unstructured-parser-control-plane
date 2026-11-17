import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowRightLeft, ExternalLink, RefreshCw } from 'lucide-react';
import { getParseRun, getSourcePreview, listLiveDocuments, listParseRuns, liveSourceUrl } from '../api/live';
import type { LiveDoc, ParseRun, StoredParseRun } from '../api/live';
import { ResultReview } from './ResultReview';
import { RunSummary } from './RunSummary';
import type { RunSide } from './RunSummary';
import type { ResultPane, ReviewLocation } from './ResultReview';

type Request<T> = (signal: AbortSignal) => Promise<T>;
function useLoad<T>(request: Request<T>, enabled: boolean) {
  const [snapshot, setSnapshot] = useState<{ request: Request<T>; data?: T; error?: string }>();
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    request(controller.signal).then(data => {
      if (!controller.signal.aborted) setSnapshot({ request, data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setSnapshot({ request, error: error instanceof Error ? error.message : '불러오지 못했어요.' });
    });
    return () => controller.abort();
  }, [enabled, request]);
  return snapshot?.request === request ? snapshot : undefined;
}

const dateFormat = new Intl.DateTimeFormat('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
function runLabel(run: ParseRun) {
  const date = run.completed_at ? new Date(run.completed_at) : null;
  return `${date && Number.isFinite(+date) ? dateFormat.format(date) : '시간 미기록'} · ${run.run_id.slice(0, 6)}`;
}

type CompareOptions = { showOriginal: boolean; showAlternative: boolean; highlight: boolean };
type Props = {
  active: boolean; selectedId: string; onChange: (id: string) => void; sourceTabs: ReactNode; switches: ReactNode;
  options: CompareOptions; onShowOriginal: () => void;
};

export function LiveCompare({ active, selectedId, onChange, sourceTabs, switches, options, onShowOriginal }: Props) {
  const [refresh, setRefresh] = useState(0);
  const request = useCallback((signal: AbortSignal) => listLiveDocuments(signal), [refresh]);
  const docs = useLoad(request, active);
  const doc = docs?.data?.find(item => item.id === selectedId) ?? docs?.data?.[0];
  return <>
    <section className="panel compare-controls">
      <div className="compare-controls-start">{sourceTabs}
        <div className="compare-document">
          <label htmlFor="compare-live-document">비교 문서</label>
          <select id="compare-live-document" value={doc?.id ?? ''} title={doc?.name} disabled={!doc} onChange={event => onChange(event.target.value)}>
            {!doc && <option value="">{docs ? '문서 없음' : '불러오는 중…'}</option>}
            {docs?.data?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        <button type="button" className="button-quiet compare-refresh" aria-label="실행 목록 새로고침" title="실행 목록 새로고침" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15} /></button>
      </div>
      <div className="compare-controls-end">{switches}</div>
    </section>
    {doc ? <DocumentRuns key={doc.id} doc={doc} active={active} refresh={refresh} options={options} onShowOriginal={onShowOriginal} />
      : <div className="panel empty-view" role={docs?.error ? 'alert' : 'status'}>{docs?.error ?? (docs ? '실제 파일 처리에서 원본을 추가하면 여기서 실행 결과를 비교할 수 있어요.' : '실제 문서를 불러오는 중…')}</div>}
  </>;
}

function DocumentRuns({ doc, active, refresh, options, onShowOriginal }: {
  doc: LiveDoc; active: boolean; refresh: number; options: CompareOptions; onShowOriginal: () => void;
}) {
  const [selection, setSelection] = useState<{ left: string; right: string }>();
  const [location, setLocation] = useState<ReviewLocation>();
  const { id } = doc;
  const loadRuns = useCallback((signal: AbortSignal) => listParseRuns(id, signal), [id, refresh]);
  const available = useLoad(loadRuns, active);
  const runs = available?.data ?? [];
  const left = selection?.left ?? runs[runs.length > 1 ? 1 : 0]?.run_id ?? '';
  const right = selection?.right ?? (runs.length > 1 ? runs[0].run_id : '');
  const loadLeft = useCallback((signal: AbortSignal) => getParseRun(id, left, signal), [id, left]);
  const loadRight = useCallback((signal: AbortSignal) => getParseRun(id, right, signal), [id, right]);
  const baseline = useLoad(loadLeft, active && !!left);
  const candidate = useLoad(loadRight, active && !!right);

  function change(next: { left: string; right: string }) {
    setSelection(next);
    setLocation(undefined);
  }

  function picker(side: 'left' | 'right') {
    const name = side === 'left' ? '이전 실행' : '현재 실행';
    const value = side === 'left' ? left : right;
    const other = side === 'left' ? right : left;
    return <div className="compare-run-select">
      <label className="compare-sr" htmlFor={`compare-run-${side}`}>{name}</label>
      <select id={`compare-run-${side}`} value={value} disabled={!runs.length}
        onChange={event => change({ left, right, [side]: event.target.value })}>
        <option value="">{runs.length ? '실행 선택' : '성공한 실행 없음'}</option>
        {runs.map(run => <option key={run.run_id} value={run.run_id} disabled={run.run_id === other}>{runLabel(run)}</option>)}
      </select>
      {side === 'right' && left && right && <button className="button-quiet" title="이전과 현재 바꾸기" aria-label="이전과 현재 바꾸기"
        onClick={() => change({ left: right, right: left })}><ArrowRightLeft size={15} /></button>}
    </div>;
  }

  const error = available?.error ?? baseline?.error ?? candidate?.error;
  const loading = !available || (!!left && !baseline) || (!!right && !candidate);
  if (available?.error) return <div className="panel empty-view" role="alert">
    {available.error === 'Not Found' ? '파싱 실행 이력을 불러올 수 없어요. 최신 코드로 로컬 백엔드를 다시 시작해 주세요.' : available.error}
  </div>;
  return <>
    {(error || loading || runs.length < 2) && <p className="compare-state" role={error ? 'alert' : 'status'}>
      {error ?? (loading ? '실행 결과를 불러오는 중…' : runs.length ? '한 번 더 파싱하면 이 결과와 비교할 수 있어요.' : doc.error || '이 문서에 성공한 파싱 실행이 없습니다.')}
    </p>}
    <RunSummary before={runSide(baseline?.data)} after={runSide(candidate?.data)} />
    <ResultReview key={`${left}/${right}`} {...options}
      baseline={runPane(baseline?.data, doc)} candidate={runPane(candidate?.data, doc)}
      baselineControl={picker('left')} candidateControl={picker('right')}
      onLocation={(value, reveal) => { setLocation(value); if (reveal) onShowOriginal(); }}
      original={<SourceOriginal doc={doc} active={active && options.showOriginal} location={location} onLocation={setLocation} />} />
  </>;
}

function runSide(run: StoredParseRun | undefined): RunSide | undefined {
  if (!run) return;
  return { text: run.markdown, label: [runLabel(run), run.parser_version].filter(Boolean).join(' · '), durationMs: run.duration_ms ?? null, warnings: run.warnings.length, locations: run.locations };
}

function runPane(run: StoredParseRun | undefined, doc: LiveDoc): ResultPane | undefined {
  if (!run) return;
  const ocr = run.ocr_enabled === null ? (doc.format === 'PDF' ? 'OCR 설정 미기록' : '') : run.ocr_enabled ? 'OCR 사용' : 'OCR 미적용';
  const desc = [run.parser || '파서 미기록', run.parser_version, ocr].filter(Boolean).join(' · ');
  return { text: run.markdown, locations: run.locations, meta: <div className="compare-run-meta">
    <p>{desc}{run.is_latest && doc.status !== 'completed' && ' · 이전 성공본'}</p>
    {run.warnings.map(warning => <p key={warning} className="compare-warning">{warning}</p>)}
  </div> };
}

function SourceOriginal({ doc, active, location, onLocation }: {
  doc: LiveDoc; active: boolean; location?: ReviewLocation; onLocation: (location: ReviewLocation) => void;
}) {
  const { id, format } = doc;
  const href = liveSourceUrl(id);
  const pdf = format === 'PDF';
  const sheet = location?.sheet ?? undefined, cell = location?.cell;
  const canPreview = ['TXT', 'LOG', 'CSV', 'MD', 'XLSX'].includes(format);
  const loadPreview = useCallback((signal: AbortSignal) => getSourcePreview(id, signal, sheet, cell), [id, sheet, cell]);
  const preview = useLoad(loadPreview, active && canPreview);
  const data = preview?.data;

  return <section className="panel compare-original">
    <header><h2>원문 미리보기</h2>
      <a className="button-quiet" href={href} target="_blank" rel="noreferrer">{pdf ? '원본 열기' : '원본 파일'} <ExternalLink size={13} /></a>
    </header>
    {pdf && <iframe key={location?.page ?? 1} title="PDF 원문" src={`${href}#page=${location?.page ?? 1}`} />}
    {data?.kind === 'sheet' && <div className="compare-sheet">
      <div className="compare-sheet-selector"><label htmlFor="source-sheet">시트</label>
        <select id="source-sheet" value={data.sheet} onChange={event => onLocation({ page: null, sheet: event.target.value, cell: 'A1' })}>
          {data.sheets.map(name => <option key={name}>{name}</option>)}
        </select><span>{data.cell}</span>
      </div>
      <div className="compare-sheet-scroll"><table>
        <thead><tr><td />{data.columns.map(column => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{data.rows.map((row, index) => <tr key={index}><th scope="row">{data.first_row + index}</th>
          {row.map((value, col) => <td key={col} className={data.cell === `${data.columns[col]}${data.first_row + index}` ? 'is-cell' : ''} title={value}>{value}</td>)}
        </tr>)}</tbody>
      </table></div>
    </div>}
    {data?.kind === 'text' && <div className="compare-paper"><pre>{data.text || '빈 원문입니다.'}</pre>{data.truncated && <p>원문의 처음 60,000자</p>}</div>}
    {!pdf && !data && <div className="compare-paper"><p>{canPreview ? preview?.error ?? '원문을 불러오는 중…' : '원본 파일을 열어 내용을 확인하세요.'}</p></div>}
  </section>;
}
