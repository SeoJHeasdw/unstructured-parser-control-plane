import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

type Anchor = Element | { x: number; y: number };
type TipState = { owner: string; content: ReactNode; x: number; y: number; below: boolean } | null;
type TipApi = { show: (owner: string, anchor: Anchor, content: ReactNode, immediate?: boolean) => void; hide: (owner?: string, blur?: boolean) => void; owner: string | null };
const TipContext = createContext<TipApi>({ show: () => {}, hide: () => {}, owner: null });

/** 마우스를 올리거나 키보드 초점을 둔 항목의 짧은 설명. 클릭하면 상세 창에 고정된다. */
export function TipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pendingOwner = useRef<string | null>(null);
  const focused = useRef<string | null>(null);
  const clearTimer = useCallback(() => clearTimeout(timer.current), []);
  const show = useCallback((owner: string, anchor: Anchor, content: ReactNode, immediate = false) => {
    clearTimer();
    pendingOwner.current = owner;
    if (immediate) focused.current = owner;
    const rect = anchor instanceof Element ? anchor.getBoundingClientRect() : { left: anchor.x, top: anchor.y, bottom: anchor.y, width: 0 };
    const halfWidth = Math.min(168, window.innerWidth / 2);
    const x = Math.min(Math.max(rect.left + rect.width / 2, halfWidth), window.innerWidth - halfWidth);
    const below = rect.top < 150;
    const display = () => setTip({ owner, content, x, y: below ? rect.bottom + 8 : rect.top - 8, below });
    if (immediate) display();
    else {
      setTip(prev => prev?.owner === owner ? prev : null);
      timer.current = setTimeout(display, 400);
    }
  }, [clearTimer]);
  const hide = useCallback((owner?: string, blur = false) => {
    if (blur && focused.current === owner) focused.current = null;
    if (owner && (focused.current === owner || pendingOwner.current !== owner)) return;
    clearTimer();
    timer.current = setTimeout(() => setTip(null), 160);
  }, [clearTimer]);
  const api = useMemo(() => ({ show, hide, owner: tip?.owner ?? null }), [show, hide, tip?.owner]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { clearTimer(); pendingOwner.current = null; focused.current = null; setTip(null); }
    };
    window.addEventListener('keydown', close);
    return () => { window.removeEventListener('keydown', close); clearTimer(); };
  }, [clearTimer]);
  return <TipContext.Provider value={api}>
    {children}
    {tip && <div role="tooltip" id="ln-tip" onMouseEnter={clearTimer} onMouseLeave={() => hide(tip.owner)} className={`ln-tip${tip.below ? ' is-below' : ''}`} style={{ left: tip.x, top: tip.y }}>{tip.content}</div>}
  </TipContext.Provider>;
}

export const useTip = () => useContext(TipContext);

/** 마우스와 초점에 같은 동작(설명 표시·강조)을 건다. */
export function useHoverProps() {
  const tip = useTip();
  return useCallback((owner: string, content: () => ReactNode, onHover?: (on: boolean) => void) => ({
    onMouseEnter: (event: { currentTarget: Element }) => { tip.show(owner, event.currentTarget, content()); onHover?.(true); },
    onMouseLeave: () => { tip.hide(owner); onHover?.(false); },
    onFocus: (event: { currentTarget: Element }) => { tip.show(owner, event.currentTarget, content(), true); onHover?.(true); },
    onBlur: () => { tip.hide(owner, true); onHover?.(false); },
    'aria-describedby': tip.owner === owner ? 'ln-tip' : undefined,
  }), [tip]);
}
