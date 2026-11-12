import { useState } from 'react';
import { ArrowRight, FileSearch, Info, Plus, RefreshCw, Search, X } from 'lucide-react';
import { REPORTED_FORMAT_GROUPS, REPORTED_FORMATS } from '../formatInventory';
import type { FlowLibrary } from './flowTypes';

type Props = {
  library: FlowLibrary; routes: Record<string, string>; mockFormats: string[]; manual: string[];
  liveCounts: Record<string, number> | null; liveFailed: boolean; highlight?: string | null;
  onRefresh: () => void; onAddManual: (ext: string) => string | null; onOpenFlow: (flowId: string) => void; onCreateRoute: (ext: string) => void;
  onOpenDocuments: (ext: string) => void; onOpenLive?: () => void; onClose: () => void;
};
export const normalizeFormat = (value: string) => { const normalized = value.trim().replace(/^\./, '').toUpperCase(); return normalized === '확장자 없음' ? '' : normalized; };
export const displayFormat = (value: string) => value ? `.${value.toLowerCase()}` : '확장자 없음';

export default function FormatPanel({ library, routes, mockFormats, manual, liveCounts, liveFailed, highlight, onRefresh, onAddManual, onOpenFlow, onCreateRoute, onOpenDocuments, onOpenLive, onClose }: Props) {
  const [search, setSearch] = useState('');
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const reported = new Set(REPORTED_FORMATS);
  const extra = [...new Set([...manual, ...mockFormats.map(normalizeFormat), ...Object.keys(liveCounts ?? {}), ...(highlight ? [highlight] : [])])].filter(ext => !reported.has(ext)).sort((a, b) => a.localeCompare(b, 'ko'));
  const matches = (ext: string) => displayFormat(ext).toLowerCase().includes(search.trim().toLowerCase().replace(/^\./, ''));
  const row = (ext: string) => {
    const flowId = routes[ext]; const local = liveCounts?.[ext] ?? 0; const isReported = reported.has(ext);
    const origin = isReported ? '사용자 제공' : local ? `로컬 ${local}건` : manual.includes(ext) ? '수동 추가' : mockFormats.map(normalizeFormat).includes(ext) ? 'Mock 예시' : '추가 형식';
    return <li key={ext || '_none'} className={`fp-row${highlight === ext ? ' is-highlight' : ''}`}>
      <span className="fp-ext">{ext || '—'}</span>
      <span className="fp-meta"><b>{displayFormat(ext)}</b><small>{origin}{isReported && local ? ` · 로컬 ${local}건` : ''}</small></span>
      {flowId ? <button className="fp-route" onClick={() => onOpenFlow(flowId)} aria-label={`${displayFormat(ext)} 경로 열기`}>{library.flows[flowId]?.title ?? flowId}<ArrowRight size={12} /></button>
        : <button className="fp-create" onClick={() => onCreateRoute(ext)} disabled={!ext} aria-label={`${displayFormat(ext)} 경로 만들기`}><Plus size={12} /> 경로 만들기</button>}
      <button className="fp-docs" onClick={() => onOpenDocuments(ext)} aria-label={`${displayFormat(ext)} 예시 문서 보기`} title="예시 문서 보기"><FileSearch size={13} /></button>
    </li>;
  };
  const submit = (event: React.FormEvent) => { event.preventDefault(); const message = onAddManual(value); if (message) setError(message); else { setValue(''); setError(''); } };
  return <div className="fp-root" role="dialog" aria-label="형식과 경로">
    <header><div><b>형식과 경로</b><small>확장자별로 어느 흐름을 타는지 확인하고 새 형식의 경로를 만듭니다.</small></div><button className="fp-close" onClick={onClose} aria-label="형식과 경로 닫기"><X size={15} /></button></header>
    <div className="fp-tools"><label className="fp-search"><Search size={14} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="확장자 검색" aria-label="확장자 검색" /></label>
      <form className="fp-add" onSubmit={submit}><label htmlFor="fp-add-input" className="fp-sr">형식 직접 추가</label><input id="fp-add-input" value={value} onChange={event => setValue(event.target.value)} placeholder="형식 추가 예: hwpx" /><button type="submit">추가</button></form></div>
    {error && <p className="fp-error" role="alert">{error}</p>}
    <div className="fp-scroll" aria-label="파일 형식 목록">
      <div className="fp-section"><span>사용자 제공 대상</span><b>{REPORTED_FORMATS.length}</b></div>
      {REPORTED_FORMAT_GROUPS.map(group => { const visible = group.formats.filter(matches); return visible.length ? <div key={group.label} className="fp-group"><h5>{group.label}</h5><ul>{visible.map(row)}</ul></div> : null; })}
      {extra.some(matches) && <><div className="fp-section"><span>추가 형식</span><b>{extra.length}</b></div><ul>{extra.filter(matches).map(row)}</ul></>}
      {!REPORTED_FORMATS.some(matches) && !extra.some(matches) && <p className="fp-empty">검색된 형식이 없습니다.</p>}
    </div>
    <footer><span className={liveFailed ? 'is-error' : ''}><Info size={12} /> {liveCounts !== null ? `로컬 형식 ${Object.keys(liveCounts).length}종 확인` : liveFailed ? '로컬 목록을 불러오지 못함' : '로컬 목록 확인 중'}</span><div>{onOpenLive && <button onClick={onOpenLive}>실제 파일 목록</button>}<button onClick={onRefresh} aria-label="로컬 형식 새로고침" title="로컬 형식 새로고침"><RefreshCw size={13} /></button></div></footer>
  </div>;
}
