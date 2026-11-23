import { useCallback, useEffect, useRef, useState } from 'react';

/** Fullscreen the document so dialogs and canvas menus portaled to body stay visible. */
export function useFlowFullscreen(enabled: boolean) {
  const [expanded, setExpanded] = useState(false);
  const wanted = useRef(false);
  const ownsNative = useRef(false);
  const leave = useCallback(() => {
    wanted.current = false;
    setExpanded(false);
    if (ownsNative.current && document.fullscreenElement === document.documentElement) {
      void document.exitFullscreen().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const changed = () => {
      if (!ownsNative.current) return;
      if (document.fullscreenElement !== document.documentElement) {
        ownsNative.current = false;
        wanted.current = false;
        setExpanded(false);
      } else if (!wanted.current) leave();
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, [leave]);
  useEffect(() => { if (!enabled) leave(); }, [enabled, leave]);
  useEffect(() => () => { wanted.current = false; if (ownsNative.current && document.fullscreenElement === document.documentElement) void document.exitFullscreen().catch(() => {}); }, []);
  useEffect(() => {
    if (!expanded || !enabled) return;
    const escape = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.isComposing || e.defaultPrevented || document.querySelector('[aria-modal="true"], .ps-insert-menu')) return;
      e.preventDefault();
      leave();
    };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [expanded, enabled, leave]);

  function toggle() {
    if (wanted.current) { leave(); return; }
    if (!enabled) return;
    wanted.current = true;
    setExpanded(true);
    if (document.fullscreenEnabled && !document.fullscreenElement && document.documentElement.requestFullscreen) {
      ownsNative.current = true;
      void document.documentElement.requestFullscreen().then(() => {
        if (!wanted.current && document.fullscreenElement === document.documentElement) leave();
      }).catch(() => { ownsNative.current = false; }); // Embedded browsers can still use the full app viewport.
    }
  }
  return {expanded: enabled && expanded, toggle};
}
