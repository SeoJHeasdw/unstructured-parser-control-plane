import { useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowRight, FileSearch, Info, Plus, RefreshCw, Search, X } from 'lucide-react';
import { REPORTED_FORMAT_GROUPS, REPORTED_FORMATS } from '../formatInventory';
import { Modal, Segmented } from '../ui';
import type { FlowLibrary } from './flowTypes';

type Props = {
  library: FlowLibrary; routes: Record<string, string>; mockFormats: string[]; manual: string[];
  liveCounts: Record<string, number> | null; liveFailed: boolean; highlight?: string | null;
  onRefresh: () => void; onAddManual: (ext: string) => string | null; onOpenFlow: (flowId: string) => void; onCreateRoute: (ext: string) => void;
  onOpenDocuments: (ext: string) => void; onOpenLive?: () => void; onClose: () => void;
};
const FILTERS = [
  { id: 'all', label: '전체' },
  { id: 'routed', label: '경로 있음' },
  { id: 'unrouted', label: '경로 없음' },
] as const;
type RouteFilter = typeof FILTERS[number]['id'];
const REPORTED = new Set<string>(REPORTED_FORMATS);
export const normalizeFormat = (value: string) => { const normalized = value.trim().replace(/^\./, '').toUpperCase(); return normalized === '확장자 없음' ? '' : normalized; };
export const displayFormat = (value: string) => value ? `.${value.toLowerCase()}` : '확장자 없음';

export default function FormatPanel({ library, routes, mockFormats, manual, liveCounts, liveFailed, highlight, onRefresh, onAddManual, onOpenFlow, onCreateRoute, onOpenDocuments, onOpenLive, onClose }: Props) {
  const [search, setSearch] = useState('');
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<RouteFilter>('all');
  const searchRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const mock = new Set(mockFormats.map(normalizeFormat));
  const extra = [...new Set([...manual, ...mock, ...Object.keys(liveCounts ?? {}), ...Object.keys(routes), ...(highlight != null ? [highlight] : [])])]
    .filter(ext => !REPORTED.has(ext)).sort((a, b) => a.localeCompare(b, 'ko'));
  const query = search.trim().toLowerCase().replace(/^\./, '');
  const matches = (ext: string) => (filter === 'all' || (filter === 'routed') === !!routes[ext])
    && `${displayFormat(ext)} ${library.flows[routes[ext]]?.title ?? ''}`.toLowerCase().includes(query);
  const groups = [...REPORTED_FORMAT_GROUPS.map(({ label, formats }) => ({ label, formats: formats.filter(matches) })),
    { label: '추가 형식', formats: extra.filter(matches) }].filter(group => group.formats.length);

  function submit(event: FormEvent) {
    event.preventDefault();
    const message = onAddManual(value);
    setError(message ?? '');
    if (message) return;
    setSearch('');
    setFilter('all');
    setValue('');
  }

  return <Modal open onClose={onClose} title="형식과 경로" size="md" flush initialFocus={searchRef}
    subtitle="확장자별 모의 처리 흐름을 찾고 새 경로를 만들 수 있습니다."
    footer={<div className="fp-footer">
      <span className={liveFailed ? 'is-error' : ''} aria-live="polite"><Info size={15} aria-hidden="true" />
        {liveCounts !== null ? `로컬 형식 ${Object.keys(liveCounts).length}종 확인` : liveFailed ? '로컬 목록을 불러오지 못함' : '로컬 목록 확인 중'}
      </span>
      <div>
        {onOpenLive && <button type="button" className="button-secondary" onClick={() => { onClose(); onOpenLive(); }}>실제 파일 목록 <ArrowRight size={15} aria-hidden="true" /></button>}
        <button type="button" className="fp-docs" onClick={onRefresh} aria-label="로컬 형식 새로고침" title="로컬 형식 새로고침"><RefreshCw size={16} /></button>
      </div>
    </div>}>
    <div className="fp-root">
      <div className="fp-tools">
        <div className="fp-fields">
          <div className="fp-search"><Search size={16} aria-hidden="true" /><input ref={searchRef} value={search} onChange={event => setSearch(event.target.value)} placeholder="확장자 또는 경로 검색" aria-label="확장자 검색" />
            {search && <button className="fp-docs" onClick={() => { setSearch(''); searchRef.current?.focus(); }} aria-label="검색어 지우기"><X size={15} /></button>}
          </div>
          <form className="fp-add" onSubmit={submit}><label htmlFor={inputId} className="fp-sr">형식 직접 추가</label>
            <input id={inputId} value={value} onChange={event => { setValue(event.target.value); setError(''); }} placeholder="형식 추가 예: hwpx" aria-invalid={!!error} aria-describedby={error ? `${inputId}-error` : undefined} />
            <button type="submit" className="button-secondary"><Plus size={15} aria-hidden="true" /> 추가</button>
          </form>
        </div>
        {error && <p className="fp-error" id={`${inputId}-error`} role="alert">{error}</p>}
        <div className="fp-filter"><Segmented<RouteFilter> options={[...FILTERS]} value={filter} onChange={setFilter} label="경로 상태" /><span aria-live="polite">{groups.reduce((count, group) => count + group.formats.length, 0)}종</span></div>
      </div>
      <div className="fp-scroll" aria-label="파일 형식 목록">
        {groups.map(({ label, formats }) => <section key={label} className="fp-group">
          <h3>{label} <span>{formats.length}</span></h3>
          <ul>{formats.map(ext => {
            const flowId = routes[ext];
            const local = liveCounts?.[ext] ?? 0;
            const isReported = REPORTED.has(ext);
            const origin = isReported ? '사용자 제공' : local ? `로컬 ${local}건` : manual.includes(ext) ? '수동 추가' : mock.has(ext) ? 'Mock 예시' : '추가 형식';
            return <li key={ext} className={`fp-row${highlight === ext ? ' is-highlight' : ''}`}>
              <span className="fp-ext" aria-hidden="true">{ext || '—'}</span>
              <span className="fp-meta"><b>{displayFormat(ext)}</b><small>{origin}{isReported && local ? ` · 로컬 ${local}건` : ''}</small></span>
              {flowId ? <button className="fp-route" onClick={() => onOpenFlow(flowId)} aria-label={`${displayFormat(ext)} 경로 열기`}><span>{library.flows[flowId]?.title ?? flowId}</span><ArrowRight size={15} aria-hidden="true" /></button>
                : <button className="fp-create" onClick={() => onCreateRoute(ext)} disabled={!ext} aria-label={`${displayFormat(ext)} 경로 만들기`}><Plus size={15} aria-hidden="true" /> 경로 만들기</button>}
              <button className="fp-docs" onClick={() => { onClose(); onOpenDocuments(ext); }} aria-label={`${displayFormat(ext)} 예시 문서 보기`} title="예시 문서 보기"><FileSearch size={16} /></button>
            </li>;
          })}</ul>
        </section>)}
        {!groups.length && <div className="fp-empty"><Search size={22} aria-hidden="true" /><p>조건에 맞는 형식이 없습니다.</p><button className="button-secondary" onClick={() => { setSearch(''); setFilter('all'); }}>검색 조건 초기화</button></div>}
      </div>
    </div>
  </Modal>;
}
