import { useEffect, useId, useRef, useState } from 'react';
import { CircleCheck, CircleDashed, CircleAlert, ListChecks, LoaderCircle, RefreshCw, ShieldQuestion } from 'lucide-react';
import { getVerify } from '../api/live';
import type { LiveDoc, ProcessOptions, QcCheck, QcGate, QcState, VerifyResult } from '../api/live';
import './qcGate.css';

/** 문서 판정 상태의 화면 이름과 뜻. 통과 후보도 기록 모드라 사람 검수를 이어 간다. */
export const qcStateText: Record<QcState, { label: string; tip: string }> = {
  pending: { label: '미평가', tip: '이 실행에 자동 대조가 아직 닿지 않았습니다. 원문 대조를 열면 계산합니다.' },
  needs_review: { label: '검수 필요', tip: '확인하지 않은 의심점이나 열린 검수 요청이 있습니다.' },
  undetermined: { label: '판정 불가', tip: '의심점은 없지만 검사하지 못한 범위·근거가 있습니다(스캔 쪽, 같은 원천을 두 번 읽음, 형식 계약 없음 등).' },
  pass_candidate: { label: '통과 후보', tip: '필수 조건을 모두 채웠습니다. 기록 모드라 운영 자동 통과는 하지 않고 사람 검수를 이어 갑니다.' },
  unavailable: { label: '대조 불가', tip: '원본 글자를 읽을 수 없어 자동 대조를 하지 못했습니다(손상·암호·이미지).' },
};
const stateIcon = { pending: CircleDashed, needs_review: CircleAlert, undetermined: ShieldQuestion, pass_candidate: CircleCheck, unavailable: CircleDashed };
const checkState: Record<string, string> = { done: '검사함', partial: '일부', unverified: '확인 안 됨' };
const derived: Record<string, string> = { independent: '파서와 별개로 읽음', same_layer: '파서와 같은 원천', same_contract: '파서와 같은 계약으로 읽음', none: '근거 없음' };

/** 목록·막대에 붙는 작은 상태 표시. */
export function QcStateBadge({ state, unresolved }: { state: QcState; unresolved?: number | null }) {
  const Icon = stateIcon[state];
  return <span className={`qc-badge is-${state}`} data-tip={qcStateText[state].tip}><Icon size={13} aria-hidden="true" />
    {qcStateText[state].label}{state === 'needs_review' && unresolved ? <b className="ui-num">{unresolved.toLocaleString('ko-KR')}</b> : null}</span>;
}

function Reasons({ gate, checks, ruleVersion }: { gate: QcGate; checks?: QcCheck[]; ruleVersion?: string }) {
  const blocking = gate.reasons.filter(reason => reason.blocking);
  const notes = gate.reasons.filter(reason => !reason.blocking);
  return <>
    {gate.note && <p className="qc-note">{gate.note}</p>}
    {!!blocking.length && <><h3>{gate.state === 'pass_candidate' ? '근거' : gate.state === 'needs_review' ? '검수가 필요한 이유' : '판정하지 못한 이유'}</h3>
      <ul className="qc-reasons">{blocking.map((reason, i) => <li key={i} className="is-blocking">{reason.message}</li>)}</ul></>}
    {!!notes.length && <><h3>참고</h3><ul className="qc-reasons">{notes.map((reason, i) => <li key={i}>{reason.message}</li>)}</ul></>}
    {!!checks?.length && <><h3>무엇을 검사했나</h3><ul className="qc-checks">{checks.map(check => <li key={check.id}>
      <span className={`qc-check is-${check.state}`}>{checkState[check.state] ?? check.state}</span>
      <span><b>{check.label}</b>{check.derived_from ? <small> · {derived[check.derived_from] ?? check.derived_from}</small> : null}
        {check.detail ? <small>{check.detail}</small> : check.units ? <small>단위 {check.units} · 검사 {check.checked ?? 0} · 제외 {check.excluded ?? 0} · 미확인 {check.unverified ?? 0}</small> : null}
        {check.method ? <small>{check.method}</small> : null}</span></li>)}</ul></>}
    {ruleVersion && <p className="qc-rule">대조 규칙 {ruleVersion}</p>}
  </>;
}

/** 원문 대조 '확인할 곳' 막대의 문서 판정 상태. 누르면 이유와 검사 항목을 펼친다. */
export function QcGateChip({ gate, checks, ruleVersion }: { gate: QcGate; checks?: QcCheck[]; ruleVersion?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
  }, [open]);
  const Icon = stateIcon[gate.state];
  return <span className="qc-chip-wrap" ref={root}>
    <button type="button" className={`qc-badge is-${gate.state} is-button`} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}
      data-tip={open ? undefined : qcStateText[gate.state].tip}>
      <Icon size={13} aria-hidden="true" />{gate.label}{gate.state === 'needs_review' && gate.unresolved ? <b className="ui-num">{gate.unresolved.toLocaleString('ko-KR')}</b> : null}
    </button>
    {open && <div id={id} className="qc-popover" role="dialog" aria-label={`문서 판정: ${gate.label}`}><Reasons gate={gate} checks={checks} ruleVersion={ruleVersion} /></div>}
  </span>;
}

const DELIMITER_LABELS: Record<string, string> = { ',': '쉼표 ,', ';': '세미콜론 ;', '\t': '탭', '|': '세로선 |' };
const ENCODINGS = ['utf-8', 'cp949', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be'] as const;

/** 문서 상세의 '자동 대조' 칸: 판정 상태, 이유, 검사 항목. 텍스트·CSV는 원천 형식(구분자·인코딩)을 지정해 다시 파싱할 수 있다. */
export function QcPanel({ doc, onCompare, onProcess, busy }: { doc: LiveDoc; onCompare: () => void; onProcess: (options: ProcessOptions) => void; busy: boolean }) {
  const [state, setState] = useState<{ key: string; data?: VerifyResult; error?: string }>();
  const [revision, setRevision] = useState(0);
  const [delimiter, setDelimiter] = useState('');
  const [encoding, setEncoding] = useState('');
  const key = `${doc.id}:${doc.updated_at}:${revision}`;
  useEffect(() => {
    if (doc.status === 'processing') return;
    const controller = new AbortController();
    setState({ key });
    getVerify(doc.id, undefined, controller.signal, { limit: 1 }).then(data => {
      if (!controller.signal.aborted) setState({ key, data });
    }).catch(reason => { if (!controller.signal.aborted) setState({ key, error: reason instanceof Error ? reason.message : '자동 대조를 하지 못했습니다.' }); });
    return () => controller.abort();
  }, [doc.id, doc.status, key]);
  const current = state?.key === key ? state : undefined;
  const data = current?.data;
  const gate = data?.gate;
  const contractReasons = gate?.reasons.filter(reason => ['delimiter_ambiguous', 'encoding_uncertain', 'no_evidence'].includes(reason.code)) ?? [];
  const textFormat = ['CSV', 'TXT', 'MD', 'LOG'].includes(doc.format.toUpperCase());
  const isCsv = doc.format.toUpperCase() === 'CSV';
  const alternatives = (contractReasons.find(reason => reason.code === 'delimiter_ambiguous')?.alternatives as string[] | undefined) ?? [];
  const used = contractReasons.find(reason => reason.code === 'delimiter_ambiguous')?.delimiter as string | undefined;
  if (!current || (!data && !current.error)) return <section className="qc-panel" aria-label="자동 대조"><p className="qc-loading"><LoaderCircle size={14} className="live-spin" aria-hidden="true" />자동 대조 판정을 불러오는 중입니다.</p></section>;
  if (current.error || !gate) return <section className="qc-panel is-muted" aria-label="자동 대조"><p><ListChecks size={15} aria-hidden="true" />자동 대조 없음 · {current.error ?? '이 서버는 판정 상태를 보내지 않습니다.'}</p></section>;
  return <section className={`qc-panel is-${gate.state}`} aria-label="자동 대조 판정">
    <header>
      <QcStateBadge state={gate.state} unresolved={gate.unresolved} />
      <span className="qc-counts">의심점 {data!.spots_total.toLocaleString('ko-KR')}곳{data!.summary.high ? ` · 높음 ${data!.summary.high}` : ''}
        {gate.open_reviews ? ` · 열린 검수 요청 ${gate.open_reviews}` : ''}{gate.wrong_reviews ? ` · 틀림 ${gate.wrong_reviews}` : ''}</span>
      <button type="button" className="lw-btn is-compact" onClick={onCompare}>원문 대조에서 확인</button>
      <button type="button" className="lw-icon-btn" aria-label="자동 대조 판정 새로고침" data-tip="새로고침" onClick={() => setRevision(n => n + 1)}><RefreshCw size={14} /></button>
    </header>
    <details className="qc-details" open={gate.state !== 'needs_review'}>
      <summary>판정 근거와 검사 항목</summary>
      <Reasons gate={gate} checks={data!.checks} ruleVersion={data!.rule_version} />
    </details>
    {textFormat && <form className="qc-contract" onSubmit={event => {
      event.preventDefault();
      const options: ProcessOptions = {};
      if (isCsv && delimiter) options.csv_delimiter = delimiter as ProcessOptions['csv_delimiter'];
      if (encoding) options.encoding = encoding as ProcessOptions['encoding'];
      onProcess(options);
    }}>
      <strong>원천 형식 지정</strong>
      <small>{contractReasons.length ? '파서가 고른 값이 확정되지 않았습니다. 원천 시스템의 형식을 알면 지정해 다시 파싱하세요.' : '파서가 고른 값 대신 원천 시스템의 형식으로 다시 파싱합니다.'}</small>
      {isCsv && <label>구분자<select value={delimiter} onChange={event => setDelimiter(event.target.value)}>
        <option value="">파서가 고름{used ? ` (지금 ${DELIMITER_LABELS[used] ?? used})` : ''}</option>
        {Object.entries(DELIMITER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}{alternatives.includes(value) ? ' — 다른 후보' : ''}</option>)}
      </select></label>}
      <label>인코딩<select value={encoding} onChange={event => setEncoding(event.target.value)}>
        <option value="">파서가 고름</option>
        {ENCODINGS.map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <button type="submit" className="lw-btn is-compact" disabled={busy || (!delimiter && !encoding)}>지정해 다시 파싱</button>
    </form>}
  </section>;
}
