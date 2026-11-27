import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { getQcSummary } from './api/live';
import type { QcSummary } from './api/live';
import { qcStateText } from './compare/QcGate';

/** 파싱하지 못한 사유(오류 코드·상태) → 짧은 이름. 모르는 코드는 그대로 보인다. */
const notParsedLabels: Record<string, string> = {
  uploaded: '실행 전', unsupported_format: '미지원', unsupported: '미지원', parser_unavailable: '파서·모델 없음', no_text: '본문 없음',
  encrypted: '암호', drm_protected: '문서 보안', drm_suspected: '보안 의심', format_mismatch: '형식 불일치', format_unrecognized: '형식 인식 실패',
  encoding_unknown: '인코딩 모름', limit_exceeded: '한도 초과', interrupted: '중단됨', internal_error: '내부 오류', parse_failed: '파싱 실패',
  failed: '실패', queue_full: '대기열 가득',
};

/**
 * 처리 깔때기: 반입 전체 → 파싱 완료 → 자동 대조 → 판정 상태. 마지막 단계(통과 후보)만 보고 처리율을 말하면 스캔·미지원 파일이
 * 통계에서 사라지므로 분모를 차례로 보인다. 통과 후보도 기록 모드라 사람 검수를 이어 간다.
 */
export function QcFunnel({ revision, active }: { revision: number; active: boolean }) {
  const [summary, setSummary] = useState<QcSummary | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    getQcSummary(controller.signal).then(body => { if (!controller.signal.aborted) setSummary(body); }).catch(() => { /* 예전 서버: 깔때기를 그리지 않는다 */ });
    return () => controller.abort();
  }, [revision, active]);
  if (!summary || !summary.documents || typeof summary.states !== 'object') return null;
  const notParsed = Object.entries(summary.not_parsed ?? {}).sort((a, b) => b[1] - a[1]);
  const notParsedTotal = notParsed.reduce((sum, [, count]) => sum + count, 0);
  const steps = [
    { label: '반입 전체', value: summary.documents },
    { label: '파싱 완료', value: summary.parsed, note: notParsedTotal ? `못 함 ${notParsedTotal}` : undefined,
      tip: notParsed.map(([key, count]) => `${notParsedLabels[key] ?? key} ${count}`).join(' · ') },
    { label: '자동 대조', value: summary.qc_done, note: summary.qc_pending ? `미평가 ${summary.qc_pending}` : summary.qc_unavailable ? `대조 불가 ${summary.qc_unavailable}` : undefined,
      tip: '최신 성공 실행을 원본 글자와 대조한 문서. 미평가는 원문 대조를 열면 계산합니다.' },
  ];
  return <section className="qc-funnel" aria-label="처리 깔때기">
    <ol>
      {steps.map((step, index) => <li key={step.label} data-tip={step.tip || undefined}>
        {index > 0 && <ChevronRight size={14} aria-hidden="true" className="qc-funnel-arrow" />}
        <span className="qc-funnel-step"><small>{step.label}</small><b className="ui-num">{step.value.toLocaleString('ko-KR')}</b>{step.note && <em>{step.note}</em>}</span>
      </li>)}
      <li className="qc-funnel-states">
        <ChevronRight size={14} aria-hidden="true" className="qc-funnel-arrow" />
        {(['needs_review', 'undetermined', 'pass_candidate'] as const).map(state => <span key={state} className={`qc-funnel-state is-${state}`} data-tip={qcStateText[state].tip}>
          <small>{qcStateText[state].label}</small><b className="ui-num">{summary.states[state].toLocaleString('ko-KR')}</b></span>)}
      </li>
    </ol>
    <p>통과 후보도 기록 모드입니다: 운영 자동 통과는 꺼져 있고 사람 검수를 이어 갑니다.{summary.human_decided ? ` 사람 판정이 있는 문서 ${summary.human_decided}개.` : ''}</p>
  </section>;
}
