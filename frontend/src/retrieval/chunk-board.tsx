import { useMemo, useState } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Image as ImageIcon, Scissors } from 'lucide-react';
import type { Chunk, ChunkSource, DocElement, ElementKind, ElementOutcome, StrategyKind, StrategyParams, StrategyResult } from '../api/retrieval';
import { ELEMENT_META, OUTCOME_BAD, outcomeTone } from './elements';
import { fmtInt } from './shared';

/** 비교 표의 한 줄 = 전략 하나와 그 결과. */
export type Column = { id: string; name: string; kind?: StrategyKind; params?: StrategyParams; result: StrategyResult };

/* ---------- 문구 ---------- */
export const pathText = (path: string[]) => path.length ? path.join(' › ') : '제목 없음';
export const preview = (text: string, max = 120) => { const flat = text.replace(/\s+/g, ' ').trim(); return flat.length > max ? `${flat.slice(0, max)}…` : flat; };
export const SHORT_KIND: Partial<Record<ElementKind, string>> = { furniture: '반복 머리말' };
export const kindLabel = (kind: ElementKind) => SHORT_KIND[kind] ?? ELEMENT_META[kind].label;

/** 요소의 사람이 읽는 이름. 본문·목록은 앞부분 글자로 대신한다. */
export function elementName(el: DocElement, text: string, max = 48) {
  const own = () => preview(text.slice(el.start, el.end).replace(/^#+\s*/, ''), max);
  if (el.kind === 'heading') return el.label || own();
  if (el.kind === 'caption' || el.kind === 'text' || el.kind === 'list' || el.kind === 'code') return own() || el.label;
  return el.label || kindLabel(el.kind);
}

/** 요소가 어느 청크에 들었는지: 청크의 elements 목록, 없으면 위치가 겹치는 청크. */
export function chunksByElement(result: StrategyResult, elements: DocElement[]) {
  const map = new Map<string, number[]>();
  const push = (id: string, i: number) => { const list = map.get(id); if (list) { if (list[list.length - 1] !== i) list.push(i); } else map.set(id, [i]); };
  result.chunks.forEach((chunk, i) => {
    if (chunk.elements?.length) chunk.elements.forEach(id => push(id, i));
    else for (const el of elements) if (el.start < chunk.end && el.end > chunk.start) push(el.id, i);
  });
  return map;
}
export const chunkElementIds = (chunk: Chunk, elements: DocElement[]) =>
  chunk.elements?.length ? chunk.elements : elements.filter(el => el.start < chunk.end && el.end > chunk.start).map(el => el.id);

/** 한 요소가 한 전략에서 어떻게 됐는지: '3조각으로 잘림 · 머리행 없음' */
export function outcomePhrase(el: DocElement, outcome: ElementOutcome | undefined, pieces: number): { text: string; bad: boolean } {
  if (!outcome) return pieces > 1 ? { text: `청크 ${pieces}개에 걸침`, bad: false } : pieces ? { text: '청크 하나에 들어감', bad: false } : { text: '청크에 없음', bad: el.kind !== 'furniture' };
  const bad = outcomeTone(el.kind, outcome) === 'bad';
  switch (outcome) {
    case 'whole': return { text: el.kind === 'furniture' ? '청크에 섞임' : pieces > 1 ? `온전 · 청크 ${pieces}개에 겹침` : '온전', bad };
    case 'rows': return { text: `행 묶음 ${Math.max(pieces, 1)}개 · 머리행 반복`, bad };
    case 'split': return { text: `${Math.max(pieces, 2)}조각으로 잘림${el.kind === 'table' ? ' · 머리행 없음' : ''}`, bad };
    case 'caption': return { text: '캡션으로 들어감', bad };
    case 'attached': return { text: '대상과 같은 청크', bad };
    case 'detached': return { text: '대상과 다른 청크', bad };
    case 'missing': return { text: el.kind === 'furniture' ? '제거' : el.empty ? '글자 없음 · 빠짐' : '빠짐', bad };
  }
}

/* ---------- 배치: 높이 ∝ √글자 수, 쪽 경계는 가는 줄 ---------- */
const GAP = 6, PAGE_BAND = 24, PAD = 12;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
function elementHeight(el: DocElement) {
  const s = Math.sqrt(Math.max(1, el.chars));
  switch (el.kind) {
    case 'heading': return 24;
    case 'text': return clamp(Math.round(s * 1.5), 16, 58);
    case 'list': return clamp(Math.round(s * 1.5), 20, 58);
    case 'code': return clamp(Math.round(s * 1.3), 20, 50);
    case 'table': return clamp(14 + Math.min(el.rows ?? 4, 14) * 5, 34, 90);
    case 'image': return 52;
    case 'caption': return 20;
    case 'furniture': return 10;
  }
}
type Placed = { el: DocElement; top: number; h: number };
type Layout = { items: Placed[]; byId: Map<string, Placed>; pages: { page: number; y: number }[]; height: number; yAt: (offset: number) => number };

function layoutDoc(elements: DocElement[]): Layout {
  const items: Placed[] = [];
  const pages: Layout['pages'] = [];
  let y = PAD, page: number | null = null;
  for (const el of elements) {
    if (el.page !== null && el.page !== page) {
      pages.push({ page: el.page, y: y + 2 }); y += PAGE_BAND;
      page = el.page;
    }
    const h = elementHeight(el);
    items.push({ el, top: y, h });
    y += h + GAP;
  }
  const sorted = [...items].sort((a, b) => a.el.start - b.el.start);
  const yAt = (o: number) => {
    if (!sorted.length) return PAD;
    let lo = 0, hi = sorted.length - 1, at = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (sorted[mid].el.start <= o) { at = mid; lo = mid + 1; } else hi = mid - 1; }
    if (at < 0) return sorted[0].top;
    const p = sorted[at], len = p.el.end - p.el.start;
    if (o <= p.el.end) return len > 0 ? p.top + ((o - p.el.start) / len) * p.h : p.top + p.h / 2;
    const next = sorted[at + 1];
    return next ? (p.top + p.h + next.top) / 2 : p.top + p.h;
  };
  return { items, byId: new Map(items.map(p => [p.el.id, p])), pages, height: y + PAD, yAt };
}

/** 청크가 덮는 세로 구간. 글자가 없는 그림은 위치 표시만 있으므로 요소 전체 높이로 넓힌다. */
function chunkSpan(chunk: Chunk, layout: Layout): [number, number] {
  let a = layout.yAt(chunk.start), b = layout.yAt(chunk.end);
  for (const id of chunk.elements ?? []) {
    const p = layout.byId.get(id);
    if (p && (p.el.kind === 'image' || p.el.end <= p.el.start)) { a = Math.min(a, p.top); b = Math.max(b, p.top + p.h); }
  }
  return [a, Math.max(b, a + 4)];
}
function assignLanes(spans: [number, number][]) {
  const ends: number[] = [];
  return spans.map(([a, b]) => {
    let lane = ends.findIndex(end => end <= a + 0.5);
    if (lane < 0) lane = ends.length < 3 ? ends.length : ends.indexOf(Math.min(...ends));
    ends[lane] = b;
    return lane;
  });
}

/* ---------- 원문 축소판의 요소 하나 ---------- */
function ElementGlyph({ el, name }: { el: DocElement; name: string }) {
  switch (el.kind) {
    case 'heading': return <><i className="cb-hbar" /><span className="cb-htext">{name}</span></>;
    case 'text': case 'list': case 'code': return <i className={`cb-lines is-${el.kind}`} />;
    case 'table': {
      const rows = clamp(el.rows ?? 4, 2, 10), cols = clamp(el.cols ?? 3, 2, 6);
      return <><i className="cb-grid" style={{ '--r': rows, '--c': cols } as CSSProperties} /><span className="cb-elabel">{el.label}</span></>;
    }
    case 'image': return <><i className={`cb-img${el.empty ? ' is-empty' : ''}`}>{!el.empty && <ImageIcon size={15} color={ELEMENT_META.image.color} aria-hidden="true" />}</i>
      <span className="cb-elabel">{el.label}{el.empty && <em>글자 없는 그림</em>}</span></>;
    case 'caption': return <span className="cb-cap">{name}</span>;
    case 'furniture': return <i className="cb-furn" />;
  }
}

/**
 * 문서 위 청크: 원문을 요소 단위 세로 축소판으로 그리고, 옆에 이 전략의 청크 괄호만 그린다.
 * 괄호에 올리면 그 청크가 덮는 요소가, 요소에 올리면 그 요소를 담은 청크가 진해진다.
 */
type DocChunksProps = { source: ChunkSource; result: StrategyResult; name: string; picked: number | null; onPick: (index: number) => void };
export function DocChunks({ source, result, name, picked, onPick }: DocChunksProps) {
  const layout = useMemo(() => layoutDoc(source.elements), [source]);
  const [hover, setHover] = useState<{ type: 'chunk'; index: number } | { type: 'element'; id: string } | null>(null);
  const drawn = useMemo(() => {
    const spans = result.chunks.map(chunk => chunkSpan(chunk, layout));
    const lanes = assignLanes(spans);
    const laneCount = Math.max(1, ...lanes.map(l => l + 1));
    const byEl = chunksByElement(result, source.elements);
    /* 머리행 없이 잘린 표: 표 안쪽에 떨어지는 청크 경계마다 붉은 선 */
    const cuts: number[] = [];
    const missing: Placed[] = [];
    for (const p of layout.items) {
      const outcome = result.outcomes?.[p.el.id];
      if (outcome === 'split' && p.el.kind !== 'furniture') {
        for (const chunk of result.chunks) for (const at of [chunk.start, chunk.end]) {
          if (at > p.el.start + 1 && at < p.el.end - 1) { const y = layout.yAt(at); if (!cuts.some(c => Math.abs(c - y) < 3)) cuts.push(y); }
        }
      }
      if (outcome === 'missing' && (p.el.kind === 'image' || p.el.kind === 'table')) missing.push(p);
    }
    const parents = (result.parents ?? []).map(parent => [layout.yAt(parent.start), layout.yAt(parent.end)] as [number, number]);
    return { spans, lanes, laneCount, byEl, cuts, missing, parents };
  }, [result, layout, source.elements]);

  const lit = useMemo(() => {
    if (!hover) return null;
    if (hover.type === 'chunk') {
      const chunk = result.chunks[hover.index];
      return chunk ? { els: new Set(chunkElementIds(chunk, source.elements)), chunks: new Set([hover.index]) } : null;
    }
    return { els: new Set([hover.id]), chunks: new Set(drawn.byEl.get(hover.id) ?? []) };
  }, [hover, result.chunks, source.elements, drawn.byEl]);

  const onKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const node = event.target as HTMLElement;
    if (node.dataset.i === undefined) return;
    const i = Number(node.dataset.i);
    const next = event.key === 'ArrowDown' ? Math.min(result.chunks.length - 1, i + 1) : event.key === 'ArrowUp' ? Math.max(0, i - 1) : -1;
    if (next < 0) return;
    event.preventDefault();
    (event.currentTarget.querySelector(`[data-i="${next}"]`) as HTMLElement | null)?.focus();
  };

  const text = source.text;
  const markX = 16 + drawn.laneCount * 14 + 6;
  const elState = (id: string) => lit ? (lit.els.has(id) ? ' is-lit' : ' is-dim') : '';
  const focusIndex = picked !== null && picked < result.chunks.length ? picked : 0;
  return <div className="cb-mini" style={{ height: layout.height }} onKeyDown={onKey}>
    <div className="cb-mini-doc" aria-hidden="true">
      {layout.pages.map(pg => <span key={pg.page} className="cb-page" style={{ top: pg.y }}>{pg.page}쪽<i /></span>)}
      {layout.items.map(p => <div key={p.el.id} className={`cb-el is-${p.el.kind}${elState(p.el.id)}`} style={{ top: p.top, height: p.h }}
        onMouseEnter={() => setHover({ type: 'element', id: p.el.id })} onMouseLeave={() => setHover(null)}>
        <ElementGlyph el={p.el} name={elementName(p.el, text)} />
      </div>)}
    </div>
    <div className="cb-mini-chunks" role="group" aria-label={`${name} 청크`}>
      {layout.items.map(item => (item.el.kind === 'table' || item.el.kind === 'image') && <i key={item.el.id} className={`cb-band is-${item.el.kind}`} style={{ top: item.top, height: item.h }} />)}
      {drawn.parents.map(([a, b], k) => <i key={`p${k}`} className="cb-parent" style={{ top: a + 1, height: Math.max(4, b - a - 2) }} />)}
      {result.chunks.map((chunk, i) => {
        const [a, b] = drawn.spans[i];
        const state = picked === i ? ' is-picked' : lit ? (lit.chunks.has(i) ? ' is-lit' : ' is-dim') : '';
        return <button key={i} type="button" className={`cb-chunk${state}`} style={{ top: a + 1, height: Math.max(4, b - a - 2), left: 16 + drawn.lanes[i] * 14 }}
          data-i={i} tabIndex={i === focusIndex ? 0 : -1} aria-label={`${i + 1}번 청크 · ${fmtInt(chunk.chars)}자`} aria-pressed={picked === i}
          onClick={() => onPick(i)} onMouseEnter={() => setHover({ type: 'chunk', index: i })} onMouseLeave={() => setHover(null)}
          onFocus={() => setHover({ type: 'chunk', index: i })} onBlur={() => setHover(null)}>{b - a >= 16 && <span className="cb-chunk-no" aria-hidden="true">{i + 1}</span>}</button>;
      })}
      {drawn.cuts.map(y => <span key={`c${y}`} className="cb-cut" style={{ top: y, '--x': `${markX}px` } as CSSProperties} aria-hidden="true"><Scissors size={12} color={OUTCOME_BAD} /></span>)}
      {drawn.missing.map(item => <span key={`m${item.el.id}`} className="cb-lost" style={{ top: item.top + item.h / 2, left: markX }} aria-hidden="true"><i />빠짐</span>)}
    </div>
  </div>;
}
