import { createContext, memo, useContext, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { EdgeLabelRenderer, getSmoothStepPath, Handle, NodeResizer, Position, useInternalNode } from '@xyflow/react';
import type { EdgeProps, InternalNode, NodeProps } from '@xyflow/react';
import { CircleCheckBig, CirclePause, Maximize2, CirclePlay, Cog, Database, FileText, GitFork, Inbox, Link2, Mail, Plus, RefreshCcw, ScanSearch, ScanText, ShieldCheck, Split, StickyNote, Table2, TriangleAlert, Type, UserCheck, Workflow } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { NodeMetric } from './flowSim';
import type { EditorMode, FlowDirection, FlowEdge, FlowNode, FlowNodeData, NodeKind, TaskIcon } from './flowTypes';

export const KIND_META: Record<NodeKind, { label: string; icon: LucideIcon; hint: string }> = {
  start: { label: '시작', icon: CirclePlay, hint: '문서가 들어오는 지점' },
  task: { label: '작업', icon: Cog, hint: '파싱·변환·추출 같은 처리 단계' },
  gateway: { label: '조건 분기', icon: GitFork, hint: '형식·조건에 따라 경로를 나눔' },
  review: { label: '사람 검토', icon: UserCheck, hint: '담당자 승인이 필요한 지점' },
  exception: { label: '예외 대기열', icon: TriangleAlert, hint: '실패·미지정 문서를 모아 두는 곳' },
  store: { label: '데이터 저장', icon: Database, hint: '인덱스·저장소 적재' },
  subflow: { label: '하위 흐름', icon: Workflow, hint: '다른 흐름을 한 단계로 묶음' },
  end: { label: '종료', icon: CircleCheckBig, hint: '흐름이 끝나는 지점' },
  note: { label: '메모', icon: StickyNote, hint: '캔버스에 설명을 남김' },
};
export const TASK_ICON: Record<TaskIcon, { label: string; icon: LucideIcon }> = {
  collect: { label: '수집', icon: Inbox }, detect: { label: '판별 · 확인', icon: ScanSearch }, parse: { label: '파싱', icon: FileText },
  ocr: { label: 'OCR', icon: ScanText }, convert: { label: '변환', icon: RefreshCcw }, sheet: { label: '시트 · 표', icon: Table2 },
  split: { label: '분리 · 재투입', icon: Split }, mail: { label: '메일', icon: Mail }, text: { label: '텍스트', icon: Type },
  relation: { label: '참조 추출', icon: Link2 }, quality: { label: '품질 검사', icon: ShieldCheck }, index: { label: '적재', icon: Database }, custom: { label: '일반 작업', icon: Cog },
};
export const STATUS_LABEL = { idle: '대기 없음', busy: '처리 중', warn: '확인 필요', error: '실패 있음', paused: '일시정지' } as const;

export type FlowUI = {
  mode: EditorMode;
  direction: FlowDirection;
  metrics: Record<string, NodeMetric | undefined>;
  traffic: Record<string, number>;
  forcedEdges: Set<string>;
  flowTitles: Record<string, string>;
  flowFormats: (flowId: string) => string[];
  editingId: string | null;
  setEditingId: (id: string | null) => void;
  rename: (id: string, label: string) => void;
  openSubflow: (flowId: string) => void;
  hoveredEdge: string | null;
  setHoveredEdge: (id: string | null) => void;
  dropEdge: string | null;
  requestInsert: (edgeId: string, rect: DOMRect) => void;
};
export const FlowUIContext = createContext<FlowUI | null>(null);
const useFlowUI = () => { const value = useContext(FlowUIContext); if (!value) throw new Error('FlowUIContext 누락'); return value; };

const SIDES = [['top', Position.Top], ['right', Position.Right], ['bottom', Position.Bottom], ['left', Position.Left]] as const;
function Handles({ connectable }: { connectable: boolean }) {
  return <>{SIDES.map(([id, position]) => <Handle key={id} id={id} type="source" position={position} className="fx-handle" isConnectable={connectable} />)}</>;
}

function Label({ id, data }: { id: string; data: FlowNodeData }) {
  const ui = useFlowUI();
  const input = useRef<HTMLInputElement>(null);
  const editing = ui.editingId === id;
  useEffect(() => { if (editing) input.current?.select(); }, [editing]);
  if (!editing) return <b className="fx-label">{data.label}</b>;
  const commit = () => { const value = input.current?.value.trim(); if (value) ui.rename(id, value); ui.setEditingId(null); };
  return <input ref={input} className="fx-label-input nodrag" defaultValue={data.label} aria-label="노드 이름" onBlur={commit} onKeyDown={event => { event.stopPropagation(); if (event.key === 'Enter') commit(); if (event.key === 'Escape') ui.setEditingId(null); }} />;
}

const n = (value: number) => value.toLocaleString('ko-KR');
function Counters({ metric, kind }: { metric: NodeMetric; kind: NodeKind }) {
  if (kind === 'exception') return <div className="fx-counters"><span className={metric.held ? 'is-warn' : ''}>보류 <b>{n(metric.held)}</b></span>{metric.held > 0 && <span>최장 <b>{wait(metric.oldestWait)}</b></span>}</div>;
  return <div className="fx-counters">
    <span className={metric.queued >= Math.max(8, metric.capacity * 4) ? 'is-warn' : ''}>대기 <b>{n(metric.queued)}</b></span>
    <span>처리 <b>{metric.processing}</b>{kind !== 'subflow' && <i>/{metric.capacity}</i>}</span>
    {(metric.held > 0 || kind === 'review') && <span className={metric.held ? 'is-warn' : ''}>보류 <b>{metric.held}</b></span>}
    {metric.failed > 0 && <span className="is-error">실패 <b>{metric.failed}</b></span>}
    {metric.spawned > 0 && <span className="is-spawn" title="최근 1분 동안 만든 하위 문서">파생 <b>{metric.spawned}</b></span>}
    <em>{metric.throughput}<small>/분</small></em>
  </div>;
}
export const wait = (seconds: number) => seconds >= 60 ? `${Math.floor(seconds / 60)}분 ${Math.round(seconds % 60)}초` : `${Math.round(seconds)}초`;

function DesignMeta({ data, flowFormats }: { data: FlowNodeData; flowFormats: (id: string) => string[] }) {
  if (data.kind === 'subflow') {
    const formats = data.subflow ? flowFormats(data.subflow) : [];
    return <div className="fx-meta">{formats.length ? formats.slice(0, 5).map(format => <span className="fx-chip" key={format}>{format}</span>) : <span className="fx-muted">{data.subflow ? '연결된 형식 없음' : '하위 흐름 미지정'}</span>}{formats.length > 5 && <span className="fx-chip">+{formats.length - 5}</span>}</div>;
  }
  if (data.kind === 'review') return <div className="fx-meta"><span>보류 {Math.round((data.holdRate ?? 0) * 100)}%</span><i />{data.assignee && <span>{data.assignee}</span>}</div>;
  if (data.kind === 'exception') return <div className="fx-meta"><span>{data.assignee ?? '담당자 확인'}</span></div>;
  return <div className="fx-meta"><span>{KIND_META[data.kind].label}</span><i /><span>동시 {data.capacity ?? '-'}</span><i /><span>{data.duration ?? '-'}초</span>{(data.failRate ?? 0) > 0 && <><i /><span>실패 {Math.round((data.failRate ?? 0) * 1000) / 10}%</span></>}{(data.spawnRate ?? 0) > 0 && <><i /><span className="fx-spawn">하위 문서 ≤{data.spawnMax ?? 1}</span></>}</div>;
}

export const FlowNodeView = memo(function FlowNodeView({ id, data, selected }: NodeProps<FlowNode>) {
  const ui = useFlowUI();
  const monitor = ui.mode === 'monitor';
  const metric = monitor ? ui.metrics[id] : undefined;
  const status = metric?.status ?? 'idle';
  const kind = data.kind;
  const Icon = kind === 'task' || kind === 'store' ? TASK_ICON[data.icon ?? 'custom'].icon : KIND_META[kind].icon;
  const state = `${selected ? ' is-selected' : ''}${monitor ? ` is-${status}` : ''}${metric?.bypass ? ' is-bypass' : ''}`;
  const open = () => { if (kind === 'subflow' && data.subflow) ui.openSubflow(data.subflow); };

  if (kind === 'note') return <div className={`fx-note${state}`}>
    <NodeResizer isVisible={!!selected && !monitor} minWidth={140} minHeight={64} color="#7468ce" />
    {ui.editingId === id ? <textarea className="fx-note-input nodrag" autoFocus defaultValue={data.label} aria-label="메모 내용" onBlur={event => { ui.rename(id, event.target.value.trim() || '메모'); ui.setEditingId(null); }} onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') ui.setEditingId(null); }} /> : <p>{data.label}</p>}
  </div>;

  if (kind === 'gateway') {
    const forced = metric?.forced;
    return <div className={`fx-gateway${state}`}>
      <div className="fx-gateway-shape"><GitFork size={20} /></div>
      <div className="fx-gateway-label"><Label id={id} data={data} />{forced && <span className="fx-forced">경로 고정</span>}{metric?.paused && <span className="fx-forced">일시정지</span>}</div>
      <Handles connectable={!monitor} />
    </div>;
  }

  if (kind === 'start' || kind === 'end') return <div className={`fx-terminal fx-${kind}${state}`}>
    <Icon size={16} />
    <Label id={id} data={data} />
    {metric && <span className="fx-terminal-metric">{kind === 'start' ? `${metric.throughput}/분` : `${n(metric.done)}건`}</span>}
    <Handles connectable={!monitor} />
  </div>;

  if (kind === 'subflow') {
    const formats = data.subflow ? ui.flowFormats(data.subflow) : [];
    return <div className={`fx-box fx-subflow${state}`}>
      <div className="fx-sub-head"><span className="fx-icon"><Icon size={15} /></span>{!monitor && <span className="fx-sub-tag">하위 흐름</span>}{metric && metric.spawned > 0 && <span className="fx-sub-spawn" title="최근 1분 동안 만든 하위 문서">파생 {metric.spawned}</span>}<button className="fx-subflow-open nodrag" onClick={open} disabled={!data.subflow} aria-label={`${data.label} 하위 흐름 열기`} title="하위 흐름 열기"><Maximize2 size={12} /></button>{monitor && <span className={`fx-status is-${status}`} title={STATUS_LABEL[status]}>{status === 'paused' ? <CirclePause size={14} /> : <i />}</span>}</div>
      <Label id={id} data={data} />
      {metric ? <div className="fx-sub-grid">
        <span className={metric.queued >= 12 ? 'is-warn' : ''}>대기<b>{n(metric.queued)}</b></span><span>처리<b>{metric.processing}</b></span>
        <span className={metric.held ? 'is-warn' : ''}>보류<b>{metric.held}</b></span><span className={metric.failed ? 'is-error' : ''}>실패<b>{metric.failed}</b></span>
      </div> : <div className="fx-sub-formats">{formats.length ? formats.slice(0, 6).map(format => <span className="fx-chip" key={format}>{format}</span>) : <span className="fx-muted">{data.subflow ? '연결된 형식 없음' : '흐름 미지정'}</span>}</div>}
      <Handles connectable={!monitor} />
    </div>;
  }

  return <div className={`fx-box fx-${kind}${state}`}>
    <div className="fx-box-head">
      <span className="fx-icon"><Icon size={16} /></span>
      <div className="fx-titles"><Label id={id} data={data} /><small>{data.engine || KIND_META[kind].label}</small></div>
      {monitor && <span className={`fx-status is-${status}`} title={STATUS_LABEL[status]}>{status === 'paused' ? <CirclePause size={14} /> : <i />}</span>}
    </div>
    {metric ? <Counters metric={metric} kind={kind} /> : <DesignMeta data={data} flowFormats={ui.flowFormats} />}
    {metric?.bypass && <span className="fx-flag">우회 중</span>}
    <Handles connectable={!monitor} />
  </div>;
});

/* ---------- 연결선 ---------- */
type Box = { x: number; y: number; w: number; h: number };
const boxOf = (node: InternalNode): Box => ({ x: node.internals.positionAbsolute.x, y: node.internals.positionAbsolute.y, w: node.measured.width ?? node.width ?? 0, h: node.measured.height ?? node.height ?? 0 });
const sidePoint = (box: Box, side: Position) => side === Position.Top ? { x: box.x + box.w / 2, y: box.y } : side === Position.Bottom ? { x: box.x + box.w / 2, y: box.y + box.h } : side === Position.Left ? { x: box.x, y: box.y + box.h / 2 } : { x: box.x + box.w, y: box.y + box.h / 2 };

/** draw.io처럼 노드 위치에 따라 연결면을 고르는 플로팅 연결선. */
export function edgeRoute(source: InternalNode, target: InternalNode, direction: FlowDirection, branchy: boolean) {
  const s = boxOf(source), t = boxOf(target);
  const dx = (t.x + t.w / 2) - (s.x + s.w / 2), dy = (t.y + t.h / 2) - (s.y + s.h / 2);
  let from: Position, to: Position;
  if (direction === 'TB') {
    if (t.y >= s.y + s.h + 4) { from = branchy && Math.abs(dx) > s.w / 2 + 4 ? (dx > 0 ? Position.Right : Position.Left) : Position.Bottom; to = Position.Top; }
    else if (t.y + t.h <= s.y - 4) { from = to = dx < -s.w / 2 ? Position.Left : Position.Right; }
    else { from = dx > 0 ? Position.Right : Position.Left; to = dx > 0 ? Position.Left : Position.Right; }
  } else {
    if (t.x >= s.x + s.w + 4) { from = branchy && Math.abs(dy) > s.h / 2 + 4 ? (dy > 0 ? Position.Bottom : Position.Top) : Position.Right; to = Position.Left; }
    else if (t.x + t.w <= s.x - 4) { from = to = dy < -s.h / 2 ? Position.Top : Position.Bottom; }
    else { from = dy > 0 ? Position.Bottom : Position.Top; to = dy > 0 ? Position.Top : Position.Bottom; }
  }
  const a = sidePoint(s, from), b = sidePoint(t, to);
  const [path] = getSmoothStepPath({ sourceX: a.x, sourceY: a.y, sourcePosition: from, targetX: b.x, targetY: b.y, targetPosition: to, borderRadius: 10, offset: 22 });
  const points = pathPoints(path);
  return { path, points, mid: pointAlong(points, 0.5), end: b, endSide: to };
}
export function pathPoints(path: string) {
  const values = (path.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g) ?? []).map(Number);
  const points: { x: number; y: number }[] = [];
  for (let i = 0; i + 1 < values.length; i += 2) points.push({ x: values[i], y: values[i + 1] });
  return points;
}
function pointAlong(points: { x: number; y: number }[], ratio: number) {
  if (points.length < 2) return points[0] ?? { x: 0, y: 0 };
  const lengths = points.slice(1).map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let left = lengths.reduce((sum, value) => sum + value, 0) * ratio;
  for (let i = 0; i < lengths.length; i++) { if (left <= lengths[i]) { const k = lengths[i] ? left / lengths[i] : 0; return { x: points[i].x + (points[i + 1].x - points[i].x) * k, y: points[i].y + (points[i + 1].y - points[i].y) * k }; } left -= lengths[i]; }
  return points[points.length - 1];
}
export function distanceToPath(point: { x: number; y: number }, points: { x: number; y: number }[]) {
  let best = Infinity;
  for (let i = 0; i + 1 < points.length; i++) {
    const a = points[i], b = points[i + 1]; const vx = b.x - a.x, vy = b.y - a.y; const len = vx * vx + vy * vy;
    const k = len ? Math.max(0, Math.min(1, ((point.x - a.x) * vx + (point.y - a.y) * vy) / len)) : 0;
    best = Math.min(best, Math.hypot(point.x - (a.x + vx * k), point.y - (a.y + vy * k)));
  }
  return best;
}

export function FlowEdgeView({ id, source, target, data, selected }: EdgeProps<FlowEdge>) {
  const ui = useFlowUI();
  const s = useInternalNode<FlowNode>(source), t = useInternalNode<FlowNode>(target);
  if (!s || !t) return null;
  const exception = data?.kind === 'exception';
  const route = edgeRoute(s, t, ui.direction, s.data.kind === 'gateway' || exception);
  const monitor = ui.mode === 'monitor';
  const traffic = monitor ? ui.traffic[id] ?? 0 : 0;
  const forced = monitor && ui.forcedEdges.has(id);
  const dropping = ui.dropEdge === id;
  const showInsert = !monitor && (selected || ui.hoveredEdge === id || dropping);
  const variant = selected || dropping ? '-selected' : exception ? '-exception' : '';
  const label = data?.label;
  const labelAt = labelPosition(route.end, route.endSide);
  return <>
    <path d={route.path} fill="none" className={`react-flow__edge-path fx-edge${exception ? ' is-exception' : ''}${selected ? ' is-selected' : ''}${dropping ? ' is-drop' : ''}${forced ? ' is-forced' : ''}`} markerEnd={`url(#fx-arrow${variant})`} />
    {traffic > 0 && <path d={route.path} fill="none" className={`fx-edge-flow${exception ? ' is-exception' : ''}`} style={{ strokeWidth: 2 + Math.min(3, traffic / 8) }} />}
    <path d={route.path} fill="none" className="react-flow__edge-interaction" strokeOpacity={0} strokeWidth={20} />
    <EdgeLabelRenderer>
      {(label || traffic > 0) && <div className={`fx-edge-label${exception ? ' is-exception' : ''}${forced ? ' is-forced' : ''}${label ? '' : ' is-count'}`} style={{ transform: label ? labelAt : `translate(-50%, -50%) translate(${route.mid.x}px, ${route.mid.y}px)` }}>
        {label}{traffic > 0 && <b>{label ? ' · ' : ''}{traffic}</b>}
      </div>}
      {showInsert && <button className="fx-edge-insert nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${route.mid.x}px, ${route.mid.y}px)` }} aria-label="이 연결 사이에 단계 삽입" title="이 연결 사이에 단계 삽입"
        onMouseEnter={() => ui.setHoveredEdge(id)} onMouseLeave={() => ui.setHoveredEdge(null)} onClick={event => ui.requestInsert(id, event.currentTarget.getBoundingClientRect())}><Plus size={13} /></button>}
    </EdgeLabelRenderer>
  </>;
}
function labelPosition(point: { x: number; y: number }, side: Position) {
  if (side === Position.Top) return `translate(-50%, -100%) translate(${point.x}px, ${point.y - 8}px)`;
  if (side === Position.Bottom) return `translate(-50%, 0) translate(${point.x}px, ${point.y + 8}px)`;
  if (side === Position.Left) return `translate(-100%, -120%) translate(${point.x - 8}px, ${point.y}px)`;
  return `translate(0, -120%) translate(${point.x + 8}px, ${point.y}px)`;
}

export function ArrowDefs() {
  const marker = (id: string, color: string) => <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="11" markerHeight="11" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill={color} /></marker>;
  return <svg className="fx-defs" aria-hidden="true"><defs>{marker('fx-arrow', '#8b97ab')}{marker('fx-arrow-exception', '#d08a2e')}{marker('fx-arrow-selected', '#6c5fd0')}</defs></svg>;
}

export function Kbd({ children }: { children: ReactNode }) { return <kbd className="fx-kbd">{children}</kbd>; }
