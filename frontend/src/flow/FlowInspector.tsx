import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, ArrowRight, ArrowRightLeft, Ban, Check, ChevronsUp, CirclePause, CirclePlay, Copy, Download, ExternalLink, FileSearch, LayoutGrid, Minus, Plus, RotateCcw, Route, SkipForward, Trash2, TriangleAlert, Upload, X } from 'lucide-react';
import { KIND_META, STATUS_LABEL, TASK_ICON, wait } from './FlowCanvasParts';
import { aggregate, rid, splitRid } from './flowSim';
import type { DocAction, FlowSimulator, NodeMetric, SimDoc, SimSnapshot } from './flowSim';
import { formatsOfFlow, OVERVIEW_ID } from './flowTemplates';
import type { FlowDirection, FlowDoc, FlowEdge, FlowEdgeData, FlowLibrary, FlowNode, FlowNodeData, NodeKind, TaskIcon } from './flowTypes';

export type Issue = { nodeId?: string; text: string };
export function validateFlow(doc: FlowDoc, library: FlowLibrary): Issue[] {
  const issues: Issue[] = [];
  const active = doc.nodes.filter(node => node.data.kind !== 'note');
  if (!active.some(node => node.data.kind === 'start')) issues.push({ text: '시작 노드가 없습니다.' });
  for (const node of active) {
    const ins = doc.edges.filter(edge => edge.target === node.id).length, outs = doc.edges.filter(edge => edge.source === node.id);
    const kind = node.data.kind;
    if (kind !== 'start' && ins === 0) issues.push({ nodeId: node.id, text: `${node.data.label} · 들어오는 연결이 없습니다.` });
    if (kind !== 'end' && kind !== 'exception' && outs.filter(edge => edge.data?.kind !== 'exception').length === 0) issues.push({ nodeId: node.id, text: `${node.data.label} · 다음 단계가 없어 문서가 멈춥니다.` });
    if (kind === 'gateway' && outs.length < 2) issues.push({ nodeId: node.id, text: `${node.data.label} · 분기가 2개 미만입니다.` });
    if (kind === 'subflow' && (!node.data.subflow || !library.flows[node.data.subflow])) issues.push({ nodeId: node.id, text: `${node.data.label} · 연결된 하위 흐름이 없습니다.` });
  }
  return issues;
}

/* ---------- 공통 입력 ---------- */
function TextField({ label, value, onCommit, multiline, placeholder }: { label: string; value: string; onCommit: (value: string) => void; multiline?: boolean; placeholder?: string }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => { if (draft !== value) onCommit(draft); };
  return <label className="fi-field"><span>{label}</span>{multiline
    ? <textarea rows={3} value={draft} placeholder={placeholder} onChange={event => setDraft(event.target.value)} onBlur={commit} />
    : <input value={draft} placeholder={placeholder} onChange={event => setDraft(event.target.value)} onBlur={commit} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} />}</label>;
}
function NumberField({ label, value, onCommit, min, max, step = 1, suffix }: { label: string; value: number; onCommit: (value: number) => void; min: number; max: number; step?: number; suffix?: string }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => { const parsed = Number(draft); if (Number.isFinite(parsed)) { const next = Math.max(min, Math.min(max, parsed)); if (next !== value) onCommit(next); setDraft(String(next)); } else setDraft(String(value)); };
  return <label className="fi-field fi-number"><span>{label}</span><div><input inputMode="decimal" value={draft} onChange={event => setDraft(event.target.value)} onBlur={commit} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} />{suffix && <em>{suffix}</em>}</div></label>;
}
function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return <section className="fi-section"><header><h4>{title}</h4>{aside}</header>{children}</section>;
}
const pct = (value?: number) => Math.round((value ?? 0) * 1000) / 10;

/* ---------- 설계 모드 ---------- */
type DesignProps = {
  library: FlowLibrary; flow: FlowDoc; node?: FlowNode; edge?: FlowEdge; issues: Issue[];
  onNodeData: (id: string, patch: Partial<FlowNodeData>) => void;
  onNodeKind: (id: string, kind: NodeKind) => void;
  onEdgeData: (id: string, patch: Partial<FlowEdgeData>) => void;
  onSelectNode: (id: string) => void; onSelectEdge: (id: string) => void;
  onDuplicate: () => void; onRemove: () => void;
  onAppend: (nodeId: string, kind: NodeKind) => void; onInsert: (edgeId: string, kind: NodeKind) => void; onReverse: (edgeId: string) => void;
  onOpenFlow: (flowId: string) => void;
  onFlowMeta: (patch: Partial<Pick<FlowDoc, 'title' | 'summary'>>) => void;
  onLayout: (direction: FlowDirection) => void; onResetFlow: () => void; onDeleteFlow: () => void;
  onExport: () => void; onImport: () => void; onOpenDocuments: (format: string) => void;
};
const INSERTABLE: NodeKind[] = ['task', 'review', 'gateway', 'exception', 'store', 'subflow'];

export function DesignInspector(props: DesignProps) {
  const { node, edge } = props;
  if (node) return <NodeDesign {...props} node={node} />;
  if (edge) return <EdgeDesign {...props} edge={edge} />;
  return <FlowDesign {...props} />;
}

function FlowDesign({ library, flow, issues, onSelectNode, onFlowMeta, onLayout, onResetFlow, onDeleteFlow, onExport, onImport, onOpenDocuments }: DesignProps) {
  const [confirmReset, setConfirmReset] = useState(false);
  const formats = flow.id === OVERVIEW_ID ? [] : formatsOfFlow(library, flow.id);
  return <div className="fi-body">
    <div className="fi-head"><span className="fi-kicker">흐름</span><h3>{flow.title}</h3><p>{flow.summary}</p></div>
    <Section title="기본 정보">
      <TextField label="흐름 이름" value={flow.title} onCommit={title => title.trim() && onFlowMeta({ title: title.trim() })} />
      <TextField label="설명" value={flow.summary} onCommit={summary => onFlowMeta({ summary })} multiline />
      {flow.id !== OVERVIEW_ID && <div className="fi-field"><span>들어오는 형식</span><div className="fi-chips">{formats.length ? formats.map(format => <button key={format} className="fi-chip" onClick={() => onOpenDocuments(format)} title={`${format} 예시 문서 보기`}>{format}<FileSearch size={11} /></button>) : <small className="fi-muted">전체 흐름의 라우팅에 연결되지 않았습니다.</small>}</div></div>}
      <div className="fi-stats"><span>노드 <b>{flow.nodes.length}</b></span><span>연결 <b>{flow.edges.length}</b></span><span>방향 <b>{flow.direction === 'TB' ? '세로' : '가로'}</b></span></div>
    </Section>
    <Section title="검증" aside={<span className={`fi-badge ${issues.length ? 'is-warn' : 'is-ok'}`}>{issues.length ? `${issues.length}건` : '문제 없음'}</span>}>
      {issues.length ? <ul className="fi-issues">{issues.map((issue, index) => <li key={index}><button disabled={!issue.nodeId} onClick={() => issue.nodeId && onSelectNode(issue.nodeId)}><TriangleAlert size={13} /><span>{issue.text}</span></button></li>)}</ul> : <p className="fi-muted">모든 단계가 시작에서 종료까지 이어져 있습니다.</p>}
    </Section>
    <Section title="정렬과 파일">
      <div className="fi-grid2">
        <button className="fi-button" onClick={() => onLayout('TB')}><LayoutGrid size={14} /> 세로 자동 정렬</button>
        <button className="fi-button" onClick={() => onLayout('LR')}><ArrowRightLeft size={14} /> 가로 자동 정렬</button>
        <button className="fi-button" onClick={onExport}><Download size={14} /> JSON 내보내기</button>
        <button className="fi-button" onClick={onImport}><Upload size={14} /> JSON 가져오기</button>
      </div>
      {confirmReset ? <div className="fi-confirm"><span>{flow.builtIn ? '기본 구성으로 되돌릴까요?' : '이 흐름을 삭제할까요?'}</span><button className="fi-button is-danger" onClick={() => { setConfirmReset(false); flow.builtIn ? onResetFlow() : onDeleteFlow(); }}>{flow.builtIn ? '되돌리기' : '삭제'}</button><button className="fi-button" onClick={() => setConfirmReset(false)}>취소</button></div>
        : <button className="fi-button is-ghost" onClick={() => setConfirmReset(true)}>{flow.builtIn ? <><RotateCcw size={14} /> 기본 구성으로 되돌리기</> : <><Trash2 size={14} /> 흐름 삭제</>}</button>}
    </Section>
    <div className="fi-help"><b>조작</b><span>왼쪽 도형을 끌어 놓거나 눌러 추가 · 노드 가장자리 점을 끌어 연결 · 연결선 위 + 로 중간에 삽입 · 더블클릭으로 이름 수정 · Delete 삭제 · ⌘Z 되돌리기 · ⌘D 복제 · 방향키로 이동</span></div>
  </div>;
}

function NodeDesign({ library, flow, node, onNodeData, onNodeKind, onSelectEdge, onDuplicate, onRemove, onAppend, onOpenFlow }: DesignProps & { node: FlowNode }) {
  const data = node.data;
  const set = (patch: Partial<FlowNodeData>) => onNodeData(node.id, patch);
  const incoming = flow.edges.filter(edge => edge.target === node.id), outgoing = flow.edges.filter(edge => edge.source === node.id);
  const name = (id: string) => flow.nodes.find(item => item.id === id)?.data.label ?? id;
  const Icon = KIND_META[data.kind].icon;
  const runnable = data.kind === 'task' || data.kind === 'store' || data.kind === 'review';
  return <div className="fi-body">
    <div className="fi-head"><span className="fi-kicker"><Icon size={13} /> {KIND_META[data.kind].label}</span><h3>{data.label}</h3>{data.description && <p>{data.description}</p>}</div>
    <Section title="속성">
      <TextField label="이름" value={data.label} onCommit={label => label.trim() && set({ label: label.trim() })} multiline={data.kind === 'note'} />
      {data.kind !== 'note' && <label className="fi-field"><span>도형</span><select value={data.kind} onChange={event => onNodeKind(node.id, event.target.value as NodeKind)}>{(Object.keys(KIND_META) as NodeKind[]).filter(kind => kind !== 'note').map(kind => <option key={kind} value={kind}>{KIND_META[kind].label}</option>)}</select></label>}
      {(data.kind === 'task' || data.kind === 'store') && <label className="fi-field"><span>작업 종류</span><select value={data.icon ?? 'custom'} onChange={event => set({ icon: event.target.value as TaskIcon })}>{(Object.keys(TASK_ICON) as TaskIcon[]).map(icon => <option key={icon} value={icon}>{TASK_ICON[icon].label}</option>)}</select></label>}
      {data.kind === 'subflow' && <label className="fi-field"><span>하위 흐름</span><div className="fi-inline"><select value={data.subflow ?? ''} onChange={event => set({ subflow: event.target.value || undefined })}><option value="">선택하세요</option>{library.order.filter(id => id !== flow.id).map(id => <option key={id} value={id}>{library.flows[id].title}</option>)}</select><button className="fi-icon" disabled={!data.subflow} onClick={() => data.subflow && onOpenFlow(data.subflow)} aria-label="하위 흐름 열기" title="하위 흐름 열기"><ExternalLink size={14} /></button></div></label>}
      {data.kind !== 'note' && data.kind !== 'gateway' && data.kind !== 'start' && data.kind !== 'end' && <TextField label="처리 엔진 · 담당" value={data.kind === 'exception' ? data.assignee ?? '' : data.engine ?? ''} onCommit={value => set(data.kind === 'exception' ? { assignee: value } : { engine: value })} placeholder="예: Docling" />}
      {data.kind !== 'note' && <TextField label="설명" value={data.description ?? ''} onCommit={description => set({ description })} multiline />}
      {runnable && <div className="fi-grid2"><TextField label="입력" value={data.input ?? ''} onCommit={input => set({ input })} /><TextField label="출력" value={data.output ?? ''} onCommit={output => set({ output })} /></div>}
    </Section>
    {runnable && <Section title="운영 파라미터">
      <div className="fi-grid2">
        <NumberField label="동시 처리" value={data.capacity ?? 3} min={1} max={32} onCommit={capacity => set({ capacity })} suffix="개" />
        <NumberField label="평균 처리 시간" value={data.duration ?? 2} min={0.2} max={60} step={0.1} onCommit={duration => set({ duration })} suffix="초" />
        <NumberField label="자동 재시도" value={data.retries ?? 0} min={0} max={5} onCommit={retries => set({ retries })} suffix="회" />
        <NumberField label="모의 실패율" value={pct(data.failRate)} min={0} max={100} step={0.5} onCommit={value => set({ failRate: value / 100 })} suffix="%" />
        {data.kind === 'task' && <NumberField label="하위 문서 생성 확률" value={pct(data.spawnRate)} min={0} max={100} onCommit={value => set({ spawnRate: value / 100 })} suffix="%" />}
        {data.kind === 'task' && <NumberField label="최대 하위 문서" value={data.spawnMax ?? 1} min={1} max={20} onCommit={spawnMax => set({ spawnMax })} suffix="개" />}
        {data.kind === 'review' && <NumberField label="사람 검토 비율" value={pct(data.holdRate)} min={0} max={100} onCommit={value => set({ holdRate: value / 100 })} suffix="%" />}
        {data.kind === 'review' && <NumberField label="목표 처리" value={data.sla ?? 30} min={1} max={1440} onCommit={sla => set({ sla })} suffix="분" />}
      </div>
      {data.kind === 'review' && <TextField label="검토 담당" value={data.assignee ?? ''} onCommit={assignee => set({ assignee })} />}
    </Section>}
    {data.kind !== 'note' && <Section title="연결">
      <div className="fi-links">
        <div><span>들어옴 {incoming.length}</span>{incoming.map(edge => <button key={edge.id} onClick={() => onSelectEdge(edge.id)}>{name(edge.source)}{edge.data?.label && <em>{edge.data.label}</em>}</button>)}</div>
        <div><span>나감 {outgoing.length}</span>{outgoing.map(edge => <button key={edge.id} onClick={() => onSelectEdge(edge.id)} className={edge.data?.kind === 'exception' ? 'is-exception' : ''}>{name(edge.target)}{edge.data?.label && <em>{edge.data.label}</em>}</button>)}</div>
      </div>
      {data.kind !== 'end' && data.kind !== 'exception' && <div className="fi-append"><span>다음에 추가</span><div>{INSERTABLE.map(kind => { const KindIcon = KIND_META[kind].icon; return <button key={kind} onClick={() => onAppend(node.id, kind)} title={`${KIND_META[kind].label} 추가`} aria-label={`다음에 ${KIND_META[kind].label} 추가`}><KindIcon size={14} /></button>; })}</div></div>}
    </Section>}
    <div className="fi-actions"><button className="fi-button" onClick={onDuplicate}><Copy size={14} /> 복제</button><button className="fi-button is-danger" onClick={onRemove}><Trash2 size={14} /> 삭제</button></div>
    {incoming.length === 1 && outgoing.length === 1 && <p className="fi-muted fi-note">삭제하면 앞뒤 단계가 자동으로 다시 연결됩니다.</p>}
    {data.kind === 'gateway' && outgoing.length > 0 && <Section title="분기 조건">{outgoing.map(edge => <button key={edge.id} className="fi-branch" onClick={() => onSelectEdge(edge.id)}><b>{edge.data?.label || '이름 없음'}</b><span>{edge.data?.formats?.length ? edge.data.formats.join(' · ') : `비율 ${edge.data?.weight ?? 1}`}{edge.data?.isDefault ? ' · 기본' : ''}</span><ArrowRight size={13} /></button>)}</Section>}
    {data.kind === 'gateway' && <p className="fi-muted fi-note">조건은 연결선을 선택해 수정합니다.</p>}
  </div>;
}

function EdgeDesign({ flow, edge, onEdgeData, onInsert, onReverse, onRemove, onSelectNode }: DesignProps & { edge: FlowEdge }) {
  const source = flow.nodes.find(node => node.id === edge.source), target = flow.nodes.find(node => node.id === edge.target);
  const data = edge.data ?? {};
  const set = (patch: Partial<FlowEdgeData>) => onEdgeData(edge.id, patch);
  const fromGateway = source?.data.kind === 'gateway';
  return <div className="fi-body">
    <div className="fi-head"><span className="fi-kicker"><Route size={13} /> 연결</span><h3 className="fi-route"><button onClick={() => source && onSelectNode(source.id)}>{source?.data.label}</button><ArrowRight size={14} /><button onClick={() => target && onSelectNode(target.id)}>{target?.data.label}</button></h3></div>
    <Section title="속성">
      <TextField label="라벨" value={data.label ?? ''} onCommit={label => set({ label: label.trim() || undefined })} placeholder={fromGateway ? '예: 스캔 · 혼합' : '선택 사항'} />
      <label className="fi-field"><span>연결 종류</span><div className="fi-segment"><button className={data.kind !== 'exception' ? 'is-on' : ''} onClick={() => set({ kind: 'default' })}>기본 흐름</button><button className={data.kind === 'exception' ? 'is-on' : ''} onClick={() => set({ kind: 'exception' })}>예외 · 실패</button></div></label>
      {data.kind === 'exception' && <p className="fi-muted">자동 재시도 후에도 실패하거나 반려된 문서가 이 연결로 이동합니다.</p>}
      {fromGateway && <>
        <TextField label="형식 조건 (쉼표로 구분)" value={(data.formats ?? []).join(', ')} onCommit={value => { const list = [...new Set(value.split(/[,\s·]+/).map(item => item.trim().replace(/^\./, '').toUpperCase()).filter(item => /^[A-Z0-9]{1,20}$/.test(item)))]; set({ formats: list.length ? list : undefined }); }} placeholder="예: PDF, TIFF" />
        <NumberField label="모의 분기 비율" value={data.weight ?? 1} min={0} max={1000} onCommit={weight => set({ weight })} />
        <label className="fi-check"><input type="checkbox" checked={!!data.isDefault} onChange={event => set({ isDefault: event.target.checked })} /> 조건에 맞는 경로가 없을 때 기본 경로로 사용</label>
      </>}
    </Section>
    <Section title="중간에 단계 삽입"><div className="fi-insert">{INSERTABLE.map(kind => { const KindIcon = KIND_META[kind].icon; return <button key={kind} onClick={() => onInsert(edge.id, kind)}><KindIcon size={14} />{KIND_META[kind].label}</button>; })}</div></Section>
    <div className="fi-actions"><button className="fi-button" onClick={() => onReverse(edge.id)}><ArrowRightLeft size={14} /> 방향 뒤집기</button><button className="fi-button is-danger" onClick={onRemove}><Trash2 size={14} /> 삭제</button></div>
  </div>;
}

/* ---------- 운영 모드 ---------- */
type MonitorProps = {
  library: FlowLibrary; flow: FlowDoc; node?: FlowNode; snapshot: SimSnapshot; sim: FlowSimulator; metrics: Record<string, NodeMetric | undefined>;
  attention: ReturnType<typeof getAttentionStages>;
  onNavigate: (flowId: string, nodeId?: string) => void; onNodeData: (id: string, patch: Partial<FlowNodeData>) => void;
};
export function MonitorInspector(props: MonitorProps) {
  return props.node ? <NodeMonitor {...props} node={props.node} /> : <Overview {...props} />;
}

function nodeLabel(library: FlowLibrary, runtimeId: string) {
  const { flowId, nodeId } = splitRid(runtimeId);
  const doc = library.flows[flowId];
  const label = doc?.nodes.find(node => node.id === nodeId)?.data.label ?? nodeId;
  return { flowId, nodeId, label, path: flowId === OVERVIEW_ID ? label : `${doc?.title ?? flowId} › ${label}` };
}
function reason(metric: NodeMetric) {
  if (metric.paused) return '일시정지';
  if (metric.failed) return `실패 ${metric.failed}건`;
  if (metric.held) return `보류 ${metric.held}건`;
  return `대기 ${metric.queued}건`;
}

const ATTENTION_PRIORITY = { error: 0, warn: 1, paused: 2, idle: 3, busy: 3 };

export function getAttentionStages(library: FlowLibrary, metrics: SimSnapshot['metrics'], flowId: string) {
  return Object.entries(metrics)
    .filter(([id, metric]) => ATTENTION_PRIORITY[metric.status] < 3 && (flowId === OVERVIEW_ID || splitRid(id).flowId === flowId))
    .map(([id, metric]) => ({ id, metric, ...nodeLabel(library, id) }))
    .sort((a, b) => ATTENTION_PRIORITY[a.metric.status] - ATTENTION_PRIORITY[b.metric.status]
      || (b.metric.failed + b.metric.held + b.metric.queued) - (a.metric.failed + a.metric.held + a.metric.queued));
}

function Overview({ library, flow, snapshot, attention, onNavigate }: MonitorProps) {
  const actions = snapshot.events.filter(event => event.level === 'action').slice(0, 5);
  return <div className="fi-body">
    <div className="fi-head"><h3>주의가 필요한 단계</h3></div>
    {attention.length ? <ul className="fi-attention">{attention.map(item => <li key={item.id}>
      <button onClick={() => onNavigate(item.flowId, item.nodeId)}>
        <i className={`fx-dot is-${item.metric.status}`} />
        <span><b>{item.label}</b>{flow.id === OVERVIEW_ID && <small>{library.flows[item.flowId]?.title}</small>}</span>
        <em className={`is-${item.metric.status}`}>{reason(item.metric)}</em>
      </button>
    </li>)}</ul> : <p className="fi-muted">이 흐름에는 확인이 필요한 단계가 없습니다.</p>}
    <Section title="최근 개입">{actions.length ? <ul className="fi-events">{actions.map(event => <li key={event.id}><time>{event.clock}</time><span>{event.text.replace(/^운영자 · /, '')}</span></li>)}</ul> : <p className="fi-muted">아직 개입 기록이 없습니다.</p>}</Section>
  </div>;
}

const STATE_LABEL: Record<SimDoc['state'], string> = { queued: '대기', processing: '처리 중', held: '보류', failed: '실패' };

function NodeMonitor({ library, flow, node, snapshot, sim, metrics, onNavigate, onNodeData }: MonitorProps & { node: FlowNode }) {
  const data = node.data;
  const id = rid(flow.id, node.id);
  const metric = metrics[node.id];
  const [filter, setFilter] = useState<'all' | SimDoc['state']>('all');
  const [moveTarget, setMoveTarget] = useState('');
  const childFlow = data.kind === 'subflow' ? data.subflow : undefined;
  const docs = useMemo(() => snapshot.docs.filter(doc => childFlow ? doc.node.startsWith(`${childFlow}::`) : doc.node === id).sort((a, b) => order(a) - order(b) || a.enteredAt - b.enteredAt), [snapshot.docs, id, childFlow]);
  const shown = filter === 'all' ? docs : docs.filter(doc => doc.state === filter);
  const targets = useMemo(() => {
    const local = flow.nodes.filter(item => item.id !== node.id && ['task', 'review', 'store', 'exception'].includes(item.data.kind)).map(item => ({ value: rid(flow.id, item.id), label: item.data.label }));
    const starts = library.order.map(flowId => ({ value: sim.entryOf(flowId) ?? '', label: `${library.flows[flowId].title} 처음부터` })).filter(item => item.value);
    return { local, starts };
  }, [flow, node.id, library, sim]);
  if (!metric) return <div className="fi-body"><div className="fi-head"><h3>{data.label}</h3><p>이 노드는 운영 지표가 없습니다.</p></div></div>;
  const Icon = data.kind === 'task' || data.kind === 'store' ? TASK_ICON[data.icon ?? 'custom'].icon : KIND_META[data.kind].icon;
  const processable = data.kind === 'task' || data.kind === 'store' || data.kind === 'review';
  const outgoing = flow.edges.filter(edge => edge.source === node.id);
  const children = childFlow ? Object.entries(snapshot.metrics).filter(([key, value]) => key.startsWith(`${childFlow}::`) && (value.status === 'error' || value.status === 'warn' || value.status === 'paused')) : [];
  const act = (doc: SimDoc, action: DocAction) => sim.docAction(doc.id, action);
  const childMetric = childFlow ? aggregate(snapshot.metrics, childFlow) : undefined;

  return <div className="fi-body">
    <div className="fi-head"><span className="fi-kicker"><Icon size={13} /> {KIND_META[data.kind].label}</span><h3>{data.label}</h3><span className={`fi-status is-${metric.status}`}><i className={`fx-dot is-${metric.status}`} />{STATUS_LABEL[metric.status]}{metric.bypass ? ' · 우회 중' : ''}</span></div>
    <div className="fi-kpis">
      {data.kind === 'gateway' || data.kind === 'start' || data.kind === 'end' ? <>
        <div><span>통과</span><b>{metric.throughput}<small>/분</small></b></div><div><span>누적</span><b>{metric.done.toLocaleString('ko-KR')}</b></div><div><span>대기</span><b>{metric.queued}</b></div>
      </> : <>
        <div className={metric.queued >= Math.max(8, metric.capacity * 4) ? 'is-warn' : ''}><span>대기</span><b>{metric.queued}</b></div>
        <div><span>처리 중</span><b>{metric.processing}{metric.capacity > 0 && <small>/{metric.capacity}</small>}</b></div>
        <div className={metric.held ? 'is-warn' : ''}><span>보류</span><b>{metric.held}</b></div>
        <div className={metric.failed ? 'is-error' : ''}><span>실패</span><b>{metric.failed}</b></div>
        <div><span>{childFlow ? '완료' : '처리량'}</span><b>{(childMetric ?? metric).throughput}<small>/분</small></b></div>
        <div><span>최장 대기</span><b className="is-small">{wait(metric.oldestWait)}</b></div>
      </>}
    </div>

    {childFlow && <Section title="하위 흐름">
      <button className="fi-button is-primary" onClick={() => onNavigate(childFlow)}><ExternalLink size={14} /> {library.flows[childFlow]?.title ?? '하위 흐름'} 열기</button>
      {children.length > 0 && <ul className="fi-attention">{children.map(([key, value]) => { const info = nodeLabel(library, key); return <li key={key}><button onClick={() => onNavigate(info.flowId, info.nodeId)}><i className={`fx-dot is-${value.status}`} /><span><b>{info.label}</b></span><em className={`is-${value.status}`}>{reason(value)}</em></button></li>; })}</ul>}
    </Section>}

    {!childFlow && data.kind !== 'start' && data.kind !== 'end' && <Section title="개입">
      <div className="fi-controls">
        {data.kind !== 'exception' && <button className={`fi-button ${metric.paused ? 'is-primary' : ''}`} onClick={() => sim.pauseNode(id, !metric.paused)}>{metric.paused ? <><CirclePlay size={14} /> 재개</> : <><CirclePause size={14} /> 일시정지</>}</button>}
        {processable && <div className="fi-stepper" role="group" aria-label="동시 처리 수"><span>동시 처리</span><button aria-label="동시 처리 줄이기" onClick={() => sim.setCapacity(id, metric.capacity - 1)} disabled={metric.capacity <= 1}><Minus size={13} /></button><b>{metric.capacity}</b><button aria-label="동시 처리 늘리기" onClick={() => sim.setCapacity(id, metric.capacity + 1)}><Plus size={13} /></button></div>}
        {data.kind === 'task' && <label className="fi-check"><input type="checkbox" checked={metric.bypass} onChange={event => sim.setBypass(id, event.target.checked)} /> 우회 — 처리하지 않고 다음 단계로 전달</label>}
        {data.kind === 'gateway' && <label className="fi-field"><span>경로 고정</span><select value={metric.forced ?? ''} onChange={event => sim.forceBranch(id, event.target.value || null)}><option value="">자동 (조건대로)</option>{outgoing.map(edge => <option key={edge.id} value={rid(flow.id, edge.id)}>{edge.data?.label || flow.nodes.find(item => item.id === edge.target)?.data.label}</option>)}</select></label>}
        {metric.failed > 0 && <button className="fi-button is-primary" onClick={() => sim.retryFailed(id)}><RotateCcw size={14} /> 실패 {metric.failed}건 재시도</button>}
        {metric.held > 0 && data.kind === 'review' && <div className="fi-grid2"><button className="fi-button is-primary" onClick={() => sim.resolveAll(id, true)}><Check size={14} /> 보류 {metric.held}건 승인</button><button className="fi-button" onClick={() => sim.resolveAll(id, false)}><X size={14} /> 모두 반려</button></div>}
        {(data.kind === 'exception' || metric.held > 0 || metric.failed > 0) && <div className="fi-move"><select aria-label="보낼 위치" value={moveTarget} onChange={event => setMoveTarget(event.target.value)}><option value="">보낼 위치 선택…</option><optgroup label="이 흐름의 단계">{targets.local.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</optgroup><optgroup label="처리 흐름">{targets.starts.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</optgroup></select><button className="fi-button" disabled={!moveTarget || !docs.length} onClick={() => { sim.moveAll(id, moveTarget); setMoveTarget(''); }}><ArrowDownToLine size={14} /> 모두 보내기</button></div>}
      </div>
    </Section>}

    {data.kind !== 'gateway' && data.kind !== 'start' && data.kind !== 'end' && <Section title={`문서 ${docs.length}건`} aside={<div className="fi-filter">{(['all', 'held', 'failed', 'queued', 'processing'] as const).map(value => <button key={value} className={filter === value ? 'is-on' : ''} onClick={() => setFilter(value)}>{value === 'all' ? '전체' : STATE_LABEL[value]}</button>)}</div>}>
      {shown.length ? <ul className="fi-docs">{shown.slice(0, 40).map(doc => <li key={doc.id} className={`is-${doc.state}`}>
        <div className="fi-doc-main"><b title={doc.parentName ? `${doc.name} ← ${doc.parentName}` : doc.name}>{doc.priority && <ChevronsUp size={12} />}{doc.depth > 0 && <i className="fi-depth">{'↳'.repeat(Math.min(doc.depth, 3))}</i>}{doc.name}</b><span><em className={`fi-state is-${doc.state}`}>{STATE_LABEL[doc.state]}</em>{childFlow && <>{nodeLabel(library, doc.node).label} · </>}{doc.state === 'processing' ? `${Math.round(doc.progress * 100)}%` : wait(snapshot.now - doc.enteredAt)}{doc.reason && <> · {doc.reason}</>}</span></div>
        {!childFlow && <div className="fi-doc-actions">
          {doc.state === 'held' && data.kind === 'review' && <><button onClick={() => act(doc, 'approve')} aria-label={`${doc.name} 승인`} title="승인"><Check size={13} /></button><button onClick={() => act(doc, 'reject')} aria-label={`${doc.name} 반려`} title="반려"><X size={13} /></button></>}
          {doc.state === 'failed' && <><button onClick={() => act(doc, 'retry')} aria-label={`${doc.name} 재시도`} title="재시도"><RotateCcw size={13} /></button><button onClick={() => act(doc, 'skip')} aria-label={`${doc.name} 건너뛰기`} title="이 단계 건너뛰기"><SkipForward size={13} /></button></>}
          {doc.state === 'queued' && !doc.priority && <button onClick={() => act(doc, 'prioritize')} aria-label={`${doc.name} 우선 처리`} title="우선 처리"><ChevronsUp size={13} /></button>}
          {doc.state === 'queued' && processable && <button onClick={() => act(doc, 'skip')} aria-label={`${doc.name} 건너뛰기`} title="이 단계 건너뛰기"><SkipForward size={13} /></button>}
          {(doc.state === 'held' || doc.state === 'failed') && <select className="fi-doc-move" aria-label={`${doc.name} 보낼 위치`} value="" onChange={event => event.target.value && sim.moveDoc(doc.id, event.target.value)}><option value="">이동…</option><optgroup label="이 흐름의 단계">{targets.local.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</optgroup><optgroup label="처리 흐름">{targets.starts.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</optgroup></select>}
          <button onClick={() => act(doc, 'cancel')} aria-label={`${doc.name} 처리 제외`} title="처리 제외"><Ban size={13} /></button>
        </div>}
      </li>)}</ul> : <p className="fi-muted">{filter === 'all' ? '이 단계에 머문 문서가 없습니다.' : '해당 상태의 문서가 없습니다.'}</p>}
      {shown.length > 40 && <p className="fi-muted">상위 40건만 표시합니다. 아래 문서 추적에서 전체를 볼 수 있습니다.</p>}
    </Section>}

    {processable && <Section title="모의 조건"><div className="fi-grid2">
      <NumberField label="실패율" value={pct(data.failRate)} min={0} max={100} step={0.5} onCommit={value => onNodeData(node.id, { failRate: value / 100 })} suffix="%" />
      <NumberField label="평균 처리 시간" value={data.duration ?? 2} min={0.2} max={60} step={0.1} onCommit={duration => onNodeData(node.id, { duration })} suffix="초" />
    </div><p className="fi-muted">장애·지연 상황을 재현할 때 사용합니다.</p></Section>}
  </div>;
}
const order = (doc: SimDoc) => ({ failed: 0, held: 1, processing: 2, queued: 3 })[doc.state];
