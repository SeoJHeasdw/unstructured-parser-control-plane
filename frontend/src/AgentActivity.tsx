import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, CircleAlert, Copy, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react';
import { getAgentActivity } from './api/agent';
import type { AgentActivity as Activity, AgentBatch, AgentCall, AgentReport } from './api/agent';
import { listLiveDocuments } from './api/live';
import type { LiveDoc } from './api/live';
import { displayStatus, statusLabels } from './LiveDocumentView';
import { WorkspaceLink } from './WorkspaceLink';
import type { WorkspaceRoute } from './navigation';
import { ListBox, Tabs, modKey } from './ui';
import './agent.css';

type Tab = 'batches' | 'reports' | 'calls';
type Navigate = (route: WorkspaceRoute) => void;
type DocIndex = { bySeq: Map<number, LiveDoc>; loaded: boolean };

const REFRESH_MS = 10_000;
const CHIP_LIMIT = 40;
/** 표는 docs/AGENT_TOOLS.md·backend/app/agent/codes.py와 같은 뜻이다. */
const SKIP_MEANINGS: Record<string, string> = { lock: 'Office 임시 잠금 파일(~$)', hidden: '숨김·시스템 파일', empty: '0바이트 파일', 'too-big': '업로드 한도 초과' };
const ITEM_ERRORS: Record<string, string> = { missing: '서버에서 문서를 찾을 수 없음', 'missing-file': '원본 파일이 없어짐', 'read-fail': '원본 파일을 읽지 못함', 'too-big': '업로드 한도 초과' };
const CALL_ERRORS: Record<string, string> = {
  'bad-arg': '잘못된 인자', 'not-found': '대상 없음', outside: '허용 폴더 밖', 'server-down': '콘솔 서버 꺼짐',
  busy: '서버가 바쁨(409·503)', api: '그 밖의 API 오류', internal: '작업 도구 내부 오류',
};
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

function DocChip({ seq, docs, onNavigate }: { seq: number; docs: DocIndex; onNavigate: Navigate }) {
  const label = `D${seq}`;
  const doc = docs.bySeq.get(seq);
  if (!doc) return <span className="ag-chip is-missing" data-tip={docs.loaded ? '문서함에서 찾을 수 없습니다.' : '문서 목록을 불러오지 못했습니다.'}>{label}</span>;
  const status = displayStatus(doc);
  return <WorkspaceLink className={`ag-chip is-${status}`} to={{ page: 'live', doc: doc.id }} onNavigate={onNavigate}
    aria-label={`${label} ${doc.name}`} data-tip={`${doc.name} · ${statusLabels[status]}`}>{label}</WorkspaceLink>;
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

function ReportView({ report, docs, onNavigate }: { report: AgentReport; docs: DocIndex; onNavigate: Navigate }) {
  const pre = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState<'' | 'copied' | 'selected'>('');
  const mentioned = useMemo(() => [...new Set(Array.from(report.text.matchAll(/\bD(\d+)\b/g), match => Number(match[1])))].filter(n => n > 0), [report.text]);
  useEffect(() => { if (copied !== 'copied') return; const timer = window.setTimeout(() => setCopied(''), 4000); return () => window.clearTimeout(timer); }, [copied]);
  return <section className="ag-report" aria-label={`보고서 ${report.name}`}>
    <header>
      <h2><code>{report.name}</code></h2>
      <time dateTime={report.modified}>{fullTime(report.modified) || '시각 미기록'}</time>
      <button type="button" className="button-secondary" onClick={async () => setCopied(await copyText(report.text, pre.current))}>
        {copied === 'copied' ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}복사</button>
    </header>
    {copied && <p className="ag-copy-note" role="status">{copied === 'copied' ? '보고서를 복사했습니다.' : `자동 복사를 쓸 수 없어 본문을 선택해 두었습니다. ${modKey('C')}로 복사하세요.`}</p>}
    <pre ref={pre} className="ag-pre" tabIndex={0} aria-label={`${report.name} 본문`}>{report.text || '(빈 보고서)'}</pre>
    {mentioned.length > 0 && <div className="ag-mentioned"><span>보고서에 나온 문서</span>
      <DocChips seqs={mentioned} docs={docs} onNavigate={onNavigate} label={`${report.name}에 나온 문서`} /></div>}
  </section>;
}

function Reports({ reports, docs, onNavigate }: { reports: AgentReport[]; docs: DocIndex; onNavigate: Navigate }) {
  const [selected, setSelected] = useState<string | null>(null);
  const current = reports.find(report => report.name === selected) ?? reports[0];
  if (!current) return <p className="ag-empty-tab">저장된 보고서가 없습니다. 에이전트가 묶음 파싱을 마치거나 report 도구를 부르면 생깁니다.</p>;
  return <div className="ag-reports">
    <ListBox items={reports} getKey={report => report.name} value={current.name} onChange={setSelected} label="보고서 목록" className="ag-report-list"
      render={report => <span className="ag-report-item"><code>{report.name}</code><time dateTime={report.modified}>{shortTime(report.modified)}</time></span>} />
    <ReportView key={current.name} report={current} docs={docs} onNavigate={onNavigate} />
  </div>;
}

function Calls({ calls }: { calls: AgentCall[] }) {
  const [errorsOnly, setErrorsOnly] = useState(false);
  const errors = calls.filter(call => call.kind).length;
  const repeats = calls.filter(call => call.repeat).length;
  const rows = errorsOnly ? calls.filter(call => call.kind) : calls;
  return <div className="ag-calls">
    <div className="ag-calls-tools">
      <button type="button" className="ag-toggle" aria-pressed={errorsOnly} onClick={() => setErrorsOnly(!errorsOnly)}>
        <CircleAlert size={14} aria-hidden="true" />오류만<span className="ui-num">{errors}</span></button>
      <span className="ag-calls-sum">호출 <b className="ui-num">{calls.length}</b> · 오류 <b className="ui-num">{errors}</b> · 반복 <b className="ui-num">{repeats}</b></span>
    </div>
    {rows.length ? <div className="ag-table-wrap" role="region" aria-label="도구 호출 기록 표" tabIndex={0}><table className="ag-table">
      <thead><tr><th scope="col">시각</th><th scope="col">도구</th><th scope="col">인자</th><th scope="col">결과 첫 줄</th><th scope="col">표시</th><th scope="col" className="is-num">ms</th></tr></thead>
      <tbody>{rows.map((call, i) => {
        const args = compactArgs(call.args);
        return <tr key={`${call.ts}-${i}`} className={call.kind ? 'is-error' : undefined}>
          <td><time dateTime={call.ts} data-tip={fullTime(call.ts) || undefined}>{shortTime(call.ts)}</time></td>
          <td><code>{call.tool || '—'}</code></td>
          <td><span className="ag-clip ag-args" data-tip={args || undefined} data-tip-overflow>{args || '—'}</span></td>
          <td><span className="ag-clip" data-tip={call.result || undefined} data-tip-overflow>{call.result || '—'}</span></td>
          <td><span className="ag-badges">{call.kind && <span className="ag-kind" data-tip={CALL_ERRORS[call.kind] ?? '오류'}>{call.kind}</span>}
            {call.repeat && <span className="ag-repeat" data-tip="2분 안에 같은 도구·같은 인자로 다시 불렀습니다.">반복</span>}</span></td>
          <td className="is-num ui-num">{call.ms === null ? '—' : call.ms.toLocaleString('ko-KR')}</td>
        </tr>;
      })}</tbody>
    </table></div> : <p className="ag-empty-tab">{errorsOnly ? '오류가 기록된 호출이 없습니다.' : '기록된 도구 호출이 없습니다.'}</p>}
    {(errors > 0 || repeats > 0) && <details className="ag-legend"><summary>표시 설명</summary><dl>
      {Object.entries(CALL_ERRORS).map(([kind, meaning]) => <div key={kind}><dt><code>{kind}</code></dt><dd>{meaning}</dd></div>)}
      <div><dt>반복</dt><dd>2분 안에 같은 도구·같은 인자로 다시 부름</dd></div>
    </dl></details>}
  </div>;
}

/** 작업 에이전트가 남긴 묶음·보고서·호출 기록을 읽기만 한다. 화면이 보일 때만 10초마다 다시 읽는다. */
export default function AgentActivity({ active = true, onNavigate }: { active?: boolean; onNavigate: Navigate }) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [docs, setDocs] = useState<LiveDoc[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [tab, setTab] = useState<Tab>('batches');
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      // 문서 목록은 D번호를 문서로 잇는 데만 쓴다. 실패해도 활동은 보여 준다.
      const [next, documents] = await Promise.all([getAgentActivity(controller.signal), listLiveDocuments(controller.signal).catch(() => null)]);
      if (controller.signal.aborted) return;
      setActivity(next);
      if (documents) setDocs(documents);
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
    bySeq: new Map((docs ?? []).filter(doc => typeof doc.seq === 'number').map(doc => [doc.seq as number, doc])), loaded: docs !== null,
  }), [docs]);

  return <div className="ag-workspace">
    <div className="ag-toolbar">
      <span className="ag-source"><Bot size={16} aria-hidden="true" />읽기 전용 · 서버의 <code>runtime/agent</code> 기록</span>
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
    : !activity.available ? <div className="ag-empty"><Bot size={30} strokeWidth={1.5} aria-hidden="true" /><h2>작업 에이전트가 아직 실행되지 않았습니다</h2>
        <p>OpenCode 같은 작업 에이전트가 이 콘솔의 작업 도구(MCP·CLI)를 처음 부르면 묶음·보고서·호출 기록이 여기에 쌓입니다. 연결과 사용법은 저장소의 <code>docs/AGENT_TOOLS.md</code>를 참고하세요.</p></div>
    : <div className="ag-sheet">
      <Tabs<Tab> label="에이전트 기록" value={tab} onChange={setTab} items={[
        { id: 'batches', label: '묶음', badge: activity.batches.length },
        { id: 'reports', label: '보고서', badge: activity.reports.length },
        { id: 'calls', label: '호출 기록', badge: activity.calls.length },
      ]}>
        {view => view === 'batches'
          ? activity.batches.length ? <ol className="ag-batches">{activity.batches.map(batch => <BatchRow key={batch.n} batch={batch} docs={index} onNavigate={onNavigate} />)}</ol>
            : <p className="ag-empty-tab">실행한 묶음이 없습니다. 에이전트가 parse 도구를 부르면 B번호 묶음이 생깁니다.</p>
          : view === 'reports' ? <Reports reports={activity.reports} docs={index} onNavigate={onNavigate} />
          : <Calls calls={activity.calls} />}
      </Tabs>
    </div>}
  </div>;
}
