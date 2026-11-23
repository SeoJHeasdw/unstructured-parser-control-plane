import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, Circle, ChevronDown, FileText, Info, LoaderCircle, RefreshCw, Ruler, Scissors, SlidersHorizontal } from 'lucide-react';
import { chunkSource, getConfig, getSamples, listDocuments } from './api/retrieval';
import type { ChunkResponse, Preset, RetrievalConfig, RetrievalDoc, Sample } from './api/retrieval';
import { Tabs } from './ui';
import { ChunkSizingFields } from './retrieval/ChunkSizingFields';
import type { Column } from './retrieval/chunk-board';
import { CompareTable, CompositionBar } from './retrieval/chunk-compare';
import { StrategyModal, TokenModal } from './retrieval/chunk-detail';
import type { StrategyTab } from './retrieval/chunk-detail';
import { ElementsView } from './retrieval/chunk-elements';
import { MAX_SELECTED, PresetModal } from './retrieval/chunk-presets';
import { SourceModal } from './retrieval/chunk-source';
import type { SourceKey } from './retrieval/chunk-source';
import { DEFAULT_PRESETS, DEFAULT_SELECTED, STORE, errorText, loadPresets, savePresets, usePersistent } from './retrieval/shared';
import './retrieval.css';

/**
 * 청킹 벤치: 비정형 문서가 어떤 요소(본문·목록·표·그림·캡션·반복 머리말)로 이뤄졌고,
 * 전략마다 그 요소들이 어떤 청크가 되는지 본다. 원문과 전략 선택, 비교 결과를 한 화면에서 다룬다.
 */
type Bench = { source: SourceKey | ''; selected: string[]; conn: string; model: string; parallelism: number };
type View = 'compare' | 'elements';
type Open = { id: string; tab: StrategyTab; index: number };
type BenchResult = { key: string; attempt: number; response: ChunkResponse | null; error: string };

export default function ChunkBench({ active, requestedSource, onSourceChange }: {
  active: boolean; requestedSource?: SourceKey; onSourceChange?: (key: SourceKey) => void;
}) {
  const [bench, setBench] = usePersistent<Bench>(STORE.bench, { source: 'sample:report', selected: DEFAULT_SELECTED, conn: '', model: '', parallelism: 1 });
  const [ui, setUi] = usePersistent<{ view: View }>(STORE.benchUi, { view: 'compare' });
  const [editingPreset, setEditingPreset] = useState('');
  const [presets, setPresets] = useState<Preset[]>(loadPresets);
  const [config, setConfig] = useState<RetrievalConfig | null>(null);
  const [docs, setDocs] = useState<RetrievalDoc[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [result, setResult] = useState<BenchResult | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [nonce, setNonce] = useState(0);
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
  const quickPreset = presets.find(p => p.id === editingPreset) ?? chosen[0] ?? presets[0];
  const maxParallel = config?.caps?.max_parallel_strategies ?? 1;
  const parallelism = Number.isInteger(bench.parallelism) ? Math.max(1, Math.min(maxParallel, bench.parallelism)) : 1;
  /* 한도 초과는 알려진 모델 가운데 가장 작은 입력 한도로 센다. */
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
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void chunkSource(key.startsWith('sample:') ? { sample: id } : { doc_id: id }, strategies, cap, controller.signal, workers)
        .then(response => { if (!controller.signal.aborted) setResult({ key: runKey, attempt: nonce, response, error: '' }); })
        .catch(error => {
          if (!controller.signal.aborted) setResult(previous => ({ key: runKey, attempt: nonce,
            response: previous?.key === runKey ? previous.response : null, error: errorText(error) }));
        });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [active, ready, runKey, nonce]);

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
  const refresh = () => setNonce(n => n + 1);
  const sourceName = src?.name ?? sample?.name ?? doc?.name ?? '원문 없음';
  const connections = (config?.connections ?? []).filter(c => c.configured);
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
          <RefreshCw size={16} className={running ? 'cb-spin' : ''} aria-hidden="true" /> {running ? '나누는 중' : '나누기'}
        </button>
      </div>
      {Object.values(composition).some(count => count > 0) && <div className="cb-composition"><CompositionBar composition={composition} /></div>}
    </section>

    <section className="cb-strategies" aria-labelledby="cb-settings-heading">
      <header><h2 id="cb-settings-heading">청킹 설정</h2><div className="cb-run-options">
        {ready && maxParallel === 1 && <small id="cb-parallel-info">{config ? '현재 서버는 순차 실행만 지원' : '서버 설정을 확인할 수 없어 순차 실행'}</small>}
        <label className="cb-parallel">전략 동시 실행
        <select aria-describedby={ready && maxParallel === 1 ? 'cb-parallel-info' : undefined} value={parallelism} disabled={maxParallel <= 1} onChange={e => setBench(prev => ({...prev, parallelism:Number(e.target.value)}))}>
          {Array.from({length:maxParallel}, (_, i) => <option key={i} value={i + 1}>{i === 0 ? '1개 · 순차' : '최대 ' + (i + 1) + '개 · 병렬'}</option>)}
        </select></label></div></header>
      {quickPreset && <fieldset className="cb-sizing cb-quick-sizing" aria-label="전략별 분할 설정">
        <label className="cb-edit-target"><span>편집할 전략</span><select value={quickPreset.id} onChange={e => setEditingPreset(e.target.value)}>
          {presets.map(p => <option value={p.id} key={p.id}>{p.name || '이름 없는 전략'}</option>)}</select></label>
        <ChunkSizingFields key={quickPreset.id} preset={quickPreset} onChange={params => changePresets(presets.map(p => p.id === quickPreset.id ? {...p, params} : p))}/>
        <button ref={presetSettingsButton} type="button" className="button-secondary cb-btn cb-advanced" title="표·그림·캡션 처리 및 전략 관리"
          onClick={() => setPresetOpen(quickPreset.id)}><SlidersHorizontal size={15} aria-hidden="true"/>전략 설정</button>
      </fieldset>}
      <p className="cb-choice-label">비교할 전략 <span>{chosen.length} / {MAX_SELECTED}개 선택</span></p>
      <div>{presets.map(preset => {
        const selected = bench.selected.includes(preset.id);
        const Icon = selected ? Check : Circle;
        return <button key={preset.id} type="button" aria-label={preset.name + ' 비교 선택'} aria-pressed={selected}
          disabled={!selected && chosen.length >= MAX_SELECTED} onClick={() => toggleChosen(preset.id)}>
          <Icon size={14} aria-hidden="true"/>{preset.name || '이름 없는 전략'}</button>;
      })}</div>
    </section>

    <section className="cb-main" aria-label="청킹 벤치" aria-busy={running || !ready || undefined}>
      <Tabs<View> label="보기" value={ui.view} onChange={view => setUi({ view })} className="cb-tabs"
        items={[{ id: 'compare', label: '전략 비교' }, { id: 'elements', label: '원문 구성' }]}>
        {view => <>
          {columns.length > 0 && view === 'compare' && <>
            {runError ? <p className="cb-error" role="alert">이전 청킹 결과를 표시합니다. {runError}</p> : <p className="cb-table-note">전략을 선택하면 청크 내용과 원문에서 나뉜 위치를 볼 수 있습니다.</p>}
            <CompareTable columns={columns} elements={src?.elements ?? []} limit={limit} busy={running}
              onEdit={setPresetOpen} onOpen={id => { strategyTrigger.current = document.activeElement as HTMLElement; setOpen({ id, tab:'chunks', index:0 }); }} />
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
      measure={<span title={connections.length ? undefined : '연결된 임베딩 모델이 없습니다'}>
        <button type="button" className="button-secondary cb-btn" disabled={!connections.length || !openColumn.result.chunks.length} data-strategy-action="measure" onClick={() => { returnAction.current = 'measure'; setMeasureOpen(true); }}><Ruler size={14} /> 토큰 실측</button>
      </span>} />}
    {active && measureOpen && openColumn && <TokenModal column={openColumn} connections={connections} specs={config?.specs ?? []} conn={bench.conn} model={bench.model}
      onPick={(conn, model) => setBench(prev => ({ ...prev, conn, model }))} onClose={() => setMeasureOpen(false)} />}
    {active && presetOpen !== false && <PresetModal returnToDetail={!!open} presets={presets} selected={bench.selected} initial={presetOpen} onChange={changePresets} onToggle={toggleChosen}
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

