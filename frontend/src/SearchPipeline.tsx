import { ArrowRight, Braces, CircleHelp, GitMerge, Layers3, MessagesSquare, Ruler, Search } from 'lucide-react';
import type { Page } from './types';
import './searchPipeline.css';

/** 검색 엔드포인트 구상도. 수치나 실행 상태가 아니라, 범위와 단계별 결정 상태를 한 장으로 보여 준다.
 *  기본 화면은 흐름만 보이고, 각 단계 설명과 참고 자료는 펼쳐서 읽는다. */
type Status = 'fixed' | 'candidate' | 'open' | 'agent';
type Lane = 'agent' | 'query' | 'index';
type Stage = {
  id: string; lane: Lane; title: string; short: string; status: Status; detail: string;
  options?: string[]; measure?: string; questions?: string[]; link?: { page: Page; label: string };
};

const STATUS: Record<Status, string> = { fixed: '확정', candidate: '후보', open: '미정', agent: '에이전트 측' };

const STAGES: Stage[] = [
  { id: 'a1', lane: 'agent', title: '사용자 질문', short: '자연어 질문', status: 'agent', detail: '사용자 질문을 받아 대화 맥락과 함께 해석하는 일은 에이전트가 맡습니다.' },
  { id: 'a2', lane: 'agent', title: '질의 재작성 · 분해', short: '다시 쓰기, N개 하위 질문', status: 'agent', detail: '질문을 다시 쓰거나 여러 하위 질문으로 나누는 방식은 에이전트 개발 측이 정합니다. 검색은 받은 질의를 그대로 처리합니다.', questions: ['하위 질문을 한 번에 묶어 보낼지, 질문마다 따로 호출할지'] },
  { id: 'a3', lane: 'agent', title: 'search 호출', short: '질의 1개 또는 묶음', status: 'agent', detail: '질의와 사용자 식별 정보, 필요한 필터를 담아 검색 엔드포인트를 호출합니다. 호출 횟수와 순서는 에이전트가 정합니다.' },
  { id: 'a4', lane: 'agent', title: '근거 판단 · 재검색', short: '충분한가, 더 찾을까', status: 'agent', detail: '돌려받은 근거가 충분한지 판단하고 다시 검색할지 정하는 일은 에이전트가 맡습니다. 검색은 판단에 쓸 단계별 점수와 원문 위치를 함께 돌려줍니다.', questions: ['검색 쪽 점수를 판단 기준으로 쓸지, 에이전트 자체 판단만 쓸지', '전체 호출 횟수와 시간 상한'] },
  { id: 'a5', lane: 'agent', title: '답변 생성', short: '인용 포함', status: 'agent', detail: '답변 작성과 인용 표시는 에이전트가 맡습니다. 검색은 인용에 필요한 문서·버전·원문 위치를 제공합니다.' },

  { id: 'q1', lane: 'query', title: '요청 확인', short: '질의, top_k, 필터', status: 'open', detail: '질의 문자열, 돌려줄 개수, 필터, 사용자 식별 정보를 확인합니다. 하위 질문 여러 개를 한 번에 받는 묶음 요청도 가안으로 둡니다.', questions: ['사용자 권한 정보를 어떤 형식으로 받을지'] },
  { id: 'q2', lane: 'query', title: '권한 · 범위 필터', short: '보안등급, 파티션, 최신본', status: 'open', detail: '사용자 권한에 맞지 않는 청크를 미리 걸러 냅니다. 원천·문서 유형·파티션으로 범위를 좁히고, 기본값으로 최신 버전 문서만 대상으로 삼습니다.', options: ['청크에 상속된 보안등급으로 필터', '문서 계보의 최신 판단으로 구버전 제외', '파티션 · 원천 · 문서 유형 지정'], link: { page: 'relations', label: '문서 계보에서 최신 판단 보기' } },
  { id: 'q3a', lane: 'query', title: '의미 검색', short: 'dense 벡터 ANN', status: 'candidate', detail: '질의를 문서와 같은 임베딩 모델로 벡터화해 가까운 청크를 찾습니다. 질의와 문서는 반드시 같은 모델·버전을 씁니다.', options: ['Harrier-OSS-v1 0.6B: 1024차원 · 최대 32K 토큰 · 질의 지시문 필요', '그 외 후보는 임베딩 평가에서 비교'], measure: '후보 재현율 Recall@50', link: { page: 'embedding', label: '임베딩 평가 열기' } },
  { id: 'q3b', lane: 'query', title: '키워드 검색', short: 'BM25 · sparse', status: 'candidate', detail: '문서번호·제품코드·수치처럼 정확히 일치해야 하는 표현을 찾습니다. 의미 검색이 놓치는 결과를 채웁니다.', options: ['Milvus 전문 검색(BM25 함수)', '학습형 희소 벡터'], measure: '후보 재현율 Recall@50', questions: ['사용할 Milvus 버전의 한국어 형태소 분석기 지원 여부'] },
  { id: 'q4', lane: 'query', title: '결과 융합', short: 'RRF / 가중 합', status: 'candidate', detail: '두 검색 결과를 한 순위로 합칩니다. 점수 척도가 달라 순위 기반 RRF를 기본으로 두고 가중 합과 비교합니다.', options: ['RRF(순위 기반)', '가중 합(점수 정규화 필요)'], measure: '융합 후 Recall@50' },
  { id: 'q5', lane: 'query', title: '리랭커', short: '상위 N개 다시 채점', status: 'candidate', detail: '융합된 상위 N개를 질의와 함께 다시 읽어 순서를 매깁니다. 정확도를 가장 크게 올리는 단계이면서 지연 시간이 가장 큰 단계입니다. 앞 단계가 가져오지 못한 청크는 리랭커가 살릴 수 없습니다.', options: ['다국어 리랭커 후보를 한국어 질문으로 실측', '재채점 개수 N과 지연 시간의 균형'], measure: 'MRR@10 · nDCG@10 · 단계 지연 시간' },
  { id: 'q6', lane: 'query', title: '후처리', short: '중복·문서당 개수·이웃 청크', status: 'open', detail: '같은 문서의 청크가 결과를 독차지하지 않게 문서당 개수를 제한하고, 겹치는 청크를 정리하고, 필요하면 앞뒤 청크를 붙여 문맥을 보강합니다.', options: ['문서당 최대 청크 수', '앞뒤 청크 붙이기', '점수 하한'] },
  { id: 'q7', lane: 'query', title: '응답', short: '근거 · 위치 · 점수', status: 'open', detail: '청크 원문, 문서 ID·버전·최신 여부, 원문 위치(페이지·시트·셀·문자 범위), 단계별 점수, 단계별 처리 시간, 모델·인덱스 버전을 돌려줍니다.' },

  { id: 'i1', lane: 'index', title: '원천 수집', short: '원천·확장자 계속 늘어남', status: 'open', detail: '원천과 파일 형식은 계속 추가될 수 있습니다. 압축 파일과 메일 첨부 안의 문서도 대상입니다.', link: { page: 'live', label: '실제 파일 처리 열기' } },
  { id: 'i2', lane: 'index', title: 'DRM 해제', short: '해제 경로 등록', status: 'open', detail: 'DRM이 걸린 문서는 해제한 뒤 처리합니다. 해제 대상 선별과 이력 관리 방식은 협의가 필요합니다.' },
  { id: 'i3', lane: 'index', title: '파싱 · OCR', short: '본문·표·원문 위치', status: 'candidate', detail: '본문과 표, 숫자·단위를 추출하고 원문 위치를 보존합니다. 스캔 페이지는 OCR이 필요합니다.', link: { page: 'compare', label: '예시 검수 열기' } },
  { id: 'i4', lane: 'index', title: '문서 계보', short: '최신본·포함·참조', status: 'candidate', detail: '버전 중 최신본을 판단하고, 문서 속 문서와 참조 관계를 정리합니다. 검색 시 최신본 필터와 구버전 참조 경고에 씁니다.', link: { page: 'relations', label: '문서 계보 열기' } },
  { id: 'i5', lane: 'index', title: '청킹', short: '구조 기준 분할', status: 'candidate', detail: '제목·표 같은 문서 구조를 살려 나눕니다. 청크 크기는 임베딩 모델의 최대 입력 토큰 안에서 정합니다.', measure: '청크 길이 분포 · 누락률 · 표 분할 수', link: { page: 'chunking', label: '청킹 비교 열기' } },
  { id: 'i6', lane: 'index', title: '임베딩', short: 'dense + sparse', status: 'candidate', detail: '청크마다 의미 벡터를 만들고, 키워드 검색용 희소 표현을 함께 준비합니다.', measure: '처리량 · 재처리 소요 시간', link: { page: 'embedding', label: '임베딩 평가 열기' } },
  { id: 'i7', lane: 'index', title: 'Milvus 적재', short: '컬렉션 · 파티션', status: 'fixed', detail: '벡터와 함께 문서 ID·버전·보안등급·원문 위치를 스칼라 필드로 저장합니다. 벡터 차원은 컬렉션마다 고정이라 모델이나 차원을 바꾸면 새 컬렉션과 전체 재임베딩이 필요합니다.', link: { page: 'vectordb', label: '벡터 DB 열기' } },
];

const LANES = [
  { id: 'agent', title: '에이전트', caption: '에이전트 개발 측', icon: MessagesSquare },
  { id: 'query', title: '검색 엔드포인트', caption: '질의 시점', icon: Search },
  { id: 'index', title: '색인 파이프라인', caption: '사전 처리', icon: Layers3 },
] as const;

const RESPONSIBILITY: [string, string, string][] = [
  ['질의 재작성 · 하위 질문 분해', '맡음', '받은 질의를 그대로 처리'],
  ['검색 횟수 · 재검색 판단', '맡음', '판단에 쓸 단계별 점수 제공'],
  ['권한 적용', '사용자 식별 정보 전달', '보안등급 필터 적용'],
  ['답변 생성 · 인용', '맡음', '문서 · 버전 · 원문 위치 제공'],
  ['정확도 책임', '최종 답변 품질', '검색 정확도(Recall · MRR · nDCG)'],
];

const REQUEST = `POST /search
{
  "query": "세척 밸리데이션 허용 기준",
  "top_k": 10,
  "filters": { "source": ["품질 문서"], "latest_only": true },
  "user": { "id": "u-001", "groups": ["QA"] },
  "options": { "rerank": true, "neighbors": 1 }
}`;
const RESPONSE = `{
  "results": [{
    "chunk_id": "c-0192", "doc_id": "d-0042",
    "doc_version": "Rev5", "is_latest": true,
    "heading_path": ["5. 허용 기준"],
    "text": "…",
    "location": { "page": 7, "char_start": 1840, "char_end": 2310 },
    "scores": {
      "dense": 0.81, "sparse": 12.4,
      "fused": 0.032, "rerank": 0.94
    }
  }],
  "timings_ms": {
    "embed": 0, "dense": 0, "sparse": 0, "rerank": 0, "total": 0
  },
  "versions": {
    "embedding": "…", "reranker": "…", "collection": "…"
  }
}`;

const MEASURE_STEPS = [
  { title: '후보 재현율', body: '의미·키워드 검색과 융합 결과가 정답 청크를 상위 50개 안에 가져오는지 봅니다. 리랭커는 가져온 것만 다시 줄 세웁니다.', metric: 'Recall@50' },
  { title: '최종 순위', body: '리랭커를 거친 뒤 정답이 몇 번째에 오는지 봅니다. 리랭커 유무와 재채점 개수별로 비교합니다.', metric: 'MRR@10 · nDCG@10' },
  { title: '응답 시간', body: '단계별 처리 시간을 따로 잽니다. 리랭커 재채점 개수가 가장 큰 변수입니다.', metric: '단계별 p95' },
  { title: '에이전트 연결 평가', body: '같은 질문으로 에이전트와 함께 답변 품질을 확인합니다. 검색 단독 결과와 나눠 봅니다.', metric: '공동 평가' },
];

const OPEN_QUESTIONS = [
  '하위 질문을 묶음 요청 한 번으로 받을지, 질문마다 따로 받을지',
  '사용자 권한 정보의 전달 형식과 보안등급 기준',
  '응답 시간 목표와 리랭커 재채점 개수',
  '사용할 Milvus 버전의 한국어 키워드 검색 지원',
  '구버전 문서를 기본 제외할지, 요청할 때만 포함할지',
];

type Section = 'roles' | 'contract' | 'measure' | 'open';
const SECTIONS: { id: Section; title: string; hint: string; count: number; icon: typeof GitMerge }[] = [
  { id: 'roles', icon: GitMerge, title: '책임 경계', hint: '에이전트 측과 검색 측이 각각 맡는 일', count: RESPONSIBILITY.length },
  { id: 'contract', icon: Braces, title: 'API 계약 (가안)', hint: '요청·응답 형식 예시', count: 2 },
  { id: 'measure', icon: Ruler, title: '정확도를 재는 순서', hint: '단계마다 따로 재야 어디서 놓쳤는지 압니다', count: MEASURE_STEPS.length },
  { id: 'open', icon: CircleHelp, title: '정할 것', hint: '에이전트 개발 측·운영 측과 합의할 항목', count: OPEN_QUESTIONS.length },
];

function SectionBody({ id }: { id: Section }) {
  if (id === 'roles') return <div className="data-table-wrap"><table className="data-table sp-table"><thead><tr><th>항목</th><th>에이전트 측</th><th>검색 측</th></tr></thead><tbody>{RESPONSIBILITY.map(([item, agent, search]) => <tr key={item}><td><b>{item}</b></td><td>{agent}</td><td>{search}</td></tr>)}</tbody></table></div>;
  if (id === 'contract') return <div className="sp-code-grid"><div><span>요청</span><pre>{REQUEST}</pre></div><div><span>응답</span><pre>{RESPONSE}</pre></div><p className="sp-note">필드 이름과 기본값은 에이전트 개발 측과 합의해 확정합니다. 값은 형식 예시입니다.</p></div>;
  if (id === 'measure') return <ol className="sp-steps">{MEASURE_STEPS.map((step, index) => <li key={step.title}><i>{index + 1}</i><div><b>{step.title}</b><p>{step.body}</p></div><span>{step.metric}</span></li>)}</ol>;
  return <ul className="sp-open">{OPEN_QUESTIONS.map(question => <li key={question}>{question}</li>)}</ul>;
}

export default function SearchPipeline({ onNavigate }: { active: boolean; onNavigate: (page: Page) => void }) {
  return <article className="reference-guide">
    <p className="reference-note">검색 엔드포인트의 설계 초안입니다. 단계별 후보와 미정 사항을 확인할 수 있습니다.</p>
    {LANES.map(lane => <details className="workspace-sheet reference-section" key={lane.id} open={lane.id === 'query'}>
      <summary><lane.icon size={19}/>{lane.title}<small>{lane.caption}</small></summary>
      <ol>{STAGES.filter(s => s.lane === lane.id).map(stage => <li key={stage.id}><h3>{stage.title}<small>{STATUS[stage.status]}</small></h3>
        <p>{stage.detail}</p>{stage.options && <ul>{stage.options.map(o => <li key={o}>{o}</li>)}</ul>}{stage.measure && <p>측정 지표 · {stage.measure}</p>}
        {stage.questions?.map(q => <p key={q}>검토 사항 · {q}</p>)}
        {stage.link && <button className="button-quiet" onClick={() => onNavigate(stage.link!.page)}>{stage.link.label}<ArrowRight size={14}/></button>}</li>)}</ol>
    </details>)}
    {SECTIONS.map(section => <details className="workspace-sheet reference-section" key={section.id}><summary><section.icon size={18}/>{section.title}</summary><div className="sp-section-body"><SectionBody id={section.id}/></div></details>)}
  </article>;
}
