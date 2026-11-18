import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import dagre from '@dagrejs/dagre';
import { ArrowDown, ArrowLeft, ArrowRight } from 'lucide-react';
import { Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react';
import type { Edge, Node, NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { LineageData, LnEntry, LnFamily, RefState } from '../api/lineage';
import { CHILD_KIND } from '../StructurePanel';
import { LATEST_META, STATE_META, groupIncoming, groupOutgoing, holderText, refsFrom, refsInto, subtree } from './model';
import type { RefGroup } from './model';
import { useHoverProps, useTip } from './Tip';
import type { Pin } from './FamilyView';
import { EntryTip, InstanceTip, RefTip } from './FamilyView';

type Role = 'center' | 'child' | 'in' | 'out' | 'ghost' | 'more';
type GData = { label: string; sub: string; tone: string; role: Role; pin: Pin | null; tip: () => ReactNode; dim: boolean; hl: boolean; onHover: (id: string | null) => void; onActivate: () => void };
type GNode = Node<GData, 'ln'>;
type EdgeKind = 'contain' | RefState;
type GEdge = Edge<{ kind: EdgeKind; groups: RefGroup[] }>;

const W = 198, H = 48, CW = 234, CH = 58, GAP = 122, ROW = H + 16, MAX_TREE = 60, MAX_SIDE = 14;
const EDGE_STYLE: Record<EdgeKind, { stroke: string; dash?: string; label: string }> = {
  contain: { stroke: '#b3bccb', label: '포함' }, linked: { stroke: '#4f7fc2', label: '참조' }, outdated: { stroke: '#c4862a', dash: '6 4', label: '구버전 참조' },
  missing: { stroke: '#c0504a', dash: '2 4', label: '대상 미발견' }, ambiguous: { stroke: '#8a7fd8', dash: '2 4', label: '후보 여러 개' }, external: { stroke: '#9aa4b2', dash: '2 4', label: '외부 주소' },
};
const WORST: RefState[] = ['missing', 'outdated', 'ambiguous', 'linked', 'external'];
const toneOf = (state: RefState) => STATE_META[state].tone;

function LnNode({ id, data, positionAbsoluteX, positionAbsoluteY, width, height }: NodeProps<GNode>) {
  const hover = useHoverProps();
  const flow = useReactFlow();
  const props = hover(`g:${id}`, data.tip, on => data.onHover(on ? id : null));
  return <>
    <Handle type="target" position={Position.Left} id="l" isConnectable={false} />
    <Handle type="target" position={Position.Top} id="t" isConnectable={false} />
    <button className={`ln-gnode is-${data.role} is-${data.tone}${data.dim ? ' is-dim' : ''}${data.hl ? ' is-hl' : ''}`} onClick={data.onActivate} {...props}
      onFocus={event => { props.onFocus(event); try { flow.setCenter(positionAbsoluteX + (width ?? W) / 2, positionAbsoluteY + (height ?? H) / 2, { zoom: flow.getZoom(), duration: 150 }); } catch { /* 화면 이동이 안 돼도 선택은 동작한다. */ } }}>
      <b>{data.label}</b>{data.sub && <small>{data.sub}</small>}
    </button>
    <Handle type="source" position={Position.Right} id="r" isConnectable={false} />
    <Handle type="source" position={Position.Bottom} id="b" isConnectable={false} />
  </>;
}
const nodeTypes = { ln: LnNode };

type Props = { data: LineageData; family: LnFamily; entry: LnEntry; onPin: (pin: Pin) => void; onFamily: (id: string) => void };

export function LineageGraph(props: Props) {
  return <div className="ln-graph-wrap">
    <div className="ln-graph" aria-label="관계 그래프: 가운데가 선택한 판, 아래가 포함된 파일, 왼쪽이 이 문서를 가리키는 문서, 오른쪽이 이 문서가 가리키는 문서">
      <ReactFlowProvider key={`${props.family.id}:${props.entry.id}`}><GraphCanvas {...props} /></ReactFlowProvider>
    </div>
    <div className="ln-graph-context" aria-label="그래프 배치">
      <span><ArrowLeft size={15} aria-hidden="true" />들어오는 참조</span>
      <span><ArrowDown size={15} aria-hidden="true" />포함된 파일</span>
      <span><ArrowRight size={15} aria-hidden="true" />나가는 참조</span>
    </div>
    <ul className="ln-legend" aria-label="선 종류">
      {(['contain', 'linked', 'outdated', 'missing', 'ambiguous'] as EdgeKind[]).map(kind => <li key={kind}><svg width="26" height="8" aria-hidden="true"><line x1="1" y1="4" x2="25" y2="4" stroke={EDGE_STYLE[kind].stroke} strokeWidth="2" strokeDasharray={EDGE_STYLE[kind].dash} /></svg>{EDGE_STYLE[kind].label}</li>)}
    </ul>
  </div>;
}

function GraphCanvas({ data, family, entry, onPin }: Props) {
  const tip = useTip();
  const [hovered, setHovered] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const base = useMemo(() => buildGraph(data, family, entry), [data, family, entry]);
  const { nodes, edges } = useMemo(() => {
    let active: Set<string> | null = null; let activeEdges: Set<string> | null = null;
    if (hovered || hoverEdge) {
      active = new Set(); activeEdges = new Set();
      for (const edge of base.edges) {
        if (edge.id === hoverEdge || (hovered && (edge.source === hovered || edge.target === hovered))) { activeEdges.add(edge.id); active.add(edge.source); active.add(edge.target); }
      }
      if (hovered) active.add(hovered);
    }
    return {
      nodes: base.nodes.map(node => ({
        id: node.id, type: 'ln' as const, position: node.position, width: node.w, height: node.h, draggable: false, selectable: false, className: 'nopan', style: { pointerEvents: 'all' as const },
        data: { label: node.label, sub: node.sub, tone: node.tone, role: node.role, pin: node.pin, tip: node.tip, dim: !!active && !active.has(node.id), hl: !!active && active.has(node.id),
          onHover: (on: string | null) => setHovered(on ? node.id : null),
          onActivate: () => { if (node.pin) onPin(node.pin); } },
      })) as GNode[],
      edges: base.edges.map(edge => {
        const style = EDGE_STYLE[edge.data!.kind];
        const dim = !!activeEdges && !activeEdges.has(edge.id);
        return { ...edge, style: { stroke: style.stroke, strokeWidth: activeEdges?.has(edge.id) ? 2.6 : 1.6, strokeDasharray: style.dash, opacity: dim ? 0.15 : 1 },
          markerEnd: edge.data!.kind === 'contain' ? undefined : { type: MarkerType.ArrowClosed, color: style.stroke, width: 16, height: 16 },
          labelStyle: { fontSize: 11, fill: '#4f5b6c', opacity: dim ? 0.2 : 1 }, labelBgStyle: { fill: '#fff', opacity: dim ? 0.2 : 0.9 } } as GEdge;
      }),
    };
  }, [base, hovered, hoverEdge, onPin]);
  return <ReactFlow<GNode, GEdge> nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }} minZoom={0.2} maxZoom={1.8}
    ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': '확대', 'controls.zoomOut.ariaLabel': '축소', 'controls.fitView.ariaLabel': '전체 그래프 보기' }}
    nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable={false} edgesFocusable={false} proOptions={{ hideAttribution: true }}
    onEdgeMouseEnter={(event, edge) => { setHoverEdge(edge.id); const groups = edge.data?.groups ?? []; tip.show(`edge:${edge.id}`, { x: event.clientX, y: event.clientY }, groups.length ? <RefTip data={data} group={groups[0]} /> : <span>{EDGE_STYLE[edge.data?.kind ?? 'contain'].label}</span>); }}
    onEdgeMouseLeave={(_, edge) => { setHoverEdge(null); tip.hide(`edge:${edge.id}`); }}
    onEdgeClick={(_, edge) => { const group = edge.data?.groups[0]; if (group) onPin({ type: 'group', id: group.key, group }); }}>
    <Controls showInteractive={false} position="bottom-right" aria-label="그래프 확대·축소" />
  </ReactFlow>;
}

type BNode = { id: string; position: { x: number; y: number }; w: number; h: number; label: string; sub: string; tone: string; role: Role; pin: Pin | null; tip: () => ReactNode };

/** 가운데: 선택한 판, 아래: 포함된 파일(dagre 정렬), 왼쪽: 이 문서를 가리키는 문서, 오른쪽: 이 문서가 가리키는 문서. */
export function buildGraph(data: LineageData, family: LnFamily, entry: LnEntry) {
  const rootId = entry.primary;
  const all = subtree(data.instances, rootId);
  const treeIds = all.slice(0, MAX_TREE);
  const inTree = new Set(treeIds);
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: 'TB', nodesep: 16, ranksep: 46, marginx: 0, marginy: 0 });
  graph.setDefaultEdgeLabel(() => ({}));
  treeIds.forEach(id => graph.setNode(id, id === rootId ? { width: CW, height: CH } : { width: W, height: H }));
  treeIds.forEach(id => { const parent = data.instances[id].parent; if (id !== rootId && parent && inTree.has(parent)) graph.setEdge(parent, id); });
  dagre.layout(graph);
  const origin = graph.node(rootId) as { x: number; y: number };
  const nodes: BNode[] = [];
  const edges: GEdge[] = [];
  const meta = LATEST_META[family.latest.status];
  for (const id of treeIds) {
    const point = graph.node(id) as { x: number; y: number };
    const node = data.instances[id];
    const center = id === rootId;
    const w = center ? CW : W, h = center ? CH : H;
    const childFamily = !center && node.family ? data.entries[node.entry ?? '']?.label : '';
    nodes.push({ id: `i:${id}`, position: { x: point.x - origin.x - w / 2, y: point.y - origin.y - h / 2 }, w, h, role: center ? 'center' : 'child',
      label: center ? family.title : node.name, sub: center ? `${entry.label} · ${node.name}` : `${CHILD_KIND[node.kind] ?? node.kind}${childFamily ? ` · ${childFamily}` : ''}`,
      tone: center ? meta.tone : node.flags.some(flag => ['encrypted', 'drm-suspect', 'unreadable'].includes(flag)) ? 'error' : 'muted',
      pin: { type: center ? 'entry' : 'instance', id: center ? entry.id : id } as Pin,
      tip: center ? () => <EntryTip data={data} family={family} entry={entry} /> : () => <InstanceTip data={data} node={node} /> });
    const parent = node.parent;
    if (!center && parent && inTree.has(parent)) edges.push({ id: `c:${parent}>${id}`, source: `i:${parent}`, target: `i:${id}`, sourceHandle: 'b', targetHandle: 't', type: 'smoothstep', data: { kind: 'contain', groups: [] } });
  }
  if (all.length > treeIds.length) {
    const lowest = Math.max(...nodes.map(node => node.position.y + node.h));
    nodes.push({ id: 'more:tree', position: { x: -W / 2, y: lowest + 24 }, w: W, h: H, role: 'more', label: `포함 파일 ${all.length - treeIds.length}개 더`, sub: '계층 보기에서 모두 확인', tone: 'muted', pin: null, tip: () => <span>그래프에는 앞의 {MAX_TREE}개만 그립니다.</span> });
  }
  const minX = Math.min(...nodes.map(node => node.position.x));
  const maxX = Math.max(...nodes.map(node => node.position.x + node.w));

  // 오른쪽: 이 판(포함 파일 포함)이 가리키는 대상
  const outgoing = groupOutgoing(data, refsFrom(data, rootId)).filter(group => group.state !== 'external');
  type Side = { id: string; label: string; sub: string; states: RefState[]; groups: RefGroup[]; pin: Pin | null; tip: () => ReactNode; family: string | null };
  const right = new Map<string, Side>();
  const sideFamily = (fid: string, sub: string): Omit<Side, 'states' | 'groups'> => { const target = data.families.find(item => item.id === fid)!; return { id: `f:${fid}`, label: target.title, sub, pin: { type: 'family', id: fid }, family: fid, tip: () => <FamilyNodeTip data={data} family={target} /> }; };
  for (const group of outgoing) {
    const base: Omit<Side, 'states' | 'groups'> = group.family ? sideFamily(group.family, group.sub)
      : group.instance ? { id: `x:${group.instance}`, label: group.text, sub: group.sub || '포함된 파일', pin: { type: 'instance', id: group.instance }, family: null, tip: () => <InstanceTip data={data} node={data.instances[group.instance!]} /> }
      : { id: `g:${group.state}:${group.text}`, label: group.text, sub: STATE_META[group.state].label, pin: { type: 'group', id: group.key, group }, family: null, tip: () => <RefTip data={data} group={group} /> };
    const side = right.get(base.id) ?? { ...base, states: [], groups: [] };
    if (side.sub !== group.sub && group.family) side.sub = '여러 판';
    side.states.push(group.state); side.groups.push(group);
    right.set(base.id, side);
  }
  // 왼쪽: 이 문서군을 가리키는 문서(같은 문서군이 오른쪽에도 있으면 오른쪽 노드를 함께 쓴다)
  const incoming = groupIncoming(data, refsInto(data, family));
  const left = new Map<string, Side>();
  for (const group of incoming) {
    const base: Omit<Side, 'states' | 'groups'> = group.sourceFamily ? sideFamily(group.sourceFamily, group.sub)
      : { id: `s:${group.sourceRoot}`, label: group.text, sub: group.sub, pin: { type: 'instance', id: group.sourceRoot }, family: null, tip: () => <InstanceTip data={data} node={data.instances[group.sourceRoot]} /> };
    const side = right.get(base.id) ?? left.get(base.id) ?? { ...base, states: [], groups: [] };
    side.states.push(group.state); side.groups.push(group);
    if (!right.has(base.id)) left.set(base.id, side);
  }
  const place = (items: Side[], x: number, role: Role) => {
    const shown = items.slice(0, MAX_SIDE);
    const total = shown.length + (items.length > MAX_SIDE ? 1 : 0);
    shown.forEach((side, index) => {
      const worst = WORST.find(state => side.states.includes(state)) ?? 'linked';
      nodes.push({ id: side.id, position: { x, y: (index - (total - 1) / 2) * ROW - H / 2 }, w: W, h: H, role: side.family || side.id.startsWith('x:') || side.id.startsWith('s:') ? role : 'ghost',
        label: side.label, sub: side.sub, tone: toneOf(worst), pin: side.pin, tip: side.tip });
    });
    if (items.length > MAX_SIDE) nodes.push({ id: `more:${role}`, position: { x, y: (total - 1 - (total - 1) / 2) * ROW - H / 2 }, w: W, h: H, role: 'more', label: `${items.length - MAX_SIDE}개 더`, sub: '계층 보기에서 모두 확인', tone: 'muted', pin: null, tip: () => <span>그래프에는 {MAX_SIDE}개까지만 그립니다.</span> });
    return new Set(shown.map(side => side.id));
  };
  const placedRight = place([...right.values()], maxX + GAP, 'out');
  const placedLeft = place([...left.values()], minX - GAP - W, 'in');
  const edgeMap = new Map<string, GEdge>();
  const addEdge = (id: string, source: string, target: string, kind: RefState, group: RefGroup, count: number) => {
    const existing = edgeMap.get(id);
    if (existing) { existing.data!.groups.push(group); existing.label = String(Number(existing.label ?? 1) + count); return; }
    edgeMap.set(id, { id, source, target, sourceHandle: 'r', targetHandle: 'l', type: 'default', label: String(count), data: { kind, groups: [group] } });
  };
  for (const side of right.values()) {
    if (!placedRight.has(side.id)) continue;
    for (const group of side.groups) {
      if (group.key.startsWith('i|')) { addEdge(`in:${side.id}:${group.state}`, side.id, `i:${rootId}`, group.state, group, group.refs.length); continue; }
      for (const ref of group.refs) {
        const holder = holderInTree(data, ref.source, inTree, rootId);
        addEdge(`out:${holder}>${side.id}:${group.state}`, `i:${holder}`, side.id, group.state, group, 1);
      }
    }
  }
  for (const side of left.values()) {
    if (!placedLeft.has(side.id)) continue;
    for (const group of side.groups) addEdge(`in:${side.id}:${group.state}`, side.id, `i:${rootId}`, group.state, group, group.refs.length);
  }
  for (const edge of edgeMap.values()) { if (edge.label === '1') edge.label = undefined; edges.push(edge); }
  return { nodes, edges };
}

function holderInTree(data: LineageData, source: string, inTree: Set<string>, rootId: string) {
  let current: string | null = source;
  while (current && !inTree.has(current)) current = data.instances[current]?.parent ?? null;
  return current ?? rootId;
}

function FamilyNodeTip({ data, family }: { data: LineageData; family: LnFamily }) {
  const latest = data.entries[family.latest.entry];
  const holder = holderText(data, latest.primary);
  return <>
    <strong>{family.title}</strong>
    <span>{LATEST_META[family.latest.status].label} · {latest.label}{holder ? ` · ${holder} 안` : ''}</span>
    <span className="ln-tip-muted">클릭하면 상세를 고정하고, 상세 창에서 이 문서군으로 이동할 수 있습니다.</span>
  </>;
}
