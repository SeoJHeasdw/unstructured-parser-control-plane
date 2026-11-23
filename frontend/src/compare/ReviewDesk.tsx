import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { BookOpen, GitCompareArrows, LocateFixed } from 'lucide-react';
import { ResultReview, type ResultPane, type ReviewEvidence, type ReviewLocation } from './ResultReview';
import { columnName } from './worksheet';
import { lines } from './diff';
import type { ReviewMode } from '../navigation';
import './compare.css';

type Props = {
  mode: ReviewMode; onMode: (mode: ReviewMode) => void; canCompare: boolean;
  baseline?: ResultPane; candidate?: ResultPane; original: ReactNode; summary: ReactNode;
  sourcePane?: ResultPane; sourceControl?: ReactNode; pairControls?: ReactNode;
  sourceStatus?: ReactNode; pairStatus?: ReactNode;
  sourceKey?: string; onEvidenceSide?: (side: ReviewEvidence['side']) => void;
  onLocation: (location: ReviewLocation) => void;
};
export function ReviewDesk({ mode, onMode, canCompare, baseline, candidate, original, summary, sourcePane, sourceControl, pairControls, sourceStatus, pairStatus, sourceKey, onEvidenceSide, onLocation }: Props) {
  const [mobilePane, setMobilePane] = useState<'original' | 'output'>('output');
  const [page, setPage] = useState(0);
  const [highlight, setHighlight] = useState<{line: number; text?: string}>();
  const [openedRuns, setOpenedRuns] = useState(mode === 'runs');
  const [openedSummary, setOpenedSummary] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const source = useRef<HTMLDivElement>(null);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const view = canCompare ? mode : 'source';
  const output = useMemo(() => sourcePane?.text ? lines(sourcePane.text) : [], [sourcePane?.text]);
  useEffect(() => { if (mode === 'runs') setOpenedRuns(true); }, [mode]);
  const lastSource = useRef(sourceKey);
  useEffect(() => {
    if (lastSource.current === sourceKey) return;
    lastSource.current = sourceKey;
    if (!highlight || highlight.text !== sourcePane?.text) { setPage(0); setHighlight(undefined); }
  }, [sourceKey, highlight, sourcePane?.text]);
  useEffect(() => {
    const box = viewport.current;
    const line = box?.querySelector<HTMLElement>('.source-line.is-evidence');
    if (view === 'source' && box && line) box.scrollTop += line.getBoundingClientRect().top - box.getBoundingClientRect().top;
  }, [highlight, view, sourcePane?.text, mobilePane]);
  const pageCount = Math.max(1, Math.ceil(output.length / 120));
  const shownPage = Math.min(page, pageCount - 1);
  const reveal = (location: ReviewLocation, line: number, side?: ReviewEvidence['side']) => {
    const pane = side ? side === 'left' ? baseline : candidate : sourcePane;
    if (side) onEvidenceSide?.(side);
    setHighlight({line, text:pane?.text});
    setPage(Math.floor((line - 1) / 120));
    if (view === 'runs') evidenceTrigger.current = document.activeElement as HTMLElement;
    onLocation(location); setMobilePane('original'); onMode('source');
    requestAnimationFrame(() => source.current?.focus({ preventScroll: true }));
  };
  useEffect(() => {
    if (view !== 'runs' || !evidenceTrigger.current) return;
    const frame = requestAnimationFrame(() => evidenceTrigger.current?.focus({preventScroll:true}));
    return () => cancelAnimationFrame(frame);
  }, [view]);
  return <div className="review-desk">
    <div className="review-mode-bar"><div className="review-modes" role="group" aria-label="검수 방식">
      <button aria-pressed={view === 'source'} onClick={() => onMode('source')}><BookOpen size={17}/>원문 대조</button>
      <button aria-pressed={view === 'runs'} disabled={!canCompare} onClick={() => onMode('runs')}><GitCompareArrows size={17}/>실행 비교</button>
    </div>{!canCompare && <small>실행 비교는 성공한 결과 2개부터 가능합니다.</small>}</div>
    <div hidden={view !== 'source'}>
      <div className="review-mobile-switch" role="group" aria-label="대조 자료">
        <button aria-pressed={mobilePane === 'original'} onClick={() => setMobilePane('original')}>원문</button>
        <button aria-pressed={mobilePane === 'output'} onClick={() => setMobilePane('output')}>추출 결과</button>
      </div>
      <div className="source-pair" data-pane={mobilePane}>
        <div className="source-original" ref={source} tabIndex={-1}>{original}</div>
        <section className="source-output" aria-label="추출 결과"><header><h2>추출 결과</h2>{sourceControl}{sourcePane?.meta}</header>
          <div className="source-lines" ref={viewport} tabIndex={0} aria-label="추출 본문">
          {sourceStatus}
          {!sourceStatus && !output.length && <p>표시할 추출 텍스트가 없습니다.</p>}
          {output.slice(shownPage * 120, (shownPage + 1) * 120).map((value, i) => {
            const number = shownPage * 120 + i + 1;
            const locations = sourcePane?.locations?.filter(l => l.start_line <= number && l.end_line >= number) ?? [];
            const origins = new Map<string, ReviewLocation>();
            for (const l of locations) {
              if (l.page) origins.set(`원문 ${l.page}쪽`, {page:l.page, sheet:null});
              else if (l.sheet && l.column && l.row) {
                const cell = columnName(l.column) + l.row;
                origins.set(l.sheet + '!' + cell, {page:null, sheet:l.sheet, cell});
              }
            }
            return <div className={'source-line' + (highlight?.line === number && highlight.text === sourcePane?.text ? ' is-evidence' : '')} key={number}><small aria-hidden="true">{number}</small><div>{value || ' '}
              {Array.from(origins, ([label, loc]) => <button className="evidence-link" key={label} onClick={() => reveal(loc, number)}><LocateFixed size={14}/>{label}</button>)}</div></div>;
          })}</div>
          {!sourceStatus && !sourcePane?.locations?.length && <p className="reader-foot">원문 위치 미기록 · 원본에서 직접 확인하세요.</p>}
          {pageCount > 1 && <div className="compare-pages"><button disabled={!shownPage} onClick={() => setPage(shownPage - 1)}>이전</button><span>{shownPage+1} / {pageCount}</span><button disabled={shownPage >= pageCount-1} onClick={() => setPage(shownPage + 1)}>다음</button></div>}
        </section>
      </div>
    </div>
    {canCompare && (view === 'runs' || openedRuns) && <div hidden={view !== 'runs'}>
      {pairControls && <details className="review-options"><summary>비교할 실행 선택</summary>{pairControls}</details>}
      {pairStatus ?? <ResultReview baseline={baseline} candidate={candidate} onEvidence={({location, side, line}) => reveal(location, line, side)} />}
      <details className="review-options" onToggle={event => { if (event.currentTarget.open) setOpenedSummary(true); }}><summary>변화 지표와 정답 대조</summary>{openedSummary && !pairStatus && summary}</details>
    </div>}
  </div>;
}
