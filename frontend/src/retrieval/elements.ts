import type { ElementKind, ElementOutcome, QuestionKind } from '../api/retrieval';

/**
 * 비정형 요소의 이름과 색. 청킹 벤치·임베딩 평가가 같은 색으로 읽히도록 한곳에서 정한다.
 * 본문 계열은 무채색으로 두고, 표·그림·캡션만 색을 써서 눈이 먼저 가게 한다.
 */
export const ELEMENT_META: Record<ElementKind, { label: string; color: string; soft: string }> = {
  heading: { label: '제목', color: '#2f3a52', soft: '#e3e6ed' },
  text: { label: '본문', color: '#7b8699', soft: '#eceef2' },
  list: { label: '목록', color: '#97a0b0', soft: '#f0f1f4' },
  table: { label: '표', color: '#14917f', soft: '#dcf1ed' },
  image: { label: '그림', color: '#c2477f', soft: '#f6e1eb' },
  caption: { label: '캡션', color: '#3b7fc4', soft: '#e0ecf8' },
  code: { label: '코드·수식', color: '#5b6475', soft: '#e7e9ee' },
  furniture: { label: '반복 머리말·꼬리말', color: '#b3b9c5', soft: '#f3f4f6' },
};

/** 화면에 나오는 순서. 본문 계열 다음에 표·그림·캡션. */
export const ELEMENT_ORDER: ElementKind[] = ['heading', 'text', 'list', 'table', 'image', 'caption', 'code', 'furniture'];

/** good: 의도대로 보존 / bad: 정보 손실·잘림 / neutral: 판단 대상 아님 */
export const OUTCOME_META: Record<ElementOutcome, { label: string; tone: 'good' | 'bad' | 'neutral' }> = {
  whole: { label: '온전', tone: 'good' },
  rows: { label: '행 묶음(머리행 반복)', tone: 'good' },
  split: { label: '잘림', tone: 'bad' },
  caption: { label: '캡션으로 들어감', tone: 'good' },
  attached: { label: '대상과 함께', tone: 'good' },
  detached: { label: '대상과 떨어짐', tone: 'bad' },
  missing: { label: '빠짐', tone: 'bad' },
};

/** 반복 머리말이 빠지는 것은 의도된 제거라 손실로 세지 않는다. */
export const outcomeTone = (kind: ElementKind, outcome: ElementOutcome) =>
  kind === 'furniture' ? (outcome === 'missing' ? 'good' : 'bad') : OUTCOME_META[outcome].tone;

export const OUTCOME_BAD = '#d04a4a';

export const QUESTION_KIND_META: Record<QuestionKind, { label: string; color: string }> = {
  text: { label: '본문 질문', color: ELEMENT_META.text.color },
  table: { label: '표 질문', color: ELEMENT_META.table.color },
  image: { label: '그림 질문', color: ELEMENT_META.image.color },
};
export const QUESTION_KINDS: QuestionKind[] = ['text', 'table', 'image'];
