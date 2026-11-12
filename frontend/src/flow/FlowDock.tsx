import { useMemo, useState } from 'react';
import { CircleAlert, CircleX, Hand, Info, Search, TriangleAlert } from 'lucide-react';
import { wait } from './FlowCanvasParts';
import { splitRid } from './flowSim';
import type { SimDoc, SimEvent, SimSnapshot } from './flowSim';
import { OVERVIEW_ID } from './flowTemplates';
import type { FlowLibrary } from './flowTypes';

type Props = { snapshot: SimSnapshot; library: FlowLibrary; tab: 'events' | 'docs'; onTab: (tab: 'events' | 'docs') => void; onNavigate: (flowId: string, nodeId?: string) => void };
const LEVEL: Record<SimEvent['level'], { label: string; icon: typeof Info }> = { info: { label: '정보', icon: Info }, warn: { label: '지연', icon: TriangleAlert }, error: { label: '실패', icon: CircleX }, action: { label: '개입', icon: Hand } };
const STATE: Record<SimDoc['state'], string> = { queued: '대기', processing: '처리 중', held: '보류', failed: '실패' };

export default function FlowDock({ snapshot, library, tab, onTab, onNavigate }: Props) {
  const [levels, setLevels] = useState<Set<SimEvent['level']>>(new Set(['warn', 'error', 'action', 'info']));
  const [query, setQuery] = useState('');
  const [state, setState] = useState<'all' | SimDoc['state']>('all');
  const where = (runtimeId: string) => {
    const { flowId, nodeId } = splitRid(runtimeId);
    const doc = library.flows[flowId];
    return { flowId, nodeId, flow: flowId === OVERVIEW_ID ? '전체' : doc?.title ?? flowId, node: doc?.nodes.find(node => node.id === nodeId)?.data.label ?? nodeId };
  };
  const events = snapshot.events.filter(event => levels.has(event.level));
  const docs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return snapshot.docs.filter(doc => (state === 'all' || doc.state === state) && (!q || doc.name.toLowerCase().includes(q) || doc.id.toLowerCase().includes(q) || doc.ext.toLowerCase() === q.replace(/^\./, '')))
      .sort((a, b) => ({ failed: 0, held: 1, processing: 2, queued: 3 })[a.state] - ({ failed: 0, held: 1, processing: 2, queued: 3 })[b.state] || a.enteredAt - b.enteredAt);
  }, [snapshot.docs, query, state]);
  const counts = { error: snapshot.events.filter(event => event.level === 'error').length, warn: snapshot.events.filter(event => event.level === 'warn').length };
  return <section className="fd-root" aria-label="운영 기록">
    <div className="fd-tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'events'} className={tab === 'events' ? 'is-on' : ''} onClick={() => onTab('events')}>이벤트 로그<span>{snapshot.events.length}</span></button>
      <button role="tab" aria-selected={tab === 'docs'} className={tab === 'docs' ? 'is-on' : ''} onClick={() => onTab('docs')}>문서 추적<span>{snapshot.docs.length}</span></button>
      <div className="fd-tools">{tab === 'events'
        ? (Object.keys(LEVEL) as SimEvent['level'][]).map(level => { const Icon = LEVEL[level].icon; return <button key={level} className={`fd-chip is-${level} ${levels.has(level) ? 'is-on' : ''}`} aria-pressed={levels.has(level)} onClick={() => setLevels(prev => { const next = new Set(prev); next.has(level) ? next.delete(level) : next.add(level); return next; })}><Icon size={12} />{LEVEL[level].label}{level === 'error' && counts.error > 0 && <b>{counts.error}</b>}{level === 'warn' && counts.warn > 0 && <b>{counts.warn}</b>}</button>; })
        : <><label className="fd-search"><Search size={13} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="문서명 · ID · 형식" aria-label="문서 검색" /></label>{(['all', 'failed', 'held', 'processing', 'queued'] as const).map(value => <button key={value} className={`fd-chip ${state === value ? 'is-on' : ''}`} onClick={() => setState(value)}>{value === 'all' ? '전체' : STATE[value]}</button>)}</>}
      </div>
    </div>
    <div className="fd-body">
      {tab === 'events' ? (events.length ? <ul className="fd-events">{events.map(event => { const Icon = LEVEL[event.level].icon; const target = event.node ? where(event.node) : null; return <li key={event.id} className={`is-${event.level}`}>
        <time>{event.clock}</time><Icon size={13} /><span>{event.text}</span>{target && <button onClick={() => onNavigate(target.flowId, target.nodeId)}>{target.flow} › {target.node}</button>}
      </li>; })}</ul> : <p className="fd-empty"><CircleAlert size={14} /> 선택한 종류의 이벤트가 없습니다.</p>)
        : <table className="fd-table"><thead><tr><th>문서</th><th>형식</th><th>현재 위치</th><th>상태</th><th>머문 시간</th><th>사유</th></tr></thead><tbody>
          {docs.slice(0, 150).map(doc => { const at = where(doc.node); return <tr key={doc.id} className={`is-${doc.state}`} onClick={() => onNavigate(at.flowId, at.nodeId)} tabIndex={0} onKeyDown={event => { if (event.key === 'Enter') onNavigate(at.flowId, at.nodeId); }}>
            <td><b>{doc.name}</b><small>{doc.id}</small></td><td><span className="fd-ext">{doc.ext}</span></td><td>{at.flow} › {at.node}</td><td><em className={`fd-state is-${doc.state}`}>{STATE[doc.state]}</em></td><td>{wait(snapshot.now - doc.enteredAt)}</td><td className="fd-reason">{doc.reason ?? ''}</td>
          </tr>; })}
          {!docs.length && <tr><td colSpan={6} className="fd-empty">조건에 맞는 문서가 없습니다.</td></tr>}
        </tbody></table>}
    </div>
  </section>;
}
