import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Clock3, FileCode2, FileText, FolderOpen, Info, LoaderCircle, Play, RefreshCw, Search, Server, UploadCloud, XCircle } from 'lucide-react';
import { getLiveDocument, getLiveResult, listLiveDocuments, processLiveDocument, uploadLiveDocument } from './api/live';
import type { LiveDoc, LiveResult, LiveStatus } from './api/live';
import './live.css';
import { StructureOverviewStrip, StructurePanel } from './StructurePanel';

type Filter = 'all' | LiveStatus;
const statuses: Record<LiveStatus, { label: string; description: string }> = {
 uploaded:{label:'업로드됨',description:'로컬 저장이 완료되었습니다. 처리를 실행할 수 있습니다.'},
 processing:{label:'처리 중 / 대기',description:'작업이 대기 중이거나 서버에서 파싱을 진행하고 있습니다.'},
 completed:{label:'처리 완료',description:'파싱 결과를 확인할 수 있습니다.'},
 failed:{label:'처리 실패',description:'처리 중 문제가 발생했습니다. 오류 내용을 확인하세요.'},
 unsupported:{label:'지원 안 됨',description:'현재 처리할 수 없는 형식입니다.'},
};
const filterOptions: {id:Filter; label:string}[] = [
 {id:'all',label:'전체'},{id:'uploaded',label:'업로드됨'},{id:'processing',label:'처리 중 / 대기'},{id:'completed',label:'완료'},{id:'failed',label:'실패'},{id:'unsupported',label:'지원 안 됨'}
];
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 120;

function displaySize(bytes:number) {
 if (!Number.isFinite(bytes) || bytes < 0) return '크기 미확인';
 if (bytes < 1024) return `${bytes} B`;
 if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
 if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
 return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
function displayDate(value:string) {
 const date = new Date(value);
 if (!value || Number.isNaN(date.getTime())) return '시간 미확인';
 return new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date);
}
function displayError(error:unknown) { return error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'; }
function Badge({status}:{status:LiveStatus}) { const s = statuses[status] || {label:status}; return <span className={'live-status live-status-'+status}><i/>{s.label}</span>; }

export default function LiveWorkspace() {
 const [documents,setDocuments]=useState<LiveDoc[]>([]);
 const [loading,setLoading]=useState(true);
 const [listError,setListError]=useState('');
 const [actionError,setActionError]=useState('');
 const [notice,setNotice]=useState('');
 const [uploading,setUploading]=useState(false);
 const [uploadProgress,setUploadProgress]=useState({done:0,total:0});
 const [dragging,setDragging]=useState(false);
 const [filter,setFilter]=useState<Filter>('all');
 const [query,setQuery]=useState('');
 const [selectedId,setSelectedId]=useState<string|null>(null);
 const [detailLoading,setDetailLoading]=useState(false);
 const [result,setResult]=useState<LiveResult|null>(null);
 const [resultLoading,setResultLoading]=useState(false);
 const [resultError,setResultError]=useState('');
 const [processingId,setProcessingId]=useState<string|null>(null);
 const [pollExhausted,setPollExhausted]=useState(false);
 const [structureKey,setStructureKey]=useState(0);
 const pollCount=useRef(0);
 const watchedJobs=useRef(new Set<string>());
 const inputRef=useRef<HTMLInputElement>(null);
 const mounted=useRef(false);
 const current=documents.find(doc=>doc.id===selectedId) || null;
 const processingCount=documents.filter(doc=>doc.status==='processing').length;
 const filtered=useMemo(()=>documents.filter(doc=>(filter==='all'||doc.status===filter)&&`${doc.name} ${doc.format} ${doc.id}`.toLowerCase().includes(query.toLowerCase())),[documents,filter,query]);
 const counts=useMemo(()=>({all:documents.length,uploaded:documents.filter(d=>d.status==='uploaded').length,processing:processingCount,completed:documents.filter(d=>d.status==='completed').length,failed:documents.filter(d=>d.status==='failed').length,unsupported:documents.filter(d=>d.status==='unsupported').length}),[documents,processingCount]);

 const refresh=useCallback(async (manual=false) => {
  if(manual){pollCount.current=0;setPollExhausted(false)}
  try {
   const body=await listLiveDocuments();
   if(mounted.current){setDocuments(body);setListError('')}
  } catch(error) { if(mounted.current)setListError(displayError(error)); }
  finally { if(mounted.current)setLoading(false); }
 },[]);
 useEffect(()=>{mounted.current=true;void refresh();return()=>{mounted.current=false}},[refresh]);
 useEffect(()=>{
  if(!processingCount){pollCount.current=0;setPollExhausted(false);return}
  if(pollExhausted)return;
  let inFlight=false;
  const timer=window.setInterval(()=>{
   if(inFlight)return;
   pollCount.current+=1;
   if(pollCount.current>MAX_POLL_ATTEMPTS){window.clearInterval(timer);setPollExhausted(true);return}
   inFlight=true;
   void refresh().finally(()=>{inFlight=false});
  },POLL_INTERVAL_MS);
  return()=>window.clearInterval(timer);
 },[processingCount,pollExhausted,refresh]);
 useEffect(()=>{
  for(const doc of documents){
   if(!watchedJobs.current.has(doc.id))continue;
   if(doc.status==='completed'){
    watchedJobs.current.delete(doc.id);setActionError('');setNotice(`${doc.name} 파싱이 완료되었습니다. 결과를 확인해 주세요.`);
   }else if(doc.status==='failed'||doc.status==='unsupported'){
    watchedJobs.current.delete(doc.id);setNotice('');setActionError(`${doc.name}: ${doc.status==='failed'?'파싱에 실패했습니다.':'지원하지 않는 형식입니다.'} 상세 상태를 확인해 주세요.`);
   }
  }
 },[documents]);
 useEffect(()=>{
  if(!selectedId)return;
  const controller=new AbortController();setDetailLoading(true);
  void getLiveDocument(selectedId,controller.signal)
   .then(detail=>{if(mounted.current)setDocuments(prev=>prev.map(item=>item.id===detail.id&&new Date(detail.updated_at).getTime()>=new Date(item.updated_at).getTime()?detail:item))})
   .catch(error=>{if(error?.name!=='AbortError'&&mounted.current)setActionError(displayError(error))})
   .finally(()=>{if(!controller.signal.aborted&&mounted.current)setDetailLoading(false)});
  return()=>controller.abort();
 },[selectedId]);
 useEffect(()=>{
  setResult(null);setResultError('');
  if(!current || !['processing','completed','failed','unsupported'].includes(current.status)){setResultLoading(false);return}
  const controller=new AbortController();setResultLoading(true);
  void getLiveResult(current.id,controller.signal)
   .then(body=>{if(!controller.signal.aborted&&mounted.current)setResult(body)})
   .catch(error=>{if(!controller.signal.aborted&&error?.name!=='AbortError'&&mounted.current)setResultError(displayError(error))})
   .finally(()=>{if(!controller.signal.aborted&&mounted.current)setResultLoading(false)});
  return()=>controller.abort();
 },[current?.id,current?.status,current?.updated_at]);

 async function upload(files:File[]) {
  if(!files.length || uploading)return;
  setUploading(true);setActionError('');setNotice('');setUploadProgress({done:0,total:files.length});
  const errors:string[]=[];let success=0;let lastId:string|null=null;
  for(const file of files){
   try {
    const doc=await uploadLiveDocument(file);
    if(!mounted.current)return;
    success++;lastId=doc.id;
    setDocuments(prev=>[doc,...prev.filter(item=>item.id!==doc.id)]);
   } catch(error) {errors.push(`${file.name}: ${displayError(error)}`)}
   if(mounted.current)setUploadProgress(prev=>({...prev,done:prev.done+1}));
  }
  if(!mounted.current)return;
  if(lastId){setSelectedId(lastId);setFilter('all');setQuery('')}
  if(success)setNotice(`${success}개 파일을 이 컴퓨터의 로컬 저장소에 저장했습니다. 파싱은 별도로 실행해 주세요.`);
  if(errors.length)setActionError(errors.join('\n'));
  setUploading(false);
 }
 async function process(doc:LiveDoc) {
  if(processingId || doc.status==='processing')return;
  setProcessingId(doc.id);setActionError('');setNotice('');pollCount.current=0;setPollExhausted(false);
  try {
   const updated=await processLiveDocument(doc.id);
   if(mounted.current){
    if(updated.status==='processing'){watchedJobs.current.add(updated.id);setNotice('파싱 작업이 접수되었습니다. 대기 또는 처리 상태를 자동으로 확인합니다.')}
    else if(updated.status==='completed'){setNotice(`${updated.name} 파싱이 완료되었습니다. 결과를 확인해 주세요.`)}
    else if(updated.status==='failed'||updated.status==='unsupported'){setActionError(`${updated.name}: ${updated.status==='failed'?'파싱에 실패했습니다.':'지원하지 않는 형식입니다.'} 상세 상태를 확인해 주세요.`)}
    setDocuments(prev=>prev.map(item=>item.id===updated.id?updated:item));setSelectedId(updated.id);
   }
  } catch(error){if(mounted.current)setActionError(displayError(error))}
  finally{if(mounted.current)setProcessingId(null)}
 }
 const onDrop=(event:React.DragEvent<HTMLDivElement>)=>{event.preventDefault();setDragging(false);void upload(Array.from(event.dataTransfer.files))};
 return <div className="live-root">
  <div className="live-mode-banner"><div className="live-mode-icon"><Server size={18}/></div><div><strong>실제 파일 작업 공간</strong><p>선택하거나 끌어온 파일은 이 컴퓨터의 백엔드 저장소에 업로드됩니다. 파싱은 직접 실행할 때 시작합니다.</p></div><span>LOCAL BACKEND</span></div>
  <div className="live-summary"><div><span>저장된 문서</span><strong>{counts.all}<small>건</small></strong></div><div><span>처리 대기</span><strong>{counts.uploaded}<small>건</small></strong></div><div><span>처리 중 / 대기</span><strong>{counts.processing}<small>건</small></strong></div><div><span>처리 완료</span><strong>{counts.completed}<small>건</small></strong></div><div><span>실패 · 미지원</span><strong>{counts.failed+counts.unsupported}<small>건</small></strong></div></div>
  <StructureOverviewStrip documents={documents} refreshKey={structureKey} onInspected={()=>setStructureKey(value=>value+1)}/>
  <div className={'live-dropzone '+(dragging?'live-dropzone-over':'')+(uploading?' live-dropzone-busy':'')} onDragOver={e=>{e.preventDefault();if(!uploading)setDragging(true)}} onDragLeave={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node|null))setDragging(false)}} onDrop={onDrop}>
   <div className="live-drop-icon">{uploading?<LoaderCircle className="live-spin" size={21}/>:<UploadCloud size={21}/>}</div><div className="live-drop-text"><strong>{uploading?`로컬에 저장하는 중 ${uploadProgress.done} / ${uploadProgress.total}`:'실제 파일을 여기에 놓아 업로드'}</strong><p>파일을 선택하거나 놓으면 즉시 로컬에 저장됩니다. 원본 파일은 자동으로 파싱되지 않습니다.</p></div><button className="live-primary" disabled={uploading} onClick={()=>inputRef.current?.click()}><UploadCloud size={15}/> 파일 선택</button><input type="file" multiple hidden ref={inputRef} onChange={event=>{if(event.target.files)void upload(Array.from(event.target.files));event.target.value=''}} aria-label="로컬에 업로드할 파일 선택"/>
  </div>
  <div className="live-format-note"><Info size={15}/><span>TXT·CSV는 로컬에서 처리합니다. 다른 형식은 해당 파서와 Docling 모델 준비가 필요할 수 있습니다. 스캔 이미지 OCR은 아직 비활성화되어 있습니다. 기존 Mock 목록과 별도로 관리됩니다.</span></div>
  {notice&&<div className="live-feedback live-feedback-success" role="status"><CheckCircle2 size={16}/><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="안내 닫기">×</button></div>}
  {actionError&&<div className="live-feedback live-feedback-error" role="alert"><AlertCircle size={16}/><span>{actionError}</span><button onClick={()=>setActionError('')} aria-label="오류 닫기">×</button></div>}
  {pollExhausted&&<div className="live-feedback live-feedback-warning" role="status"><AlertTriangle size={16}/><span>자동 상태 확인을 잠시 멈췄습니다. 새로고침 버튼으로 현재 상태를 확인하세요.</span><button onClick={()=>void refresh(true)}>새로고침</button></div>}
  <div className="live-workspace-grid">
   <section className="live-panel live-list-panel"><div className="live-panel-heading"><div><span className="live-kicker">LOCAL FILES</span><h2>업로드 문서 <small>{documents.length}</small></h2><p>문서를 선택해 상태와 결과를 확인하세요.</p></div><button className="live-icon-button" onClick={()=>void refresh(true)} title="문서 목록 새로고침" aria-label="문서 목록 새로고침"><RefreshCw size={16}/></button></div>
    <div className="live-search"><Search size={15}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="파일명, 확장자, ID 검색" aria-label="실제 문서 검색"/></div><div className="live-filters" aria-label="처리 상태 필터">{filterOptions.map(option=><button key={option.id} onClick={()=>setFilter(option.id)} className={filter===option.id?'live-filter-active':''} aria-pressed={filter===option.id}>{option.label}<span>{counts[option.id]}</span></button>)}</div>
    {listError&&<div className="live-inline-error"><AlertCircle size={15}/><span>목록을 불러오지 못했습니다: {listError}</span><button onClick={()=>void refresh(true)}>다시 시도</button></div>}
    <div className="live-list">{loading?<div className="live-empty"><LoaderCircle size={22} className="live-spin"/><strong>문서 목록을 불러오는 중</strong></div>:filtered.length===0?<div className="live-empty"><FolderOpen size={25}/><strong>{documents.length?'조건에 맞는 문서가 없습니다':'업로드된 문서가 없습니다'}</strong><span>{documents.length?'검색어나 필터를 변경해 보세요.':'위에서 파일을 선택하면 이곳에 표시됩니다.'}</span></div>:filtered.map(doc=><button className={'live-file-row '+(doc.id===selectedId?'live-file-selected':'')} key={doc.id} onClick={()=>{setSelectedId(doc.id);setActionError('')}}><span className="live-file-icon"><FileText size={18}/></span><span className="live-file-info"><strong title={doc.name}>{doc.name}</strong><small>{doc.format || '확장자 없음'} · {displaySize(doc.size_bytes)} · {displayDate(doc.updated_at)}</small></span><Badge status={doc.status}/><ChevronRight size={15} className="live-row-arrow"/></button>)}</div>
   </section>
   <section className="live-panel live-detail-panel"><div className="live-panel-heading"><div><span className="live-kicker">DOCUMENT INSPECTOR</span><h2>문서 상세</h2><p>실행 상태와 파싱 결과를 확인합니다.</p></div>{detailLoading&&<LoaderCircle className="live-spin" size={17}/>}</div>
    {!current?<div className="live-detail-empty"><div><FileCode2 size={24}/></div><strong>문서를 선택해 주세요</strong><p>실제 문서의 파일 정보와 파싱 결과가 이곳에 표시됩니다.</p></div>:<><div className="live-detail-title"><span className="live-detail-icon"><FileText size={20}/></span><div><span>{current.id}</span><h3 title={current.name}>{current.name}</h3></div><Badge status={current.status}/></div>
    <div className={'live-state-callout live-state-'+current.status}><span>{current.status==='processing'?<LoaderCircle size={16} className="live-spin"/>:current.status==='completed'?<CheckCircle2 size={16}/>:current.status==='uploaded'?<Clock3 size={16}/>:<AlertCircle size={16}/>}</span><div><strong>{statuses[current.status]?.label || current.status}</strong><p>{statuses[current.status]?.description || '처리 상태를 확인해 주세요.'}</p></div></div>
    <dl className="live-detail-meta"><div><dt>파일 형식</dt><dd>{current.format || '확장자 없음'}</dd></div><div><dt>파일 크기</dt><dd>{displaySize(current.size_bytes)}</dd></div><div><dt>저장 시각</dt><dd>{displayDate(current.created_at)}</dd></div><div><dt>마지막 변경</dt><dd>{displayDate(current.updated_at)}</dd></div><div><dt>적용 파서</dt><dd>{current.parser || '아직 지정되지 않음'}</dd></div></dl>
    {(current.status==='failed'||current.status==='unsupported')&&current.error&&<div className="live-error-detail"><span><AlertTriangle size={15}/> 처리 오류</span><pre>{current.error}</pre><p>파서 미설치 또는 모델 파일 미준비가 원인일 수 있습니다. 오류 내용을 확인해 주세요.</p></div>}
    <div className="live-actions"><button className="live-primary" disabled={current.status==='processing'||!!processingId} onClick={()=>void process(current)}>{processingId===current.id?<LoaderCircle size={15} className="live-spin"/>:<Play size={15}/>} {current.status==='uploaded'?'파싱 실행':'다시 파싱 실행'}</button><span>이 버튼을 누르면 실제 처리가 시작됩니다.</span></div>
    <StructurePanel key={current.id} doc={current} onInspected={()=>setStructureKey(value=>value+1)}/>
    <div className="live-result"><div className="live-result-head"><div><FileCode2 size={16}/><strong>파싱 결과</strong></div>{result&&<span>{result.parser} {result.parser_version}</span>}</div>{resultLoading?<div className="live-result-placeholder"><LoaderCircle className="live-spin" size={17}/> 결과를 불러오는 중</div>:resultError?<div className="live-result-placeholder live-result-error" role="alert"><AlertCircle size={17}/> {resultError}</div>:result?<>{result.is_stale&&<div className="live-feedback live-feedback-warning" role="status" style={{margin:'0 19px 10px'}}><AlertTriangle size={16}/><span><strong>이전 성공 결과 · 현재 작업 결과 아님</strong><br/>현재 처리 상태와 별개로 마지막 성공 결과를 표시합니다.</span></div>}{Array.isArray(result.warnings)&&result.warnings.length>0&&<div className="live-feedback live-feedback-warning" role="alert" style={{margin:'0 19px 10px'}}><AlertTriangle size={16}/><span><strong>파싱 경고</strong>{result.warnings.map((warning,index)=><span key={index} style={{display:'block',marginTop:'4px'}}>{warning}</span>)}</span></div>}<pre className="live-result-content">{result.markdown || '텍스트 결과가 비어 있습니다.'}</pre></>:<div className="live-result-placeholder">{current.status==='uploaded'?'파싱을 실행하면 추출 결과가 여기에 표시됩니다.':'이전에 성공한 파싱 결과가 없습니다.'}</div>}<div className="live-result-foot">결과는 서식이 적용되지 않은 텍스트로 표시됩니다.</div></div></>}
   </section>
  </div>
 </div>
}
