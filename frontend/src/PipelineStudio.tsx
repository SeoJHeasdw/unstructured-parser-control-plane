import { useCallback, useEffect, useMemo, useReducer, useRef, useState, useSyncExternalStore } from 'react';
import { applyEdgeChanges, applyNodeChanges, Background, BackgroundVariant, ConnectionLineType, ConnectionMode, MiniMap, Panel, ReactFlow, ReactFlowProvider, SelectionMode, useReactFlow, useViewport } from '@xyflow/react';
import type { Connection, EdgeChange, FinalConnectionState, FitViewOptions, NodeChange, NodeMouseHandler, XYPosition } from '@xyflow/react';
import { Activity, ChevronRight, CirclePause, CirclePlay, LayoutGrid, ListTree, Maximize, Minus, PanelBottomClose, PanelBottomOpen, PanelRightClose, PanelRightOpen, PenTool, Plus, Redo2, RotateCcw, Rows3, TriangleAlert, Undo2, X } from 'lucide-react';
import '@xyflow/react/dist/style.css';
import './flow/flow.css';
import { listLiveDocuments } from './api/live';
import { ArrowDefs, edgeRoute, distanceToPath, FlowEdgeView, FlowNodeView, FlowUIContext, KIND_META } from './flow/FlowCanvasParts';
import type { FlowUI } from './flow/FlowCanvasParts';
import FlowDock from './flow/FlowDock';
import { DesignInspector, MonitorInspector, validateFlow } from './flow/FlowInspector';
import { autoLayout, NODE_SIZE, sizeOf, snap } from './flow/flowLayout';
import { aggregate, FlowSimulator, rid } from './flow/flowSim';
import type { NodeMetric } from './flow/flowSim';
import { addFormatRoute, defaultsFor, formatRoutes, formatsOfFlow, loadLibrary, makeEdge, makeNode, OVERVIEW_ID, parseLibrary, saveLibrary, stripTransient, templateFor, uid } from './flow/flowTemplates';
import type { EditorMode, FlowDirection, FlowDoc, FlowEdge, FlowEdgeData, FlowLibrary, FlowNode, FlowNodeData, NodeKind } from './flow/flowTypes';
import FormatPanel, { displayFormat, normalizeFormat } from './flow/FormatPanel';

type Props = { formats: string[]; onOpenDocuments: (format: string) => void; onOpenLiveDocuments?: () => void; initialFormat?: string; active?: boolean; simulator?: FlowSimulator; focus?: { flowId: string; nodeId?: string; n: number } };

const nodeTypes = { flow: FlowNodeView };
const edgeTypes = { flow: FlowEdgeView };
const DND = 'application/x-docops-node';
const MANUAL_KEY = 'document-ops:manual-formats:v1';
const PALETTE: NodeKind[] = ['task', 'gateway', 'review', 'exception', 'store', 'subflow', 'start', 'end', 'note'];
const INSERTABLE: NodeKind[] = ['task', 'review', 'gateway', 'exception', 'store', 'subflow'];
type Padding = NonNullable<FitViewOptions['padding']>;
const fitOptions = (design: boolean) => ({ padding: { top: design ? '32px' : '60px', bottom: '52px', left: '40px', right: '40px' } as Padding, maxZoom: 1 });
const DEFAULT_LABEL: Record<NodeKind, string> = { task: '새 작업', gateway: '조건', review: '사람 검토', exception: '예외 대기열', store: '데이터 저장', subflow: '하위 흐름', start: '시작', end: '종료', note: '메모를 입력하세요' };

function readManualFormats(): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem(MANUAL_KEY) || '[]'); return Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === 'string').map(normalizeFormat).filter(item => /^[A-Z0-9]{1,20}$/.test(item)))] : []; } catch { return []; }
}

export default function PipelineStudio(props: Props) {
  return <ReactFlowProvider><Studio {...props} /></ReactFlowProvider>;
}

function Studio({ formats, onOpenDocuments, onOpenLiveDocuments, initialFormat, active = true, simulator, focus }: Props) {
  const [library, setLibraryState] = useState<FlowLibrary>(loadLibrary);
  const [ownSim] = useState(() => simulator ? null : new FlowSimulator(library));
  const sim = simulator ?? ownSim!;
  const initialExt = initialFormat !== undefined ? normalizeFormat(initialFormat) : null;
  const [flowId, setFlowId] = useState(() => (initialExt !== null && formatRoutes(library)[initialExt]) || OVERVIEW_ID);
  const [pendingExt, setPendingExt] = useState<string | null>(() => initialExt !== null && !formatRoutes(library)[initialExt] ? initialExt : null);
  const [mode, setMode] = useState<EditorMode>('monitor');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdgeState] = useState<string | null>(null);
  const [dropEdge, setDropEdge] = useState<string | null>(null);
  const [insertMenu, setInsertMenu] = useState<{ edgeId: string; x: number; y: number } | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [dockTab, setDockTab] = useState<'events' | 'docs'>('events');
  const [formatsOpen, setFormatsOpen] = useState(() => pendingExt !== null);
  const [notice, setNotice] = useState('');
  const [view, setView] = useState<{ nodeId?: string; n: number }>({ n: 0 });
  const [manual, setManual] = useState<string[]>(readManualFormats);
  const [liveCounts, setLiveCounts] = useState<Record<string, number> | null>(null);
  const [liveFailed, setLiveFailed] = useState(false);
  const [refreshId, setRefreshId] = useState(0);
  const history = useRef<{ past: FlowLibrary[]; future: FlowLibrary[] }>({ past: [], future: [] });
  const [, bump] = useReducer((value: number) => value + 1, 0);
  const libRef = useRef(library); libRef.current = library;
  const flowRef = useRef(flowId); flowRef.current = flowId;
  const modeRef = useRef(mode); modeRef.current = mode;
  const dragOrigin = useRef<FlowLibrary | null>(null);
  const autoFit = useRef(true);
  const hoverTimer = useRef<number | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const rf = useReactFlow<FlowNode, FlowEdge>();
  const snapshot = useSyncExternalStore(sim.subscribe, sim.getSnapshot);

  const flow: FlowDoc = library.flows[flowId] ?? library.flows[OVERVIEW_ID] ?? Object.values(library.flows)[0];
  const design = mode === 'design';
  const routes = useMemo(() => formatRoutes(library), [library]);

  /* ----- 저장 · 동기화 ----- */
  useEffect(() => { const timer = window.setTimeout(() => saveLibrary(library), 250); return () => window.clearTimeout(timer); }, [library]);
  const structure = useMemo(() => JSON.stringify(library.order.map(id => { const doc = library.flows[id]; return [id, doc.title, doc.nodes.map(node => [node.id, node.data]), doc.edges.map(edge => [edge.id, edge.source, edge.target, edge.data])]; })), [library]);
  useEffect(() => { sim.setLibrary(libRef.current); }, [structure, sim]);
  useEffect(() => { if (!active || mode !== 'monitor') return; return sim.acquire(); }, [active, mode, sim]);
  useEffect(() => { if (!library.flows[flowId]) setFlowId(OVERVIEW_ID); }, [library, flowId]);
  useEffect(() => { try { localStorage.setItem(MANUAL_KEY, JSON.stringify(manual)); } catch { /* 선택 사항 */ } }, [manual]);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    listLiveDocuments().then(docs => { if (!alive) return; const next: Record<string, number> = {}; for (const doc of docs) { const ext = normalizeFormat(doc.format || ''); next[ext] = (next[ext] || 0) + 1; } setLiveCounts(next); setLiveFailed(false); })
      .catch(() => { if (alive) { setLiveCounts(null); setLiveFailed(true); } });
    return () => { alive = false; };
  }, [active, refreshId]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 4200); return () => window.clearTimeout(timer); }, [notice]);

  /* ----- 화면 맞춤 ----- */
  useEffect(() => {
    if (!active) return;
    let tries = 0, timer = 0;
    const run = () => {
      const node = view.nodeId ? rf.getNode(view.nodeId) : undefined;
      if (view.nodeId && !node && tries++ < 10) { timer = window.setTimeout(run, 80); return; }
      autoFit.current = !node;
      if (node) rf.setCenter(node.position.x + (node.width ?? 0) / 2, node.position.y + (node.height ?? 0) / 2, { zoom: Math.max(rf.getZoom(), 0.95), duration: 300 });
      else rf.fitView({ ...fitOptions(modeRef.current === 'design'), duration: 200 });
    };
    timer = window.setTimeout(run, 60);
    return () => window.clearTimeout(timer);
  }, [flowId, view, active, rf]);
  useEffect(() => {
    const element = canvasRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => { if (autoFit.current && element.clientWidth > 0) rf.fitView(fitOptions(modeRef.current === 'design')); });
    observer.observe(element);
    return () => observer.disconnect();
  }, [rf]);

  /* ----- 변경 · 기록 ----- */
  const apply = useCallback((next: FlowLibrary) => { libRef.current = next; setLibraryState(next); }, []);
  const record = useCallback((previous: FlowLibrary) => { const h = history.current; h.past.push(previous); if (h.past.length > 80) h.past.shift(); h.future = []; bump(); }, []);
  const commit = useCallback((updater: (lib: FlowLibrary) => FlowLibrary, recordHistory = true) => {
    const previous = libRef.current; const next = updater(previous);
    if (next === previous) return;
    if (recordHistory) record(previous);
    apply(next);
  }, [apply, record]);
  const updateFlow = useCallback((updater: (doc: FlowDoc) => FlowDoc, recordHistory = true) => commit(lib => {
    const doc = lib.flows[flowRef.current]; if (!doc) return lib;
    const next = updater(doc);
    return next === doc ? lib : { ...lib, flows: { ...lib.flows, [doc.id]: next } };
  }, recordHistory), [commit]);
  const undo = useCallback(() => { const h = history.current; const previous = h.past.pop(); if (!previous) return; h.future.push(libRef.current); apply(previous); bump(); }, [apply]);
  const redo = useCallback(() => { const h = history.current; const next = h.future.pop(); if (!next) return; h.past.push(libRef.current); apply(next); bump(); }, [apply]);

  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    const allowed = changes.filter(change => change.type !== 'remove' && (modeRef.current === 'design' || change.type === 'select' || change.type === 'dimensions'));
    if (allowed.length) updateFlow(doc => ({ ...doc, nodes: applyNodeChanges(allowed, doc.nodes) }), false);
  }, [updateFlow]);
  const onEdgesChange = useCallback((changes: EdgeChange<FlowEdge>[]) => {
    const allowed = changes.filter(change => change.type === 'select');
    if (allowed.length) updateFlow(doc => ({ ...doc, edges: applyEdgeChanges(allowed, doc.edges) }), false);
  }, [updateFlow]);
  const onConnect = useCallback((connection: Connection) => {
    if (modeRef.current !== 'design' || !connection.source || !connection.target || connection.source === connection.target) return;
    updateFlow(doc => {
      if (doc.edges.some(edge => edge.source === connection.source && edge.target === connection.target)) return doc;
      const source = doc.nodes.find(node => node.id === connection.source);
      const count = doc.edges.filter(edge => edge.source === connection.source).length;
      const data: FlowEdgeData = source?.data.kind === 'gateway' ? { kind: 'default', label: `조건 ${count + 1}`, weight: 1 } : { kind: 'default' };
      const edge: FlowEdge = { ...makeEdge(connection.source, connection.target, data, uid('e')), sourceHandle: connection.sourceHandle, targetHandle: connection.targetHandle, selected: true };
      return { ...doc, nodes: doc.nodes.map(node => node.selected ? { ...node, selected: false } : node), edges: [...doc.edges.map(item => item.selected ? { ...item, selected: false } : item), edge] };
    });
  }, [updateFlow]);

  /** draw.io처럼 연결점이 아니라 대상 도형 위에 놓아도 연결한다. */
  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
    if (state.isValid || !state.fromNode) return;
    const point = 'changedTouches' in event ? event.changedTouches[0] : event;
    const target = document.elementFromPoint(point.clientX, point.clientY)?.closest('.react-flow__node')?.getAttribute('data-id');
    if (target && target !== state.fromNode.id) onConnect({ source: state.fromNode.id, target, sourceHandle: state.fromHandle?.id ?? null, targetHandle: null });
  }, [onConnect]);

  const clearSelection = (doc: FlowDoc): FlowDoc => ({ ...doc, nodes: doc.nodes.map(node => node.selected ? { ...node, selected: false } : node), edges: doc.edges.map(edge => edge.selected ? { ...edge, selected: false } : edge) });
  const viewportCenter = useCallback((): XYPosition => {
    const box = canvasRef.current?.getBoundingClientRect();
    return box ? rf.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 }) : { x: 200, y: 200 };
  }, [rf]);
  const addNode = useCallback((kind: NodeKind, center?: XYPosition) => {
    const size = NODE_SIZE[kind]; const at = center ?? viewportCenter();
    const start = { x: snap(at.x - size.w / 2), y: snap(at.y - size.h / 2) };
    const node = { ...makeNode(uid('n'), kind, DEFAULT_LABEL[kind], {}, center ? start : freeSpot(start, size, libRef.current.flows[flowRef.current]?.nodes ?? [])), selected: true };
    updateFlow(doc => { const base = clearSelection(doc); return { ...base, nodes: [...base.nodes, node] }; });
    setInspectorOpen(true);
  }, [updateFlow, viewportCenter]);

  /** 연결선 중간에 단계를 끼워 넣고, 뒤쪽 노드를 밀어 자리를 만든다. */
  const insertOnEdge = useCallback((edgeId: string, kind: NodeKind) => {
    updateFlow(doc => {
      const edge = doc.edges.find(item => item.id === edgeId); if (!edge) return doc;
      const source = doc.nodes.find(node => node.id === edge.source), target = doc.nodes.find(node => node.id === edge.target);
      if (!source || !target) return doc;
      const size = NODE_SIZE[kind], s = sizeOf(source), t = sizeOf(target), vertical = doc.direction === 'TB';
      let position: XYPosition, shift = 0;
      if (vertical) {
        const aligned = Math.abs(source.position.x + s.w / 2 - (target.position.x + t.w / 2)) < 12;
        const cx = aligned || target.position.y <= source.position.y ? source.position.x + s.w / 2 : target.position.x + t.w / 2;
        position = { x: snap(cx - size.w / 2), y: snap(source.position.y + s.h + 48) };
        if (target.position.y > source.position.y) shift = Math.max(0, position.y + size.h + 48 - target.position.y);
      } else {
        const cy = target.position.x <= source.position.x ? source.position.y + s.h / 2 : target.position.y + t.h / 2;
        position = { x: snap(source.position.x + s.w + 64), y: snap(cy - size.h / 2) };
        if (target.position.x > source.position.x) shift = Math.max(0, position.x + size.w + 64 - target.position.x);
      }
      const node = { ...makeNode(uid('n'), kind, DEFAULT_LABEL[kind], {}, position), selected: true };
      const limit = vertical ? target.position.y - 1 : target.position.x - 1;
      const nodes = doc.nodes.map(item => {
        const moved = shift && (vertical ? item.position.y >= limit : item.position.x >= limit) ? { ...item, position: vertical ? { x: item.position.x, y: item.position.y + snap(shift) } : { x: item.position.x + snap(shift), y: item.position.y } } : item;
        return moved.selected ? { ...moved, selected: false } : moved;
      });
      const first = { ...makeEdge(edge.source, node.id, { ...edge.data }, uid('e')) };
      const second = makeEdge(node.id, edge.target, kind === 'gateway' ? { kind: 'default', label: '기본', isDefault: true } : { kind: 'default' }, uid('e'));
      return { ...doc, nodes: [...nodes, node], edges: [...doc.edges.filter(item => item.id !== edgeId).map(item => item.selected ? { ...item, selected: false } : item), first, second] };
    });
    setInspectorOpen(true);
    setNotice(`${KIND_META[kind].label} 단계를 연결 사이에 넣었습니다.`);
  }, [updateFlow]);

  const appendAfter = useCallback((nodeId: string, kind: NodeKind) => {
    const doc = libRef.current.flows[flowRef.current];
    const outgoing = doc?.edges.filter(edge => edge.source === nodeId && edge.data?.kind !== 'exception') ?? [];
    if (outgoing.length === 1) { insertOnEdge(outgoing[0].id, kind); return; }
    updateFlow(current => {
      const source = current.nodes.find(node => node.id === nodeId); if (!source) return current;
      const s = sizeOf(source), size = NODE_SIZE[kind];
      const position = current.direction === 'TB' ? { x: snap(source.position.x + s.w / 2 - size.w / 2 + outgoing.length * (size.w + 32)), y: snap(source.position.y + s.h + 64) } : { x: snap(source.position.x + s.w + 80), y: snap(source.position.y + s.h / 2 - size.h / 2 + outgoing.length * (size.h + 32)) };
      const node = { ...makeNode(uid('n'), kind, DEFAULT_LABEL[kind], {}, position), selected: true };
      const base = clearSelection(current);
      const data: FlowEdgeData = source.data.kind === 'gateway' ? { kind: 'default', label: `조건 ${outgoing.length + 1}`, weight: 1 } : { kind: 'default' };
      return { ...base, nodes: [...base.nodes, node], edges: [...base.edges, makeEdge(nodeId, node.id, data, uid('e'))] };
    });
  }, [insertOnEdge, updateFlow]);

  const removeSelection = useCallback(() => {
    updateFlow(doc => {
      const nodeIds = new Set(doc.nodes.filter(node => node.selected).map(node => node.id));
      const edgeIds = new Set(doc.edges.filter(edge => edge.selected).map(edge => edge.id));
      if (!nodeIds.size && !edgeIds.size) return doc;
      const kept = doc.edges.filter(edge => !edgeIds.has(edge.id));
      const healed: FlowEdge[] = [];
      for (const id of nodeIds) {
        const ins = kept.filter(edge => edge.target === id && !nodeIds.has(edge.source)), outs = kept.filter(edge => edge.source === id && !nodeIds.has(edge.target));
        if (ins.length === 1 && outs.length === 1 && !kept.some(edge => edge.source === ins[0].source && edge.target === outs[0].target)) healed.push(makeEdge(ins[0].source, outs[0].target, { ...ins[0].data }, uid('e')));
      }
      return { ...doc, nodes: doc.nodes.filter(node => !nodeIds.has(node.id)), edges: [...kept.filter(edge => !nodeIds.has(edge.source) && !nodeIds.has(edge.target)), ...healed] };
    });
  }, [updateFlow]);

  const duplicate = useCallback(() => updateFlow(doc => {
    const picked = doc.nodes.filter(node => node.selected); if (!picked.length) return doc;
    const ids = new Map(picked.map(node => [node.id, uid('n')]));
    const copies = picked.map(node => ({ ...node, id: ids.get(node.id)!, position: { x: node.position.x + 32, y: node.position.y + 32 }, data: { ...node.data }, selected: true }));
    const edges = doc.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)).map(edge => ({ ...edge, id: uid('e'), source: ids.get(edge.source)!, target: ids.get(edge.target)!, selected: false }));
    const base = clearSelection(doc);
    return { ...base, nodes: [...base.nodes, ...copies], edges: [...base.edges, ...edges] };
  }), [updateFlow]);

  const setNodeData = useCallback((id: string, patch: Partial<FlowNodeData>) => updateFlow(doc => ({ ...doc, nodes: doc.nodes.map(node => node.id === id ? { ...node, data: { ...node.data, ...patch } } : node) })), [updateFlow]);
  const setNodeKind = useCallback((id: string, kind: NodeKind) => updateFlow(doc => ({ ...doc, nodes: doc.nodes.map(node => {
    if (node.id !== id) return node;
    const before = sizeOf(node), after = NODE_SIZE[kind];
    return { ...node, width: after.w, height: after.h, position: { x: snap(node.position.x + (before.w - after.w) / 2), y: snap(node.position.y + (before.h - after.h) / 2) }, data: { ...defaultsFor(kind), ...node.data, kind } };
  }) })), [updateFlow]);
  const setEdgeData = useCallback((id: string, patch: Partial<FlowEdgeData>) => updateFlow(doc => ({ ...doc, edges: doc.edges.map(edge => edge.id === id ? { ...edge, data: { ...edge.data, ...patch } } : edge) })), [updateFlow]);
  const reverseEdge = useCallback((id: string) => updateFlow(doc => ({ ...doc, edges: doc.edges.map(edge => edge.id === id ? { ...edge, source: edge.target, target: edge.source, sourceHandle: undefined, targetHandle: undefined } : edge) })), [updateFlow]);
  const rename = useCallback((id: string, label: string) => setNodeData(id, { label }), [setNodeData]);
  const layout = useCallback((direction: FlowDirection) => { updateFlow(doc => ({ ...doc, direction, nodes: autoLayout(doc.nodes, doc.edges, direction) })); setView(prev => ({ n: prev.n + 1 })); }, [updateFlow]);
  const selectInFlow = useCallback((nodeId?: string, edgeId?: string) => updateFlow(doc => ({ ...doc, nodes: doc.nodes.map(node => (node.id === nodeId) === !!node.selected ? node : { ...node, selected: node.id === nodeId }), edges: doc.edges.map(edge => (edge.id === edgeId) === !!edge.selected ? edge : { ...edge, selected: edge.id === edgeId }) }), false), [updateFlow]);

  const openFlow = useCallback((id: string, nodeId?: string) => {
    const lib = libRef.current; const doc = lib.flows[id]; if (!doc) return;
    if (nodeId !== undefined) apply({ ...lib, flows: { ...lib.flows, [id]: { ...doc, nodes: doc.nodes.map(node => (node.id === nodeId) === !!node.selected ? node : { ...node, selected: node.id === nodeId }), edges: doc.edges.map(edge => edge.selected ? { ...edge, selected: false } : edge) } } });
    setFlowId(id); setInsertMenu(null); setEditingId(null); setFormatsOpen(false);
    if (nodeId) setInspectorOpen(true);
    setView(prev => ({ nodeId, n: prev.n + 1 }));
  }, [apply]);

  useEffect(() => { if (focus) { setMode('monitor'); openFlow(focus.flowId, focus.nodeId); } }, [focus?.n]); // eslint-disable-line react-hooks/exhaustive-deps

  const createRoute = useCallback((ext: string) => {
    if (!ext) return;
    const result = addFormatRoute(libRef.current, ext);
    if (result.library !== libRef.current) commit(() => result.library);
    setPendingExt(null); setMode('design'); openFlow(result.flowId);
    setNotice(`${displayFormat(ext)} 흐름을 만들고 전체 흐름의 라우팅에 연결했습니다. 실제 파서는 등록되지 않습니다.`);
  }, [commit, openFlow]);
  const addManual = useCallback((value: string) => {
    const ext = normalizeFormat(value);
    if (!/^[A-Z0-9]{1,20}$/.test(ext)) return '영문과 숫자 1~20자로 입력해 주세요.';
    setManual(prev => prev.includes(ext) ? prev : [...prev, ext]); setPendingExt(ext);
    setNotice(`${displayFormat(ext)} 형식을 목록에 추가했습니다. 경로를 만들면 전체 흐름에 연결됩니다.`);
    return null;
  }, []);
  const resetFlow = useCallback(() => { const template = templateFor(flowRef.current); if (template) { updateFlow(() => template); setView(prev => ({ n: prev.n + 1 })); setNotice('기본 구성으로 되돌렸습니다.'); } }, [updateFlow]);
  const deleteFlow = useCallback(() => {
    const id = flowRef.current; if (id === OVERVIEW_ID) return;
    commit(lib => {
      const flows = { ...lib.flows }; delete flows[id];
      const root = flows[OVERVIEW_ID];
      if (root) { const gone = new Set(root.nodes.filter(node => node.data.subflow === id).map(node => node.id)); flows[OVERVIEW_ID] = { ...root, nodes: root.nodes.filter(node => !gone.has(node.id)), edges: root.edges.filter(edge => !gone.has(edge.source) && !gone.has(edge.target)) }; }
      return { ...lib, flows, order: lib.order.filter(item => item !== id) };
    });
    openFlow(OVERVIEW_ID); setNotice('흐름을 삭제했습니다.');
  }, [commit, openFlow]);
  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(stripTransient(libRef.current), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'unstructured-review-flows.json'; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, []);
  const importJson = useCallback(async (file: File) => {
    try { const parsed = parseLibrary(JSON.parse(await file.text())); if (!parsed) { setNotice('흐름 파일 형식이 맞지 않습니다.'); return; } commit(() => parsed); openFlow(parsed.flows[OVERVIEW_ID] ? OVERVIEW_ID : parsed.order[0]); setNotice('흐름을 가져왔습니다.'); }
    catch { setNotice('JSON 파일을 읽지 못했습니다.'); }
  }, [commit, openFlow]);

  /* ----- 단축키 ----- */
  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setInsertMenu(null); setFormatsOpen(false); }
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]') || modeRef.current !== 'design') return;
      const mod = event.metaKey || event.ctrlKey; const key = event.key.toLowerCase();
      if (mod && key === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); }
      else if (mod && key === 'y') { event.preventDefault(); redo(); }
      else if (mod && key === 'd') { event.preventDefault(); duplicate(); }
      else if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeSelection(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [active, undo, redo, duplicate, removeSelection]);

  /* ----- 드래그 앤 드롭 ----- */
  const nearestEdge = useCallback((point: XYPosition) => {
    let best: { id: string; distance: number } | null = null;
    for (const edge of flow.edges) {
      const source = rf.getInternalNode(edge.source), target = rf.getInternalNode(edge.target);
      if (!source || !target) continue;
      const distance = distanceToPath(point, edgeRoute(source, target, flow.direction, source.data.kind === 'gateway' || edge.data?.kind === 'exception').points);
      if (distance < 28 && (!best || distance < best.distance)) best = { id: edge.id, distance };
    }
    return best?.id ?? null;
  }, [flow, rf]);
  const onDragOver = (event: React.DragEvent) => {
    if (!design || !event.dataTransfer.types.includes(DND)) return;
    event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
    setDropEdge(nearestEdge(rf.screenToFlowPosition({ x: event.clientX, y: event.clientY })));
  };
  const onDrop = (event: React.DragEvent) => {
    const kind = event.dataTransfer.getData(DND) as NodeKind;
    setDropEdge(null);
    if (!design || !KIND_META[kind]) return;
    event.preventDefault();
    const point = rf.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const edge = kind === 'note' || kind === 'start' || kind === 'end' ? null : nearestEdge(point);
    if (edge) insertOnEdge(edge, kind); else addNode(kind, point);
  };

  /* ----- 운영 지표 ----- */
  const viewMetrics = useMemo(() => {
    const result: Record<string, NodeMetric | undefined> = {};
    for (const node of flow.nodes) result[node.id] = node.data.kind === 'subflow' && node.data.subflow ? aggregate(snapshot.metrics, node.data.subflow) : snapshot.metrics[rid(flow.id, node.id)];
    return result;
  }, [snapshot, flow]);
  const viewTraffic = useMemo(() => { const result: Record<string, number> = {}; for (const edge of flow.edges) result[edge.id] = snapshot.traffic[rid(flow.id, edge.id)] ?? 0; return result; }, [snapshot, flow]);
  const forcedEdges = useMemo(() => { const result = new Set<string>(); for (const node of flow.nodes) { const forced = snapshot.metrics[rid(flow.id, node.id)]?.forced; if (forced) result.add(forced.slice(flow.id.length + 2)); } return result; }, [snapshot, flow]);
  const flowStatus = useMemo(() => Object.fromEntries(library.order.map(id => [id, aggregate(snapshot.metrics, id)])), [snapshot, library.order]);
  const issues = useMemo(() => validateFlow(flow, library), [flow, library]);
  const labeledEdges = useMemo(() => { const names = new Map(flow.nodes.map(node => [node.id, node.data.label])); return flow.edges.map(edge => ({ ...edge, ariaLabel: `${names.get(edge.source) ?? edge.source} → ${names.get(edge.target) ?? edge.target} 연결` })); }, [flow]);

  const setHoveredEdge = useCallback((id: string | null) => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    if (id) setHoveredEdgeState(id); else hoverTimer.current = window.setTimeout(() => setHoveredEdgeState(null), 180);
  }, []);
  const ui: FlowUI = useMemo(() => ({
    mode, direction: flow.direction, metrics: viewMetrics, traffic: viewTraffic, forcedEdges,
    flowTitles: Object.fromEntries(Object.values(library.flows).map(doc => [doc.id, doc.title])), flowFormats: (id: string) => formatsOfFlow(library, id),
    editingId, setEditingId, rename, openSubflow: (id: string) => openFlow(id), hoveredEdge, setHoveredEdge, dropEdge,
    requestInsert: (edgeId: string, rect: DOMRect) => setInsertMenu({ edgeId, x: rect.right + 8, y: rect.top - 6 }),
  }), [mode, flow.direction, viewMetrics, viewTraffic, forcedEdges, library, editingId, rename, openFlow, hoveredEdge, setHoveredEdge, dropEdge]);

  const onNodeDoubleClick: NodeMouseHandler<FlowNode> = (_, node) => {
    if (design) setEditingId(node.id);
    else if (node.data.kind === 'subflow' && node.data.subflow) openFlow(node.data.subflow);
  };
  const selectedNode = flow.nodes.find(node => node.selected);
  const selectedEdge = selectedNode ? undefined : flow.edges.find(edge => edge.selected);
  const selectionKey = selectedNode?.id ?? selectedEdge?.id;
  useEffect(() => { if (selectionKey) setInspectorOpen(true); }, [selectionKey]);
  const flowFormats = flow.id === OVERVIEW_ID ? [] : formatsOfFlow(library, flow.id);
  const t = snapshot.totals;
  const jumpTo = (predicate: (metric: NodeMetric) => boolean) => {
    const found = Object.entries(snapshot.metrics).find(([id, metric]) => id.startsWith(`${flow.id}::`) && predicate(metric)) ?? Object.entries(snapshot.metrics).find(([, metric]) => predicate(metric));
    if (found) { const [flowPart, ...rest] = found[0].split('::'); openFlow(flowPart, rest.join('::')); }
  };

  return <FlowUIContext.Provider value={ui}>
    <section className={`ps-root ${design ? 'ps-design' : 'ps-monitor'}`} aria-label="파이프라인 작업 공간">
      <header className="ps-toolbar">
        <div className="ps-title">
          {flow.id !== OVERVIEW_ID && <><button className="ps-crumb" onClick={() => openFlow(OVERVIEW_ID)}>{library.flows[OVERVIEW_ID]?.title ?? '전체 흐름'}</button><ChevronRight size={14} className="ps-crumb-sep" /></>}
          <h2>{flow.title}</h2>
          {flowFormats.length > 0 && <div className="ps-formats">{flowFormats.slice(0, 6).map(format => <span key={format}>{format}</span>)}{flowFormats.length > 6 && <span>+{flowFormats.length - 6}</span>}</div>}
        </div>
        <div className="ps-mode" role="group" aria-label="화면 모드">
          <button className={mode === 'monitor' ? 'is-on' : ''} aria-pressed={mode === 'monitor'} onClick={() => { setMode('monitor'); setEditingId(null); setInsertMenu(null); }}><Activity size={14} /> 운영</button>
          <button className={design ? 'is-on' : ''} aria-pressed={design} onClick={() => setMode('design')}><PenTool size={14} /> 설계</button>
        </div>
        <div className="ps-tools">
          {design ? <>
            <button className="ps-icon" onClick={undo} disabled={!history.current.past.length} aria-label="되돌리기" title="되돌리기 (⌘Z)"><Undo2 size={16} /></button>
            <button className="ps-icon" onClick={redo} disabled={!history.current.future.length} aria-label="다시 실행" title="다시 실행 (⇧⌘Z)"><Redo2 size={16} /></button>
            <span className="ps-sep" />
            <button className="ps-btn" onClick={() => layout('TB')} aria-label="세로 자동 정렬" title="세로(위→아래) 자동 정렬"><LayoutGrid size={14} /> 세로 정렬</button>
            <button className="ps-btn" onClick={() => layout('LR')} aria-label="가로 자동 정렬" title="가로(왼쪽→오른쪽) 자동 정렬"><Rows3 size={14} /> 가로 정렬</button>
            <span className="ps-sep" />
            <button className={`ps-pill ${issues.length ? 'is-warn' : 'is-ok'}`} onClick={() => { selectInFlow(); setInspectorOpen(true); }} title="검증 결과 보기">{issues.length ? <><TriangleAlert size={13} /> 검증 {issues.length}</> : '검증 통과'}</button>
          </> : <>
            <button className={`ps-btn ${snapshot.running ? '' : 'is-primary'}`} onClick={() => sim.setRunning(!snapshot.running)}>{snapshot.running ? <><CirclePause size={14} /> 전체 일시정지</> : <><CirclePlay size={14} /> 전체 재개</>}</button>
            <div className="ps-seg" role="group" aria-label="모의 속도">{[1, 2, 4].map(speed => <button key={speed} className={snapshot.speed === speed ? 'is-on' : ''} aria-pressed={snapshot.speed === speed} onClick={() => sim.setSpeed(speed)}>{speed}×</button>)}</div>
            <div className="ps-rate" role="group" aria-label="유입량"><span>유입</span><button aria-label="유입 줄이기" onClick={() => sim.setRate(snapshot.rate - 6)}><Minus size={12} /></button><b>{snapshot.rate}<small>/분</small></b><button aria-label="유입 늘리기" onClick={() => sim.setRate(snapshot.rate + 6)}><Plus size={12} /></button></div>
            <span className="ps-sep" />
            <span className="ps-clock" title="모의 시각">{snapshot.clock}</span>
            <button className="ps-icon" onClick={() => sim.reset()} aria-label="모의 운영 초기화" title="모의 운영 초기화"><RotateCcw size={15} /></button>
          </>}
          <span className="ps-sep" />
          <button className={`ps-btn ${formatsOpen ? 'is-on' : ''}`} onClick={() => setFormatsOpen(open => !open)} aria-expanded={formatsOpen}><ListTree size={14} /> 형식 · 경로</button>
          <button className="ps-icon" onClick={() => setInspectorOpen(open => !open)} aria-label={inspectorOpen ? '상세 패널 접기' : '상세 패널 펼치기'} title={inspectorOpen ? '상세 패널 접기' : '상세 패널 펼치기'}>{inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button>
        </div>
      </header>

      {pendingExt !== null && <div className="ps-banner" role="status"><TriangleAlert size={15} /><span><b>{displayFormat(pendingExt)}</b> 형식은 아직 처리 경로가 없어 <b>형식 확인 대기열</b>로 모입니다.</span><button className="ps-btn is-primary" onClick={() => createRoute(pendingExt)} disabled={!pendingExt}><Plus size={13} /> {displayFormat(pendingExt)} 경로 만들기</button><button className="ps-icon" onClick={() => setPendingExt(null)} aria-label="안내 닫기"><X size={14} /></button></div>}

      <div className="ps-body">
        {design && <aside className="ps-palette" aria-label="도형">
          {PALETTE.map(kind => { const Icon = KIND_META[kind].icon; return <button key={kind} className={`ps-shape is-${kind}`} draggable onDragStart={event => { event.dataTransfer.setData(DND, kind); event.dataTransfer.effectAllowed = 'copy'; }} onClick={() => addNode(kind)} aria-label={`${KIND_META[kind].label} 추가`} title={`${KIND_META[kind].label} — ${KIND_META[kind].hint}. 끌어 놓거나 눌러 추가`}><Icon size={18} /><span>{KIND_META[kind].label}</span></button>; })}
        </aside>}
        <div className="ps-center">
          <div className="ps-canvas" ref={canvasRef} onDragOver={onDragOver} onDragLeave={() => setDropEdge(null)} onDrop={onDrop}>
            <ReactFlow<FlowNode, FlowEdge>
              nodes={flow.nodes} edges={labeledEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onConnectEnd={onConnectEnd} connectionRadius={28}
              onNodeDragStart={() => { dragOrigin.current = libRef.current; }}
              onNodeDragStop={() => { if (dragOrigin.current && dragOrigin.current !== libRef.current) record(dragOrigin.current); dragOrigin.current = null; }}
              onNodeDoubleClick={onNodeDoubleClick}
              onEdgeMouseEnter={(_, edge) => setHoveredEdge(edge.id)} onEdgeMouseLeave={() => setHoveredEdge(null)}
              onPaneClick={() => { setInsertMenu(null); setEditingId(null); }}
              onMoveStart={event => { if (event) autoFit.current = false; }}
              nodesDraggable={design} nodesConnectable={design} elementsSelectable edgesReconnectable={false}
              connectionMode={ConnectionMode.Loose} connectionLineType={ConnectionLineType.SmoothStep}
              deleteKeyCode={null} selectionKeyCode="Shift" multiSelectionKeyCode={['Meta', 'Control']} selectionMode={SelectionMode.Partial}
              snapToGrid snapGrid={[8, 8]} minZoom={0.2} maxZoom={2} zoomOnDoubleClick={false}
              fitView fitViewOptions={fitOptions(design)} proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1.3} color="#cdd4df" />
              <MiniMap pannable zoomable className="ps-minimap" ariaLabel="흐름 미니맵" nodeBorderRadius={6} nodeColor={node => minimapColor(node as FlowNode, viewMetrics[node.id], design)} maskColor="rgba(241,244,249,.72)" />
              <ZoomControls design={design} />
              {!design && <Panel position="top-left" className="ps-kpi" aria-label="운영 지표">
                <span><small>유입</small><b>{t.arrivalsPerMin}</b><i>/분</i></span>
                <span><small>완료</small><b>{t.completedPerMin}</b><i>/분</i></span>
                <span><small>처리 중</small><b>{t.processing}</b></span>
                <span><small>대기</small><b>{t.queued}</b></span>
                <button className={t.held ? 'is-warn' : ''} onClick={() => jumpTo(metric => metric.held > 0)} disabled={!t.held}><small>보류</small><b>{t.held}</b></button>
                <button className={t.failed ? 'is-error' : ''} onClick={() => jumpTo(metric => metric.failed > 0)} disabled={!t.failed}><small>실패</small><b>{t.failed}</b></button>
                <button className="ps-kpi-more" onClick={() => { selectInFlow(); setInspectorOpen(true); }}>운영 요약</button>
              </Panel>}
            </ReactFlow>
            {notice && <div className="ps-toast" role="status">{notice}</div>}
            {design && !flow.nodes.length && <div className="ps-empty"><b>빈 흐름입니다</b><span>왼쪽 도형을 끌어 놓아 시작하세요.</span></div>}
          </div>
          {!design && dockOpen && <FlowDock snapshot={snapshot} library={library} tab={dockTab} onTab={setDockTab} onNavigate={openFlow} />}
          <nav className="ps-pages" aria-label="흐름 페이지">
            {library.order.map(id => { const status = flowStatus[id]?.status ?? 'idle'; const alerts = (flowStatus[id]?.failed ?? 0) + (flowStatus[id]?.held ?? 0); return <button key={id} className={id === flowId ? 'is-on' : ''} aria-current={id === flowId ? 'page' : undefined} onClick={() => openFlow(id)}>{!design && <i className={`fx-dot is-${status}`} />}{library.flows[id].title}{!design && alerts > 0 && <b className={`is-${status}`}>{alerts}</b>}</button>; })}
            <button className="ps-page-add" onClick={() => setFormatsOpen(true)} aria-label="새 형식 경로 추가" title="새 형식 경로 추가"><Plus size={14} /></button>
            {!design && <button className={`ps-dock-toggle ${dockOpen ? 'is-on' : ''}`} onClick={() => setDockOpen(open => !open)} aria-expanded={dockOpen} aria-label={dockOpen ? '운영 기록 접기' : '운영 기록 펼치기'}>{dockOpen ? <PanelBottomClose size={15} /> : <PanelBottomOpen size={15} />}운영 기록{snapshot.events.some(event => event.level === 'error') && <em>{snapshot.events.filter(event => event.level === 'error').length}</em>}</button>}
          </nav>
        </div>
        {inspectorOpen && <aside className="ps-inspector" aria-label={design ? '속성' : '운영 상세'}>
          {design
            ? <DesignInspector library={library} flow={flow} node={selectedNode} edge={selectedEdge} issues={issues}
              onNodeData={setNodeData} onNodeKind={setNodeKind} onEdgeData={setEdgeData}
              onSelectNode={id => { selectInFlow(id); setView(prev => ({ nodeId: id, n: prev.n + 1 })); }} onSelectEdge={id => selectInFlow(undefined, id)}
              onDuplicate={duplicate} onRemove={removeSelection} onAppend={appendAfter} onInsert={insertOnEdge} onReverse={reverseEdge} onOpenFlow={id => openFlow(id)}
              onFlowMeta={patch => updateFlow(doc => ({ ...doc, ...patch }))} onLayout={layout} onResetFlow={resetFlow} onDeleteFlow={deleteFlow}
              onExport={exportJson} onImport={() => importRef.current?.click()} onOpenDocuments={onOpenDocuments} />
            : <MonitorInspector library={library} flow={flow} node={selectedNode} snapshot={snapshot} sim={sim} metrics={viewMetrics} onNavigate={openFlow} onNodeData={setNodeData} />}
        </aside>}
      </div>

      {formatsOpen && <FormatPanel library={library} routes={routes} mockFormats={formats} manual={manual} liveCounts={liveCounts} liveFailed={liveFailed} highlight={pendingExt}
        onRefresh={() => setRefreshId(value => value + 1)} onAddManual={addManual} onOpenFlow={id => openFlow(id)} onCreateRoute={createRoute}
        onOpenDocuments={ext => onOpenDocuments(ext)} onOpenLive={onOpenLiveDocuments} onClose={() => setFormatsOpen(false)} />}
      {insertMenu && <div className="ps-insert-menu" style={{ left: insertMenu.x, top: insertMenu.y }} role="menu" aria-label="삽입할 단계">
        <span>사이에 넣기</span>
        {INSERTABLE.map(kind => { const Icon = KIND_META[kind].icon; return <button key={kind} role="menuitem" onClick={() => { insertOnEdge(insertMenu.edgeId, kind); setInsertMenu(null); }}><Icon size={14} />{KIND_META[kind].label}</button>; })}
      </div>}
      <ArrowDefs />
      <input ref={importRef} type="file" accept="application/json,.json" hidden aria-label="흐름 JSON 가져오기" onChange={event => { const file = event.target.files?.[0]; if (file) void importJson(file); event.target.value = ''; }} />
    </section>
  </FlowUIContext.Provider>;
}

/** 새 도형이 기존 노드와 겹치지 않는 가까운 자리를 찾는다. */
function freeSpot(start: XYPosition, size: { w: number; h: number }, nodes: FlowNode[]): XYPosition {
  const hits = (x: number, y: number) => nodes.some(node => { const s = sizeOf(node); return x < node.position.x + s.w + 16 && x + size.w + 16 > node.position.x && y < node.position.y + s.h + 16 && y + size.h + 16 > node.position.y; });
  for (let ring = 0; ring < 8; ring++) for (const [dx, dy] of ring ? [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]] : [[0, 0]]) {
    const x = snap(start.x + dx * ring * (size.w + 32) * 0.6), y = snap(start.y + dy * ring * (size.h + 32) * 0.8);
    if (!hits(x, y)) return { x, y };
  }
  return start;
}

function ZoomControls({ design }: { design: boolean }) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const { zoom } = useViewport();
  return <Panel position="bottom-left" className="ps-zoom">
    <button onClick={() => zoomOut({ duration: 150 })} aria-label="축소" title="축소"><Minus size={14} /></button>
    <span>{Math.round(zoom * 100)}%</span>
    <button onClick={() => zoomIn({ duration: 150 })} aria-label="확대" title="확대"><Plus size={14} /></button>
    <button onClick={() => fitView({ ...fitOptions(design), duration: 200 })} aria-label="화면에 맞추기" title="화면에 맞추기"><Maximize size={13} /></button>
  </Panel>;
}

function minimapColor(node: FlowNode, metric: NodeMetric | undefined, design: boolean) {
  if (!design && metric) return metric.status === 'error' ? '#ef4444' : metric.status === 'warn' ? '#f59e0b' : metric.status === 'paused' ? '#94a3b8' : metric.status === 'busy' ? '#818cf8' : '#cbd5e1';
  return ({ gateway: '#fbbf24', exception: '#fcd34d', review: '#c4b5fd', start: '#86efac', end: '#94a3b8', subflow: '#a5b4fc', store: '#7dd3fc', note: '#fde68a', task: '#c7d2fe' } as Record<string, string>)[node.data.kind] ?? '#cbd5e1';
}

