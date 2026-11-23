import { useId, useRef } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import './ui.css';

export type TabItem<T extends string = string> = { id: T; label: ReactNode; badge?: ReactNode; disabled?: boolean };

type Props<T extends string> = {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** 화면 낭독기용 이름 */
  label: string;
  variant?: 'line' | 'boxed';
  /** 선택된 탭의 내용. 없으면 탭 줄만 그린다(팝업 머리 등). */
  children?: (active: T) => ReactNode;
  className?: string;
};

/** 관점 전환용 탭. ←/→·Home/End로 옮기고, 옮기면 바로 선택된다. */
export function Tabs<T extends string>({ items, value, onChange, label, variant = 'line', children, className = '' }: Props<T>) {
  const base = useId();
  const refs = useRef(new Map<T, HTMLButtonElement>());
  const enabled = items.filter(item => !item.disabled);
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = enabled.findIndex(item => item.id === value);
    let next = -1;
    if (event.key === 'ArrowRight') next = (index + 1) % enabled.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + enabled.length) % enabled.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = enabled.length - 1;
    if (next < 0) return;
    event.preventDefault();
    const id = enabled[next].id;
    onChange(id);
    refs.current.get(id)?.focus();
  };
  return <>
    <div className={`ui-tabs is-${variant} ${className}`} role="tablist" aria-label={label} onKeyDown={move}>
      {items.map(item => {
        const selected = item.id === value;
        return <button key={item.id} ref={el => { if (el) refs.current.set(item.id, el); else refs.current.delete(item.id); }}
          type="button" role="tab" className="ui-tab" id={`${base}-tab-${item.id}`} aria-selected={selected} aria-controls={children ? `${base}-panel` : undefined}
          tabIndex={selected ? 0 : -1} disabled={item.disabled} onClick={() => onChange(item.id)}>
          {item.label}{item.badge !== undefined && item.badge !== null && <span className="ui-tab-badge">{item.badge}</span>}
        </button>;
      })}
    </div>
    {children && <div key={value} className="ui-tabpanel" role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${value}`} tabIndex={0}>{children(value)}</div>}
  </>;
}

type SegProps<T extends string> = { options: { id: T; label: ReactNode }[]; value: T; onChange: (id: T) => void; label: string; className?: string };

/** 같은 내용을 다른 기준으로 보는 짧은 선택(지표·단위 등). */
export function Segmented<T extends string>({ options, value, onChange, label, className = '' }: SegProps<T>) {
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = options.findIndex(option => option.id === value);
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = options[(index + step + options.length) % options.length];
    onChange(next.id);
    [...event.currentTarget.querySelectorAll<HTMLElement>('[data-id]')].find(el => el.dataset.id === next.id)?.focus();
  };
  return <div className={`ui-seg ${className}`} role="radiogroup" aria-label={label} onKeyDown={move}>
    {options.map(option => <button key={option.id} type="button" role="radio" data-id={option.id} aria-checked={option.id === value}
      tabIndex={option.id === value ? 0 : -1} onClick={() => onChange(option.id)}>{option.label}</button>)}
  </div>;
}
