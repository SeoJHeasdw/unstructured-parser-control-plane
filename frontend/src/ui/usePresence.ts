import { useEffect, useState } from 'react';

const raf = (callback: () => void) => typeof requestAnimationFrame === 'function' ? requestAnimationFrame(callback) : window.setTimeout(callback, 16);
const cancelRaf = (id: number) => typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame(id) : window.clearTimeout(id);
export const prefersReducedMotion = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * 열고 닫을 때 전환이 보이도록 마운트 시점을 늦춘다.
 * mounted: DOM에 둘지, shown: 열린 모양(클래스)으로 그릴지. 닫히는 동안에도 mounted는 exitMs만큼 유지된다.
 * 접근성·조작은 shown이 아니라 원래 open 값으로 판단한다.
 */
export function usePresence(open: boolean, exitMs: number) {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      // 닫힌 모양을 한 프레임 그린 다음 열린 모양으로 바꿔야 전환이 실행된다.
      let inner = 0;
      const outer = raf(() => { inner = raf(() => setShown(true)); });
      return () => { cancelRaf(outer); cancelRaf(inner); };
    }
    setShown(false);
    const timer = window.setTimeout(() => setMounted(false), prefersReducedMotion() ? 0 : exitMs);
    return () => window.clearTimeout(timer);
  }, [open, exitMs]);
  return { mounted: open || mounted, shown: open && shown };
}
