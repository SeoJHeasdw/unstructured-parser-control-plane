import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { FocusEvent, MouseEvent as ReactMouseEvent } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, CirclePause, CirclePlay, TriangleAlert } from 'lucide-react';
import { STATUS_LABEL } from './FlowCanvasParts';
import { aggregate, rid, splitRid } from './flowSim';
import type { FlowSimulator, NodeMetric } from './flowSim';
import { OVERVIEW_ID } from './flowTemplates';
import type { FlowNode } from './flowTypes';
import './flow.css';
import './liveFlow.css';

type Props = { simulator: FlowSimulator; active: boolean; onOpen: (flowId: string, nodeId?: string) => void };
type MetricKey = 'queued' | 'processing' | 'held' | 'failed';
type Tip = { x: number; y: number; title: string; status?: NodeMetric['status']; lines: [string, string, string?][]; foot?: string; rows?: { label: string; metric: NodeMetric }[] };

const STORE_KEY = 'document-ops:dashboard-flow';
type Saved = { formats: boolean; attention: boolean };
function loadSaved(): Saved {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) ?? 'null') as Partial<Saved> | null;
    return { formats: raw?.formats === true, attention: raw?.attention === true };
  } catch { return { formats: false, attention: false }; }
}
const KEY_LABEL: Record<MetricKey, string> = { queued: '대기', processing: '처리 중', held: '보류', failed: '실패' };

/** 대시보드 상단: 전체 처리 흐름을 한 줄로 보여 준다. 세부 수치는 hover, 형식별 표와 주의 목록은 펼쳐서 본다. */
export default function LiveFlowPanel({ simulator, active, onOpen }: Props) {
  const snapshot = useSyncExternalStore(simulator.subscribe, simulator.getSnapshot);
  useEffect(() => { if (active) return simulator.acquire(); }, [active, simulator]);
  const [saved, setSaved] = useState<Saved>(loadSaved);
  const [focusKey, setFocusKey] = useState<MetricKey | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const railRef = useRef<HTMLOListElement>(null);
  const update = (next: Saved) => { setSaved(next); try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch { /* 저장 실패는 화면 동작에 영향 없음 */ } };

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
  const metricOf = useCallback((node: FlowNode) => node.data.kind === 'subflow' && node.data.subflow ? aggregate(snapshot.metrics, node.data.subflow) : snapshot.metrics[rid(OVERVIEW_ID, node.id)], [snapshot.metrics]);
  const attention = Object.entries(snapshot.metrics).filter(([, metric]) => metric.status === 'error' || metric.status === 'warn' || metric.status === 'paused')
    .sort(([, a], [, b]) => rank(a) - rank(b) || (b.failed + b.held + b.queued) - (a.failed + a.held + a.queued)).slice(0, 6)
    .map(([id, metric]) => { const { flowId, nodeId } = splitRid(id); const doc = library.flows[flowId]; return { id, flowId, nodeId, metric, label: doc?.nodes.find(node => node.id === nodeId)?.data.label ?? nodeId, flow: flowId === OVERVIEW_ID ? '전체 흐름' : doc?.title ?? flowId }; });
  const t = snapshot.totals;

  const lit = (metric?: Pick<NodeMetric, MetricKey>) => !focusKey ? '' : metric && metric[focusKey] > 0 ? ' is-lit' : ' is-dim';
  const showTip = (target: Element, content: Omit<Tip, 'x' | 'y'>) => {
    const rect = target.getBoundingClientRect();
    const railBottom = railRef.current?.getBoundingClientRect().bottom ?? rect.bottom;
    setTip({ ...content, x: Math.min(Math.max(rect.left + rect.width / 2, 160), window.innerWidth - 160), y: Math.max(rect.bottom, railBottom) + 8 });
  };
  const hideTip = () => setTip(null);
  useEffect(() => {
    if (!tip) return;
    const hide = () => setTip(null);
    window.addEventListener('scroll', hide, true);
    return () => window.removeEventListener('scroll', hide, true);
  }, [tip]);
  const stageTip = (node: FlowNode, metric?: NodeMetric) => (event: ReactMouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    if (!metric) return;
    const lines: Tip['lines'] = node.data.kind === 'start' ? [['유입', `${metric.throughput}`, '/분']] : node.data.kind === 'end' ? [['완료', metric.done.toLocaleString('ko-KR'), '건']]
      : [['대기', `${metric.queued}`], ['처리 중', `${metric.processing}`], ['보류', `${metric.held}`], ['실패', `${metric.failed}`]];
    showTip(event.currentTarget, { title: node.data.label, status: metric.status, lines, foot: '클릭하면 파이프라인에서 이 단계를 엽니다' });
  };

  const kpi = (key: MetricKey | null, label: string, value: string, unit = '', hint?: string, tone = '') => {
    const props = key ? { onMouseEnter: () => setFocusKey(key), onMouseLeave: () => setFocusKey(null), onFocus: () => setFocusKey(key), onBlur: () => setFocusKey(null) } : {};
    return <button type="button" className={`lf-kpi${tone}${key && focusKey === key ? ' is-focus' : ''}`} title={hint} {...props}
      onClick={() => { if (key === 'held' || key === 'failed') jump(attention.find(item => item.metric[key] > 0)); }}>
      <span>{label}</span><b>{value}<small>{unit}</small></b>
    </button>;
  };
  const formatNodes = columns.flatMap(group => group.length > 1 && group.some(node => node.data.kind === 'subflow') ? group : []);

  return <section className={`lf-root${focusKey ? ' has-focus' : ''}`} aria-label="처리 흐름 현황">
    <header className="lf-head">
      <div><h2>처리 흐름</h2><span className={`lf-state ${snapshot.running ? 'is-on' : ''}`}>{snapshot.running ? <><i /> 진행 중</> : <><CirclePause size={13} /> 전체 일시정지</>}</span><time>{snapshot.clock}</time><span className="lf-mock" title="브라우저 안의 모의 운영 수치입니다. 실제 처리 목록과 연결되어 있지 않습니다.">모의 운영</span></div>
      <div className="lf-actions">
        <button type="button" className={`lf-attn-toggle${attention.length ? ' has-items' : ''}`} aria-expanded={saved.attention} onClick={() => update({ ...saved, attention: !saved.attention })}>
          <TriangleAlert size={14} /> 주의 <b>{attention.length}</b><ChevronDown size={13} className={saved.attention ? '' : 'lf-rot'} />
        </button>
        <button type="button" onClick={() => simulator.setRunning(!snapshot.running)}>{snapshot.running ? <><CirclePause size={14} /> 일시정지</> : <><CirclePlay size={14} /> 재개</>}</button>
        <button type="button" className="is-primary" onClick={() => onOpen(OVERVIEW_ID)}>파이프라인에서 보기 <ArrowRight size={14} /></button>
      </div>
    </header>
    <div className="lf-kpis" role="group" aria-label="처리 지표">
      {kpi(null, '유입', `${t.arrivalsPerMin}`, '/분')}
      {kpi(null, '파생 문서', `${t.derivedPerMin}`, '/분', t.arrivals ? `압축 항목·첨부·내장 개체에서 나온 문서 · 원본 대비 ×${((t.arrivals + t.derived) / t.arrivals).toFixed(2)} · 최대 깊이 ${t.maxDepth}` : '압축 항목·첨부·내장 개체에서 나온 문서')}
      {kpi('processing', '처리 중', `${t.processing}`, '', '마우스를 올리면 처리 중인 단계를 강조합니다')}
      {kpi('queued', '대기', `${t.queued}`, '', '마우스를 올리면 대기가 쌓인 단계를 강조합니다')}
      {kpi('held', '보류 · 사람 확인', `${t.held}`, '', '클릭하면 보류된 단계로 이동합니다', t.held ? ' is-warn' : '')}
      {kpi('failed', '실패', `${t.failed}`, '', '클릭하면 실패한 단계로 이동합니다', t.failed ? ' is-error' : '')}
      {kpi(null, '누적 완료', t.completed.toLocaleString('ko-KR'), '', `분당 완료 ${t.completedPerMin}`)}
    </div>
    <div className="lf-body">
      <ol className="lf-rail" ref={railRef}>{columns.map((group, index) => {
        const table = group.length > 1 && group.some(node => node.data.kind === 'subflow');
        const next = index < columns.length - 1 && <ChevronRight className="lf-arrow" size={14} aria-hidden="true" />;
        if (table) {
          const rows = group.map(node => ({ node, metric: metricOf(node) })).filter((row): row is { node: FlowNode; metric: NodeMetric } => !!row.metric);
          const sum = (key: MetricKey) => rows.reduce((total, row) => total + row.metric[key], 0);
          const worst = rows.map(row => row.metric).sort((a, b) => rank(a) - rank(b))[0];
          const groupMetric = { queued: sum('queued'), processing: sum('processing'), held: sum('held'), failed: sum('failed') };
          const routes = group.filter(node => node.data.kind === 'subflow').length;
          const tipRows = rows.map(row => ({ label: row.node.data.label, metric: row.metric }));
          return <li key={group[0].id} className="is-group">
            <button type="button" className={`lf-node lf-group is-${worst?.status ?? 'idle'}${lit(groupMetric)}`} aria-expanded={saved.formats} aria-label={`형식별 처리 ${routes}개 경로`}
              onClick={() => update({ ...saved, formats: !saved.formats })}
              onMouseEnter={event => showTip(event.currentTarget, { title: '형식별 처리', status: worst?.status, lines: [], rows: tipRows, foot: saved.formats ? '클릭하면 표를 접습니다' : '클릭하면 형식별 표를 펼칩니다' })}
              onFocus={event => showTip(event.currentTarget, { title: '형식별 처리', status: worst?.status, lines: [], rows: tipRows })}
              onMouseLeave={hideTip} onBlur={hideTip}>
              <span className="lf-node-name"><i className={`fx-dot is-${worst?.status ?? 'idle'}`} />형식별 처리<em>{routes}</em><ChevronDown size={13} className={saved.formats ? '' : 'lf-rot'} /></span>
              <span className="lf-spark" aria-hidden="true">{rows.map(row => <i key={row.node.id} className={`is-${row.metric.status}`} style={{ flexGrow: 1 + row.metric.queued + row.metric.processing + row.metric.held + row.metric.failed }} />)}</span>
              <Primary metric={groupMetric} />
            </button>{next}
          </li>;
        }
        return <li key={group[0].id}><div className="lf-stack">{group.map(node => { const metric = metricOf(node); return <button type="button" key={node.id} className={`lf-node is-${metric?.status ?? 'idle'} is-${node.data.kind}${lit(metric)}`}
          onClick={() => open(node)} onMouseEnter={stageTip(node, metric)} onFocus={stageTip(node, metric)} onMouseLeave={hideTip} onBlur={hideTip}>
          <span className="lf-node-name"><i className={`fx-dot is-${metric?.status ?? 'idle'}`} />{node.data.label}</span>
          {metric && (node.data.kind === 'start' ? <span className="lf-primary"><b>{metric.throughput}</b>/분</span> : node.data.kind === 'end' ? <span className="lf-primary"><b>{metric.done.toLocaleString('ko-KR')}</b>건</span> : <Primary metric={metric} />)}
        </button>; })}</div>{next}</li>;
      })}</ol>

      {saved.formats && <div className="lf-drawer" role="region" aria-label="형식별 처리 표">
        <div className="lf-row-head"><span>형식별 처리 경로</span><em>대기</em><em>처리</em><em>보류</em><em>실패</em></div>
        <ul>{formatNodes.map(node => { const metric = metricOf(node); return metric ? <li key={node.id}>
          <button type="button" className={`lf-row is-${metric.status}${node.data.kind === 'exception' ? ' is-exception' : ''}${lit(metric)}`} onClick={() => open(node)}>
            <span>{node.data.label}</span>{node.data.kind === 'exception' ? <em className={metric.held ? 'is-warn' : ''}>보류 {metric.held}</em> : <>
              <em>{metric.queued}</em><em>{metric.processing}</em><em className={metric.held ? 'is-warn' : ''}>{metric.held}</em><em className={metric.failed ? 'is-error' : ''}>{metric.failed}</em></>}
          </button></li> : null; })}</ul>
      </div>}

      {saved.attention && <div className="lf-attention" role="region" aria-label="주의가 필요한 단계">
        {attention.length ? <ul>{attention.map(item => <li key={item.id}><button type="button" onClick={() => onOpen(item.flowId, item.nodeId)}><i className={`fx-dot is-${item.metric.status}`} /><span><b>{item.label}</b><small>{item.flow} · {STATUS_LABEL[item.metric.status]}</small></span><em className={`is-${item.metric.status}`}>{reason(item.metric)}</em><span className="lf-go">개입<ChevronRight size={13} /></span></button></li>)}</ul> : <p>지연·실패·보류된 단계가 없습니다.</p>}
      </div>}
    </div>

    {tip && <div className="lf-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
      <div className="lf-tip-head">{tip.status && <i className={`fx-dot is-${tip.status}`} />}<b>{tip.title}</b>{tip.status && <small>{STATUS_LABEL[tip.status]}</small>}</div>
      {tip.lines.length > 0 && <dl>{tip.lines.map(([label, value, unit]) => <div key={label}><dt>{label}</dt><dd>{value}{unit && <small>{unit}</small>}</dd></div>)}</dl>}
      {tip.rows && <table><thead><tr><th /><th>대기</th><th>처리</th><th>보류</th><th>실패</th></tr></thead><tbody>{tip.rows.map(row => <tr key={row.label}><td><i className={`fx-dot is-${row.metric.status}`} />{row.label}</td><td>{row.metric.queued}</td><td>{row.metric.processing}</td><td className={row.metric.held ? 'is-warn' : ''}>{row.metric.held}</td><td className={row.metric.failed ? 'is-error' : ''}>{row.metric.failed}</td></tr>)}</tbody></table>}
      {tip.foot && <small className="lf-tip-foot">{tip.foot}</small>}
    </div>}
    {focusKey && <span className="lf-sr" role="status">{KEY_LABEL[focusKey]} 단계 강조</span>}
  </section>;

  function open(node: FlowNode) { if (node.data.kind === 'subflow' && node.data.subflow) onOpen(node.data.subflow); else onOpen(OVERVIEW_ID, node.id); }
  function jump(item?: { flowId: string; nodeId: string }) { if (item) onOpen(item.flowId, item.nodeId); }
}

/** 단계마다 가장 먼저 봐야 할 숫자 하나: 실패 → 보류 → 대기가 더 많으면 대기 → 처리 중. */
function Primary({ metric }: { metric: Pick<NodeMetric, MetricKey> }) {
  if (metric.failed > 0) return <span className="lf-primary is-error"><b>{metric.failed}</b>실패</span>;
  if (metric.held > 0) return <span className="lf-primary is-warn"><b>{metric.held}</b>보류</span>;
  if (metric.queued > metric.processing) return <span className="lf-primary"><b>{metric.queued}</b>대기</span>;
  return <span className="lf-primary"><b>{metric.processing}</b>처리 중</span>;
}
const rank = (metric: NodeMetric) => ({ error: 0, warn: 1, paused: 2, busy: 3, idle: 4 })[metric.status];
function reason(metric: NodeMetric) { return metric.paused ? '일시정지' : metric.failed ? `실패 ${metric.failed}` : metric.held ? `보류 ${metric.held}` : `대기 ${metric.queued}`; }
