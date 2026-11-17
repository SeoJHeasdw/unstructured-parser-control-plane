import { useEffect, useState } from 'react';
import { getDrilldown } from '../api/retrieval';
import type { Combo, Drilldown, Run, RunQuestion } from '../api/retrieval';
import { ListBox, Modal, Segmented } from '../ui';
import { QUESTION_KIND_META } from './elements';
import { errorText, fmtInt, fmtScore } from './shared';
import { BASIS_LABEL, cutoffOf, fmtMetric, isMissed, metricLabel, metricsOf, modelName, outcomeOf } from './eval-common';
import type { Basis, KindKey, MetricKey, Outcome } from './eval-common';

type Item = { q: RunQuestion; out: Outcome; missed: boolean };

/** 모델 × 질문 유형: 왼쪽 질문 목록(정답 순위), 오른쪽 질문·정답·실제로 검색된 청크. */
export function ResultModal({ run, combo, kind, metric, basis, onClose }: { run: Run; combo: Combo; kind: KindKey; metric: MetricKey; basis: Basis; onClose: () => void }) {
  const cutoff = cutoffOf(metric);
  const items: Item[] = run.questions.filter(q => kind === 'all' || q.kind === kind).map(q => {
    const out = outcomeOf(combo.per_question[q.index], basis, q);
    return { q, out, missed: isMissed(out, cutoff) };
  });
  const missedCount = items.filter(i => i.missed).length;
  const [filter, setFilter] = useState<'all' | 'miss'>('all');
  const [sel, setSel] = useState<string | null>(null);
  const shown = filter === 'miss' ? items.filter(i => i.missed) : items;
  const current = shown.find(i => String(i.q.index) === sel) ?? shown[0] ?? null;
  const value = metricsOf(combo, kind, basis).metrics?.[metric];
  const kindLabel = kind === 'all' ? '전체 질문' : QUESTION_KIND_META[kind].label;

  return <Modal open onClose={onClose} size="xl" flush title={`${modelName(combo.model)} · ${kindLabel}`}
    subtitle={`${metricLabel(metric)} ${fmtMetric(metric, value)} · ${BASIS_LABEL[basis]} 기준 · ${combo.preset_name}`}>
    <div className="ui-split ee-split">
      <div>
        <div className="ee-split-tools">
          <Segmented label="보기" value={filter} onChange={setFilter}
            options={[{ id: 'all', label: <>전체 <span className="ee-num">{fmtInt(items.length)}</span></> }, { id: 'miss', label: <>놓친 질문 <span className="ee-num">{fmtInt(missedCount)}</span></> }]} />
        </div>
        <ListBox items={shown} getKey={i => String(i.q.index)} value={current ? String(current.q.index) : null} onChange={setSel} label="질문 목록" className="ee-list"
          empty={<div className="ui-listbox-empty">{filter === 'miss' ? '놓친 질문이 없습니다.' : '이 유형의 질문이 없습니다.'}</div>}
          render={i => <div className="ee-opt is-result">
            <span className={`ee-rank${i.missed ? ' is-miss' : ''}${i.out.tone === 'na' ? ' is-na' : ''}`}>{i.out.label}</span>
            <span className="ee-clamp">{kind === 'all' && <i className="ee-sw" style={{ background: QUESTION_KIND_META[i.q.kind].color }} />}{i.q.question}</span>
          </div>} />
      </div>
      <div>{current ? <QuestionDetail key={current.q.index} run={run} combo={combo} item={current} /> : <div className="ui-empty"><b>질문이 없습니다</b></div>}</div>
    </div>
  </Modal>;
}

function QuestionDetail({ run, combo, item }: { run: Run; combo: Combo; item: Item }) {
  const { q } = item;
  const [state, setState] = useState<{ data?: Drilldown; error?: string }>({});
  useEffect(() => {
    if (!run.drilldown) return;
    const controller = new AbortController();
    getDrilldown(combo.key, q.index, controller.signal).then(data => setState({ data }), error => { if (!controller.signal.aborted) setState({ error: errorText(error) }); });
    return () => controller.abort();
  }, [run.drilldown, combo.key, q.index]);
  const docName = run.request.documents.find(d => d.id === q.doc_id)?.name ?? '목록에 없는 문서';
  const doc = outcomeOf(combo.per_question[q.index], 'doc', q);
  const span = outcomeOf(combo.per_question[q.index], 'span', q);
  return <article className="ee-detail">
    <p className="ee-detail-kind"><i className="ee-sw" style={{ background: QUESTION_KIND_META[q.kind].color }} />{QUESTION_KIND_META[q.kind].label}</p>
    <h3 className="ee-detail-q">{q.question}</h3>
    <dl className="ee-answer">
      <div><dt>정답 문서</dt><dd>{docName}<span className="ee-rank-text">{doc.label}</span></dd></div>
      <div><dt>정답 구절</dt><dd>{q.answer || '없음'}{q.answer && <span className="ee-rank-text">{span.label}</span>}</dd></div>
    </dl>
    <h4 className="ee-h">검색된 청크</h4>
    {!run.drilldown ? <p className="ee-quiet">이 실행은 검색된 청크를 남기지 않았습니다.</p>
      : state.error ? <p className="ee-quiet is-bad">{state.error}</p>
      : !state.data ? <p className="ee-quiet">불러오는 중</p>
      : state.data.failed ? <p className="ee-quiet is-bad">이 질문은 임베딩하지 못했습니다.</p>
      : <ol className="ee-hits" aria-label="검색된 청크">{state.data.results.map(r => <li key={r.rank}>
        <div className="ee-hit-head">
          <b className="ee-num">{r.rank}</b>
          <span className="ee-hit-doc">{r.doc_name}{r.heading_path.length > 0 && ` · ${r.heading_path.join(' › ')}`}</span>
          {r.hit_doc && <span className="ui-pill">정답 문서</span>}{r.hit_span && <span className="ui-pill">정답 구절</span>}
          <span className="ee-score ee-num">{fmtScore(r.score)}</span>
        </div>
        <p className="ee-hit-text">{r.text}</p>
      </li>)}</ol>}
  </article>;
}
