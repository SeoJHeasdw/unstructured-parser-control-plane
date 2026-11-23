import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import './ui.css';
import { Check, ChevronDown } from 'lucide-react';
import { usePresence } from './usePresence';

export type HoverMenuItem = {
  id: string; label: string; hint?: string; icon?: ReactNode;
  /** 접근 가능한 이름. 비우면 label. */
  name?: string;
  /** 값이 있으면 하나를 고르는 항목(menuitemradio)으로 그리고 현재 값에 체크를 단다. */
  checked?: boolean;
  onSelect: () => void;
};
type Props = { label: string; icon: ReactNode; items: HoverMenuItem[]; className?: string; triggerClassName?: string; labelClassName?: string };

const OPEN_DELAY = 90;
const CLOSE_DELAY = 220;

/**
 * 마우스를 올리면 펼쳐지고 벗어나면 접히는 작은 메뉴. 누르면 고정되고, 키보드(Enter·↓)로도 연다.
 * 자주 쓰지 않는 같은 종류의 동작 여러 개를 버튼 하나 뒤로 모을 때 쓴다.
 */
export function HoverMenu({ label, icon, items, className = '', triggerClassName = '', labelClassName }: Props) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const timer = useRef(0);
  const focusOnOpen = useRef<'first' | 'last' | null>(null);
  const presence = usePresence(open, 120);
  const id = useId();

  const clear = () => window.clearTimeout(timer.current);
  const openMenu = (pin: boolean, focus: 'first' | 'last' | null = null) => {
    clear();
    focusOnOpen.current = focus;
    setOpen(true);
    if (pin) setPinned(true);
  };
  const close = (returnFocus = false) => {
    clear(); setOpen(false); setPinned(false);
    if (returnFocus) trigger.current?.focus();
  };
  const hoverIn = (event: ReactPointerEvent) => {
    if (event.pointerType === 'touch') return;
    clear();
    if (!open) timer.current = window.setTimeout(() => openMenu(false), OPEN_DELAY);
  };
  const hoverOut = (event: ReactPointerEvent) => {
    if (event.pointerType === 'touch' || pinned) return;
    clear();
    timer.current = window.setTimeout(() => close(), CLOSE_DELAY);
  };

  useEffect(() => clear, []);
  /* 고정된 메뉴는 바깥을 누르거나 화면이 움직이면 접는다. */
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) close();
    };
    const away = (event: Event) => { if (!menu.current?.contains(event.target as Node)) close(); };
    document.addEventListener('pointerdown', outside, true);
    window.addEventListener('scroll', away, true);
    window.addEventListener('resize', away);
    return () => { document.removeEventListener('pointerdown', outside, true); window.removeEventListener('scroll', away, true); window.removeEventListener('resize', away); };
  }, [open]);
  /* 버튼 아래에 띄우고, 오른쪽이 모자라면 버튼 오른쪽 끝에 맞춘다. */
  useLayoutEffect(() => {
    if (!presence.mounted || !trigger.current || !menu.current) return;
    const r = trigger.current.getBoundingClientRect();
    const w = menu.current.offsetWidth;
    const x = r.left + w > window.innerWidth - 8 ? Math.max(8, r.right - w) : r.left;
    setPos({ x: Math.round(x), y: Math.round(r.bottom + 6) });
  }, [presence.mounted, open]);
  useEffect(() => {
    if (!open || !focusOnOpen.current || !menu.current) return;
    const buttons = [...menu.current.querySelectorAll<HTMLButtonElement>('[role^=menuitem]')];
    const checked = buttons.find(button => button.getAttribute('aria-checked') === 'true');
    (focusOnOpen.current === 'last' ? buttons.at(-1) : checked ?? buttons[0])?.focus();
    focusOnOpen.current = null;
  }, [open, presence.mounted]);

  const onTriggerKey = (event: ReactKeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      openMenu(true, event.key === 'ArrowUp' ? 'last' : 'first');
    }
  };
  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return; }
    if (event.key === 'Tab') { close(); return; }
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role^=menuitem]')];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  };

  return <span className={`ui-hover-menu ${className}`} onPointerEnter={hoverIn} onPointerLeave={hoverOut}>
    <button ref={trigger} type="button" className={`ui-hover-trigger ${triggerClassName}${open ? ' is-open' : ''}`} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={event => open && pinned ? close() : openMenu(true, event.detail === 0 ? 'first' : null)} onKeyDown={onTriggerKey}>
      {icon}<span className={labelClassName}>{label}</span><ChevronDown className="ui-hover-chevron" size={13} aria-hidden="true" />
    </button>
    {presence.mounted && createPortal(<div ref={menu} id={id} role="menu" aria-label={label} aria-hidden={!open || undefined}
      className={'ui-menu' + (presence.shown && pos ? ' is-open' : '')} style={pos ? { left: pos.x, top: pos.y } : { left: 0, top: 0, visibility: 'hidden' }}
      onPointerEnter={hoverIn} onPointerLeave={hoverOut} onKeyDown={onMenuKey}>
      {items.map(item => <button key={item.id} type="button" role={item.checked === undefined ? 'menuitem' : 'menuitemradio'} aria-checked={item.checked}
        aria-label={item.name} tabIndex={-1} className={item.checked ? 'is-checked' : undefined}
        onClick={() => { item.onSelect(); close(true); }}>
        {item.icon && <span className="ui-menu-icon" aria-hidden="true">{item.icon}</span>}
        <span className="ui-menu-text"><b>{item.label}</b>{item.hint && <small>{item.hint}</small>}</span>
        {item.checked !== undefined && <Check className="ui-menu-check" size={15} aria-hidden="true" />}
      </button>)}
    </div>, document.body)}
  </span>;
}
