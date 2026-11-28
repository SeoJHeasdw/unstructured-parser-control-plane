import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, BookOpenText, Database, Layers, LayoutGrid, LoaderCircle, LockKeyhole, PlugZap, RefreshCw, TriangleAlert } from 'lucide-react';
import { checkMilvus, getCollection, getSources, getTree, type CheckResult, type CollectionDetail, type SourceKey, type SourcesInfo, type Tree } from './api/vectordb';
import { Tabs, type TabItem } from './ui';
import { fmtCount, loadLabel, metricHint, readStored, useFloating, useStored, writeStored } from './vectordb/ui';
import VdbTree from './vectordb/VdbTree';
import ChunkBrowser from './vectordb/ChunkBrowser';
import SchemaView from './vectordb/SchemaView';
import { ChunkModal, type PanelState } from './vectordb/VdbPanel';
import Overview from './vectordb/Overview';
import PartitionModal, { type PartRef } from './vectordb/PartitionModal';
import './vectordb.css';

export default function VectorDbWorkspace({ active }: { active: boolean }) {
  const [started, setStarted] = useState(active);
  useEffect(() => { if (active) setStarted(true); }, [active]);
  return started ? <VectorDbScreen active={active} /> : <div className="vdb-root" />;
}

type Selection = { db: string; collection: string };
type Page = 'overview' | 'collections';
type Tab = 'chunks' | 'schema';
type Tip = ReturnType<typeof useFloating>;
const PAGES: TabItem<Page>[] = [
  { id: 'overview', label: <><LayoutGrid size={16} aria-hidden="true" />개요</> },
  { id: 'collections', label: <><Layers size={16} aria-hidden="true" />컬렉션</> },
];
const TABS: TabItem<Tab>[] = [{ id: 'chunks', label: '청크' }, { id: 'schema', label: '스키마·인덱스' }];
const SUMMARY: { key: keyof Tree['totals']; label: string; unit: string }[] = [
  { key: 'databases', label: '데이터베이스', unit: '개' },
  { key: 'collections', label: '컬렉션', unit: '개' },
  { key: 'partitions', label: '파티션', unit: '개' },
  { key: 'rows', label: '청크', unit: '건' },
];

function firstCollection(tree: Tree, stored: string): Selection | null {
  const all = tree.databases.flatMap(db => db.collections.map(c => ({ db: db.name, collection: c.name, rows: c.row_count ?? 0 })));
  const pick = all.find(c => `${c.db}/${c.collection}` === stored) ?? all.find(c => c.rows > 0) ?? all[0];
  return pick ? { db: pick.db, collection: pick.collection } : null;
}

function VectorDbScreen({ active }: { active: boolean }) {
  const [info, setInfo] = useState<SourcesInfo | null>(null);
  const [infoError, setInfoError] = useState('');
  const [infoTry, setInfoTry] = useState(0);
  const [source, setSource] = useState<SourceKey | null>(null);
  const [fallback, setFallback] = useState('');
  const [paused, setPaused] = useState(false);
  const [tree, setTree] = useState<Tree | null>(null);
  const [treeError, setTreeError] = useState('');
  const [treeBusy, setTreeBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [partition, setPartition] = useState<string | null>(null);
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [textField, setTextField] = useState<string | null>(null);
  const [page, setPage] = useStored<Page>('page', 'overview');
  const [tab, setTab] = useStored<Tab>('tab', 'chunks');
  const [history, setHistory] = useState<PanelState[]>([]);
  const [openPart, setOpenPart] = useState<PartRef | null>(null);
  const tip = useFloating();

  useEffect(() => {
    let alive = true;
    setInfoError('');
    getSources().then(result => {
      if (!alive) return;
      setInfo(result);
      const pick: SourceKey = result.sources.some(s => s.key === result.default && s.available) ? result.default : 'example';
      setPaused(!!result.milvus.unreachable);
      setFallback(result.milvus.unreachable ? result.milvus.unreachable.error : '');
      setSource(result.milvus.unreachable ? 'milvus' : pick);
    }).catch((err: Error) => { if (alive) setInfoError(err.message); });
    return () => { alive = false; };
  }, [infoTry]);

  useEffect(() => {
    if (!source || paused) return;
    let alive = true;
    setTreeError('');
    setTreeBusy(true);
    getTree(source).then(result => {
      if (!alive) return;
      setTree(result);
      setSelection(current => {
        const keep = current && result.databases.some(db => db.name === current.db && db.collections.some(c => c.name === current.collection));
        return keep ? current : firstCollection(result, readStored<string>(`sel.${source}`, ''));
      });
    }).catch((err: Error) => {
      if (!alive) return;
      setTreeError(err.message);
    }).finally(() => { if (alive) setTreeBusy(false); });
    return () => { alive = false; };
  }, [source, reload, paused]);

  useEffect(() => {
    if (!source || !selection) return;
    let alive = true;
    setDetailError('');
    getCollection(source, selection.db, selection.collection)
      .then(result => { if (alive) setDetail(result); })
      .catch((err: Error) => { if (alive) setDetailError(err.message); });
    return () => { alive = false; };
  }, [source, selection, reload]);

  // 다른 작업 탭으로 가면 열린 팝업을 닫는다(팝업은 화면 밖 body에 뜬다).
  useEffect(() => { if (!active) { setOpenPart(null); setHistory([]); } }, [active]);

  const select = (db: string, collection: string, part: string | null) => {
    if (selection?.db !== db || selection.collection !== collection) {
      setSelection({ db, collection }); setDetail(null); setTextField(null); setHistory([]);
      if (source) writeStored(`sel.${source}`, `${db}/${collection}`);
    }
    setPartition(part);
    if (part) setTab('chunks');
  };
  const switchSource = (next: SourceKey) => {
    if (next === source) return;
    setPaused(false); setTreeError(''); setFallback('');
    setSource(next); setTree(null); setSelection(null); setPartition(null); setDetail(null); setTextField(null); setHistory([]); setOpenPart(null);
  };
  const navigate = useCallback((next: PanelState) => setHistory(current => [...current, next]), []);
  const openChunk = useCallback((pk: string) => setHistory(current => {
    const top = current[current.length - 1];
    return top?.mode === 'chunk' && top.pk === pk ? current : [...current, { mode: 'chunk', pk }];
  }), []);
  const back = useCallback(() => setHistory(current => current.slice(0, -1)), []);
  const close = useCallback(() => setHistory([]), []);
  const retry = () => setReload(n => n + 1);
  const top = history[history.length - 1] ?? null;
  const shown = detail && selection && detail.db === selection.db && detail.name === selection.collection ? detail : null;

  if (infoError) return <div className="vdb-root"><Problem title="데이터 출처를 확인할 수 없습니다" message={infoError} onRetry={() => setInfoTry(n => n + 1)} /></div>;
  if (!info || !source) return <div className="vdb-root"><Loading label="벡터 DB 정보를 불러오는 중" /></div>;
  const collections = (loadedTree: Tree) => <div className="vdb-main">
    <nav className="panel vdb-side" aria-label="컬렉션 목록">
      <VdbTree key={source} source={source} tree={loadedTree} selected={selection} partition={partition} onSelect={select} />
    </nav>
    <section className="panel vdb-center" aria-label="컬렉션">
      {!selection ? <div className="vdb-empty is-page"><Layers size={24} aria-hidden="true" /><b>표시할 컬렉션이 없습니다</b><span>현재 데이터 출처의 데이터베이스 구성을 확인하세요.</span><button type="button" className="button-secondary" onClick={() => setPage('overview')}>개요 보기 <ArrowRight size={15} aria-hidden="true" /></button></div>
        : detailError ? <Problem title="컬렉션을 읽을 수 없습니다" message={detailError} onRetry={retry} />
          : !shown ? <Loading label="컬렉션 정보를 불러오는 중" />
            : <>
              <CollectionHead detail={shown} tip={tip} onRead={() => navigate({ mode: 'document', field: null, value: null })} />
              <Tabs<Tab> items={TABS} value={tab} onChange={setTab} label="컬렉션 보기" className="vdb-tabs">
                {current => current === 'chunks'
                  ? <ChunkBrowser key={`${source}|${shown.db}|${shown.name}`} source={source} detail={shown} textField={textField} onTextField={setTextField}
                    partition={partition} onPartition={setPartition} onOpen={openChunk} activePk={top?.mode === 'chunk' ? top.pk : null} />
                  : <SchemaView detail={shown} />}
              </Tabs>
            </>}
    </section>
  </div>;

  return <div className="vdb-root">
    <SourcePanel info={info} source={source} fallback={fallback} tree={tree} busy={treeBusy} stale={!!treeError} tip={tip} onSource={switchSource} onRefresh={retry} />
    <div className="vdb-shell">
      <Tabs<Page> items={PAGES} value={page} onChange={setPage} label="벡터 DB 보기" className="vdb-pages">
        {current => (treeError || paused) ? <div><Problem title="컬렉션 목록을 읽을 수 없습니다" message={treeError || fallback} onRetry={() => { setPaused(false); retry(); }} />
          {source === 'milvus' && <button className="button-secondary" onClick={() => switchSource('example')}>예시 보기</button>}</div>
          : !tree ? <Loading label="컬렉션 목록을 불러오는 중" />
            : current === 'overview' ? <Overview tree={tree} onOpen={setOpenPart} onBrowse={() => setPage('collections')} /> : collections(tree)}
      </Tabs>
    </div>
    {openPart && active && <PartitionModal key={`${source}|${openPart.db}|${openPart.collection}|${openPart.partition}`} source={source} part={openPart} onClose={() => setOpenPart(null)} />}
    {shown && active && <ChunkModal stack={history} onBack={back} onClose={close} onNavigate={navigate} source={source} detail={shown} textField={textField} />}
    {tip.layer}
  </div>;
}

function SourcePanel({ info, source, fallback, tree, busy, stale, tip, onSource, onRefresh }: {
  info: SourcesInfo; source: SourceKey; fallback: string; tree: Tree | null; busy: boolean; stale: boolean; tip: Tip;
  onSource: (next: SourceKey) => void; onRefresh: () => void;
}) {
  const milvus = info.milvus;
  const example = source === 'example';
  return <section className="vdb-source" aria-label="데이터 출처와 현황">
    <div className="vdb-source-head">
      <span className="vdb-source-icon"><Database size={23} strokeWidth={1.7} aria-hidden="true" /></span>
      <div className="vdb-source-copy">
        <div className="vdb-source-title">
          <h2>{example ? (fallback ? '예시 데이터 · Milvus 연결 실패' : '예시 데이터') : 'Milvus 데이터'}</h2>
          <span className="ui-pill vdb-readonly"><LockKeyhole size={12} aria-hidden="true" />읽기 전용</span>
        </div>
        <p>{example ? (milvus.configured ? '합성 컬렉션으로 파티션과 청크를 탐색할 수 있습니다.' : 'Milvus 주소를 설정하면 실제 컬렉션을 볼 수 있습니다. 현재는 합성 컬렉션을 표시합니다.')
          : <>기본 데이터베이스 <code>{milvus.db}</code> · 연결된 컬렉션을 조회합니다.</>}</p>
      </div>
      <div className="vdb-source-controls">
        {milvus.configured && <div className="vdb-seg" role="group" aria-label="데이터 출처">
          {info.sources.map(item => <button key={item.key} type="button" aria-pressed={source === item.key} disabled={!item.available} onClick={() => onSource(item.key)}>{item.label}</button>)}
        </div>}
        <button type="button" className="button-secondary vdb-refresh" aria-label="다시 불러오기" onClick={onRefresh} disabled={busy}>
          <RefreshCw size={16} className={busy ? 'vdb-spin' : undefined} aria-hidden="true" /> 새로고침
        </button>
      </div>
    </div>
    <div className="vdb-source-foot">
      <MilvusControl info={info} tip={tip} />
      {stale && tree && <span className="ui-pill is-warn" role="status">새로고침 실패 · 이전 집계</span>}
      {fallback && example && <details className="vdb-source-details"><summary>연결 오류 상세</summary><p>{fallback}</p></details>}
      {!milvus.configured && <details className="vdb-source-details"><summary>연결 설정</summary><p>서버의 <code>.env</code>에 <code>MILVUS_URI</code>와 필요한 경우 <code>MILVUS_TOKEN</code>, <code>MILVUS_DB</code>를 설정한 뒤 서버를 다시 시작하세요.</p></details>}
    </div>
    <dl className="vdb-summary" aria-label="데이터 출처 집계" aria-busy={busy}>
      {SUMMARY.map(({ key, label, unit }) => <div key={key}><dt>{label}</dt><dd>{tree ? <>{fmtCount(tree.totals[key])}<small>{unit}</small></> : '—'}</dd></div>)}
    </dl>
    {!!tree?.warnings.length && <details className="vdb-warnings">
      <summary><TriangleAlert size={16} aria-hidden="true" /> 일부 정보를 읽지 못했습니다 <b className="ui-pill is-warn">{tree.warnings.length}건</b></summary>
      <ul>{tree.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
    </details>}
  </section>;
}

function CollectionHead({ detail, tip, onRead }: { detail: CollectionDetail; tip: Tip; onRead: () => void }) {
  const vector = detail.vector_fields[0];
  const loaded = detail.load_state === 'LoadStateLoaded';
  const emb = detail.embedding;
  const partitions = detail.partitions_num ?? detail.partitions.length;
  return <header className="vdb-head">
    <div className="vdb-head-title">
      <span className="vdb-head-icon"><Layers size={19} strokeWidth={1.8} aria-hidden="true" /></span>
      <div><span className="vdb-head-db">{detail.db}</span><h2>{detail.name}</h2></div>
    </div>
    <div className="vdb-chips" aria-label="컬렉션 요약">
      <span className="vdb-chip" tabIndex={0} {...tip.bind('h-rows', () => <><b>청크 {fmtCount(detail.row_count)}개</b><span>파티션 {fmtCount(partitions)}개{detail.shards ? ` · 샤드 ${detail.shards}개` : ''}</span></>)}>
        <b>{fmtCount(detail.row_count)}</b>행
      </span>
      {vector && <span className="vdb-chip" tabIndex={0}
        {...tip.bind('h-dim', () => <><b>{vector.name} · {vector.dim ?? '—'}차원</b><span>{emb.model ? `임베딩 모델 ${emb.model}` : '임베딩 모델 기록 없음'}</span>{emb.dim_mismatch && <span className="is-error">기록된 차원 {emb.recorded_dim}과 다릅니다.</span>}</>)}>
        <b>{vector.dim ?? '—'}</b>d{emb.dim_mismatch && <TriangleAlert size={11} className="vdb-ti-warn" aria-label="차원 기록 불일치" />}
      </span>}
      {vector && <span className="vdb-chip" tabIndex={0} {...tip.bind('h-metric', () => <><b>{vector.index_type ?? '인덱스 없음'}</b><span>{metricHint(vector.metric, !['L2', 'HAMMING', 'JACCARD'].includes(vector.metric ?? ''))}</span></>)}>
        {vector.metric ?? '측정 방식 미확인'}
      </span>}
      <span className={`vdb-chip is-load ${loaded ? 'is-ok' : 'is-warn'}`} tabIndex={0}
        {...tip.bind('h-load', () => <><b>{loadLabel(detail.load_state)}</b><span>{loaded ? '메모리에 올라가 있어 바로 검색할 수 있습니다.' : '메모리에 올라가 있지 않아 조회·검색이 제한될 수 있습니다.'}</span></>)}>
        <i aria-hidden />{loadLabel(detail.load_state)}{detail.load_progress !== null && detail.load_progress < 100 ? ` ${detail.load_progress}%` : ''}
      </span>
    </div>
    <span className="vdb-toolbar-gap" />
    <button type="button" className="button-quiet vdb-head-read" onClick={onRead}><BookOpenText size={16} aria-hidden="true" /> 문서로 다시 읽기</button>
  </header>;
}

function MilvusControl({ info, tip }: { info: SourcesInfo; tip: Tip }) {
  const [result, setResult] = useState<CheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const milvus = info.milvus;
  if (!milvus.configured) return <span className="vdb-conn is-off"><i aria-hidden="true" />Milvus 미연결</span>;
  const run = () => {
    setChecking(true);
    checkMilvus().then(setResult).catch((err: Error) => setResult({ ok: false, status: null, latency_ms: 0, error: err.message })).finally(() => setChecking(false));
  };
  return <span className={`vdb-conn ${!checking && result ? (result.ok ? 'is-ok' : 'is-bad') : ''}`}>
    <span className="vdb-conn-label" tabIndex={0} role="status" {...tip.bind('conn', () => <><b>{milvus.uri}</b><span>데이터베이스 {milvus.db}</span>
      {result && (result.ok
        ? <span>연결됨 · {result.latency_ms}ms{result.databases ? ` · 데이터베이스 ${result.databases.length}개` : ''}{result.db_found === false ? ` · ${milvus.db} 없음` : ''}</span>
        : <span className="is-error">{result.error ?? '연결하지 못했습니다.'}</span>)}
      {result?.note && <span>{result.note}</span>}</>)}>
      <i aria-hidden />{checking ? '연결 확인 중' : result ? (result.ok ? `연결됨 · ${result.latency_ms} ms` : '연결 확인 실패') : 'Milvus 설정됨'}
    </span>
    <button type="button" className="vdb-conn-check" onClick={run} disabled={checking}>
      {checking ? <LoaderCircle size={16} className="vdb-spin" aria-hidden="true" /> : <PlugZap size={16} aria-hidden="true" />} 연결 확인
    </button>
    {!checking && result && (!result.ok || result.db_found === false) && <span className="vdb-conn-result">{result.ok ? `설정한 데이터베이스 ${milvus.db}을(를) 찾을 수 없습니다.` : result.error ?? 'Milvus에 연결하지 못했습니다.'}</span>}
  </span>;
}

const Loading = ({ label }: { label: string }) => <p className="vdb-loading is-page" role="status"><LoaderCircle size={16} className="vdb-spin" aria-hidden /> {label}</p>;

function Problem({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return <div className="vdb-problem" role="alert">
    <TriangleAlert size={19} aria-hidden="true" /><div><strong>{title}</strong><p>{message}</p></div>
    <button type="button" className="button-secondary" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" /> 다시 시도</button>
  </div>;
}
