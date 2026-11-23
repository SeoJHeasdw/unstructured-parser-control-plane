import { useCallback, useEffect, useRef, useState } from 'react';
import type { FocusEvent, MouseEvent, ReactNode } from 'react';
import { X } from 'lucide-react';
import { createPortal } from 'react-dom';
import type { ChunkKind, ImagePolicy, Preset, StrategyKind, StrategyParams, TablePolicy } from '../api/retrieval';

/* ---------- 브라우저 저장(뷰어별 편의 설정). 저장이 막힌 환경에서도 화면은 그대로 동작한다. ---------- */
/* 프리셋·벤치 선택은 v3: 기본 전략 여섯 개(요소 인지 넷 + 기준선 둘)로 바뀌었다. 예전 저장값은 읽지 않는다. */
export const STORE = { presets: 'document-ops:chunk-presets-v3', bench: 'document-ops:chunk-bench-v3', benchUi: 'document-ops:chunk-bench-ui-v3', candidates: 'document-ops:embedding-candidates', evalUi: 'document-ops:embedding-eval-ui' } as const;

export function readStore<T>(key: string, fallback: T): T {
  try { const raw = window.localStorage.getItem(key); return raw ? JSON.parse(raw) as T : fallback; } catch { return fallback; }
}
export function writeStore(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장할 수 없는 환경: 이번 화면에서만 유지 */ }
}
export function usePersistent<T extends object>(key: string, initial: T): [T, (update: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => { const stored = readStore<unknown>(key, null); return stored && typeof stored === 'object' && !Array.isArray(stored) && !Array.isArray(initial) ? { ...initial, ...(stored as Partial<T>) } : initial; });
  useEffect(() => { writeStore(key, value); }, [key, value]);
  return [value, setValue];
}

/* ---------- 청킹 프리셋: 청킹 벤치에서 저장하고 임베딩 평가에서 다시 쓴다. ---------- */
export const STRATEGY_LABEL: Record<StrategyKind, string> = {
  element: '요소 인지', parent_child: '부모-자식', page: '페이지 단위', semantic: '의미 기반',
  fixed: '고정 길이', recursive: '재귀 분할', sentence: '문장 묶음', markdown: '제목 구조',
};
/** 방식 고르기 카드의 한 줄 설명. */
export const STRATEGY_SHORT: Record<StrategyKind, string> = {
  element: '표·그림·캡션을 따로 다룸', parent_child: '작게 찾고 넓게 읽기', page: '쪽마다 한 청크', semantic: '뜻이 바뀌는 곳에서 나눔',
  fixed: '정한 길이마다 자름', recursive: '문단→줄→문장 순서로 쪼갬', sentence: '문장을 크기만큼 묶음', markdown: '제목 단위로 나눔',
};
export const STRATEGY_HINT: Record<StrategyKind, string> = {
  element: '본문·목록은 크기만큼 묶고, 표·그림·캡션은 정한 방식대로 따로 다룹니다. 반복 머리말은 뺄 수 있습니다.',
  parent_child: '작은 청크로 찾고, 답할 때는 그 청크가 속한 큰 맥락을 함께 넘깁니다.',
  page: '쪽마다 한 청크로 둡니다. 쪽이 크기를 넘으면 요소 경계에서 나눕니다.',
  fixed: '정해진 길이마다 자르고 앞 청크와 일부를 겹칩니다. 표·그림을 구분하지 않습니다.',
  recursive: '문단 → 줄 → 문장 → 띄어쓰기 순서로, 크기 안에 들 때까지 나눕니다. 표·그림을 구분하지 않습니다.',
  markdown: '제목 단위로 나누고 제목 경로를 남깁니다. 표는 크기를 넘을 때만 행 단위로 나눕니다.',
  sentence: '문장 끝을 찾아 크기만큼 묶고 앞 묶음과 문장 몇 개를 겹칩니다. 표·그림을 구분하지 않습니다.',
  semantic: '이웃 문장의 임베딩을 비교해 뜻이 크게 바뀌는 곳에서 나눕니다. 제목에서 끊고 표·코드는 통째로 둡니다. 임베딩 모델이 필요합니다.',
};
/** 요소 인지 계열(표·그림·캡션·머리말을 구분), 의미 기반, 텍스트만 보는 기준선. */
export const ELEMENT_KINDS: StrategyKind[] = ['element', 'parent_child', 'page'];
export const SEMANTIC_KINDS: StrategyKind[] = ['semantic'];
export const familyOf = (kind: StrategyKind) => ELEMENT_KINDS.includes(kind) ? '요소 인지' : SEMANTIC_KINDS.includes(kind) ? '의미 기반' : '기준선';
/** 경계 민감도: 문서 안 이웃 문장 거리의 몇 번째 백분위부터 나눌지. 낮을수록 자주 나눈다. */
export const BREAKPOINTS = [{ value: 95, label: '적게 나눔' }, { value: 90, label: '보통' }, { value: 80, label: '자주 나눔' }] as const;
export const BASELINE_KINDS: StrategyKind[] = ['fixed', 'recursive', 'sentence', 'markdown'];
export const isBaseline = (kind: StrategyKind | undefined) => !!kind && BASELINE_KINDS.includes(kind);
export const TABLE_POLICY: Record<TablePolicy, string> = { whole: '통째로', rows: '행 묶음마다 머리행 반복', row_text: '행을 문장으로' };
export const IMAGE_POLICY: Record<ImagePolicy, string> = { drop: '버림', caption: '캡션으로 청크' };

const ELEMENT_DEFAULTS = { table: 'whole' as TablePolicy, table_rows: 5, image: 'caption' as ImagePolicy, attach_caption: true, drop_furniture: true };
export const DEFAULT_PRESETS: Preset[] = [
  { id: 'builtin-element', name: '요소 인지 · 표 통째', kind: 'element', params: { unit: 'chars', size: 800, ...ELEMENT_DEFAULTS } },
  { id: 'builtin-element-rows', name: '요소 인지 · 행 묶음', kind: 'element', params: { unit: 'chars', size: 500, ...ELEMENT_DEFAULTS, table: 'rows' } },
  { id: 'builtin-parent-child', name: '부모-자식', kind: 'parent_child', params: { unit: 'chars', size: 300, parent_size: 1500, ...ELEMENT_DEFAULTS } },
  { id: 'builtin-page', name: '페이지 단위', kind: 'page', params: { unit: 'chars', size: 3000, ...ELEMENT_DEFAULTS } },
  { id: 'builtin-fixed', name: '고정 500자', kind: 'fixed', params: { unit: 'chars', size: 500, overlap: 50 } },
  { id: 'builtin-recursive', name: '재귀 500자', kind: 'recursive', params: { unit: 'chars', size: 500, overlap: 50 } },
];
/** 처음에는 기본 전략 여섯 개를 모두 비교한다. */
export const DEFAULT_SELECTED = DEFAULT_PRESETS.map(p => p.id);
export function defaultParams(kind: StrategyKind, unit: 'chars' | 'tokens' = 'chars'): StrategyParams {
  const size = unit === 'chars' ? 500 : 250;
  if (kind === 'fixed' || kind === 'recursive') return { unit, size, overlap: Math.round(size / 10) };
  if (kind === 'markdown') return { unit, size, merge_small: true, min_size: Math.round(size / 4) };
  if (kind === 'sentence') return { unit, size, overlap_sentences: 1 };
  if (kind === 'semantic') return { unit, size: unit === 'chars' ? 800 : 400, min_size: unit === 'chars' ? 200 : 100, breakpoint: 90, buffer: 1, connection: 'embed', model: '' };
  if (kind === 'parent_child') return { unit, size: Math.round(size * 0.6), parent_size: size * 3, ...ELEMENT_DEFAULTS };
  if (kind === 'page') return { unit, size: size * 6, ...ELEMENT_DEFAULTS };
  return { unit, size, ...ELEMENT_DEFAULTS };
}
export function isPreset(value: unknown): value is Preset {
  const p = value as Preset;
  return !!p && typeof p === 'object' && typeof p.id === 'string' && typeof p.name === 'string' && p.kind in STRATEGY_LABEL && !!p.params && (p.params.unit === 'chars' || p.params.unit === 'tokens') && typeof p.params.size === 'number';
}
export function loadPresets(): Preset[] {
  const saved = readStore<unknown>(STORE.presets, null);
  return Array.isArray(saved) && saved.some(isPreset) ? saved.filter(isPreset) : DEFAULT_PRESETS;
}
export function savePresets(presets: Preset[]) { writeStore(STORE.presets, presets); }
/** 한 줄 요약: '500자 · 표 통째 · 그림 캡션' */
export function describeParams(p: StrategyParams): string {
  const unit = p.unit === 'chars' ? '자' : '토큰';
  const n = (v: number) => fmtInt(v);
  const parts: string[] = [];
  if (p.parent_size !== undefined) parts.push(`검색 ${n(p.size)}${unit}`, `맥락 ${n(p.parent_size)}${unit}`);
  else parts.push(`${n(p.size)}${unit}`);
  if (p.breakpoint !== undefined) {
    parts[0] = `최대 ${n(p.size)}${unit}`;
    parts.push(`경계 ${BREAKPOINTS.find(b => b.value === p.breakpoint)?.label ?? `상위 ${100 - p.breakpoint}%`}`);
    if (p.model) parts.push(p.model.split('/').pop()!);
    return parts.join(' · ');
  }
  if (p.overlap !== undefined) parts.push(`겹침 ${n(p.overlap)}${unit}`);
  else if (p.overlap_sentences !== undefined) parts.push(`${p.overlap_sentences}문장 겹침`);
  else if (p.merge_small) parts.push(`${n(p.min_size ?? 0)}${unit} 미만 절 합침`);
  if (p.table) parts.push(p.table === 'whole' ? '표 통째' : p.table === 'rows' ? `표 ${p.table_rows ?? 5}행씩` : '표 행→문장');
  if (p.image) parts.push(p.image === 'caption' ? '그림 캡션' : '그림 버림');
  return parts.join(' · ');
}

/* ---------- 표시 문구 ---------- */
export const CHUNK_KIND: Record<ChunkKind, string> = { text: '본문', table: '표', mixed: '본문+표' };
export type Tone = 'bad' | 'warn' | 'info' | 'muted';
export const FLAGS: Record<string, { label: string; tone: Tone; desc: string }> = {
  'over-limit': { label: '한도 초과', tone: 'bad', desc: '대상 모델의 최대 입력 토큰(추정)을 넘습니다. 잘리거나 오류가 날 수 있습니다.' },
  'table-cut': { label: '표 잘림', tone: 'warn', desc: '청크 경계가 표 중간을 지납니다.' },
  'table-no-header': { label: '머리행 없음', tone: 'warn', desc: '표 행이 들어 있지만 머리행은 없습니다. 열 의미를 잃습니다.' },
  'sentence-split': { label: '문장 중간 분할', tone: 'warn', desc: '크기를 넘는 문장을 띄어쓰기에서 나눴습니다.' },
  'hard-split': { label: '글자 단위 분할', tone: 'warn', desc: '띄어쓰기도 없어 글자 수로 잘랐습니다.' },
  'table-split': { label: '표 행 분할', tone: 'info', desc: '큰 표를 행 단위로 나누고 머리행을 반복했습니다.' },
  'merged-sections': { label: '절 합침', tone: 'info', desc: '작은 절을 이웃 절과 합쳤습니다.' },
  'heading-only': { label: '제목만', tone: 'muted', desc: '제목 줄만 있는 청크입니다.' },
  'image-empty': { label: '글자 없는 그림', tone: 'warn', desc: '스캔 그림에 글자·캡션이 없어 내용이 들어가지 않았습니다.' },
  'image-dropped': { label: '그림 버림', tone: 'warn', desc: '그림을 청크에 넣지 않았습니다.' },
  'caption-detached': { label: '캡션 떨어짐', tone: 'warn', desc: '캡션이 설명하는 표·그림과 다른 청크에 있습니다.' },
  'furniture-kept': { label: '반복 머리말 포함', tone: 'warn', desc: '쪽마다 반복되는 머리말·꼬리말이 들어 있습니다.' },
  'table-row-text': { label: '행을 문장으로', tone: 'info', desc: '표 행을 \'열: 값\' 문장으로 바꿨습니다.' },
};
export const flagMeta = (flag: string) => FLAGS[flag] ?? { label: flag, tone: 'muted' as Tone, desc: '' };
export const TOKEN_NOTE = '추정 토큰: 한글 1음절 1토큰, 영문 약 4글자 1토큰, 숫자 2자리 1토큰, 기호 1토큰으로 셉니다. 한글은 보수적으로 잡은 값입니다.';

const nf = new Intl.NumberFormat('ko-KR');
export const fmtInt = (value: number | null | undefined) => value === null || value === undefined || !Number.isFinite(value) ? '—' : nf.format(Math.round(value));
export const fmtPct = (value: number | null | undefined, digits = 1) => value === null || value === undefined || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
export const fmtScore = (value: number | null | undefined) => value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(3);
export function fmtBytes(bytes: number | null | undefined) {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes, i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value >= 100 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}
export function fmtDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}초`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}분`;
  if (seconds < 86400 * 2) return `${(seconds / 3600).toFixed(1)}시간`;
  return `${(seconds / 86400).toFixed(1)}일`;
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '요청을 처리하지 못했습니다.';

/* ---------- 말풍선: 마우스를 올리거나 키보드로 초점을 옮기면 같은 내용이 뜬다. ---------- */
type TipState = { content: ReactNode; x: number; y: number; below: boolean } | null;
export function useTip() {
  const [tip, setTip] = useState<TipState>(null);
  useEffect(() => {
    if (!tip) return;
    const hide = () => setTip(null);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    return () => { window.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide); };
  }, [tip]);
  const bind = useCallback((content: ReactNode | (() => ReactNode), onEnter?: () => void, onLeave?: () => void) => {
    const show = (event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      /* 키가 큰 대상(긴 청크)은 마우스 높이에 띄워 화면 밖으로 나가지 않게 한다. */
      const pointer = 'clientY' in event && rect.height > 120 ? event.clientY : null;
      const top = pointer ?? rect.top, bottom = pointer ?? rect.bottom;
      const below = top < 150;
      setTip({ content: typeof content === 'function' ? content() : content, x: rect.left + rect.width / 2, y: below ? bottom + 8 : top - 8, below });
      onEnter?.();
    };
    const hide = () => { setTip(null); onLeave?.(); };
    return { onMouseEnter: show, onMouseLeave: hide, onFocus: show, onBlur: hide };
  }, []);
  const width = typeof window === 'undefined' ? 1200 : window.innerWidth;
  const inset = Math.min(width / 2, 172);
  const node = tip ? createPortal(<div className={`rb-tip${tip.below ? ' is-below' : ''}`} role="tooltip" style={{ left: Math.min(width - inset, Math.max(inset, tip.x)), top: tip.y }}>{tip.content}</div>, document.body) : null;
  return { node, bind, hide: () => setTip(null) };
}

/* ---------- 고정 상세 패널: X 또는 Esc로 닫고, 닫으면 원래 초점으로 돌아간다. ---------- */
export function SidePanel({ label, title, subtitle, onClose, actions, children }: { label: string; title: ReactNode; subtitle?: ReactNode; onClose: () => void; actions?: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close.current(); } };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); if (previous && document.contains(previous)) previous.focus(); };
  }, []);
  return <aside className="rb-panel" role="dialog" aria-label={label} tabIndex={-1} ref={ref}>
    <header className="rb-panel-head"><div><strong>{title}</strong>{subtitle && <span>{subtitle}</span>}</div>{actions}<button type="button" className="rb-icon" onClick={onClose} aria-label="상세 닫기" data-tip="닫기" data-tip-key="Esc"><X size={16} /></button></header>
    <div className="rb-panel-body">{children}</div>
  </aside>;
}

/** 단위가 바뀌어도 자연스러운 눈금 간격(1·2·5 × 10ⁿ). */
export function niceStep(raw: number) {
  if (raw <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
}
