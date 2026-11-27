import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';
import { BookOpen, GitCompareArrows, LocateFixed } from 'lucide-react';
import { ResultReview, pageLabel, type ResultPane, type ReviewEvidence, type ReviewLocation } from './ResultReview';
import { columnName } from './worksheet';
import { lines } from './diff';
import { lineKinds } from '../markdown';
import type { LineKind } from '../markdown';
import { ResultModeSwitch, useResultMode } from '../MarkdownView';
import type { ReviewMode } from '../navigation';
import type { ShowAt } from './ReviewChecks';
import './compare.css';

const SPLIT_KEY = 'docops.review.split';
const SPLIT_MIN = 25, SPLIT_MAX = 75;
function readSplit() {
  try {
    const value = Number(localStorage.getItem(SPLIT_KEY));
    return value >= SPLIT_MIN && value <= SPLIT_MAX ? value : 50;
  } catch { return 50; }
}
function saveSplit(value: number) {
  try { localStorage.setItem(SPLIT_KEY, String(value)); } catch { /* 기억하지 못해도 동작은 같다 */ }
}

type Props = {
  mode: ReviewMode; onMode: (mode: ReviewMode) => void; canCompare: boolean;
  baseline?: ResultPane; candidate?: ResultPane; original: ReactNode; summary: ReactNode;
  sourcePane?: ResultPane; sourceControl?: ReactNode; pairControls?: ReactNode;
  sourceStatus?: ReactNode; pairStatus?: ReactNode;
  sourceKey?: string; onEvidenceSide?: (side: ReviewEvidence['side']) => void;
  onLocation: (location: ReviewLocation) => void;
  /** 모드 전환 줄 왼쪽에 둘 머리(뒤로 가기·문서 이름). */
  heading?: ReactNode;
  /** 화면 높이를 채우고 두 칸이 각각 안에서 스크롤한다(문서 상세의 원문 대조). */
  fill?: boolean;
  /** 원문 대조 위 '확인할 곳' 막대. show로 원본 위치와 결과 줄을 옮긴다. */
  checks?: (show: ShowAt) => ReactNode;
  /** 처음 열 때 강조할 결과 줄(주소의 line) */
  initialLine?: number;
};
export function ReviewDesk({ mode, onMode, canCompare, baseline, candidate, original, summary, sourcePane, sourceControl, pairControls, sourceStatus, pairStatus, sourceKey, onEvidenceSide, onLocation, heading, fill = false, checks, initialLine }: Props) {
  const [mobilePane, setMobilePane] = useState<'original' | 'output'>('output');
  const [page, setPage] = useState(0);
  const [highlight, setHighlight] = useState<{line: number; end?: number; text?: string}>();
  const [split, setSplit] = useState(readSplit);
  const pair = useRef<HTMLDivElement>(null);
  const appliedLine = useRef(false);
  const [openedRuns, setOpenedRuns] = useState(mode === 'runs');
  const [openedSummary, setOpenedSummary] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const source = useRef<HTMLDivElement>(null);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const view = canCompare ? mode : 'source';
  const output = useMemo(() => sourcePane?.text ? lines(sourcePane.text) : [], [sourcePane?.text]);
  const [textMode, setTextMode] = useResultMode();
  // 읽기 보기: 줄 번호와 원문 위치는 그대로 두고 표 줄은 칸으로, 제목 줄은 제목으로 그린다. 읽기 보기(상세)와 같은 블록 해석기를 쓴다
  // (한글 폭을 2칸으로 세어 같은 표는 같은 칸 너비. 코드 블록 안의 '# …'·'#LOT-7'은 제목이 아니다).
  const kinds = useMemo(() => textMode === 'read' && sourcePane?.text ? lineKinds(sourcePane.text) : new Map<number, LineKind>(), [sourcePane?.text, textMode]);
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
    if (view === 'source' && box && line) box.scrollTop += line.getBoundingClientRect().top - box.getBoundingClientRect().top - Math.min(64, box.clientHeight / 4);
  }, [highlight, view, sourcePane?.text, mobilePane]);
  const pageCount = Math.max(1, Math.ceil(output.length / 120));
  const show = useCallback<ShowAt>((location, line, lineEnd) => {
    if (location) onLocation(location);
    if (line) {
      setHighlight({ line, end: lineEnd && lineEnd >= line ? lineEnd : line, text: sourcePane?.text });
      setPage(Math.floor((line - 1) / 120));
      setMobilePane(location ? 'original' : 'output');
    } else if (location) setMobilePane('original');
    onMode('source');
  }, [onLocation, onMode, sourcePane?.text]);
  useEffect(() => {
    if (appliedLine.current || !initialLine || !sourcePane?.text) return;
    appliedLine.current = true;
    setHighlight({ line: initialLine, end: initialLine, text: sourcePane.text });
    setPage(Math.floor((initialLine - 1) / 120));
  }, [initialLine, sourcePane?.text]);
  const lit = (number: number) => !!highlight && highlight.text === sourcePane?.text && number >= highlight.line && number <= (highlight.end ?? highlight.line);
  function resize(clientX: number) {
    const box = pair.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    setSplit(Math.round(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, (clientX - box.left) * 100 / box.width))));
  }
  function startResize(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture?.(event.pointerId);
    const move = (next: globalThis.PointerEvent) => resize(next.clientX);
    const stop = () => {
      handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', stop); handle.removeEventListener('pointercancel', stop);
      setSplit(value => { saveSplit(value); return value; });
    };
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', stop); handle.addEventListener('pointercancel', stop);
  }
  function keyResize(event: KeyboardEvent<HTMLDivElement>) {
    const next = event.key === 'ArrowLeft' ? split - 2 : event.key === 'ArrowRight' ? split + 2 : event.key === 'Home' ? SPLIT_MIN
      : event.key === 'End' ? SPLIT_MAX : event.key === 'Enter' ? 50 : null;
    if (next === null) return;
    event.preventDefault();
    const value = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, next));
    setSplit(value); saveSplit(value);
  }
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
  return <div className={'review-desk' + (fill ? ' is-fill' : '')}>
    <div className="review-mode-bar">{heading}<div className="review-modes" role="group" aria-label="검수 방식">
      <button aria-pressed={view === 'source'} onClick={() => onMode('source')}><BookOpen size={17}/>원문 대조</button>
      <button aria-pressed={view === 'runs'} disabled={!canCompare} onClick={() => onMode('runs')}><GitCompareArrows size={17}/>실행 비교</button>
    </div>{!canCompare && <small>실행 비교는 성공한 결과 2개부터 가능합니다.</small>}</div>
    <div hidden={view !== 'source'} className="review-source-view">
      {checks?.(show)}
      <div className="review-mobile-switch" role="group" aria-label="대조 자료">
        <button aria-pressed={mobilePane === 'original'} onClick={() => setMobilePane('original')}>원문</button>
        <button aria-pressed={mobilePane === 'output'} onClick={() => setMobilePane('output')}>추출 결과</button>
      </div>
      <div className="source-pair" data-pane={mobilePane} ref={pair} style={fill ? { ['--split' as string]: `${split}%` } : undefined}>
        <div className="source-original" ref={source} tabIndex={-1}>{original}</div>
        {fill && <div className="source-split" role="separator" aria-orientation="vertical" aria-label="원본과 추출 결과 폭"
          aria-valuemin={SPLIT_MIN} aria-valuemax={SPLIT_MAX} aria-valuenow={split} aria-valuetext={`원본 ${split}%`} tabIndex={0}
          data-tip="끌거나 ←·→로 폭을 바꿉니다. Enter·두 번 누르면 반반" onPointerDown={startResize} onKeyDown={keyResize}
          onDoubleClick={() => { setSplit(50); saveSplit(50); }}><span aria-hidden="true" /></div>}
        <section className="source-output" aria-label="추출 결과"><header><h2>추출 결과</h2>{sourceControl}<ResultModeSwitch value={textMode} onChange={setTextMode} />{sourcePane?.meta}</header>
          <div className="source-lines" ref={viewport} tabIndex={0} aria-label="추출 본문">
          {sourceStatus}
          {!sourceStatus && !output.length && <p>표시할 추출 텍스트가 없습니다.</p>}
          {(() => { let previous = new Set<string>(); return output.slice(shownPage * 120, (shownPage + 1) * 120).map((value, i) => {
            const number = shownPage * 120 + i + 1;
            const locations = sourcePane?.locations?.filter(l => l.start_line <= number && l.end_line >= number) ?? [];
            const origins = new Map<string, ReviewLocation>();
            for (const l of locations) {
              if (l.page) origins.set(pageLabel(l.page, sourcePane?.pageUnit), {page:l.page, sheet:null});
              else if (l.sheet && l.column && l.row) {
                const cell = columnName(l.column) + l.row;
                origins.set(l.sheet + '!' + cell, {page:null, sheet:l.sheet, cell});
              }
            }
            // 같은 위치가 여러 줄에 걸치면(PPTX 슬라이드, PDF 쪽) 그 묶음의 첫 줄에만 근거 버튼을 단다.
            const labels = new Set(origins.keys());
            const shown = Array.from(origins).filter(([label]) => !previous.has(label));
            previous = labels;
            const kind = kinds.get(number);
            const table = kind && (kind.role === 'head' || kind.role === 'rule' || kind.role === 'row') ? kind : undefined;
            const heading = kind?.role === 'heading' ? kind : null;
            const body = table ? table.role === 'rule' ? <span className="source-cells-rule" aria-hidden="true" />
              : <span className="source-table-line"><span className={`source-cells${table.role === 'head' ? ' is-head' : ''}`} style={{ gridTemplateColumns: table.columns }}>{table.cells.map((cell, c) => <span key={c}>{cell}</span>)}</span>
                {/* 표 줄은 칸 정렬이 흐트러지지 않게 근거를 오른쪽 고정 칸에 아이콘으로 단다 */}
                <span className="source-evidence">{shown.map(([label, loc]) => <button className="evidence-link is-icon" key={label} aria-label={label} data-tip={label} onClick={() => reveal(loc, number)}><LocateFixed size={14}/></button>)}</span></span>
              : heading ? <span className={`source-heading is-h${heading.level}`}><span className="source-level" aria-label={`제목 ${heading.level}단계`}>H{heading.level}</span>{heading.text}</span>
              : textMode === 'read' && /^\s*<!--\s*image\s*-->\s*$/.test(value) ? <span className="source-figure">그림 자리 · 그림 안 글자 없음</span> : value || ' ';
            return <div className={'source-line' + (table ? table.role === 'rule' ? ' is-table is-rule' : ' is-table' : '') + (!value.trim() && !table ? ' is-blank' : '') + (lit(number) ? ' is-evidence' : '')} key={number}><small aria-hidden="true">{number}</small><div>{body}
              {!table && shown.map(([label, loc]) => <button className="evidence-link" key={label} onClick={() => reveal(loc, number)}><LocateFixed size={14}/>{label}</button>)}</div></div>;
          }); })()}</div>
          {!sourceStatus && !sourcePane?.locations?.length && <p className="reader-foot">원문 위치 미기록 · 원본에서 직접 확인하세요.</p>}
          {pageCount > 1 && <div className="compare-pages"><button disabled={!shownPage} onClick={() => setPage(shownPage - 1)}>이전</button><span>{shownPage+1} / {pageCount}</span><button disabled={shownPage >= pageCount-1} onClick={() => setPage(shownPage + 1)}>다음</button></div>}
        </section>
      </div>
    </div>
    {canCompare && (view === 'runs' || openedRuns) && <div hidden={view !== 'runs'} className="review-runs-view">
      {pairControls && <details className="review-options"><summary>비교할 실행 선택</summary>{pairControls}</details>}
      {pairStatus ?? <ResultReview baseline={baseline} candidate={candidate} onEvidence={({location, side, line}) => reveal(location, line, side)} />}
      <details className="review-options" onToggle={event => { if (event.currentTarget.open) setOpenedSummary(true); }}><summary>변화 지표와 정답 대조</summary>{openedSummary && !pairStatus && summary}</details>
    </div>}
  </div>;
}
