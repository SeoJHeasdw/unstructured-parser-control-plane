import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

type Anchor = Element | { x: number; y: number };
type TipState = { owner: string; content: ReactNode; x: number; y: number; below: boolean } | null;
type TipApi = { show: (owner: string, anchor: Anchor, content: ReactNode) => void; hide: (owner?: string) => void; owner: string | null };
const TipContext = createContext<TipApi>({ show: () => {}, hide: () => {}, owner: null });

/** 마우스를 올리거나 키보드 초점을 둔 항목의 짧은 설명. 클릭하면 상세 창에 고정된다. */
export function TipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState>(null);
  const show = useCallback((owner: string, anchor: Anchor, content: ReactNode) => {
    const rect = anchor instanceof Element ? anchor.getBoundingClientRect() : { left: anchor.x, top: anchor.y, bottom: anchor.y, width: 0 };
    const width = typeof window === 'undefined' ? 1200 : window.innerWidth;
    const x = Math.min(Math.max(rect.left + rect.width / 2, 168), Math.max(168, width - 168));
    const below = rect.top < 150;
    setTip({ owner, content, x, y: below ? rect.bottom + 8 : rect.top - 8, below });
  }, []);
  const hide = useCallback((owner?: string) => setTip(current => !owner || current?.owner === owner ? null : current), []);
  const api = useMemo(() => ({ show, hide, owner: tip?.owner ?? null }), [show, hide, tip?.owner]);
  const open = !!tip;
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setTip(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [open]);
  return <TipContext.Provider value={api}>
    {children}
    {tip && <div role="tooltip" id="ln-tip" className={`ln-tip${tip.below ? ' is-below' : ''}`} style={{ left: tip.x, top: tip.y }}>{tip.content}</div>}
  </TipContext.Provider>;
}

export const useTip = () => useContext(TipContext);

/** 마우스와 초점에 같은 동작(설명 표시·강조)을 건다. */
export function useHoverProps() {
  const tip = useTip();
  return useCallback((owner: string, content: () => ReactNode, onHover?: (on: boolean) => void) => ({
    onMouseEnter: (event: { currentTarget: Element }) => { tip.show(owner, event.currentTarget, content()); onHover?.(true); },
    onMouseLeave: () => { tip.hide(owner); onHover?.(false); },
    onFocus: (event: { currentTarget: Element }) => { tip.show(owner, event.currentTarget, content()); onHover?.(true); },
    onBlur: () => { tip.hide(owner); onHover?.(false); },
    'aria-describedby': tip.owner === owner ? 'ln-tip' : undefined,
  }), [tip]);
}
