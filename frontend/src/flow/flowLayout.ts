import dagre from '@dagrejs/dagre';
import type { FlowDirection, FlowEdge, FlowNode, NodeKind } from './flowTypes';

export const NODE_SIZE: Record<NodeKind, { w: number; h: number }> = {
  start: { w: 196, h: 40 },
  end: { w: 196, h: 40 },
  task: { w: 228, h: 78 },
  review: { w: 228, h: 78 },
  store: { w: 228, h: 78 },
  exception: { w: 212, h: 78 },
  subflow: { w: 156, h: 112 },
  gateway: { w: 56, h: 56 },
  note: { w: 220, h: 112 },
};
export const GRID = 8;

export function sizeOf(node: FlowNode) {
  const fallback = NODE_SIZE[node.data.kind];
  return { w: node.width ?? fallback.w, h: node.height ?? fallback.h };
}

/** dagre로 세로(TB) 또는 가로(LR) 자동 정렬. 메모 노드는 위치를 유지한다. */
export function autoLayout(nodes: FlowNode[], edges: FlowEdge[], direction: FlowDirection): FlowNode[] {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: direction, nodesep: direction === 'TB' ? 22 : 30, ranksep: direction === 'TB' ? 40 : 72, edgesep: 16, marginx: 32, marginy: 32 });
  graph.setDefaultEdgeLabel(() => ({}));
  const placed = nodes.filter(node => node.data.kind !== 'note');
  for (const node of placed) { const { w, h } = sizeOf(node); graph.setNode(node.id, { width: w, height: h }); }
  for (const edge of edges) if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && edge.source !== edge.target) graph.setEdge(edge.source, edge.target, { weight: edge.data?.kind === 'exception' ? 1 : 3 });
  dagre.layout(graph);
  return nodes.map(node => {
    const point = graph.node(node.id) as { x: number; y: number } | undefined;
    if (!point) return node;
    const { w, h } = sizeOf(node);
    return { ...node, position: { x: snap(point.x - w / 2), y: snap(point.y - h / 2) } };
  });
}

export const snap = (value: number) => Math.round(value / GRID) * GRID;
