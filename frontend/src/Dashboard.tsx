import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, AlertCircle, ArrowDown, ArrowRight, ArrowUp, BarChart3, ChevronDown, ChevronUp, CircleHelp, FileCheck2, FileText, GripVertical, LayoutGrid, ListFilter, RotateCcw, Settings2, SlidersHorizontal, Sparkles, Workflow, X } from 'lucide-react';
import './dashboard.css';
import LiveFlowPanel from './flow/LiveFlowPanel';
import type { FlowSimulator } from './flow/flowSim';

type DocumentItem = { id: string; name: string; source: string; format: string; status: string; stage: string; parser: string; updated: string; note: string; ocr: boolean };
type Props = { docs: DocumentItem[]; onOpenDoc: (id: string) => void; onNavigate: (page: 'documents' | 'pipeline' | 'relations' | 'compare', filter?: { status?: string; format?: string }) => void; simulator?: FlowSimulator; active?: boolean; onOpenPipeline?: (flowId: string, nodeId?: string) => void };
type Tab = 'overview' | 'format' | 'quality';
type WidgetId = 'flow' | 'formats' | 'exceptions' | 'recent' | 'formatBreakdown' | 'routes' | 'sources' | 'statusBreakdown' | 'qualityExceptions' | 'ocr' | 'stages';
type Layout = { order: WidgetId[]; hidden: WidgetId[]; collapsed: WidgetId[] };
type WidgetDef = { id: WidgetId; tab: Tab; title: string; subtitle: string; wide?: boolean; icon: typeof Workflow };

const widgets: WidgetDef[] = [
  { id: 'flow', tab: 'overview', title: '처리 단계 현황', subtitle: '각 문서가 현재 머물러 있는 단계', wide: true, icon: Workflow },
  { id: 'formats', tab: 'overview', title: '파일 형식 분포', subtitle: '현재 문서 목록 기준', icon: BarChart3 },
  { id: 'exceptions', tab: 'overview', title: '확인이 필요한 문서', subtitle: '검토·형식 확인·실패 항목', icon: AlertCircle },
  { id: 'recent', tab: 'overview', title: '최근 문서', subtitle: '예시 수집·처리 목록', wide: true, icon: FileText },
  { id: 'formatBreakdown', tab: 'format', title: '확장자별 문서 분포', subtitle: '형식을 선택하면 해당 문서 목록으로 이동', wide: true, icon: BarChart3 },
  { id: 'routes', tab: 'format', title: '형식별 처리 경로', subtitle: '문서에 기록된 처리 방법 · 예시', icon: Workflow },
  { id: 'sources', tab: 'format', title: '원천별 문서 구성', subtitle: '예시 문서에 기록된 원천', icon: LayoutGrid },
  { id: 'statusBreakdown', tab: 'quality', title: '상태별 문서', subtitle: '현재 상태 기준 · 문서 선택 가능', wide: true, icon: Activity },
  { id: 'qualityExceptions', tab: 'quality', title: '예외 및 검토 대기', subtitle: '상세를 열어 사유와 처리 위치 확인', wide: true, icon: AlertCircle },
  { id: 'ocr', tab: 'quality', title: 'OCR 적용 현황', subtitle: '예시 데이터에 기록된 적용 여부', icon: FileCheck2 },
  { id: 'stages', tab: 'quality', title: '단계별 문서', subtitle: '현재 단계 기준', icon: ListFilter },
];
const allIds = widgets.map(w => w.id);
const storageKey = 'document-ops-dashboard-layout-v1';
const initialLayout: Layout = { order: allIds, hidden: [], collapsed: [] };
const isWidget = (value: unknown): value is WidgetId => typeof value === 'string' && allIds.includes(value as WidgetId);
function loadLayout(): Layout {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return initialLayout;
    const parsed = JSON.parse(raw) as Partial<Record<keyof Layout, unknown>>;
    const order = Array.isArray(parsed.order) ? [...new Set(parsed.order.filter(isWidget))] : [];
    return { order: [...order, ...allIds.filter(id => !order.includes(id))], hidden: Array.isArray(parsed.hidden) ? parsed.hidden.filter(isWidget) : [], collapsed: Array.isArray(parsed.collapsed) ? parsed.collapsed.filter(isWidget) : [] };
  } catch { return initialLayout; }
}
const colors = ['#7567d8', '#5a9db8', '#d3a15c', '#72ac90', '#bf829a', '#9e9ab7', '#6883b6', '#c18468'];
const statusPalette: Record<string, string> = { '처리 완료': '#49a58c', '처리 중': '#6995d7', '검토 필요': '#d4a24d', '형식 확인 필요': '#df8f5b', '처리 실패': '#d56f70', '대기': '#9a9faf' };
const attentionStatus = ['검토 필요', '형식 확인 필요', '처리 실패'];
const tabs: { id: Tab; label: string }[] = [{ id: 'overview', label: '운영 현황' }, { id: 'format', label: '형식 분석' }, { id: 'quality', label: '품질 · 예외' }];
function countBy(docs: DocumentItem[], key: 'format' | 'source' | 'status' | 'stage') {
  const counts = new Map<string, number>();
  docs.forEach(d => { const value = d[key] || '미확인'; counts.set(value, (counts.get(value) || 0) + 1); });
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ko'));
}
function Status({ status }: { status: string }) { return <span className="dash-status"><i style={{ background: statusPalette[status] || '#a0a6b4' }} />{status}</span>; }

export default function Dashboard({ docs, onOpenDoc, onNavigate, simulator, active = true, onOpenPipeline }: Props) {
  const [tab, setTab] = useState<Tab>('overview');
  const [layout, setLayout] = useState<Layout>(loadLayout);
  const [editing, setEditing] = useState(false);
  const [dragId, setDragId] = useState<WidgetId | null>(null);
  const byFormat = useMemo(() => countBy(docs, 'format'), [docs]);
  const byStatus = useMemo(() => countBy(docs, 'status'), [docs]);
  const bySource = useMemo(() => countBy(docs, 'source'), [docs]);
  const byStage = useMemo(() => { const steps = ['수집', '형식 확인', '압축 해제', '파싱', 'OCR', '품질 확인', '관계 추출', '검색용 가공', '인덱스 반영']; return countBy(docs, 'stage').sort((a, b) => { const left = steps.indexOf(a[0]), right = steps.indexOf(b[0]); return (left < 0 ? steps.length : left) - (right < 0 ? steps.length : right); }); }, [docs]);
  const exceptions = docs.filter(d => attentionStatus.includes(d.status));
  const complete = docs.filter(d => d.status === '처리 완료').length;
  const running = docs.filter(d => d.status === '처리 중').length;
  const withOcr = docs.filter(d => d.ocr).length;
  const visible = layout.order.filter(id => widgets.find(w => w.id === id)?.tab === tab && !layout.hidden.includes(id));
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(layout)); } catch { /* Browser storage is optional. */ } }, [layout]);
  function toggle(key: 'hidden' | 'collapsed', id: WidgetId) {
    setLayout(prev => ({ ...prev, [key]: prev[key].includes(id) ? prev[key].filter(item => item !== id) : [...prev[key], id] }));
  }
  function move(id: WidgetId, destination: WidgetId) {
    if (id === destination || widgets.find(w => w.id === id)?.tab !== widgets.find(w => w.id === destination)?.tab) return;
    setLayout(prev => {
      const next = prev.order.filter(item => item !== id);
      const index = next.indexOf(destination);
      next.splice(index, 0, id);
      return { ...prev, order: next };
    });
  }
  function step(id: WidgetId, direction: -1 | 1) {
    const index = visible.indexOf(id);
    const target = visible[index + direction];
    if (!target) return;
    if (direction === -1) move(id, target); else move(target, id);
  }
  const formatBars = (max = byFormat.length) => <div className="dash-format-bars">{byFormat.slice(0, max).map(([format, count], i) => <button key={format} className="dash-bar-row" onClick={() => onNavigate('documents', { format })} title={`${format} 문서 보기`}><span className="dash-bar-name"><i style={{ background: colors[i % colors.length] }} />{format}</span><span className="dash-bar-track"><i style={{ width: `${docs.length ? count / docs.length * 100 : 0}%`, background: colors[i % colors.length] }} /></span><b>{count}<small>건</small></b><ChevronDown size={14} className="dash-bar-arrow"/></button>)}{!byFormat.length && <p className="dash-empty">표시할 문서가 없습니다.</p>}</div>;
  const exceptionList = (limit = exceptions.length) => <div className="dash-exception-list">{exceptions.slice(0, limit).map(d => <button className="dash-exception-row" onClick={() => onOpenDoc(d.id)} key={d.id}><span className="dash-exception-icon"><AlertCircle size={16} /></span><span className="dash-exception-text"><strong>{d.name}</strong><small>{d.note}</small></span><Status status={d.status}/><ArrowRight size={15} className="dash-chevron"/></button>)}{!exceptions.length && <p className="dash-empty">확인이 필요한 문서가 없습니다.</p>}</div>;
  function renderBody(id: WidgetId): ReactNode {
    switch (id) {
      case 'flow': return <><div className="dash-flow">{byStage.map(([stage, count], i) => <div className="dash-flow-step" key={stage}><span className="dash-flow-number">{String(i + 1).padStart(2, '0')}</span><strong>{count}<small>건</small></strong><b>{stage}</b><span className="dash-flow-line"/></div>)}</div><div className="dash-card-foot"><span><i className="dash-live-dot"/>단계별 숫자는 누적 처리량이 아닌 현재 상태입니다.</span><button onClick={() => onNavigate('pipeline')}>파이프라인 열기 <ArrowRight size={14}/></button></div></>;
      case 'formats': return <>{formatBars(5)}{byFormat.length > 5 && <div className="dash-card-foot"><span>그 외 {byFormat.length - 5}개 형식</span><button onClick={() => setTab('format')}>형식 전체 보기 <ArrowRight size={14}/></button></div>}</>;
      case 'exceptions': return <>{exceptionList(3)}<div className="dash-card-foot"><span>총 {exceptions.length}건</span><button onClick={() => onNavigate('documents', { status: '확인 필요 전체' })}>예외 문서 보기 <ArrowRight size={14}/></button></div></>;
      case 'recent': return <div className="dash-table-scroll"><table className="dash-table"><thead><tr><th>문서명 / 원천</th><th>형식</th><th>현재 단계</th><th>상태</th><th>최근 처리</th><th/></tr></thead><tbody>{docs.slice(0, 5).map(d => <tr key={d.id}><td><button className="dash-doc-link" onClick={() => onOpenDoc(d.id)}><span className="dash-doc-icon"><FileText size={16}/></span><span><b>{d.name}</b><small>{d.source} · {d.id}</small></span></button></td><td>{d.format}</td><td>{d.stage}</td><td><Status status={d.status}/></td><td>{d.updated}</td><td><button className="dash-row-btn" aria-label={`${d.name} 상세 보기`} onClick={() => onOpenDoc(d.id)}><ArrowRight size={15}/></button></td></tr>)}</tbody></table><div className="dash-card-foot"><span>예시 문서 {Math.min(5, docs.length)} / {docs.length}</span><button onClick={() => onNavigate('documents')}>전체 문서 <ArrowRight size={14}/></button></div></div>;
      case 'formatBreakdown': return <div className="dash-chart-split"><div className="dash-donut" style={{ background: docs.length ? `conic-gradient(${byFormat.map(([_, count], i) => { const start = byFormat.slice(0, i).reduce((a, item) => a + item[1], 0) / docs.length * 100; const end = start + count / docs.length * 100; return `${colors[i % colors.length]} ${start}% ${end}%`; }).join(',')})` : '#eaecf1' }}><div><b>{docs.length}</b><span>전체 문서</span></div></div>{formatBars()}</div>;
      case 'routes': return <div className="dash-route-list">{byFormat.map(([format, count]) => { const parsers = [...new Set(docs.filter(d => d.format === format).map(d => d.parser))]; return <button key={format} onClick={() => onNavigate('documents', { format })}><span className="dash-route-format">{format}</span><span><b>{parsers.join(' · ')}</b><small>{count}건의 문서</small></span><ArrowRight size={15}/></button>; })}</div>;
      case 'sources': return <div className="dash-source-list">{bySource.map(([source, count], i) => <div className="dash-source-row" key={source}><span><i style={{background: colors[i % colors.length]}}/>{source}</span><b>{count}건</b><div><i style={{ width: `${docs.length ? count / docs.length * 100 : 0}%`, background: colors[i % colors.length] }}/></div></div>)}</div>;
      case 'statusBreakdown': return <div className="dash-status-visual"><div className="dash-stacked" aria-label="상태별 문서 비율">{byStatus.map(([name, count]) => <button title={`${name} ${count}건`} aria-label={`${name} ${count}건 문서 보기`} key={name} style={{ width: `${docs.length ? count / docs.length * 100 : 0}%`, background: statusPalette[name] || '#a0a6b4' }} onClick={() => onNavigate('documents', { status: name })}/>)}</div><div className="dash-status-legend">{byStatus.map(([name,count]) => <button key={name} onClick={() => onNavigate('documents', {status:name})}><span><i style={{background: statusPalette[name] || '#a0a6b4'}}/>{name}</span><b>{count}<small>건</small></b></button>)}</div></div>;
      case 'qualityExceptions': return <>{exceptionList()}<div className="dash-card-foot"><span>예시 데이터 기준 · {exceptions.length}건</span><button onClick={() => onNavigate('documents', {status:'확인 필요 전체'})}>전체 예외 보기 <ArrowRight size={14}/></button></div></>;
      case 'ocr': return <div className="dash-ocr"><div className="dash-ocr-head"><strong>{withOcr}<small> / {docs.length}건</small></strong><span>OCR 적용 예시</span></div><div className="dash-ocr-track"><i style={{width:`${docs.length ? withOcr/docs.length*100 : 0}%`}}/></div><p>OCR 적용 여부가 기록된 문서 수입니다. 품질 점수나 실제 인식률을 뜻하지 않습니다.</p><button onClick={() => onNavigate('compare')}>파싱 결과 비교 <ArrowRight size={14}/></button></div>;
      case 'stages': return <div className="dash-stage-list">{byStage.map(([stage,count], i) => <div key={stage}><span><i style={{background:colors[i % colors.length]}}/>{stage}</span><b>{count}건</b></div>)}</div>;
    }
  }
  return <div className="dash-root">
    <div className="dash-tabs-bar"><div className="dash-tabs" role="tablist" aria-label="대시보드 보기">{tabs.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'dash-tab-active' : ''} onClick={() => setTab(t.id)}>{t.label}</button>)}</div><button className={'dash-edit-btn '+(editing ? 'dash-edit-active':'')} onClick={() => setEditing(!editing)}><SlidersHorizontal size={15}/>{editing ? '편집 완료' : '위젯 편집'}</button></div>
    {tab === 'overview' && simulator && onOpenPipeline && <LiveFlowPanel simulator={simulator} active={active} onOpen={onOpenPipeline} />}
    <div className="dash-subhead"><h2>샘플 문서</h2><span>파싱 결과·문서 관계를 열어 볼 수 있는 예시 {docs.length}건</span></div>
    <div className="dash-kpis">
      <button onClick={() => onNavigate('documents')}><span>전체 문서 <FileText size={17}/></span><strong>{docs.length}<small>건</small></strong><em>예시 데이터 전체</em></button>
      <button onClick={() => onNavigate('documents', {status:'처리 완료'})}><span>처리 완료 <FileCheck2 size={17}/></span><strong>{complete}<small>건</small></strong><em>인덱스 반영 완료</em></button>
      <button onClick={() => onNavigate('documents', {status:'처리 중'})}><span>처리 중 <Activity size={17}/></span><strong>{running}<small>건</small></strong><em>처리 진행 중</em></button>
      <button className="dash-kpi-attention" onClick={() => onNavigate('documents', {status:'확인 필요 전체'})}><span>확인 필요 <AlertCircle size={17}/></span><strong>{exceptions.length}<small>건</small></strong><em>검토 · 형식 확인 · 실패</em></button>
    </div>
    {editing && <div className="dash-editor"><div><strong><Settings2 size={16}/> 위젯 구성</strong><p>드래그하거나 화살표로 순서를 바꾸고, 필요한 항목만 표시해요. 이 브라우저에만 저장됩니다.</p></div><div className="dash-editor-buttons">{widgets.filter(w => w.tab === tab).map(w => <button className={!layout.hidden.includes(w.id) ? 'dash-editor-on' : ''} key={w.id} onClick={() => toggle('hidden', w.id)} aria-pressed={!layout.hidden.includes(w.id)}>{!layout.hidden.includes(w.id) ? '✓' : '+'} {w.title}</button>)}<button onClick={() => setLayout(initialLayout)}><RotateCcw size={12}/> 초기화</button></div></div>}
    <div className="dash-section-heading"><div><h2>{tabs.find(t => t.id === tab)?.label}</h2><span>예시 문서 {docs.length}건 기준 · 클릭하여 상세 확인</span></div><span className="dash-instruction"><GripVertical size={14}/> 위젯을 잡고 순서 변경</span></div>
    <div className="dash-grid">{visible.map((id, index) => { const def = widgets.find(w => w.id === id)!; const isCollapsed = layout.collapsed.includes(id); const Icon = def.icon; return <section key={id} className={'dash-widget '+(def.wide ? 'dash-widget-wide ' : '')+(dragId === id ? 'dash-dragging' : '')} onDragOver={e => { if(dragId && dragId!==id){e.preventDefault();e.dataTransfer.dropEffect='move';} }} onDrop={e => {e.preventDefault();if(dragId)move(dragId,id);setDragId(null)}}><div className="dash-widget-head"><div className="dash-widget-title"><span className="dash-widget-icon"><Icon size={16}/></span><span><h3>{def.title}</h3><small>{def.subtitle}</small></span></div><div className="dash-widget-actions"><button className="dash-drag-handle" draggable onDragStart={e => {setDragId(id);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',id)}} onDragEnd={() => setDragId(null)} title="드래그하여 위젯 순서 변경" aria-label={`${def.title} 순서 변경: 드래그 또는 화살표 사용`}><GripVertical size={16}/></button>{editing && <><button onClick={() => step(id,-1)} disabled={index===0} title="앞으로 이동" aria-label={`${def.title} 앞으로 이동`}><ArrowUp size={14}/></button><button onClick={() => step(id,1)} disabled={index===visible.length-1} title="뒤로 이동" aria-label={`${def.title} 뒤로 이동`}><ArrowDown size={14}/></button><button onClick={() => toggle('hidden',id)} title="숨기기" aria-label={`${def.title} 숨기기`}><X size={14}/></button></>}<button onClick={() => toggle('collapsed',id)} aria-expanded={!isCollapsed} aria-label={`${def.title} ${isCollapsed ? '펼치기':'접기'}`}>{isCollapsed?<ChevronDown size={16}/>:<ChevronUp size={16}/>}</button></div></div>{!isCollapsed && <div className="dash-widget-body">{renderBody(id)}</div>}</section>})}</div>
    {visible.length===0 && <div className="dash-all-hidden"><CircleHelp size={19}/><b>이 보기에 표시되는 위젯이 없습니다.</b><button onClick={() => setEditing(true)}>위젯 다시 표시</button></div>}
  </div>;
}
