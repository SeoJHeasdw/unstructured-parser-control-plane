import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { ArrowRight, ChevronRight, CirclePause, CirclePlay } from 'lucide-react';
import { STATUS_LABEL } from './FlowCanvasParts';
import { aggregate, rid, splitRid } from './flowSim';
import type { FlowSimulator, NodeMetric } from './flowSim';
import { OVERVIEW_ID } from './flowTemplates';
import type { FlowNode } from './flowTypes';
import './flow.css';
import './liveFlow.css';

type Props = { simulator: FlowSimulator; active: boolean; onOpen: (flowId: string, nodeId?: string) => void };
type Row = { node: FlowNode; metric: NodeMetric };

/** 대시보드 상단: 전체 처리 흐름을 단계 열로 접어 보여 주고, 문제 단계에서 바로 파이프라인으로 들어간다. */
export default function LiveFlowPanel({ simulator, active, onOpen }: Props) {
  const snapshot = useSyncExternalStore(simulator.subscribe, simulator.getSnapshot);
  useEffect(() => { if (active) return simulator.acquire(); }, [active, simulator]);
  const library = simulator.getLibrary();
  const root = library.flows[OVERVIEW_ID];
  const columns = useMemo(() => {
    if (!root) return [] as FlowNode[][];
    const vertical = root.direction === 'TB';
    const center = (node: FlowNode) => vertical ? node.position.y + (node.height ?? 0) / 2 : node.position.x + (node.width ?? 0) / 2;
    const cross = (node: FlowNode) => vertical ? node.position.x : node.position.y;
    const nodes = root.nodes.filter(node => node.data.kind !== 'note' && node.data.kind !== 'gateway').sort((a, b) => center(a) - center(b));
    const groups: FlowNode[][] = [];
    for (const node of nodes) { const last = groups[groups.length - 1]; if (last && Math.abs(center(last[0]) - center(node)) < 24) last.push(node); else groups.push([node]); }
    return groups.map(group => group.sort((a, b) => cross(a) - cross(b)));
  }, [root]);
  const metricOf = (node: FlowNode) => node.data.kind === 'subflow' && node.data.subflow ? aggregate(snapshot.metrics, node.data.subflow) : snapshot.metrics[rid(OVERVIEW_ID, node.id)];
  const attention = Object.entries(snapshot.metrics).filter(([, metric]) => metric.status === 'error' || metric.status === 'warn' || metric.status === 'paused')
    .sort(([, a], [, b]) => rank(a) - rank(b) || (b.failed + b.held + b.queued) - (a.failed + a.held + a.queued)).slice(0, 6)
    .map(([id, metric]) => { const { flowId, nodeId } = splitRid(id); const doc = library.flows[flowId]; return { id, flowId, nodeId, metric, label: doc?.nodes.find(node => node.id === nodeId)?.data.label ?? nodeId, flow: flowId === OVERVIEW_ID ? '전체 흐름' : doc?.title ?? flowId }; });
  const t = snapshot.totals;
  return <section className="lf-root" aria-label="처리 흐름 현황">
    <header className="lf-head">
      <div><h2>처리 흐름</h2><span className={`lf-state ${snapshot.running ? 'is-on' : ''}`}>{snapshot.running ? <><i /> 진행 중</> : <><CirclePause size={13} /> 전체 일시정지</>}</span><time>{snapshot.clock}</time></div>
      <div className="lf-actions">
        <button onClick={() => simulator.setRunning(!snapshot.running)}>{snapshot.running ? <><CirclePause size={14} /> 일시정지</> : <><CirclePlay size={14} /> 재개</>}</button>
        <button className="is-primary" onClick={() => onOpen(OVERVIEW_ID)}>파이프라인에서 보기 <ArrowRight size={14} /></button>
      </div>
    </header>
    <div className="lf-kpis">
      <div><span>유입</span><b>{t.arrivalsPerMin}<small>/분</small></b></div>
      <div title="압축 항목·첨부·내장 개체에서 나와 형식 판별로 다시 들어간 문서"><span>파생 문서</span><b>{t.derivedPerMin}<small>/분</small></b><em>{t.arrivals ? `원본 대비 ×${((t.arrivals + t.derived) / t.arrivals).toFixed(2)} · 최대 깊이 ${t.maxDepth}` : ''}</em></div>
      <div><span>완료</span><b>{t.completedPerMin}<small>/분</small></b></div>
      <div><span>처리 중</span><b>{t.processing}</b></div>
      <div><span>대기</span><b>{t.queued}</b></div>
      <button className={t.held ? 'is-warn' : ''} onClick={() => jump(attention.find(item => item.metric.held > 0))}><span>보류 · 사람 확인</span><b>{t.held}</b></button>
      <button className={t.failed ? 'is-error' : ''} onClick={() => jump(attention.find(item => item.metric.failed > 0))}><span>실패</span><b>{t.failed}</b></button>
      <div><span>누적 완료</span><b>{t.completed.toLocaleString('ko-KR')}</b></div>
    </div>
    <div className="lf-body">
      <ol className="lf-rail">{columns.map((group, index) => { const table = group.length > 1 && group.some(node => node.data.kind === 'subflow'); return <li key={group[0].id} className={table ? 'is-group' : ''}>
        {table ? <div className="lf-col"><h3>형식별 처리<span>{group.filter(node => node.data.kind === 'subflow').length}</span></h3>
          <div className="lf-row-head"><span /><em>대기</em><em>처리</em><em>보류</em><em>실패</em></div>
          <ul>{group.map(node => { const metric = metricOf(node); return metric ? <li key={node.id}><RowButton row={{ node, metric }} onClick={() => open(node)} /></li> : null; })}</ul></div>
          : <div className="lf-stack">{group.map(node => <Stage key={node.id} node={node} metric={metricOf(node)} onClick={() => open(node)} />)}</div>}
        {index < columns.length - 1 && <ChevronRight className="lf-arrow" size={16} aria-hidden="true" />}
      </li>; })}</ol>
      <aside className="lf-attention"><h3>주의가 필요한 단계<span>{attention.length}</span></h3>
        {attention.length ? <ul>{attention.map(item => <li key={item.id}><button onClick={() => onOpen(item.flowId, item.nodeId)}><i className={`fx-dot is-${item.metric.status}`} /><span><b>{item.label}</b><small>{item.flow} · {STATUS_LABEL[item.metric.status]}</small></span><em className={`is-${item.metric.status}`}>{reason(item.metric)}</em><span className="lf-go">개입<ChevronRight size={13} /></span></button></li>)}</ul> : <p>지연·실패·보류된 단계가 없습니다.</p>}
      </aside>
    </div>
  </section>;

  function open(node: FlowNode) { if (node.data.kind === 'subflow' && node.data.subflow) onOpen(node.data.subflow); else onOpen(OVERVIEW_ID, node.id); }
  function jump(item?: { flowId: string; nodeId: string }) { if (item) onOpen(item.flowId, item.nodeId); }
}

function Stage({ node, metric, onClick }: { node: FlowNode; metric?: NodeMetric; onClick: () => void }) {
  return <button className={`lf-stage is-${metric?.status ?? 'idle'} is-${node.data.kind}`} onClick={onClick}>
    <span className="lf-stage-name"><i className={`fx-dot is-${metric?.status ?? 'idle'}`} />{node.data.label}</span>
    {metric && (node.data.kind === 'start' ? <b>{metric.throughput}<small>/분 유입</small></b> : node.data.kind === 'end' ? <b>{metric.done.toLocaleString('ko-KR')}<small>건 완료</small></b> : node.data.kind === 'exception' ? <span className="lf-stage-counts"><em className={metric.held ? 'is-warn' : ''}>보류 <b>{metric.held}</b></em></span>
      : <span className="lf-stage-counts"><em>대기 <b>{metric.queued}</b></em><em>처리 <b>{metric.processing}</b></em>{metric.held > 0 && <em className="is-warn">보류 <b>{metric.held}</b></em>}{metric.failed > 0 && <em className="is-error">실패 <b>{metric.failed}</b></em>}</span>)}
  </button>;
}

function RowButton({ row, onClick }: { row: Row; onClick: () => void }) {
  const { node, metric } = row;
  return <button className={`lf-row is-${metric.status}${node.data.kind === 'exception' ? ' is-exception' : ''}`} onClick={onClick}>
    <i className={`fx-dot is-${metric.status}`} /><span>{node.data.label}</span>
    {node.data.kind === 'exception' ? <em className={metric.held ? 'is-warn' : ''}>보류 {metric.held}</em> : <>
      <em>{metric.queued}</em><em>{metric.processing}</em><em className={metric.held ? 'is-warn' : ''}>{metric.held}</em><em className={metric.failed ? 'is-error' : ''}>{metric.failed}</em>
    </>}
  </button>;
}
const rank = (metric: NodeMetric) => ({ error: 0, warn: 1, paused: 2, busy: 3, idle: 4 })[metric.status];
function reason(metric: NodeMetric) { return metric.paused ? '일시정지' : metric.failed ? `실패 ${metric.failed}` : metric.held ? `보류 ${metric.held}` : `대기 ${metric.queued}`; }
