import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ChevronRight, CircleAlert, FileCheck2, FileCode2, FileInput, FileText, GitBranch, Layers3, PencilRuler, Play, RefreshCw, ScanText, Scissors, Settings2, SlidersHorizontal, Table2, Workflow } from 'lucide-react';
import { getParserCatalog, listLiveDocuments, processLiveDocument, type LiveDoc, type ParserCatalog } from './api/live';
import { displayDate, failureReason, FileGlyph, StatusBadge } from './LiveDocumentView';
import { WorkspaceLink } from './WorkspaceLink';
import type { WorkspaceRoute } from './navigation';
import './parserWorkspace.css';

type Navigate = (route: WorkspaceRoute) => void;
const engines = new Map([
  ['docling', { name: 'Docling', icon: Layers3 }],
  ['python-text', { name: '텍스트', icon: FileText }],
  ['python-csv', { name: 'CSV 테이블', icon: Table2 }],
  ['easyocr', { name: 'EasyOCR', icon: ScanText }],
  ['python-svg', { name: 'SVG', icon: FileCode2 }],
]);
const formatName = (ext: string) => ext || '확장자 없음';

function extraction(format: string, engine: string) {
  switch (engine) {
    case 'docling':
      if (format === 'PDF') return ['페이지 분석', '페이지의 본문·표를 추출합니다. 로컬 OCR 모델이 있으면 스캔 글자도 읽습니다.'];
      if (format === 'XLSX') return ['워크시트 추출', '시트의 셀과 표를 읽고 원본 행·열 위치를 대조합니다.'];
      return ['Office 구조 추출', '본문·표를 변환하고 원본의 기호, 첨자와 내장 그림을 점검합니다.'];
    case 'easyocr': return ['이미지 문자 인식', '프레임별로 한국어·영어 글자를 인식하고 추출 순서를 기록합니다.'];
    case 'python-svg': return ['벡터 글자 추출', 'SVG의 텍스트를 읽고 내장 이미지에서 추출 가능한 글자를 보충합니다.'];
    case 'python-csv': return ['행·열 복원', '인코딩과 구분자를 판별한 뒤 행과 열을 Markdown 표로 변환합니다.'];
    case 'python-text': return ['텍스트 읽기', '인코딩을 판별해 본문의 줄바꿈과 문자 순서를 보존합니다.'];
    default: return ['본문 추출', '이 형식에 등록된 파서가 원본을 처리합니다.'];
  }
}

function Environment({ engine, format, catalog }: { engine: string; format: string; catalog: ParserCatalog }) {
  const facts: string[] = [];
  if (engine === 'docling') {
    facts.push(catalog.docling_installed ? 'Docling 설치됨' : 'Docling 설치 필요');
    if (format === 'PDF') facts.push(catalog.pdf_model_directory ? 'PDF 모델 폴더 확인' : 'PDF 모델 폴더 없음');
  }
  if (['docling', 'easyocr', 'python-svg'].includes(engine)) {
    facts.push(!catalog.ocr_enabled ? 'OCR 설정 꺼짐' : catalog.ocr_models_found ? '로컬 OCR 모델 확인' : '로컬 OCR 모델 미확인');
  }
  if (!facts.length) facts.push('Python 표준 라이브러리');
  facts.push('문서 파싱 1개씩 · 단일 워커');
  return <p className="pr-environment"><Settings2 size={15} aria-hidden="true"/><strong>실행 환경</strong>{facts.map(fact => <span key={fact}>{fact}</span>)}</p>;
}

function RouteDiagram({ format, engine, catalog, onNavigate }: { format: string; engine?: string; catalog: ParserCatalog; onNavigate: Navigate }) {
  const info = engines.get(engine ?? '');
  const Icon = info?.icon ?? Workflow;
  const [action, detail] = extraction(format, engine ?? '');
  return <section className="pr-diagram" aria-label="실제 파서 경로">
    <header className="pr-diagram-head">
      <div><span className="pr-source"><GitBranch size={15} aria-hidden="true"/>실제 처리 경로</span>
        <h2>{formatName(format)} <ChevronRight size={20} aria-hidden="true"/> {info?.name ?? engine ?? '미지원'}</h2></div>
      {format && <WorkspaceLink className="pr-edit" to={{page:'pipeline', format, mode:'design'}} onNavigate={onNavigate}><PencilRuler size={15}/>모의 경로 설계</WorkspaceLink>}
    </header>
    {engine ? <>
      <ol className="pr-stages" aria-label={formatName(format) + ' 처리 순서'}>
        <li><span className="pr-stage-icon"><FileInput size={21}/></span><strong>형식 확인</strong><p>확장자와 파일 내용을 검사해 처리 가능 여부를 확인합니다.</p></li>
        <li className="is-engine"><span className="pr-stage-icon"><Icon size={21}/></span><strong>{action}</strong><p>{detail}</p></li>
        <li><span className="pr-stage-icon"><FileCheck2 size={21}/></span><strong>결과 저장</strong><p>추출한 Markdown과 파서 버전, 경고를 실행 이력에 남깁니다.</p></li>
      </ol>
      <Environment format={format} engine={engine} catalog={catalog}/>
    </> : <div className="pr-missing"><CircleAlert size={19}/><p>이 형식에 등록된 로컬 파서가 없습니다. 아래 문서에서 처리 상태와 오류를 확인할 수 있습니다.</p></div>}
  </section>;
}

function RouteDocuments({ docs, error, format, canParse, pendingId, onProcess, onNavigate, refresh }: {
  docs: LiveDoc[] | null; error: string; format: string; canParse: boolean; pendingId: string | null;
  onProcess: (doc: LiveDoc) => void; onNavigate: Navigate; refresh: () => void;
}) {
  const [attention, setAttention] = useState(false);
  const [page, setPage] = useState(0);
  const matching = docs?.filter(doc => doc.format.toUpperCase() === format) ?? [];
  const issues = matching.filter(doc => doc.status === 'failed' || doc.status === 'unsupported');
  const rows = attention ? issues : matching;
  const size = 5;
  const current = Math.min(page, Math.max(0, Math.ceil(rows.length / size) - 1));
  return <section className="pr-docs" aria-labelledby="pr-docs-title">
    <header><h2 id="pr-docs-title">{formatName(format)} 문서 {docs && <small>{matching.length}</small>}</h2>
      <button className="pr-filter" aria-pressed={attention} onClick={() => { setAttention(!attention); setPage(0); }}><SlidersHorizontal size={15}/>실패 · 미지원{docs && ' ' + issues.length}</button>
    </header>
    {error ? <p className="pr-empty" role="alert">{error} <button className="text-button" onClick={refresh}>다시 시도</button></p> :
      !docs ? <p className="pr-empty" role="status">문서 목록을 불러오는 중입니다.</p> :
      rows.length ? <ul>{rows.slice(current * size, (current + 1) * size).map(doc => <li key={doc.id}>
        <WorkspaceLink className="pr-doc" to={{page:'live', doc:doc.id}} onNavigate={onNavigate}><FileGlyph format={doc.format}/><span><b>{doc.name}</b><small>{doc.status === 'failed' || doc.status === 'unsupported' ? failureReason(doc) : displayDate(doc.updated_at)}</small></span><StatusBadge status={doc.status}/><ChevronRight size={15}/></WorkspaceLink>
        {canParse && (doc.status === 'uploaded' || doc.status === 'failed') && <button className="pr-process" disabled={pendingId !== null}
          onClick={() => onProcess(doc)} aria-label={doc.name + (doc.status === 'failed' ? ' 다시 파싱' : ' 파싱 실행')}>
          <Play size={14}/>{pendingId === doc.id ? '접수 중' : doc.status === 'failed' ? '다시 파싱' : '파싱 실행'}</button>}
        {doc.status === 'completed' && <WorkspaceLink className="pr-chunk" aria-label={doc.name + ' 청킹 비교'} to={{page:'chunking', doc:doc.id}} onNavigate={onNavigate}><Scissors size={15}/>청킹</WorkspaceLink>}
      </li>)}</ul> : <div className="pr-empty"><FileText size={22}/><p>{attention ? '확인이 필요한 문서가 없습니다.' : '이 형식으로 등록된 문서가 없습니다.'}</p>{!attention && <WorkspaceLink to={{page:'live'}} onNavigate={onNavigate}>문서함 열기 <ArrowRight size={14}/></WorkspaceLink>}</div>}
    {rows.length > size && !error && <div className="pr-paging"><button disabled={!current} onClick={() => setPage(current - 1)}>이전</button><span>{current + 1} / {Math.ceil(rows.length / size)}</span><button disabled={(current + 1) * size >= rows.length} onClick={() => setPage(current + 1)}>다음</button></div>}
  </section>;
}

export default function ParserWorkspace({ format: requested, onNavigate }: { format?: string; onNavigate: Navigate }) {
  const [catalog, setCatalog] = useState<ParserCatalog | null>(null);
  const [docs, setDocs] = useState<LiveDoc[] | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [docsError, setDocsError] = useState('');
  const [revision, setRevision] = useState(0);
  const [listRevision, setListRevision] = useState(0);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const submitting = useRef(false);
  const refresh = () => { setRevision(n => n + 1); setListRevision(n => n + 1); };
  useEffect(() => {
    const controller = new AbortController(), signal = controller.signal;
    setCatalogError('');
    getParserCatalog(signal).then(result => { if (!signal.aborted) setCatalog(result); })
      .catch(() => { if (!signal.aborted) setCatalogError('파서 목록을 불러오지 못했습니다.'); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    const controller = new AbortController(), signal = controller.signal;
    let timer: number | undefined;
    async function load() {
      try {
        const result = await listLiveDocuments(signal);
        if (signal.aborted) return;
        setDocs(result);
        setDocsError('');
        if (result.some(doc => doc.status === 'processing')) timer = window.setTimeout(load, 2000);
      } catch {
        if (!signal.aborted) setDocsError('로컬 문서 목록을 불러오지 못했습니다.');
      }
    }
    void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [listRevision]);
  async function process(doc: LiveDoc) {
    if (submitting.current) return;
    submitting.current = true;
    setPendingId(doc.id);
    setActionMessage(null);
    try {
      const updated = await processLiveDocument(doc.id);
      setDocs(previous => previous?.map(item => item.id === updated.id ? updated : item) ?? null);
      setActionMessage({text:doc.name + ' 파싱 요청을 접수했습니다.'});
    } catch (err) {
      setActionMessage({text:doc.name + ' · ' + (err instanceof Error ? err.message : '파싱을 접수하지 못했습니다.'), error:true});
    } finally {
      submitting.current = false;
      setPendingId(null);
      setListRevision(n => n + 1);
    }
  }
  if (!catalog || catalogError) return <div className="pr-empty panel" role={catalogError ? 'alert' : 'status'}>{catalogError || '파서 목록을 불러오는 중입니다.'}{catalogError && <button className="button-secondary" onClick={refresh}>다시 시도</button>}</div>;

  const format = requested ?? ('PDF' in catalog.routes ? 'PDF' : Object.keys(catalog.routes)[0] ?? '');
  const groups = new Map<string, string[]>();
  for (const [ext, parser] of Object.entries(catalog.routes)) groups.set(parser, [...(groups.get(parser) ?? []), ext]);
  const unrouted = [...new Set([...(docs ?? []).map(doc => doc.format.toUpperCase()), format])].filter(ext => !Object.hasOwn(catalog.routes, ext)).sort();
  if (unrouted.length) groups.set('', unrouted);
  const engine = Object.hasOwn(catalog.routes, format) ? catalog.routes[format] : undefined;
  const routeFor = (ext: string): WorkspaceRoute => ({page:'parsers', format:ext});

  return <div className="pr-workspace">
    <aside className="pr-index" aria-label="형식별 파서 목록">
      <header><h2>형식별 파서</h2><button className="pr-reload" onClick={refresh} data-tip="파서와 문서 새로고침" aria-label="파서와 문서 새로고침"><RefreshCw size={16}/></button></header>
      <div className="pr-index-list">{Array.from(groups, ([id, formats]) => {
        const info = engines.get(id), Icon = info?.icon ?? GitBranch;
        return <section key={id}><h3><Icon size={17} aria-hidden="true"/>{info?.name ?? (id || '미지원 형식')}</h3><div>{formats.map(ext =>
          <WorkspaceLink key={ext} to={routeFor(ext)} onNavigate={onNavigate} aria-current={ext === format ? 'true' : undefined}>{formatName(ext)}</WorkspaceLink>)}</div></section>;
      })}</div>
      <select className="pr-picker" aria-label="파일 형식" value={format} onChange={e => onNavigate(routeFor(e.target.value))}>
        {Array.from(groups, ([id, formats]) => <optgroup key={id} label={engines.get(id)?.name ?? (id || '미지원 형식')}>{formats.map(ext => <option value={ext} key={ext}>{formatName(ext)}</option>)}</optgroup>)}
      </select>
    </aside>
    <div className="pr-detail"><RouteDiagram format={format} engine={engine} catalog={catalog} onNavigate={onNavigate}/>
      {actionMessage && <p className={'pr-feedback' + (actionMessage.error ? ' is-error' : '')} role={actionMessage.error ? 'alert' : 'status'}>{actionMessage.text}<button aria-label="파싱 안내 닫기" onClick={() => setActionMessage(null)}>닫기</button></p>}
      <RouteDocuments canParse={!!engine} pendingId={pendingId} onProcess={process} key={format} format={format} docs={docs} error={docsError} onNavigate={onNavigate} refresh={refresh}/></div>
  </div>;
}
