import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent as ReactKeyboardEvent, MouseEvent, PointerEvent, ReactNode } from 'react';
import { AlertCircle, ArrowLeft, ArrowRight, Boxes, ChevronRight, FlaskConical, FolderOpen, Layers3, Maximize2, Minimize2, Menu, Search, Server, Settings2 } from 'lucide-react';
import Dashboard from './Dashboard';
import LiveWorkspace from './LiveWorkspace';
import ModelWorkspace from './ModelWorkspace';
import SearchPipeline from './SearchPipeline';
import { useFlowFullscreen } from './flow/useFlowFullscreen';
import { FlowSimulator } from './flow/flowSim';
import { loadLibrary } from './flow/flowTemplates';
import { DocumentBrowser, DocumentDrawer, CompareView } from './DocumentViews';
import { WorkspaceLink } from './WorkspaceLink';
import { WorkspaceFinder } from './WorkspaceFinder';
import { Modal, TooltipLayer } from './ui';
import { destinations, examples, toolsList, useWorkspaceRoute, workspaceHref } from './navigation';
import type { Page, WorkspaceRoute } from './navigation';
import type { AppData, DocumentFilter } from './types';

const ParserWorkspace = lazy(() => import('./ParserWorkspace'));
const PipelineStudio = lazy(() => import('./PipelineStudio'));
const LineageView = lazy(() => import('./LineageView'));
const ChunkBench = lazy(() => import('./ChunkBench'));
const EmbeddingEval = lazy(() => import('./EmbeddingEval'));
const VectorDbWorkspace = lazy(() => import('./VectorDbWorkspace'));
const AgentActivity = lazy(() => import('./AgentActivity'));

/** 사이드바 접기·펼치기 아이콘. 둥근 막대가 사이드바, 화살표가 누를 때 갈 방향이다.
 * 상태가 바뀌면 막대가 줄고 늘며 화살표가 뒤집히고, 마우스를 올리면 누른 뒤 모습을 미리 보여 준다(shell.css). */
function SidebarGlyph() {
  return <svg className="shell-glyph" viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect className="shell-glyph-frame" x="2.75" y="3.75" width="14.5" height="12.5" rx="3.25"/>
    <rect className="shell-glyph-bar" x="4.75" y="5.75" width="3.5" height="8.5" rx="1.75" fill="currentColor" stroke="none"/>
    <path className="shell-glyph-arrow" d="M13 8 11 10l2 2"/>
  </svg>;
}

const finderItems = (Object.keys(destinations) as Page[]).map(id => ({ id, ...destinations[id] }));
/** 사이드바를 접어 두었는지(이 브라우저에만 기억). 저장소를 못 쓰면 펼친 상태로 시작한다. */
const SIDEBAR_KEY = 'docops.sidebar';
function readSidebarOpen() {
  try { return localStorage.getItem(SIDEBAR_KEY) !== 'collapsed'; } catch { return true; }
}
function keyboardFocusInside(element: HTMLElement) {
  const focused = document.activeElement;
  if (!focused || !element.contains(focused)) return false;
  try { return focused.matches(':focus-visible'); } catch { return false; }
}
function saveSidebarOpen(open: boolean) {
  try { localStorage.setItem(SIDEBAR_KEY, open ? 'open' : 'collapsed'); } catch { /* 기억하지 못해도 동작은 같다 */ }
}
const shortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

export default function App() {
  const { route, go } = useWorkspaceRoute();
  const active = route.page;
  const info = destinations[active];
  const flowPage = active === 'parsers' || active === 'pipeline';
  const fullscreen = useFlowFullscreen(flowPage);
  const fullscreenLabel = fullscreen.expanded ? '전체화면 종료' : '전체화면';
  const FullscreenIcon = fullscreen.expanded ? Minimize2 : Maximize2;
  const fullscreenButton = <button className="flow-fullscreen-toggle" onClick={fullscreen.toggle}
    aria-pressed={fullscreen.expanded} aria-label={fullscreenLabel} data-tip={fullscreen.expanded ? fullscreenLabel : undefined} data-tip-key="Esc">
    <FullscreenIcon size={16} aria-hidden="true"/><span>{fullscreenLabel}</span></button>;
  const example = examples.includes(active) || active === 'pipeline';
  const [visited, setVisited] = useState<Page[]>([active]);
  const [sidebarOpen, setSidebarOpenState] = useState(readSidebarOpen);
  // 접힌 사이드바에 마우스를 올리거나 키보드 초점이 들어가면 본문을 밀지 않고 겹쳐 펼친다(고정 아님). 벗어나면 다시 접힌다.
  const [peek, setPeek] = useState(false);
  const peekTimer = useRef<number | undefined>(undefined);
  const peekBlocked = useRef(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [finderOpen, setFinderOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [data, setData] = useState<AppData | null>(null);
  const [mockError, setMockError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<DocumentFilter>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [simulator] = useState(() => new FlowSimulator(loadLibrary()));
  const content = useRef<HTMLDivElement>(null);
  const lastPage = useRef(active);
  const focusContent = useRef(false);
  const current = data?.documents.find(doc => doc.id === selected);
  const expanded = sidebarOpen || peek;
  const reviewing = active === 'live' && !!route.doc && !!route.review;
  function setSidebarOpen(open: boolean) {
    setSidebarOpenState(open);
    saveSidebarOpen(open);
    window.clearTimeout(peekTimer.current);
    setPeek(false);
    // 접기 단추를 누른 직후에는 마우스가 아직 사이드바 위에 있다: 밖으로 나갔다 들어올 때까지 엿보기를 쉰다.
    peekBlocked.current = !open;
  }
  const schedulePeek = (open: boolean, delay: number) => {
    window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPeek(open), delay);
  };
  useEffect(() => () => window.clearTimeout(peekTimer.current), []);
  const peekHandlers = sidebarOpen ? {} : {
    onPointerEnter: (event: PointerEvent<HTMLElement>) => {
      if (event.pointerType === 'touch' || event.pointerType === 'pen' || peekBlocked.current) return;
      schedulePeek(true, 120);
    },
    onPointerLeave: (event: PointerEvent<HTMLElement>) => {
      peekBlocked.current = false;
      if (event.pointerType === 'touch' || event.pointerType === 'pen') return;
      if (keyboardFocusInside(event.currentTarget)) return; // 키보드로 메뉴를 고르는 중이면 그대로 둔다
      schedulePeek(false, 220);
    },
    onFocus: () => { window.clearTimeout(peekTimer.current); setPeek(true); },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) schedulePeek(false, 0);
    },
    onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.key !== 'Escape' || !peek) return;
      event.stopPropagation();
      setPeek(false);
      (document.activeElement as HTMLElement | null)?.blur?.();
    },
  };

  useEffect(() => { setVisited(prev => prev.includes(active) ? prev : [...prev, active]); }, [active]);
  useEffect(() => {
    if (!example || data) return;
    const controller = new AbortController();
    setMockError(false);
    fetch('/api/data', { signal: controller.signal }).then(r => {
      if (!r.ok) throw Error();
      return r.json();
    }).then(payload => { if (!controller.signal.aborted) setData(payload); })
      .catch(() => { if (!controller.signal.aborted) setMockError(true); });
    return () => controller.abort();
  }, [example, data, attempt]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k' && !document.querySelector('[aria-modal="true"]')) {
        event.preventDefault(); setFinderOpen(true);
      }
    };
    const onPop = () => { setSelected(null); setMobileMenu(false); setFinderOpen(false); };
    window.addEventListener('keydown', onKey); window.addEventListener('popstate', onPop);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('popstate', onPop); };
  }, []);
  useEffect(() => {
    const pageChanged = lastPage.current !== active;
    lastPage.current = active;
    if (!pageChanged && !focusContent.current) return;
    focusContent.current = false;
    const heading = Array.from(content.current?.querySelectorAll<HTMLElement>('h1') ?? []).find(el => !el.closest('[hidden]'));
    (heading ?? content.current)?.focus({ preventScroll: true });
    document.scrollingElement?.scrollTo?.({ top: 0 });
  }, [active, route, finderOpen, mobileMenu]);
  function navigate(page: Page, nextFilter?: DocumentFilter) {
    if (page === 'documents' && nextFilter) setFilter(nextFilter);
    openRoute({ page, format: page === 'pipeline' ? nextFilter?.format : undefined });
  }
  function openRoute(next: WorkspaceRoute) {
    setMobileMenu(false); setFinderOpen(false); setSelected(null);
    focusContent.current = true;
    go(next);
  }
  function link(event: MouseEvent<HTMLAnchorElement>, page: Page) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(page);
  }
  function navLink(page: Page, label: string, Icon: typeof FolderOpen, isCurrent: boolean, expanded: boolean) {
    return <a href={workspaceHref({ page })} onClick={e => link(e, page)} className={'shell-nav-item' + (isCurrent ? ' is-active' : '')}
      aria-current={isCurrent ? 'location' : undefined} aria-label={label} data-tip={expanded ? undefined : label} data-tip-side="right"><Icon size={20} strokeWidth={1.75} aria-hidden="true"/><span>{label}</span></a>;
  }
  const chunkSource = active !== 'chunking' ? undefined
    : route.doc ? `doc:${route.doc}` as const : route.sample ? `sample:${route.sample}` as const : undefined;
  const nav = (expanded: boolean) => <nav className="shell-nav" aria-label="업무 메뉴">
    {navLink('live', '문서함', FolderOpen, active === 'live', expanded)}
    {navLink('agent', '에이전트 작업', destinations.agent.icon, active === 'agent', expanded)}
    {navLink('parsers', '파서 플로우', destinations.parsers.icon, active === 'parsers' || active === 'pipeline', expanded)}
    {navLink('chunking', '청킹 비교', destinations.chunking.icon, active === 'chunking', expanded)}
    <hr className="shell-nav-rule" />
    {navLink('analysis', '분석 도구', Boxes, info.group === '분석 도구', expanded)}
    {navLink('models', '설정', Settings2, active === 'models', expanded)}
    <div className="shell-examples">{navLink('overview', '예시 둘러보기', FlaskConical, examples.includes(active), expanded)}</div>
  </nav>;
  const keep = (page: Page, child: ReactNode) => (active === page || visited.includes(page)) && <div hidden={active !== page} className={page === 'pipeline' ? 'shell-fill' : undefined}><Suspense fallback={<p role="status" className="workspace-empty">화면을 불러오는 중입니다.</p>}>{child}</Suspense></div>;
  function changeLive(next: WorkspaceRoute) {
    if (active === 'live') go(next);
  }
  const toggleLabel = sidebarOpen ? '사이드바 접기' : peek ? '사이드바 펼친 채 고정' : '사이드바 펼치기';
  return <div className={'shell-root' + (sidebarOpen ? '' : ' shell-collapsed') + (!sidebarOpen && peek ? ' shell-peek' : '') + (flowPage ? ' shell-flow-page' : '') + (fullscreen.expanded ? ' shell-flow-fullscreen' : '')}>
    <a className="shell-skip" href="#workspace-content">본문으로 건너뛰기</a>
    <aside className="shell-sidebar" aria-label="주 탐색 메뉴" {...peekHandlers}>
      <div className="shell-brand"><span className="shell-mark"><Layers3 size={21} aria-hidden="true"/></span>
        <div className="shell-brand-text" aria-hidden={!expanded || undefined}><strong>비정형 관리 콘솔</strong></div>
        <button className="shell-sidebar-toggle" aria-expanded={sidebarOpen} aria-label={toggleLabel}
          data-tip={toggleLabel} data-tip-side={expanded ? 'bottom' : 'right'} onClick={() => setSidebarOpen(!sidebarOpen)}>
          <SidebarGlyph/></button></div>
      {nav(expanded)}
      <div className="shell-environment" data-tip={expanded ? undefined : '로컬 워크스페이스'} data-tip-side="right"><Server size={16} aria-hidden="true"/><span aria-hidden={!expanded || undefined}>로컬 워크스페이스</span></div>
    </aside>
    <main className="shell-main">
      <header className="shell-header"><div className="shell-topbar">
        <button className="shell-menu-toggle" aria-label="탐색 메뉴 열기" aria-expanded={mobileMenu} onClick={() => setMobileMenu(true)}><Menu size={21}/></button>
        <div className="shell-breadcrumb" aria-label="현재 위치">{active === 'pipeline' ? <WorkspaceLink to={{page:'parsers', format:route.format}} onNavigate={openRoute} aria-label="실제 파서 플로우"><ArrowLeft size={15}/>파서 플로우</WorkspaceLink> : <span>{info.group}</span>}{info.group !== info.label && <><ChevronRight size={14}/><strong>{info.label}</strong></>}{active === 'live' && route.doc && <><ChevronRight size={14}/><strong>{route.review ? '결과 검수' : '문서 상세'}</strong></>}</div>
        <div className="shell-top-right">{uploading && active !== 'live' && <a href={workspaceHref({page:'live'})} onClick={e => link(e, 'live')}>파일 저장 중</a>}
          {example && <span className="workspace-source"><FlaskConical size={15}/>예시 데이터</span>}
          <button className="shell-finder-trigger" aria-label="화면 찾기" aria-keyshortcuts="Meta+K Control+K" onClick={() => setFinderOpen(true)}><Search size={17}/><span>화면 찾기</span><kbd>{shortcut}</kbd></button></div>
      </div></header>
      <div id="workspace-content" ref={content} tabIndex={-1} className={'shell-content' + (active === 'pipeline' ? ' is-fill' : '') + (reviewing ? ' is-review' : '')}>
        {toolsList.includes(active) && <a className="workspace-back" href={workspaceHref({page:'analysis'})} onClick={e => link(e, 'analysis')}><ArrowLeft size={15}/>분석 도구로</a>}
        {examples.includes(active) && <nav className="example-nav" aria-label="예시 둘러보기">{examples.map(page => <a key={page} href={workspaceHref({page})} aria-current={active === page ? 'page' : undefined} onClick={e => link(e, page)}>{destinations[page].label}</a>)}</nav>}
        {active !== 'live' && active !== 'pipeline' && <div className="shell-title-row"><div><h1 tabIndex={-1}>{info.label}</h1>{active === 'parsers' && <p>파일 형식별 처리 경로와 로컬 문서의 파싱 상태를 확인하세요.</p>}{active === 'chunking' && <p>같은 원문에서 전략을 바꿔 가며 청크의 크기와 표·그림 보존 결과를 비교하세요.</p>}{active === 'agent' && <p>작업 에이전트(OpenCode 등)가 원본과 대조해 올린 검수 요청을 원문 대조로 확인하고, 다룬 문서·묶음·호출 기록을 보세요.</p>}</div>
          {active === 'parsers' && <div className="shell-flow-actions"><WorkspaceLink className="button-secondary" to={{page:'pipeline', mode:'design'}} onNavigate={openRoute}><FlaskConical size={16}/>모의 플로우 설계</WorkspaceLink>{fullscreenButton}</div>}</div>}
        {active === 'analysis' && <div className="tools-directory">{toolsList.map(page => {
          const tool = destinations[page], Icon = tool.icon;
          return <a key={page} href={workspaceHref({page})} onClick={e => link(e, page)}><Icon size={22} strokeWidth={1.75}/><span><strong>{tool.label}</strong><small>{tool.description}</small></span><ArrowRight size={17}/></a>;
        })}</div>}
        {keep('live', <LiveWorkspace active={active === 'live'} route={route} onRoute={changeLive} onNavigate={openRoute} onUploadStateChange={setUploading} onFamily={id => go({ page: 'relations', familyDoc: id })}/>)}
        {keep('agent', <AgentActivity active={active === 'agent'} onNavigate={openRoute}/>)}
        {example && !data && active !== 'pipeline' && <div className="panel shell-loading" role={mockError ? 'alert' : 'status'}><AlertCircle size={21}/><p>{mockError ? '예시 데이터를 불러오지 못했습니다.' : '예시 데이터를 불러오는 중입니다.'}</p>{mockError && <button className="button-secondary" onClick={() => setAttempt(n => n + 1)}>다시 시도</button>}</div>}
        {active === 'overview' && data && <Dashboard docs={data.documents} onOpenDoc={setSelected} onNavigate={navigate}/>}
        {data && keep('documents', <DocumentBrowser docs={data.documents} filter={filter} onFilterChange={setFilter} onOpenDoc={setSelected} onPipeline={format => navigate('pipeline', {format})}/>)}
        {active === 'parsers' && <ParserWorkspace format={route.format} onNavigate={go}/>}
        {keep('pipeline', <PipelineStudio fullscreenControl={fullscreenButton} active={active === 'pipeline'} simulator={simulator} formats={[...new Set(data?.documents.map(d => d.format) ?? [])]} initialFormat={active === 'pipeline' ? route.format : undefined} mode={route.mode ?? 'monitor'} onModeChange={mode => go({...route, mode:mode === 'design' ? mode : undefined})} onOpenDocuments={format => navigate('documents', {format: format || '확장자 없음'})} onOpenLiveDocuments={() => navigate('live')}/>)}
        {active === 'compare' && data && <CompareView docs={data.documents} selectedId={route.doc ?? 'DOC-0842'} onChange={doc => go({page:'compare', doc})} onOpenDoc={setSelected}/>}
        {keep('relations', <LineageView active={active === 'relations'} documentId={route.familyDoc} onOpenLive={doc => doc ? go({page:'live', doc, tab:'structure'}) : navigate('live')}/>)}
        {keep('search', <SearchPipeline active={active === 'search'} onNavigate={navigate}/>)}
        {keep('chunking', <ChunkBench active={active === 'chunking'} requestedSource={chunkSource} onSourceChange={key => go(key.startsWith('doc:') ? {page:'chunking',doc:key.slice(4)} : {page:'chunking',sample:key.slice(7)})}/>)}
        {keep('embedding', <EmbeddingEval active={active === 'embedding'}/>)}
        {keep('vectordb', <VectorDbWorkspace active={active === 'vectordb'}/>)}
        {keep('models', <ModelWorkspace/>)}
      </div>
    </main>
    {mobileMenu && <Modal open title="탐색 메뉴" size="sm" onClose={() => setMobileMenu(false)}><div className="shell-mobile-nav">{nav(true)}</div></Modal>}
    <TooltipLayer/>
    {finderOpen && <WorkspaceFinder destinations={finderItems} current={active} onClose={() => setFinderOpen(false)} onNavigate={navigate}/>}
    {current && data && <DocumentDrawer doc={current} relations={data.relations} onClose={() => setSelected(null)}
      onCompare={() => { setSelected(null); go({page:'compare', doc:current.id}); }}
      onPipeline={() => navigate('pipeline', {format:current.format})} onOpenRelated={id => { if (!data.documents.some(d => d.id === id)) return false; setSelected(id); return true; }}/>}
  </div>;
}
