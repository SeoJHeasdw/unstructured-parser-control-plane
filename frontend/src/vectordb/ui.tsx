import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type FocusEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

/* ----- 보는 사람별 펼침 상태. 저장소를 못 쓰면 이번 화면에서만 유지한다. ----- */
const PREFIX = 'vdb.';
export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const value = JSON.parse(raw) as unknown;
    return typeof value === typeof fallback && (Array.isArray(fallback) === Array.isArray(value)) ? value as T : fallback;
  } catch { return fallback; }
}
export function writeStored(key: string, value: unknown) {
  try { window.localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch { /* 사생활 보호 모드 등 */ }
}
export function useStored<T>(key: string, fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => readStored(key, fallback));
  const update = useCallback((next: T) => { setValue(next); writeStored(key, next); }, [key]);
  return [value, update];
}

export function Disclosure({ id, title, summary, icon, children, className = '' }: { id: string; title: ReactNode; summary?: ReactNode; icon?: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useStored<boolean>(`open.${id}`, false);
  const bodyId = useId();
  return <section className={`vdb-disc ${open ? 'is-open' : ''} ${className}`}>
    <button type="button" className="vdb-disc-head" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
      <ChevronRight size={14} className="vdb-disc-chev" aria-hidden />{icon}<b>{title}</b>{summary !== undefined && <span className="vdb-disc-sum">{summary}</span>}
    </button>
    {open && <div id={bodyId} className="vdb-disc-body">{children}</div>}
  </section>;
}

/* ----- 마우스를 올리거나 키보드로 초점을 옮기면 같은 내용을 띄운다. ----- */
type Float = { key: string; content: ReactNode; rect: DOMRect; kind: 'tip' | 'peek' };
export type FloatBind = ReturnType<ReturnType<typeof useFloating>['bind']>;
export function useFloating() {
  const [float, setFloat] = useState<Float | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const id = useId();
  useEffect(() => {
    if (!float) return;
    const hide = () => setFloat(null);
    window.addEventListener('scroll', hide, true); window.addEventListener('resize', hide);
    return () => { window.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide); };
  }, [float]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const hide = useCallback(() => { window.clearTimeout(timer.current); setFloat(null); }, []);
  const bind = (key: string, content: () => ReactNode, kind: 'tip' | 'peek' = 'tip', delay = 0) => ({
    onMouseEnter: (event: MouseEvent<HTMLElement>) => {
      const el = event.currentTarget; window.clearTimeout(timer.current);
      const show = () => setFloat({ key, content: content(), rect: el.getBoundingClientRect(), kind });
      if (delay) timer.current = window.setTimeout(show, delay); else show();
    },
    onMouseLeave: () => { window.clearTimeout(timer.current); setFloat(current => current?.key === key ? null : current); },
    onFocus: (event: FocusEvent<HTMLElement>) => { window.clearTimeout(timer.current); setFloat({ key, content: content(), rect: event.currentTarget.getBoundingClientRect(), kind }); },
    onBlur: () => setFloat(current => current?.key === key ? null : current),
    'aria-describedby': float?.key === key ? id : undefined,
  });
  const layer = float ? <FloatBox id={id} float={float} /> : null;
  return { bind, layer, hide, shown: float?.key ?? null };
}

function FloatBox({ id, float }: { id: string; float: Float }) {
  const { rect, kind } = float;
  const vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
  let style: CSSProperties;
  if (kind === 'tip') {
    const below = rect.top < 80;
    style = { left: Math.min(Math.max(rect.left + rect.width / 2, 130), vw - 130), top: below ? rect.bottom + 8 : rect.top - 8, transform: below ? 'translateX(-50%)' : 'translate(-50%, -100%)' };
  } else {
    const width = Math.min(460, vw - 24);
    const below = rect.bottom + 280 < vh;
    style = { left: Math.min(Math.max(rect.left, 12), vw - width - 12), width, top: below ? rect.bottom + 4 : rect.top - 4, transform: below ? undefined : 'translateY(-100%)' };
  }
  return <div role="tooltip" id={id} className={`vdb-float vdb-${kind}`} style={style}>{float.content}</div>;
}

/** 미리보기가 떠 있으면 Escape는 미리보기만 닫는다(팝업은 그대로). */
export const escapeHides = (float: { hide: () => void; shown: string | null }) => (event: KeyboardEvent<HTMLElement>) => {
  if (event.key === 'Escape' && float.shown) { event.preventDefault(); event.stopPropagation(); float.hide(); }
};

/* ----- 벡터: 숫자를 늘어놓지 않고 앞부분 값의 부호·크기만 색으로 ----- */
export function heat(t: number): string {
  const a = Math.min(1, Math.abs(t));
  return t >= 0 ? `rgba(110, 99, 202, ${(0.12 + 0.88 * a).toFixed(3)})` : `rgba(214, 128, 58, ${(0.12 + 0.88 * a).toFixed(3)})`;
}
export function VectorStrip({ values, size = 'sm' }: { values: number[]; size?: 'sm' | 'lg' }) {
  const peak = Math.max(1e-9, ...values.map(v => Math.abs(v)));
  return <span className={`vdb-strip is-${size}`} role="img" aria-label={`앞 ${values.length}개 값의 부호와 크기`}>{values.map((v, i) => <i key={i} style={{ background: heat(v / peak) }} />)}</span>;
}

/* ----- 표시 형식 ----- */
export const PALETTE = ['#7468ce', '#3f9b7f', '#d08a3c', '#4a86c5', '#c2557a', '#8a9a3b', '#5f6680', '#2f9db0'];
export const fmtCount = (n: number | null | undefined) => n === null || n === undefined ? '—' : n.toLocaleString('ko-KR');
export const fmtPct = (part: number, whole: number) => whole > 0 ? `${(part / whole * 100).toFixed(part / whole < 0.1 ? 1 : 0)}%` : '—';
export const shortPk = (pk: string) => pk.length > 16 ? `${pk.slice(0, 8)}…${pk.slice(-4)}` : pk;
export const oneLine = (text: string | null | undefined, max = 160) => { const s = (text ?? '').replace(/\s+/g, ' ').trim(); return s.length > max ? `${s.slice(0, max)}…` : s; };
export function fmtValue(value: unknown, max = 40): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString('ko-KR') : String(Number(value.toFixed(6)));
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  const s = typeof value === 'string' ? value : JSON.stringify(value);
  return s.length > max ? `${s.slice(0, max)}…` : s;
}
export const LOAD_LABEL: Record<string, string> = { LoadStateLoaded: '로드됨', LoadStateLoading: '로딩 중', LoadStateNotLoad: '로드 안 됨', LoadStateNotExist: '없음' };
export const loadLabel = (state: string | null | undefined) => state ? LOAD_LABEL[state] ?? state : '확인 안 됨';
export const ROLE_LABEL: Record<string, string> = { text: '텍스트', doc: '문서', order: '순서', source: '출처', page: '쪽', vector: '벡터', pk: '기본 키' };
export function metricHint(metric: string | null | undefined, higher: boolean | null | undefined) {
  if (!metric) return '측정 방식 확인 안 됨';
  return `${metric} · ${higher === false ? '작을수록 가까움' : '클수록 가까움'}`;
}
