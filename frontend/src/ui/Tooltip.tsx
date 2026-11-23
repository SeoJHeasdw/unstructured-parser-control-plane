import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './ui.css';

type Side = 'top' | 'bottom' | 'left' | 'right';
type Tip = { el: HTMLElement; text: string; keys?: string; side: Side; n: number };
type Shown = { tip: Tip; open: boolean; glide: boolean };

const SHOW_DELAY = 400;
const WARM_MS = 600;
const HIDE_GRACE = 80;
const GAP = 8;
const EDGE = 8;
const SIDES: Side[] = ['top', 'bottom', 'left', 'right'];
const OPPOSITE: Record<Side, Side> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
/** 운영체제에 맞는 단축키 표기. modKey('Z', true) → ⇧⌘Z / Ctrl+Shift+Z */
export const modKey = (key: string, shift = false) => isMac ? `${shift ? '⇧' : ''}⌘${key}` : `Ctrl+${shift ? 'Shift+' : ''}${key}`;

const targetOf = (node: EventTarget | null) => node instanceof Element ? node.closest<HTMLElement>('[data-tip]') : null;
const focusVisible = (el: Element) => { try { return el.matches(':focus-visible'); } catch { return false; } };
/* data-tip-overflow: 글자가 말줄임으로 잘렸을 때만 전체를 보여 준다(다 보이면 같은 말을 또 띄우지 않는다). */
const overflows = (el: Element) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
/* 가운데 말줄임처럼 안쪽 요소가 잘리는 경우도 잘린 것으로 본다. */
const clipped = (el: HTMLElement) => overflows(el) || [...el.querySelectorAll(':scope > *')].some(overflows);
const read = (el: HTMLElement, n: number): Tip | null => {
  const text = el.dataset.tip?.trim();
  if (!text || (el.hasAttribute('data-tip-overflow') && !clipped(el))) return null;
  const side = SIDES.includes(el.dataset.tipSide as Side) ? el.dataset.tipSide as Side : 'bottom';
  return { el, text, keys: el.dataset.tipKey || undefined, side, n };
};

/**
 * data-tip을 단 요소에 짧은 이름과 단축키를 띄우는 공통 툴팁. 앱에 한 번만 둔다.
 * 마우스는 400ms 머물 때, 키보드는 초점이 오면 바로 보인다. 한 번 뜬 뒤 옆 버튼으로 옮기면 기다리지 않고 미끄러지듯 옮겨 간다.
 * Esc·클릭으로 닫으면 포인터가 그 요소를 벗어날 때까지 다시 열지 않는다. 터치에서는 띄우지 않는다.
 * 사용: <button aria-label="되돌리기" data-tip="되돌리기" data-tip-key={modKey('Z')} data-tip-side="right">
 *       <b className="ellipsis" data-tip={name} data-tip-overflow>{name}</b>  ← 잘렸을 때만
 */
export function TooltipLayer() {
  const [shown, setShown] = useState<Shown | null>(null);
  const [place, setPlace] = useState<{ x: number; y: number; side: Side } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current: HTMLElement | null = null;
    let open = false;
    let suppressed: HTMLElement | null = null;
    let lastClosed = 0, n = 0, showTimer = 0, hideTimer = 0;
    let observer: MutationObserver | null = null;
    let described: { el: HTMLElement; prev: string | null } | null = null;

    const undescribe = () => {
      if (!described) return;
      if (described.prev) described.el.setAttribute('aria-describedby', described.prev); else described.el.removeAttribute('aria-describedby');
      described = null;
    };
    /* 툴팁 글이 접근 가능한 이름과 다를 때만 설명으로 연결한다(같은 말을 두 번 읽지 않게). */
    const describe = (tip: Tip) => {
      undescribe();
      const name = tip.el.getAttribute('aria-label') ?? tip.el.textContent?.trim();
      if (name === tip.text) return;
      const prev = tip.el.getAttribute('aria-describedby');
      described = { el: tip.el, prev };
      tip.el.setAttribute('aria-describedby', prev ? `${prev} ui-tip` : 'ui-tip');
    };
    const unwatch = () => { observer?.disconnect(); observer = null; };
    /* 떠 있는 동안 대상이 사라지거나 문구가 바뀌면 따라간다. */
    const watch = (el: HTMLElement) => {
      unwatch();
      if (typeof MutationObserver === 'undefined') return;
      observer = new MutationObserver(() => {
        const next = el.isConnected ? read(el, n) : null;
        if (!next) { hide(); return; }
        setShown(prev => prev && prev.tip.el === el && (prev.tip.text !== next.text || prev.tip.keys !== next.keys || prev.tip.side !== next.side) ? { ...prev, tip: { ...next, n: ++n } } : prev);
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-tip', 'data-tip-key', 'data-tip-side'] });
    };
    const show = (el: HTMLElement, immediate: boolean) => {
      window.clearTimeout(showTimer); window.clearTimeout(hideTimer);
      current = el;
      const run = () => {
        if (current !== el || !el.isConnected) return;
        const tip = read(el, ++n);
        if (!tip) return;
        const glide = open;
        open = true;
        setShown({ tip, open: true, glide });
        watch(el); describe(tip);
      };
      if (immediate || open || Date.now() - lastClosed < WARM_MS) run();
      else showTimer = window.setTimeout(run, SHOW_DELAY);
    };
    const hide = (delay = 0) => {
      window.clearTimeout(showTimer); window.clearTimeout(hideTimer);
      const run = () => {
        current = null;
        if (open) { open = false; lastClosed = Date.now(); }
        unwatch(); undescribe();
        setShown(prev => prev && { ...prev, open: false });
      };
      if (delay) hideTimer = window.setTimeout(run, delay); else run();
    };

    const onOver = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      if (box.current?.contains(event.target as Node)) { window.clearTimeout(hideTimer); return; }
      const el = targetOf(event.target);
      if (!el) { if (current) hide(HIDE_GRACE); return; }
      if (el === current && open) { window.clearTimeout(hideTimer); return; }
      if (el === suppressed) return;
      show(el, false);
    };
    const onOut = (event: PointerEvent) => {
      const from = targetOf(event.target);
      if (!from || from === targetOf(event.relatedTarget)) return;
      if (from === suppressed) suppressed = null;
      if (from === current && !box.current?.contains(event.relatedTarget as Node)) hide(HIDE_GRACE);
    };
    const onFocusIn = (event: FocusEvent) => {
      const el = targetOf(event.target);
      if (el && el !== suppressed && focusVisible(event.target as Element)) show(el, true);
    };
    const onFocusOut = (event: FocusEvent) => {
      const el = targetOf(event.target);
      if (el === suppressed) suppressed = null;
      if (el && el === current) hide();
    };
    const onDown = (event: PointerEvent) => {
      if (!current || box.current?.contains(event.target as Node)) return;
      const el = targetOf(event.target);
      suppressed = el;
      hide();
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && current) { suppressed = current; hide(); } };
    const onScroll = () => { if (current) hide(); };

    document.addEventListener('pointerover', onOver);
    document.addEventListener('pointerout', onOut);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.clearTimeout(showTimer); window.clearTimeout(hideTimer); unwatch(); undescribe();
      document.removeEventListener('pointerover', onOver);
      document.removeEventListener('pointerout', onOut);
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', onFocusOut);
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  /* 닫힌 뒤 사라지는 전환이 끝나면 DOM에서 뺀다. */
  useEffect(() => {
    if (!shown || shown.open) return;
    const timer = window.setTimeout(() => { setShown(prev => prev && !prev.open ? null : prev); setPlace(null); }, 140);
    return () => window.clearTimeout(timer);
  }, [shown]);

  /* 원하는 쪽에 자리가 없으면 반대쪽으로 뒤집고, 창 가장자리 안쪽으로 붙인다. */
  useLayoutEffect(() => {
    const el = box.current;
    if (!shown?.tip || !el) return;
    const a = shown.tip.el.getBoundingClientRect();
    const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    const fits = (side: Side) => side === 'top' ? a.top - GAP - h >= EDGE : side === 'bottom' ? a.bottom + GAP + h <= vh - EDGE
      : side === 'left' ? a.left - GAP - w >= EDGE : a.right + GAP + w <= vw - EDGE;
    const want = shown.tip.side;
    const side = fits(want) || !fits(OPPOSITE[want]) ? want : OPPOSITE[want];
    let x: number, y: number;
    if (side === 'top' || side === 'bottom') { x = a.left + a.width / 2 - w / 2; y = side === 'top' ? a.top - GAP - h : a.bottom + GAP; }
    else { y = a.top + a.height / 2 - h / 2; x = side === 'left' ? a.left - GAP - w : a.right + GAP; }
    x = Math.min(Math.max(x, EDGE), Math.max(EDGE, vw - EDGE - w));
    y = Math.min(Math.max(y, EDGE), Math.max(EDGE, vh - EDGE - h));
    setPlace({ x: Math.round(x), y: Math.round(y), side });
  }, [shown?.tip]);

  if (!shown) return null;
  const { tip, open, glide } = shown;
  return createPortal(<div ref={box} id="ui-tip" role="tooltip"
    className={`ui-tip is-${place?.side ?? tip.side}${open && place ? ' is-open' : ''}${glide ? ' is-glide' : ''}`}
    style={place ? { left: place.x, top: place.y } : { left: 0, top: 0, visibility: 'hidden' }}>
    <span>{tip.text}</span>{tip.keys && <kbd>{tip.keys}</kbd>}
  </div>, document.body);
}
