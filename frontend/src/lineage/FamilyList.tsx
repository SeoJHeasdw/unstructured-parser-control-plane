import { CircleDashed, CircleSlash, Copy, History, Search, Split, X } from 'lucide-react';
import type { LineageData, LnFamily } from '../api/lineage';
import { FILTERS, LATEST_META, familyMatches, timeText } from './model';
import type { Filter } from './model';
import { useHoverProps } from './Tip';

type Props = {
  data: LineageData; shown: LnFamily[]; selected: string | null; onSelect: (id: string) => void;
  query: string; onQuery: (value: string) => void; filter: Filter; onFilter: (value: Filter) => void;
  moreFilters: boolean; onMoreFilters: (open: boolean) => void; related: Set<string> | null; onHoverFamily: (id: string | null) => void;
};

export function FamilyList({ data, shown, selected, onSelect, query, onQuery, filter, onFilter, moreFilters, onMoreFilters, related, onHoverFamily }: Props) {
  const hover = useHoverProps();
  const count = (id: Filter) => data.families.filter(family => familyMatches(family, id)).length;
  const visible = FILTERS.filter(item => item.essential || moreFilters || item.id === filter);
  return <aside className="ln-list" aria-label="문서군 목록">
    <div className="ln-search"><Search size={14} aria-hidden="true" /><input value={query} onChange={event => onQuery(event.target.value)} placeholder="이름 · 문서번호 검색" aria-label="문서군 검색" />{query && <button onClick={() => onQuery('')} aria-label="검색어 지우기"><X size={13} /></button>}</div>
    <div className="ln-chips" role="group" aria-label="문서군 필터">
      {visible.map(item => <button key={item.id} className={filter === item.id ? 'is-on' : ''} aria-pressed={filter === item.id} onClick={() => onFilter(item.id)}>{item.label}<span>{count(item.id)}</span></button>)}
      <button className="ln-chip-more" aria-expanded={moreFilters} onClick={() => onMoreFilters(!moreFilters)}>{moreFilters ? '필터 접기' : '필터 더보기'}</button>
    </div>
    {shown.length ? <ul className="ln-fams">
      {shown.map(family => {
        const latest = data.entries[family.latest.entry];
        const meta = LATEST_META[family.latest.status];
        const outdated = family.counts.out.outdated + family.counts.in.outdated;
        const dim = related ? (related.has(family.id) ? ' is-hl' : ' is-dim') : '';
        return <li key={family.id}>
          <button className={`ln-fam${selected === family.id ? ' is-on' : ''}${dim}`} aria-current={selected === family.id ? 'true' : undefined} onClick={() => onSelect(family.id)}
            {...hover(`fam:${family.id}`, () => <FamilyTip data={data} family={family} />, on => onHoverFamily(on ? family.id : null))}>
            <i className={`ln-dot is-${meta.tone}`} aria-hidden="true" />
            <span className="ln-fam-main"><b>{family.title}</b><small>{family.latest.status === 'hold' ? '판단 보류' : latest.label} · {family.entries.length}판{family.files > 1 ? ` · 파일 ${family.files}` : ''}</small></span>
            <span className="ln-fam-marks">
              {outdated > 0 && <em className="is-warn" title="구버전 참조"><History size={11} aria-hidden="true" />{outdated}<span className="ln-sr"> 구버전 참조</span></em>}
              {family.counts.out.missing > 0 && <em className="is-error" title="대상 미발견"><CircleSlash size={11} aria-hidden="true" />{family.counts.out.missing}<span className="ln-sr"> 대상 미발견</span></em>}
              {family.flags.includes('ambiguous') && <em className="is-amb" title="후보 여러 개"><Split size={11} aria-hidden="true" /><span className="ln-sr">후보 여러 개</span></em>}
              {family.counts.duplicates > 0 && <em className="is-info" title="같은 내용 파일"><Copy size={11} aria-hidden="true" /><span className="ln-sr">중복</span></em>}
              {family.analysed !== 'all' && <em className="is-muted" title="구조 분석 전 파일 있음"><CircleDashed size={11} aria-hidden="true" /><span className="ln-sr">구조 분석 전</span></em>}
            </span>
          </button>
        </li>;
      })}
    </ul> : <div className="ln-list-empty">{data.families.length ? '조건에 맞는 문서군이 없습니다.' : '표시할 문서군이 없습니다.'}</div>}
  </aside>;
}

function FamilyTip({ data, family }: { data: LineageData; family: LnFamily }) {
  const latest = data.entries[family.latest.entry];
  const file = data.instances[latest.primary];
  return <>
    <strong>{family.title}</strong>
    <span>{LATEST_META[family.latest.status].label} · {file.name}</span>
    {family.latest.status === 'hold' ? <span className="is-warn">{family.latest.conflicts[0]?.message}</span> : family.latest.reasons[0] && <span>근거: {family.latest.reasons.map(reason => reason.label).join(', ')}</span>}
    <span className="ln-tip-muted">최근 반입 {timeText(latest.uploaded_at)}</span>
  </>;
}
