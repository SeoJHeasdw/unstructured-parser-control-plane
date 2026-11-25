import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { ArrowRight, Braces, ChevronDown, Database, Play } from 'lucide-react';
import type { Page } from './types';
import './searchPipeline.css';

/** 검색 설계 참고. 에이전트 개발 측·운영자·현업과 같은 그림을 보며 이야기하려고 만든 화면이다.
 *  글을 늘어놓지 않고, 흐름 지도 한 장(에이전트 → 검색 엔드포인트 → 저장소 ← 색인 파이프라인)에 단계와 결정 상태를 올린다.
 *  그림의 문법(키커 + 두 줄 결론 제목, 흐르는 선, 짧은 말)은 udemy-agent 강의 덱에서 가져오고, 색과 바탕은 콘솔 토큰을 그대로 쓴다.
 *  단계를 누르면 그 단계에서 정한 것과 정할 것을 보이고, 원래 설명 글은 '자세히'로 접어 둔다.
 *  상태(확정·후보·미정)는 설계 초안이다. 수치나 실행 상태가 아니다. */

type Status = 'fixed' | 'candidate' | 'open' | 'agent';
type Lane = 'agent' | 'query' | 'index';
type Stage = {
  id: string; lane: Lane; title: string; short: string; status: Status; does: string; detail: string;
  options?: string[]; measure?: string; badge?: string; questions?: string[]; link?: { page: Page; label: string };
};

const STATUS: Record<Status, string> = { fixed: '확정', candidate: '후보', open: '미정', agent: '에이전트 측' };
const LANE_LABEL: Record<Lane, string> = { agent: '에이전트 · 에이전트 개발 측', query: '검색 엔드포인트 · 질의 시점', index: '색인 파이프라인 · 미리 해 두는 일' };

const STAGES: Stage[] = [
  { id: 'a1', lane: 'agent', title: '사용자 질문', short: '자연어 질문', status: 'agent', does: '질문과 대화 맥락을 받는다', detail: '사용자 질문을 받아 대화 맥락과 함께 해석하는 일은 에이전트가 맡습니다.' },
  { id: 'a2', lane: 'agent', title: '재작성 · 분해', short: '다시 쓰기, 하위 질문', status: 'agent', does: '질문을 다시 쓰거나 하위 질문으로 나눈다', detail: '질문을 다시 쓰거나 여러 하위 질문으로 나누는 방식은 에이전트 개발 측이 정합니다. 검색은 받은 질의를 그대로 처리합니다.', questions: ['하위 질문을 한 번에 묶어 보낼지, 질문마다 따로 호출할지'] },
  { id: 'a3', lane: 'agent', title: 'search 호출', short: '질의 1개 또는 묶음', status: 'agent', does: '질의 · 사용자 정보 · 필터를 담아 호출한다', detail: '질의와 사용자 식별 정보, 필요한 필터를 담아 검색 엔드포인트를 호출합니다. 호출 횟수와 순서는 에이전트가 정합니다.' },
  { id: 'a4', lane: 'agent', title: '근거 판단', short: '충분한가, 더 찾을까', status: 'agent', does: '근거가 충분한지 보고 다시 찾을지 정한다', detail: '돌려받은 근거가 충분한지 판단하고 다시 검색할지 정하는 일은 에이전트가 맡습니다. 검색은 판단에 쓸 단계별 점수와 원문 위치를 함께 돌려줍니다.', questions: ['검색 쪽 점수를 판단 기준으로 쓸지, 에이전트 자체 판단만 쓸지', '전체 호출 횟수와 시간 상한'] },
  { id: 'a5', lane: 'agent', title: '답변 생성', short: '인용 포함', status: 'agent', does: '인용을 달아 답을 쓴다', detail: '답변 작성과 인용 표시는 에이전트가 맡습니다. 검색은 인용에 필요한 문서·버전·원문 위치를 제공합니다.' },

  { id: 'q1', lane: 'query', title: '요청 확인', short: '질의, top_k, 필터', status: 'open', does: '질의 · 개수 · 필터 · 사용자 정보를 확인한다', detail: '질의 문자열, 돌려줄 개수, 필터, 사용자 식별 정보를 확인합니다. 하위 질문 여러 개를 한 번에 받는 묶음 요청도 가안으로 둡니다.', questions: ['사용자 권한 정보를 어떤 형식으로 받을지'] },
  { id: 'q2', lane: 'query', title: '권한 · 범위 필터', short: '보안등급, 최신본', status: 'open', does: '볼 수 없는 조각과 구버전을 먼저 뺀다', detail: '사용자 권한에 맞지 않는 청크를 미리 걸러 냅니다. 원천·문서 유형·파티션으로 범위를 좁히고, 기본값으로 최신 버전 문서만 대상으로 삼습니다.', options: ['상속된 보안등급으로 거르기', '문서 계보의 최신 판단으로 구버전 빼기', '파티션 · 원천 · 문서 유형 지정'], link: { page: 'relations', label: '문서 계보에서 최신 판단 보기' } },
  { id: 'q3a', lane: 'query', title: '의미 검색', short: 'dense 벡터', status: 'candidate', does: '뜻이 가까운 조각을 찾는다', detail: '질의를 문서와 같은 임베딩 모델로 벡터화해 가까운 청크를 찾습니다. 질의와 문서는 반드시 같은 모델·버전을 씁니다.', options: ['Harrier-OSS-v1 0.6B · 1024차원 · 32K 토큰', '그 밖의 후보는 임베딩 평가에서 비교'], measure: 'Recall@50', link: { page: 'embedding', label: '임베딩 평가 열기' } },
  { id: 'q3b', lane: 'query', title: '키워드 검색', short: 'BM25 · sparse', status: 'candidate', does: '같은 단어가 적힌 조각을 찾는다', detail: '문서번호·제품코드·수치처럼 정확히 일치해야 하는 표현을 찾습니다. 의미 검색이 놓치는 결과를 채웁니다.', options: ['Milvus 전문 검색(BM25 함수)', '학습형 희소 벡터'], measure: 'Recall@50', questions: ['사용할 Milvus 버전의 한국어 형태소 분석기 지원 여부'] },
  { id: 'q4', lane: 'query', title: '결과 융합', short: 'RRF / 가중 합', status: 'candidate', does: '두 순위를 하나로 합친다', detail: '두 검색 결과를 한 순위로 합칩니다. 점수 척도가 달라 순위 기반 RRF를 기본으로 두고 가중 합과 비교합니다.', options: ['RRF(순위 기반)', '가중 합(점수 정규화 필요)'], measure: 'Recall@50' },
  { id: 'q5', lane: 'query', title: '리랭커', short: '상위 N개 다시 채점', status: 'candidate', does: '상위 후보를 다시 읽어 순서를 매긴다', detail: '융합된 상위 N개를 질의와 함께 다시 읽어 순서를 매깁니다. 정확도를 가장 크게 올리는 단계이면서 지연 시간이 가장 큰 단계입니다. 앞 단계가 가져오지 못한 청크는 리랭커가 살릴 수 없습니다.', options: ['다국어 리랭커를 한국어 질문으로 실측', '재채점 개수 N과 지연 시간의 균형'], measure: 'MRR@10 · nDCG@10' },
  { id: 'q6', lane: 'query', title: '후처리', short: '중복 · 문서당 개수', status: 'open', does: '중복을 정리하고 문서당 개수를 제한한다', detail: '같은 문서의 청크가 결과를 독차지하지 않게 문서당 개수를 제한하고, 겹치는 청크를 정리하고, 필요하면 앞뒤 청크를 붙여 문맥을 보강합니다.', options: ['문서당 최대 청크 수', '앞뒤 청크 붙이기', '점수 하한'] },
  { id: 'q7', lane: 'query', title: '응답', short: '근거 · 위치 · 점수', status: 'open', does: '원문 · 위치 · 단계별 점수를 돌려준다', detail: '청크 원문, 문서 ID·버전·최신 여부, 원문 위치(페이지·시트·셀·문자 범위), 단계별 점수, 단계별 처리 시간, 모델·인덱스 버전을 돌려줍니다.' },

  { id: 'i1', lane: 'index', title: '원천 수집', short: '원천 · 형식이 늘어남', status: 'open', does: '원천과 파일 형식은 계속 늘어날 수 있다', detail: '원천과 파일 형식은 계속 추가될 수 있습니다. 압축 파일과 메일 첨부 안의 문서도 대상입니다.', link: { page: 'live', label: '실제 파일 처리 열기' } },
  { id: 'i2', lane: 'index', title: 'DRM 해제', short: '해제 경로 등록', status: 'open', does: 'DRM이 걸린 문서는 해제한 뒤 처리한다', detail: 'DRM이 걸린 문서는 해제한 뒤 처리합니다. 해제 대상 선별과 이력 관리 방식은 협의가 필요합니다.' },
  { id: 'i3', lane: 'index', title: '파싱 · OCR', short: '본문 · 표 · 위치', status: 'candidate', does: '본문 · 표 · 원문 위치를 뽑는다', detail: '본문과 표, 숫자·단위를 추출하고 원문 위치를 보존합니다. 스캔 페이지는 OCR이 필요합니다.', link: { page: 'compare', label: '예시 검수 열기' } },
  { id: 'i4', lane: 'index', title: '문서 계보', short: '최신본 · 포함 · 참조', status: 'candidate', does: '최신본과 포함 · 참조 관계를 정리한다', detail: '버전 중 최신본을 판단하고, 문서 속 문서와 참조 관계를 정리합니다. 검색 시 최신본 필터와 구버전 참조 경고에 씁니다.', link: { page: 'relations', label: '문서 계보 열기' } },
  { id: 'i5', lane: 'index', title: '청킹', short: '구조 기준 분할', status: 'candidate', does: '제목 · 표 구조를 살려 나눈다', detail: '제목·표 같은 문서 구조를 살려 나눕니다. 청크 크기는 임베딩 모델의 최대 입력 토큰 안에서 정합니다.', measure: '길이 분포 · 누락률 · 표 분할 수', badge: '누락률 · 표 분할', link: { page: 'chunking', label: '청킹 비교 열기' } },
  { id: 'i6', lane: 'index', title: '임베딩', short: 'dense + sparse', status: 'candidate', does: '의미 벡터와 키워드 표현을 만든다', detail: '청크마다 의미 벡터를 만들고, 키워드 검색용 희소 표현을 함께 준비합니다.', measure: '처리량 · 재처리 시간', badge: '처리량', link: { page: 'embedding', label: '임베딩 평가 열기' } },
  { id: 'i7', lane: 'index', title: 'Milvus 적재', short: '컬렉션 · 파티션', status: 'fixed', does: '벡터와 꼬리표를 함께 저장한다', detail: '벡터와 함께 문서 ID·버전·보안등급·원문 위치를 스칼라 필드로 저장합니다. 벡터 차원은 컬렉션마다 고정이라 모델이나 차원을 바꾸면 새 컬렉션과 전체 재임베딩이 필요합니다.', link: { page: 'vectordb', label: '벡터 DB 열기' } },
];
const BY_ID = Object.fromEntries(STAGES.map(s => [s.id, s])) as Record<string, Stage>;

/* ── 흐름 지도: 1060 × 548 좌표. 칸이 좁으면 통째로 줄인다. ───────────── */
const MW = 1060, MH = 548, NW = 128;
const COL = [28, 174, 320, 466, 612, 758, 904];
type Box = { x: number; y: number; w: number; h: number };
const box = (x: number, y: number, h = 58): Box => ({ x, y, w: NW, h });
const POS: Record<string, Box> = {
  a1: box(COL[0], 160), a2: box(COL[1], 160), a3: box(COL[2], 160), a4: box(COL[5], 160), a5: box(COL[6], 160),
  q1: box(COL[0], 280), q2: box(COL[1], 280), q3a: box(COL[2], 262, 44), q3b: box(COL[2], 312, 44), q4: box(COL[3], 280), q5: box(COL[4], 280), q6: box(COL[5], 280), q7: box(COL[6], 280),
  i1: box(COL[0], 458), i2: box(COL[1], 458), i3: box(COL[2], 458), i4: box(COL[3], 458), i5: box(COL[4], 458), i6: box(COL[5], 458), i7: box(COL[6], 458),
};
const BAR: Box = { x: 28, y: 384, w: 1004, h: 32 };
const LANE_Y: Record<Lane, number> = { agent: 138, query: 240, index: 436 };

const R = (b: Box) => [b.x + b.w, b.y + b.h / 2] as const;
const L = (b: Box) => [b.x, b.y + b.h / 2] as const;
const T = (b: Box, dx = b.w / 2) => [b.x + dx, b.y] as const;
const B = (b: Box, dx = b.w / 2) => [b.x + dx, b.y + b.h] as const;
const across = ([ax, ay]: readonly number[], [bx, by]: readonly number[]) => { const m = (ax + bx) / 2; return `M${ax},${ay} C${m},${ay} ${m},${by} ${bx},${by}`; };
const down = ([ax, ay]: readonly number[], [bx, by]: readonly number[]) => { const m = (ay + by) / 2; return `M${ax},${ay} C${ax},${m} ${bx},${m} ${bx},${by}`; };

/** 흐름을 보여 줄 때 켜지는 차례. 문서가 먼저 쌓이고, 질문이 그 위를 지나간다. */
const SEQ: Record<string, number> = { i1: 1, i2: 2, i3: 3, i4: 4, i5: 5, i6: 6, i7: 7, bar: 8, a1: 9, a2: 10, a3: 11, q1: 12, q2: 13, q3a: 14, q3b: 14, q4: 15, q5: 16, q6: 17, q7: 18, a4: 19, a5: 20 };
const LAST = 21;
type Edge = { from: string; to: string; d: string; tone: 'query' | 'index' | 'store' | 'loop'; seq: number };
const edge = (from: string, to: string, d: string, tone: Edge['tone'], seq = SEQ[to]): Edge => ({ from, to, d, tone, seq });
const EDGES: Edge[] = [
  ...['i1', 'i2', 'i3', 'i4', 'i5', 'i6'].map((id, k) => { const next = `i${k + 2}`; return edge(id, next, across(R(POS[id]), L(POS[next])), 'index'); }),
  edge('i7', 'bar', down(T(POS.i7), [POS.i7.x + NW / 2, BAR.y + BAR.h]), 'store', 8),
  edge('a1', 'a2', across(R(POS.a1), L(POS.a2)), 'query'),
  edge('a2', 'a3', across(R(POS.a2), L(POS.a3)), 'query'),
  edge('a3', 'q1', down(B(POS.a3), T(POS.q1)), 'query'),
  edge('q1', 'q2', across(R(POS.q1), L(POS.q2)), 'query'),
  edge('q2', 'q3a', across(R(POS.q2), L(POS.q3a)), 'query'),
  edge('q2', 'q3b', across(R(POS.q2), L(POS.q3b)), 'query'),
  edge('bar', 'q3b', down([POS.q3b.x + NW / 2, BAR.y], B(POS.q3b)), 'store', 14),
  edge('bar', 'q2', down([POS.q2.x + NW / 2, BAR.y], B(POS.q2)), 'store', 13),
  edge('q3a', 'q4', across(R(POS.q3a), L(POS.q4)), 'query', 15),
  edge('q3b', 'q4', across(R(POS.q3b), L(POS.q4)), 'query', 15),
  edge('q4', 'q5', across(R(POS.q4), L(POS.q5)), 'query'),
  edge('q5', 'q6', across(R(POS.q5), L(POS.q6)), 'query'),
  edge('q6', 'q7', across(R(POS.q6), L(POS.q7)), 'query'),
  edge('q7', 'a4', down(T(POS.q7), B(POS.a4)), 'query', 19),
  edge('a4', 'a5', across(R(POS.a4), L(POS.a5)), 'query'),
  edge('a4', 'a3', `M${POS.a4.x},${POS.a4.y + 20} C${POS.a4.x - 90},${POS.a4.y - 34} ${POS.a3.x + NW + 90},${POS.a3.y - 34} ${POS.a3.x + NW},${POS.a3.y + 20}`, 'loop', LAST),
];

type Lens = 'all' | 'user' | 'operator' | 'designer';
const COUNTS = { fixed: STAGES.filter(s => s.status === 'fixed').length, candidate: STAGES.filter(s => s.status === 'candidate').length, open: STAGES.filter(s => s.status === 'open').length };
const LENSES: { id: Lens; who: string; what: string; kicker: string; title: [string, string]; ids?: string[] }[] = [
  { id: 'all', who: '전체', what: '흐름 한 장', kicker: '검색 엔드포인트 · 설계 초안', title: ['에이전트가 묻고', '검색은 근거를 돌려줍니다'] },
  { id: 'user', who: '사용자', what: '문서가 찾아지기까지', kicker: '사용자가 볼 때', title: ['올린 문서는 미리 잘라 두고', '질문이 오면 그 조각을 찾습니다'], ids: ['a1', 'a5', 'q3a', 'q3b', 'q7', 'i1', 'i2', 'i3', 'i4', 'i5', 'i6', 'i7', 'bar'] },
  { id: 'operator', who: '운영자', what: '품질을 재는 곳', kicker: '운영자가 볼 때', title: ['단계마다 따로 재야', '어디서 놓쳤는지 압니다'], ids: STAGES.filter(s => s.measure).map(s => s.id) },
  { id: 'designer', who: '설계자', what: '정할 것', kicker: '설계자가 볼 때', title: [`확정 ${COUNTS.fixed} · 후보 ${COUNTS.candidate}`, `미정 ${COUNTS.open}곳을 함께 정합니다`], ids: STAGES.filter(s => s.status === 'open' || s.questions?.length).map(s => s.id) },
];

function useFit(width: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => { if (el.clientWidth) setScale(Math.min(1, el.clientWidth / width)); };
    fit();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [width]);
  return { ref, scale };
}

/** 처음 열 때 한 번 흐름을 켜며 보여 주고, 다시 볼 수 있다. 동작 줄이기 설정이면 바로 다 켠다. */
function useFlow() {
  const reduced = typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [t, setT] = useState(reduced ? LAST : 0);
  const [run, setRun] = useState(!reduced);
  useEffect(() => {
    if (!run) return;
    const timer = window.setInterval(() => setT(v => { if (v >= LAST) { setRun(false); return LAST; } return v + 1; }), 280);
    return () => window.clearInterval(timer);
  }, [run]);
  return { t, running: run, replay: () => { setT(0); setRun(true); } };
}

function FlowMap({ lens, setLens, selected, onSelect, hot }: { lens: Lens; setLens: (lens: Lens) => void; selected?: string; onSelect: (id: string) => void; hot: string[] }) {
  const { ref, scale } = useFit(MW);
  const { t, running, replay } = useFlow();
  const view = LENSES.find(l => l.id === lens)!;
  const focus = view.ids ? new Set(view.ids) : undefined;
  const dim = (id: string) => focus ? !focus.has(id) : false;
  return <div className="sp-map" ref={ref} style={{ height: MH * scale }}>
    <div className="sp-map-stage" style={{ transform: `scale(${scale})` }} data-lens={lens}>
      <div className="sp-kicker">{view.kicker}</div>
      <h2 className="sp-title" aria-live="polite">{view.title[0]}<br/><em>{view.title[1]}</em></h2>
      <div className="sp-lens" role="group" aria-label="누가 보나">
        {LENSES.map(l => <button key={l.id} aria-pressed={lens === l.id} onClick={() => setLens(l.id)}><b>{l.who}</b><small>{l.what}</small></button>)}
      </div>
      <button className="sp-replay" onClick={replay} disabled={running}><Play size={13} aria-hidden="true"/>흐름 다시 보기</button>

      {(Object.keys(LANE_Y) as Lane[]).map(lane => <div key={lane} className="sp-lane-label" data-lane={lane} style={{ top: LANE_Y[lane] }}>{LANE_LABEL[lane]}</div>)}

      <svg className="sp-edges" viewBox={`0 0 ${MW} ${MH}`} aria-hidden="true">
        <defs>{(['query', 'index', 'store', 'loop'] as const).map(tone => <marker key={tone} id={`sp-arrow-${tone}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" className="sp-arrowhead" data-tone={tone}/></marker>)}</defs>
        {EDGES.map(e => {
          const lit = t >= e.seq, faded = dim(e.from) || dim(e.to);
          return <g key={`${e.from}-${e.to}`} data-tone={e.tone} data-lit={lit || undefined} data-dim={faded || undefined} data-hot={hot.includes(e.to) || hot.includes(e.from) || undefined}>
            <path className="sp-edge" d={e.d} pathLength={1} markerEnd={lit ? `url(#sp-arrow-${e.tone})` : undefined}/>
            {e.tone !== 'loop' && <path className="sp-edge-flow" d={e.d}/>}
          </g>;
        })}
      </svg>
      <div className="sp-loop-label" data-lit={t >= LAST || undefined} data-dim={dim('a4') || undefined}>근거가 모자라면 다시 찾는다</div>

      <div className="sp-bar" data-lit={t >= SEQ.bar || undefined} data-dim={dim('bar') || undefined} style={{ left: BAR.x, top: BAR.y, width: BAR.w, height: BAR.h }}>
        <Database size={15} aria-hidden="true"/><b>Milvus</b><span>벡터 + 꼬리표(문서 ID · 판 · 보안등급 · 원문 위치)</span>
      </div>

      {STAGES.map(s => {
        const p = POS[s.id];
        return <button key={s.id} className="sp-node" data-status={s.status} data-lit={t >= SEQ[s.id] || undefined} data-now={(running && t === SEQ[s.id]) || undefined}
          data-dim={dim(s.id) || undefined} data-hot={hot.includes(s.id) || undefined} aria-pressed={selected === s.id}
          style={{ left: p.x, top: p.y, width: p.w, height: p.h }} onClick={() => onSelect(s.id)} aria-label={`${s.title} · ${STATUS[s.status]}`}>
          <b>{s.title}</b>{p.h > 50 && <small>{s.short}</small>}
          <i className="sp-node-status">{STATUS[s.status]}</i>
          {lens === 'operator' && s.measure && <em className="sp-node-badge" data-kind="measure" data-at={s.id === 'q3a' ? 'top' : undefined}>{s.badge ?? s.measure}</em>}
          {lens === 'designer' && !!s.questions?.length && <em className="sp-node-badge" data-kind="ask">정할 것 {s.questions.length}</em>}
        </button>;
      })}
    </div>
  </div>;
}

function Inspector({ id, onNavigate }: { id?: string; onNavigate: (page: Page) => void }) {
  const [more, setMore] = useState(false);
  useEffect(() => setMore(false), [id]);
  if (!id) return <div className="sp-inspect sp-inspect-empty">
    <p><b>단계를 누르면</b> 무엇을 하는지, 무엇이 정해졌고 무엇을 정해야 하는지가 여기 보입니다.</p>
    <ul className="sp-legend">
      {(['fixed', 'candidate', 'open', 'agent'] as Status[]).map(k => <li key={k} data-status={k}><i aria-hidden="true"/>{STATUS[k]}<b>{STAGES.filter(s => s.status === k).length}</b></li>)}
    </ul>
  </div>;
  const s = BY_ID[id];
  return <div className="sp-inspect" key={id}>
    <div className="sp-inspect-head">
      <span className="sp-pill" data-status={s.status}>{STATUS[s.status]}</span>
      <h3>{s.title}</h3>
      <small>{LANE_LABEL[s.lane]}</small>
      {s.link && <button className="sp-go" onClick={() => onNavigate(s.link!.page)}>{s.link.label}<ArrowRight size={14} aria-hidden="true"/></button>}
    </div>
    <p className="sp-does">{s.does}</p>
    <div className="sp-facets">
      {s.options && <div><span>후보 · 방법</span><ul className="sp-chips" data-kind="option">{s.options.map(o => <li key={o}>{o}</li>)}</ul></div>}
      {s.measure && <div><span>재는 것</span><ul className="sp-chips" data-kind="measure"><li>{s.measure}</li></ul></div>}
      {s.questions && <div><span>정할 것</span><ul className="sp-chips" data-kind="ask">{s.questions.map(q => <li key={q}>{q}</li>)}</ul></div>}
    </div>
    <button className="sp-more" aria-expanded={more} onClick={() => setMore(v => !v)}>자세히<ChevronDown size={14} aria-hidden="true"/></button>
    {more && <p className="sp-detail">{s.detail}</p>}
  </div>;
}

/* ── 아래 판: 책임 경계 · API 계약 · 재는 순서 · 정할 것 ───────────────── */
function Panel({ kicker, title, wide, children }: { kicker: string; title: [string, string]; wide?: boolean; children: ReactNode }) {
  return <section className="sp-panel" data-wide={wide || undefined}>
    <div className="sp-panel-kicker">{kicker}</div>
    <h2 className="sp-panel-title">{title[0]} <em>{title[1]}</em></h2>
    {children}
  </section>;
}

const RESPONSIBILITY: [string, string, string][] = [
  ['질의 재작성 · 하위 질문', '맡는다', '받은 질의를 그대로 처리'],
  ['검색 횟수 · 재검색 판단', '맡는다', '판단에 쓸 단계별 점수 제공'],
  ['권한 적용', '사용자 식별 정보 전달', '보안등급 필터 적용'],
  ['답변 생성 · 인용', '맡는다', '문서 · 판 · 원문 위치 제공'],
  ['정확도 책임', '최종 답변 품질', '검색 정확도(Recall · MRR · nDCG)'],
];

const REQUEST_FIELDS: { name: string; say: string; stage: string }[] = [
  { name: 'query', say: '질의 한 줄', stage: 'a3' },
  { name: 'top_k', say: '돌려받을 개수', stage: 'q1' },
  { name: 'filters', say: '원천 · 최신본만', stage: 'q2' },
  { name: 'user', say: '사용자 · 그룹', stage: 'q2' },
  { name: 'options', say: '리랭커 · 앞뒤 조각', stage: 'q5' },
];
const RESPONSE_FIELDS: { name: string; say: string; stage: string }[] = [
  { name: 'text · heading_path', say: '조각 원문과 제목 경로', stage: 'i5' },
  { name: 'doc_version · is_latest', say: '어느 판인지', stage: 'q2' },
  { name: 'location', say: '쪽 · 시트 · 셀 · 문자 범위', stage: 'i3' },
  { name: 'scores.dense · sparse', say: '두 검색의 점수', stage: 'q3a' },
  { name: 'scores.fused · rerank', say: '합친 점수 · 다시 매긴 점수', stage: 'q5' },
  { name: 'timings_ms · versions', say: '단계별 시간 · 모델과 인덱스 판', stage: 'q7' },
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
    "scores": { "dense": 0.81, "sparse": 12.4, "fused": 0.032, "rerank": 0.94 }
  }],
  "timings_ms": { "embed": 0, "dense": 0, "sparse": 0, "rerank": 0, "total": 0 },
  "versions": { "embedding": "…", "reranker": "…", "collection": "…" }
}`;

const MEASURE_STEPS = [
  { title: '가져왔나', body: '정답 조각이 후보 50개 안에 들었나', metric: 'Recall@50', stages: ['q3a', 'q3b', 'q4'] },
  { title: '몇 위인가', body: '다시 매긴 뒤 정답이 몇 번째인가', metric: 'MRR@10 · nDCG@10', stages: ['q5'] },
  { title: '얼마나 걸리나', body: '단계마다 시간을 따로 잰다', metric: '단계별 p95', stages: ['q3a', 'q3b', 'q5', 'q7'] },
  { title: '답이 맞나', body: '같은 질문으로 에이전트와 함께 본다', metric: '공동 평가', stages: ['a4', 'a5'] },
];

const OPEN_QUESTIONS = [
  { q: '하위 질문을 묶음 요청 한 번으로 받을지, 질문마다 따로 받을지', stage: 'q1' },
  { q: '사용자 권한 정보의 전달 형식과 보안등급 기준', stage: 'q2' },
  { q: '응답 시간 목표와 리랭커 재채점 개수', stage: 'q5' },
  { q: '사용할 Milvus 버전의 한국어 키워드 검색 지원', stage: 'q3b' },
  { q: '구버전 문서를 기본 제외할지, 요청할 때만 포함할지', stage: 'q2' },
];

function FieldList({ title, fields, onHot }: { title: string; fields: { name: string; say: string; stage: string }[]; onHot: (ids: string[]) => void }) {
  return <div className="sp-fields">
    <b className="sp-fields-title">{title}</b>
    <ul>{fields.map(f => <li key={f.name} onMouseEnter={() => onHot([f.stage])} onMouseLeave={() => onHot([])}>
      <code>{f.name}</code><span>{f.say}</span><em>{BY_ID[f.stage].title}</em>
    </li>)}</ul>
  </div>;
}

export default function SearchPipeline({ onNavigate }: { active: boolean; onNavigate: (page: Page) => void }) {
  const [lens, setLens] = useState<Lens>('all');
  const [selected, setSelected] = useState<string>();
  const [hot, setHot] = useState<string[]>([]);
  const [json, setJson] = useState(false);
  const mapRef = useRef<HTMLDivElement>(null);
  const pick = (id: string) => setSelected(v => v === id ? undefined : id);
  const show = (id: string) => { setSelected(id); setLens('all'); mapRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' }); };

  return <article className="sp-root">
    <div className="sp-board" ref={mapRef}>
      <FlowMap lens={lens} setLens={setLens} selected={selected} onSelect={pick} hot={hot}/>
      <Inspector id={selected} onNavigate={onNavigate}/>
    </div>

    <div className="sp-grid">
      <Panel kicker="책임 경계" title={['에이전트가 묻고 판단하고,', '검색은 근거를 돌려줍니다']}>
        <div className="sp-relay">
          <div className="sp-relay-head"><span data-side="agent">에이전트 측</span><span className="sp-relay-pass"><i>질의 · 사용자 정보 →</i><i>← 근거 · 위치 · 단계별 점수</i></span><span data-side="search">검색 측</span></div>
          {RESPONSIBILITY.map(([item, agent, search]) => <div className="sp-relay-row" key={item}>
            <span data-side="agent" data-own={agent === '맡는다' || undefined}>{agent}</span>
            <b>{item}</b>
            <span data-side="search">{search}</span>
          </div>)}
        </div>
      </Panel>

      <Panel kicker="정확도를 재는 순서" title={['가져왔는지 먼저 재고,', '그다음 순서를 잽니다']}>
        <ol className="sp-funnel">
          {MEASURE_STEPS.map((m, i) => <li key={m.title} style={{ '--w': `${100 - i * 8}%` } as CSSProperties} onMouseEnter={() => setHot(m.stages)} onMouseLeave={() => setHot([])}>
            <i>{i + 1}</i><div><b>{m.title}</b><span>{m.body}</span></div><em>{m.metric}</em>
          </li>)}
        </ol>
        <p className="sp-panel-note">리랭커는 가져온 것만 다시 줄 세웁니다. 1에서 놓친 조각은 2에서 살릴 수 없으니, 단계마다 따로 잽니다.</p>
      </Panel>

      <Panel wide kicker="API 계약 · 가안" title={['보내는 것은 질문과 범위,', '받는 것은 근거와 위치와 점수']}>
        <div className="sp-contract">
          <FieldList title="요청 POST /search" fields={REQUEST_FIELDS} onHot={setHot}/>
          <ArrowRight className="sp-contract-arrow" size={20} aria-hidden="true"/>
          <FieldList title="응답 results[]" fields={RESPONSE_FIELDS} onHot={setHot}/>
        </div>
        <p className="sp-panel-note">필드에 마우스를 올리면 위 지도에서 그 값을 만드는 단계가 빛납니다. 필드 이름과 기본값은 에이전트 개발 측과 합의해 확정합니다.</p>
        <button className="sp-more" aria-expanded={json} onClick={() => setJson(v => !v)}><Braces size={14} aria-hidden="true"/>JSON 원문 보기<ChevronDown size={14} aria-hidden="true"/></button>
        {json && <div className="sp-json"><pre>{REQUEST}</pre><pre>{RESPONSE}</pre></div>}
      </Panel>

      <Panel wide kicker="정할 것" title={[`${OPEN_QUESTIONS.length}가지를`, '에이전트 개발 측 · 운영 측과 정합니다']}>
        <ul className="sp-asks">
          {OPEN_QUESTIONS.map(o => <li key={o.q}><p>{o.q}</p><button onClick={() => show(o.stage)}>{BY_ID[o.stage].title}<ArrowRight size={13} aria-hidden="true"/></button></li>)}
        </ul>
      </Panel>
    </div>
  </article>;
}
