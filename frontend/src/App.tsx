import { useCallback, useEffect, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { AlertCircle, Blocks, CalendarDays, ChevronDown, ChevronRight, Database, FileSearch, FlaskConical, Gauge, GitBranch, Layers3, LayoutDashboard, Menu, Network, PanelLeftClose, PanelLeftOpen, Plus, Scissors, Search, Server, Sparkles, Waypoints, X } from 'lucide-react';
import Dashboard from './Dashboard';
import PipelineStudio from './PipelineStudio';
import LiveWorkspace from './LiveWorkspace';
import ModelWorkspace from './ModelWorkspace';
import LineageView from './LineageView';
import ChunkBench from './ChunkBench';
import EmbeddingEval from './EmbeddingEval';
import VectorDbWorkspace from './VectorDbWorkspace';
import SearchPipeline from './SearchPipeline';
import { FlowSimulator } from './flow/flowSim';
import { loadLibrary } from './flow/flowTemplates';
import { DocumentBrowser, DocumentDrawer, CompareView } from './DocumentViews';
import { WorkspaceFinder } from './WorkspaceFinder';
import { WorkspaceIntro } from './WorkspaceIntro';
import { Modal } from './ui';
import type { CompareSource } from './CompareView';
import type { AppData, DocumentFilter, DocumentItem, Page } from './types';

const pages: Record<Page, {label: string; title: string; description: string; icon: LucideIcon}> = {
  overview: {label:'운영 대시보드',title:'운영 대시보드',description:'문서 수집부터 파싱과 색인까지, 처리 현황을 살펴봅니다.',icon:LayoutDashboard},
  documents: {label:'문서 탐색',title:'문서 탐색',description:'들어온 문서, 처리 상태와 원문 근거를 살펴봅니다.',icon:FileSearch},
  pipeline: {label:'처리 파이프라인',title:'처리 파이프라인',description:'처리 흐름을 운영하고 설계합니다.',icon:GitBranch},
  live: {label:'실제 파일 처리',title:'실제 파일 처리',description:'파일 업로드, 파싱 실행, 추출 결과와 구조 분석을 확인합니다.',icon:Server},
  compare: {label:'파싱 비교',title:'파싱 비교',description:'원문과 파서 결과의 차이를 나란히 확인합니다.',icon:FlaskConical},
  relations: {label:'문서 계보',title:'문서 계보',description:'어떤 파일이 최신인지, 무엇을 담고 있고 무엇을 가리키는지 계층으로 봅니다.',icon:Network},
  search: {label:'검색 파이프라인',title:'검색 파이프라인',description:'질의가 검색 근거로 돌아오기까지의 흐름을 살펴봅니다.',icon:Waypoints},
  chunking: {label:'청킹 벤치',title:'청킹 벤치',description:'문서가 본문·표·그림으로 어떻게 나뉘고, 전략마다 어떤 청크가 되는지 비교합니다.',icon:Scissors},
  embedding: {label:'임베딩 평가',title:'임베딩 평가',description:'여러 임베딩 모델을 본문·표·그림 질문별 검색 정확도와 입력 한도로 비교합니다.',icon:Gauge},
  vectordb: {label:'벡터 DB',title:'벡터 DB',description:'컬렉션·파티션 구성과 저장된 청크를 사람이 읽을 수 있는 형태로 확인합니다.',icon:Database},
  models: {label:'모델 연결',title:'모델 연결',description:'서버에 설정된 모델 주소와 연결 상태를 확인합니다.',icon:Blocks},
};
const GROUP_LABEL: Record<string,string> = {MONITOR:'모니터링',WORKSPACE:'문서 처리',RETRIEVAL:'검색 준비',SYSTEM:'시스템'};
const groups: {label:string; ids:Page[]}[] = [
  {label:'MONITOR',ids:['overview','documents']},
  {label:'WORKSPACE',ids:['live','pipeline','compare','relations']},
  {label:'RETRIEVAL',ids:['search','chunking','embedding','vectordb']},
  {label:'SYSTEM',ids:['models']},
];
const destinations = groups.flatMap(group => group.ids.map(id => ({ id, group: GROUP_LABEL[group.label], ...pages[id] })));
const pageGroup = Object.fromEntries(destinations.map(page => [page.id, page.group]));
const shortcut = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

/** 예시(Mock) 데이터로 그리는 화면. 나머지 화면은 각자 데이터 출처를 표시한다. */
const MOCK_PAGES = new Set<Page>(['overview','documents','pipeline']);
const supportedDemo = new Set(['PDF','XLSX','XLS','XLSM','DOC','DOCX','DOCM','PPT','PPTX','PNG','JPG','JPEG','TIFF','HWP','HWPX','EML','ZIP','TXT','CSV','HTM','HTML','MHT','LOG']);
const getFormat = (name:string) => { const filename=name.split(/[\\/]/).pop() || ''; const i=filename.lastIndexOf('.'); return i<=0 || i===filename.length-1 ? '확장자 없음' : filename.slice(i+1).toUpperCase(); };
const fileSize = (size:number) => size >= 1048576 ? `${(size/1048576).toFixed(1)} MB` : `${Math.max(1,Math.ceil(size/1024))} KB`;

export default function App() {
  const [data,setData]=useState<AppData|null>(null); const [error,setError]=useState(false); const [mockAttempt,setMockAttempt]=useState(0);
  const [active,setActive]=useState<Page>(()=>new URLSearchParams(window.location.search).get('view')==='pipeline'?'pipeline':'overview'); const [tabs,setTabs]=useState<Page[]>(()=>new URLSearchParams(window.location.search).get('view')==='pipeline'?['overview','pipeline']:['overview']);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [finderOpen, setFinderOpen] = useState(false);
  const [liveUploading, setLiveUploading] = useState(false);
  const [groupsOpen, setGroupsOpen] = useState<Record<string, boolean>>({ MONITOR: true, WORKSPACE: true, RETRIEVAL: true, SYSTEM: true });
  const tabStrip = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const nextFocus = useRef<'content' | 'tab' | null>(null);
  const [documentFilter,setDocumentFilter]=useState<DocumentFilter>({}); const [pipelineFormat,setPipelineFormat]=useState<string|undefined>(undefined); const [pipelineRequest,setPipelineRequest]=useState(0); const [selected,setSelected]=useState<string|null>(null); const [compareId,setCompareId]=useState<string>('DOC-0842');
  const [compareSource, setCompareSource] = useState<CompareSource>('sample');
  const [liveCompareId, setLiveCompareId] = useState('');
  const [simulator]=useState(()=>new FlowSimulator(loadLibrary())); const [pipelineFocus,setPipelineFocus]=useState<{flowId:string;nodeId?:string;n:number}|undefined>(undefined);
  const [fileNotice,setFileNotice]=useState(''); const fileInput=useRef<HTMLInputElement>(null);
  useEffect(()=>{let alive=true; fetch('/api/data').then(r=>{if(!r.ok)throw Error();return r.json()}).then((payload:AppData)=>{if(alive){setData(payload);setError(false)}}).catch(()=>{if(alive)setError(true)});return()=>{alive=false}},[mockAttempt]);
  const retryMock=()=>{setError(false);setMockAttempt(value=>value+1)};
  const navigate=useCallback((next:Page, filter?:DocumentFilter)=>{setTabs(prev=>prev.includes(next)?prev:[...prev,next]);setActive(next);if(next==='documents')setDocumentFilter(filter || {});if(next==='pipeline' && filter?.format){setPipelineFormat(filter.format);setPipelineRequest(value=>value+1)}setSelected(null)},[]);
  const navigateToContent = useCallback((next: Page, filter?: DocumentFilter) => {
    nextFocus.current = 'content';
    navigate(next, filter);
  }, [navigate]);
  const openPipeline=useCallback((flowId:string,nodeId?:string)=>{nextFocus.current='content';setTabs(prev=>prev.includes('pipeline')?prev:[...prev,'pipeline']);setActive('pipeline');setPipelineFocus(prev=>({flowId,nodeId,n:(prev?.n??0)+1}));setSelected(null)},[]);
  const closeTab = (page: Page) => {
    if (page === 'overview') return;
    const next = tabs.filter(tab => tab !== page);
    nextFocus.current = 'tab';
    setTabs(next);
    if (active === page) {
      setActive(next[next.length - 1]);
      setSelected(null);
    }
  };
  const switchTab = (page: Page) => { setActive(page); setSelected(null); };
  const addFiles=(files: File[])=>{
    if(!files.length || !data)return;
    const additions:DocumentItem[]=files.map((file,index)=>{const format=getFormat(file.name), known=supportedDemo.has(format);return {id:`LOCAL-${Date.now()}-${index}`,name:file.name,source:'로컬 시뮬레이션',format,size:fileSize(file.size),updated:'방금 추가',status:known?'처리 대기':'형식 확인 필요',stage:'형식 확인',parser:'미지정',ocr:false,note:known?'파일 정보만 추가되었습니다. 파싱은 실행되지 않았습니다.':'새 파일 형식입니다. 처리 경로를 확인해 주세요. 파일 내용은 읽지 않았습니다.',pages:0,refs:0,text:'아직 파싱된 내용이 없습니다. 로컬 미리보기에서 파일 이름과 크기만 등록되었습니다.',compare:'아직 비교할 파싱 결과가 없습니다.',simulated:true}});
    setData(prev=>prev?{...prev,documents:[...additions,...prev.documents]}:prev);setFileNotice(`${files.length}개 파일 정보를 예시 목록에 추가했어요. 업로드와 파싱은 실행되지 않았습니다.`);setDocumentFilter({});navigate('documents');
  };
  useEffect(() => {
    const openFinder = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.key.toLowerCase() !== 'k') return;
      if (document.querySelector('[aria-modal="true"]')) return;
      event.preventDefault();
      setFinderOpen(true);
    };
    window.addEventListener('keydown', openFinder);
    return () => window.removeEventListener('keydown', openFinder);
  }, []);
  useEffect(() => {
    const strip = tabStrip.current;
    const tab = strip?.querySelector<HTMLElement>('.is-current');
    if (strip && tab) {
      const viewport = strip.getBoundingClientRect();
      const current = tab.getBoundingClientRect();
      if (current.right > viewport.right) strip.scrollLeft += current.right - viewport.right;
      if (current.left < viewport.left) strip.scrollLeft -= viewport.left - current.left;
    }
  }, [active, tabs]);
  useEffect(() => {
    document.scrollingElement?.scrollTo?.({ top: 0 });
  }, [active]);
  useEffect(() => {
    if (nextFocus.current === 'content') {
      const heading = content.current?.querySelector<HTMLElement>('.shell-title-row h1, .shell-fill:not([hidden]) .ps-title h1');
      (heading ?? content.current)?.focus({ preventScroll: true });
    } else if (nextFocus.current === 'tab') {
      tabStrip.current?.querySelector<HTMLElement>('.is-current > button')?.focus({ preventScroll: true });
    }
    nextFocus.current = null;
  }, [active, tabs, finderOpen, mobileMenu, pipelineRequest, pipelineFocus]);

  const current=data?.documents.find(d=>d.id===selected);
  const unknownCount=data?.documents.filter(d=>d.status==='형식 확인 필요').length;
  const renderNavigation = (expanded: boolean, mobile = false) => <nav className="shell-nav" aria-label={mobile ? '모바일 탐색' : undefined}>
    {groups.map(group => <div className="shell-nav-group" key={group.label}>
      {expanded && <button className="shell-group-label" onClick={() => setGroupsOpen(state => ({ ...state, [group.label]: !state[group.label] }))}
        aria-expanded={groupsOpen[group.label]}>
        <span>{GROUP_LABEL[group.label]}</span><ChevronDown className={groupsOpen[group.label] ? '' : 'shell-chevron-closed'} size={14} aria-hidden="true" />
      </button>}
      {(!expanded || groupsOpen[group.label]) && group.ids.map(id => {
        const Icon = pages[id].icon;
        return <button key={id} className={`shell-nav-item${active === id ? ' is-active' : ''}`} onClick={() => {
            if (mobile && active !== id) navigateToContent(id); else navigate(id);
            setMobileMenu(false);
          }}
          title={pages[id].label} aria-label={pages[id].label} aria-current={active === id ? 'page' : undefined}>
          <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
          {expanded && <span>{pages[id].label}</span>}
          {expanded && id === 'pipeline' && !!unknownCount && <em title="경로 확인이 필요한 예시 형식">{unknownCount}</em>}
        </button>;
      })}
    </div>)}
  </nav>;

  return <div className={`shell-root${sidebarOpen ? '' : ' shell-collapsed'}`}>
    <a className="shell-skip" href="#workspace-content">본문으로 건너뛰기</a>
    <aside className="shell-sidebar" aria-label="주 탐색 메뉴">
      <div className="shell-brand">
        <div className="shell-mark"><Layers3 size={21} strokeWidth={1.7} aria-hidden="true" /></div>
        {sidebarOpen && <div className="shell-brand-text"><strong>비정형 관리 콘솔</strong><small>Unstructured Data Console</small></div>}
        <button className="shell-sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label={sidebarOpen ? '사이드바 접기' : '사이드바 펼치기'}
          title={sidebarOpen ? '사이드바 접기' : '사이드바 펼치기'} aria-expanded={sidebarOpen}>
          {sidebarOpen ? <PanelLeftClose size={17} aria-hidden="true" /> : <PanelLeftOpen size={17} aria-hidden="true" />}
        </button>
      </div>
      {renderNavigation(sidebarOpen)}
      <div className="shell-environment" title="로컬 워크스페이스">
        <span className="shell-environment-icon"><Server size={16} strokeWidth={1.7} aria-hidden="true" /></span>
        {sidebarOpen && <span>로컬 워크스페이스</span>}
      </div>
    </aside>
    <main className="shell-main">
      <header className="shell-header">
        <div className="shell-topbar">
          <button className="shell-menu-toggle" onClick={() => setMobileMenu(true)} aria-label="탐색 메뉴 열기" aria-expanded={mobileMenu}><Menu size={21} aria-hidden="true" /></button>
          <div className="shell-breadcrumb" aria-label="현재 위치">
            <span>{pageGroup[active]}</span><ChevronRight size={14} aria-hidden="true" /><strong>{pages[active].label}</strong>
          </div>
          <div className="shell-top-right">
            {(MOCK_PAGES.has(active) || active === 'live') && <span className={`shell-live${active === 'live' ? ' is-real' : ''}`}>
              <i aria-hidden="true" />{active === 'live' ? '로컬 파일' : '예시 데이터'}
            </span>}
            <button className="shell-finder-trigger" onClick={() => setFinderOpen(true)} aria-label="화면 찾기" aria-keyshortcuts="Meta+K Control+K" title="화면 찾기">
              <Search size={17} aria-hidden="true" /><span>화면 찾기</span><kbd aria-hidden="true">{shortcut}</kbd>
            </button>
          </div>
        </div>
        <div className="shell-tabbar" aria-label="열린 작업 탭">
          <div className="shell-tabstrip" ref={tabStrip}>{tabs.map((page, index) => {
            const Icon = pages[page].icon;
            return <div className={`shell-worktab${page === active ? ' is-current' : ''}`} key={page}>
              <button onClick={() => switchTab(page)} aria-current={page === active ? 'page' : undefined}>
                <Icon size={16} strokeWidth={1.8} aria-hidden="true" /><span>{pages[page].label}</span>
              </button>
              {index > 0 && <button className="shell-tab-close" aria-label={`${pages[page].label} 탭 닫기`} onClick={() => closeTab(page)}
                disabled={page === 'live' && liveUploading} title={page === 'live' && liveUploading ? '파일 저장이 끝나면 탭을 닫을 수 있습니다' : undefined}>
                {page === 'live' && liveUploading ? <span className="shell-tab-progress" /> : <X size={15} aria-hidden="true" />}
              </button>}
            </div>;
          })}</div>
          {active === 'documents' && <button className="shell-add button-secondary" aria-label="문서 추가 시뮬레이션" title="파일 이름·형식·크기만 예시 목록에 추가합니다"
            disabled={!data} onClick={() => fileInput.current?.click()}><Plus size={16} aria-hidden="true" /><span>예시 추가</span></button>}
        </div>
      </header>
      <div id="workspace-content" ref={content} tabIndex={-1} className={`shell-content${active === 'pipeline' ? ' is-fill' : ''}`}>
        {active !== 'pipeline' && <div className="shell-title-row">
          <div><h1 tabIndex={-1}>{pages[active].title}</h1><p>{pages[active].description}</p></div>
          {data && MOCK_PAGES.has(active) && <div className="shell-title-right"><CalendarDays size={16} aria-hidden="true" /><span>예시 기준</span><b>{data.asOf}</b></div>}
        </div>}
        {active === 'overview' && <WorkspaceIntro onLive={() => navigateToContent('live')} onExamples={() => navigateToContent('documents')} />}
        {fileNotice&&MOCK_PAGES.has(active)&&active!=='pipeline'&&<div className="shell-notice" role="status"><Sparkles size={16}/><span>{fileNotice}</span><button onClick={()=>setFileNotice('')} aria-label="안내 닫기"><X size={15}/></button></div>}
        {data&&tabs.includes('overview')&&<div hidden={active!=='overview'}><Dashboard docs={data.documents} onOpenDoc={setSelected} onNavigate={navigateToContent} simulator={simulator} active={active==='overview'} onOpenPipeline={openPipeline}/></div>}
        {data&&tabs.includes('documents')&&<div hidden={active!=='documents'}><DocumentBrowser docs={data.documents} filter={documentFilter} onFilterChange={setDocumentFilter} onOpenDoc={setSelected} onFiles={addFiles} onPickFiles={()=>fileInput.current?.click()} onPipeline={format => navigateToContent('pipeline', { format })}/></div>}
        {tabs.includes('pipeline')&&<div className="shell-fill" hidden={active!=='pipeline'}><PipelineStudio key={pipelineRequest} active={active==='pipeline'} simulator={simulator} focus={pipelineFocus} formats={[...new Set((data?.documents||[]).map(d=>d.format))]} initialFormat={pipelineFormat} onOpenDocuments={format => navigateToContent('documents', { format: format || '확장자 없음' })} onOpenLiveDocuments={() => navigateToContent('live')}/></div>}
        {!data&&MOCK_PAGES.has(active)&&active!=='pipeline'&&<div className="panel shell-loading" role={error?'alert':'status'}>{error?<AlertCircle size={24}/>:<span className="shell-spinner"/>}<div><h2>{error?'예시 데이터를 불러오지 못했어요':'예시 데이터를 불러오는 중입니다'}</h2><p>{error?'예시 데이터 연결을 확인한 뒤 다시 시도해 주세요. 실제 파일 처리 화면은 별도로 이용할 수 있습니다.':'잠시만 기다려 주세요. 실제 파일 처리는 별도로 이용할 수 있습니다.'}</p></div>{error&&<button className="button-secondary" onClick={retryMock}>다시 시도</button>}</div>}
        {tabs.includes('live') && <div hidden={active !== 'live'}>
          <LiveWorkspace onUploadStateChange={setLiveUploading} onOpenCompare={id => { setLiveCompareId(id); setCompareSource('live'); navigateToContent('compare'); }} />
        </div>}
        {tabs.includes('compare')&&<div hidden={active!=='compare'}><CompareView docs={data?.documents ?? []} selectedId={compareId} onChange={setCompareId} onOpenDoc={setSelected}
          source={compareSource} onSourceChange={setCompareSource} liveId={liveCompareId} onLiveChange={setLiveCompareId} active={active==='compare'}
          sampleStatus={data ? 'ready' : error ? 'error' : 'loading'} onRetrySample={retryMock} onOpenLive={() => navigateToContent('live')} /></div>}
        {tabs.includes('relations')&&<div hidden={active!=='relations'}><LineageView active={active === 'relations'} onOpenLive={() => navigateToContent('live')} /></div>}
        {tabs.includes('search')&&<div hidden={active!=='search'}><SearchPipeline active={active==='search'} onNavigate={page => navigateToContent(page)}/></div>}
        {tabs.includes('chunking')&&<div hidden={active!=='chunking'}><ChunkBench active={active==='chunking'}/></div>}
        {tabs.includes('embedding')&&<div hidden={active!=='embedding'}><EmbeddingEval active={active==='embedding'}/></div>}
        {tabs.includes('vectordb')&&<div hidden={active!=='vectordb'}><VectorDbWorkspace active={active==='vectordb'}/></div>}
        {tabs.includes('models')&&<div hidden={active!=='models'}><ModelWorkspace/></div>}
      </div>
    </main>
    {mobileMenu && <Modal open title="탐색 메뉴" size="sm" onClose={() => setMobileMenu(false)}>
      <div className="shell-mobile-nav">{renderNavigation(true, true)}</div>
    </Modal>}
    {finderOpen && <WorkspaceFinder destinations={destinations} current={active} onClose={() => setFinderOpen(false)} onNavigate={page => { setFinderOpen(false); navigateToContent(page); }} />}
    <input ref={fileInput} type="file" multiple hidden onChange={e=>{if(e.target.files)addFiles(Array.from(e.target.files));e.target.value=''}} aria-label="문서 파일 선택"/>
    {current && data && <DocumentDrawer doc={current} relations={data.relations} onClose={() => setSelected(null)}
      onCompare={() => { setCompareId(current.id); setCompareSource('sample'); navigateToContent('compare'); }}
      onPipeline={() => navigateToContent('pipeline', { format: current.format })}
      onOpenRelated={id => {
        if (!data.documents.some(doc => doc.id === id)) return false;
        setSelected(id);
        return true;
      }} />}
  </div>
}
