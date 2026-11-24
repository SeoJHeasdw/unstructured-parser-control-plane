import { useEffect, useState } from 'react';
import { AlertCircle, ArrowLeft, BookOpen, CircleAlert, CircleDashed, Scissors, CircleCheck, CircleSlash, Clock3, Download, File, FileText, FileSpreadsheet, FileImage, FileArchive, Presentation, GitCompareArrows, LoaderCircle, Play, RefreshCw, TriangleAlert, Workflow } from 'lucide-react';
import { getDocumentHistory, listParseRuns, liveSourceUrl } from './api/live';
import type { HistoryEntry, LiveDoc, LiveResult, LiveStatus, ParseRun } from './api/live';
import { WorkspaceLink } from './WorkspaceLink';
import type { DetailTab, WorkspaceRoute } from './navigation';
import { Tabs } from './ui';
import { StructurePanel } from './StructurePanel';

/** 화면에 보이는 상태. 글자 없는 이미지는 서버에서 failed지만 실패로 보이지 않는다(no_text). */
export type DisplayStatus = LiveStatus | 'no_text';
export const statusLabels: Record<DisplayStatus, string> = {
  uploaded: '실행 전', processing: '처리 중 / 대기', completed: '처리 완료', failed: '처리 실패', unsupported: '지원 안 됨', no_text: '글자 없음',
};
const statusIcons = { uploaded: Clock3, processing: LoaderCircle, completed: CircleCheck, failed: CircleAlert, unsupported: CircleSlash, no_text: CircleDashed };

/** 서버의 이미지 형식 목록(app/formats.py IMAGE_FORMATS)과 같다. */
const IMAGE_FORMATS = ['PNG', 'JPG', 'JPEG', 'BMP', 'TIFF', 'TIF', 'GIF', 'WEBP'];
export const NO_TEXT_NOTE = '이미지에서 글자를 찾지 못했습니다. 글자 없는 사진이면 정상이고, 글자가 보이는 이미지라면 OCR이 놓친 것입니다.';
/** 이미지에서 글자를 찾지 못한 경우는 실패가 아니라 '글자 없음'이다. 다른 실패는 그대로 실패다. */
export const isNoTextImage = (doc: Pick<LiveDoc, 'status' | 'error_code' | 'format'>) =>
  doc.status === 'failed' && doc.error_code === 'no_text' && IMAGE_FORMATS.includes((doc.format || '').toUpperCase());
export const displayStatus = (doc: LiveDoc): DisplayStatus => isNoTextImage(doc) ? 'no_text' : doc.status;

/** 문서 번호 'D12'. 예전 서버처럼 번호가 없으면 빈 문자열. */
export const docNumber = (seq?: number | null) => typeof seq === 'number' && Number.isInteger(seq) && seq > 0 ? `D${seq}` : '';
/** 'D12'·'d12'·'D-12'·'#12'·'12'를 번호로 읽는다. 번호 모양이 아니면 null. */
export function parseDocNumber(query: string): number | null {
  const match = /^(?:d\s*-?\s*|#)?0*(\d{1,9})$/i.exec(query.trim());
  return match ? Number(match[1]) : null;
}
/** 검색어가 이름·형식·ID에 들어 있거나, 번호 모양이면 문서 번호와 같을 때 맞는다. */
export function matchesDocQuery(doc: LiveDoc, query: string) {
  const search = query.trim().toLowerCase();
  if (`${doc.name} ${doc.format} ${doc.id}`.toLowerCase().includes(search)) return true;
  const number = parseDocNumber(search);
  return number !== null && doc.seq === number;
}
export function DocNumber({ seq }: { seq?: number | null }) {
  const label = docNumber(seq);
  // 뒤의 공백은 줄 안에서 다음 글자와 붙어 읽히지 않게 한다(flex 줄에서는 무시된다).
  return label ? <><span className="lw-seq">{label}</span>{' '}</> : null;
}
const dateFormat = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
});
export function displayDate(value: string) {
  const date = new Date(value);
  return Number.isFinite(+date) ? dateFormat.format(date) : '시간 미확인';
}
export function displaySize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return '크기 미확인';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function StatusBadge({ status }: { status: DisplayStatus }) {
  const Icon = statusIcons[status] ?? AlertCircle;
  return <span className={`lw-status is-${status}`}><Icon size={15} aria-hidden="true" />{statusLabels[status] ?? status}</span>;
}

export function FileGlyph({ format }: { format: string }) {
  const type = format.toUpperCase();
  let Icon = File;
  if (['TXT','MD','LOG','PDF','DOC','DOCX','RTF','ODT'].includes(type)) Icon = FileText;
  else if (['XLS','XLSX','XLSM','CSV'].includes(type)) Icon = FileSpreadsheet;
  else if (['JPEG','JPG','PNG','TIF','TIFF','GIF','WEBP','HEIC','HEIF'].includes(type)) Icon = FileImage;
  else if (['PPT','PPTX'].includes(type)) Icon = Presentation;
  else if (type === 'ZIP') Icon = FileArchive;
  return <span className="lw-file-glyph" aria-hidden="true"><Icon size={22} strokeWidth={1.6} /></span>;
}

const failureLabels: Record<string, string> = {
  format_mismatch: '확장자와 파일 내용이 다릅니다.', encrypted: '암호로 보호된 파일입니다.',
  drm_protected: '문서 보안으로 보호된 파일입니다.', drm_suspected: '문서 보안 적용이 의심됩니다.',
  unsupported_format: '지원하는 파서가 없는 형식입니다.', parser_unavailable: '파서 또는 모델을 사용할 수 없습니다.',
  no_text: '추출할 수 있는 텍스트를 찾지 못했습니다.', interrupted: '서버 중단으로 처리가 끝나지 않았습니다.',
};
export const failureReason = (doc: LiveDoc) => failureLabels[doc.error_code ?? ''] || doc.error || '처리 상태를 확인하세요.';
/** 목록 행의 둘째 줄: 실패·미지원은 사유, 글자 없음은 설명, 나머지는 기본 정보. */
export const statusNote = (doc: LiveDoc) => isNoTextImage(doc) ? NO_TEXT_NOTE : doc.status === 'failed' || doc.status === 'unsupported' ? failureReason(doc) : null;

const tabs = [{ id: 'result', label: '추출 결과' }, { id: 'history', label: '처리 이력' }, { id: 'structure', label: '구조·참조' }] as const;

function History({ doc }: { doc: LiveDoc }) {
  const [events, setEvents] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    getDocumentHistory(doc.id, controller.signal).then(body => {
      if (!controller.signal.aborted) setEvents(body);
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '이력을 불러오지 못했습니다.');
    });
    return () => controller.abort();
  }, [doc.id, doc.updated_at, revision]);
  if (error) return <div className="lw-message" role="alert">{error}<button onClick={() => setRevision(value => value + 1)}>다시 시도</button></div>;
  if (!events) return <p className="lw-placeholder" role="status">처리 이력을 불러오는 중입니다.</p>;
  if (!events.length) return <p className="lw-placeholder">아직 기록된 처리 이력이 없습니다.</p>;
  return <ol className="lw-timeline">{[...events].reverse().map((event, i) => <li key={i}>
    <time dateTime={event.created_at}>{displayDate(event.created_at)}</time>
    <div><strong>{statusLabels[event.status as LiveStatus] ?? event.status}</strong><p>{event.message}</p></div>
  </li>)}</ol>;
}

type Props = {
  doc: LiveDoc; result: LiveResult | null; resultError: string; resultLoading: boolean; submittingId: string | null;
  onNavigate?: (route: WorkspaceRoute) => void;
  onBack: () => void; onProcess: () => void; tab: DetailTab; onTab: (tab: DetailTab) => void; onCompare: () => void; onFamily?: () => void; onPickFile: () => void;
};

export default function LiveDocumentView({ doc, result, resultError, resultLoading, submittingId, onBack, onProcess, onCompare, tab, onTab, onFamily, onPickFile, onNavigate }: Props) {
  const replaceFile = ['format_mismatch','encrypted','drm_protected','drm_suspected'].includes(doc.error_code ?? '');
  const noText = isNoTextImage(doc);
  const failed = !noText && (doc.status === 'failed' || doc.status === 'unsupported');
  const running = doc.status === 'processing';
  const submitting = submittingId === doc.id;
  const hasComparison = !!result;
  const needsRuns = tab === 'history' || !!result?.is_stale;
  const [runs, setRuns] = useState<ParseRun[] | null>(null);
  const [runError, setRunError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!needsRuns) return;
    const controller = new AbortController();
    setRunError('');
    listParseRuns(doc.id, controller.signal).then(data => {
      if (!controller.signal.aborted) setRuns(data);
    }).catch(reason => {
      if (!controller.signal.aborted) setRunError(reason instanceof Error ? reason.message : '성공 실행을 불러오지 못했습니다.');
    });
    return () => controller.abort();
  }, [doc.id, doc.updated_at, needsRuns, retry]);
  const latestTime = runs?.find(run => run.is_latest)?.completed_at;
  return <article className="lw-detail">
    <button className="lw-back" onClick={onBack}><ArrowLeft size={16} />문서함으로</button>
    <header className="lw-detail-head">
      <FileGlyph format={doc.format} />
      <div className="lw-detail-name"><h1 tabIndex={-1}>{doc.name}</h1><div className="lw-subline"><DocNumber seq={doc.seq} /><StatusBadge status={displayStatus(doc)} />{onNavigate
        ? <WorkspaceLink className="lw-flow-link" to={{page:'parsers',format:doc.format}} onNavigate={onNavigate}><Workflow size={14}/>{doc.format || '확장자 없음'} 파서 플로우</WorkspaceLink>
        : <span>{doc.format || '확장자 없음'}</span>}<span>{displaySize(doc.size_bytes)}</span></div></div>
      <div className="lw-head-actions">
        {result && onNavigate && <WorkspaceLink className="lw-btn" to={{page:'chunking', doc:doc.id}} onNavigate={onNavigate}><Scissors size={16}/>{result.is_stale ? '이전 성공본 청킹' : '청킹 비교'}</WorkspaceLink>}
        {hasComparison && <button className="lw-btn is-compare" onClick={onCompare}><GitCompareArrows size={17} />원문과 대조</button>}
        {doc.status === 'unsupported' ? <a className="lw-btn" href="#detail-formats" onClick={() => { const node = document.querySelector<HTMLDetailsElement>('#detail-formats'); if (node) node.open = true; }}>지원 형식 보기</a> : replaceFile && failed ? <button className="lw-btn" onClick={onPickFile}>다른 파일 추가</button> : <button className={`lw-btn ${hasComparison ? '' : 'is-primary'}`} disabled={running || !!submittingId} onClick={onProcess}>
          {submitting || running ? <LoaderCircle size={16} className="live-spin" /> : doc.status === 'uploaded' ? <Play size={16} /> : <RefreshCw size={16} />}
          {submitting ? '접수 중' : running ? '처리 중 / 대기' : doc.status === 'uploaded' ? '파싱 실행' : '다시 파싱 실행'}
        </button>}
      </div>
    </header>
    {noText && <div className="lw-message is-neutral" role="note"><CircleDashed size={18} aria-hidden="true" /><span>{NO_TEXT_NOTE}</span></div>}
    {failed && <div className="lw-message is-error"><TriangleAlert size={18} /><div><strong>{failureReason(doc)}</strong>
      {doc.error && failureReason(doc) !== doc.error && <details><summary>오류 상세</summary><p>{doc.error}</p></details>}
    </div></div>}
    <div className="lw-sheet">
      <Tabs<DetailTab> items={[...tabs]} value={tab} onChange={onTab} label="문서 상세 보기">
        {view => view === 'history' ? <div className="lw-history">
          <h2>상태 이벤트</h2><History doc={doc} />
          <h2>성공한 파싱 실행</h2>
          {runError ? <p role="alert">{runError} <button className="lw-btn" onClick={() => setRetry(n => n + 1)}>다시 시도</button></p> :
            !runs ? <p role="status">성공 실행을 불러오는 중입니다.</p> : !runs.length ? <p>저장된 성공 실행이 없습니다.</p> :
            <ol className="lw-timeline">{runs.map(run => <li key={run.run_id}>
              <time dateTime={run.completed_at ?? undefined}>{run.completed_at ? displayDate(run.completed_at) : '시각 미기록'}</time>
              <div><strong>{[run.parser, run.parser_version].filter(Boolean).join(' · ') || '파서 미기록'}</strong><p>{run.is_latest ? '최근 성공 실행 · ' : ''}{run.run_id}</p></div>
            </li>)}</ol>}
        </div> : view === 'structure' ? <>{onFamily && <button className="lw-btn lw-family" onClick={onFamily}>문서군 보기</button>}<StructurePanel doc={doc}/></> :
          <section className="lw-reader" aria-label="파싱 결과">
            <div className="lw-reader-head"><span><BookOpen size={18} />{result ? [result.parser, result.parser_version].filter(Boolean).join(' · ') : '파싱 결과'}</span>
              <a className="lw-source" href={liveSourceUrl(doc.id)} download={doc.name}><Download size={15} />원본 다운로드</a></div>
            {resultLoading ? <p className="lw-placeholder" role="status">결과를 불러오는 중입니다.</p> :
              resultError ? <p className="lw-message is-error live-result-error" role="alert"><AlertCircle size={16} />{resultError}</p> :
              result ? <>
                {result.is_stale && <div className="lw-message is-warning" role="status"><Clock3 size={17} /><div><strong>이전 성공 결과 · 현재 작업 결과 아님</strong>{latestTime && <time dateTime={latestTime}> · {displayDate(latestTime)}</time>}</div></div>}
                {!!result.warnings.length && <div className="lw-message is-warning" role="alert"><TriangleAlert size={17} /><div><strong>파싱 경고</strong><ul>{result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></div></div>}
                {result.fidelity && <details className="lw-disclosure"><summary>원문 충실도 · 확인 항목 {result.fidelity.findings?.length ?? 0}개</summary>
                  {result.fidelity.findings?.length ? <ul>{result.fidelity.findings.map((f,i) => <li key={i}>{f.message}</li>)}</ul> : <p>기록된 확인 항목이 없습니다.</p>}</details>}
                <pre className="live-result-content">{result.markdown || '텍스트 결과가 비어 있습니다.'}</pre>
              </> : <div className="lw-placeholder"><p>{doc.status === 'uploaded' ? '파싱을 실행하면 추출 결과가 여기에 표시됩니다.' : running ? '현재 작업이 끝나면 결과가 표시됩니다.' : '이전에 성공한 파싱 결과가 없습니다.'}</p></div>}
          </section>}
      </Tabs>
    </div>
    {doc.status === 'unsupported' && <details id="detail-formats" className="lw-disclosure"><summary>지원 형식</summary><p>TXT·CSV·MD·LOG·SVG 벡터 글자는 기본 환경에서 읽습니다. PDF·DOCX·PPTX·XLSX는 Docling을, PNG·JPEG·TIFF·BMP·GIF·WebP와 스캔 글자는 모델 연결에서 연결한 OCR 모델로 읽습니다.</p></details>}
    <details className="lw-disclosure"><summary>파일 정보</summary><dl className="lw-meta">
      <div><dt>문서 ID</dt><dd>{doc.id}</dd></div><div><dt>저장 시각</dt><dd>{displayDate(doc.created_at)}</dd></div>
      <div><dt>마지막 변경</dt><dd>{displayDate(doc.updated_at)}</dd></div><div><dt>적용 파서</dt><dd>{doc.parser || '미지정'}</dd></div>
    </dl></details>
  </article>;
}

