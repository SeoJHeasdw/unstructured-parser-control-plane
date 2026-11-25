import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowRightLeft, FileSearch, TriangleAlert } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { getParseRun, getSourcePreview, listParseRuns, liveSourceUrl } from '../api/live';
import type { LiveDoc, ParseRun, StoredParseRun } from '../api/live';
import { ReviewDesk } from './ReviewDesk';
import type { ReviewMode } from '../navigation';
import { RunSummary } from './RunSummary';
import { OriginalPane, PdfSource, TextSource, WorksheetSource } from './SourceViewer';
import type { RunSide } from './RunSummary';
import type { ResultPane, ReviewLocation } from './ResultReview';

// DOCX·PPTX 원본 그리기는 큰 라이브러리(docx-preview·JSZip)를 쓰므로 필요할 때만 불러온다.
const OfficeSource = lazy(() => import('./OfficeSource'));
const OFFICE: Readonly<Record<string, 'docx' | 'pptx'>> = Object.freeze({ DOCX: 'docx', PPTX: 'pptx' });

type Request<T> = (signal: AbortSignal) => Promise<T>;
function useLoad<T>(request: Request<T>, enabled: boolean, revision = 0) {
  const [snapshot, setSnapshot] = useState<{ request: Request<T>; revision: number; data?: T; error?: string }>();
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    request(controller.signal).then(data => {
      if (!controller.signal.aborted) setSnapshot({ request, revision, data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setSnapshot(previous => ({ request, revision, data: previous?.request === request ? previous.data : undefined, error: error instanceof Error ? error.message : '불러오지 못했어요.' }));
    });
    return () => controller.abort();
  }, [enabled, request, revision]);
  return snapshot?.request === request ? { ...snapshot, pending: snapshot.revision !== revision } : undefined;
}

const dateFormat = new Intl.DateTimeFormat('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
function runLabel(run: ParseRun) {
  const date = run.completed_at ? new Date(run.completed_at) : null;
  return `${date && Number.isFinite(+date) ? dateFormat.format(date) : '시간 미기록'} · ${run.run_id.slice(0, 6)}`;
}

export function CompareState({ icon: Icon = FileSearch, title, message, actions, tone = 'neutral' }: {
  icon?: LucideIcon; title: string; message?: string; actions?: ReactNode; tone?: 'neutral' | 'error' | 'loading';
}) {
  return <section className={`panel compare-empty is-${tone}`} role={tone === 'error' ? 'alert' : tone === 'loading' ? 'status' : undefined}>
    <span className="compare-empty-icon" aria-hidden="true">{tone === 'loading' ? <span className="shell-spinner" /> : <Icon size={24} />}</span>
    <div><h2>{title}</h2>{message && <p>{message}</p>}</div>
    {actions && <div className="compare-empty-actions">{actions}</div>}
  </section>;
}

export function DocumentRuns({ doc, active, mode, onMode }: {
  doc: LiveDoc; active: boolean; mode: ReviewMode; onMode: (mode: ReviewMode) => void;
}) {
  const [sourceRun, setSourceRun] = useState('');
  const [selection, setSelection] = useState<{ left: string; right: string }>();
  const [location, setLocation] = useState<ReviewLocation>();
  const [retry, setRetry] = useState(0);
  const { id } = doc;
  const revision = retry;
  const loadRuns = useCallback((signal: AbortSignal) => listParseRuns(id, signal), [id]);
  const available = useLoad(loadRuns, active, revision);
  const runs = available?.data ?? [];
  const left = selection?.left ?? runs[runs.length > 1 ? 1 : 0]?.run_id ?? '';
  const right = selection?.right ?? runs[0]?.run_id ?? '';
  const sourceId = sourceRun || right;
  const needsPair = active && mode === 'runs' && runs.length > 1;
  const loadLeft = useCallback((signal: AbortSignal) => getParseRun(id, left, signal), [id, left]);
  const loadRight = useCallback((signal: AbortSignal) => getParseRun(id, right, signal), [id, right]);
  const baseline = useLoad(loadLeft, active && !!left && left !== right && (needsPair || sourceId === left), retry);
  const candidate = useLoad(loadRight, active && !!right && (needsPair || sourceId === right), retry);

  const loadOther = useCallback((signal: AbortSignal) => getParseRun(id, sourceId, signal), [id, sourceId]);
  const other = useLoad(loadOther, active && !!sourceId && sourceId !== left && sourceId !== right, retry);
  const sourceResult = sourceId === right ? candidate : sourceId === left ? baseline : other;

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

        {runs.map(run => <option key={run.run_id} value={run.run_id} disabled={run.run_id === other}>{runLabel(run)}</option>)}
      </select>
      {side === 'right' && left && right && <button className="button-quiet" data-tip="이전과 현재 바꾸기" aria-label="이전과 현재 바꾸기"
        onClick={() => change({ left: right, right: left })}><ArrowRightLeft size={15} /></button>}
    </div>;
  }

  const errorPanel = (message: string) => <CompareState icon={TriangleAlert} tone="error" title="실행 결과를 읽을 수 없습니다" message={message}
    actions={<button className="button-secondary" onClick={() => setRetry(n => n + 1)}>다시 시도</button>}/>;
  const pending = <CompareState title="실행 결과를 불러오는 중" tone="loading"/>;
  if (available?.error) return errorPanel(available.error);
  if (!available) return pending;
  const pairError = baseline?.error || candidate?.error;
  if (!runs.length) return <CompareState title="성공한 파싱 실행이 없습니다" message="문서 상세에서 처리 상태와 이력을 확인하세요."/>;
  return <ReviewDesk key={left + '/' + right} mode={mode} onMode={onMode} canCompare={runs.length > 1}
    baseline={runPane(baseline?.data, doc)} candidate={runPane(candidate?.data, doc)}
    pairStatus={pairError ? errorPanel(pairError) : !baseline?.data || !candidate?.data ? pending : undefined}
    sourceStatus={sourceResult?.error ? errorPanel(sourceResult.error) : !sourceResult?.data ? pending : undefined}
    sourceKey={sourceId} onEvidenceSide={side => setSourceRun(side === 'left' ? left : right)}
    sourcePane={runPane(sourceResult?.data, doc)} onLocation={setLocation}
    original={<SourceOriginal doc={doc} active={active && (mode === 'source' || runs.length < 2)} location={location} onLocation={setLocation}/>}
    sourceControl={<label className="reader-select">성공 실행<select value={sourceId} onChange={e => { setSourceRun(e.target.value); setLocation(undefined); }}>
      {runs.map(r => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}</select></label>}
    pairControls={<div className="pair-pickers"><div>이전 실행{picker('left')}</div><div>현재 실행{picker('right')}</div></div>}
    summary={<RunSummary before={runSide(baseline?.data)} after={runSide(candidate?.data)}/>}/>;
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
    <p>{desc}</p>
    {run.is_latest && doc.status !== 'completed' && <p className="compare-warning">이전 성공 결과 · 현재 작업 결과 아님</p>}
    {run.warnings.map(warning => <p key={warning} className="compare-warning">{warning}</p>)}
  </div> };
}

const IMAGE_MIME: Readonly<Record<string, string>> = Object.freeze({
  PNG: 'image/png', JPEG: 'image/jpeg', JPG: 'image/jpeg', GIF: 'image/gif', WEBP: 'image/webp', BMP: 'image/bmp', AVIF: 'image/avif',
  // <img>로만 보이므로 SVG 안의 스크립트는 돌지 않는다.
  SVG: 'image/svg+xml',
});

function SourceOriginal({ doc, active, location, onLocation }: {
  doc: LiveDoc; active: boolean; location?: ReviewLocation; onLocation: (location: ReviewLocation) => void;
}) {
  const { id, format } = doc;
  const href = liveSourceUrl(id);
  const pdf = format === 'PDF';
  const sheet = location?.sheet ?? undefined, cell = location?.cell;
  const canPreview = ['TXT', 'LOG', 'CSV', 'MD', 'XLSX', 'XLSM'].includes(format);
  const imageType = IMAGE_MIME[format];
  const office = OFFICE[format];
  const [retry, setRetry] = useState(0);
  const [imageUrl, setImageUrl] = useState<string>();
  const [imageFailed, setImageFailed] = useState(false);
  const loadPreview = useCallback((signal: AbortSignal) => getSourcePreview(id, signal, sheet, cell), [id, sheet, cell]);
  const loadImage = useCallback(async (signal: AbortSignal) => {
    const response = await fetch(href, { signal });
    if (!response.ok) throw Error('원본 이미지 파일을 불러오지 못했어요.');
    return new Blob([await response.blob()], { type: imageType });
  }, [href, imageType]);
  const loadOffice = useCallback(async (signal: AbortSignal) => {
    const response = await fetch(href, { signal });
    if (!response.ok) throw Error('원본 파일을 불러오지 못했어요.');
    return response.arrayBuffer();
  }, [href]);
  const preview = useLoad(loadPreview, active && canPreview, retry);
  const image = useLoad(loadImage, active && !!imageType, retry);
  const officeFile = useLoad(loadOffice, active && !!office, retry);
  const data = preview?.data;
  const page = location?.page ?? 1;

  useEffect(() => {
    if (!image?.data) return;
    const url = URL.createObjectURL(image.data);
    setImageFailed(false);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image?.data]);

  const renderPreview = pdf ? (expanded: boolean) => <PdfSource href={href} page={page} expanded={expanded} />
    : data?.kind === 'sheet' ? () => <WorksheetSource key={`${data.sheet}!${data.cell}`} data={data} onLocation={onLocation} />
    : data?.kind === 'text' ? () => <TextSource {...data} />
    : imageUrl && !imageFailed ? () => <div className="compare-image-source"><img src={imageUrl} alt={doc.name} onError={() => setImageFailed(true)} /></div>
    : office && officeFile?.data ? (expanded: boolean) => <Suspense fallback={<p className="office-status" role="status">원본 보기를 준비하는 중…</p>}>
      <OfficeSource kind={office} data={officeFile.data!} expanded={expanded} /></Suspense>
    : undefined;
  const error = preview?.error ?? image?.error ?? officeFile?.error;
  const fallback = error || imageFailed ? <div role="alert"><p>{error ?? '브라우저에서 이 이미지를 표시할 수 없어요.'}</p>
    {error && <button type="button" className="button-secondary" onClick={() => setRetry(value => value + 1)}>다시 시도</button>}</div>
    : canPreview || imageType || office ? <p role="status">원본을 불러오는 중…</p>
    : <div><strong>전용 앱에서 원본을 확인하세요</strong><p>{['XLS', 'DOC', 'PPT'].includes(format)
      ? '원본을 다운로드하면 전용 앱에서 페이지 배치와 서식을 그대로 확인할 수 있어요.'
      : '원본 파일을 내려받아 열 수 있어요.'}</p></div>;

  return <OriginalPane name={doc.name} label={format === 'XLSX' || format === 'XLSM' ? `${format} 셀 값` : office ? `${format} · 브라우저 재현` : format || '원본 파일'}
    href={pdf ? `${href}#page=${page}` : href} downloadName={pdf ? undefined : doc.name} preview={renderPreview} fallback={fallback} />;
}
