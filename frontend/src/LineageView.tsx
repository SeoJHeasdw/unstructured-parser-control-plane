import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, ChevronDown, Database, FlaskConical, FolderOpen, ListFilter, RotateCw } from 'lucide-react';
import { getLineage } from './api/lineage';
import type { LineageData, LineageSource, LnFamily, RefState } from './api/lineage';
import { FamilyList } from './lineage/FamilyList';
import { FamilyView } from './lineage/FamilyView';
import type { Pin } from './lineage/FamilyView';
import { DetailPanel } from './lineage/DetailPanel';
import { TipProvider, useHoverProps } from './lineage/Tip';
import { STATE_META, familyMatches, loadPrefs, relatedFamilies, savePrefs, timeText } from './lineage/model';
import type { Filter, Tone, UiPrefs } from './lineage/model';
import './lineage.css';
import { StructureOverviewStrip } from './StructurePanel';

const SOURCE_KEY = 'document-ops:lineage-source:v1';
const SOURCES: { id: LineageSource; label: string; tip: string }[] = [
  { id: 'live', label: '실제 파일', tip: '업로드한 파일과 저장된 구조 분석 결과에서 관계를 찾습니다.' },
  { id: 'example', label: '예시 데이터', tip: '예시 파일에서 판·포함·참조 관계를 살펴봅니다.' },
];
function loadSource(): LineageSource {
  try { return localStorage.getItem(SOURCE_KEY) === 'example' ? 'example' : 'live'; } catch { return 'live'; }
}
function saveSource(source: LineageSource) {
  try { localStorage.setItem(SOURCE_KEY, source); } catch { /* 저장할 수 없어도 화면은 동작한다. */ }
}

type Load = { status: 'idle' | 'loading' | 'ready' | 'error'; data: LineageData | null; error: string };

/** 문서 계보: 문서군 목록 · 선택한 문서군의 판과 포함·참조 관계 · 클릭으로 고정하는 상세. */
export default function LineageView({ active, onOpenLive, documentId }: { active: boolean; documentId?: string; onOpenLive?: (doc?: string) => void }) {
  return <TipProvider><LineageScreen documentId={documentId} active={active} onOpenLive={onOpenLive} /></TipProvider>;
}

function familyText(data: LineageData, family: LnFamily) {
  const names = family.entries.flatMap(id => data.entries[id]?.instances.map(item => data.instances[item]?.name ?? '') ?? []);
  return [family.title, family.docno ?? '', ...names].join('\n').toLowerCase();
}

function LineageScreen({ active, onOpenLive, documentId }: { active: boolean; documentId?: string; onOpenLive?: (doc?: string) => void }) {
  const [started, setStarted] = useState(active);
  const [source, setSource] = useState<LineageSource>(loadSource);
  const [bulkOpen, setBulkOpen] = useState(false);
  useEffect(() => { if (documentId) { setSource('live'); setQuery(''); setFilter('all'); } }, [documentId]);
  const [reload, setReload] = useState(0);
  const [load, setLoad] = useState<Load>({ status: 'idle', data: null, error: '' });
  const [prefs, setPrefs] = useState<UiPrefs>(loadPrefs);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<string | null>(null);
  const [entry, setEntry] = useState<string | null>(null);
  const [pin, setPin] = useState<Pin | null>(null);
  const [hoverFamily, setHoverFamily] = useState<string | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => { if (active) setStarted(true); }, [active]);
  useEffect(() => {
    if (!started) return;
    const controller = new AbortController();
    setLoad(prev => ({ ...prev, status: 'loading', error: '' }));
    getLineage(source, controller.signal)
      .then(data => { if (!controller.signal.aborted) setLoad({ status: 'ready', data, error: '' }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setLoad({ status: 'error', data: null, error: error instanceof Error ? error.message : '' }); });
    return () => controller.abort();
  }, [started, source, reload]);

  const data = load.data && load.data.source === source ? load.data : null;
  useEffect(() => { setPin(null); setHoverFamily(null); }, [data]);
  const linkedDocument = useMemo(() => documentId && data?.source === 'live'
    ? Object.values(data.instances).find(item => item.doc_id === documentId && item.depth === 0) : undefined, [documentId, data]);
  useEffect(() => {
    if (!documentId || !linkedDocument) return;
    setSelected(linkedDocument.family); setEntry(linkedDocument.entry);
  }, [documentId, linkedDocument?.family, linkedDocument?.entry]);
  const closeDetail = useCallback(() => {
    setPin(null);
    detailTrigger.current?.focus({ preventScroll: true });
  }, []);
  useEffect(() => {
    if (!pin || !active) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) closeDetail(); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [pin, active, closeDetail]);

  const searchable = useMemo(() => new Map(data?.families.map(family => [family.id, familyText(data, family)])), [data]);
  const shown = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    return data.families.filter(family => familyMatches(family, filter) && (!q || searchable.get(family.id)?.includes(q)));
  }, [data, filter, query, searchable]);
  const missingFamily = !!documentId && data?.source === 'live' && !linkedDocument;
  const family = shown.find(item => item.id === selected) ?? (missingFamily ? null : shown[0]);
  const entryId = family && entry && data?.entries[entry]?.family === family.id ? entry : family?.latest.entry ?? '';
  const related = useMemo(() => data && hoverFamily ? relatedFamilies(data, hoverFamily) : null, [data, hoverFamily]);

  const updatePrefs = useCallback((patch: Partial<UiPrefs>) => setPrefs(prev => { const next = { ...prev, ...patch }; savePrefs(next); return next; }), []);
  const changeSource = (next: LineageSource) => {
    if (next === source) return;
    setSource(next); saveSource(next); setSelected(null); setEntry(null); setPin(null); setQuery(''); setFilter('all');
  };
  const selectFamily = (id: string, nextEntry?: string) => {
    setSelected(id); setEntry(nextEntry ?? null); setPin(null);
    if (!shown.some(item => item.id === id)) { setFilter('all'); setQuery(''); }
  };
  const togglePin = (next: Pin) => {
    if (pin?.type === next.type && pin.id === next.id) {
      closeDetail();
      return;
    }
    detailTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPin(next);
  };
  const pickFilter = (next: Filter) => { setFilter(next); setSelected(null); setEntry(null); setPin(null); };

  const pickQuery = (value: string) => { setQuery(value); setSelected(null); setEntry(null); setPin(null); };
  const resetFilters = () => { pickQuery(''); pickFilter('all'); };
  const sourceLabel = SOURCES.find(item => item.id === source)!;

  let body;
  if (!data && load.status === 'error') {
    body = <div className="panel ln-state-panel" role="alert">
      <span className="ln-state-icon is-error"><AlertCircle size={22} aria-hidden="true" /></span>
      <div><h2>문서 계보를 불러오지 못했습니다</h2><p>{load.error || '잠시 후 다시 시도해 주세요.'}</p></div>
      <div className="ln-state-actions">
        <button className="button-secondary" onClick={() => setReload(n => n + 1)}>다시 시도</button>
        {source === 'live' && <button className="button-quiet" onClick={() => changeSource('example')}>예시 데이터 보기</button>}
      </div>
    </div>;
  } else if (!data) {
    body = <div className="panel ln-state-panel" role="status"><span className="ln-state-icon"><span className="shell-spinner" aria-hidden="true" /></span><div><h2>문서 계보를 불러오는 중입니다</h2><p>{source === 'example' ? '예시 데이터로 판과 관계를 계산하고 있습니다.' : '올린 파일과 구조 분석 결과로 판과 관계를 계산하고 있습니다.'}</p></div></div>;
  } else if (!data.families.length) {
    body = <div className="panel ln-state-panel">
      <span className="ln-state-icon"><FolderOpen size={22} aria-hidden="true" /></span>
      <div><h2>{source === 'live' ? '아직 올린 파일이 없습니다' : '표시할 문서가 없습니다'}</h2><p>{source === 'live' ? '파일을 올리고 구조 분석을 실행하면 문서에 포함된 파일과 다른 문서를 가리키는 참조를 확인할 수 있어요.' : '예시 데이터가 비어 있습니다.'}</p></div>
      {source === 'live' && <div className="ln-state-actions">
        {onOpenLive && <button type="button" className="button-primary" onClick={() => onOpenLive()}>실제 파일 처리 열기 <ArrowRight size={15} aria-hidden="true" /></button>}
        <button type="button" className="button-secondary" onClick={() => changeSource('example')}>예시 데이터 보기</button>
      </div>}
    </div>;
  } else {
    body = <div className={`ln-main${pin ? ' has-pin' : ''}`}>
      <FamilyList data={data} shown={shown} selected={family?.id ?? null} onSelect={id => selectFamily(id)} query={query} onQuery={pickQuery} onReset={resetFilters}
        filter={filter} onFilter={pickFilter} moreFilters={prefs.moreFilters} onMoreFilters={open => updatePrefs({ moreFilters: open })} related={related} onHoverFamily={setHoverFamily} />
      {family ? <FamilyView key={family.id} data={data} family={family} entryId={entryId} onEntry={setEntry} view={prefs.view} onView={view => updatePrefs({ view })}
        refTab={prefs.refTab} onRefTab={refTab => updatePrefs({ refTab })} pin={pin} onPin={togglePin} onFamily={id => selectFamily(id)} onOpenLive={onOpenLive} /> : <div className="panel ln-state-panel">
        <span className="ln-state-icon"><ListFilter size={22} aria-hidden="true" /></span>
        <div><h2>{missingFamily ? '이 문서의 문서군을 찾을 수 없습니다' : '조건에 맞는 문서군이 없습니다'}</h2><p>{missingFamily ? '목록에서 다른 문서군을 선택할 수 있습니다.' : '검색어를 바꾸거나 필터를 해제하면 다른 문서군을 확인할 수 있어요.'}</p></div>
      </div>}
      {pin && <DetailPanel data={data} pin={pin} current={family} onClose={closeDetail} onFamily={selectFamily} />}
    </div>;
  }

  return <div className="ln-root" aria-busy={load.status === 'loading' ? 'true' : undefined}>
    <div className="panel ln-bar">
      <div className="ln-source-block">
        <div className="ln-seg ln-source" role="group" aria-label="데이터 출처">
          {SOURCES.map(item => <button type="button" key={item.id} aria-pressed={source === item.id} className={source === item.id ? 'is-on' : ''} onClick={() => changeSource(item.id)}>
            {item.id === 'live' ? <Database size={16} aria-hidden="true" /> : <FlaskConical size={16} aria-hidden="true" />}{item.label}
          </button>)}
        </div>
        <p className="ln-source-note">{sourceLabel.tip}</p>
      </div>
      <div className="ln-bar-end">
        {data && <span className="ln-asof">{source === 'example' && <em>예시 데이터</em>}기준 {timeText(data.as_of ?? data.generated_at)}</span>}
        {data && data.families.length > 0 && <button type="button" className="ln-sum-toggle" aria-expanded={prefs.summaryOpen} aria-controls="ln-summary" onClick={() => updatePrefs({ summaryOpen: !prefs.summaryOpen })}>
          요약 <ChevronDown size={15} className={prefs.summaryOpen ? '' : 'ln-rot'} aria-hidden="true" /></button>}
        <button type="button" className="ln-icon" onClick={() => setReload(n => n + 1)} disabled={load.status === 'loading'} aria-label="다시 불러오기" title="다시 불러오기"><RotateCw size={16} aria-hidden="true" /></button>
      </div>
    </div>
    {data && data.families.length > 0 && prefs.summaryOpen && <Summary data={data} filter={filter} onFilter={pickFilter} />}
    {body}
    <details hidden={source !== 'live'} className="lw-disclosure" onToggle={e => { if (e.currentTarget.open) setBulkOpen(true); }}><summary>전체 구조 분석</summary>
      {bulkOpen && <StructureOverviewStrip onInspected={() => setReload(n => n + 1)}/>}</details>
  </div>;
}

const REF_FILTER: Partial<Record<RefState, Filter>> = { outdated: 'outdated', missing: 'missing', ambiguous: 'ambiguous' };
const REF_ORDER: RefState[] = ['outdated', 'missing', 'ambiguous', 'linked', 'external'];
const REF_TIP: Record<RefState, string> = {
  linked: '가리키는 문서를 찾아 연결했습니다.', outdated: '최신이 아닌 판을 가리키는 참조입니다.', missing: '가리키는 문서를 올린 파일에서 찾지 못했습니다.',
  ambiguous: '가리키는 문서 후보가 여러 개입니다.', external: '웹 주소처럼 바깥을 가리키는 참조입니다.',
};
type Stat = { key: string; label: string; value: number; tone?: Tone; filter?: Filter; tip: string };

function Summary({ data, filter, onFilter }: { data: LineageData; filter: Filter; onFilter: (filter: Filter) => void }) {
  const hover = useHoverProps();
  const { summary, documents } = data;
  const docs: Stat[] = [
    { key: 'files', label: '파일', value: documents.total, tip: `구조 분석 완료 ${documents.analysed}건 · 분석 전 ${documents.not_analysed}건` },
    { key: 'families', label: '문서군', value: summary.families, tip: '이름·문서번호가 같은 파일을 한 문서로 묶은 수입니다.' },
    { key: 'versioned', label: '여러 판', value: summary.versioned, tip: '판이 둘 이상인 문서군입니다.' },
    { key: 'hold', label: '판단 보류', value: summary.hold, tone: 'warn', filter: 'hold', tip: '최신 판을 정하지 못한 문서군입니다.' },
    { key: 'contained', label: '포함 파일', value: summary.contained, tip: '압축·첨부·내장으로 다른 파일 안에 들어 있는 파일입니다.' },
    { key: 'duplicate', label: '중복', value: summary.duplicates, tone: 'info', filter: 'duplicate', tip: '같은 내용이라 한 판으로 묶은 추가 파일입니다.' },
  ];
  const refs: Stat[] = REF_ORDER.map(state => ({ key: state, label: STATE_META[state].short, value: summary.references[state], tone: STATE_META[state].tone, filter: REF_FILTER[state], tip: REF_TIP[state] }));
  const item = (row: Stat) => {
    const props = hover(`sum:${row.key}`, () => <><strong>{row.label} {row.value}</strong><span>{row.tip}</span>{row.filter && row.value > 0 && <span className="ln-tip-muted">클릭하면 목록을 이 조건으로 거릅니다.</span>}</>);
    const inner = <>{row.tone && <i className={`ln-dot is-${row.tone}`} aria-hidden="true" />}{row.label}<b>{row.value}</b></>;
    return row.filter && row.value > 0
      ? <button key={row.key} className={`ln-stat is-click${filter === row.filter ? ' is-on' : ''}`} aria-pressed={filter === row.filter} onClick={() => onFilter(filter === row.filter ? 'all' : row.filter!)} {...props}>{inner}</button>
      : <span key={row.key} className="ln-stat" tabIndex={0} {...props}>{inner}</span>;
  };
  return <div id="ln-summary" className="ln-summary" role="group" aria-label="요약">
    <span className="ln-sum-label">문서</span>{docs.map(item)}
    <span className="ln-sum-sep" aria-hidden="true" />
    <span className="ln-sum-label">참조</span>{refs.map(item)}
  </div>;
}
