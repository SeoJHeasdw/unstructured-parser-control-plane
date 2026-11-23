import { useId, useMemo, useRef, useState } from 'react';
import {
  ArrowDownUp, ArrowRight, ChevronDown, ChevronRight, FolderOpen,
  RotateCcw, Search, Workflow, X,
} from 'lucide-react';
import type { DocumentFilter, DocumentItem } from './types';
import { FileIcon, Status, attention } from './DocumentCommon';
import './documents.css';

type Props = {
  docs: DocumentItem[];
  filter: DocumentFilter;
  onFilterChange: (filter: DocumentFilter) => void;
  onOpenDoc: (id: string) => void;
  onPipeline: (format: string) => void;
};

type Sort = 'latest' | 'name' | 'attention';
const ATTENTION_FILTER = '확인 필요 전체';
const STATUS_OPTIONS = ['처리 완료', '처리 중', '처리 대기', '검토 필요', '형식 확인 필요', '처리 실패'];
const issuePriority = new Map([['처리 실패', 0], ['형식 확인 필요', 1], ['검토 필요', 2]]);
const ORDER: { value: Sort; label: string }[] = [
  { value: 'latest', label: '최근 순' },
  { value: 'name', label: '이름 순' },
  { value: 'attention', label: '확인 필요 우선' },
];

export function DocumentBrowser({ docs, filter, onFilterChange, onOpenDoc, onPipeline }: Props) {
  const query = filter.query ?? '';
  const status = filter.status === '전체 상태' ? '' : filter.status ?? '';
  const format = filter.format === '전체 형식' ? '' : filter.format ?? '';
  const source = filter.source === '전체 원천' ? '' : filter.source ?? '';
  const [sort, setSort] = useState<Sort>('latest');
  const listHeading = useId();
  const formatSelect = useRef<HTMLSelectElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);

  const inventory = useMemo(() => ({
    formats: [...new Set(docs.map(d => d.format))].sort(),
    sources: [...new Set(docs.map(d => d.source))].sort((a, b) => a.localeCompare(b, 'ko')),
    statuses: [...new Set([...STATUS_OPTIONS, ...docs.map(d => d.status)])],
    complete: docs.filter(d => d.status === '처리 완료').length,
    attention: docs.filter(d => attention(d.status)).length,
  }), [docs]);

  const visible = useMemo(() => {
    const terms = query.trim().toLocaleLowerCase('ko').split(/\s+/).filter(Boolean);
    const matches = docs.filter(doc => {
      const matchesStatus = !status || (status === ATTENTION_FILTER ? attention(doc.status) : doc.status === status);
      if (!matchesStatus || (format && doc.format !== format) || (source && doc.source !== source)) return false;
      const indexed = [doc.name, doc.id, doc.source, doc.format, doc.parser].join(' ').toLocaleLowerCase('ko');
      return terms.every(term => indexed.includes(term));
    });
    if (sort === 'name') return matches.sort((a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true }));
    if (sort === 'attention') return matches.sort((a, b) => (issuePriority.get(a.status) ?? 3) - (issuePriority.get(b.status) ?? 3));
    return matches;
  }, [docs, query, status, format, source, sort]);

  const filtered = Boolean(query || status || format || source);
  const changeStatus = (next?: string) => onFilterChange({ ...filter, status: next });
  const clear = () => {
    onFilterChange({});
    searchInput.current?.focus();
  };

  return (
    <div className="doc-space">
      <section className="doc-list-panel inventory-panel" aria-labelledby={listHeading}>
        <header className="inventory-panel-heading">
          <div>
            <h2 id={listHeading}>문서 목록 <span>{docs.length.toLocaleString('ko-KR')}건</span></h2>
            <p>문서를 선택해 처리 이력과 참조 근거를 확인하세요.</p>
          </div>
          <div className="inventory-order">
            <ArrowDownUp size={16} aria-hidden="true" />
            <select aria-label="문서 정렬" value={sort} onChange={event => setSort(event.target.value as Sort)}>
              {ORDER.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <ChevronDown size={14} aria-hidden="true" />
          </div>
        </header>
        <div className="inventory-toolbar" aria-label="문서 목록 검색과 필터">
          <div className="inventory-search">
            <Search size={18} aria-hidden="true" />
            <input ref={searchInput} value={query} onChange={event => onFilterChange({ ...filter, query: event.target.value })}
              placeholder="파일명, ID, 원천 검색" aria-label="문서 검색" />
            {query && <button type="button" className="inventory-icon-button" aria-label="검색어 지우기" onClick={() => {
              onFilterChange({ ...filter, query: undefined });
              searchInput.current?.focus();
            }}><X size={16} aria-hidden="true" /></button>}
          </div>
          <div className="inventory-filters">
            <label className={`inventory-select${status ? ' is-active' : ''}`}>
              <select aria-label="문서 상태" value={status} onChange={event => changeStatus(event.target.value || undefined)}>
                <option value="">전체 상태</option>
                <option value={ATTENTION_FILTER}>{ATTENTION_FILTER}</option>
                {inventory.statuses.map(item => <option key={item}>{item}</option>)}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
            <label className={`inventory-select${format ? ' is-active' : ''}`}>
              <select ref={formatSelect} aria-label="문서 형식" value={format}
                onChange={event => onFilterChange({ ...filter, format: event.target.value || undefined })}>
                <option value="">전체 형식</option>
                {inventory.formats.map(item => <option key={item}>{item}</option>)}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
            <label className={`inventory-select${source ? ' is-active' : ''}`}>
              <select aria-label="문서 원천" value={source}
                onChange={event => onFilterChange({ ...filter, source: event.target.value || undefined })}>
                <option value="">전체 원천</option>
                {inventory.sources.map(item => <option key={item}>{item}</option>)}
              </select>
              <ChevronDown size={14} aria-hidden="true" />
            </label>
          </div>
          {filtered && <button type="button" className="inventory-reset" onClick={clear}>
            <RotateCcw size={15} aria-hidden="true" />초기화
          </button>}
        </div>
        {format && (
          <div className="inventory-format-context">
            <Workflow size={17} aria-hidden="true" />
            <span><b>{format}</b> 형식의 처리 경로</span>
            <button type="button" className="inventory-text-button" onClick={() => onPipeline(format)}>
              처리 경로 보기 <ArrowRight size={15} aria-hidden="true" />
            </button>
          </div>
        )}

        {visible.length > 0 ? (
          <div className="inventory-scroll">
            <table className="inventory-table" aria-labelledby={listHeading}>
              <colgroup>
                <col className="inventory-col-file" />
                <col className="inventory-col-source" />
                <col className="inventory-col-state" />
                <col className="inventory-col-route" />
                <col className="inventory-col-recent" />
              </colgroup>
              <thead><tr>
                <th scope="col" aria-sort={sort === 'name' ? 'ascending' : undefined}>문서명</th>
                <th scope="col" className="inventory-source-cell">원천</th>
                <th scope="col" aria-sort={sort === 'attention' ? 'other' : undefined}>처리 상태</th>
                <th scope="col" className="inventory-route-cell">처리 경로</th>
                <th scope="col" className="inventory-recent-cell" aria-sort={sort === 'latest' ? 'descending' : undefined}>최근 처리</th>
              </tr></thead>
              <tbody>{visible.map(doc => (
                <tr key={doc.id}>
                  <td>
                    <button type="button" className="doc-name-button inventory-file-button" onClick={() => onOpenDoc(doc.id)}>
                      <FileIcon format={doc.format} />
                      <span className="inventory-file-text">
                        <b title={doc.name}>{doc.name}</b>
                        <span className="inventory-file-meta">
                          <span className="inventory-format">{doc.format}</span>
                          <span className="inventory-file-size">{doc.size}</span>
                          <span className="inventory-file-id">{doc.id}</span>
                          <span className="inventory-file-source">{doc.source}</span>
                        </span>
                      </span>
                      <ChevronRight className="inventory-file-arrow" size={17} aria-hidden="true" />
                    </button>
                  </td>
                  <td className="inventory-source-cell">{doc.source}</td>
                  <td><Status status={doc.status} /><span className="inventory-secondary-line">{doc.stage}</span></td>
                  <td className="inventory-route-cell">{doc.parser}</td>
                  <td className="inventory-recent-cell">{doc.updated}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : (
          <div className="inventory-empty">
            <span className="inventory-empty-icon">
              {docs.length ? <Search size={24} strokeWidth={1.6} aria-hidden="true" /> : <FolderOpen size={24} strokeWidth={1.6} aria-hidden="true" />}
            </span>
            <strong>{docs.length ? '조건에 맞는 문서가 없습니다' : '표시할 문서가 없습니다'}</strong>
            <p>{docs.length ? '다른 검색어를 입력하거나 필터를 초기화하세요.' : '준비된 예시 문서가 없습니다.'}</p>
            {!!docs.length && <button type="button" className="inventory-secondary" onClick={clear}>필터 초기화</button>}
          </div>
        )}
        <footer className="inventory-panel-footer" aria-live="polite" aria-atomic="true">
          <b>{visible.length.toLocaleString('ko-KR')}건 표시</b>
          {filtered && <span>전체 {docs.length.toLocaleString('ko-KR')}건</span>}
        </footer>
      </section>
    </div>
  );
}
