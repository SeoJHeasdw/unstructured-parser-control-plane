import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowRight, ArrowRightLeft, FileSearch, RefreshCw, TriangleAlert } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { getParseRun, getSourcePreview, listLiveDocuments, listParseRuns, liveSourceUrl } from '../api/live';
import type { LiveDoc, ParseRun, StoredParseRun } from '../api/live';
import { ResultReview } from './ResultReview';
import { RunSummary } from './RunSummary';
import { OriginalPane, PdfSource, TextSource, WorksheetSource } from './SourceViewer';
import type { RunSide } from './RunSummary';
import type { ResultPane, ReviewLocation } from './ResultReview';

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

type CompareOptions = { showOriginal: boolean; showAlternative: boolean; highlight: boolean };
type Props = {
  active: boolean; selectedId: string; onChange: (id: string) => void; sourceTabs: ReactNode; switches: ReactNode;
  options: CompareOptions; onShowOriginal: () => void; onOpenLive?: () => void; onOpenExample?: () => void;
};

export function CompareState({ icon: Icon = FileSearch, title, message, actions, tone = 'neutral' }: {
  icon?: LucideIcon; title: string; message?: string; actions?: ReactNode; tone?: 'neutral' | 'error' | 'loading';
}) {
  return <section className={`panel compare-empty is-${tone}`} role={tone === 'error' ? 'alert' : tone === 'loading' ? 'status' : undefined}>
    <span className="compare-empty-icon" aria-hidden="true">{tone === 'loading' ? <span className="shell-spinner" /> : <Icon size={24} />}</span>
    <div><h2>{title}</h2>{message && <p>{message}</p>}</div>
    {actions && <div className="compare-empty-actions">{actions}</div>}
  </section>;
}

export function LiveCompare({ active, selectedId, onChange, sourceTabs, switches, options, onShowOriginal, onOpenLive, onOpenExample }: Props) {
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh(value => value + 1);
  const docs = useLoad(listLiveDocuments, active, refresh);
  const doc = docs?.data?.find(item => item.id === selectedId) ?? docs?.data?.[0];
  const loading = !docs || docs.pending;

  return <>
    <section className="panel compare-controls" aria-label="비교 설정">
      <div className="compare-controls-start">{sourceTabs}
        <div className="compare-document">
          <label className="compare-control-label" htmlFor="compare-live-document">비교 문서</label>
          <select id="compare-live-document" value={doc?.id ?? ''} title={doc?.name} disabled={!doc} onChange={event => onChange(event.target.value)}>
            {!doc && <option value="">{loading ? '불러오는 중…' : '문서 없음'}</option>}
            {docs?.data?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
      </div>
      <div className="compare-controls-end">
        <button type="button" className="button-secondary compare-refresh" disabled={loading} onClick={reload}><RefreshCw size={16} aria-hidden="true" />실행 목록 새로고침</button>
      </div>
    </section>
    {!loading && docs?.error && <CompareState icon={TriangleAlert} tone="error" title="실제 문서 목록을 불러오지 못했어요" message={docs.error}
      actions={<button type="button" className="button-secondary" onClick={reload}>다시 시도</button>} />}
    {doc ? <DocumentRuns key={doc.id} doc={doc} active={active} refresh={refresh} options={options} switches={switches}
      onShowOriginal={onShowOriginal} onOpenLive={onOpenLive} onOpenExample={onOpenExample} />
      : loading ? <CompareState title="실제 문서를 불러오는 중" tone="loading" />
      : !docs.error && <CompareState title="비교할 실제 문서가 없습니다" message="실제 파일을 올리고 같은 문서의 파싱 실행을 두 번 완료하면 결과를 비교할 수 있어요."
        actions={<>
          {onOpenLive && <button type="button" className="button-primary" onClick={onOpenLive}>실제 파일 처리 열기 <ArrowRight size={15} aria-hidden="true" /></button>}
          {onOpenExample && <button type="button" className="button-secondary" onClick={onOpenExample}>예시로 비교해 보기</button>}
        </>} />}
  </>;
}

function DocumentRuns({ doc, active, refresh, options, switches, onShowOriginal, onOpenLive, onOpenExample }: {
  doc: LiveDoc; active: boolean; refresh: number; options: CompareOptions; switches: ReactNode;
  onShowOriginal: () => void; onOpenLive?: () => void; onOpenExample?: () => void;
}) {
  const [selection, setSelection] = useState<{ left: string; right: string }>();
  const [location, setLocation] = useState<ReviewLocation>();
  const [retry, setRetry] = useState(0);
  const { id } = doc;
  const revision = refresh + retry;
  const loadRuns = useCallback((signal: AbortSignal) => listParseRuns(id, signal), [id]);
  const available = useLoad(loadRuns, active, revision);
  const runs = available?.data ?? [];
  const left = selection?.left ?? runs[runs.length > 1 ? 1 : 0]?.run_id ?? '';
  const right = selection?.right ?? (runs.length > 1 ? runs[0].run_id : '');
  const loadLeft = useCallback((signal: AbortSignal) => getParseRun(id, left, signal), [id, left]);
  const loadRight = useCallback((signal: AbortSignal) => getParseRun(id, right, signal), [id, right]);
  const baseline = useLoad(loadLeft, active && !!left, retry);
  const candidate = useLoad(loadRight, active && !!right, retry);

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

  const loading = !available || available.pending || (!!left && (!baseline || baseline.pending)) || (!!right && (!candidate || candidate.pending));
  const error = !loading && (available?.error ?? baseline?.error ?? candidate?.error);
  if (error) return <CompareState icon={TriangleAlert} tone="error" title="파싱 실행 결과를 불러오지 못했어요"
    message={error === 'Not Found' ? '로컬 백엔드의 실행 이력 주소를 찾지 못했어요.' : error}
    actions={<button type="button" className="button-secondary" onClick={() => setRetry(value => value + 1)}>다시 시도</button>} />;
  return <>
    {loading && !baseline?.data ? <CompareState title="실행 결과를 불러오는 중" tone="loading" /> :
    !loading && runs.length < 2 && <CompareState title={runs.length ? '파싱 실행이 한 번 더 필요합니다' : '성공한 파싱 실행이 없습니다'}
      message={runs.length ? '같은 문서를 다시 파싱하면 이전 결과와 나란히 비교할 수 있어요.' : doc.error || '실제 파일 처리에서 이 문서의 파싱을 완료해 주세요.'}
      actions={<>
        {onOpenLive && <button type="button" className="button-secondary" onClick={onOpenLive}>실제 파일 처리 열기 <ArrowRight size={15} aria-hidden="true" /></button>}
        {onOpenExample && <button type="button" className="button-secondary" onClick={onOpenExample}>예시로 비교해 보기</button>}
      </>} />}
    <RunSummary before={runSide(baseline?.data)} after={runSide(candidate?.data)} />
    {runs.length > 0 && <ResultReview key={`${left}/${right}`} {...options} controls={switches}
      baseline={runPane(baseline?.data, doc)} candidate={runPane(candidate?.data, doc)}
      baselineControl={picker('left')} candidateControl={picker('right')}
      onLocation={(value, reveal) => { if (value) setLocation(value); if (reveal) onShowOriginal(); }}
      original={<SourceOriginal doc={doc} active={active && options.showOriginal} location={location} onLocation={setLocation} />} />}
    {!loading && !runs.length && <SourceOriginal doc={doc} active={active} location={location} onLocation={setLocation} />}
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
    <p>{desc}</p>
    {run.is_latest && doc.status !== 'completed' && <p className="compare-warning">이전 성공 결과 · 현재 작업 결과 아님</p>}
    {run.warnings.map(warning => <p key={warning} className="compare-warning">{warning}</p>)}
  </div> };
}

const IMAGE_MIME: Readonly<Record<string, string>> = Object.freeze({
  PNG: 'image/png', JPEG: 'image/jpeg', JPG: 'image/jpeg', GIF: 'image/gif', WEBP: 'image/webp', BMP: 'image/bmp', AVIF: 'image/avif',
});

function SourceOriginal({ doc, active, location, onLocation }: {
  doc: LiveDoc; active: boolean; location?: ReviewLocation; onLocation: (location: ReviewLocation) => void;
}) {
  const { id, format } = doc;
  const href = liveSourceUrl(id);
  const pdf = format === 'PDF';
  const sheet = location?.sheet ?? undefined, cell = location?.cell;
  const canPreview = ['TXT', 'LOG', 'CSV', 'MD', 'XLSX'].includes(format);
  const imageType = IMAGE_MIME[format];
  const [retry, setRetry] = useState(0);
  const [imageUrl, setImageUrl] = useState<string>();
  const [imageFailed, setImageFailed] = useState(false);
  const loadPreview = useCallback((signal: AbortSignal) => getSourcePreview(id, signal, sheet, cell), [id, sheet, cell]);
  const loadImage = useCallback(async (signal: AbortSignal) => {
    const response = await fetch(href, { signal });
    if (!response.ok) throw Error('원본 이미지 파일을 불러오지 못했어요.');
    return new Blob([await response.blob()], { type: imageType });
  }, [href, imageType]);
  const preview = useLoad(loadPreview, active && canPreview, retry);
  const image = useLoad(loadImage, active && !!imageType, retry);
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
    : undefined;
  const error = preview?.error ?? image?.error;
  const fallback = error || imageFailed ? <div role="alert"><p>{error ?? '브라우저에서 이 이미지를 표시할 수 없어요.'}</p>
    {error && <button type="button" className="button-secondary" onClick={() => setRetry(value => value + 1)}>다시 시도</button>}</div>
    : canPreview || imageType ? <p role="status">원본을 불러오는 중…</p>
    : <div><strong>전용 앱에서 원본을 확인하세요</strong><p>{['DOCX', 'PPTX', 'XLS', 'XLSM'].includes(format)
      ? '원본을 다운로드하면 전용 앱에서 페이지 배치와 서식을 그대로 확인할 수 있어요.'
      : '원본 파일을 내려받아 열 수 있어요.'}</p></div>;

  return <OriginalPane name={doc.name} label={format === 'XLSX' ? 'XLSX 셀 값' : format || '원본 파일'}
    href={pdf ? `${href}#page=${page}` : href} downloadName={pdf ? undefined : doc.name} preview={renderPreview} fallback={fallback} />;
}
