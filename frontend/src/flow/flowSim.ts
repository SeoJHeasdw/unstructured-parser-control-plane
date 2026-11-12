import { OVERVIEW_ID } from './flowTemplates';
import type { FlowLibrary, NodeKind, TaskIcon } from './flowTypes';

/**
 * 브라우저 안에서만 도는 모의 운영 엔진.
 * 문서가 흐름 그래프를 따라 이동하고, 운영자가 단계별로 개입할 수 있다.
 * 실제 파일·백엔드·모델에는 어떤 요청도 보내지 않는다.
 */
export type DocState = 'queued' | 'processing' | 'held' | 'failed';
export type SimDoc = { id: string; name: string; ext: string; node: string; state: DocState; progress: number; need: number; enteredAt: number; createdAt: number; attempts: number; priority: boolean; reason?: string; hops: number };
export type NodeStatus = 'idle' | 'busy' | 'warn' | 'error' | 'paused';
export type NodeMetric = { kind: NodeKind; queued: number; processing: number; held: number; failed: number; capacity: number; throughput: number; done: number; failedTotal: number; paused: boolean; bypass: boolean; forced?: string; oldestWait: number; status: NodeStatus };
export type SimEvent = { id: number; t: number; clock: string; level: 'info' | 'warn' | 'error' | 'action'; text: string; node?: string; doc?: string };
export type SimTotals = { arrivals: number; inFlight: number; queued: number; processing: number; held: number; failed: number; completed: number; completedPerMin: number; arrivalsPerMin: number };
export type SimSnapshot = { now: number; clock: string; running: boolean; speed: number; rate: number; metrics: Record<string, NodeMetric>; traffic: Record<string, number>; docs: SimDoc[]; events: SimEvent[]; totals: SimTotals; version: number };
export type DocAction = 'approve' | 'reject' | 'retry' | 'skip' | 'prioritize' | 'cancel';

type REdge = { viewKey: string; to: string; formats?: string[]; weight: number; isDefault: boolean; exception: boolean; label: string };
type RNode = { id: string; flowId: string; nodeId: string; kind: NodeKind; icon?: TaskIcon; label: string; capacity: number; duration: number; failRate: number; retries: number; holdRate: number; out: REdge[]; instant: boolean; completes: boolean };
type Control = { paused: boolean; bypass: boolean; forced?: string; capacity?: number };

const TICK_MS = 500;
const WINDOW = 60;
export const rid = (flowId: string, nodeId: string) => `${flowId}::${nodeId}`;
export const splitRid = (id: string) => { const [flowId, ...rest] = id.split('::'); return { flowId, nodeId: rest.join('::') }; };

/** 모의 유입 분포. 실측 분포가 아니다. HEIC·TIFF는 경로가 없는 형식의 예시. */
const MIX: [string, number][] = [['PDF', 26], ['XLSX', 10], ['XLSM', 3], ['XLS', 3], ['DOCX', 10], ['DOCM', 1], ['DOC', 3], ['PPTX', 6], ['PPT', 2], ['CSV', 4], ['EML', 5], ['MSG', 3], ['MHT', 1], ['HTM', 2], ['PNG', 4], ['JPG', 5], ['TXT', 3], ['LOG', 3], ['ZIP', 4], ['HEIC', 2], ['TIFF', 1]];
const NAMES: Record<string, string[]> = {
  PDF: ['제조기록서_BMR-2026-#', '시험성적서_COA-#', 'SOP-QC-#_품질관리', '밸리데이션_보고서_VR-#', '배치기록_검토_#'],
  DOCX: ['일탈보고서_DEV-2026-#', '변경관리_CC-#_검토', 'CAPA_계획서_#'], DOCM: ['품질회의록_매크로_#'], DOC: ['구_SOP_PD-#', '교육자료_#'],
  PPTX: ['변경관리_회의자료_#', '공정개선_발표_#'], PPT: ['설비교육_#'],
  XLSX: ['설비점검_관리대장_#', '시험결과_집계_#', '원료입고_목록_#'], XLSM: ['환경모니터링_집계_#'], XLS: ['구_점검대장_#'],
  CSV: ['센서로그_#', '배치목록_#'], TXT: ['장비로그_#'], LOG: ['MES_이벤트_#'], HTM: ['포털_공지_#'], MHT: ['웹보관_#'],
  EML: ['RE_변경요청_#', '품질이슈_공유_#'], MSG: ['FW_공급사회신_#'], PNG: ['현장사진_#', '라벨스캔_#'], JPG: ['점검사진_#', '서명스캔_#'],
  ZIP: ['장비운영_기록_#', '감사자료_묶음_#'], HEIC: ['현장_기록_#'], TIFF: ['도면스캔_#'],
};
const ERRORS: Partial<Record<TaskIcon, string[]>> = {
  ocr: ['인식 신뢰도 0.62 — 기준 미달', '페이지 기울기 보정 실패'], parse: ['표 구조 추출 시간 초과', '페이지 렌더링 오류'],
  convert: ['변환 도구 응답 없음', '지원하지 않는 레거시 서식'], detect: ['암호로 보호된 압축 파일', '손상된 파일 헤더'],
  sheet: ['외부 연결 수식 해석 실패'], mail: ['첨부 인코딩 오류'], text: ['인코딩 판별 실패'], relation: ['참조 대상 조회 시간 초과'], index: ['인덱스 쓰기 지연'],
};
const HOLDS = ['표 구조 신뢰도 0.71', '숫자·단위 불일치 의심', '스캔 페이지 포함', '참조 문서번호 미확인', '원문 위치 누락'];

function mulberry32(seed: number) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

export class FlowSimulator {
  private source: FlowLibrary;
  private nodes = new Map<string, RNode>();
  private entry = '';
  private flowEntries = new Map<string, string>();
  private flowTitles = new Map<string, string>();
  private docs: SimDoc[] = [];
  private controls = new Map<string, Control>();
  private completions = new Map<string, number[]>();
  private failedTotals = new Map<string, number>();
  private doneTotals = new Map<string, number>();
  private trafficLog = new Map<string, number[]>();
  private arrivalsLog: number[] = [];
  private completedLog: number[] = [];
  private warned = new Set<string>();
  private events: SimEvent[] = [];
  private listeners = new Set<() => void>();
  private random = mulberry32(20261112);
  private now = 0;
  private carry = 0;
  private serial = 0;
  private eventSerial = 0;
  private completed = 0;
  private arrivals = 0;
  private running = true;
  private speed = 1;
  private rate = 36;
  private holders = 0;
  private timer: number | null = null;
  private startedAt = new Date(2026, 10, 12, 9, 0, 0).getTime();
  private snapshot: SimSnapshot;

  constructor(library: FlowLibrary, warmup = 240) {
    this.source = library;
    this.build(library);
    const quiet = this.events.length;
    for (let t = 0; t < warmup; t += TICK_MS / 1000) this.step(TICK_MS / 1000);
    this.events = this.events.slice(quiet).slice(-14);
    this.snapshot = this.compose();
  }

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.snapshot;
  flowTitle(flowId: string) { return this.flowTitles.get(flowId) ?? flowId; }

  /** 화면에 보이는 동안만 시간을 진행한다. */
  acquire() {
    this.holders += 1;
    this.sync();
    return () => { this.holders = Math.max(0, this.holders - 1); this.sync(); };
  }
  private sync() {
    const shouldRun = this.holders > 0 && this.running;
    if (shouldRun && this.timer === null) this.timer = window.setInterval(() => { this.step(TICK_MS / 1000 * this.speed); this.emit(); }, TICK_MS);
    if (!shouldRun && this.timer !== null) { window.clearInterval(this.timer); this.timer = null; }
  }

  getLibrary = () => this.source;

  setLibrary(library: FlowLibrary) {
    if (library === this.source && this.nodes.size) return;
    this.source = library;
    const previous = new Set(this.nodes.keys());
    this.build(library);
    let moved = 0;
    for (const doc of this.docs) {
      if (this.nodes.has(doc.node)) continue;
      const { flowId } = splitRid(doc.node);
      const fallback = this.flowEntries.get(flowId) ?? this.entry;
      if (!fallback) continue;
      doc.node = fallback; doc.state = 'queued'; doc.progress = 0; doc.enteredAt = this.now; moved += 1;
    }
    this.docs = this.docs.filter(doc => this.nodes.has(doc.node));
    for (const id of [...this.controls.keys()]) if (!this.nodes.has(id)) this.controls.delete(id);
    if (moved) this.log('info', `흐름 변경으로 ${moved}건을 해당 흐름의 시작으로 다시 보냈습니다.`);
    else if (previous.size && [...previous].some(id => !this.nodes.has(id))) this.log('info', '흐름 구성이 바뀌어 모의 운영에 반영했습니다.');
    this.emit();
  }

  setRunning(running: boolean) { this.running = running; this.log('action', running ? '운영자 · 전체 흐름 재개' : '운영자 · 전체 흐름 일시정지'); this.sync(); this.emit(); }
  setSpeed(speed: number) { this.speed = speed; this.emit(); }
  setRate(rate: number) { this.rate = Math.max(0, Math.min(240, Math.round(rate))); this.emit(); }

  pauseNode(id: string, paused: boolean) { const node = this.nodes.get(id); if (!node) return; this.control(id).paused = paused; this.log('action', `운영자 · ${node.label} ${paused ? '일시정지' : '재개'}`, id); this.emit(); }
  setCapacity(id: string, capacity: number) { const node = this.nodes.get(id); if (!node) return; const value = Math.max(1, Math.min(32, Math.round(capacity))); this.control(id).capacity = value; this.log('action', `운영자 · ${node.label} 동시 처리 ${value}개로 조정`, id); this.emit(); }
  setBypass(id: string, bypass: boolean) { const node = this.nodes.get(id); if (!node) return; this.control(id).bypass = bypass; this.log('action', `운영자 · ${node.label} ${bypass ? '우회 시작 — 처리 없이 다음 단계로 전달' : '우회 해제'}`, id); this.emit(); }
  forceBranch(id: string, viewKey: string | null) {
    const node = this.nodes.get(id); if (!node) return;
    this.control(id).forced = viewKey ?? undefined;
    const edge = node.out.find(item => item.viewKey === viewKey);
    this.log('action', viewKey ? `운영자 · ${node.label} 경로 고정 → ${edge?.label || this.nodes.get(edge?.to ?? '')?.label || '선택 경로'}` : `운영자 · ${node.label} 경로 고정 해제`, id); this.emit();
  }
  retryFailed(id: string) { const list = this.docs.filter(doc => doc.node === id && doc.state === 'failed'); for (const doc of list) this.requeue(doc); if (list.length) this.log('action', `운영자 · ${this.nodes.get(id)?.label} 실패 ${list.length}건 재시도`, id); this.emit(); }
  resolveAll(id: string, approve: boolean) {
    const list = this.docs.filter(doc => doc.node === id && doc.state === 'held');
    for (const doc of list) approve ? this.release(doc) : this.reject(doc);
    if (list.length) this.log('action', `운영자 · ${this.nodes.get(id)?.label} 보류 ${list.length}건 ${approve ? '승인' : '반려'}`, id);
    this.emit();
  }
  docAction(docId: string, action: DocAction) {
    const doc = this.docs.find(item => item.id === docId); if (!doc) return;
    const node = this.nodes.get(doc.node); const where = node?.label ?? '';
    if (action === 'approve') { this.release(doc); this.log('action', `운영자 · ${doc.name} 승인 (${where})`, doc.node, doc.id); }
    if (action === 'reject') { this.reject(doc); this.log('action', `운영자 · ${doc.name} 반려 (${where})`, node?.id, doc.id); }
    if (action === 'retry') { this.requeue(doc); this.log('action', `운영자 · ${doc.name} 재시도 (${where})`, doc.node, doc.id); }
    if (action === 'skip') { this.log('action', `운영자 · ${doc.name} ${where} 건너뜀`, doc.node, doc.id); this.route(doc, true); }
    if (action === 'prioritize') { doc.priority = true; this.log('action', `운영자 · ${doc.name} 우선 처리 (${where})`, doc.node, doc.id); }
    if (action === 'cancel') { this.docs = this.docs.filter(item => item !== doc); this.log('action', `운영자 · ${doc.name} 처리 제외`, node?.id, doc.id); }
    this.emit();
  }
  moveDoc(docId: string, target: string) {
    const doc = this.docs.find(item => item.id === docId); const node = this.nodes.get(target);
    if (!doc || !node) return;
    const from = this.nodes.get(doc.node)?.label ?? '';
    this.place(doc, target, null);
    this.log('action', `운영자 · ${doc.name} 이동 ${from} → ${this.where(target)}`, target, doc.id);
    this.settle(doc, 0);
    this.emit();
  }
  moveAll(from: string, target: string) {
    const list = this.docs.filter(doc => doc.node === from && (doc.state === 'held' || doc.state === 'failed' || doc.state === 'queued'));
    for (const doc of list) { this.place(doc, target, null); this.settle(doc, 0); }
    if (list.length) this.log('action', `운영자 · ${this.nodes.get(from)?.label} ${list.length}건 → ${this.where(target)} 이동`, target);
    this.emit();
  }
  entryOf(flowId: string) { return this.flowEntries.get(flowId) ?? null; }
  reset() {
    this.docs = []; this.controls.clear(); this.completions.clear(); this.failedTotals.clear(); this.doneTotals.clear(); this.trafficLog.clear();
    this.arrivalsLog = []; this.completedLog = []; this.warned.clear(); this.events = []; this.completed = 0; this.arrivals = 0; this.now = 0; this.carry = 0;
    this.log('action', '운영자 · 모의 운영 초기화'); this.emit();
  }

  private where(id: string) { const node = this.nodes.get(id); if (!node) return ''; const { flowId } = splitRid(id); return flowId === OVERVIEW_ID ? node.label : `${this.flowTitle(flowId)} › ${node.label}`; }
  private control(id: string) { let item = this.controls.get(id); if (!item) { item = { paused: false, bypass: false }; this.controls.set(id, item); } return item; }

  private build(library: FlowLibrary) {
    this.nodes.clear(); this.flowEntries.clear(); this.flowTitles.clear();
    for (const doc of Object.values(library.flows)) {
      this.flowTitles.set(doc.id, doc.title);
      for (const node of doc.nodes) {
        if (node.data.kind === 'note') continue;
        const kind = node.data.kind;
        const instant = kind === 'start' || kind === 'end' || kind === 'gateway' || kind === 'subflow';
        this.nodes.set(rid(doc.id, node.id), {
          id: rid(doc.id, node.id), flowId: doc.id, nodeId: node.id, kind, icon: node.data.icon, label: node.data.label,
          capacity: Math.max(1, node.data.capacity ?? 3), duration: Math.max(0.2, node.data.duration ?? 2), failRate: clamp01(node.data.failRate ?? 0), retries: Math.max(0, node.data.retries ?? 0), holdRate: clamp01(node.data.holdRate ?? 0),
          out: [], instant, completes: false,
        });
        if (kind === 'start' && !this.flowEntries.has(doc.id)) this.flowEntries.set(doc.id, rid(doc.id, node.id));
      }
      for (const edge of doc.edges) {
        const from = this.nodes.get(rid(doc.id, edge.source)); if (!from || !this.nodes.has(rid(doc.id, edge.target))) continue;
        from.out.push({ viewKey: rid(doc.id, edge.id), to: rid(doc.id, edge.target), formats: edge.data?.formats, weight: edge.data?.weight ?? 1, isDefault: !!edge.data?.isDefault, exception: edge.data?.kind === 'exception', label: edge.data?.label ?? '' });
      }
    }
    // 하위 흐름 노드: 들어오는 연결은 하위 흐름의 시작으로, 하위 흐름의 종료는 상위 노드의 다음 단계로 잇는다.
    const entries = new Map<string, { entry: string; child: string }>();
    for (const node of this.nodes.values()) {
      if (node.kind !== 'subflow') continue;
      const child = library.flows[node.flowId]?.nodes.find(item => item.id === node.nodeId)?.data.subflow;
      const entry = child ? this.flowEntries.get(child) : undefined;
      if (child && entry && child !== node.flowId) entries.set(node.id, { entry, child });
    }
    for (const node of this.nodes.values()) for (const edge of node.out) { const target = entries.get(edge.to); if (target) edge.to = target.entry; }
    for (const [id, { child }] of entries) {
      const parent = this.nodes.get(id)!;
      for (const exit of this.nodes.values()) if (exit.flowId === child && exit.kind === 'end' && exit.out.length === 0) exit.out = parent.out.map(edge => ({ ...edge }));
    }
    for (const node of this.nodes.values()) if (node.kind === 'end' && node.out.length === 0) node.completes = true;
    this.entry = this.flowEntries.get(OVERVIEW_ID) ?? [...this.flowEntries.values()][0] ?? '';
  }

  private step(dt: number) {
    this.now += dt;
    // 유입
    if (this.entry) {
      this.carry += (this.rate / 60) * dt;
      while (this.carry >= 1) { this.carry -= 1; this.spawn(); }
    }
    // 처리 진행
    for (const doc of [...this.docs]) {
      if (doc.state !== 'processing') continue;
      doc.progress += dt / doc.need;
      if (doc.progress >= 1) this.finish(doc);
    }
    // 대기열에서 시작
    const byNode = new Map<string, SimDoc[]>();
    for (const doc of this.docs) if (doc.state === 'queued' || doc.state === 'processing') { const list = byNode.get(doc.node) ?? []; list.push(doc); byNode.set(doc.node, list); }
    for (const [id, list] of byNode) {
      const node = this.nodes.get(id); if (!node) continue;
      const control = this.control(id);
      if (control.paused) continue;
      if (node.instant) { for (const doc of list.filter(item => item.state === 'queued')) this.settle(doc, 0); continue; }
      if (control.bypass) { for (const doc of list.filter(item => item.state === 'queued')) this.route(doc, true); continue; }
      let free = (control.capacity ?? node.capacity) - list.filter(doc => doc.state === 'processing').length;
      const queue = list.filter(doc => doc.state === 'queued').sort((a, b) => Number(b.priority) - Number(a.priority) || a.enteredAt - b.enteredAt);
      for (const doc of queue) { if (free <= 0) break; doc.state = 'processing'; doc.progress = 0; doc.need = node.duration * (0.6 + this.random() * 0.8); free -= 1; }
    }
    this.watch();
  }

  private spawn() {
    const total = MIX.reduce((sum, [, weight]) => sum + weight, 0);
    let pick = this.random() * total, ext = 'PDF';
    for (const [format, weight] of MIX) { pick -= weight; if (pick <= 0) { ext = format; break; } }
    const names = NAMES[ext] ?? ['문서_#'];
    const name = `${names[Math.floor(this.random() * names.length)].replace('#', String(1000 + Math.floor(this.random() * 9000)))}.${ext.toLowerCase()}`;
    this.serial += 1; this.arrivals += 1; this.arrivalsLog.push(this.now);
    const doc: SimDoc = { id: `SIM-${String(this.serial).padStart(5, '0')}`, name, ext, node: this.entry, state: 'queued', progress: 0, need: 1, enteredAt: this.now, createdAt: this.now, attempts: 0, priority: false, hops: 0 };
    this.docs.push(doc);
    this.settle(doc, 0);
  }

  /** 즉시 통과 노드(시작·분기·종료)와 예외 대기열 도착을 처리한다. */
  private settle(doc: SimDoc, depth: number) {
    const node = this.nodes.get(doc.node);
    if (!node || depth > 40 || !this.docs.includes(doc)) return;
    if (node.kind === 'exception') { doc.state = 'held'; doc.reason = doc.reason ?? '담당자 확인 필요'; return; }
    if (node.instant) {
      if (this.control(node.id).paused) return;
      if (node.completes) { this.complete(doc, node); return; }
      this.tally(node.id);
      this.route(doc, false, depth);
    }
  }

  private finish(doc: SimDoc) {
    const node = this.nodes.get(doc.node); if (!node) return;
    if (this.random() < node.failRate) {
      doc.attempts += 1;
      const messages = ERRORS[node.icon ?? 'custom'] ?? ['처리 오류'];
      const message = messages[Math.floor(this.random() * messages.length)];
      if (doc.attempts <= node.retries) { doc.state = 'queued'; doc.progress = 0; doc.reason = `자동 재시도 ${doc.attempts}회 · ${message}`; return; }
      this.failedTotals.set(node.id, (this.failedTotals.get(node.id) ?? 0) + 1);
      const fallback = node.out.find(edge => edge.exception);
      doc.reason = message;
      if (fallback) { this.log('error', `${node.label} · ${doc.name} 실패 → ${this.nodes.get(fallback.to)?.label ?? '예외 경로'} (${message})`, node.id, doc.id); this.place(doc, fallback.to, fallback.viewKey); this.settle(doc, 0); return; }
      doc.state = 'failed'; doc.progress = 0;
      this.log('error', `${node.label} · ${doc.name} 처리 실패 (${message})`, node.id, doc.id);
      return;
    }
    this.tally(node.id);
    if (node.kind === 'review' && this.random() < node.holdRate) { doc.state = 'held'; doc.progress = 0; doc.reason = HOLDS[Math.floor(this.random() * HOLDS.length)]; return; }
    this.route(doc, false);
  }

  private route(doc: SimDoc, manual: boolean, depth = 0) {
    const node = this.nodes.get(doc.node); if (!node) return;
    if (manual) this.tally(node.id);
    const normal = node.out.filter(edge => !edge.exception);
    const forced = this.control(node.id).forced;
    let edge = forced ? node.out.find(item => item.viewKey === forced) : undefined;
    if (!edge && node.kind === 'gateway' && node.out.some(item => item.formats?.length)) edge = node.out.find(item => item.formats?.includes(doc.ext)) ?? node.out.find(item => item.isDefault);
    if (!edge && normal.length) {
      const total = normal.reduce((sum, item) => sum + Math.max(0, item.weight), 0);
      let pick = this.random() * (total || normal.length);
      edge = normal.find(item => (pick -= total ? Math.max(0, item.weight) : 1) <= 0) ?? normal[normal.length - 1];
    }
    if (!edge) edge = node.out.find(item => item.isDefault) ?? node.out[0];
    if (!edge) {
      if (node.kind === 'end') { this.complete(doc, node); return; }
      doc.state = 'held'; doc.progress = 0; doc.reason = '다음 단계 연결 없음';
      return;
    }
    this.place(doc, edge.to, edge.viewKey);
    this.settle(doc, depth + 1);
  }

  private place(doc: SimDoc, target: string, viewKey: string | null) {
    if (viewKey) { const log = this.trafficLog.get(viewKey) ?? []; log.push(this.now); this.trafficLog.set(viewKey, log); }
    doc.node = target; doc.state = 'queued'; doc.progress = 0; doc.enteredAt = this.now; doc.hops += 1; doc.attempts = 0;
    if (!this.nodes.get(target) || this.nodes.get(target)?.kind !== 'exception') doc.reason = undefined;
  }
  private requeue(doc: SimDoc) { doc.state = 'queued'; doc.progress = 0; doc.attempts = 0; doc.reason = undefined; doc.enteredAt = this.now; }
  private release(doc: SimDoc) { doc.reason = undefined; this.route(doc, false); }
  private reject(doc: SimDoc) {
    const node = this.nodes.get(doc.node);
    const fallback = node?.out.find(edge => edge.exception);
    if (fallback && node?.kind !== 'exception') { doc.reason = '운영자 반려'; this.place(doc, fallback.to, fallback.viewKey); this.settle(doc, 0); return; }
    this.docs = this.docs.filter(item => item !== doc);
  }
  private complete(doc: SimDoc, node: RNode) {
    this.tally(node.id);
    this.completed += 1; this.completedLog.push(this.now);
    this.docs = this.docs.filter(item => item !== doc);
  }
  private tally(id: string) {
    const list = this.completions.get(id) ?? []; list.push(this.now); this.completions.set(id, list);
    this.doneTotals.set(id, (this.doneTotals.get(id) ?? 0) + 1);
  }

  private watch() {
    for (const node of this.nodes.values()) {
      if (node.instant) continue;
      const here = this.docs.filter(doc => doc.node === node.id);
      const queued = here.filter(doc => doc.state === 'queued').length;
      const capacity = this.controls.get(node.id)?.capacity ?? node.capacity;
      const backlog = !this.controls.get(node.id)?.paused && queued >= Math.max(8, capacity * 4);
      if (backlog && !this.warned.has(node.id)) { this.warned.add(node.id); this.log('warn', `${this.where(node.id)} 대기 ${queued}건 — 처리 지연`, node.id); }
      if (!backlog && queued <= capacity) this.warned.delete(node.id);
    }
  }

  private log(level: SimEvent['level'], text: string, node?: string, doc?: string) {
    this.eventSerial += 1;
    this.events.push({ id: this.eventSerial, t: this.now, clock: this.clock(), level, text, node, doc });
    if (this.events.length > 300) this.events.splice(0, this.events.length - 300);
  }
  private clock() { const date = new Date(this.startedAt + this.now * 1000); return [date.getHours(), date.getMinutes(), date.getSeconds()].map(v => String(v).padStart(2, '0')).join(':'); }

  private emit() { this.snapshot = this.compose(); for (const listener of this.listeners) listener(); }

  private compose(): SimSnapshot {
    const cutoff = this.now - WINDOW;
    const prune = (list: number[]) => { while (list.length && list[0] < cutoff) list.shift(); return list; };
    const metrics: Record<string, NodeMetric> = {};
    const grouped = new Map<string, SimDoc[]>();
    for (const doc of this.docs) { const list = grouped.get(doc.node) ?? []; list.push(doc); grouped.set(doc.node, list); }
    for (const node of this.nodes.values()) {
      const here = grouped.get(node.id) ?? [];
      const control = this.controls.get(node.id);
      const queued = here.filter(doc => doc.state === 'queued').length, processing = here.filter(doc => doc.state === 'processing').length;
      const held = here.filter(doc => doc.state === 'held').length, failed = here.filter(doc => doc.state === 'failed').length;
      const capacity = node.kind === 'exception' || node.instant ? 0 : control?.capacity ?? node.capacity;
      const oldestWait = here.reduce((max, doc) => doc.state === 'processing' ? max : Math.max(max, this.now - doc.enteredAt), 0);
      const paused = !!control?.paused;
      const status: NodeStatus = paused ? 'paused' : failed ? 'error' : held || (capacity && queued >= Math.max(8, capacity * 4)) ? 'warn' : processing || queued ? 'busy' : 'idle';
      metrics[node.id] = { kind: node.kind, queued, processing, held, failed, capacity, throughput: prune(this.completions.get(node.id) ?? []).length, done: this.doneTotals.get(node.id) ?? 0, failedTotal: this.failedTotals.get(node.id) ?? 0, paused, bypass: !!control?.bypass, forced: control?.forced, oldestWait, status };
    }
    const traffic: Record<string, number> = {};
    for (const [key, list] of this.trafficLog) { const count = prune(list).length; if (count) traffic[key] = count; }
    const count = (state: DocState) => this.docs.filter(doc => doc.state === state).length;
    return {
      now: this.now, clock: this.clock(), running: this.running, speed: this.speed, rate: this.rate, metrics, traffic,
      docs: this.docs.map(doc => ({ ...doc })), events: this.events.slice(-200).reverse(),
      totals: { arrivals: this.arrivals, inFlight: this.docs.length, queued: count('queued'), processing: count('processing'), held: count('held'), failed: count('failed'), completed: this.completed, completedPerMin: prune(this.completedLog).length, arrivalsPerMin: prune(this.arrivalsLog).length },
      version: this.eventSerial * 100000 + Math.round(this.now * 10),
    };
  }
}

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const ORDER: NodeStatus[] = ['idle', 'busy', 'paused', 'warn', 'error'];
export const worst = (a: NodeStatus, b: NodeStatus) => ORDER.indexOf(a) >= ORDER.indexOf(b) ? a : b;

/** 하위 흐름 노드처럼 여러 실행 노드를 묶어 보여 줄 때 합산한다. */
export function aggregate(metrics: Record<string, NodeMetric>, flowId: string): NodeMetric {
  const result: NodeMetric = { kind: 'subflow', queued: 0, processing: 0, held: 0, failed: 0, capacity: 0, throughput: 0, done: 0, failedTotal: 0, paused: false, bypass: false, oldestWait: 0, status: 'idle' };
  for (const [id, metric] of Object.entries(metrics)) {
    if (!id.startsWith(`${flowId}::`)) continue;
    result.queued += metric.queued; result.processing += metric.processing; result.held += metric.held; result.failed += metric.failed;
    result.capacity += metric.capacity; result.failedTotal += metric.failedTotal; result.oldestWait = Math.max(result.oldestWait, metric.oldestWait);
    result.paused ||= metric.paused; result.status = worst(result.status, metric.status);
    if (metric.kind === 'end') { result.throughput += metric.throughput; result.done += metric.done; }
  }
  return result;
}
