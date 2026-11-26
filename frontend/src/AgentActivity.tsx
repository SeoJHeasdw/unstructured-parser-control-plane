import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, BookOpen, Check, ChevronDown, ChevronRight, CircleAlert, CircleHelp, ClipboardCheck, Copy, LoaderCircle, RefreshCw, TriangleAlert, X } from 'lucide-react';
import { getAgentActivity } from './api/agent';
import type { AgentActivity as Activity, AgentBatch, AgentCall, AgentDocument } from './api/agent';
import { listLiveDocuments } from './api/live';
import type { LiveDoc } from './api/live';
import { listReviews, reviewStatusLabels, reviewWhere, updateReview } from './api/reviews';
import type { Review, ReviewStatus } from './api/reviews';
import { displayStatus, statusLabels, StatusBadge } from './LiveDocumentView';
import { WorkspaceLink } from './WorkspaceLink';
import type { ReviewFocus, WorkspaceRoute } from './navigation';
import { Tabs, modKey } from './ui';
import './agent.css';

type Tab = 'reviews' | 'docs' | 'batches' | 'calls';
type Navigate = (route: WorkspaceRoute) => void;
type DocIndex = { bySeq: Map<number, LiveDoc>; byId: Map<string, LiveDoc>; loaded: boolean };
type ReviewFilter = ReviewStatus | 'all';

const REFRESH_MS = 10_000;
const CHIP_LIMIT = 40;
/** 표는 docs/AGENT_TOOLS.md·backend/app/agent/codes.py와 같은 뜻이다. */
const SKIP_MEANINGS: Record<string, string> = { lock: 'Office 임시 잠금 파일(~$)', hidden: '숨김·시스템 파일', empty: '0바이트 파일', 'too-big': '업로드 한도 초과' };
const ITEM_ERRORS: Record<string, string> = { missing: '서버에서 문서를 찾을 수 없음', 'missing-file': '원본 파일이 없어짐', 'read-fail': '원본 파일을 읽지 못함', 'too-big': '업로드 한도 초과' };
const CALL_ERRORS: Record<string, string> = {
  'bad-arg': '잘못된 인자', 'not-found': '대상 없음', outside: '허용 폴더 밖', 'server-down': '콘솔 서버 꺼짐',
  busy: '서버가 바쁨(409·503)', api: '그 밖의 API 오류', internal: '작업 도구 내부 오류', 'no-source': '원본 글자를 읽을 수 없음(이미지·스캔·형식)',
};
/** 도구 이름 → 하는 일(backend/app/agent/mcp.py의 title) */
const TOOL_TITLES: Record<string, string> = {
  status: '준비 상태', files: '원본 파일 찾기', parse: '등록·파싱', wait: '기다리기', docs: '문서 목록', doc: '문서 상세',
  verify: '원본과 자동 대조', source: '원본 읽기', read: '결과 읽기', flag: '검수 요청 올리기', verdicts: '사람 검수 결과',
  compare: '이전 실행과 비교', chunk: '청킹 비교', report: '보고서(이전 도구)',
};
const REVIEW_FILTERS: ReviewFilter[] = ['open', 'wrong', 'unclear', 'correct', 'all'];
const skipMeaning = (code: string) => SKIP_MEANINGS[code]
  ?? (code.startsWith('ext-') ? `처리 경로가 없는 확장자(${code === 'ext-none' ? '확장자 없음' : code.slice(4).toUpperCase()})` : '');
const itemErrorMeaning = (note: string) => ITEM_ERRORS[note]
  ?? (/^upload-\d+$/.test(note) ? `업로드 실패(HTTP ${note.slice(7)})` : /^process-\d+$/.test(note) ? `파싱 접수 실패(HTTP ${note.slice(8)})` : '');

const clock = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const dayClock = new Intl.DateTimeFormat('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const fullClock = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const parse = (iso: string | null) => { const date = iso ? new Date(iso) : null; return date && Number.isFinite(+date) ? date : null; };
/** 오늘이면 시:분:초, 아니면 월.일 시:분 */
function shortTime(iso: string | null) {
  const date = parse(iso);
  if (!date) return '—';
  return date.toDateString() === new Date().toDateString() ? clock.format(date) : dayClock.format(date);
}
const fullTime = (iso: string | null) => { const date = parse(iso); return date ? fullClock.format(date) : ''; };
function elapsed(from: string | null, to: string | null) {
  const start = parse(from), end = parse(to);
  if (!start || !end || end < start) return '';
  const seconds = Math.round((+end - +start) / 1000);
  if (seconds < 60) return `${seconds}초`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
  return `${Math.floor(seconds / 3600)}시간 ${Math.floor(seconds % 3600 / 60)}분`;
}
const tally = (values: string[]) => [...values.reduce((map, value) => map.set(value, (map.get(value) ?? 0) + 1), new Map<string, number>())];
/** 인자를 'target=D12 reparse=true'처럼 한 줄로. */
const compactArgs = (args: Record<string, unknown>) => Object.entries(args)
  .map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`).join(' ');
const numberArg = (value: unknown) => {
  const number = typeof value === 'number' ? value : typeof value === 'string' && /^\d{1,6}$/.test(value) ? Number(value) : NaN;
  return number > 0 ? number : undefined;
};
/** 원문 대조 주소(위치·검수 요청을 짚어 연다) */
const reviewRoute = (id: string, focus?: ReviewFocus): WorkspaceRoute => ({ page: 'live', doc: id, review: 'source', focus });
/** 원문 대조는 성공한 파싱 결과가 있어야 연다(목록에서는 완료 상태로 가늠한다). */
const canReview = (doc: { status: string } | undefined) => doc?.status === 'completed';

function DocChip({ seq, docs, onNavigate, focus }: { seq: number; docs: DocIndex; onNavigate: Navigate; focus?: ReviewFocus }) {
  const label = `D${seq}`;
  const doc = docs.bySeq.get(seq);
  if (!doc) return <span className="ag-chip is-missing" data-tip={docs.loaded ? '문서함에서 찾을 수 없습니다.' : '문서 목록을 불러오지 못했습니다.'}>{label}</span>;
  const status = displayStatus(doc);
  const review = focus && doc.status === 'completed';
  return <WorkspaceLink className={`ag-chip is-${status}`} to={review ? reviewRoute(doc.id, focus) : { page: 'live', doc: doc.id }} onNavigate={onNavigate}
    aria-label={`${label} ${doc.name}`} data-tip={`${doc.name} · ${statusLabels[status]}${review ? ' · 원문 대조로 열기' : ''}`}>{label}</WorkspaceLink>;
}

function DocChips({ seqs, docs, onNavigate, label }: { seqs: number[]; docs: DocIndex; onNavigate: Navigate; label: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? seqs : seqs.slice(0, CHIP_LIMIT);
  return <div className="ag-chips" role="group" aria-label={label}>
    {shown.map(seq => <DocChip key={seq} seq={seq} docs={docs} onNavigate={onNavigate} />)}
    {seqs.length > CHIP_LIMIT && <button type="button" className="ag-more" aria-expanded={all} onClick={() => setAll(!all)}>
      {all ? '접기' : `+${seqs.length - CHIP_LIMIT}개 더 보기`}</button>}
  </div>;
}

async function copyText(text: string, target: HTMLElement | null): Promise<'copied' | 'selected'> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return 'copied'; }
  } catch { /* 보안 연결이 아니거나 권한이 없으면 아래 방식으로 */ }
  if (target) {
    const range = document.createRange();
    range.selectNodeContents(target);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    try { if (typeof document.execCommand === 'function' && document.execCommand('copy')) return 'copied'; } catch { /* 선택만 남긴다 */ }
  }
  return 'selected';
}

// ---------------------------------------------------------------- 검수 요청
function wrongSummary(reviews: Review[]) {
  const wrong = reviews.filter(review => review.status === 'wrong');
  const lines = [`파싱 오류(사람이 원문 대조로 확인) ${wrong.length}건 — ${fullClock.format(new Date())}`];
  wrong.forEach((review, index) => {
    const where = reviewWhere(review, review.document_format === 'PPTX' ? 'slide' : 'page');
    const pair = review.source_hit || review.result_hit ? ` · 원본 '${review.source_hit ?? ''}' → 결과 ${review.result_hit ? `'${review.result_hit}'` : '없음'}` : '';
    lines.push(`${index + 1}. V${review.id} D${review.document_seq ?? '?'} ${review.document_format}${where ? ` · ${where}` : ''} · ${review.kind}${pair}`);
    lines.push(`   ${review.note.replace(/\s+/g, ' ')}${review.comment ? ` / 메모: ${review.comment.replace(/\s+/g, ' ')}` : ''}`);
  });
  return lines.join('\n');
}

function ReviewRow({ review, onNavigate, onDecide, busy }: { review: Review; onNavigate: Navigate; onDecide: (review: Review, status: ReviewStatus) => void; busy: boolean }) {
  const unit = review.document_format === 'PPTX' ? 'slide' : 'page';
  const where = reviewWhere(review, unit);
  const focus: ReviewFocus = { page: review.page ?? undefined, sheet: review.sheet ?? undefined, cell: review.cell ?? undefined,
    line: review.line ?? undefined, check: `V${review.id}`, run: review.run_id ?? undefined };
  return <li className={`ag-review is-${review.status}`} aria-label={`검수 요청 V${review.id}`}>
    <div className="ag-review-head">
      <b className={`ag-vkey is-${review.status}`}>V{review.id}</b>
      <span className={`ag-vstate is-${review.status}`}>{reviewStatusLabels[review.status]}</span>
      <WorkspaceLink className="ag-review-doc" to={{ page: 'live', doc: review.document_id }} onNavigate={onNavigate} data-tip={`${review.document_name} 상세`}>
        {review.document_seq ? <span className="lw-seq">D{review.document_seq}</span> : null} {review.document_name}</WorkspaceLink>
      {where && <span className="ag-review-where">{where}</span>}
      <span className="ag-review-meta">{review.origin === 'agent' ? '에이전트' : '화면'} · <time dateTime={review.created_at} data-tip={fullTime(review.created_at) || undefined}>{shortTime(review.created_at)}</time>
        {review.is_latest_run === false && <span className="ag-review-stale" data-tip="이 검수 요청을 만든 뒤 문서를 다시 파싱했습니다. 원문 대조는 그때의 실행으로 엽니다.">다시 파싱됨</span>}</span>
    </div>
    <p className="ag-review-note">{review.note}</p>
    {(review.source_hit || review.result_hit) && <p className="ag-review-pair"><span>원본</span><mark>{review.source_hit || '—'}</mark><ChevronRight size={13} aria-hidden="true" />
      <span>결과</span>{review.result_hit ? <mark className="is-result">{review.result_hit}</mark> : <em>없음</em>}</p>}
    {review.comment && <p className="ag-review-comment">메모: {review.comment}</p>}
    <div className="ag-review-actions">
      {canReview({ status: review.document_status }) ? <WorkspaceLink className="button-secondary ag-review-open" to={reviewRoute(review.document_id, focus)} onNavigate={onNavigate}>
        <BookOpen size={15} aria-hidden="true" />원문 대조에서 보기</WorkspaceLink> : <span className="ag-review-meta">원문 대조할 결과 없음</span>}
      <span className="ag-review-quick" role="group" aria-label={`V${review.id} 판정`}>
        {([['correct', Check], ['wrong', X], ['unclear', CircleHelp]] as const).map(([status, Icon]) =>
          <button key={status} type="button" className={`ag-quick is-${status}`} aria-pressed={review.status === status} disabled={busy}
            onClick={() => onDecide(review, review.status === status ? 'open' : status)}
            data-tip={review.status === status ? '확인 전으로 되돌리기' : `${reviewStatusLabels[status]}으로 판정`}><Icon size={13} aria-hidden="true" />{reviewStatusLabels[status]}</button>)}
      </span>
    </div>
  </li>;
}

function Reviews({ reviews, counts, error, onNavigate, onChanged }: {
  reviews: Review[]; counts: Partial<Record<ReviewStatus, number>>; error: string; onNavigate: Navigate; onChanged: (review: Review) => void;
}) {
  const [filter, setFilter] = useState<ReviewFilter>(counts.open ? 'open' : 'all');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [copied, setCopied] = useState<'' | 'copied' | 'selected'>('');
  const holder = useRef<HTMLPreElement>(null);
  const shown = filter === 'all' ? reviews : reviews.filter(review => review.status === filter);
  const total = Object.values(counts).reduce((sum, value) => sum + (value ?? 0), 0);
  const summary = useMemo(() => wrongSummary(reviews), [reviews]);
  useEffect(() => { if (copied !== 'copied') return; const timer = window.setTimeout(() => setCopied(''), 4000); return () => window.clearTimeout(timer); }, [copied]);
  async function decide(review: Review, status: ReviewStatus) {
    setBusy(true); setActionError('');
    try { onChanged(await updateReview(review.id, { status })); }
    catch (reason) { setActionError(reason instanceof Error ? reason.message : '판정을 저장하지 못했습니다.'); }
    finally { setBusy(false); }
  }
  if (!total && !error) return <p className="ag-empty-tab">검수 요청이 없습니다. 에이전트가 원본과 대조해 <code>docops_flag</code>로 올리거나, 원문 대조의 <b>확인할 곳</b>에서 자동 대조 지점을 판정하면 생깁니다.</p>;
  return <div className="ag-reviews">
    <div className="ag-calls-tools">
      <div className="ag-segment" role="group" aria-label="검수 요청 상태">
        {REVIEW_FILTERS.map(id => <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>
          {id === 'all' ? '전체' : reviewStatusLabels[id]}<span className="ui-num">{id === 'all' ? total : counts[id] ?? 0}</span></button>)}
      </div>
      <span className="ag-calls-sum">사람이 원문 대조로 보고 <b>맞음·틀림·보류</b>를 누릅니다. 틀림은 파싱 오류로 확인된 곳입니다.</span>
      <button type="button" className="button-secondary ag-copy" disabled={!counts.wrong} onClick={async () => setCopied(await copyText(summary, holder.current))}
        data-tip="틀림으로 판정한 곳의 위치·원본/결과 글자·메모를 글로 복사합니다(문서 글이 들어 있으니 전달 범위를 확인하세요).">
        {copied === 'copied' ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}틀림 정리 복사</button>
    </div>
    {copied && <p className="ag-copy-note" role="status">{copied === 'copied' ? '틀림으로 판정한 곳을 복사했습니다.' : `자동 복사를 쓸 수 없어 정리 글을 선택해 두었습니다. ${modKey('C')}로 복사하세요.`}</p>}
    <pre ref={holder} className="ag-hidden-copy" aria-hidden="true">{summary}</pre>
    {(error || actionError) && <p className="ag-note is-bad" role="alert"><TriangleAlert size={14} aria-hidden="true" />{error || actionError}</p>}
    {shown.length ? <ol className="ag-review-list">{shown.map(review => <ReviewRow key={review.id} review={review} onNavigate={onNavigate} onDecide={(item, status) => void decide(item, status)} busy={busy} />)}</ol>
      : <p className="ag-empty-tab">{filter === 'open' ? '확인 전인 검수 요청이 없습니다.' : '이 상태의 검수 요청이 없습니다.'}</p>}
  </div>;
}

// ---------------------------------------------------------------- 문서
function HandledDocs({ documents, docs, onNavigate }: { documents: AgentDocument[]; docs: DocIndex; onNavigate: Navigate }) {
  if (!documents.length) return <p className="ag-empty-tab">에이전트가 다룬 문서가 없습니다. 에이전트가 파싱하거나 원본을 읽고 대조한 문서가 여기에 모입니다.</p>;
  return <div className="ag-table-wrap" role="region" aria-label="에이전트가 다룬 문서" tabIndex={0}><table className="ag-table ag-docs">
    <thead><tr><th scope="col">문서</th><th scope="col">상태</th><th scope="col">검수 요청</th><th scope="col">묶음</th><th scope="col">마지막 에이전트 작업</th><th scope="col"><span className="compare-sr">열기</span></th></tr></thead>
    <tbody>{documents.map(item => {
      const doc = docs.byId.get(item.id);
      const live = doc ?? { id: item.id, name: item.name, format: item.format, status: item.status, error_code: item.error_code } as LiveDoc;
      const open = item.reviews.open, wrong = item.reviews.wrong;
      return <tr key={item.id}>
        <td><WorkspaceLink className="ag-doc-name" to={{ page: 'live', doc: item.id }} onNavigate={onNavigate} data-tip={item.name} data-tip-overflow>
          {item.seq ? <span className="lw-seq">D{item.seq}</span> : null} {item.name}</WorkspaceLink><small>{item.format || '확장자 없음'}</small></td>
        <td><StatusBadge status={displayStatus(live)} /></td>
        <td>{open || wrong || item.reviews.correct || item.reviews.unclear ? <span className="ag-review-counts">
          {open > 0 && <span className="ag-vstate is-open">확인 전 {open}</span>}{wrong > 0 && <span className="ag-vstate is-wrong">틀림 {wrong}</span>}
          {item.reviews.correct > 0 && <span className="ag-vstate is-correct">맞음 {item.reviews.correct}</span>}{item.reviews.unclear > 0 && <span className="ag-vstate is-unclear">보류 {item.reviews.unclear}</span>}
        </span> : <span className="ag-muted">—</span>}</td>
        <td>{item.batches.length ? item.batches.slice(0, 4).map(n => <code key={n} className="ag-bkey">B{n}</code>) : <span className="ag-muted">—</span>}</td>
        <td><time dateTime={item.last_agent_at ?? undefined} data-tip={fullTime(item.last_agent_at) || undefined}>{shortTime(item.last_agent_at)}</time>
          {item.calls > 0 && <small>도구 호출 {item.calls}회</small>}</td>
        <td className="ag-doc-actions">{canReview(live) ? <WorkspaceLink className="button-secondary" to={reviewRoute(item.id)} onNavigate={onNavigate}
          aria-label={`D${item.seq ?? ''} ${item.name} 원문 대조`}><BookOpen size={15} aria-hidden="true" />원문 대조</WorkspaceLink> : null}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

// ---------------------------------------------------------------- 묶음
function batchState(batch: AgentBatch, failed: number) {
  if (batch.error) return { tone: 'bad', label: '중단' };
  if (!batch.finished) return { tone: 'accent', label: '진행 중' };
  return failed ? { tone: 'warn', label: '끝남 · 오류 있음' } : { tone: 'ok', label: '끝남' };
}

function BatchRow({ batch, docs, onNavigate }: { batch: AgentBatch; docs: DocIndex; onNavigate: Navigate }) {
  const code = `B${batch.n}`;
  const count = (state: string) => batch.counts[state] ?? 0;
  const done = count('done'), failed = count('error');
  const state = batchState(batch, failed);
  const waiting: [string, number][] = [['처리 중·대기', count('queued')], ['접수 전', count('pending')], ['등록 전', count('file')]];
  const skips = Object.entries(batch.skips).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const took = elapsed(batch.started, batch.finished);
  return <li className="ag-batch" aria-label={`묶음 ${code}`}>
    <div className="ag-batch-head">
      <b className="ag-code">{code}</b>
      <span className="ag-target" data-tip={batch.target} data-tip-overflow>{batch.target || '대상 미기록'}</span>
      {batch.reparse && <span className="ui-pill">다시 파싱</span>}
      <span className={`ui-pill is-${state.tone}`}>{state.label}</span>
    </div>
    <div className="ag-facts">
      <span className="ag-progress"><progress value={done} max={Math.max(batch.total, 1)} aria-label={`${code} 처리 끝난 항목`} />
        <b className="ui-num">{done}/{batch.total}</b> 처리 끝남</span>
      {failed > 0 && <span className="is-bad">오류 <b className="ui-num">{failed}</b></span>}
      {waiting.filter(([, n]) => n > 0).map(([label, n]) => <span key={label}>{label} <b className="ui-num">{n}</b></span>)}
      <span>시작 <time dateTime={batch.started ?? undefined} data-tip={fullTime(batch.started) || undefined}>{shortTime(batch.started)}</time></span>
      {batch.finished && <span>끝 <time dateTime={batch.finished} data-tip={fullTime(batch.finished) || undefined}>{shortTime(batch.finished)}</time>{took && ` · ${took}`}</span>}
    </div>
    {batch.error && <p className="ag-note is-bad"><TriangleAlert size={14} aria-hidden="true" />{batch.error}</p>}
    {batch.errors.length > 0 && <p className="ag-note is-bad"><span>항목 오류</span>{tally(batch.errors).map(([note, n]) =>
      <code key={note} data-tip={itemErrorMeaning(note) || undefined}>{note || '사유 미기록'}{n > 1 && ` ×${n}`}</code>)}</p>}
    {skips.length > 0 && <p className="ag-note"><span>건너뜀</span>{skips.map(([skip, n]) =>
      <code key={skip} data-tip={skipMeaning(skip) || undefined}>{skip} {n}</code>)}</p>}
    {batch.docs.length > 0 && <DocChips seqs={batch.docs} docs={docs} onNavigate={onNavigate} label={`${code} 문서`} />}
  </li>;
}

// ---------------------------------------------------------------- 호출 기록
type CallGroup = { key: string; session: string | null; calls: AgentCall[] };
/** 연결(MCP 프로세스·CLI 실행)마다, 표식이 없는 예전 기록은 10분 넘게 쉬면 나눈다. 목록은 최신이 먼저다. */
function groupCalls(calls: AgentCall[]): CallGroup[] {
  const groups: CallGroup[] = [];
  let last: AgentCall | null = null;
  for (const call of calls) {
    const current = groups[groups.length - 1];
    const gap = last && Math.abs((parse(last.ts)?.getTime() ?? 0) - (parse(call.ts)?.getTime() ?? 0)) > 10 * 60_000;
    if (!current || (call.session ?? null) !== current.session || (!call.session && gap)) {
      groups.push({ key: `${call.session ?? 'old'}-${call.ts}-${groups.length}`, session: call.session ?? null, calls: [call] });
    } else current.calls.push(call);
    last = call;
  }
  return groups;
}

function CallRow({ call, docs, onNavigate }: { call: AgentCall; docs: DocIndex; onNavigate: Navigate }) {
  const [open, setOpen] = useState(false);
  const args = compactArgs(call.args);
  const focus: ReviewFocus = { page: numberArg(call.args.page), sheet: typeof call.args.sheet === 'string' ? call.args.sheet : undefined,
    line: numberArg(call.args.line), check: typeof call.args.spot === 'string' && /^s\d+$/i.test(call.args.spot) ? call.args.spot.toUpperCase() : undefined };
  return <>
    <tr className={(call.kind ? 'is-error' : '') + (open ? ' is-open' : '')}>
      <td><time dateTime={call.ts} data-tip={fullTime(call.ts) || undefined}>{shortTime(call.ts)}</time></td>
      <td><code>{call.tool || '—'}</code>{TOOL_TITLES[call.tool] && <small className="ag-tool-title">{TOOL_TITLES[call.tool]}</small>}</td>
      <td><span className="ag-clip ag-args" data-tip={args || undefined} data-tip-overflow>{args || '—'}</span></td>
      <td><span className="ag-clip" data-tip={call.result || undefined} data-tip-overflow>{call.result || '—'}</span></td>
      <td>{call.docs.length ? <span className="ag-chips">{call.docs.slice(0, 6).map(seq => <DocChip key={seq} seq={seq} docs={docs} onNavigate={onNavigate}
        focus={['verify', 'source', 'read', 'flag'].includes(call.tool) ? focus : undefined} />)}{call.docs.length > 6 && <span className="ag-muted">+{call.docs.length - 6}</span>}</span> : <span className="ag-muted">—</span>}</td>
      <td><span className="ag-badges">{call.kind && <span className="ag-kind" data-tip={CALL_ERRORS[call.kind] ?? '오류'}>{call.kind}</span>}
        {call.repeat && <span className="ag-repeat" data-tip="2분 안에 같은 도구·같은 인자로 다시 불렀습니다(막지 않고 기록만 함).">반복</span>}</span></td>
      <td className="is-num ui-num">{call.ms === null ? '—' : call.ms.toLocaleString('ko-KR')}</td>
      <td className="ag-expand">{call.text ? <button type="button" className="plain-icon" aria-expanded={open} aria-label={open ? '결과 접기' : '에이전트가 받은 결과 전체 보기'}
        data-tip={open ? '접기' : '에이전트가 받은 결과 전체'} onClick={() => setOpen(!open)}><ChevronDown size={15} aria-hidden="true" /></button> : null}</td>
    </tr>
    {open && <tr className="ag-call-text"><td colSpan={8}><pre className="ag-pre" tabIndex={0} aria-label={`${call.tool} 결과 전체`}>{call.text}</pre></td></tr>}
  </>;
}

function Calls({ calls, docs, onNavigate }: { calls: AgentCall[]; docs: DocIndex; onNavigate: Navigate }) {
  const [errorsOnly, setErrorsOnly] = useState(false);
  const errors = calls.filter(call => call.kind).length;
  const repeats = calls.filter(call => call.repeat).length;
  const rows = errorsOnly ? calls.filter(call => call.kind) : calls;
  const groups = useMemo(() => groupCalls(rows), [rows]);
  return <div className="ag-calls">
    <div className="ag-calls-tools">
      <button type="button" className="ag-toggle" aria-pressed={errorsOnly} onClick={() => setErrorsOnly(!errorsOnly)}>
        <CircleAlert size={14} aria-hidden="true" />오류만<span className="ui-num">{errors}</span></button>
      <span className="ag-calls-sum">호출 <b className="ui-num">{calls.length}</b> · 오류 <b className="ui-num">{errors}</b> · 반복 <b className="ui-num">{repeats}</b> · 줄 끝 단추로 에이전트가 받은 결과 전체를 봅니다</span>
    </div>
    {rows.length ? <div className="ag-table-wrap" role="region" aria-label="도구 호출 기록 표" tabIndex={0}><table className="ag-table">
      <thead><tr><th scope="col">시각</th><th scope="col">도구</th><th scope="col">인자</th><th scope="col">결과 첫 줄</th><th scope="col">문서</th><th scope="col">표시</th><th scope="col" className="is-num">ms</th><th scope="col"><span className="compare-sr">펼치기</span></th></tr></thead>
      {groups.map(group => {
        const first = group.calls[group.calls.length - 1], last = group.calls[0];
        const failed = group.calls.filter(call => call.kind).length;
        return <tbody key={group.key}>
          {group.calls.length > 1 && <tr className="ag-group"><th scope="rowgroup" colSpan={8}>
            <span>{group.session ? <>연결 <code>{group.session}</code></> : '이전 기록'}</span>
            <span><time dateTime={first.ts}>{shortTime(first.ts)}</time>{first !== last && <> ~ <time dateTime={last.ts}>{shortTime(last.ts)}</time></>}</span>
            <span>호출 {group.calls.length}{failed ? ` · 오류 ${failed}` : ''}</span>
          </th></tr>}
          {group.calls.map((call, i) => <CallRow key={`${call.ts}-${i}`} call={call} docs={docs} onNavigate={onNavigate} />)}
        </tbody>;
      })}
    </table></div> : <p className="ag-empty-tab">{errorsOnly ? '오류가 기록된 호출이 없습니다.' : '기록된 도구 호출이 없습니다.'}</p>}
    {(errors > 0 || repeats > 0) && <details className="ag-legend"><summary>표시 설명</summary><dl>
      {Object.entries(CALL_ERRORS).map(([kind, meaning]) => <div key={kind}><dt><code>{kind}</code></dt><dd>{meaning}</dd></div>)}
      <div><dt>반복</dt><dd>2분 안에 같은 도구·같은 인자로 다시 부름(막지 않음)</dd></div>
    </dl></details>}
  </div>;
}

/** 작업 에이전트가 올린 검수 요청과 다룬 문서·묶음·호출 기록. 화면이 보일 때만 10초마다 다시 읽는다. 판정은 원문 대조나 검수 요청 목록에서 사람이 남긴다. */
export default function AgentActivity({ active = true, onNavigate }: { active?: boolean; onNavigate: Navigate }) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [docs, setDocs] = useState<LiveDoc[] | null>(null);
  const [reviews, setReviews] = useState<{ reviews: Review[]; counts: Partial<Record<ReviewStatus, number>>; error: string }>({ reviews: [], counts: {}, error: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      // 문서 목록은 D번호를 문서로 잇는 데만 쓴다. 검수 요청을 못 읽어도 활동은 보여 준다.
      const [next, documents, listed] = await Promise.all([getAgentActivity(controller.signal), listLiveDocuments(controller.signal).catch(() => null),
        listReviews({}, controller.signal).then(body => ({ ...body, error: '' })).catch((reason: unknown) => ({ reviews: [] as Review[], counts: {}, error: reason instanceof Error ? reason.message : '검수 요청을 불러오지 못했습니다.' }))]);
      if (controller.signal.aborted) return;
      setActivity(next);
      if (documents) setDocs(documents);
      setReviews(listed);
      setTab(current => current ?? (listed.reviews.length ? 'reviews' : next.documents.length ? 'docs' : 'batches'));
      setError('');
      setCheckedAt(new Date());
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '에이전트 활동을 불러오지 못했습니다.');
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  useEffect(() => {
    if (!active) return;
    if (document.visibilityState !== 'hidden') void load();
    const tick = () => { if (document.visibilityState === 'visible') void load(); };
    const timer = window.setInterval(tick, REFRESH_MS);
    document.addEventListener('visibilitychange', tick);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
  }, [active, load]);

  const index = useMemo<DocIndex>(() => ({
    bySeq: new Map((docs ?? []).filter(doc => typeof doc.seq === 'number').map(doc => [doc.seq as number, doc])),
    byId: new Map((docs ?? []).map(doc => [doc.id, doc])), loaded: docs !== null,
  }), [docs]);
  const changed = (review: Review) => setReviews(previous => {
    const next = previous.reviews.map(item => item.id === review.id ? review : item);
    const counts: Partial<Record<ReviewStatus, number>> = {};
    for (const item of next) counts[item.status] = (counts[item.status] ?? 0) + 1;
    return { ...previous, reviews: next, counts };
  });
  const open = reviews.counts.open ?? 0;
  const anything = !!activity && (activity.available || reviews.reviews.length > 0);

  return <div className="ag-workspace">
    <div className="ag-toolbar">
      <span className="ag-source"><Bot size={16} aria-hidden="true" />서버의 <code>runtime/agent</code> 기록과 검수 요청</span>
      {checkedAt && <span className="ag-checked">마지막 확인 <time dateTime={checkedAt.toISOString()}>{clock.format(checkedAt)}</time> · 화면이 보일 때 10초마다 확인</span>}
      <button type="button" className="button-secondary ag-refresh" onClick={() => void load()} disabled={loading}>
        {loading ? <LoaderCircle size={15} className="ag-spin" aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />}새로고침</button>
    </div>
    {error && activity && <div className="ag-message is-warn" role="alert"><TriangleAlert size={16} aria-hidden="true" /><span>마지막 조회 결과입니다. {error}</span>
      <button type="button" onClick={() => void load()} disabled={loading}>다시 시도</button></div>}
    {!activity ? (error
      ? <div className="ag-empty" role="alert"><CircleAlert size={26} aria-hidden="true" /><h2>에이전트 활동을 확인할 수 없습니다</h2><p>{error}</p>
        <button type="button" className="button-secondary" onClick={() => void load()} disabled={loading}>다시 시도</button></div>
      : <p className="ag-empty-tab" role="status">에이전트 활동을 불러오는 중입니다.</p>)
    : !anything ? <div className="ag-empty"><Bot size={30} strokeWidth={1.5} aria-hidden="true" /><h2>작업 에이전트가 아직 실행되지 않았습니다</h2>
        <p>OpenCode 같은 작업 에이전트가 이 콘솔의 작업 도구(MCP·CLI)로 문서를 원본과 대조하고 사람이 볼 곳을 검수 요청으로 올리면 여기에 쌓입니다. 연결과 사용법은 저장소의 <code>docs/AGENT_TOOLS.md</code>를 참고하세요.</p></div>
    : <div className="ag-sheet">
      <Tabs<Tab> label="에이전트 기록" value={tab ?? 'reviews'} onChange={setTab} items={[
        { id: 'reviews', label: <><ClipboardCheck size={15} aria-hidden="true" />검수 요청</>, badge: open ? `확인 전 ${open}` : reviews.reviews.length },
        { id: 'docs', label: '문서', badge: activity.documents.length },
        { id: 'batches', label: '묶음', badge: activity.batches.length },
        { id: 'calls', label: '호출 기록', badge: activity.calls.length },
      ]}>
        {view => view === 'reviews' ? <Reviews reviews={reviews.reviews} counts={reviews.counts} error={reviews.error} onNavigate={onNavigate} onChanged={changed} />
          : view === 'docs' ? <HandledDocs documents={activity.documents} docs={index} onNavigate={onNavigate} />
          : view === 'batches' ? activity.batches.length ? <ol className="ag-batches">{activity.batches.map(batch => <BatchRow key={batch.n} batch={batch} docs={index} onNavigate={onNavigate} />)}</ol>
            : <p className="ag-empty-tab">실행한 묶음이 없습니다. 에이전트가 parse 도구를 부르면 B번호 묶음이 생깁니다.</p>
          : <Calls calls={activity.calls} docs={index} onNavigate={onNavigate} />}
      </Tabs>
    </div>}
  </div>;
}
