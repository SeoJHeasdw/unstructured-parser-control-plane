import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Play, Square } from 'lucide-react';
import { cancelRun, getConfig, getQuestions, getRun, getSamples, listDocuments, planRun, sampleDocId, startRun } from './api/retrieval';
import type { Candidate, Combo, PlanResult, Preset, Question, QuestionKind, RetrievalConfig, RetrievalDoc, Run, Sample } from './api/retrieval';
import { Segmented } from './ui';
import { QUESTION_KIND_META, QUESTION_KINDS } from './retrieval/elements';
import { STORE, describeParams, errorText, fmtBytes, fmtInt, loadPresets, usePersistent, useTip } from './retrieval/shared';
import { BASIS_LABEL, DEFAULT_MODELS, KIND_SHORT, METRICS, defaultCandidates, fmtMetric, isCandidate, metricLabel, metricsOf, modelName, normalizeCandidate, samePreset, specFor } from './retrieval/eval-common';
import type { Basis, KindKey, MetricKey } from './retrieval/eval-common';
import { DocsModal, ModelFacts, ModelsModal } from './retrieval/eval-setup';
import { QuestionsModal } from './retrieval/eval-questions';
import { ResultModal } from './retrieval/eval-result';
import './retrieval.css';
import './embedding.css';

/**
 * 임베딩 평가: 모델을 행으로 놓고 본문·표·그림 질문별 정확도를 나란히 본다.
 * 청킹은 청킹 벤치의 방식 하나로 고정한다. 입력 한도 초과·벡터 용량 열은 실행 전에도 실제 계산값이다.
 * 문서·질문·모델 설정과 질문별 결과는 팝업으로 연다.
 */
type Ui = { metric: MetricKey; basis: Basis };
type Setup = { candidates: Candidate[] | null; docIds: string[] | null; presetId: string | null };
type Pick = { candidateId: string; kind: KindKey };
type PlanState = { key: string; data: PlanResult | null; error: string | null };
type Dialog = 'docs' | 'questions' | 'models' | null;

/** 기본 모델이 다섯으로 바뀌어 저장 키를 올렸다. 이전 구성은 읽지 않는다. */
const SETUP_KEY = `${STORE.candidates}:v3`;
const POLL_MS = 1500;
const PLAN_DELAY = 300;
const TOP_K = 10;
const COLS: KindKey[] = [...QUESTION_KINDS, 'all'];

export default function EmbeddingEval({ active }: { active: boolean }) {
  const [rawUi, setUi] = usePersistent<Ui>(STORE.evalUi, { metric: 'hit@5', basis: 'doc' });
  const ui: Ui = { metric: METRICS.some(m => m.key === rawUi.metric) ? rawUi.metric : 'hit@5', basis: rawUi.basis === 'span' ? 'span' : 'doc' };
  const [setup, setSetup] = usePersistent<Setup>(SETUP_KEY, { candidates: null, docIds: null, presetId: null });
  const [config, setConfig] = useState<RetrievalConfig | null>(null);
  const [docs, setDocs] = useState<RetrievalDoc[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [presets, setPresets] = useState<Preset[]>(loadPresets);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanState | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const tip = useTip();
  const loaded = useRef(false);

  const load = useCallback(async () => {
    setLoadError(null);
    const [c, d, s, q, r] = await Promise.allSettled([getConfig(), listDocuments(), getSamples(), getQuestions(), getRun()]);
    if (c.status === 'fulfilled') setConfig(c.value); else setLoadError(errorText(c.reason));
    if (d.status === 'fulfilled') setDocs(d.value);
    if (s.status === 'fulfilled') setSamples(s.value);
    if (q.status === 'fulfilled') setQuestions(q.value.questions);
    if (r.status === 'fulfilled') setRun(r.value);
    setReady(true);
  }, []);
  useEffect(() => { if (active && !loaded.current) { loaded.current = true; void load(); } }, [active, load]);
  useEffect(() => { if (active) setPresets(loadPresets()); }, [active]);

  /* 실행 중이고 화면이 보일 때만 진행 상태를 묻는다. */
  const running = run?.status === 'running';
  useEffect(() => {
    if (!active || !running) return;
    let stopped = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const next = await getRun(controller.signal);
        if (stopped) return;
        setRun(next);
        if (next?.status === 'running') timer = setTimeout(tick, POLL_MS);
      } catch {
        if (!stopped) timer = setTimeout(tick, POLL_MS * 3);
      }
    };
    timer = setTimeout(tick, POLL_MS);
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [active, running]);

  /* ---------- 현재 구성 ---------- */
  const caps = config?.caps ?? run?.caps ?? null;
  const candidates = useMemo<Candidate[]>(() => Array.isArray(setup.candidates) ? setup.candidates.filter(isCandidate).map(normalizeCandidate) : defaultCandidates(config), [setup.candidates, config]);
  const isDefault = setup.candidates === null || (candidates.length === DEFAULT_MODELS.length && candidates.every((c, i) => (specFor(config?.specs, c.model)?.id ?? c.model) === DEFAULT_MODELS[i]));
  const preset = presets.find(p => p.id === setup.presetId) ?? presets.find(p => p.kind === 'element') ?? presets[0] ?? null;
  const docIds = useMemo(() => {
    const sampleIds = samples.map(s => sampleDocId(s.id));
    if (Array.isArray(setup.docIds)) { const known = new Set([...sampleIds, ...docs.map(d => d.id)]); return setup.docIds.filter(id => known.has(id)); }
    const asked = new Set((questions ?? []).map(q => q.doc_id));
    return [...sampleIds, ...docs.filter(d => asked.has(d.id)).map(d => d.id)].slice(0, caps?.max_documents ?? 200);
  }, [setup.docIds, samples, docs, questions, caps]);
  const sampleCount = docIds.filter(id => id.startsWith('sample:')).length;
  const models = [...new Set(candidates.map(c => c.model.trim()).filter(Boolean))];

  /* ---------- 계획: 고른 청킹으로 나눈 청크 수, 모델별 입력 한도 초과, 벡터 용량(외부 호출 없음) ---------- */
  const planBody = useMemo(() => preset && docIds.length && models.length ? { doc_ids: docIds, preset, models } : null, [preset, docIds, models.join('\n')]); // eslint-disable-line react-hooks/exhaustive-deps
  const planKey = JSON.stringify([planBody, (questions ?? []).map(q => `${q.doc_id}:${q.kind ?? ''}`)]);
  useEffect(() => {
    if (!active || !ready || !planBody) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      planRun(planBody, controller.signal).then(
        data => setPlan({ key: planKey, data, error: null }),
        error => { if (!controller.signal.aborted) setPlan({ key: planKey, data: null, error: errorText(error) }); });
    }, PLAN_DELAY);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [active, ready, planKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const planData = planBody ? plan?.data ?? null : null;
  const planStale = !!plan && plan.key !== planKey;
  const planError = planBody ? (plan?.error ?? planData?.errors[0] ?? null) : null;
  const docSet = new Set(docIds);
  const questionTotal = (questions ?? []).filter(q => docSet.has(q.doc_id)).length;
  const kindCount = (k: QuestionKind) => planData && !planStale ? planData.questions.by_kind[k] : null;

  /* ---------- 실행 ---------- */
  const connOk = (c: Candidate) => !!config?.connections.find(x => x.key === c.connection && x.configured);
  const reason = !config ? (loadError ?? (ready ? '설정을 불러오지 못했습니다' : null))
    : !config.configured ? '임베딩 연결이 없습니다'
    : !candidates.length ? '비교할 모델이 없습니다'
    : candidates.some(c => !c.model.trim()) ? '모델 ID가 빈 모델이 있습니다'
    : candidates.some(c => !connOk(c)) ? '연결이 없는 모델이 있습니다'
    : !preset ? '청킹이 없습니다'
    : !docIds.length ? '고른 문서가 없습니다'
    : questions === null ? '질문을 불러오지 못했습니다'
    : !questionTotal ? '고른 문서에 질문이 없습니다'
    : caps && questionTotal > caps.max_questions ? `질문은 한 번에 ${fmtInt(caps.max_questions)}개까지입니다` : null;
  const start = async () => {
    if (!preset) return;
    setBusy(true); setActionError(null); setPick(null);
    try { setRun(await startRun({ doc_ids: docIds, presets: [preset], candidates, top_k: Math.max(TOP_K, caps?.top_k_min ?? TOP_K) })); }
    catch (error) { setActionError(errorText(error)); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    setBusy(true); setActionError(null);
    try { await cancelRun(); setRun(await getRun()); }
    catch (error) { setActionError(errorText(error)); }
    finally { setBusy(false); }
  };

  /* ---------- 결과: 지금 고른 청킹과 같은 실행일 때만 칸을 채운다. ---------- */
  const runPreset = run?.request.presets[0] ?? null;
  const shown = run && runPreset && samePreset(runPreset, preset) ? run : null;
  const comboOf = useCallback((c: Candidate): Combo | undefined => shown?.results.find(r => r.model === c.model && r.connection === c.connection), [shown]);
  const valueOf = useCallback((combo: Combo | undefined, kind: KindKey) => {
    const v = metricsOf(combo, kind, ui.basis).metrics?.[ui.metric];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  }, [ui.basis, ui.metric]);
  const best = useMemo(() => {
    const out = {} as Record<KindKey, number | null>;
    for (const k of COLS) {
      const values = candidates.map(c => valueOf(comboOf(c), k)).filter((v): v is number => v !== null);
      out[k] = values.length > 1 ? Math.max(...values) : null;
    }
    return out;
  }, [candidates, comboOf, valueOf]);
  const picked = pick && shown ? candidates.find(c => c.id === pick.candidateId) : undefined;
  const pickedCombo = picked ? comboOf(picked) : undefined;
  const otherDocs = !!shown && (shown.request.documents.length !== docIds.length || shown.request.documents.some(d => !docSet.has(d.id)));
  const runPresetLocal = runPreset ? presets.find(p => samePreset(p, runPreset)) ?? null : null;

  /* 상태는 한 자리에 하나만. */
  let status: { tone: '' | 'bad' | 'warn'; body: ReactNode } | null = null;
  if (actionError) status = { tone: 'bad', body: actionError };
  else if (running && run) {
    const pct = run.progress.total > 0 ? Math.min(100, Math.round(run.progress.done / run.progress.total * 100)) : 0;
    status = { tone: '', body: <><span className="ee-progress" aria-hidden><i style={{ width: `${pct}%` }} /></span>
      <span className="ee-num">{fmtInt(run.progress.done)} / {fmtInt(run.progress.total)}</span>{run.progress.phase ? ` · ${modelName(run.progress.phase)}` : ''}{run.progress.detail ? ` ${run.progress.detail}` : ''}</> };
  } else if (run?.status === 'failed') status = { tone: 'bad', body: run.error ?? '평가하지 못했습니다' };
  else if (reason) status = { tone: '', body: reason };
  else if (run && !shown && runPreset) status = { tone: '', body: runPresetLocal
    ? <>이전 결과는 {runPreset.name} 기준<button type="button" className="ee-link" onClick={() => setSetup(prev => ({ ...prev, presetId: runPresetLocal.id }))}>그 청킹으로 보기</button></>
    : '이전 결과는 바꾸기 전 청킹 기준입니다' };
  else if (planError) status = { tone: 'warn', body: `청크를 계산하지 못했습니다 · ${planError}` };
  else if (shown) status = { tone: '', body: `${shown.status === 'cancelled' ? '취소됨' : '측정'} ${fmtTime(shown.finished_at ?? shown.created_at)}${otherDocs ? ' · 지금과 다른 문서 기준' : ''}` };

  const docsLabel = [sampleCount ? `예시 ${sampleCount}` : '', docIds.length - sampleCount ? `실제 ${docIds.length - sampleCount}` : ''].filter(Boolean).join(' · ') || '없음';
  const openDialog = (d: Dialog) => { tip.hide(); setDialog(d); };

  return <div className="ee-root">
    <div className="ee-bar">
      <div className="ee-chunk">
        <label className="ee-chunk-field"><span>청킹</span>
          <select value={preset?.id ?? ''} onChange={e => setSetup(prev => ({ ...prev, presetId: e.target.value }))} disabled={!presets.length}>
            {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        {preset && <span className="ee-chunk-desc">{describeParams(preset.params)}</span>}
      </div>
      <button type="button" className="ee-pick" onClick={() => openDialog('docs')}><span>문서</span><b>{docsLabel}</b></button>
      <button type="button" className="ee-pick" onClick={() => openDialog('questions')}><span>질문</span><b className="ee-num">{fmtInt(questionTotal)}</b></button>
      <button type="button" className="ee-pick" onClick={() => openDialog('models')}><span>모델</span><b className="ee-num">{fmtInt(candidates.length)}</b></button>
      <div className="ee-run">
        {status && <span className={`ee-status${status.tone ? ` is-${status.tone}` : ''}`} role="status">{status.body}</span>}
        {running
          ? <button type="button" className="ee-btn" onClick={cancel} disabled={busy}><Square size={14} aria-hidden />취소</button>
          : <button type="button" className="ee-btn is-primary" onClick={start} disabled={!config || !!reason || busy}><Play size={14} aria-hidden />평가 실행</button>}
      </div>
    </div>

    <section className="ee-board" aria-label="모델 비교">
      <div className="ee-board-bar">
        <Segmented label="지표" value={ui.metric} onChange={metric => setUi(prev => ({ ...prev, metric }))} options={METRICS.map(m => ({ id: m.key, label: m.label }))} />
        <Segmented label="기준" value={ui.basis} onChange={basis => setUi(prev => ({ ...prev, basis }))} options={(['doc', 'span'] as Basis[]).map(b => ({ id: b, label: BASIS_LABEL[b] }))} />
      </div>
      <div className="ee-scroll">
        <table className={`ee-table${planStale ? ' is-planning' : ''}`}>
          <colgroup><col className="ee-c-model" />{COLS.map(k => <col key={k} className="ee-c-acc" />)}<col className="ee-c-over" /><col className="ee-c-size" /><col className="ee-c-lat" /></colgroup>
          <thead><tr>
            <th scope="col">모델</th>
            {QUESTION_KINDS.map(k => <th scope="col" key={k} className="is-num"><i className="ee-sw" style={{ background: QUESTION_KIND_META[k].color }} />{QUESTION_KIND_META[k].label}
              {kindCount(k) !== null && <span className="ee-th-count">{fmtInt(kindCount(k))}</span>}</th>)}
            <th scope="col" className="is-num">전체</th>
            <th scope="col" className="is-num is-gap">입력 한도 초과 청크</th>
            <th scope="col" className="is-num">벡터 용량</th>
            <th scope="col" className="is-num">지연</th>
          </tr></thead>
          <tbody>{candidates.map(c => {
            const spec = specFor(config?.specs, c.model);
            const pm = planData?.models.find(m => m.model === c.model.trim());
            const combo = comboOf(c);
            const storage = pm?.storage_bytes ?? combo?.storage_bytes ?? null;
            return <tr key={c.id}>
              <th scope="row"><div className="ee-model"><b>{modelName(c.model)}</b><ModelFacts spec={spec} dims={pm?.dims} limit={pm?.max_tokens} /></div></th>
              {combo?.status === 'failed' ? <td colSpan={COLS.length} className="ee-failed">평가하지 못했습니다{combo.error ? ` · ${combo.error}` : ''}</td>
                : COLS.map(k => {
                  const m = metricsOf(combo, k, ui.basis);
                  const v = valueOf(combo, k);
                  const none = m.questions === 0 || (m.questions === null && k !== 'all' && kindCount(k) === 0);
                  if (v === null) return <td key={k} className="is-num ee-empty">{none && (planData?.questions.total ?? 0) > 0 ? '질문 없음' : combo && m.questions ? '구절 없음' : <Dash />}</td>;
                  const label = `${modelName(c.model)} · ${k === 'all' ? '전체' : KIND_SHORT[k]} · ${metricLabel(ui.metric)} ${fmtMetric(ui.metric, v)}`;
                  return <td key={k} className="is-num ee-hit">
                    <button type="button" className={`ee-cell${best[k] !== null && v === best[k] ? ' is-best' : ''}`} aria-label={label}
                      onClick={() => { tip.hide(); setPick({ candidateId: c.id, kind: k }); }} {...tip.bind(() => <CellTip combo={combo!} kind={k} metric={ui.metric} basis={ui.basis} />)}>
                      <span className="ee-track" aria-hidden><i style={{ width: `${Math.max(2, v * 100)}%`, background: k === 'all' ? 'var(--ink-3)' : QUESTION_KIND_META[k].color }} /></span>
                      <span className="ee-val">{fmtMetric(ui.metric, v)}</span>
                    </button>
                  </td>;
                })}
              {!pm || pm.max_tokens === null ? <td className="is-num is-gap ee-empty"><Dash /></td>
                : <td className={`is-num is-gap${pm.over_limit > 0 ? ' ee-over' : ' ee-zero'}`}>{fmtInt(pm.over_limit)}</td>}
              {storage === null ? <td className="is-num ee-empty"><Dash /></td> : <td className="is-num">{fmtBytes(storage)}</td>}
              {combo?.latency_ms ? <td className="is-num">{fmtInt(combo.latency_ms)} ms</td> : <td className="is-num ee-empty"><Dash /></td>}
            </tr>;
          })}</tbody>
        </table>
        {!candidates.length && <p className="ee-none">비교할 모델이 없습니다.</p>}
      </div>
      {planData && planData.chunks > 0 && <p className="ee-foot">청크 {fmtInt(planData.chunks)}개 · 중앙값 {fmtInt(planData.median_chunk_tokens)}토큰 · 가장 긴 청크 {fmtInt(planData.max_chunk_tokens)}토큰</p>}
    </section>

    {tip.node}
    {shown && pick && pickedCombo && <ResultModal key={`${pickedCombo.key}:${pick.kind}`} run={shown} combo={pickedCombo} kind={pick.kind} metric={ui.metric} basis={ui.basis} onClose={() => setPick(null)} />}
    <DocsModal open={dialog === 'docs'} onClose={() => setDialog(null)} samples={samples} docs={docs} questions={questions ?? []} docIds={docIds}
      max={caps?.max_documents ?? 200} onChange={ids => setSetup(prev => ({ ...prev, docIds: ids }))} />
    <QuestionsModal open={dialog === 'questions'} onClose={() => setDialog(null)} questions={questions ?? []} onSaved={setQuestions} samples={samples} docs={docs}
      maxRows={caps?.max_question_rows ?? 2000} />
    <ModelsModal open={dialog === 'models'} onClose={() => setDialog(null)} config={config} candidates={candidates} isDefault={isDefault}
      onChange={list => setSetup(prev => ({ ...prev, candidates: list }))} onReset={() => setSetup(prev => ({ ...prev, candidates: null }))} />
  </div>;
}

/** 아직 값이 없는 칸. 글자보다 옅게 둬서 값이 있는 칸이 먼저 읽히게 한다. */
const Dash = () => <span className="ee-dash">—</span>;

function fmtTime(iso: string | null | undefined) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 칸에 보이지 않는 것만: 나머지 지표, 질문 수, 실패. */
function CellTip({ combo, kind, metric, basis }: { combo: Combo; kind: KindKey; metric: MetricKey; basis: Basis }) {
  const { questions, metrics } = metricsOf(combo, kind, basis);
  const failures = (combo.failures ?? 0) + (combo.query_failures ?? 0);
  return <div className="ee-tip">
    <dl>{METRICS.filter(m => m.key !== metric).map(m => <div key={m.key}><dt>{m.label}</dt><dd>{fmtMetric(m.key, metrics?.[m.key])}</dd></div>)}</dl>
    <p>질문 {fmtInt(questions)}개{failures > 0 ? ` · 임베딩 실패 ${fmtInt(failures)}건` : ''}{combo.over_limit_failed ? ` · 한도 초과로 실패 ${fmtInt(combo.over_limit_failed)}건` : ''}</p>
  </div>;
}
