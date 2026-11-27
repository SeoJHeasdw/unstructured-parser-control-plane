import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Scissors, Workflow, CheckCircle2, CircleAlert, Clock3, FilePlus2, FolderInput, FolderOpen, ListFilter, LoaderCircle, RefreshCw, Search, ArrowDownWideNarrow, FileType2 } from 'lucide-react';
import { LiveRequestError, getDocumentsByIds, getLiveDocument, getLiveResult, listDocumentPage, processLiveDocument, uploadLiveDocument } from './api/live';
import type { DocPage, DocSort, LiveDoc, LiveResult, ProcessOptions } from './api/live';
import LiveDocumentView, { DocNumber, displayDate, displaySize, displayStatus, FileGlyph, isNoTextImage, matchesDocQuery, statusNote, StatusBadge } from './LiveDocumentView';
import type { DisplayStatus } from './LiveDocumentView';
import { ArrowLeft } from 'lucide-react';
import { DocumentRuns } from './compare/LiveCompare';
import { QcStateBadge } from './compare/QcGate';
import { QcFunnel } from './QcFunnel';
import { workspaceHref, type WorkspaceRoute } from './navigation';
import { WorkspaceLink } from './WorkspaceLink';
import FolderImport from './FolderImport';
import './live.css';

type Filter = 'all' | 'attention' | DisplayStatus;
const filterOptions: {id:Filter; label:string}[] = [
 {id:'all',label:'전체 상태'},{id:'attention',label:'실패 · 미지원'},{id:'uploaded',label:'실행 전'},{id:'processing',label:'처리 중 / 대기'},{id:'completed',label:'완료'},{id:'failed',label:'실패'},{id:'unsupported',label:'지원 안 됨'},{id:'no_text',label:'글자 없음 (이미지)'}
];
const sortOptions: {id: DocSort; label: string}[] = [{id:'recent', label:'올린 순'}, {id:'updated', label:'마지막 변경 순'}, {id:'name', label:'이름 순'}];
const needsAttention = (status: DisplayStatus) => status === 'failed' || status === 'unsupported';
/** 끝난 작업의 안내. 글자 없는 이미지는 실패가 아니므로 오류로 띄우지 않는다. */
const outcome = (doc: LiveDoc) => isNoTextImage(doc) ? {notice:`${doc.name}: 이미지에서 글자를 찾지 못했습니다. 상세에서 확인해 주세요.`}
  : doc.status === 'completed' ? {notice:`${doc.name} 파싱이 완료되었습니다. 결과를 확인해 주세요.`}
  : doc.status === 'failed' || doc.status === 'unsupported' ? {error:`${doc.name}: ${doc.status === 'failed' ? '파싱에 실패했습니다.' : '지원하지 않는 형식입니다.'} 상세 상태를 확인해 주세요.`} : null;
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 120;
/** 한 번에 받는 문서 수. 더 보기로 이어 받는다. 처리 중 다시 읽을 때는 받은 만큼(최대 500)을 한 번에 다시 읽는다. */
const PAGE = 50;
const REFRESH_MAX = 500;
const formatLabel = (format: string) => format || '확장자 없음';

function displayError(error: unknown) {
 return error instanceof Error ? error.message : '요청을 처리하지 못했습니다.';
}

function FileName({name}: {name: string}) {
 const chars = Array.from(name);
 if (chars.length <= 28) return <strong data-tip={name} data-tip-overflow>{name}</strong>;
 return <strong className="lw-long-name" data-tip={name} data-tip-overflow aria-label={name}><span>{chars.slice(0,-12).join('')}</span><span>{chars.slice(-12).join('')}</span></strong>;
}

type Saved = { query?: unknown; filter?: unknown; format?: unknown; sort?: unknown; scroll?: unknown; count?: unknown };
const readSaved = (): Saved => (history.state?.inbox ?? {}) as Saved;
const savedFilter = (saved: Saved) => filterOptions.find(f => f.id === saved.filter)?.id ?? 'all';
const savedFormat = (saved: Saved) => typeof saved.format === 'string' ? saved.format : null;
const savedSort = (saved: Saved) => sortOptions.find(option => option.id === saved.sort)?.id ?? 'recent';

/** 예전 서버(전체 목록만 줌): 화면이 거르고 정렬하고 센다. */
function legacyView(documents: LiveDoc[], query: string, filter: Filter, format: string | null, sort: DocSort) {
 const byStatus = (doc: LiveDoc) => { const status = displayStatus(doc); return filter === 'all' || (filter === 'attention' ? needsAttention(status) : status === filter); };
 const byFormat = (doc: LiveDoc) => format === null || (doc.format || '').toUpperCase() === format;
 const searched = documents.filter(doc => matchesDocQuery(doc, query));
 const shown = searched.filter(doc => byStatus(doc) && byFormat(doc));
 if (sort === 'name') shown.sort((a, b) => a.name.localeCompare(b.name, 'ko') || (a.seq ?? 0) - (b.seq ?? 0));
 else if (sort === 'updated') shown.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
 const formats: Record<string, number> = {}, statuses: Record<string, number> = {};
 for (const doc of searched) if (byStatus(doc)) formats[(doc.format || '').toUpperCase()] = (formats[(doc.format || '').toUpperCase()] ?? 0) + 1;
 for (const doc of searched) if (byFormat(doc)) statuses[displayStatus(doc)] = (statuses[displayStatus(doc)] ?? 0) + 1;
 return { shown, facets: { formats, statuses } };
}

type LiveWorkspaceProps = {
 active?: boolean; route?: WorkspaceRoute; onRoute?: (next: WorkspaceRoute) => void; onFamily?: (id: string) => void;
 onNavigate?: (next: WorkspaceRoute) => void;
 onUploadStateChange?: (uploading: boolean) => void;
};

export default function LiveWorkspace({ active = true, route, onRoute, onFamily, onNavigate, onUploadStateChange }: LiveWorkspaceProps = {}) {
 const [documents,setDocuments]=useState<LiveDoc[]>([]);
 const [listMeta, setListMeta] = useState<{total: number; next: string | null; facets: DocPage['facets']; legacy: boolean}>({total: 0, next: null, facets: {formats: {}, statuses: {}}, legacy: false});
 const [outside, setOutside] = useState<LiveDoc[]>([]); // 지금 받은 쪽 밖에서 처리 중인(이 화면이 접수한) 문서
 const [loading,setLoading]=useState(true);
 const [loadingMore, setLoadingMore] = useState(false);
 const [listError,setListError]=useState('');
 const [actionError,setActionError]=useState('');
 const [detailRead, setDetailRead] = useState<{id: string; doc?: LiveDoc; error?: string; missing?: boolean}>();
 const [detailRevision, setDetailRevision] = useState(0);
 const [summaryRevision, setSummaryRevision] = useState(0);
 const [notice,setNotice]=useState('');
 const [uploading,setUploading]=useState(false);
 const [uploadProgress,setUploadProgress]=useState({done:0,total:0});
 const [dragging,setDragging]=useState(false);
 const [folderOpen,setFolderOpen]=useState(false);
 const [bulkProcessing,setBulkProcessing]=useState(false);
 const [filter,setFilter]=useState<Filter>(() => savedFilter(readSaved()));
 const [query,setQuery]=useState<string>(() => typeof readSaved().query === 'string' ? readSaved().query as string : '');
 const [searched, setSearched] = useState(query); // 입력을 잠시 멈췄을 때 서버에 묻는다
 const [format, setFormat] = useState<string | null>(() => savedFormat(readSaved()));
 const [sort, setSort] = useState<DocSort>(() => savedSort(readSaved()));
 const [localRoute, setLocalRoute] = useState<WorkspaceRoute>({page:'live'});
 const liveRoute = route ?? localRoute;
 const selectedId = liveRoute.page === 'live' ? liveRoute.doc ?? null : null;
 const changeRoute = onRoute ?? setLocalRoute;
 const latestView = useRef({active, selectedId});
 latestView.current = {active, selectedId};
 const [failedFiles, setFailedFiles] = useState<{file: File; reason: string}[]>([]);
 const uploadLock = useRef(false);
 const selectFile = (id: string | null) => changeRoute({page:'live', doc:id ?? undefined});
 const [result,setResult]=useState<LiveResult|null>(null);
 const [resultLoading,setResultLoading]=useState(false);
 const [resultError,setResultError]=useState('');
 const [processingId,setProcessingId]=useState<string|null>(null);
 const [pollExhausted,setPollExhausted]=useState(false);
 const pollCount=useRef(0);
 const watchedJobs=useRef(new Set<string>());
 const inputRef=useRef<HTMLInputElement>(null);
 const root = useRef<HTMLDivElement>(null);
 const previousReview = useRef(false);
 const previousView = useRef<string | null>(null);
 const listScroll = useRef<number>(Number(readSaved().scroll) || 0);
 const restoreCount = useRef<number>(Number(readSaved().count) || PAGE);
 const mounted=useRef(false);
 const latestListRequest = useRef(0);
 const mutationVersion = useRef(0);
 const listQuery = useRef({q: searched, status: filter, format, sort});
 listQuery.current = {q: searched, status: filter, format, sort};
 const loadedCount = useRef(0);
 loadedCount.current = documents.length;
 useEffect(() => { const timer = window.setTimeout(() => setSearched(query), 250); return () => window.clearTimeout(timer); }, [query]);
 const detail = detailRead?.id === selectedId ? detailRead : undefined;
 const listed = documents.find(doc => doc.id === selectedId) ?? outside.find(doc => doc.id === selectedId);
 const current = detail?.missing ? null : listed ?? detail?.doc ?? null;
 // 예전 서버는 화면이 거른다: 서버에 묻지 않으니 입력을 기다리지 않고 바로 거른다.
 const legacy = useMemo(() => listMeta.legacy ? legacyView(documents, query, filter, format, sort) : null, [listMeta.legacy, documents, query, filter, format, sort]);
 const shown = legacy ? legacy.shown : documents;
 const facets = legacy ? legacy.facets : listMeta.facets;
 const total = legacy ? legacy.shown.length : listMeta.total;
 const processingCount = documents.filter(doc => doc.status === 'processing').length + outside.filter(doc => doc.status === 'processing').length;
 const counts = useMemo(() => {
  const next: Record<Filter, number> = { all: 0, uploaded: 0, processing: 0, completed: 0, failed: 0, unsupported: 0, no_text: 0, attention: 0 };
  for (const [status, count] of Object.entries(facets.statuses)) if (status in next) next[status as Filter] = count;
  next.attention = next.failed + next.unsupported;
  next.all = Object.values(facets.statuses).reduce((sum, count) => sum + count, 0);
  return next;
 }, [facets]);
 const formatOptions = useMemo(() => {
  const entries = Object.entries(facets.formats).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  if (format !== null && !entries.some(([value]) => value === format)) entries.push([format, 0]);
  return entries;
 }, [facets, format]);
 const countsAvailable = !loading && (!listError || documents.length > 0);
 const filtersActive = !!query || filter !== 'all' || format !== null;
 const resetFilters = () => { setQuery(''); setSearched(''); setFilter('all'); setFormat(null); };
 useEffect(() => {
  const restore = () => {
   const saved = readSaved();
   const text = typeof saved.query === 'string' ? saved.query : '';
   setQuery(text); setSearched(text);
   setFilter(savedFilter(saved)); setFormat(savedFormat(saved)); setSort(savedSort(saved));
   listScroll.current = Number(saved.scroll) || 0;
   restoreCount.current = Number(saved.count) || PAGE;
  };
  window.addEventListener('popstate', restore);
  return () => window.removeEventListener('popstate', restore);
 }, []);
 useEffect(() => {
  if (!active || selectedId) return;
  const save = () => {
   if (!latestView.current.active || latestView.current.selectedId) return;
   const scroll = document.scrollingElement?.scrollTop ?? listScroll.current;
   history.replaceState({...history.state, inbox:{query, filter, format, sort, scroll, count: loadedCount.current}}, '');
  };
  save();
  const rememberScroll = () => { listScroll.current = document.scrollingElement?.scrollTop ?? listScroll.current; };
  window.addEventListener('scroll', rememberScroll, {passive:true});
  window.addEventListener('pagehide', save);
  return () => {
   window.removeEventListener('scroll', rememberScroll);
   window.removeEventListener('pagehide', save);
  };
 }, [active, selectedId, query, filter, format, sort]);
 const selectDocument = (id: string) => {
  listScroll.current = document.scrollingElement?.scrollTop ?? 0;
  history.replaceState({...history.state, inbox:{query, filter, format, sort, scroll:listScroll.current, count: documents.length}}, '');
  selectFile(id);
  setActionError('');
 };
 const viewId = current?.id ?? null;
 const reviewing = !!liveRoute.review;
 useLayoutEffect(() => {
  const previous = previousView.current;
  previousView.current = viewId;
  const reviewChanged = previousReview.current !== reviewing;
  previousReview.current = reviewing;
  if ((previous === viewId && !reviewChanged) || !root.current || root.current.closest('[hidden]')) return;
  const target = viewId ? root.current.querySelector<HTMLElement>('h1') :
    Array.from(root.current.querySelectorAll<HTMLElement>('[data-document-id]')).find(row => row.dataset.documentId === previous) ?? root.current.querySelector<HTMLElement>('h1');
  document.scrollingElement?.scrollTo?.({ top: viewId ? 0 : listScroll.current });
  target?.focus({ preventScroll: true });
 }, [viewId, reviewing]);

 /** 받은 범위(처음부터 지금까지)를 다시 읽는다. reset이면 조건이 바뀐 것: 첫 쪽부터(뒤로 가기면 그때 본 만큼). */
 const refresh=useCallback(async (manual=false, reset=false) => {
  if(manual){pollCount.current=0;setPollExhausted(false);setSummaryRevision(n => n + 1)}
  const request = ++latestListRequest.current;
  const before = mutationVersion.current;
  const isCurrent = () => mounted.current && latestListRequest.current === request;
  const q = listQuery.current;
  const limit = Math.min(REFRESH_MAX, Math.max(PAGE, reset ? restoreCount.current : loadedCount.current));
  if (reset) restoreCount.current = PAGE;
  try {
   const body = await listDocumentPage({q: q.q, status: q.status, format: q.format, sort: q.sort, limit});
   if (!isCurrent()) return;
   const changedDuringRead = before !== mutationVersion.current;
   setDocuments(previous => {
    const known = new Map(previous.map(doc => [doc.id, doc]));
    const merged = body.documents.map(doc => {
     const cached = known.get(doc.id);
     known.delete(doc.id);
     return cached && Date.parse(cached.updated_at) > Date.parse(doc.updated_at) ? {...cached, qc: doc.qc ?? cached.qc} : doc;
    });
    // A file added during this read may be absent from the server snapshot.
    return changedDuringRead ? [...known.values(), ...merged] : merged;
   });
   setListMeta({total: body.total, next: body.next_cursor, facets: body.facets, legacy: !!body.legacy});
   setListError('');
   // 지금 쪽 밖에서 처리 중인 문서(이 화면이 접수한 것)는 따로 묻는다: 완료 알림을 놓치지 않게.
   const inWindow = new Set(body.documents.map(doc => doc.id));
   const missing = [...watchedJobs.current].filter(id => !inWindow.has(id));
   if (missing.length && !body.legacy) {
    try { const extra = await getDocumentsByIds(missing); if (isCurrent()) setOutside(extra); } catch { /* 다음 확인에서 다시 묻는다 */ }
   } else if (isCurrent()) setOutside([]);
  } catch(error) { if (isCurrent()) setListError(displayError(error)); }
  finally { if (isCurrent()) setLoading(false); }
 },[]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(() => { void refresh(false, true); }, [refresh, searched, filter, format, sort]);
 async function loadMore() {
  if (!listMeta.next || loadingMore || listMeta.legacy) return;
  setLoadingMore(true);
  const q = listQuery.current;
  const request = latestListRequest.current;
  try {
   const body = await listDocumentPage({q: q.q, status: q.status, format: q.format, sort: q.sort, cursor: listMeta.next, limit: PAGE});
   if (!mounted.current || request !== latestListRequest.current) return;
   setDocuments(previous => { const ids = new Set(previous.map(doc => doc.id)); return [...previous, ...body.documents.filter(doc => !ids.has(doc.id))]; });
   setListMeta(meta => ({...meta, total: body.total, next: body.next_cursor, facets: body.facets}));
  } catch (error) { if (mounted.current) setActionError(displayError(error)); }
  finally { if (mounted.current) setLoadingMore(false); }
 }
 useEffect(()=>{
  if(!processingCount && !watchedJobs.current.size){pollCount.current=0;setPollExhausted(false);return}
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
  let finished = false;
  for(const doc of [...documents, ...outside]){
   if(!watchedJobs.current.has(doc.id))continue;
   const done=outcome(doc);
   if(done?.notice){watchedJobs.current.delete(doc.id);setActionError('');setNotice(done.notice);finished=true}
   else if(done?.error){watchedJobs.current.delete(doc.id);setNotice('');setActionError(done.error);finished=true}
  }
  if (finished) setSummaryRevision(n => n + 1);
 },[documents, outside]);
 useEffect(()=>{
  if(!selectedId || !active)return;
  const controller=new AbortController();
  void getLiveDocument(selectedId,controller.signal)
   .then(detail => {
    if (controller.signal.aborted || !mounted.current) return;
    setDetailRead({id:selectedId, doc:detail});
    setDocuments(previous => {
     return previous.map(item => item.id === detail.id && Date.parse(detail.updated_at) >= Date.parse(item.updated_at) ? {...detail, qc: item.qc} : item);
    });
   })
   .catch(error => {
    if (!controller.signal.aborted && mounted.current) setDetailRead({id:selectedId, error:displayError(error), missing:error instanceof LiveRequestError && error.status === 404});
   });
  return()=>controller.abort();
 },[selectedId, active, detailRevision]);
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
  if(!files.length || uploadLock.current)return;
  uploadLock.current = true;
  const startedAt = latestView.current.selectedId;
  setFailedFiles([]);
  setUploading(true);onUploadStateChange?.(true);setActionError('');setNotice('');setUploadProgress({done:0,total:files.length});
  const errors:{file:File; reason:string}[]=[];let success=0;let lastId:string|null=null;
  for(const file of files){
   if (!mounted.current) return;
   try {
    const doc=await uploadLiveDocument(file);
    if(!mounted.current)return;
    mutationVersion.current += 1;
    success++;lastId=doc.id;
    setDocuments(prev=>[doc,...prev.filter(item=>item.id!==doc.id)]);
    setListMeta(meta => ({...meta, total: meta.total + 1}));
   } catch(error) {errors.push({file, reason:displayError(error)})}
   if(mounted.current)setUploadProgress(prev=>({...prev,done:prev.done+1}));
  }
  if(!mounted.current)return;
  if (lastId && latestView.current.active && startedAt === latestView.current.selectedId) {
   selectFile(files.length === 1 ? lastId : null); setFilter('all'); setQuery(''); setFormat(null); setSort('recent');
  }
  if(success){setNotice(`${success}개 파일을 이 컴퓨터의 로컬 저장소에 저장했습니다. 파싱은 별도로 실행해 주세요.`);setSummaryRevision(n => n + 1)}
  setFailedFiles(errors);
  uploadLock.current = false;
  setUploading(false);
  onUploadStateChange?.(false);
 }
 async function process(doc:LiveDoc, options?: ProcessOptions) {
  if(processingId || doc.status==='processing')return;
  setProcessingId(doc.id);setActionError('');setNotice('');pollCount.current=0;setPollExhausted(false);
  try {
   const updated=await processLiveDocument(doc.id, options);
   if(mounted.current){
    const done=outcome(updated);
    if(updated.status==='processing'){watchedJobs.current.add(updated.id);setNotice(options && Object.keys(options).length ? '지정한 원천 형식으로 파싱 작업을 접수했습니다. 대기 또는 처리 상태를 자동으로 확인합니다.' : '파싱 작업이 접수되었습니다. 대기 또는 처리 상태를 자동으로 확인합니다.')}
    else if(done?.notice){setNotice(done.notice)}
    else if(done?.error){setActionError(done.error)}
    mutationVersion.current += 1;
    setDocuments(prev=>prev.map(item=>item.id===updated.id?{...updated, qc: item.qc}:item));
    if (!documents.some(item => item.id === updated.id)) setOutside(prev => [updated, ...prev.filter(item => item.id !== updated.id)]);
   }
  } catch(error){if(mounted.current)setActionError(displayError(error))}
  finally{if(mounted.current)setProcessingId(null)}
 }
 /** 허용 폴더에서 가져온 문서를 목록에 넣는다. 파싱은 하지 않는다. */
 function addImported(docs: LiveDoc[]) {
  if (!mounted.current || !docs.length) return;
  mutationVersion.current += 1;
  const ids = new Set(docs.map(doc => doc.id));
  setDocuments(prev => [...docs, ...prev.filter(item => !ids.has(item.id))]);
  setFilter('all'); setQuery(''); setFormat(null); setActionError('');
  setSummaryRevision(n => n + 1);
  setNotice(`${docs.length}개 문서를 허용 폴더에서 가져와 이 컴퓨터의 로컬 저장소에 두었습니다. 파싱은 별도로 실행해 주세요.`);
 }
 /** 가져오기 결과에서 사용자가 누른 일괄 파싱. 하나씩 접수하고, 접수하지 못한 문서는 이유를 모아 보여 준다. */
 async function processMany(docs: LiveDoc[]) {
  if (bulkProcessing || !docs.length) return;
  setBulkProcessing(true); setActionError(''); setNotice('');
  pollCount.current = 0; setPollExhausted(false);
  const errors: string[] = []; let accepted = 0;
  for (const doc of docs) {
   if (!mounted.current) return;
   try {
    const updated = await processLiveDocument(doc.id);
    accepted++;
    mutationVersion.current += 1;
    setDocuments(prev => prev.map(item => item.id === updated.id ? updated : item));
   } catch (error) { errors.push(`${doc.name} · ${displayError(error)}`); }
  }
  if (!mounted.current) return;
  setBulkProcessing(false);
  if (accepted) setNotice(`${accepted}개 문서의 파싱을 접수했습니다. 대기 또는 처리 상태를 자동으로 확인합니다.`);
  if (errors.length) setActionError(`${errors.length}개 문서는 파싱을 접수하지 못했습니다. 문서 상세에서 다시 실행해 주세요.\n${errors.slice(0, 5).join('\n')}${errors.length > 5 ? `\n… 외 ${errors.length - 5}개` : ''}`);
 }
 const canDrop = (event: React.DragEvent) => event.dataTransfer.types.includes('Files');
 const pickFiles = () => inputRef.current?.click();
 const onDrop = (event: React.DragEvent) => {
  if (!canDrop(event)) return;
  event.preventDefault();
  setDragging(false);
  if (!uploading && !current) void upload(Array.from(event.dataTransfer.files));
 };
 const remaining = Math.max(0, total - shown.length);
 return <div ref={root} className="lw-workspace"
   onDragOver={event => { if (canDrop(event)) { event.preventDefault(); setDragging(!current && !uploading); } }}
   onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
   onDrop={onDrop}>
  <input ref={inputRef} hidden type="file" multiple aria-label="로컬에 업로드할 파일 선택"
    onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ''; void upload(files); }} />
  {dragging && <div className="lw-drop-hint"><FilePlus2 size={28} /><strong>놓아서 이 컴퓨터에 저장</strong></div>}
  {notice && <div className="lw-message is-notice" role="status"><CheckCircle2 size={17}/><span>{notice}</span><button aria-label="안내 닫기" onClick={() => setNotice('')}>×</button></div>}
  {actionError && <div className="lw-message is-error" role="alert"><CircleAlert size={17}/><span>{actionError}</span><button aria-label="오류 닫기" onClick={() => setActionError('')}>×</button></div>}
  {!!failedFiles.length && <div className="lw-message is-error" role="alert"><CircleAlert size={17}/><div><strong>{failedFiles.length}개 파일 저장 실패</strong><ul>{failedFiles.map(({file, reason}, i) => <li key={i}>{file.name} · {reason}</li>)}</ul><button onClick={() => void upload(failedFiles.map(f => f.file))}>실패한 파일만 다시 저장</button></div></div>}
  {pollExhausted && <div className="lw-message is-warning" role="status"><Clock3 size={17}/><span>자동 상태 확인이 멈췄습니다.</span><button onClick={() => void refresh(true)}>상태 새로고침</button></div>}
  {bulkProcessing && <div className="lw-progress" role="status"><LoaderCircle size={16} className="live-spin"/>가져온 문서의 파싱을 접수하는 중입니다.</div>}
  {uploading && <div className="lw-progress" role="status"><LoaderCircle size={16} className="live-spin"/>파일 저장 중 · {uploadProgress.done}/{uploadProgress.total}<progress aria-label="파일 업로드 진행률" value={uploadProgress.done} max={uploadProgress.total}/></div>}
  {listError && (documents.length > 0 || current) && <div className="lw-message is-warning" role="alert"><CircleAlert size={17}/><span>마지막 조회 결과입니다. {listError}</span><button onClick={() => void refresh(true)}>다시 시도</button></div>}
  {!selectedId && <section className="lw-inbox" aria-labelledby="lw-inbox-title">
    <header className="lw-inbox-head">
      <div><h1 id="lw-inbox-title" tabIndex={-1}>문서함</h1><p>파일을 이 컴퓨터에 저장하고, 문서를 열어 파싱을 실행하세요.</p></div>
      <div className="lw-head-actions">
        <button className="lw-btn" onClick={() => setFolderOpen(true)} disabled={uploading || bulkProcessing} data-tip="브라우저로 파일을 보내지 않고, 콘솔 서버가 이 컴퓨터의 허용 폴더에서 직접 읽어 옵니다. 브라우저 파일 첨부가 막힌 PC에서 씁니다."><FolderInput size={18} />폴더에서 가져오기</button>
        <button className="lw-btn is-primary" onClick={pickFiles} disabled={uploading}><FilePlus2 size={18} />파일 추가</button>
      </div>
    </header>
    {onNavigate && <nav className="lw-shortcuts" aria-label="문서 처리 바로가기">
      <WorkspaceLink to={{page:'parsers'}} onNavigate={onNavigate}><span><Workflow size={21}/></span><span><b>파서 플로우</b><small>형식별 파서와 처리 경로</small></span><ArrowUpRight size={17}/></WorkspaceLink>
      <WorkspaceLink to={{page:'chunking'}} onNavigate={onNavigate}><span><Scissors size={21}/></span><span><b>청킹 비교</b><small>분할 전략과 청크 품질</small></span><ArrowUpRight size={17}/></WorkspaceLink>
    </nav>}
    <QcFunnel revision={summaryRevision} active={active} />
    <div className="lw-sheet">
      <div className="lw-tools">
        <label className="lw-search"><Search size={17} /><input aria-label="실제 문서 검색" placeholder="파일명, D번호, 확장자 또는 ID 검색" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <label className="lw-filter"><ListFilter size={16}/><select aria-label="처리 상태 필터" value={filter} onChange={event => setFilter(event.target.value as Filter)}>
          {filterOptions.filter(option => option.id !== 'no_text' || counts.no_text > 0 || filter === 'no_text').map(option => <option key={option.id} value={option.id}>{option.label}{countsAvailable ? ` (${counts[option.id]})` : ''}</option>)}
        </select></label>
        <label className="lw-filter"><FileType2 size={16}/><select aria-label="확장자 필터" value={format === null ? '*' : format === '' ? '-' : format}
          onChange={event => setFormat(event.target.value === '*' ? null : event.target.value === '-' ? '' : event.target.value)}>
          <option value="*">모든 확장자</option>
          {formatOptions.map(([value, count]) => <option key={value || '-'} value={value || '-'}>{formatLabel(value)}{countsAvailable ? ` (${count})` : ''}</option>)}
        </select></label>
        <label className="lw-filter"><ArrowDownWideNarrow size={16}/><select aria-label="정렬" value={sort} onChange={event => setSort(event.target.value as DocSort)}>
          {sortOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select></label>
        {filtersActive && shown.length > 0 && <button className="lw-reset" onClick={resetFilters}>조건 초기화</button>}
        {countsAvailable && <span className="lw-count">{remaining ? `${shown.length.toLocaleString('ko-KR')} / ` : ''}{total.toLocaleString('ko-KR')}개 문서</span>}
        {!listError && <button className="lw-icon-btn" data-tip="문서 목록 새로고침" aria-label="문서 목록 새로고침" onClick={() => void refresh(true)}><RefreshCw size={16} /></button>}
      </div>
      <div className="live-list">
        {loading ? <p className="lw-placeholder" role="status">문서 목록을 불러오는 중입니다.</p> :
         listError && !documents.length ? <div className="lw-empty" role="alert"><CircleAlert size={26}/><h2>문서 목록을 확인할 수 없습니다</h2><p>{listError}</p><button className="lw-btn" onClick={() => void refresh(true)}>다시 시도</button></div> :
         !shown.length ? <div className="lw-empty"><FolderOpen size={30} strokeWidth={1.5}/><h2>{filtersActive ? '조건에 맞는 문서가 없습니다' : '업로드된 문서가 없습니다'}</h2>
           <p>{filtersActive ? '다른 검색어나 처리 상태·확장자로 찾아보세요.' : '파일 추가를 누르거나 여기에 파일을 끌어 놓으세요. 브라우저 파일 첨부가 막힌 PC는 폴더에서 가져오기를 쓰세요.'}</p>
           {filtersActive && <button className="lw-btn" onClick={resetFilters}>검색 및 필터 초기화</button>}</div> :
         <>
           <div className="lw-columns lw-grid" aria-hidden="true"><span>문서명</span><span>처리 상태</span><span>마지막 변경</span></div>
           <ul className="lw-files">{shown.map(doc => <li key={doc.id}><a className="lw-row lw-grid" href={workspaceHref({page:'live', doc:doc.id})} data-document-id={doc.id} onClick={e => {
             if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
             e.preventDefault(); selectDocument(doc.id);
           }}>
             <span className="lw-file"><FileGlyph format={doc.format}/><span className="lw-file-copy"><FileName name={doc.name}/><small><DocNumber seq={doc.seq}/>{statusNote(doc) ?? `${doc.format || '확장자 없음'} · ${displaySize(doc.size_bytes)}`}</small></span></span>
             <span className="lw-status-cell"><StatusBadge status={displayStatus(doc)}/>{doc.qc?.state && <QcStateBadge state={doc.qc.state} unresolved={doc.qc.unresolved} label={doc.qc.label} previous={doc.qc.previous} />}</span>
             <time dateTime={doc.updated_at}>{displayDate(doc.updated_at)}</time>
           </a></li>)}</ul>
           {remaining > 0 && !legacy && <div className="lw-more"><button className="lw-btn" onClick={() => void loadMore()} disabled={loadingMore || !listMeta.next}>
             {loadingMore && <LoaderCircle size={16} className="live-spin" />}{Math.min(PAGE, remaining).toLocaleString('ko-KR')}개 더 보기<small>남은 {remaining.toLocaleString('ko-KR')}개</small></button></div>}
         </>}
      </div>
    </div>
    <details className="lw-disclosure"><summary>지원 형식 안내</summary><p>TXT·CSV·MD·LOG는 기본 환경에서 처리합니다. PDF·DOCX·PPTX·XLSX·XLSM은 Docling이 필요합니다(XLSM 매크로는 실행하지 않습니다). 설정의 모델 연결에서 OCR 모델을 연결하면 이미지와 스캔 PDF의 글자도 읽습니다. SVG 벡터 글자와 EML 메일(본문·헤더·첨부 목록, 첨부 본문은 읽지 않음)은 기본 환경에서 읽습니다.</p></details>
  </section>}
  {current && detail?.error && <div className="lw-message is-warning" role="alert">마지막 조회 결과입니다. {detail.error}<button onClick={() => setDetailRevision(n => n + 1)}>다시 시도</button></div>}
  {selectedId && !current && <section className="lw-empty">
    <h1 tabIndex={-1}>{detail?.missing ? '문서를 찾을 수 없습니다' : detail?.error ? '문서를 불러오지 못했습니다' : '문서를 불러오는 중입니다'}</h1>
    {detail?.error && !detail.missing && <p role="alert">{detail.error}</p>}
    <button className="lw-btn" onClick={() => selectFile(null)}>문서함으로</button>
    {detail?.error && !detail.missing && <button className="lw-btn" onClick={() => setDetailRevision(n => n + 1)}>다시 시도</button>}
  </section>}
  {current && liveRoute.review && <section className="compare-space is-live-review" aria-label="결과 검수">
    <DocumentRuns key={current.id} doc={current} active={active} mode={liveRoute.review} focus={liveRoute.focus}
      onMode={review => { if (liveRoute.review !== review) changeRoute({page:'live', doc:current.id, review}); }}
      heading={<div className="review-head">
        <button className="workspace-back" onClick={() => changeRoute({page:'live',doc:current.id})} data-tip="문서 상세로" aria-label="문서 상세로"><ArrowLeft size={16}/><span>상세</span></button>
        <h1 tabIndex={-1} data-tip={current.name} data-tip-overflow><DocNumber seq={current.seq}/>{current.name}</h1>
      </div>}/></section>}
  {current && !liveRoute.review && <LiveDocumentView key={current.id} doc={current} result={result?.id === current.id ? result : null} resultLoading={resultLoading}
    resultError={resultError} submittingId={processingId} onBack={() => selectFile(null)} onProcess={options => void process(current, options)}
    tab={liveRoute.tab ?? 'result'} onTab={tab => changeRoute({page:'live', doc:current.id, tab})}
    onCompare={() => changeRoute({page:'live', doc:current.id, review:'source'})} onFamily={onFamily && (() => onFamily(current.id))}
    onPickFile={pickFiles} onNavigate={onNavigate} />}
  {folderOpen && <FolderImport onClose={() => setFolderOpen(false)} onImported={addImported} onParse={docs => void processMany(docs)}/>}
 </div>;
}
