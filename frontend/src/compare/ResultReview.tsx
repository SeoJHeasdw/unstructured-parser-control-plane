import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react';
import type { ResultLocation } from '../api/live';
import { alignResults, diagnosticLabels, highlightParts, LINE_LIMIT, lines } from './diff';
import type { Diagnostic, DiffRow } from './diff';

export type ResultPane = { text: string; meta: ReactNode; locations?: ResultLocation[] };
export type ReviewLocation = { page: number | null; sheet: string | null; cell?: string };
const PAGE_SIZE = 200;

function columnName(column: number): string {
  let label = '';
  for (let index = column; index > 0; index = Math.floor((index - 1) / 26)) {
    label = String.fromCharCode(65 + (index - 1) % 26) + label;
  }
  return label;
}

function reviewLocations(row: DiffRow, baseline?: ResultPane, candidate?: ResultPane): ReviewLocation[] {
  const parts = row.left && row.right ? highlightParts(row.left.text, row.right.text) : undefined;
  const locations: ReviewLocation[] = [];
  for (const [side, entry, pane] of [[0, row.left, baseline], [1, row.right, candidate]] as const) {
    if (!entry || !pane?.locations) continue;
    const changed: [number, number][] = [];
    let offset = 0;
    (parts?.[side] ?? [{ text: entry.text, changed: true }]).forEach(part => {
      if (part.changed && part.text.trim()) changed.push([offset, offset + part.text.length]);
      offset += part.text.length;
    });
    for (const source of pane.locations) {
      if (source.start_line > entry.line || source.end_line < entry.line) continue;
      if (source.page && changed.some(([start, end]) =>
        start < (source.end_offset ?? Infinity) && end > (source.start_offset ?? 0))) {
        locations.push({ page: source.page, sheet: null });
      }
      const { sheet, column, row: sourceRow, columns } = source;
      if (sheet && column && sourceRow && columns) {
        const changedColumn = (row.columns ?? [0]).find(index => index < columns);
        if (changedColumn !== undefined) locations.push({ page: null, sheet, cell: `${columnName(column + changedColumn)}${sourceRow}` });
      }
    }
  }
  return locations.filter((item, index) => locations.findIndex(location =>
    location.page === item.page && location.sheet === item.sheet && location.cell === item.cell) === index);
}

const kindLabels = { same: '', changed: '내용 변경', removed: '현재 실행에서 빠짐', added: '현재 실행에 추가' };

export function ResultReview({ baseline, candidate, original, baselineControl, candidateControl, showOriginal, showAlternative, highlight,
  onLocation }: {
  baseline?: ResultPane; candidate?: ResultPane; original: ReactNode; baselineControl?: ReactNode; candidateControl?: ReactNode;
  showOriginal: boolean; showAlternative: boolean; highlight: boolean; onLocation?: (location?: ReviewLocation, reveal?: boolean) => void;
}) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [filter, setFilter] = useState<Diagnostic | 'all'>('all');
  const target = useRef<HTMLDivElement>(null);
  const canCompare = !!baseline?.text.trim() && !!candidate?.text.trim();
  const { rows, truncated } = useMemo(() => {
    const left = baseline?.text.trim() ? lines(baseline.text) : [];
    const right = candidate?.text.trim() ? lines(candidate.text) : [];
    const a = left.slice(0, LINE_LIMIT), b = right.slice(0, LINE_LIMIT);
    const rows: DiffRow[] = canCompare ? alignResults(a, b) : Array.from({ length: Math.max(a.length, b.length) }, (_, index) => ({
      left: index < a.length ? { text: a[index], line: index + 1 } : undefined,
      right: index < b.length ? { text: b[index], line: index + 1 } : undefined,
      kind: 'same',
    }));
    return { rows, truncated: left.length > LINE_LIMIT || right.length > LINE_LIMIT };
  }, [baseline?.text, candidate?.text, canCompare]);
  const changes = useMemo(() => rows.flatMap((row, index) => row.kind !== 'same' ? [index] : []), [rows]);
  const categories = useMemo(() => {
    const result: Record<Diagnostic, number> = { number: 0, reference: 0, table: 0 };
    changes.forEach(index => rows[index].notes?.forEach(note => result[note.type]++));
    return result;
  }, [changes, rows]);
  const filtered = useMemo(() => filter === 'all' ? changes : changes.filter(index => rows[index].notes?.some(note => note.type === filter)), [changes, filter, rows]);
  const current = selected !== null ? rows[selected] : undefined;
  const currentIndex = selected === null ? -1 : filtered.indexOf(selected);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const origins = current ? reviewLocations(current, baseline, candidate) : [];
  useEffect(() => { if (selected !== null) target.current?.scrollIntoView?.({ block: 'nearest' }); }, [selected]);

  function select(index: number) {
    setSelected(index);
    setPage(Math.floor(index / PAGE_SIZE));
    const locations = reviewLocations(rows[index], baseline, candidate);
    onLocation?.(locations.length === 1 ? locations[0] : undefined);
  }

  function selectFilter(next: typeof filter) {
    setFilter(next);
    const first = changes.find(index => next === 'all' || rows[index].notes?.some(note => note.type === next));
    if (first !== undefined) select(first);
  }

  function renderColumn(side: 'left' | 'right', pane: ResultPane | undefined, control: ReactNode) {
    const isBaseline = side === 'left';
    const hasOutput = !!pane?.text.trim();
    return <section className={`panel compare-result ${isBaseline ? 'is-baseline' : 'is-candidate'}`} aria-label={isBaseline ? '이전 실행' : '현재 실행'}>
      <div className="compare-result-head">
        <h2>{isBaseline ? '이전 실행' : '현재 실행'}</h2>
        {control}
        {pane?.meta}
      </div>
      {hasOutput && visible.map((row, offset) => {
        const index = page * PAGE_SIZE + offset, entry = row[side];
        const isChanged = row.kind !== 'same';
        const parts = highlight && isChanged && row.left && row.right
          ? highlightParts(row.left.text, row.right.text)[isBaseline ? 0 : 1] : undefined;
        return <div key={index} ref={index === selected && isBaseline ? target : undefined}
          className={`compare-line${isChanged && highlight ? ' is-different' : ''}${index === selected ? ' is-selected' : ''}${!entry ? ' is-gap' : ''}`}>
          {entry && <><span className="compare-line-no" aria-hidden="true">{entry.line}</span><span className="compare-line-text">
            {parts ? parts.map((part, i) => part.changed ? <mark key={i}>{part.text}</mark> : part.text) : entry.text}
          </span></>}
        </div>;
      })}
      <div className="compare-result-end" style={hasOutput ? undefined : { gridRow: '2/-1' }}>{!hasOutput && <p>표시할 파싱 결과가 없습니다.</p>}</div>
    </section>;
  }

  return <>
    <section className="compare-review-bar" aria-label="차이 검수">
      <div className="compare-review-main">
        <strong>{!canCompare ? '비교할 결과 없음' : changes.length ? `차이 ${changes.length.toLocaleString()}곳` : '표시된 결과에 차이 없음'}</strong>
        {canCompare && changes.length > 0 && <>
          <div className="compare-review-filters" role="group" aria-label="검수 유형">
            {Object.entries(categories).filter(([, count]) => count > 0).map(([key, count]) =>
              <button key={key} type="button" className="compare-diagnostic-filter" aria-pressed={filter === key}
                onClick={() => selectFilter(filter === key ? 'all' : key as Diagnostic)}>{diagnosticLabels[key as Diagnostic]} {count}</button>)}
          </div>
          <div className="compare-review-nav" role="group" aria-label="차이 이동">
            <button type="button" title="이전 차이" aria-label="이전 차이" disabled={currentIndex < 1} onClick={() => select(filtered[currentIndex - 1])}><ArrowUp size={15} /></button>
            <span aria-live="polite">{currentIndex < 0 ? '—' : currentIndex + 1} / {filtered.length}</span>
            <button type="button" title="다음 차이" aria-label="다음 차이" disabled={currentIndex >= filtered.length - 1} onClick={() => select(filtered[currentIndex + 1])}><ArrowDown size={15} /></button>
          </div>
        </>}
      </div>
      {current && <div className="compare-review-detail" aria-live="polite">
        <b>{kindLabels[current.kind]}</b>
        {current.notes?.map(note => <span key={note.type}><strong>{note.label}</strong> {note.detail}</span>)}
        {onLocation && origins.map(origin => <button type="button" className="button-quiet" key={origin.page ?? `${origin.sheet}!${origin.cell}`} onClick={() => onLocation(origin, true)}>
          {origin.page ? `원문 ${origin.page}쪽` : `${origin.sheet}!${origin.cell}`} <ArrowRight size={13} />
        </button>)}
      </div>}
      {truncated && <p className="compare-limit">결과별 첫 {LINE_LIMIT.toLocaleString()}줄을 비교했어요.</p>}
    </section>
    <div className="compare-review-surface" data-original={showOriginal} data-candidate={showAlternative}>
      {showOriginal && original}
      <div className="compare-results" style={{ gridTemplateRows: `auto ${visible.length ? `repeat(${visible.length}, minmax(27px, auto)) ` : ''}1fr` }}>
        {renderColumn('left', baseline, baselineControl)}
        {showAlternative && renderColumn('right', candidate, candidateControl)}
      </div>
    </div>
    {pages > 1 && <div className="compare-pages" role="group" aria-label="결과 페이지">
      <button type="button" title="이전 결과 페이지" aria-label="이전 결과 페이지" disabled={!page} onClick={() => { setPage(page - 1); setSelected(null); }}><ArrowLeft size={15} /></button>
      <span>{page + 1} / {pages}</span>
      <button type="button" title="다음 결과 페이지" aria-label="다음 결과 페이지" disabled={page >= pages - 1} onClick={() => { setPage(page + 1); setSelected(null); }}><ArrowRight size={15} /></button>
    </div>}
  </>;
}
