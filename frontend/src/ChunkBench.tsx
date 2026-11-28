import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Brain, Check, ChevronDown, FileText, Info, LoaderCircle, Pencil, Plus, RefreshCw, Ruler, Scissors, SlidersHorizontal } from 'lucide-react';
import { chunkSource, getConfig, getSamples, listDocuments } from './api/retrieval';
import type { ChunkResponse, Preset, RetrievalConfig, RetrievalDoc, Sample } from './api/retrieval';
import { Tabs } from './ui';
import type { Column } from './retrieval/chunk-board';
import { CompareTable, CompositionBar } from './retrieval/chunk-compare';
import { StrategyModal, TokenModal } from './retrieval/chunk-detail';
import type { StrategyTab } from './retrieval/chunk-detail';
import { ElementsView } from './retrieval/chunk-elements';
import { MAX_PRESETS, MAX_SELECTED, PresetModal, newPresetId } from './retrieval/chunk-presets';
import { SourceModal } from './retrieval/chunk-source';
import type { SourceKey } from './retrieval/chunk-source';
import { DEFAULT_PRESETS, DEFAULT_SELECTED, STORE, defaultParams, describeParams, errorText, familyOf, fmtInt, loadPresets, savePresets, usePersistent } from './retrieval/shared';
import './retrieval.css';

type Bench = { source: SourceKey | ''; selected: string[]; conn: string; model: string; parallelism: number };
type View = 'compare' | 'elements';
type Open = { id: string; tab: StrategyTab; index: number };
type BenchResult = { key: string; attempt: number; response: ChunkResponse | null; error: string };

export default function ChunkBench({ active, requestedSource, onSourceChange }: {
  active: boolean; requestedSource?: SourceKey; onSourceChange?: (key: SourceKey) => void;
}) {
  const [bench, setBench] = usePersistent<Bench>(STORE.bench, { source: 'sample:report', selected: DEFAULT_SELECTED, conn: '', model: '', parallelism: 1 });
  const [ui, setUi] = usePersistent<{ view: View }>(STORE.benchUi, { view: 'compare' });
  const [presets, setPresets] = useState<Preset[]>(loadPresets);
  const [config, setConfig] = useState<RetrievalConfig | null>(null);
  const [docs, setDocs] = useState<RetrievalDoc[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [result, setResult] = useState<BenchResult | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [trigger, setTrigger] = useState<{ n: number; embed: boolean; key: string }>({ n: 0, embed: false, key: '' });
  const nonce = trigger.n;
  const [open, setOpen] = useState<Open | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [presetOpen, setPresetOpen] = useState<string | null | false>(false);
  const [measureOpen, setMeasureOpen] = useState(false);
  const presetSettingsButton = useRef<HTMLButtonElement>(null);
  const strategyTrigger = useRef<HTMLElement | null>(null);
  const returnAction = useRef<'measure' | 'edit' | null>(null);

  const [docsError, setDocsError] = useState('');
  useEffect(() => {
    if (!active) return;
    let current = true;
    setReady(false);
    setLoadError('');
    setDocsError('');
    void Promise.allSettled([getConfig(), listDocuments(), getSamples()]).then(([c, d, s]) => {
      if (!current) return;
      setConfig(c.status === 'fulfilled' ? c.value : null);
      setDocs(d.status === 'fulfilled' ? d.value : []);
      setSamples(s.status === 'fulfilled' ? s.value : []);
      if (d.status === 'rejected') setDocsError(errorText(d.reason));
      if (s.status === 'rejected') setLoadError(errorText(s.reason));
      setReady(true);
    });
    return () => { current = false; };
  }, [active, loadAttempt]);

  const sourceKey: SourceKey | null = useMemo(() => {
    const has = (key: string) => key.startsWith('sample:') ? samples.some(s => `sample:${s.id}` === key) : docs.some(d => `doc:${d.id}` === key);
    if (requestedSource) return has(requestedSource) ? requestedSource : null;
    if (bench.source && has(bench.source)) return bench.source;
    return samples[0] ? `sample:${samples[0].id}` as const : docs[0] ? `doc:${docs[0].id}` as const : null;
  }, [requestedSource, bench.source, samples, docs]);
  const isSample = !!sourceKey?.startsWith('sample:');
  const sourceId = sourceKey ? sourceKey.slice(sourceKey.indexOf(':') + 1) : '';
  const sample = isSample ? samples.find(s => s.id === sourceId) : undefined;
  const doc = !isSample ? docs.find(d => d.id === sourceId) : undefined;

  const chosen = useMemo(() => presets.filter(p => bench.selected.includes(p.id)).slice(0, MAX_SELECTED), [bench.selected, presets]);
  const maxParallel = config?.caps?.max_parallel_strategies ?? 1;
  const parallelism = Number.isInteger(bench.parallelism) ? Math.max(1, Math.min(maxParallel, bench.parallelism)) : 1;
  const limit = useMemo(() => { const caps = (config?.specs ?? []).map(s => s.max_tokens).filter(n => n > 0); return caps.length ? Math.min(...caps) : null; }, [config]);
  const runKey = sourceKey && chosen.length ? JSON.stringify({ sourceKey, chosen, limit, parallelism, updatedAt: doc?.updated_at ?? null }) : '';

  useEffect(() => {
    setOpen(null);
    setMeasureOpen(false);
    setPresetOpen(false);
    setSourceOpen(false);
    returnAction.current = null;
  }, [active, requestedSource]);

  const currentResult = runKey && result?.key === runKey ? result : null;
  const response = currentResult?.response ?? null;
  const running = active && ready && !!runKey && currentResult?.attempt !== nonce;
  const runError = running ? '' : currentResult?.error ?? '';

  /* 원문·전략이 바뀌면 잠깐 기다렸다가 다시 나눈다(서버 안에서만 처리, 외부 모델 호출 없음). */
  useEffect(() => {
    if (!active || !ready || !runKey) return;
    const { sourceKey: key, chosen: strategies, limit: cap, parallelism: workers } = JSON.parse(runKey) as { sourceKey: SourceKey; chosen: Preset[]; limit: number | null; parallelism: number };
    const id = key.slice(key.indexOf(':') + 1);
    const embed = trigger.embed && trigger.key === runKey;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void chunkSource(key.startsWith('sample:') ? { sample: id } : { doc_id: id }, strategies, cap, controller.signal, workers, embed)
        .then(response => { if (!controller.signal.aborted) setResult({ key: runKey, attempt: nonce, response, error: '' }); })
        .catch(error => {
          if (!controller.signal.aborted) setResult(previous => ({ key: runKey, attempt: nonce,
            response: previous?.key === runKey ? previous.response : null, error: errorText(error) }));
        });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [active, ready, runKey, nonce, trigger]);

  const changePresets = (next: Preset[]) => {
    setPresets(next); savePresets(next);
    setBench(prev => ({ ...prev, selected: prev.selected.filter(id => next.some(p => p.id === id)) }));
  };
  const toggleChosen = (id: string) => setBench(prev => prev.selected.includes(id) ? { ...prev, selected: prev.selected.filter(item => item !== id) }
    : prev.selected.length >= MAX_SELECTED ? prev : { ...prev, selected: [...prev.selected, id] });

  const columns: Column[] = useMemo(() => (response?.results ?? []).map(r => {
    const preset = presets.find(p => p.id === r.id);
    return { id: r.id, name: preset?.name ?? r.name ?? r.id, kind: r.kind ?? preset?.kind, params: r.params ?? preset?.params, result: r };
  }), [response, presets]);
  /* 설정 팝업에서 전략을 빼도 위에 떠 있는 상세 팝업은 마지막 결과로 유지한다. */
  const lastColumn = useRef<Column | null>(null);
  const openColumn = open ? columns.find(c => c.id === open.id) ?? (lastColumn.current?.id === open.id ? lastColumn.current : null) : null;
  if (openColumn) lastColumn.current = openColumn;

  const src = response?.source;
  const composition = src?.composition ?? sample?.composition ?? {};
  const refresh = () => setTrigger(t => ({ n: t.n + 1, embed: true, key: runKey }));
  const addPreset = () => {
    const next: Preset = { id: newPresetId(), name: `요소 인지 ${presets.length + 1}`, kind: 'element', params: defaultParams('element') };
    changePresets([...presets, next]);
    setBench(prev => prev.selected.length >= MAX_SELECTED ? prev : { ...prev, selected: [...prev.selected, next.id] });
    setPresetOpen(next.id);
  };
  const sourceName = src?.name ?? sample?.name ?? doc?.name ?? '원문 없음';
  const connections = (config?.connections ?? []).filter(c => c.configured);
  const pending = (response?.results ?? []).filter(r => r.pending);
  const pendingWindows = pending.reduce((sum, r) => sum + (r.pending?.missing ?? 0), 0);
  const emptyImages = (src?.elements ?? []).filter(el => el.kind === 'image' && el.empty);

  useEffect(() => {
    if (measureOpen || presetOpen !== false || !returnAction.current) return;
    const action = document.querySelector<HTMLElement>(`[aria-modal="true"] [data-strategy-action="${returnAction.current}"]`);
    (action ?? strategyTrigger.current)?.focus({ preventScroll: true });
    returnAction.current = null;
  }, [measureOpen, presetOpen, openColumn]);
  const empty = () => {
    if (!ready) return <div className="cb-empty" role="status"><LoaderCircle className="cb-spin" size={24} aria-hidden="true" /><b>문서를 불러오는 중입니다</b></div>;
    if (requestedSource && !sourceKey) {
      const failure = requestedSource.startsWith('doc:') ? docsError : loadError;
      return <div className="cb-empty" role="alert"><FileText size={24}/><b>선택한 원문을 불러올 수 없습니다</b>
        <p>{failure || '이 문서의 청킹 가능한 파싱 결과를 찾지 못했습니다.'}</p>
        <button className="button-secondary cb-btn" onClick={() => setLoadAttempt(n => n + 1)}>다시 확인</button>
        <button className="button-quiet cb-btn" onClick={() => setSourceOpen(true)}>다른 원문 선택</button></div>;
    }
    if (!sourceKey) return <div className="cb-empty" role={loadError ? 'alert' : undefined}>
      <span className="cb-empty-icon"><FileText size={23} aria-hidden="true" /></span><b>나눌 문서가 없습니다</b>
      <p>{loadError ? `예시 문서를 불러오지 못했습니다. ${loadError}` : '파싱이 끝난 실제 문서가 여기에 표시됩니다.'}</p>
      {loadError && <button type="button" className="button-secondary cb-btn" onClick={() => setLoadAttempt(n => n + 1)}>문서 다시 불러오기</button>}
    </div>;
    if (!chosen.length) return <div className="cb-empty"><span className="cb-empty-icon"><Scissors size={23} aria-hidden="true" /></span><b>비교할 전략이 없습니다</b>
      <p>하나 이상의 전략을 골라 같은 문서를 어떻게 나누는지 확인하세요.</p><button type="button" className="button-secondary cb-btn" onClick={() => setPresetOpen(null)}>비교할 전략 고르기</button>
    </div>;
    if (runError) return <div className="cb-empty" role="alert"><span className="cb-empty-icon is-error"><AlertCircle size={23} aria-hidden="true" /></span><b>문서를 나누지 못했습니다</b><p>{runError}</p>
      <button type="button" className="button-secondary cb-btn" onClick={refresh}>다시 나누기</button></div>;
    return <div className="cb-empty" role="status"><LoaderCircle className="cb-spin" size={24} aria-hidden="true" /><b>선택한 문서를 나누는 중입니다</b><p>{chosen.length}개 전략의 결과를 계산하고 있어요.</p></div>;
  };

  return <div className="cb-root">
    <section className="cb-bar" aria-label="청킹 원문 및 전략">
      <div className="cb-source">
        <span className="cb-source-icon"><FileText size={22} strokeWidth={1.75} aria-hidden="true" /></span>
        <div className="cb-source-content">
          <div className="cb-source-meta"><span className="cb-bar-label">원문</span>
            {sourceKey && (isSample ? <span className="ui-pill is-accent">예시 데이터</span> : (src?.is_stale ?? doc?.is_stale) ? <span className="ui-pill is-warn">이전 처리 결과</span> : <span className="ui-pill is-ok">실제 문서</span>)}
          </div>
          <button type="button" className="cb-srcbtn" aria-haspopup="dialog" aria-label={`원문: ${sourceName}`} disabled={!ready} onClick={() => setSourceOpen(true)}>
            <b>{sourceName}</b><ChevronDown size={17} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="cb-bar-actions">
        <button type="button" className="button-primary cb-btn" disabled={!runKey || running} onClick={refresh}>
          <RefreshCw size={16} className={running ? 'cb-spin' : ''} aria-hidden="true" /> {running ? '나누는 중' : pending.length ? '임베딩 계산하고 나누기' : '나누기'}
        </button>
      </div>
      {Object.values(composition).some(count => count > 0) && <div className="cb-composition"><CompositionBar composition={composition} /></div>}
    </section>

    <section className="cb-strategies" aria-labelledby="cb-settings-heading">
      <header><h2 id="cb-settings-heading">비교할 전략 <span>{chosen.length} / {MAX_SELECTED}개 선택</span></h2>
        <button ref={presetSettingsButton} type="button" className="button-secondary cb-btn cb-advanced" onClick={() => setPresetOpen(chosen[0]?.id ?? presets[0]?.id ?? null)}>
          <SlidersHorizontal size={15} aria-hidden="true"/>전략 설정</button></header>
      <ul className="cb-picks">{presets.map(preset => {
        const selected = bench.selected.includes(preset.id);
        return <li key={preset.id} className={selected ? 'is-on' : ''}>
          <button type="button" className="cb-pick" aria-label={preset.name + ' 비교 선택'} aria-pressed={selected}
            disabled={!selected && chosen.length >= MAX_SELECTED} onClick={() => toggleChosen(preset.id)}>
            <span className="cb-pick-check" aria-hidden="true"><Check size={12} strokeWidth={3}/></span>
            <span className="cb-pick-text"><b>{preset.name || '이름 없는 전략'}</b><small>{familyOf(preset.kind)} · {describeParams(preset.params)}</small></span>
          </button>
          <button type="button" className="cb-pick-edit" aria-label={preset.name + ' 전략 편집'} data-tip="설정 편집" onClick={() => setPresetOpen(preset.id)}><Pencil size={13}/></button>
        </li>;
      })}
        {presets.length < MAX_PRESETS && <li><button type="button" className="cb-pick-add" onClick={addPreset}><Plus size={15} aria-hidden="true"/>전략 추가</button></li>}
      </ul>
      {pending.length > 0 && !running && <div className="cb-embed-note" role="status"><Brain size={17} aria-hidden="true"/>
        <span><b>의미 기반 전략 {pending.length}개가 문장 임베딩을 기다립니다.</b> {pending[0].pending?.model} 모델로 문장 창 {fmtInt(pendingWindows)}개를 계산합니다. 위의 '임베딩 계산하고 나누기'를 누르면 계산하고, 이 PC에 저장해 다음부터는 바로 나눕니다.</span></div>}
    </section>

    <section className="cb-main" aria-label="청킹 벤치" aria-busy={running || !ready || undefined}>
      <Tabs<View> label="보기" value={ui.view} onChange={view => setUi({ view })} className="cb-tabs"
        items={[{ id: 'compare', label: '전략 비교' }, { id: 'elements', label: '원문 구성' }]}>
        {view => <>
          {columns.length > 0 && view === 'compare' && <>
            {runError ? <p className="cb-error" role="alert">이전 청킹 결과를 표시합니다. {runError}</p> : <p className="cb-table-note">전략을 선택하면 청크 내용과 원문에서 나뉜 위치를 볼 수 있습니다.</p>}
            <CompareTable columns={columns} elements={src?.elements ?? []} limit={limit} busy={running}
              onEdit={setPresetOpen} onEmbed={refresh} onOpen={id => { strategyTrigger.current = document.activeElement as HTMLElement; setOpen({ id, tab:'chunks', index:0 }); }} />
            {emptyImages.length > 0 && <p className="cb-foot"><Info size={16} aria-hidden="true" /><span>
              {emptyImages.map(el => el.page ? `${el.page}쪽` : el.label).join(', ')} 그림은 글자가 없어 어느 전략에도 담기지 않습니다(시각 모델 필요). 그림 칸에서는 문제로 세지 않았습니다.</span></p>}
          </>}
          {view === 'elements' && src && <ElementsView source={src} columns={columns} />}
          {(view === 'compare' ? !columns.length : !src) && empty()}
        </>}
      </Tabs>
    </section>

    {active && open && openColumn && src && !measureOpen && presetOpen === false && <StrategyModal source={src} column={openColumn} tab={open.tab} index={open.index}
      onTab={tab => setOpen(prev => prev && { ...prev, tab })} onIndex={index => setOpen(prev => prev && { ...prev, index })}
      onClose={() => { setOpen(null); requestAnimationFrame(() => strategyTrigger.current?.focus()); }} onEdit={() => { returnAction.current = 'edit'; setPresetOpen(openColumn.id); }}
      measure={<span data-tip={connections.length ? undefined : '연결된 임베딩 모델이 없습니다'}>
        <button type="button" className="button-secondary cb-btn" disabled={!connections.length || !openColumn.result.chunks.length} data-strategy-action="measure" onClick={() => { returnAction.current = 'measure'; setMeasureOpen(true); }}><Ruler size={14} /> 토큰 실측</button>
      </span>} />}
    {active && measureOpen && openColumn && <TokenModal column={openColumn} connections={connections} specs={config?.specs ?? []} conn={bench.conn} model={bench.model}
      onPick={(conn, model) => setBench(prev => ({ ...prev, conn, model }))} onClose={() => setMeasureOpen(false)} />}
    {active && presetOpen !== false && <PresetModal returnToDetail={!!open} presets={presets} selected={bench.selected} initial={presetOpen} onChange={changePresets} onToggle={toggleChosen}
      connections={config?.connections ?? []} parallel={{ value: parallelism, max: maxParallel, info: ready && maxParallel === 1 ? (config ? '현재 서버는 순차 실행만 지원' : '서버 설정을 확인할 수 없어 순차 실행') : '', onChange: value => setBench(prev => ({ ...prev, parallelism: value })) }}
      onReset={() => { changePresets(DEFAULT_PRESETS); setBench(prev => ({ ...prev, selected: DEFAULT_SELECTED })); }} onClose={() => {
        const directEdit = !!presetOpen && !open;
        setPresetOpen(false);
        if (directEdit) requestAnimationFrame(() => {
          if (document.activeElement === document.body) presetSettingsButton.current?.focus();
        });
      }} />}
    {active && sourceOpen && <SourceModal docsError={docsError} onRetry={() => setLoadAttempt(n => n + 1)} samples={samples} docs={docs} current={sourceKey} currentComposition={src?.composition ?? null}
      onPick={key => { setBench(prev => ({ ...prev, source: key })); setSourceOpen(false); onSourceChange?.(key); }} onClose={() => setSourceOpen(false)} />}
  </div>;
}

