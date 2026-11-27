import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, ClipboardCheck, Clock3, LoaderCircle, MessageSquare, RefreshCw, X } from 'lucide-react';
import { getVerify, getVerifySpot } from '../api/live';
import type { LiveDoc, ParseRun, VerifyResult, VerifySpot } from '../api/live';
import { createReview, listReviews, reviewStatusLabels, reviewWhere, updateReview } from '../api/reviews';
import type { Review, ReviewStatus } from '../api/reviews';
import type { ReviewFocus } from '../navigation';
import type { ReviewLocation } from './ResultReview';
import { QcGateChip } from './QcGate';

/** 원문 대조에서 원본 칸을 그 위치로, 결과 칸을 그 줄로 옮긴다. */
export type ShowAt = (location: ReviewLocation | undefined, line?: number, lineEnd?: number) => void;
type Severity = 'high' | 'medium' | 'low';
type Item = {
  key: string; review?: Review; spot?: VerifySpot; severity: Severity | null; status: ReviewStatus | null;
  page: number | null; sheet: string | null; cell: string | null; line: number | null; lineEnd: number | null; ref: string | null;
  text: string; source: string; sourceHit: string; result: string; resultHit: string; before: boolean; runId: string | null;
};
type Filter = 'todo' | 'all';
type SeverityFilter = 'any' | Severity;
/** 한 번에 받는 자동 대조 상세 수(우선순위 순). 나머지는 '더 보기'로 이어 받는다. */
const PAGE = 400;

const severityLabels: Record<Severity, string> = { high: '높음', medium: '보통', low: '낮음' };
const statusOrder: Record<ReviewStatus, number> = { open: 0, unclear: 1, wrong: 2, correct: 3 };
const severityOrder: Record<Severity, number> = { high: 0, medium: 1, low: 2 };
const verdicts: { status: ReviewStatus; label: string; icon: typeof Check; tip: string }[] = [
  { status: 'correct', label: '맞음', icon: Check, tip: '원본과 결과가 같다(파싱 정상)' },
  { status: 'wrong', label: '틀림', icon: X, tip: '원본과 결과가 다르다(파싱 오류)' },
  { status: 'unclear', label: '보류', icon: CircleHelp, tip: '지금은 판단할 수 없다' },
];

function fromReview(review: Review): Item {
  return { key: `V${review.id}`, review, severity: review.severity, status: review.status, page: review.page, sheet: review.sheet, cell: review.cell,
    line: review.line, lineEnd: review.line_end, ref: review.ref, text: review.note, source: review.source_text ?? '', sourceHit: review.source_hit ?? '',
    result: review.result_text ?? '', resultHit: review.result_hit ?? '', before: !review.result_hit && review.kind === 'missing', runId: review.run_id };
}

function fromSpot(spot: VerifySpot, runId: string): Item {
  return { key: spot.key, spot, severity: spot.severity, status: null, page: spot.page, sheet: spot.sheet, cell: spot.cell, line: spot.line,
    lineEnd: spot.line_end, ref: spot.ref, text: spot.message, source: spot.source, sourceHit: spot.source_hit, result: spot.result,
    resultHit: spot.result_hit, before: spot.result_role === 'before', runId };
}

/** 우선순위(서버의 rank, 없으면 심각도 → S번호). */
const spotOrder = (a: VerifySpot, b: VerifySpot) => a.rank !== undefined && b.rank !== undefined ? a.rank - b.rank
  : severityOrder[a.severity] - severityOrder[b.severity] || Number(a.key.slice(1)) - Number(b.key.slice(1));

/** 문맥 글에서 다른 부분(hit)을 표시한다. 여러 조각('A … B')이면 첫 조각만. */
function Marked({ text, hit }: { text: string; hit: string }) {
  const first = hit.split(' … ')[0];
  if (first.trim() === text.trim()) return <>{text}</>; // 줄 전체가 빠진 경우: 문맥 전체를 칠하지 않는다
  const at = first ? text.indexOf(first) : -1;
  if (at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<mark>{first}</mark>{text.slice(at + first.length)}</>;
}

type VerifyState = { run: string; severity: SeverityFilter; data?: VerifyResult; error?: string; more: VerifySpot[]; loadingMore?: boolean };

export function ReviewChecks({ doc, runId, runs, onRun, focus, show, pageUnit }: {
  doc: LiveDoc; runId: string; runs: ParseRun[]; onRun: (runId: string) => void; focus?: ReviewFocus; show: ShowAt; pageUnit: 'page' | 'slide';
}) {
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [verify, setVerify] = useState<VerifyState>();
  const [reviewError, setReviewError] = useState('');
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState<Filter>('todo');
  const [severity, setSeverity] = useState<SeverityFilter>('any');
  const [selected, setSelected] = useState<string | undefined>(focus?.check);
  const [listOpen, setListOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState('');
  const [memo, setMemo] = useState<string | null>(null);
  const appliedFocus = useRef(false);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    listReviews({ doc: doc.id }, controller.signal).then(body => {
      if (!controller.signal.aborted) { setReviews(body.reviews); setReviewError(''); }
    }).catch(reason => { if (!controller.signal.aborted) { setReviews([]); setReviewError(reason instanceof Error ? reason.message : '검수 요청을 불러오지 못했습니다.'); } });
    return () => controller.abort();
  }, [doc.id, revision]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    setVerify({ run: runId, severity, more: [] });
    // 사람이 아직 판정하지 않은 의심점만(판정한 것은 검수 요청 V로 보인다), 우선순위 순으로 한 쪽.
    getVerify(doc.id, runId, controller.signal, { limit: PAGE, unreviewed: true, severity: severity === 'any' ? undefined : [severity] }).then(data => {
      if (!controller.signal.aborted) setVerify({ run: runId, severity, data, more: [] });
    }).catch(reason => { if (!controller.signal.aborted) setVerify({ run: runId, severity, more: [], error: reason instanceof Error ? reason.message : '자동 대조를 하지 못했습니다.' }); });
    return () => controller.abort();
  }, [doc.id, runId, revision, severity]);

  const verifyState = verify?.run !== runId ? undefined : verify;
  const loadedSpots = useMemo(() => {
    if (!verifyState?.data) return [] as VerifySpot[];
    const seen = new Set<string>();
    return [...verifyState.data.spots, ...verifyState.more].filter(spot => !seen.has(spot.key) && !!seen.add(spot.key));
  }, [verifyState]);
  const items = useMemo(() => {
    const fromReviews = [...(reviews ?? [])].sort((a, b) => statusOrder[a.status] - statusOrder[b.status] || b.id - a.id).map(fromReview);
    const reviewedRun = (reviews ?? []).filter(review => review.run_id === runId);
    const reviewedIds = new Set(reviewedRun.map(review => review.finding_id).filter(Boolean));
    const reviewedKeys = new Set(reviewedRun.filter(review => !review.finding_id).map(review => review.spot));
    const spots = [...loadedSpots]
      .filter(spot => !(spot.id ? reviewedIds.has(spot.id) : reviewedKeys.has(spot.key)))
      .sort(spotOrder)
      .map(spot => fromSpot(spot, runId));
    return [...fromReviews, ...spots];
  }, [reviews, loadedSpots, runId]);
  const todo = items.filter(item => !item.review || item.status === 'open');
  const shown = filter === 'todo' ? todo : items;
  const current = items.find(item => item.key === selected);
  const position = current ? shown.findIndex(item => item.key === current.key) : -1;
  const data = verifyState?.data;
  // 아직 받지 않은 자동 대조 지점(우선순위 다음 쪽). 판정한 것은 서버가 이미 뺐다.
  const remaining = data ? Math.max(0, (data.spots_matched ?? data.spots.length) - loadedSpots.length) : 0;

  const reveal = useCallback((item: Item) => {
    const location = item.page || item.sheet ? { page: item.page, sheet: item.sheet, cell: item.cell ?? undefined } : undefined;
    const sameRun = !item.runId || item.runId === runId;
    show(location, sameRun ? item.line ?? undefined : undefined, sameRun ? item.lineEnd ?? undefined : undefined);
  }, [runId, show]);
  const choose = useCallback((item: Item) => {
    setSelected(item.key); setActionError(''); setMemo(null);
    reveal(item);
  }, [reveal]);
  // 주소의 check=V12·S3(또는 finding ID)를 처음 한 번 보인다. 받은 쪽에 없는 S번호는 원장에서 하나만 받아 온다.
  useEffect(() => {
    if (appliedFocus.current || reviews === null) return;
    const check = focus?.check;
    if (check && /^[SF]/.test(check) && !verifyState?.data && !verifyState?.error) return;
    const target = check ? items.find(item => item.key === check || item.spot?.id === check) : undefined;
    appliedFocus.current = true;
    if (target) { choose(target); return; }
    if (check && /^(S\d+|F[0-9a-f]{12})$/.test(check) && verifyState?.data) {
      getVerifySpot(doc.id, check, runId).then(spot => {
        setVerify(previous => previous && previous.run === runId ? { ...previous, more: [...previous.more, spot] } : previous);
        setSelected(spot.key);
        reveal(fromSpot(spot, runId));
      }).catch(() => { /* 없는 지점: 목록에서 고르게 둔다 */ });
    }
  }, [focus, items, reviews, verifyState, runId, choose, reveal, doc.id]);

  async function loadMore() {
    if (!verifyState?.data || verifyState.loadingMore || !remaining) return;
    const base = verifyState;
    setVerify({ ...base, loadingMore: true });
    try {
      const next = await getVerify(doc.id, runId, undefined, { limit: PAGE, unreviewed: true, offset: loadedSpots.length,
        severity: base.severity === 'any' ? undefined : [base.severity] });
      setVerify(previous => previous && previous.run === base.run ? { ...previous, more: [...previous.more, ...next.spots], loadingMore: false } : previous);
    } catch (reason) {
      setVerify(previous => previous ? { ...previous, loadingMore: false } : previous);
      setActionError(reason instanceof Error ? reason.message : '다음 자동 대조 지점을 받지 못했습니다.');
    }
  }

  function step(delta: number) {
    if (!shown.length) return;
    const next = position < 0 ? (delta > 0 ? 0 : shown.length - 1) : (position + delta + shown.length) % shown.length;
    choose(shown[next]);
  }

  async function decide(status: ReviewStatus, comment?: string) {
    if (!current || saving) return;
    setSaving(true); setActionError('');
    try {
      let saved: Review;
      if (current.review) {
        saved = await updateReview(current.review.id, comment !== undefined ? { comment } : { status });
      } else if (current.spot) {
        // finding ID로 올린다: S번호는 규칙이 바뀌면 달라질 수 있다(예전 서버는 S번호).
        const ref = current.spot.id ? { finding_id: current.spot.id } : { spot: current.spot.key };
        saved = await createReview({ document_id: doc.id, run_id: current.runId, ...ref, status, ...(comment ? { comment } : {}) });
      } else return;
      setReviews(previous => [saved, ...(previous ?? []).filter(review => review.id !== saved.id)]);
      setSelected(`V${saved.id}`);
      setMemo(null);
      if (comment === undefined && filter === 'todo' && status !== 'open') {
        // 판정한 곳은 '할 일'에서 빠진다: 다음 할 일로 넘어간다.
        const rest = shown.filter(item => item.key !== current.key);
        const next = rest[Math.min(Math.max(position, 0), rest.length - 1)];
        if (next) choose(next);
      }
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '판정을 저장하지 못했습니다.');
    } finally {
      setSaving(false);
    }
  }

  const summary = data?.summary;
  const reviewCount = reviews?.length ?? 0;
  const spotCount = items.length - reviewCount + remaining;
  const otherRun = current?.runId && current.runId !== runId ? runs.find(run => run.run_id === current.runId) : undefined;
  const stale = !!data && (data.is_latest === false || (data.document_status !== undefined && data.document_status !== 'completed'));
  let status: ReactNode = null;
  if (!verifyState || (!verifyState.data && !verifyState.error)) status = <span className="rc-muted"><LoaderCircle size={14} className="rc-spin" aria-hidden="true" />자동 대조 중</span>;
  else if (verifyState.error) status = <span className="rc-muted" data-tip={verifyState.error}>자동 대조 없음</span>;
  else if (summary) status = <span className="rc-muted" data-tip={`${data!.method}${data!.notes.length ? ' · ' + data!.notes.join(' / ') : ''}`}>
    원본 글자 {summary.coverage === null ? '—' : `${Math.round(summary.coverage * 1000) / 10}%`} 일치</span>;

  return <section className="review-checks" aria-label="확인할 곳">
    <div className="rc-bar">
      <span className="rc-title"><ClipboardCheck size={16} aria-hidden="true" />확인할 곳 <b className="ui-num">{todo.length + remaining}</b></span>
      <span className="rc-muted">검수 요청 {reviewCount} · 자동 대조 {spotCount}</span>
      {data?.gate && <QcGateChip gate={data.gate} checks={data.checks} ruleVersion={data.rule_version} />}
      {stale && <span className="rc-state is-medium" data-tip="이 결과는 이전 성공본입니다. 그 뒤 처리가 실패했거나 다시 처리하는 중입니다."><Clock3 size={12} aria-hidden="true" /> 이전 성공본</span>}
      {status}
      <div className="rc-filter" role="group" aria-label="보일 곳">
        <button type="button" aria-pressed={filter === 'todo'} onClick={() => setFilter('todo')}>할 일 {todo.length + remaining}</button>
        <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>전체 {items.length + remaining}</button>
      </div>
      {!!data?.spots_total && <div className="rc-filter" role="group" aria-label="자동 대조 심각도">
        {(['any', 'high', 'medium', 'low'] as const).map(value => <button key={value} type="button" aria-pressed={severity === value}
          onClick={() => setSeverity(value)}>{value === 'any' ? '모든 심각도' : `${severityLabels[value]} ${data.summary[value]}`}</button>)}
      </div>}
      <div className="rc-nav">
        <button type="button" className="plain-icon" aria-label="이전 확인할 곳" data-tip="이전" onClick={() => step(-1)} disabled={!shown.length}><ChevronLeft size={16} aria-hidden="true" /></button>
        <span className="ui-num" aria-live="polite">{position >= 0 ? position + 1 : '–'} / {shown.length}{remaining ? '+' : ''}</span>
        <button type="button" className="plain-icon" aria-label="다음 확인할 곳" data-tip="다음" onClick={() => step(1)} disabled={!shown.length}><ChevronRight size={16} aria-hidden="true" /></button>
        <button type="button" className="rc-list-toggle" aria-expanded={listOpen} aria-controls="rc-list" onClick={() => setListOpen(!listOpen)}>목록<ChevronDown size={14} aria-hidden="true" /></button>
        <button type="button" className="plain-icon" aria-label="확인할 곳 새로고침" data-tip="새로고침" onClick={() => setRevision(n => n + 1)}><RefreshCw size={14} aria-hidden="true" /></button>
      </div>
    </div>
    {reviewError && <p className="rc-error" role="alert">{reviewError}</p>}
    {current ? <div className="rc-detail">
      <div className="rc-head">
        <span className={`rc-key is-${current.review ? current.status : current.severity}`}>{current.key}</span>
        {current.review ? <span className={`rc-state is-${current.status}`}>{reviewStatusLabels[current.status!]}</span>
          : <span className={`rc-state is-${current.severity}`}>자동 · {severityLabels[current.severity!]}</span>}
        <span className="rc-where">{reviewWhere({ ...current, line_end: current.lineEnd }, pageUnit) || '위치 미기록'}</span>
        {current.review?.origin === 'agent' && <span className="rc-muted">에이전트</span>}
        {current.spot?.source_layer === 'pdf_hidden_layer' && <span className="rc-state is-high" data-tip="그림 위의 보이지 않는 글자 층에서 읽은 값입니다. 화면에 보이는 값과 다를 수 있습니다.">숨은 글자 층</span>}
      </div>
      <p className="rc-text">{current.text}</p>
      {(current.source || current.result) && <dl className="rc-evidence">
        {current.source && <div><dt>원본</dt><dd><Marked text={current.source} hit={current.sourceHit} /></dd></div>}
        {(current.result || current.before) && <div><dt>{current.before ? '결과(있어야 할 자리 앞 줄)' : '결과'}</dt>
          <dd>{current.result ? <Marked text={current.result} hit={current.resultHit} /> : '없음'}</dd></div>}
      </dl>}
      {otherRun && <p className="rc-note">이 검수 요청은 다른 실행의 결과 줄을 가리킵니다. <button type="button" className="button-quiet" onClick={() => onRun(otherRun.run_id)}>그 실행으로 보기</button></p>}
      {current.review?.comment && memo === null && <p className="rc-comment"><MessageSquare size={13} aria-hidden="true" />{current.review.comment}</p>}
      <div className="rc-actions" role="group" aria-label={`${current.key} 판정`}>
        {verdicts.map(({ status, label, icon: Icon, tip }) =>
          <button key={status} type="button" className={`rc-verdict is-${status}`} aria-pressed={current.status === status} data-tip={tip}
            disabled={saving} onClick={() => void decide(status)}><Icon size={14} aria-hidden="true" />{label}</button>)}
        <button type="button" className="rc-verdict" aria-expanded={memo !== null} disabled={saving}
          onClick={() => setMemo(memo === null ? current.review?.comment ?? '' : null)}><MessageSquare size={14} aria-hidden="true" />메모</button>
        {saving && <LoaderCircle size={14} className="rc-spin" aria-label="저장 중" />}
      </div>
      {memo !== null && <form className="rc-memo" onSubmit={event => { event.preventDefault(); void decide(current.status ?? 'open', memo.trim()); }}>
        <label className="compare-sr" htmlFor="rc-memo-input">메모</label>
        <input id="rc-memo-input" value={memo} maxLength={2000} placeholder="무엇이 다른지, 왜 그렇게 판정했는지" onChange={event => setMemo(event.target.value)} autoFocus />
        <button type="submit" className="button-secondary" disabled={saving}>메모 저장</button>
      </form>}
      {actionError && <p className="rc-error" role="alert">{actionError}</p>}
    </div> : <p className="rc-empty">{!items.length && !remaining && reviews !== null && verifyState && (verifyState.data || verifyState.error)
      ? '확인할 곳이 없습니다. 자동 대조가 같다고 해도 표 구조·읽는 순서·그림 속 글자는 원본과 직접 비교하세요.'
      : '이전·다음 단추나 목록으로 확인할 곳을 고르면 원본과 결과가 그 자리로 옮겨 갑니다. 자동 대조 지점은 심각도가 높은 것부터 놓입니다.'}</p>}
    {listOpen && <ul id="rc-list" ref={listRef} className="rc-list" aria-label="확인할 곳 목록">
      {shown.map(item => <li key={item.key}><button type="button" aria-current={item.key === current?.key || undefined} onClick={() => { choose(item); setListOpen(false); }}>
        <span className={`rc-key is-${item.review ? item.status : item.severity}`}>{item.key}</span>
        <span className="rc-where">{reviewWhere({ ...item, line_end: item.lineEnd }, pageUnit) || '위치 미기록'}</span>
        <span className="rc-line-text">{item.text}</span>
        {item.review && <span className={`rc-state is-${item.status}`}>{reviewStatusLabels[item.status!]}</span>}
      </button></li>)}
      {!shown.length && !remaining && <li className="rc-empty">{filter === 'todo' ? '남은 할 일이 없습니다.' : '확인할 곳이 없습니다.'}</li>}
      {remaining > 0 && <li className="rc-more"><button type="button" onClick={() => void loadMore()} disabled={verifyState?.loadingMore}>
        {verifyState?.loadingMore ? <LoaderCircle size={14} className="rc-spin" aria-hidden="true" /> : null}
        <span>자동 대조 다음 {Math.min(PAGE, remaining).toLocaleString('ko-KR')}곳 더 보기</span><small>남은 {remaining.toLocaleString('ko-KR')}곳 · 우선순위 순</small></button></li>}
    </ul>}
  </section>;
}
