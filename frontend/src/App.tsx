import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Blocks, ChevronDown, FileSearch, FlaskConical, GitBranch, Layers3, LayoutDashboard, PanelLeftClose, PanelLeftOpen, Plus, Server, ShieldCheck, Sparkles, X } from 'lucide-react';
import Dashboard from './Dashboard';
import PipelineStudio from './PipelineStudio';
import LiveWorkspace from './LiveWorkspace';
import ModelWorkspace from './ModelWorkspace';
import { FlowSimulator } from './flow/flowSim';
import { loadLibrary } from './flow/flowTemplates';
import { DocumentBrowser, DocumentDrawer, CompareView, RelationsView } from './DocumentViews';
import type { AppData, DocumentFilter, DocumentItem, Page } from './types';

const pages: Record<Page, {label: string; title: string; description: string; icon: React.ElementType}> = {
  overview: {label:'운영 대시보드',title:'운영 대시보드',description:'문서 수집부터 파싱과 색인까지, 처리 현황을 살펴봅니다.',icon:LayoutDashboard},
  documents: {label:'문서 탐색',title:'문서 탐색',description:'들어온 문서, 처리 상태와 원문 근거를 살펴봅니다.',icon:FileSearch},
  pipeline: {label:'처리 파이프라인',title:'처리 파이프라인',description:'처리 흐름을 운영하고 설계합니다.',icon:GitBranch},
  live: {label:'실제 파일 처리',title:'실제 파일 처리',description:'파일을 로컬에 저장하고 실제 파싱을 실행합니다.',icon:Server},
  compare: {label:'파싱 비교',title:'파싱 비교',description:'원문과 파서 결과의 차이를 나란히 확인합니다.',icon:FlaskConical},
  relations: {label:'문서 관계',title:'문서 관계',description:'문서 간 참조와 근거 위치를 탐색합니다.',icon:Layers3},
  models: {label:'모델 연결',title:'모델 연결',description:'서버에 설정된 모델 주소와 연결 상태를 확인합니다.',icon:Blocks},
};
const GROUP_LABEL: Record<string,string> = {MONITOR:'모니터링',WORKSPACE:'작업',SYSTEM:'시스템'};
const groups: {label:string; ids:Page[]}[] = [
  {label:'MONITOR',ids:['overview','documents']},
  {label:'WORKSPACE',ids:['pipeline','live','compare','relations']},
  {label:'SYSTEM',ids:['models']},
];
const supportedDemo = new Set(['PDF','XLSX','XLS','XLSM','DOC','DOCX','DOCM','PPT','PPTX','PNG','JPG','JPEG','TIFF','HWP','HWPX','EML','ZIP','TXT','CSV','HTM','HTML','MHT','LOG']);
const getFormat = (name:string) => { const filename=name.split(/[\\/]/).pop() || ''; const i=filename.lastIndexOf('.'); return i<=0 || i===filename.length-1 ? '확장자 없음' : filename.slice(i+1).toUpperCase(); };
const fileSize = (size:number) => size >= 1048576 ? `${(size/1048576).toFixed(1)} MB` : `${Math.max(1,Math.ceil(size/1024))} KB`;

export default function App() {
  const [data,setData]=useState<AppData|null>(null); const [error,setError]=useState(false); const [mockAttempt,setMockAttempt]=useState(0);
  const [active,setActive]=useState<Page>(()=>new URLSearchParams(window.location.search).get('view')==='pipeline'?'pipeline':'overview'); const [tabs,setTabs]=useState<Page[]>(()=>new URLSearchParams(window.location.search).get('view')==='pipeline'?['overview','pipeline']:['overview']);
  const [sidebarOpen,setSidebarOpen]=useState(()=>typeof window==='undefined'||window.innerWidth>=1000); const [groupsOpen,setGroupsOpen]=useState<Record<string,boolean>>({MONITOR:true,WORKSPACE:true,SYSTEM:true});
  const [documentFilter,setDocumentFilter]=useState<DocumentFilter>({}); const [pipelineFormat,setPipelineFormat]=useState<string|undefined>(undefined); const [pipelineRequest,setPipelineRequest]=useState(0); const [selected,setSelected]=useState<string|null>(null); const [compareId,setCompareId]=useState<string>('DOC-0842');
  const [simulator]=useState(()=>new FlowSimulator(loadLibrary())); const [pipelineFocus,setPipelineFocus]=useState<{flowId:string;nodeId?:string;n:number}|undefined>(undefined);
  const [fileNotice,setFileNotice]=useState(''); const fileInput=useRef<HTMLInputElement>(null);
  useEffect(()=>{let alive=true; fetch('/api/data').then(r=>{if(!r.ok)throw Error();return r.json()}).then((payload:AppData)=>{if(alive){setData(payload);setError(false)}}).catch(()=>{if(alive)setError(true)});return()=>{alive=false}},[mockAttempt]);
  const retryMock=()=>{setError(false);setMockAttempt(value=>value+1)};
  const navigate=useCallback((next:Page, filter?:DocumentFilter)=>{setTabs(prev=>prev.includes(next)?prev:[...prev,next]);setActive(next);if(next==='documents')setDocumentFilter(filter || {});if(next==='pipeline' && filter?.format){setPipelineFormat(filter.format);setPipelineRequest(value=>value+1)}setSelected(null)},[]);
  const openPipeline=useCallback((flowId:string,nodeId?:string)=>{setTabs(prev=>prev.includes('pipeline')?prev:[...prev,'pipeline']);setActive('pipeline');setPipelineFocus(prev=>({flowId,nodeId,n:(prev?.n??0)+1}));setSelected(null)},[]);
  const closeTab=(page:Page)=>{if(page==='overview')return; const next=tabs.filter(x=>x!==page);setTabs(next);if(active===page)setActive(next[next.length-1]||'overview')};
  const addFiles=(files: File[])=>{
    if(!files.length || !data)return;
    const additions:DocumentItem[]=files.map((file,index)=>{const format=getFormat(file.name), known=supportedDemo.has(format);return {id:`LOCAL-${Date.now()}-${index}`,name:file.name,source:'로컬 시뮬레이션',format,size:fileSize(file.size),updated:'방금 추가',status:known?'처리 대기':'형식 확인 필요',stage:'형식 확인',parser:'미지정',ocr:false,note:known?'파일 정보만 추가되었습니다. 파싱은 실행되지 않았습니다.':'새 파일 형식입니다. 처리 경로를 확인해 주세요. 파일 내용은 읽지 않았습니다.',pages:0,refs:0,text:'아직 파싱된 내용이 없습니다. 로컬 미리보기에서 파일 이름과 크기만 등록되었습니다.',compare:'아직 비교할 파싱 결과가 없습니다.',simulated:true}});
    setData(prev=>prev?{...prev,documents:[...additions,...prev.documents]}:prev);setFileNotice(`${files.length}개 파일 정보를 예시 목록에 추가했어요. 업로드와 파싱은 실행되지 않았습니다.`);setDocumentFilter({});navigate('documents');
  };
  const current=data?.documents.find(d=>d.id===selected);
  const unknownCount=data?.documents.filter(d=>d.status==='형식 확인 필요').length;
  return <div className={'shell-root '+(!sidebarOpen?'shell-collapsed':'')}>
    <aside className="shell-sidebar" aria-label="주 탐색 메뉴">
      <div className="shell-brand"><div className="shell-mark"><Layers3 size={18}/></div>{sidebarOpen&&<div className="shell-brand-text"><strong>비정형 리뷰</strong><small>Unstructured Review</small></div>}<button className="shell-sidebar-toggle" onClick={()=>setSidebarOpen(!sidebarOpen)} aria-label={sidebarOpen?'사이드바 접기':'사이드바 펼치기'} title={sidebarOpen?'사이드바 접기':'사이드바 펼치기'}>{sidebarOpen?<PanelLeftClose size={17}/>:<PanelLeftOpen size={17}/>}</button></div>
      <nav className="shell-nav">{groups.map(group=><div className="shell-nav-group" key={group.label}>{sidebarOpen&&<button className="shell-group-label" onClick={()=>setGroupsOpen({...groupsOpen,[group.label]:!groupsOpen[group.label]})} aria-expanded={groupsOpen[group.label]}><span>{GROUP_LABEL[group.label]}</span><ChevronDown className={!groupsOpen[group.label]?'shell-chevron-closed':''} size={13}/></button>}{(!sidebarOpen||groupsOpen[group.label])&&group.ids.map(id=>{const I=pages[id].icon;return <button key={id} className={'shell-nav-item '+(active===id?'is-active':'')} onClick={()=>navigate(id)} title={pages[id].label} aria-label={pages[id].label} aria-current={active===id?'page':undefined}><I size={17}/>{sidebarOpen&&<span>{pages[id].label}</span>}{sidebarOpen&&id==='pipeline'&&unknownCount!==undefined&&unknownCount>0&&<em title="경로 확인이 필요한 형식">{unknownCount}</em>}</button>})}</div>)}</nav>
    </aside>
    <main className="shell-main">
      <header className="shell-tabbar" aria-label="열린 작업 탭">{tabs.map((page,index)=>{const I=pages[page].icon;return <div className={'shell-worktab '+(page===active?'is-current':'')} key={page}><button onClick={()=>setActive(page)} aria-current={page===active?'page':undefined}><I size={15}/><span>{pages[page].label}</span></button>{index>0&&<button className="shell-tab-close" aria-label={`${pages[page].label} 탭 닫기`} onClick={()=>closeTab(page)}><X size={13}/></button>}</div>})}<span className="shell-tab-end"/>
        <div className="shell-top-right">{active!=='models'&&<span className={'shell-live '+(active==='live'?'is-real':'')} title={active==='live'?'로컬 서버에 실제 파일을 저장하고 처리합니다':'예시 데이터로 구성한 화면입니다'}><i/> {active==='live'?'실제 파일 · 로컬 처리':'예시 데이터'}</span>}{active!=='live'&&active!=='models'&&<button className="shell-add" aria-label="문서 추가 시뮬레이션" title="파일 이름·형식·크기만 예시 목록에 추가합니다" disabled={!data} onClick={()=>fileInput.current?.click()}><Plus size={15}/> <span>문서 추가</span></button>}</div>
      </header>
      <div className={'shell-content'+(active==='pipeline'?' is-fill':'')}>
        {active!=='pipeline'&&<div className="shell-title-row"><div><h1>{pages[active].title}</h1><p>{pages[active].description}</p></div>{active!=='live'&&active!=='models'&&<div className="shell-title-right">{data?`기준 ${data.asOf}`:error?'예시 데이터 오류':'예시 데이터 불러오는 중'}</div>}</div>}
        {fileNotice&&active!=='live'&&active!=='pipeline'&&<div className="shell-notice" role="status"><Sparkles size={16}/><span>{fileNotice}</span><button onClick={()=>setFileNotice('')} aria-label="안내 닫기"><X size={15}/></button></div>}
        {data&&tabs.includes('overview')&&<div hidden={active!=='overview'}><Dashboard docs={data.documents} onOpenDoc={setSelected} onNavigate={navigate} simulator={simulator} active={active==='overview'} onOpenPipeline={openPipeline}/></div>}
        {data&&tabs.includes('documents')&&<div hidden={active!=='documents'}><DocumentBrowser docs={data.documents} filter={documentFilter} onFilterChange={setDocumentFilter} onOpenDoc={setSelected} onFiles={addFiles} onPickFiles={()=>fileInput.current?.click()} onPipeline={(format)=>navigate('pipeline',{format})}/></div>}
        {tabs.includes('pipeline')&&<div className="shell-fill" hidden={active!=='pipeline'}><PipelineStudio key={pipelineRequest} active={active==='pipeline'} simulator={simulator} focus={pipelineFocus} formats={[...new Set((data?.documents||[]).map(d=>d.format))]} initialFormat={pipelineFormat} onOpenDocuments={(format)=>navigate('documents',{format:format || '확장자 없음'})} onOpenLiveDocuments={()=>navigate('live')}/></div>}
        {!data&&active!=='live'&&active!=='pipeline'&&<div className="panel shell-loading" role={error?'alert':'status'}>{error?<AlertCircle size={24}/>:<span className="shell-spinner"/>}<div><h2>{error?'예시 데이터를 불러오지 못했어요':'예시 데이터를 불러오는 중입니다'}</h2><p>{error?'예시 데이터 연결을 확인한 뒤 다시 시도해 주세요. 실제 파일 처리 화면은 별도로 이용할 수 있습니다.':'잠시만 기다려 주세요. 실제 파일 처리는 별도로 이용할 수 있습니다.'}</p></div>{error&&<button className="button-secondary" onClick={retryMock}>다시 시도</button>}</div>}
        {active==='live'&&<LiveWorkspace/>}
        {data&&tabs.includes('compare')&&<div hidden={active!=='compare'}><CompareView docs={data.documents} selectedId={compareId} onChange={setCompareId} onOpenDoc={setSelected}/></div>}
        {data&&tabs.includes('relations')&&<div hidden={active!=='relations'}><RelationsView relations={data.relations} onOpenDoc={setSelected}/></div>}
        {tabs.includes('models')&&<div hidden={active!=='models'}><ModelWorkspace/></div>}
      </div>
    </main>
    <input ref={fileInput} type="file" multiple hidden onChange={e=>{if(e.target.files)addFiles(Array.from(e.target.files));e.target.value=''}} aria-label="문서 파일 선택"/>
    {current&&data&&<DocumentDrawer doc={current} relations={data.relations} onClose={()=>setSelected(null)} onCompare={()=>{setCompareId(current.id);navigate('compare')}} onPipeline={()=>navigate('pipeline',{format:current.format})}/>}
  </div>
}
