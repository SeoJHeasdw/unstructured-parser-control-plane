import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, CircleX, Hand, Info, Search, TriangleAlert, X } from 'lucide-react';
import { Tabs } from '../ui';
import { wait } from './FlowCanvasParts';
import { splitRid } from './flowSim';
import type { SimDoc, SimEvent, SimSnapshot } from './flowSim';
import { OVERVIEW_ID } from './flowTemplates';
import type { FlowLibrary } from './flowTypes';

export type DockState = 'all' | SimDoc['state'];
type DockTab = 'events' | 'docs';
type Props = {
  snapshot: SimSnapshot; library: FlowLibrary; flowId: string;
  tab: DockTab; onTab: (tab: DockTab) => void;
  state: DockState; onState: (state: DockState) => void;
  query: string; onQuery: (query: string) => void;
  onNavigate: (flowId: string, nodeId?: string) => void;
};
const LEVEL: Record<SimEvent['level'], { label: string; icon: typeof Info }> = {
  info: { label: '정보', icon: Info }, warn: { label: '주의', icon: TriangleAlert },
  error: { label: '실패', icon: CircleX }, action: { label: '개입', icon: Hand },
};
const STATE: Record<DockState, string> = { all: '전체', queued: '대기', processing: '처리 중', held: '보류', failed: '실패' };
const PRIORITY: Record<SimDoc['state'], number> = { failed: 0, held: 1, processing: 2, queued: 3 };
const LEVELS = Object.keys(LEVEL) as SimEvent['level'][];
const PAGE_SIZE = 100;

export default function FlowDock({ snapshot, library, flowId, tab, onTab, state, onState, query, onQuery, onNavigate }: Props) {
  const [levels, setLevels] = useState(() => new Set(LEVELS));
  const [limit, setLimit] = useState(PAGE_SIZE);
  const allFlows = flowId === OVERVIEW_ID;
  const scope = allFlows ? '전체 흐름' : library.flows[flowId]?.title ?? flowId;
  const where = (runtimeId: string) => {
    const { flowId: targetFlow, nodeId } = splitRid(runtimeId);
    const doc = library.flows[targetFlow];
    return { flowId: targetFlow, nodeId, flow: targetFlow === OVERVIEW_ID ? '전체 흐름' : doc?.title ?? targetFlow, node: doc?.nodes.find(node => node.id === nodeId)?.data.label ?? nodeId };
  };
  const scopedEvents = useMemo(() => snapshot.events.filter(event => allFlows || event.node?.startsWith(`${flowId}::`)), [snapshot.events, allFlows, flowId]);
  const scopedDocs = useMemo(() => snapshot.docs.filter(doc => allFlows || doc.node.startsWith(`${flowId}::`)), [snapshot.docs, allFlows, flowId]);
  const events = scopedEvents.filter(event => levels.has(event.level));
  const docs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return scopedDocs.filter(doc => (state === 'all' || doc.state === state) && (!q || doc.name.toLowerCase().includes(q) || doc.id.toLowerCase().includes(q) || doc.ext.toLowerCase() === q.replace(/^\./, '')))
      .sort((a, b) => PRIORITY[a.state] - PRIORITY[b.state] || a.enteredAt - b.enteredAt);
  }, [scopedDocs, query, state]);
  useEffect(() => setLimit(PAGE_SIZE), [flowId, query, state]);

  return <section className="fd-root" aria-label="운영 기록">
    <div className="fd-heading">
      <Tabs<DockTab> items={[{ id: 'events', label: '이벤트 로그', badge: scopedEvents.length }, { id: 'docs', label: '문서 추적', badge: scopedDocs.length }]}
        value={tab} onChange={onTab} label="운영 기록 보기" />
      <span className="fd-scope" title={scope}>{scope}</span>
    </div>
    <div className="fd-tools" role="group" aria-label={tab === 'events' ? '이벤트 종류' : '문서 상태'}>
      {tab === 'events'
        ? LEVELS.map(level => {
          const Icon = LEVEL[level].icon;
          return <button key={level} className={`fd-chip is-${level} ${levels.has(level) ? 'is-on' : ''}`} aria-pressed={levels.has(level)}
            onClick={() => setLevels(previous => { const next = new Set(previous); next.has(level) ? next.delete(level) : next.add(level); return next; })}>
            <Icon size={14} aria-hidden="true" />{LEVEL[level].label}<b>{scopedEvents.filter(event => event.level === level).length}</b>
          </button>;
        })
        : <><div className="fd-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={event => onQuery(event.target.value)} placeholder="문서명 · ID · 형식" aria-label="문서 검색" />
          {query && <button onClick={() => onQuery('')} aria-label="문서 검색어 지우기"><X size={15} /></button>}
        </div>{(['all', 'failed', 'held', 'processing', 'queued'] as const).map(value => <button key={value} className={`fd-chip ${state === value ? 'is-on' : ''}`} aria-pressed={state === value} onClick={() => onState(value)}>{STATE[value]}</button>)}</>}
    </div>
    <div className="fd-body">
      {tab === 'events' ? (events.length ? <ul className="fd-events">{events.map(event => {
        const Icon = LEVEL[event.level].icon;
        const target = event.node ? where(event.node) : null;
        return <li key={event.id} className={`is-${event.level}`}>
          <time>{event.clock}</time><Icon size={15} aria-label={LEVEL[event.level].label} /><span>{event.text}</span>
          {target && <button onClick={() => onNavigate(target.flowId, target.nodeId)}>{target.flow} › {target.node}<ArrowUpRight size={13} aria-hidden="true" /></button>}
        </li>;
      })}</ul> : <p className="fd-empty">선택한 종류의 이벤트가 없습니다.</p>)
        : docs.length ? <>
          <table className="fd-table"><thead><tr><th scope="col">문서</th><th scope="col">형식</th><th scope="col">계보</th><th scope="col">현재 위치</th><th scope="col">상태</th><th scope="col">머문 시간</th><th scope="col">사유</th></tr></thead><tbody>
            {docs.slice(0, limit).map(doc => { const at = where(doc.node); return <tr key={doc.id} className={`is-${doc.state}`}>
              <td><b title={doc.name}>{doc.name}</b><small>{doc.id}</small></td>
              <td><span className="fd-ext">{doc.ext}</span></td>
              <td className="fd-lineage" title={doc.parentName}>{doc.depth ? <>{`깊이 ${doc.depth}`} · {doc.parentName}</> : '원본'}</td>
              <td><button className="fd-location" onClick={() => onNavigate(at.flowId, at.nodeId)}>{at.flow} › {at.node}<ArrowUpRight size={13} aria-hidden="true" /></button></td>
              <td><em className={`fd-state is-${doc.state}`}>{STATE[doc.state]}</em></td><td>{wait(snapshot.now - doc.enteredAt)}</td><td className="fd-reason" title={doc.reason}>{doc.reason || '—'}</td>
            </tr>; })}
          </tbody></table>
          {docs.length > limit && <div className="fd-more"><span>{docs.length}건 중 {limit}건 표시</span><button className="ps-btn" onClick={() => setLimit(value => value + PAGE_SIZE)}>문서 더 보기</button></div>}
        </> : <div className="fd-empty"><p>{scopedDocs.length ? '조건에 맞는 문서가 없습니다.' : '현재 추적 중인 문서가 없습니다.'}</p>
          {scopedDocs.length > 0 && <button className="ps-btn" onClick={() => { onQuery(''); onState('all'); }}>검색 조건 초기화</button>}</div>}
    </div>
  </section>;
}
