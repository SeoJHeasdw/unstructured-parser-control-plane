import { useCallback, useEffect, useState } from 'react';
import { BookOpenText, Layers, LoaderCircle, PlugZap, RefreshCw, TriangleAlert } from 'lucide-react';
import { checkMilvus, getCollection, getSources, getTree, type CheckResult, type CollectionDetail, type SourceKey, type SourcesInfo, type Tree } from './api/vectordb';
import { Tabs } from './ui';
import { fmtCount, loadLabel, metricHint, readStored, useFloating, useStored, writeStored } from './vectordb/ui';
import VdbTree from './vectordb/VdbTree';
import ChunkBrowser from './vectordb/ChunkBrowser';
import SchemaView from './vectordb/SchemaView';
import { ChunkModal, type PanelState } from './vectordb/VdbPanel';
import Overview from './vectordb/Overview';
import PartitionModal, { type PartRef } from './vectordb/PartitionModal';
import './vectordb.css';

/** 벡터 DB(읽기 전용). 화면이 처음 열릴 때 한 번 불러온다. */
export default function VectorDbWorkspace({ active }: { active: boolean }) {
  const [started, setStarted] = useState(active);
  useEffect(() => { if (active) setStarted(true); }, [active]);
  return started ? <VectorDbScreen active={active} /> : <div className="vdb-root" />;
}

type Selection = { db: string; collection: string };
type Page = 'overview' | 'collections';
type Tab = 'chunks' | 'schema';
type Tip = ReturnType<typeof useFloating>;
const PAGES: { id: Page; label: string }[] = [{ id: 'overview', label: '개요' }, { id: 'collections', label: '컬렉션' }];
const TABS: [Tab, string][] = [['chunks', '청크'], ['schema', '스키마·인덱스']];

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
  const [tree, setTree] = useState<Tree | null>(null);
  const [treeError, setTreeError] = useState('');
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
      setSource(result.sources.some(s => s.key === result.default && s.available) ? result.default : 'example');
    }).catch((err: Error) => { if (alive) setInfoError(err.message); });
    return () => { alive = false; };
  }, [infoTry]);

  useEffect(() => {
    if (!source) return;
    let alive = true;
    setTreeError('');
    getTree(source).then(result => {
      if (!alive) return;
      setTree(result);
      setSelection(current => {
        const keep = current && result.databases.some(db => db.name === current.db && db.collections.some(c => c.name === current.collection));
        return keep ? current : firstCollection(result, readStored<string>(`sel.${source}`, ''));
      });
    }).catch((err: Error) => { if (alive) setTreeError(err.message); });
    return () => { alive = false; };
  }, [source, reload]);

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
  };
  const switchSource = (next: SourceKey) => {
    if (next === source) return;
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

  if (infoError) return <div className="vdb-root"><Problem message={infoError} onRetry={() => setInfoTry(n => n + 1)} /></div>;
  if (!info || !source) return <div className="vdb-root"><Loading label="벡터 DB 정보를 불러오는 중" /></div>;
  const milvus = info.milvus;

  const collections = () => <div className="vdb-main">
    <nav className="panel vdb-side" aria-label="컬렉션 목록">
      <VdbTree source={source} tree={tree!} selected={selection} partition={partition} onSelect={select} />
    </nav>
    <section className="panel vdb-center" aria-label="컬렉션">
      {!selection ? <p className="vdb-empty is-page">표시할 컬렉션이 없습니다.</p>
        : detailError ? <Problem message={detailError} onRetry={retry} />
          : !shown ? <Loading label="컬렉션 정보를 불러오는 중" />
            : <>
              <CollectionHead detail={shown} tip={tip} onRead={() => navigate({ mode: 'document', field: null, value: null })} />
              <div className="vdb-tabs" role="tablist" aria-label="컬렉션 보기">
                {TABS.map(([key, label]) => <button key={key} type="button" role="tab" id={`vdb-tab-${key}`} aria-selected={tab === key} aria-controls="vdb-tabpanel" tabIndex={tab === key ? 0 : -1}
                  onClick={() => setTab(key)}
                  onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); const next = tab === 'chunks' ? 'schema' : 'chunks'; setTab(next); document.getElementById(`vdb-tab-${next}`)?.focus(); } }}>{label}</button>)}
              </div>
              <div role="tabpanel" id="vdb-tabpanel" aria-labelledby={`vdb-tab-${tab}`} className="vdb-tabpanel">
                {tab === 'chunks'
                  ? <ChunkBrowser key={`${source}|${shown.db}|${shown.name}`} source={source} detail={shown} textField={textField} onTextField={setTextField}
                    partition={partition} onPartition={setPartition} onOpen={openChunk} activePk={top?.mode === 'chunk' ? top.pk : null} />
                  : <SchemaView detail={shown} />}
              </div>
            </>}
    </section>
  </div>;

  return <div className="vdb-root">
    <div className="vdb-shell">
      <Tabs<Page> items={PAGES} value={page} onChange={setPage} label="벡터 DB 보기" className="vdb-pages">
        {current => treeError ? <Problem message={treeError} onRetry={retry} />
          : !tree ? <Loading label="컬렉션 목록을 불러오는 중" />
            : current === 'overview' ? <Overview tree={tree} onOpen={setOpenPart} /> : collections()}
      </Tabs>
      <div className="vdb-bar">
        {milvus.configured && <div className="vdb-seg" role="group" aria-label="데이터 출처">
          {info.sources.map(s => <button key={s.key} type="button" aria-pressed={source === s.key} disabled={!s.available} onClick={() => switchSource(s.key)}>{s.label}</button>)}
        </div>}
        {source === 'example' && <span className="vdb-example" tabIndex={0}
          {...tip.bind('example', () => <span>{milvus.configured ? '합성 예시 컬렉션입니다.' : 'Milvus 연결 정보가 없어 합성 예시 컬렉션을 보여 줍니다.'}</span>)}>예시 데이터</span>}
        {tree && <span className="vdb-totals">컬렉션 <b>{fmtCount(tree.totals.collections)}</b> · 청크 <b>{fmtCount(tree.totals.rows)}</b></span>}
        {tree && tree.warnings.length > 0 && <span className="vdb-chip is-warn" tabIndex={0}
          {...tip.bind('tree-warn', () => <><b>읽지 못한 정보</b>{tree.warnings.slice(0, 6).map(w => <span key={w}>{w}</span>)}</>)}><TriangleAlert size={12} aria-hidden /> {tree.warnings.length}건</span>}
        <MilvusControl info={info} tip={tip} />
        <button type="button" className="plain-icon" aria-label="다시 불러오기" title="다시 불러오기" onClick={retry}><RefreshCw size={15} /></button>
      </div>
    </div>
    {openPart && active && <PartitionModal key={`${source}|${openPart.db}|${openPart.collection}|${openPart.partition}`} source={source} part={openPart} onClose={() => setOpenPart(null)} />}
    {shown && active && <ChunkModal stack={history} onBack={back} onClose={close} onNavigate={navigate} source={source} detail={shown} textField={textField} />}
    {tip.layer}
  </div>;
}

function CollectionHead({ detail, tip, onRead }: { detail: CollectionDetail; tip: Tip; onRead: () => void }) {
  const vector = detail.vector_fields[0];
  const loaded = detail.load_state === 'LoadStateLoaded';
  const emb = detail.embedding;
  const partitions = detail.partitions_num ?? detail.partitions.length;
  return <header className="vdb-head">
    <div className="vdb-head-title">
      <Layers size={16} aria-hidden />
      <h2>{detail.name}</h2>
      <span className="vdb-head-db">{detail.db}</span>
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
    <button type="button" className="button-quiet vdb-head-read" onClick={onRead}><BookOpenText size={14} aria-hidden /> 문서로 다시 읽기</button>
  </header>;
}

function MilvusControl({ info, tip }: { info: SourcesInfo; tip: Tip }) {
  const [result, setResult] = useState<CheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const milvus = info.milvus;
  if (!milvus.configured) return <span className="vdb-conn is-off" tabIndex={0}
    {...tip.bind('conn', () => <><b>Milvus 미연결</b><span>연결 정보가 설정되지 않았습니다.</span></>)}><i aria-hidden />Milvus 미연결</span>;
  const run = () => {
    setChecking(true);
    checkMilvus().then(setResult).catch((err: Error) => setResult({ ok: false, status: null, latency_ms: 0, error: err.message })).finally(() => setChecking(false));
  };
  return <span className={`vdb-conn ${result ? (result.ok ? 'is-ok' : 'is-bad') : ''}`}>
    <span className="vdb-conn-label" tabIndex={0} {...tip.bind('conn', () => <><b>{milvus.uri}</b><span>데이터베이스 {milvus.db}</span>
      {result && (result.ok
        ? <span>연결됨 · {result.latency_ms}ms{result.databases ? ` · 데이터베이스 ${result.databases.length}개` : ''}{result.db_found === false ? ` · ${milvus.db} 없음` : ''}</span>
        : <span className="is-error">{result.error ?? '연결하지 못했습니다.'}</span>)}
      {result?.note && <span>{result.note}</span>}</>)}>
      <i aria-hidden />{result ? (result.ok ? `연결됨 · ${result.latency_ms}ms` : '연결 실패') : 'Milvus'}
    </span>
    <button type="button" className="vdb-conn-check" onClick={run} disabled={checking}>
      {checking ? <LoaderCircle size={13} className="mw-spin" aria-hidden /> : <PlugZap size={13} aria-hidden />} 연결 확인
    </button>
  </span>;
}

const Loading = ({ label }: { label: string }) => <p className="vdb-loading is-page" role="status"><LoaderCircle size={16} className="mw-spin" aria-hidden /> {label}</p>;

function Problem({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="vdb-problem" role="alert">
    <TriangleAlert size={16} aria-hidden /><span>{message}</span>
    <button type="button" className="button-secondary" onClick={onRetry}><RefreshCw size={13} aria-hidden /> 다시 시도</button>
  </div>;
}
