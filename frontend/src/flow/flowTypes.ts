import type { Edge, Node } from '@xyflow/react';

/** BPMN·draw.io 계열의 도형 종류. 실제 처리 엔진의 단계 정의가 아니라 Mock 흐름 설계용이다. */
export type NodeKind = 'start' | 'task' | 'gateway' | 'review' | 'store' | 'subflow' | 'exception' | 'end' | 'note';
export type TaskIcon = 'collect' | 'detect' | 'parse' | 'ocr' | 'convert' | 'sheet' | 'split' | 'mail' | 'text' | 'relation' | 'quality' | 'index' | 'custom';

export type FlowNodeData = {
  kind: NodeKind;
  label: string;
  icon?: TaskIcon;
  description?: string;
  engine?: string;
  input?: string;
  output?: string;
  /** 모의 운영 파라미터 */
  capacity?: number;
  duration?: number;
  failRate?: number;
  retries?: number;
  holdRate?: number;
  assignee?: string;
  sla?: number;
  /** 하위 흐름 노드가 여는 흐름 ID */
  subflow?: string;
};

export type FlowEdgeKind = 'default' | 'exception';
export type FlowEdgeData = {
  label?: string;
  kind?: FlowEdgeKind;
  /** 확장자 조건. 조건 분기에서 문서 형식으로 경로를 고른다. */
  formats?: string[];
  /** 모의 분기 비율 */
  weight?: number;
  /** 조건에 맞는 경로가 없을 때 쓰는 기본 경로 */
  isDefault?: boolean;
};

export type FlowNode = Node<FlowNodeData, 'flow'>;
export type FlowEdge = Edge<FlowEdgeData, 'flow'>;
export type FlowDirection = 'TB' | 'LR';

export type FlowDoc = {
  id: string;
  title: string;
  summary: string;
  direction: FlowDirection;
  nodes: FlowNode[];
  edges: FlowEdge[];
  builtIn: boolean;
};

export type FlowLibrary = { version: 2; order: string[]; flows: Record<string, FlowDoc> };
export type EditorMode = 'monitor' | 'design';
