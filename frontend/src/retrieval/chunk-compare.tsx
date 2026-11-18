import { ChevronRight } from 'lucide-react';
import type { DocElement, ElementKind, ElementOutcome, StrategyResult } from '../api/retrieval';
import { ELEMENT_META, outcomeTone } from './elements';
import type { Column } from './chunk-board';
import { describeParams, fmtInt, isBaseline } from './shared';

/* ---------- 문서 구성: 본문·표·그림·캡션·반복 머리말 ---------- */
export const COMPOSITION: { id: string; label: string; kinds: ElementKind[]; color: string }[] = [
  { id: 'text', label: '본문', kinds: ['text', 'list', 'code'], color: ELEMENT_META.text.color },
  { id: 'table', label: '표', kinds: ['table'], color: ELEMENT_META.table.color },
  { id: 'image', label: '그림', kinds: ['image'], color: ELEMENT_META.image.color },
  { id: 'caption', label: '캡션', kinds: ['caption'], color: ELEMENT_META.caption.color },
  { id: 'furniture', label: '반복 머리말', kinds: ['furniture'], color: ELEMENT_META.furniture.color },
];
export function compositionParts(composition: Partial<Record<ElementKind, number>>) {
  return COMPOSITION.map(group => ({ ...group, count: group.kinds.reduce((sum, kind) => sum + (composition[kind] ?? 0), 0) })).filter(part => part.count > 0);
}

/** 문서 구성 한 줄: 얇은 누적 막대 + 종류별 개수. */
export function CompositionBar({ composition, bar = true }: { composition: Partial<Record<ElementKind, number>>; bar?: boolean }) {
  const parts = compositionParts(composition);
  if (!parts.length) return null;
  const total = parts.reduce((sum, part) => sum + part.count, 0);
  return <div className="cb-comp">
    {bar && <span className="cb-comp-bar" aria-hidden="true">{parts.map(part => <i key={part.id} style={{ flexGrow: part.count, background: part.color }} />)}</span>}
    <ul className="cb-comp-list" aria-label={`문서 구성 · 요소 ${fmtInt(total)}개`}>
      {parts.map(part => <li key={part.id}><i style={{ background: part.color }} />{part.label}<b>{fmtInt(part.count)}</b></li>)}
    </ul>
  </div>;
}

/* ---------- 요소 종류별 집계 ---------- */
export type Tally = { total: number; good: number; split: number; missing: number; detached: number; kept: number; excused: number };
/** 서버가 준 종류별 집계(by_kind)를 우선 쓰고, 없으면 요소별 결과로 센다. 글자 없는 그림이 빠진 것은 전략 탓이 아니므로 따로 센다. */
export function tallyKind(result: StrategyResult, kind: ElementKind, elements: DocElement[]): Tally {
  const t: Tally = { total: 0, good: 0, split: 0, missing: 0, detached: 0, kept: 0, excused: 0 };
  const add = (outcome: ElementOutcome, n: number) => {
    t.total += n;
    if (outcomeTone(kind, outcome) === 'good') t.good += n;
    else if (outcome === 'split') t.split += n;
    else if (outcome === 'detached') t.detached += n;
    else if (outcome === 'missing') t.missing += n;
    else if (kind === 'furniture') t.kept += n;
  };
  const counts = result.by_kind?.[kind];
  const own = elements.filter(el => el.kind === kind);
  if (counts && Object.keys(counts).length) for (const [outcome, n] of Object.entries(counts) as [ElementOutcome, number][]) add(outcome, n ?? 0);
  else for (const el of own) { const o = result.outcomes?.[el.id]; if (o) add(o, 1); else { t.total++; if (kind !== 'furniture') t.missing++; } }
  if (kind === 'image') {
    const empty = own.filter(el => el.empty && (result.outcomes?.[el.id] ?? 'missing') === 'missing').length;
    t.excused = Math.min(empty, t.missing);
    t.missing -= t.excused;
  }
  return t;
}
const problem = (kind: ElementKind, t: Tally) =>
  kind === 'table' ? (t.split ? `${fmtInt(t.split)}개 잘림` : t.missing ? `${fmtInt(t.missing)}개 빠짐` : '')
    : kind === 'image' ? (t.missing ? `${fmtInt(t.missing)}개 빠짐` : '')
      : kind === 'caption' ? (t.detached ? `${fmtInt(t.detached)}개 떨어짐` : t.missing ? `${fmtInt(t.missing)}개 빠짐` : '')
        : t.kept ? `${fmtInt(t.kept)}개 남음` : '';

const KIND_COLUMNS: { kind: ElementKind; label: string }[] = [
  { kind: 'table', label: '표 보존' },
  { kind: 'image', label: '그림' },
  { kind: 'caption', label: '캡션 함께' },
  { kind: 'furniture', label: '머리말 제거' },
];

/**
 * 전략 비교 표: 줄 = 전략, 칸 = 청크 수·길이와 요소 종류별 보존.
 * 칸마다 가장 나은 값은 굵게, 문제(잘림·빠짐·떨어짐·남음·한도 초과)만 붉게.
 */
type TableProps = { columns: Column[]; elements: DocElement[]; limit: number | null; busy: boolean; onOpen: (id: string) => void };
export function CompareTable({ columns, elements, limit, busy, onOpen }: TableProps) {
  const kinds = KIND_COLUMNS.filter(col => elements.some(el => el.kind === col.kind));
  const ok = columns.filter(c => !c.result.error);
  const tallies = new Map(columns.map(c => [c.id, new Map(kinds.map(k => [k.kind, tallyKind(c.result, k.kind, elements)]))]));
  /* 칸마다 최고 비율. 모두 같으면 굵게 하지 않는다. */
  const best = new Map(kinds.map(k => {
    const ratios = ok.map(c => { const t = tallies.get(c.id)!.get(k.kind)!; return t.total ? t.good / t.total : 0; });
    const top = Math.max(...ratios);
    return [k.kind, ratios.length > 1 && ratios.some(r => r !== top) ? top : null] as const;
  }));
  const span = 3 + kinds.length + (limit ? 1 : 0);
  return <div className={`cb-table-wrap${busy ? ' is-busy' : ''}`} tabIndex={0} role="region" aria-label="청킹 전략 및 지표">
    <table className="cb-cmp" aria-label="전략 비교">
      <thead><tr>
        <th scope="col" className="cb-cmp-name">전략</th>
        <th scope="col" className="num">청크 수</th>
        <th scope="col" className="num">길이 중앙값(자)</th>
        {kinds.map(k => <th key={k.kind} scope="col" className="num"><span className="cb-th"><i style={{ background: ELEMENT_META[k.kind].color }} />{k.label}</span></th>)}
        {limit ? <th scope="col" className="num">한도 초과<small>{fmtInt(limit)}토큰</small></th> : null}
      </tr></thead>
      <tbody>{columns.map(c => {
        const s = c.result.stats;
        const baseline = isBaseline(c.kind);
        return <tr key={c.id} className="cb-cmp-row" onClick={event => { event.currentTarget.querySelector<HTMLElement>('.cb-rowbtn')?.focus(); onOpen(c.id); }}>
          <th scope="row" className="cb-cmp-name">
            <button type="button" className="cb-rowbtn"><ChevronRight size={15} aria-hidden="true" />{c.name}</button>{baseline && <span className="cb-base">기준선</span>}
            {c.params && <span className="cb-sub">{describeParams(c.params)}</span>}
          </th>
          {c.result.error ? <td colSpan={span - 1} className="cb-cmp-error" role="alert">{c.result.error}</td> : <>
            <td className="num">{fmtInt(s?.count ?? c.result.chunks.length)}{c.result.parents?.length ? <span className="cb-sub">맥락 {fmtInt(c.result.parents.length)}</span> : null}</td>
            <td className="num">{fmtInt(s?.chars.median)}</td>
            {kinds.map(k => {
              const t = tallies.get(c.id)!.get(k.kind)!;
              const words = problem(k.kind, t);
              const isBest = best.get(k.kind) !== null && t.total > 0 && t.good / t.total === best.get(k.kind);
              return <td key={k.kind} className="num">
                <span className="cb-cell">
                  {k.kind === 'table' && t.total > 0 && <span className="cb-mbar" aria-hidden="true"><i style={{ width: `${(t.good / t.total) * 100}%` }} /><i className="is-bad" style={{ width: `${(t.split / t.total) * 100}%` }} /></span>}
                  <span className={`cb-ratio${words ? ' is-bad' : ''}${isBest ? ' is-best' : ''}`}>{fmtInt(t.good)}<small>/{fmtInt(t.total)}</small></span>
                </span>
                {words && <span className="cb-sub is-bad">{words}</span>}
              </td>;
            })}
            {limit ? <td className="num"><span className={s?.over_limit ? 'cb-ratio is-bad' : 'cb-zero'}>{fmtInt(s?.over_limit ?? 0)}</span></td> : null}
          </>}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
