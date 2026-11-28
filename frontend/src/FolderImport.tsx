import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, CheckCircle2, ChevronRight, CircleAlert, Folder, HardDrive, Info, LoaderCircle, Play, RefreshCw, Search, X } from 'lucide-react';
import { Modal } from './ui';
import { getImportRoots, importFromFolder, listImportEntries } from './api/live';
import type { ImportFile, ImportItem, ImportListing, ImportRoots, LiveDoc } from './api/live';
import { DocNumber, FileGlyph, displaySize } from './LiveDocumentView';
import './folderImport.css';

/** 브라우저 파일 첨부·전송이 보안 프로그램으로 막힌 PC용. */
type Props = { onClose: () => void; onImported: (docs: LiveDoc[]) => void; onParse: (docs: LiveDoc[]) => void };

const CHUNK = 500;
const selectable = (file: ImportFile) => file.state === 'ready' || file.state === 'no_parser';
const pickedByDefault = (file: ImportFile) => file.state === 'ready' && !file.existing.length;
const message = (error: unknown) => error instanceof Error ? error.message : '요청을 처리하지 못했습니다.';
const folderOf = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';

function FileState({ file, maxBytes }: { file: ImportFile; maxBytes: number }) {
 if (file.state === 'empty') return <span className="fi-state is-off">빈 파일</span>;
 if (file.state === 'too_large') return <span className="fi-state is-off">{displaySize(maxBytes)} 초과</span>;
 const known = file.existing[0];
 return <span className="fi-states">
  {known && <span className="fi-state is-known" data-tip="이름·크기가 같은 문서가 문서함에 있습니다. 내용까지 같으면 새로 만들지 않고 그 문서를 씁니다."><DocNumber seq={known.seq}/>문서함에 있음</span>}
  {file.state === 'no_parser' && <span className="fi-state is-warn" data-tip="저장과 구조 분석은 되지만 파싱 경로가 없습니다.">파서 없음</span>}
 </span>;
}

export default function FolderImport({ onClose, onImported, onParse }: Props) {
 const [roots, setRoots] = useState<ImportRoots | null>(null);
 const [rootsError, setRootsError] = useState('');
 const [rootIndex, setRootIndex] = useState(0);
 const [path, setPath] = useState('');
 const [recursive, setRecursive] = useState(false);
 const [listing, setListing] = useState<ImportListing | null>(null);
 const [listLoading, setListLoading] = useState(false);
 const [listError, setListError] = useState('');
 const [reload, setReload] = useState(0);
 const [rootsReload, setRootsReload] = useState(0);
 const [query, setQuery] = useState('');
 const [selected, setSelected] = useState<Map<string, ImportFile>>(() => new Map());
 const [importing, setImporting] = useState<{done: number; total: number} | null>(null);
 const [importError, setImportError] = useState('');
 const [result, setResult] = useState<ImportItem[] | null>(null);
 const searchRef = useRef<HTMLInputElement>(null);
 const allRef = useRef<HTMLInputElement>(null);
 const root = roots?.roots[rootIndex];
 const maxBytes = roots?.max_bytes ?? 100 * 1024 * 1024;

 useEffect(() => {
  const controller = new AbortController();
  getImportRoots(controller.signal).then(setRoots).catch(error => { if (!controller.signal.aborted) setRootsError(message(error)); });
  return () => controller.abort();
 }, [rootsReload]);
 const rootIndexValue = root?.index;
 useEffect(() => {
  if (rootIndexValue === undefined) return;
  const controller = new AbortController();
  setListLoading(true); setListError('');
  listImportEntries(rootIndexValue, path, recursive, controller.signal)
   .then(body => { if (!controller.signal.aborted) setListing(body); })
   .catch(error => { if (!controller.signal.aborted) { setListing(null); setListError(message(error)); } })
   .finally(() => { if (!controller.signal.aborted) setListLoading(false); });
  return () => controller.abort();
 }, [rootIndexValue, path, recursive, reload]);

 const needle = query.trim().toLocaleLowerCase('ko-KR');
 const folders = useMemo(() => (listing?.folders ?? []).filter(folder => folder.name.toLocaleLowerCase('ko-KR').includes(needle)), [listing, needle]);
 const files = useMemo(() => (listing?.files ?? []).filter(file => file.path.toLocaleLowerCase('ko-KR').includes(needle)), [listing, needle]);
 const candidates = files.filter(pickedByDefault);
 const chosen = candidates.filter(file => selected.has(file.path)).length;
 useEffect(() => { if (allRef.current) allRef.current.indeterminate = chosen > 0 && chosen < candidates.length; }, [chosen, candidates.length]);
 const totalBytes = [...selected.values()].reduce((sum, file) => sum + file.size_bytes, 0);

 const go = (next: string) => { setPath(next); setQuery(''); };
 const toggle = (file: ImportFile) => setSelected(previous => {
  const next = new Map(previous);
  if (next.has(file.path)) next.delete(file.path); else next.set(file.path, file);
  return next;
 });
 const toggleAll = () => setSelected(previous => {
  const next = new Map(previous);
  if (chosen === candidates.length) candidates.forEach(file => next.delete(file.path));
  else candidates.forEach(file => next.set(file.path, file));
  return next;
 });
 const changeRoot = (index: number) => { setRootIndex(index); setPath(''); setSelected(new Map()); setQuery(''); };

 async function run() {
  if (!root || !selected.size || importing) return;
  const paths = [...selected.keys()];
  const items: ImportItem[] = [];
  setImportError(''); setImporting({done: 0, total: paths.length});
  try {
   for (let start = 0; start < paths.length; start += CHUNK) {
    items.push(...await importFromFolder(root.index, paths.slice(start, start + CHUNK)));
    setImporting({done: Math.min(start + CHUNK, paths.length), total: paths.length});
   }
  } catch (error) {
   setImportError(message(error));
  } finally {
   setImporting(null);
  }
  const done = new Set(items.map(item => item.path));
  setSelected(previous => new Map([...previous].filter(([key]) => !done.has(key))));
  const docs = items.flatMap(item => item.outcome !== 'failed' && item.document ? [item.document] : []);
  if (docs.length) onImported(docs);
  if (items.length) { setResult(items); setReload(n => n + 1); }
 }

 const segments = (listing?.path ?? path).split('/').filter(Boolean);
 const close = () => { if (!importing) onClose(); };

 if (result) {
  const imported = result.filter(item => item.outcome === 'imported');
  const reused = result.filter(item => item.outcome === 'reused');
  const failed = result.filter(item => item.outcome === 'failed');
  const toParse = [...new Map(result.flatMap(item => item.document && item.outcome !== 'failed' && item.document.status === 'uploaded' ? [[item.document.id, item.document] as const] : [])).values()];
  return <Modal open onClose={close} size="md" title="가져오기 결과"
   subtitle="파일을 이 컴퓨터의 로컬 저장소에 복사했습니다. 원본 폴더의 파일은 그대로입니다."
   footer={<div className="fi-foot">
    <span>{toParse.length ? `파싱 전 문서 ${toParse.length}개` : '파싱할 새 문서가 없습니다.'}</span>
    <div>
     <button type="button" className="button-secondary" onClick={() => setResult(null)}>더 가져오기</button>
     <button type="button" className="button-secondary" onClick={onClose}>닫기</button>
     {!!toParse.length && <button type="button" className="fi-primary" onClick={() => { onParse(toParse); onClose(); }}><Play size={15} aria-hidden="true"/>{toParse.length}개 파싱 실행</button>}
    </div>
   </div>}>
   <div className="fi-result">
    <dl className="fi-summary">
     <div><dt>새로 저장</dt><dd>{imported.length}</dd></div>
     <div><dt>이미 있던 문서</dt><dd>{reused.length}</dd></div>
     <div className={failed.length ? 'is-bad' : ''}><dt>실패</dt><dd>{failed.length}</dd></div>
    </dl>
    {importError && <p className="fi-alert is-error" role="alert"><CircleAlert size={16}/>일부 요청이 끝나지 않았습니다. {importError}</p>}
    {!!failed.length && <section aria-label="실패한 파일"><h3>실패</h3><ul className="fi-outcomes">{failed.map(item => <li key={item.path}><CircleAlert size={15} className="is-bad" aria-hidden="true"/><span><b>{item.path}</b><small>{item.reason}</small></span></li>)}</ul></section>}
    {!!(imported.length + reused.length) && <section aria-label="저장된 문서"><h3>문서함에 들어간 문서</h3><ul className="fi-outcomes">{[...imported, ...reused].map(item => item.document && <li key={item.path}>
      <CheckCircle2 size={15} className="is-ok" aria-hidden="true"/><span><b><DocNumber seq={item.document.seq}/>{item.document.name}</b><small>{item.outcome === 'reused' ? '같은 원본이 이미 있어 그 문서를 씁니다' : '새로 저장'} · {item.path}</small></span></li>)}</ul></section>}
   </div>
  </Modal>;
 }

 return <Modal open onClose={close} size="lg" flush initialFocus={searchRef} title="허용 폴더에서 가져오기"
  subtitle="콘솔 서버가 이 컴퓨터의 허용 폴더에서 직접 읽어 로컬 저장소에 복사합니다. 브라우저로 파일을 보내지 않으며 파싱은 따로 실행합니다."
  footer={<div className="fi-foot">
   <span aria-live="polite">{importing ? <><LoaderCircle size={15} className="live-spin" aria-hidden="true"/>가져오는 중 · {importing.done}/{importing.total}</>
     : selected.size ? <>선택 {selected.size.toLocaleString('ko-KR')}개 · {displaySize(totalBytes)}<button type="button" className="fi-link" onClick={() => setSelected(new Map())}>선택 해제</button></> : '가져올 파일을 고르세요.'}</span>
   <div>
    <button type="button" className="button-secondary" onClick={close} disabled={!!importing}>닫기</button>
    <button type="button" className="fi-primary" onClick={() => void run()} disabled={!selected.size || !!importing}>{selected.size ? `${selected.size.toLocaleString('ko-KR')}개 가져오기` : '가져오기'}</button>
   </div>
  </div>}>
  <div className="fi-root">
   <div className="fi-where">
    <HardDrive size={16} aria-hidden="true"/>
    {roots && roots.roots.length > 1
     ? <select aria-label="허용 폴더" value={rootIndex} onChange={event => changeRoot(Number(event.target.value))}>{roots.roots.map(item => <option key={item.index} value={item.index}>{item.path}</option>)}</select>
     : <code title={root?.path}>{root?.path ?? (rootsError ? '허용 폴더를 확인할 수 없음' : '허용 폴더 확인 중')}</code>}
    {roots && <span className="fi-setting" data-tip={`허용 폴더는 .env의 ${roots.setting}로 정합니다(여러 개는 ; 로 구분). 바꾼 뒤 run을 다시 실행하세요. 화면에서는 바꿀 수 없습니다.`}>
     <Info size={14} aria-hidden="true"/>{roots.default ? '기본값: 프로젝트 samples(합성 예시 문서)' : `.env ${roots.setting}`}</span>}
   </div>
   {rootsError && <p className="fi-alert is-error" role="alert"><CircleAlert size={16}/>{rootsError}<button type="button" className="fi-link" onClick={() => { setRootsError(''); setRootsReload(n => n + 1); }}>다시 시도</button></p>}
   {roots?.notes.map(note => <p key={note} className="fi-alert is-warn" role="status"><CircleAlert size={16}/>{note}</p>)}
   {roots && !roots.roots.length && <div className="fi-empty"><Folder size={26} strokeWidth={1.5} aria-hidden="true"/><h3>열 수 있는 허용 폴더가 없습니다</h3>
    <p>.env의 <code>{roots.setting}</code>에 문서 폴더 경로를 넣고 콘솔을 다시 실행하세요. 예: <code>{roots.setting}=C:\docs\검증</code></p></div>}
   {root && <>
    <div className="fi-tools">
     <nav className="fi-crumbs" aria-label="현재 폴더">
      <button type="button" onClick={() => go('')} aria-current={!segments.length ? 'location' : undefined}>{root.name}</button>
      {segments.map((segment, index) => <span key={index}><ChevronRight size={14} aria-hidden="true"/>
       <button type="button" onClick={() => go(segments.slice(0, index + 1).join('/'))} aria-current={index === segments.length - 1 ? 'location' : undefined}>{segment}</button></span>)}
     </nav>
     <div className="fi-row-tools">
      <label className="fi-search"><Search size={15} aria-hidden="true"/><input ref={searchRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="이 목록에서 이름 찾기" aria-label="이 목록에서 이름 찾기"/>
       {query && <button type="button" onClick={() => { setQuery(''); searchRef.current?.focus(); }} aria-label="검색어 지우기"><X size={14}/></button>}</label>
      <label className="fi-check"><input type="checkbox" checked={recursive} onChange={event => setRecursive(event.target.checked)}/>하위 폴더 포함</label>
      <button type="button" className="fi-icon" onClick={() => setReload(n => n + 1)} aria-label="폴더 목록 새로고침" data-tip="폴더 목록 새로고침"><RefreshCw size={15}/></button>
     </div>
    </div>
    {listing?.truncated && <p className="fi-alert is-warn" role="status"><CircleAlert size={16}/>파일이 많아 일부만 보여 줍니다. 하위 폴더로 들어가 고르세요.</p>}
    {listError && <p className="fi-alert is-error" role="alert"><CircleAlert size={16}/>{listError}<button type="button" className="fi-link" onClick={() => go('')}>허용 폴더 처음으로</button></p>}
    <div className="fi-list" aria-busy={listLoading}>
     <div className="fi-head fi-grid">
      <label className="fi-cell-check">{candidates.length > 0 && <input ref={allRef} type="checkbox" checked={chosen === candidates.length} onChange={toggleAll}
        aria-label={`파서가 있고 문서함에 없는 파일 ${candidates.length}개 모두 선택`}/>}</label>
      <span>이름</span><span>크기</span><span>상태</span>
     </div>
     {listing && listing.parent !== null && !recursive && <button type="button" className="fi-folder fi-grid" onClick={() => go(listing.parent ?? '')}>
      <span/><span className="fi-name"><ArrowUp size={16} aria-hidden="true"/><b>상위 폴더</b></span><span/><span/></button>}
     {!recursive && folders.map(folder => <button type="button" key={folder.path} className="fi-folder fi-grid" onClick={() => go(folder.path)} aria-label={`${folder.name} 폴더 열기`}>
      <span/><span className="fi-name"><Folder size={16} aria-hidden="true"/><b>{folder.name}</b></span><span/><span className="fi-open">열기<ChevronRight size={14} aria-hidden="true"/></span></button>)}
     {files.map(file => {
      const enabled = selectable(file);
      const sub = recursive ? folderOf(file.path) : '';
      return <label key={file.path} className={`fi-file fi-grid${enabled ? '' : ' is-disabled'}${selected.has(file.path) ? ' is-selected' : ''}`}>
       <span className="fi-cell-check"><input type="checkbox" disabled={!enabled} checked={selected.has(file.path)} onChange={() => toggle(file)} aria-label={`${file.path} 선택`}/></span>
       <span className="fi-name"><FileGlyph format={file.format}/><span><b title={file.name}>{file.name}</b>{sub && <small>{sub}</small>}</span></span>
       <span className="fi-size">{file.format || '확장자 없음'} · {displaySize(file.size_bytes)}</span>
       <FileState file={file} maxBytes={maxBytes}/>
      </label>;
     })}
     {listLoading && !listing && <p className="fi-placeholder" role="status"><LoaderCircle size={16} className="live-spin" aria-hidden="true"/>폴더를 읽는 중입니다.</p>}
     {listing && !folders.length && !files.length && <p className="fi-placeholder">{needle ? '이름이 맞는 항목이 없습니다.' : '이 폴더에는 가져올 파일이 없습니다.'}</p>}
    </div>
   </>}
   {importError && !result && <p className="fi-alert is-error" role="alert"><CircleAlert size={16}/>{importError}</p>}
   {roots?.default && <p className="fi-note">samples는 저장소에 들어 있는 합성 예시 문서입니다. 가져오면 예시 둘러보기가 아니라 실제 파일 처리 문서함에 들어갑니다.</p>}
  </div>
 </Modal>;
}
