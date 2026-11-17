import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, FileText, RefreshCw, Ruler, SlidersHorizontal } from 'lucide-react';
import { chunkSource, getConfig, getSamples, listDocuments } from './api/retrieval';
import type { ChunkResponse, Preset, RetrievalConfig, RetrievalDoc, Sample } from './api/retrieval';
import { Tabs } from './ui';
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
 * 전략마다 그 요소들이 어떤 청크가 되는지 본다. 첫 화면은 비교 표 하나, 세부는 팝업.
 */
type Bench = { source: SourceKey | ''; selected: string[]; conn: string; model: string };
type View = 'compare' | 'elements';
type Open = { id: string; tab: StrategyTab; index: number };

export default function ChunkBench({ active }: { active: boolean }) {
  const [bench, setBench] = usePersistent<Bench>(STORE.bench, { source: 'sample:report', selected: DEFAULT_SELECTED, conn: '', model: '' });
  const [ui, setUi] = usePersistent<{ view: View }>(STORE.benchUi, { view: 'compare' });
  const [presets, setPresets] = useState<Preset[]>(loadPresets);
  const [config, setConfig] = useState<RetrievalConfig | null>(null);
  const [docs, setDocs] = useState<RetrievalDoc[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [response, setResponse] = useState<ChunkResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState('');
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState<Open | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [presetOpen, setPresetOpen] = useState<string | null | false>(false);
  const [measureOpen, setMeasureOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /* 처음 열 때 설정·문서·예시 목록을 읽고, 다시 열 때는 문서 목록만 새로 읽는다. */
  const loadStarted = useRef(false);
  useEffect(() => {
    if (!active) return;
    if (loadStarted.current) { listDocuments().then(setDocs).catch(() => undefined); return; }
    loadStarted.current = true;
    void Promise.allSettled([getConfig(), listDocuments(), getSamples()]).then(([c, d, s]) => {
      if (c.status === 'fulfilled') setConfig(c.value);
      if (d.status === 'fulfilled') setDocs(d.value);
      if (s.status === 'fulfilled') setSamples(s.value);
      else setLoadError(errorText(s.reason));
      setReady(true);
    });
  }, [active]);

  /* 고른 원문이 없어졌으면 첫 예시 문서, 그다음 첫 실제 문서로. */
  const sourceKey: SourceKey | null = useMemo(() => {
    const has = (key: string) => key.startsWith('sample:') ? samples.some(s => `sample:${s.id}` === key) : docs.some(d => `doc:${d.id}` === key);
    if (bench.source && has(bench.source)) return bench.source as SourceKey;
    return samples[0] ? `sample:${samples[0].id}` as const : docs[0] ? `doc:${docs[0].id}` as const : null;
  }, [bench.source, samples, docs]);
  const isSample = !!sourceKey?.startsWith('sample:');
  const sourceId = sourceKey ? sourceKey.slice(sourceKey.indexOf(':') + 1) : '';
  const sample = isSample ? samples.find(s => s.id === sourceId) : undefined;
  const doc = !isSample ? docs.find(d => d.id === sourceId) : undefined;

  const chosen = useMemo(() => presets.filter(p => bench.selected.includes(p.id)).slice(0, MAX_SELECTED), [bench.selected, presets]);
  /* 한도 초과는 알려진 모델 가운데 가장 작은 입력 한도로 센다. */
  const limit = useMemo(() => { const caps = (config?.specs ?? []).map(s => s.max_tokens).filter(n => n > 0); return caps.length ? Math.min(...caps) : null; }, [config]);
  const runKey = sourceKey && chosen.length ? JSON.stringify({ sourceKey, chosen, limit }) : '';

  /* 원문·전략이 바뀌면 잠깐 기다렸다가 다시 나눈다(서버 안에서만 처리, 외부 모델 호출 없음). */
  useEffect(() => {
    if (!active || !ready || !runKey) return;
    const { sourceKey: key, chosen: strategies, limit: cap } = JSON.parse(runKey) as { sourceKey: SourceKey; chosen: Preset[]; limit: number | null };
    const id = key.slice(key.indexOf(':') + 1);
    const timer = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setRunning(true); setRunError('');
      chunkSource(key.startsWith('sample:') ? { sample: id } : { doc_id: id }, strategies, cap, controller.signal)
        .then(result => { if (!controller.signal.aborted) setResponse(result); })
        .catch(error => { if (!controller.signal.aborted) setRunError(errorText(error)); })
        .finally(() => { if (abortRef.current === controller) setRunning(false); });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [active, ready, runKey, nonce]);
  useEffect(() => () => abortRef.current?.abort(), []);

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
  const sourceName = src?.name ?? sample?.name ?? doc?.name ?? '원문 없음';
  const connections = (config?.connections ?? []).filter(c => c.configured);
  const emptyImages = (src?.elements ?? []).filter(el => el.kind === 'image' && el.empty);

  const compare = () => {
    if (!ready) return <div className="ui-empty">불러오는 중…</div>;
    if (!sourceKey) return <div className="ui-empty" role={loadError ? 'alert' : undefined}><b>나눌 문서가 없습니다</b>{loadError ? `예시 문서를 불러오지 못했습니다. ${loadError}` : '처리가 끝난 문서가 없습니다.'}</div>;
    if (!chosen.length) return <div className="ui-empty"><b>비교할 전략이 없습니다</b><button type="button" className="button-secondary cb-btn" onClick={() => setPresetOpen(null)}>전략 설정</button></div>;
    if (!columns.length) return runError ? <div className="ui-empty" role="alert"><b>나누지 못했습니다</b>{runError}</div> : <div className="ui-empty">나누는 중…</div>;
    return <>
      {runError && <p className="cb-error" role="alert">{runError}</p>}
      <CompareTable columns={columns} elements={src?.elements ?? []} limit={limit} busy={running}
        onOpen={id => setOpen({ id, tab: 'chunks', index: 0 })} />
      {emptyImages.length > 0 && <p className="cb-foot">
        {emptyImages.map(el => el.page ? `${el.page}쪽` : el.label).join(', ')} 그림은 글자가 없어 어느 전략에도 담기지 않습니다(시각 모델 필요). 그림 칸에서는 문제로 세지 않았습니다.</p>}
    </>;
  };

  return <div className="cb-root">
    <div className="cb-bar">
      <span className="cb-bar-label">원문</span>
      <button type="button" className="cb-srcbtn" aria-haspopup="dialog" aria-label={`원문: ${sourceName}`} disabled={!ready} onClick={() => setSourceOpen(true)}>
        <FileText size={15} aria-hidden="true" /><b>{sourceName}</b><ChevronDown size={15} aria-hidden="true" />
      </button>
      {sourceKey && (isSample ? <span className="ui-pill">예시 데이터</span> : (src?.is_stale ?? doc?.is_stale) ? <span className="ui-pill is-warn">이전 처리 결과</span> : null)}
      <CompositionBar composition={composition} />
      <span className="cb-bar-gap" />
      <button type="button" className="button-secondary cb-btn" onClick={() => setPresetOpen(null)}><SlidersHorizontal size={14} /> 전략 설정</button>
      <button type="button" className="button-secondary cb-btn" disabled={!runKey || running} onClick={() => setNonce(n => n + 1)}>
        <RefreshCw size={14} className={running ? 'cb-spin' : ''} /> {running ? '나누는 중' : '나누기'}
      </button>
    </div>

    <section className="cb-main" aria-label="청킹 벤치" aria-busy={running || !ready || undefined}>
      <Tabs<View> label="보기" value={ui.view} onChange={view => setUi({ view })} className="cb-tabs"
        items={[{ id: 'compare', label: '전략 비교' }, { id: 'elements', label: '원문 구성' }]}>
        {view => view === 'compare' ? compare()
          : src ? <ElementsView source={src} columns={columns} /> : <div className="ui-empty">{ready ? '나눈 결과가 없습니다.' : '불러오는 중…'}</div>}
      </Tabs>
    </section>

    {open && openColumn && src && <StrategyModal source={src} column={openColumn} tab={open.tab} index={open.index}
      onTab={tab => setOpen(prev => prev && { ...prev, tab })} onIndex={index => setOpen(prev => prev && { ...prev, index })}
      onClose={() => setOpen(null)} onEdit={() => setPresetOpen(openColumn.id)}
      measure={<span title={connections.length ? undefined : '연결된 임베딩 모델이 없습니다'}>
        <button type="button" className="button-secondary cb-btn" disabled={!connections.length || !openColumn.result.chunks.length} onClick={() => setMeasureOpen(true)}><Ruler size={14} /> 토큰 실측</button>
      </span>} />}
    {measureOpen && openColumn && <TokenModal column={openColumn} connections={connections} specs={config?.specs ?? []} conn={bench.conn} model={bench.model}
      onPick={(conn, model) => setBench(prev => ({ ...prev, conn, model }))} onClose={() => setMeasureOpen(false)} />}
    {presetOpen !== false && <PresetModal presets={presets} selected={bench.selected} initial={presetOpen} onChange={changePresets} onToggle={toggleChosen}
      onReset={() => { changePresets(DEFAULT_PRESETS); setBench(prev => ({ ...prev, selected: DEFAULT_SELECTED })); }} onClose={() => setPresetOpen(false)} />}
    {sourceOpen && <SourceModal samples={samples} docs={docs} current={sourceKey} currentComposition={src?.composition ?? null}
      onPick={key => { setBench(prev => ({ ...prev, source: key })); setSourceOpen(false); }} onClose={() => setSourceOpen(false)} />}
  </div>;
}

