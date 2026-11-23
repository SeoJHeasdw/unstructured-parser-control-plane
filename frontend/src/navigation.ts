import { useEffect, useState } from 'react';
import { BookOpen, Boxes, Database, FileSearch, FlaskConical, FolderOpen, GitBranch, GitCompareArrows, ListChecks, Network, Scissors, Settings2, Workflow } from 'lucide-react';

export const destinations = {
  live: { label: '문서함', group: '실제 문서', icon: FolderOpen, description: '파일 업로드와 파싱, 추출 결과 검수', alias: '실제 파일 처리' },
  parsers: { label: '파서 플로우', group: '문서 처리', icon: Workflow, description: '파일 형식별 파서와 추출 단계, 처리 문서를 확인합니다.', alias: '파서 파이프라인 파서 관리 라우팅 OCR' },
  analysis: { label: '분석 도구', group: '분석 도구', icon: Boxes, description: '문서 분석과 검색 품질 평가', alias: '' },
  chunking: { label: '청킹 비교', group: '문서 처리', icon: Scissors, description: '같은 원문을 여러 전략으로 나누고 청크를 비교합니다.', alias: '청킹 벤치 전략 관리' },
  embedding: { label: '임베딩 평가', group: '분석 도구', icon: ListChecks, description: '질문별 검색 정확도와 모델 입력 한도를 비교합니다.', alias: '' },
  relations: { label: '문서 계보', group: '분석 도구', icon: Network, description: '문서군의 판과 첨부 파일, 참조 근거를 확인합니다.', alias: '' },
  vectordb: { label: '벡터 DB', group: '분석 도구', icon: Database, description: '컬렉션과 파티션에 저장된 청크를 읽습니다.', alias: '' },
  search: { label: '검색 설계 참고', group: '분석 도구', icon: BookOpen, description: '검색 단계별 역할과 API 계약 초안을 살펴봅니다.', alias: '검색 파이프라인' },
  models: { label: '모델 연결', group: '설정', icon: Settings2, description: '게이트웨이 설정과 모델 응답을 확인합니다.', alias: '설정' },
  overview: { label: '처리 현황', group: '예시', icon: FlaskConical, description: '예시 문서에서 확인이 필요한 작업을 찾습니다.', alias: '운영 대시보드 예시 둘러보기' },
  documents: { label: '예시 문서', group: '예시', icon: FileSearch, description: '준비된 예시 문서의 처리 이력과 참조를 읽습니다.', alias: '문서 탐색' },
  pipeline: { label: '모의 플로우', group: '문서 처리', icon: GitBranch, description: '예시 처리 흐름을 확인하고 경로를 편집합니다.', alias: '처리 파이프라인 처리 시뮬레이터 파서 플로우 설계' },
  compare: { label: '예시 검수', group: '예시', icon: GitCompareArrows, description: '예시 원문과 추출 결과, 두 실행의 차이를 확인합니다.', alias: '파싱 비교' },
} as const;
export type Page = keyof typeof destinations;
export type DetailTab = 'result' | 'history' | 'structure';
export type ReviewMode = 'source' | 'runs';
export type WorkspaceRoute = { page: Page; doc?: string; tab?: DetailTab; review?: ReviewMode; familyDoc?: string; format?: string; mode?: 'design'; sample?: string };
export const toolsList: Page[] = ['embedding', 'relations', 'vectordb', 'search'];
export const examples: Page[] = ['overview', 'documents', 'compare'];

function readRoute(): WorkspaceRoute {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('view') ?? '';
  const page = Object.hasOwn(destinations, requested) ? requested as Page : 'live';
  const doc = params.get('doc') || undefined;
  const tab = params.get('tab'), review = params.get('review');
  if (page === 'chunking') return { page, doc, sample: doc ? undefined : params.get('sample') || undefined };
  if (page === 'parsers' || page === 'pipeline') return {
    page, format: params.has('format') ? params.get('format')!.toUpperCase() : undefined,
    mode: page === 'pipeline' && params.get('mode') === 'design' ? 'design' : undefined,
  };
  if (page === 'relations') return { page, familyDoc: doc };
  if (page === 'compare') return { page, doc };
  if (page !== 'live' || !doc) return { page };
  return { page, doc, tab: tab === 'history' || tab === 'structure' ? tab : 'result', review: review === 'source' || review === 'runs' ? review : undefined };
}

export function workspaceHref(route: WorkspaceRoute) {
  const url = new URL(window.location.href);
  for (const key of ['view', 'doc', 'tab', 'review', 'format', 'mode', 'sample']) url.searchParams.delete(key);
  url.searchParams.set('view', route.page);
  if (route.doc || route.familyDoc) url.searchParams.set('doc', (route.doc || route.familyDoc)!);
  if (route.format !== undefined) url.searchParams.set('format', route.format);
  if (route.mode) url.searchParams.set('mode', route.mode);
  if (route.sample) url.searchParams.set('sample', route.sample);
  if (route.tab && route.tab !== 'result') url.searchParams.set('tab', route.tab);
  if (route.review) url.searchParams.set('review', route.review);
  return url.pathname + url.search;
}

export function useWorkspaceRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const restore = () => setRoute(readRoute());
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  function go(next: WorkspaceRoute) {
    const href = workspaceHref(next);
    if (location.pathname + location.search !== href) history.pushState({...history.state}, '', href);
    setRoute(next);
  }
  return { route, go };
}
