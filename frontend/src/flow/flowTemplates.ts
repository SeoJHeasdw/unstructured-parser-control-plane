import { autoLayout, NODE_SIZE } from './flowLayout';
import type { FlowDirection, FlowDoc, FlowEdge, FlowEdgeData, FlowLibrary, FlowNode, FlowNodeData, NodeKind } from './flowTypes';

export const OVERVIEW_ID = 'overview';
const STORAGE_KEY = 'document-ops:flows:v2';

let seq = 0;
export const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}${(seq++).toString(36)}`;

export function makeNode(id: string, kind: NodeKind, label: string, extra: Partial<FlowNodeData> = {}, position = { x: 0, y: 0 }): FlowNode {
  const size = NODE_SIZE[kind];
  return { id, type: 'flow', position, width: size.w, height: size.h, data: { ...defaultsFor(kind), kind, label, ...extra } };
}
export function makeEdge(source: string, target: string, extra: FlowEdgeData = {}, id = `${source}->${target}`): FlowEdge {
  return { id, source, target, type: 'flow', data: { kind: 'default', ...extra } };
}
export function defaultsFor(kind: NodeKind): Partial<FlowNodeData> {
  if (kind === 'task') return { icon: 'custom', capacity: 3, duration: 3, failRate: 0.02, retries: 1 };
  if (kind === 'review') return { capacity: 4, duration: 1.5, failRate: 0, retries: 0, holdRate: 0.2, assignee: '문서 품질 담당', sla: 30 };
  if (kind === 'store') return { icon: 'index', capacity: 8, duration: 0.8, failRate: 0.005, retries: 2 };
  if (kind === 'exception') return { capacity: 0, duration: 0 };
  if (kind === 'subflow') return {};
  return {};
}

function flow(id: string, title: string, summary: string, nodes: FlowNode[], edges: FlowEdge[], direction: FlowDirection = 'TB'): FlowDoc {
  return { id, title, summary, direction, nodes: autoLayout(nodes, edges, direction), edges, builtIn: true };
}

/** 2026-11-10 사용자가 알려준 초기 19종의 기본 경로. 전체 형식을 제한하지 않는다. */
const ROUTES: { flow: string; label: string; formats: string[] }[] = [
  { flow: 'pdf', label: 'PDF', formats: ['PDF'] },
  { flow: 'office', label: 'DOCX · PPTX · DOC …', formats: ['DOCX', 'DOCM', 'PPTX', 'DOC', 'PPT'] },
  { flow: 'sheet', label: 'XLSX · XLSM · XLS', formats: ['XLSX', 'XLSM', 'XLS'] },
  { flow: 'mail', label: 'EML · MSG', formats: ['EML', 'MSG'] },
  { flow: 'web', label: 'TXT · CSV · HTM …', formats: ['TXT', 'LOG', 'CSV', 'HTM', 'MHT'] },
  { flow: 'image', label: 'PNG · JPG', formats: ['PNG', 'JPG'] },
  { flow: 'zip', label: 'ZIP', formats: ['ZIP'] },
];

function overview(): FlowDoc {
  const nodes: FlowNode[] = [
    makeNode('src', 'start', '문서 수집', { engine: '원천 문서함 · 수동 등록', description: '원천 문서함과 수동 등록 경로에서 문서를 받아 수집 정보를 기록합니다.', output: '원본 파일, 원천·수집 시점' }),
    makeNode('detect', 'task', '형식 판별', { icon: 'detect', engine: '확장자 + 파일 시그니처', description: '확장자와 실제 파일 시그니처를 비교해 처리 경로를 고릅니다.', input: '원본 파일', output: '형식 판별 결과', capacity: 8, duration: 0.6, failRate: 0.004, retries: 1 }),
    makeNode('router', 'gateway', '형식별 라우팅', { description: '판별된 형식에 따라 형식별 하위 흐름으로 보냅니다. 조건에 맞는 경로가 없으면 기본 경로로 보냅니다.' }),
    ...ROUTES.map(route => makeNode(`sf-${route.flow}`, 'subflow', TITLES[route.flow], { subflow: route.flow, description: SUMMARIES[route.flow] })),
    makeNode('unrouted', 'exception', '형식 확인 대기열', { description: '경로가 정해지지 않은 형식입니다. 담당자가 처리 경로를 지정하거나 제외합니다.', assignee: '데이터 운영 담당' }),
    makeNode('review', 'review', '품질 검토', { engine: '신뢰도 기준 0.85', description: '표·숫자·원문 위치 검사 결과가 기준에 못 미치면 사람 검토로 보류합니다.', input: '구조화 결과, 품질 점수', output: '승인 또는 반려', holdRate: 0.16, capacity: 6, duration: 1 }),
    makeNode('refs', 'task', '문서 참조 연결', { icon: 'relation', engine: '문서번호 패턴 + 후보 검증', description: '문서번호·파일명·링크를 찾아 참조 대상 후보와 원문 위치를 기록합니다.', input: '파싱 결과와 위치', output: '참조 후보, 연결 상태', capacity: 6, duration: 1.4, failRate: 0.01 }),
    makeNode('index', 'store', '검색 인덱스 적재', { engine: '청크 · 출처 · 버전', description: '문서 구조와 출처를 유지한 검색 단위를 적재합니다.', input: '승인된 구조화 결과', output: '검색 단위' }),
    makeNode('done', 'end', '처리 완료'),
    makeNode('rejected', 'exception', '반려 문서', { description: '품질 검토에서 반려된 문서입니다. 재처리하거나 제외합니다.', assignee: '문서 품질 담당' }),
  ];
  const edges: FlowEdge[] = [
    makeEdge('src', 'detect'), makeEdge('detect', 'router'),
    ...ROUTES.map(route => makeEdge('router', `sf-${route.flow}`, { label: route.label, formats: route.formats })),
    makeEdge('router', 'unrouted', { label: '미지정 형식', isDefault: true, kind: 'exception' }),
    ...ROUTES.map(route => makeEdge(`sf-${route.flow}`, 'review')),
    makeEdge('review', 'refs'), makeEdge('review', 'rejected', { label: '반려', kind: 'exception' }),
    makeEdge('refs', 'index'), makeEdge('index', 'done'),
  ];
  return flow(OVERVIEW_ID, '전체 처리 흐름', '수집부터 형식별 처리, 품질 검토, 인덱스 적재까지', nodes, edges);
}

const TITLES: Record<string, string> = { pdf: 'PDF 문서', office: 'Office 문서', sheet: '스프레드시트', mail: '메일 · 첨부', web: '텍스트 · 웹', image: '이미지 OCR', zip: '압축 파일' };
const SUMMARIES: Record<string, string> = {
  pdf: '텍스트 계층을 확인하고 스캔 페이지는 OCR을 거쳐 레이아웃을 파싱합니다.',
  office: '최신 Office는 바로 파싱하고, 레거시 형식은 변환 후 파싱합니다.',
  sheet: '시트·셀 구조와 수식, 셀 안의 문서 참조를 추출합니다.',
  mail: '메일 본문과 첨부를 분리하고 첨부는 형식 판별로 다시 보냅니다.',
  web: '인코딩을 확인하고 구조에 따라 텍스트·표·HTML을 정리합니다.',
  image: '이미지 품질을 확인한 뒤 OCR로 문자와 영역을 추출합니다.',
  zip: '암호·손상 여부를 확인하고 내부 파일을 분리합니다.',
};

function pdf(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', 'PDF 수신'),
    makeNode('layer', 'task', '텍스트 계층 확인', { icon: 'detect', engine: '페이지별 텍스트 비율', description: '페이지마다 추출 가능한 텍스트가 있는지 확인합니다.', input: 'PDF 페이지', output: '텍스트/스캔 판정', capacity: 6, duration: 0.8, failRate: 0.004 }),
    makeNode('scan', 'gateway', '스캔 페이지 포함?'),
    makeNode('ocr', 'task', 'OCR 인식', { icon: 'ocr', engine: 'OCR 모델 후보', description: '스캔·이미지 페이지에서 문자와 영역을 인식합니다.', input: '스캔 페이지 이미지', output: '인식 텍스트, 영역 좌표', capacity: 2, duration: 6, failRate: 0.1, retries: 1 }),
    makeNode('layout', 'task', '레이아웃 파싱', { icon: 'parse', engine: 'Docling', description: '본문, 읽기 순서, 표와 페이지 위치를 추출합니다.', input: 'PDF, OCR 텍스트', output: '본문, 표, 페이지 위치', capacity: 4, duration: 3.2, failRate: 0.03, retries: 1 }),
    makeNode('table', 'task', '표 · 숫자 검증', { icon: 'quality', engine: '셀 수 · 단위 검사', description: '표의 행·열 수와 숫자·단위가 원문과 맞는지 검사합니다.', input: '추출된 표', output: '검증 결과, 경고', capacity: 4, duration: 1.2, failRate: 0.01 }),
    makeNode('ocr-review', 'exception', 'OCR 재검토 대기', { description: '자동 재시도 후에도 인식에 실패한 문서입니다.', assignee: '문서 품질 담당' }),
    makeNode('out', 'end', 'PDF 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'layer'), makeEdge('layer', 'scan'),
    makeEdge('scan', 'layout', { label: '텍스트 PDF', weight: 70, isDefault: true }),
    makeEdge('scan', 'ocr', { label: '스캔 · 혼합', weight: 30 }),
    makeEdge('ocr', 'layout'), makeEdge('ocr', 'ocr-review', { label: '인식 실패', kind: 'exception' }),
    makeEdge('layout', 'table'), makeEdge('table', 'out'),
  ];
  return flow('pdf', TITLES.pdf, SUMMARIES.pdf, nodes, edges);
}

function office(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', 'Office 수신'),
    makeNode('legacy', 'gateway', '레거시 형식?'),
    makeNode('convert', 'task', '레거시 변환', { icon: 'convert', engine: '문서 변환 도구 후보', description: '구형 형식을 최신 형식으로 변환합니다. 변환 손실은 경고로 남깁니다.', input: 'DOC · PPT', output: '변환된 문서', capacity: 2, duration: 4, failRate: 0.06 }),
    makeNode('parse', 'task', '구조 파싱', { icon: 'parse', engine: 'Docling', description: '본문, 표, 슬라이드와 원문 위치를 추출합니다.', input: 'DOCX · DOCM · PPTX', output: '본문, 표, 슬라이드', capacity: 4, duration: 2.6, failRate: 0.02 }),
    makeNode('convert-fail', 'exception', '변환 실패 검토', { description: '변환 도구가 처리하지 못한 레거시 문서입니다.' }),
    makeNode('out', 'end', 'Office 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'legacy'),
    makeEdge('legacy', 'parse', { label: 'DOCX · DOCM · PPTX', formats: ['DOCX', 'DOCM', 'PPTX'], isDefault: true }),
    makeEdge('legacy', 'convert', { label: 'DOC · PPT', formats: ['DOC', 'PPT'] }),
    makeEdge('convert', 'parse'), makeEdge('convert', 'convert-fail', { label: '변환 실패', kind: 'exception' }),
    makeEdge('parse', 'out'),
  ];
  return flow('office', TITLES.office, SUMMARIES.office, nodes, edges);
}

function sheet(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', '스프레드시트 수신'),
    makeNode('kind', 'gateway', 'XLS 여부'),
    makeNode('convert', 'task', 'XLS 변환', { icon: 'convert', engine: '문서 변환 도구 후보', capacity: 2, duration: 2.5, failRate: 0.04, description: '구형 XLS를 변환합니다.' }),
    makeNode('workbook', 'task', '워크북 구조 분석', { icon: 'sheet', engine: '시트 · 셀 · 병합', description: '시트 구성과 셀 주소, 병합 영역을 읽습니다.', input: '워크북', output: '시트 목록, 셀 주소', capacity: 4, duration: 1.6, failRate: 0.01 }),
    makeNode('cells', 'task', '셀 값 · 수식 추출', { icon: 'sheet', engine: '값 · 수식 보존', description: '셀 값과 수식을 시트·셀 위치와 함께 추출합니다.', input: '시트 구조', output: '값, 수식, 셀 위치', capacity: 4, duration: 2.2, failRate: 0.02 }),
    makeNode('links', 'task', '셀 참조 · 링크 추출', { icon: 'relation', engine: '외부 참조 · 문서번호', description: '하이퍼링크, 외부 참조 수식, 셀 안의 문서번호를 찾습니다.', input: '셀 값, 수식', output: '참조 후보, 셀 위치', capacity: 4, duration: 1.3, failRate: 0.01 }),
    makeNode('out', 'end', '스프레드시트 완료'),
  ];
  const edges = [
    makeEdge('in', 'kind'),
    makeEdge('kind', 'workbook', { label: 'XLSX · XLSM', formats: ['XLSX', 'XLSM'], isDefault: true }),
    makeEdge('kind', 'convert', { label: 'XLS', formats: ['XLS'] }),
    makeEdge('convert', 'workbook'), makeEdge('workbook', 'cells'), makeEdge('cells', 'links'), makeEdge('links', 'out'),
  ];
  return flow('sheet', TITLES.sheet, SUMMARIES.sheet, nodes, edges);
}

function mail(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', '메일 수신'),
    makeNode('split', 'task', '본문 · 첨부 분리', { icon: 'mail', engine: 'EML · MSG 파서', description: '메일 본문과 첨부를 분리하고 부모-자식 관계를 기록합니다.', capacity: 3, duration: 1.8, failRate: 0.03 }),
    makeNode('has', 'gateway', '첨부 있음?'),
    makeNode('body', 'task', '본문 텍스트 추출', { icon: 'text', engine: '본문 · 헤더', capacity: 4, duration: 0.8, failRate: 0.005 }),
    makeNode('attach', 'task', '첨부 재투입', { icon: 'split', engine: '첨부별 형식 판별로 전달', description: '첨부 파일을 개별 문서로 등록해 형식 판별로 다시 보냅니다.', capacity: 3, duration: 1.2, failRate: 0.01 }),
    makeNode('out', 'end', '메일 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'split'), makeEdge('split', 'has'),
    makeEdge('has', 'body', { label: '본문만', weight: 40, isDefault: true }),
    makeEdge('has', 'attach', { label: '첨부 포함', weight: 60 }),
    makeEdge('body', 'out'), makeEdge('attach', 'out'),
  ];
  return flow('mail', TITLES.mail, SUMMARIES.mail, nodes, edges);
}

function web(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', '텍스트 · 웹 수신'),
    makeNode('enc', 'task', '인코딩 판별', { icon: 'text', engine: 'UTF-8 · CP949', description: '문자 인코딩을 확인합니다.', capacity: 6, duration: 0.6, failRate: 0.01 }),
    makeNode('kind', 'gateway', '구조 구분'),
    makeNode('plain', 'task', '본문 추출', { icon: 'text', engine: '텍스트 · 로그', capacity: 6, duration: 0.8, failRate: 0.005 }),
    makeNode('csv', 'task', '표 변환', { icon: 'sheet', engine: 'CSV → Markdown 표', capacity: 4, duration: 1, failRate: 0.01 }),
    makeNode('html', 'task', 'HTML 정제', { icon: 'parse', engine: '태그 제거 · 구조 보존', capacity: 4, duration: 1.2, failRate: 0.01 }),
    makeNode('out', 'end', '텍스트 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'enc'), makeEdge('enc', 'kind'),
    makeEdge('kind', 'plain', { label: 'TXT · LOG', formats: ['TXT', 'LOG'], isDefault: true }),
    makeEdge('kind', 'csv', { label: 'CSV', formats: ['CSV'] }),
    makeEdge('kind', 'html', { label: 'HTM · MHT', formats: ['HTM', 'MHT'] }),
    makeEdge('plain', 'out'), makeEdge('csv', 'out'), makeEdge('html', 'out'),
  ];
  return flow('web', TITLES.web, SUMMARIES.web, nodes, edges);
}

function image(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', '이미지 수신'),
    makeNode('quality', 'task', '이미지 품질 확인', { icon: 'detect', engine: '해상도 · 기울기', capacity: 4, duration: 0.9, failRate: 0.01 }),
    makeNode('ocr', 'task', 'OCR 인식', { icon: 'ocr', engine: 'OCR 모델 후보', description: '이미지에서 문자와 영역을 인식합니다.', capacity: 2, duration: 5.5, failRate: 0.12, retries: 1 }),
    makeNode('verify', 'task', '숫자 · 단위 검증', { icon: 'quality', engine: '패턴 · 단위 사전', capacity: 4, duration: 1.2, failRate: 0.01 }),
    makeNode('ocr-review', 'exception', 'OCR 재검토 대기', { description: '인식 신뢰도가 기준에 못 미친 이미지입니다.' }),
    makeNode('out', 'end', '이미지 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'quality'), makeEdge('quality', 'ocr'), makeEdge('ocr', 'verify'),
    makeEdge('ocr', 'ocr-review', { label: '인식 실패', kind: 'exception' }), makeEdge('verify', 'out'),
  ];
  return flow('image', TITLES.image, SUMMARIES.image, nodes, edges);
}

function zip(): FlowDoc {
  const nodes = [
    makeNode('in', 'start', '압축 파일 수신'),
    makeNode('check', 'task', '압축 상태 확인', { icon: 'detect', engine: '암호 · 손상 검사', description: '암호화·손상 여부를 확인합니다.', capacity: 4, duration: 1, failRate: 0.14, retries: 0 }),
    makeNode('extract', 'task', '내부 파일 분리', { icon: 'split', engine: '상위-하위 관계 기록', description: '내부 항목을 개별 문서로 분리하고 상위 압축 파일과의 관계를 기록합니다.', capacity: 2, duration: 3, failRate: 0.02 }),
    makeNode('blocked', 'exception', '압축 예외 검토', { description: '암호가 걸렸거나 손상된 압축 파일입니다.' }),
    makeNode('out', 'end', '압축 처리 완료'),
  ];
  const edges = [
    makeEdge('in', 'check'), makeEdge('check', 'extract'),
    makeEdge('check', 'blocked', { label: '암호 · 손상', kind: 'exception' }), makeEdge('extract', 'out'),
  ];
  return flow('zip', TITLES.zip, SUMMARIES.zip, nodes, edges);
}

const BUILDERS: Record<string, () => FlowDoc> = { [OVERVIEW_ID]: overview, pdf, office, sheet, mail, web, image, zip };
export const BUILT_IN_ORDER = [OVERVIEW_ID, 'pdf', 'office', 'sheet', 'mail', 'web', 'image', 'zip'];
export const templateFor = (id: string) => BUILDERS[id]?.() ?? null;

export function defaultLibrary(): FlowLibrary {
  const flows: Record<string, FlowDoc> = {};
  for (const id of BUILT_IN_ORDER) flows[id] = BUILDERS[id]();
  return { version: 2, order: [...BUILT_IN_ORDER], flows };
}

/** 새 형식을 위한 기본 흐름. 실제 파서를 등록하지 않는다. */
export function customFlow(ext: string): FlowDoc {
  const lower = ext.toLowerCase();
  const nodes = [
    makeNode('in', 'start', `.${lower} 수신`),
    makeNode('verify', 'task', '실제 형식 확인', { icon: 'detect', engine: '시그니처 확인', capacity: 3, duration: 1, failRate: 0.02 }),
    makeNode('ok', 'gateway', '처리 가능?'),
    makeNode('parse', 'task', '파서 지정 필요', { icon: 'custom', engine: '미지정', description: '이 형식에 맞는 파서를 정하면 이 단계에 연결합니다.', capacity: 2, duration: 3, failRate: 0.05 }),
    makeNode('manual', 'exception', '수동 처리 대기', { description: '자동 처리할 수 없는 파일입니다.' }),
    makeNode('out', 'end', `.${lower} 처리 완료`),
  ];
  const edges = [
    makeEdge('in', 'verify'), makeEdge('verify', 'ok'),
    makeEdge('ok', 'parse', { label: '처리 가능', weight: 80, isDefault: true }),
    makeEdge('ok', 'manual', { label: '처리 불가', weight: 20, kind: 'exception' }),
    makeEdge('parse', 'out'),
  ];
  const doc = flow(`custom-${lower}`, `.${lower} 처리`, '새 형식의 기본 흐름 · 파서 미지정', nodes, edges);
  return { ...doc, builtIn: false };
}

/** 전체 흐름의 라우팅 연결에서 확장자 → 흐름 매핑을 계산한다. 라우팅 조건이 유일한 원본이다. */
export function formatRoutes(library: FlowLibrary): Record<string, string> {
  const root = library.flows[OVERVIEW_ID];
  const result: Record<string, string> = {};
  if (!root) return result;
  const byId = new Map(root.nodes.map(node => [node.id, node]));
  for (const edge of root.edges) {
    const source = byId.get(edge.source), target = byId.get(edge.target);
    if (source?.data.kind !== 'gateway' || target?.data.kind !== 'subflow' || !target.data.subflow) continue;
    for (const ext of edge.data?.formats ?? []) if (!result[ext]) result[ext] = target.data.subflow;
  }
  return result;
}
export function formatsOfFlow(library: FlowLibrary, flowId: string) {
  return Object.entries(formatRoutes(library)).filter(([, id]) => id === flowId).map(([ext]) => ext);
}

/** 새 형식 흐름을 만들고 전체 흐름의 라우팅에 연결한다. */
export function addFormatRoute(library: FlowLibrary, ext: string): { library: FlowLibrary; flowId: string } {
  const existing = formatRoutes(library)[ext];
  if (existing) return { library, flowId: existing };
  const doc = customFlow(ext);
  const root = library.flows[OVERVIEW_ID];
  if (!root) return { library: { ...library, flows: { ...library.flows, [doc.id]: doc }, order: [...library.order, doc.id] }, flowId: doc.id };
  const router = root.nodes.find(node => node.data.kind === 'gateway' && root.edges.some(edge => edge.source === node.id && edge.data?.formats?.length));
  const subflows = root.nodes.filter(node => node.data.kind === 'subflow');
  const anchor = subflows.reduce<FlowNode | null>((best, node) => !best || (root.direction === 'TB' ? node.position.x > best.position.x : node.position.y > best.position.y) ? node : best, null);
  const nodeId = uid('sf');
  const position = anchor ? (root.direction === 'TB' ? { x: anchor.position.x + (anchor.width ?? 212) + 32, y: anchor.position.y } : { x: anchor.position.x, y: anchor.position.y + (anchor.height ?? 98) + 32 }) : { x: 40, y: 40 };
  const node = makeNode(nodeId, 'subflow', doc.title, { subflow: doc.id, description: doc.summary }, position);
  const next = root.edges.find(edge => edge.source === anchor?.id);
  const edges = [...root.edges];
  if (router) edges.push(makeEdge(router.id, nodeId, { label: ext, formats: [ext] }, uid('e')));
  if (next) edges.push(makeEdge(nodeId, next.target, {}, uid('e')));
  const updatedRoot = { ...root, nodes: [...root.nodes, node], edges };
  return { library: { ...library, order: [...library.order, doc.id], flows: { ...library.flows, [OVERVIEW_ID]: updatedRoot, [doc.id]: doc } }, flowId: doc.id };
}

export function loadLibrary(): FlowLibrary {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = parseLibrary(JSON.parse(raw));
      if (parsed) return parsed;
    }
  } catch { /* 저장된 값이 없거나 읽을 수 없으면 기본 흐름을 쓴다. */ }
  return defaultLibrary();
}
export function saveLibrary(library: FlowLibrary) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(stripTransient(library))); } catch { /* 저장소가 없어도 화면은 동작한다. */ }
}
export function stripTransient(library: FlowLibrary): FlowLibrary {
  const flows: Record<string, FlowDoc> = {};
  for (const [id, doc] of Object.entries(library.flows)) flows[id] = { ...doc, nodes: doc.nodes.map(({ selected: _s, dragging: _d, measured: _m, ...node }) => node as FlowNode), edges: doc.edges.map(({ selected: _s, ...edge }) => edge as FlowEdge) };
  return { ...library, flows };
}

const KINDS = new Set<NodeKind>(['start', 'task', 'gateway', 'review', 'store', 'subflow', 'exception', 'end', 'note']);
/** 저장값·가져온 JSON을 검증한다. 형식이 맞지 않으면 null. */
export function parseLibrary(value: unknown): FlowLibrary | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<FlowLibrary>;
  if (candidate.version !== 2 || !candidate.flows || typeof candidate.flows !== 'object' || !Array.isArray(candidate.order)) return null;
  const flows: Record<string, FlowDoc> = {};
  for (const [id, raw] of Object.entries(candidate.flows)) {
    const doc = raw as Partial<FlowDoc>;
    if (!doc || typeof doc.title !== 'string' || !Array.isArray(doc.nodes) || !Array.isArray(doc.edges)) continue;
    const nodes = doc.nodes.filter((node): node is FlowNode => !!node && typeof node.id === 'string' && !!node.data && KINDS.has(node.data.kind) && typeof node.data.label === 'string' && !!node.position && Number.isFinite(node.position.x) && Number.isFinite(node.position.y)).map(node => ({ ...node, type: 'flow' as const }));
    const ids = new Set(nodes.map(node => node.id));
    const edges = doc.edges.filter((edge): edge is FlowEdge => !!edge && typeof edge.id === 'string' && ids.has(edge.source) && ids.has(edge.target)).map(edge => ({ ...edge, type: 'flow' as const, data: edge.data ?? { kind: 'default' } }));
    flows[id] = { id, title: doc.title, summary: typeof doc.summary === 'string' ? doc.summary : '', direction: doc.direction === 'LR' ? 'LR' : 'TB', nodes, edges, builtIn: !!doc.builtIn };
  }
  const order = candidate.order.filter((id): id is string => typeof id === 'string' && !!flows[id]);
  for (const id of Object.keys(flows)) if (!order.includes(id)) order.push(id);
  if (!order.length) return null;
  return { version: 2, order, flows };
}
