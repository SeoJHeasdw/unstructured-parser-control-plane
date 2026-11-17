import { Fragment, useEffect, useId, useRef } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import './ui.css';

type Props<T> = {
  items: T[];
  getKey: (item: T) => string;
  value: string | null;
  onChange: (key: string) => void;
  render: (item: T, state: { selected: boolean }) => ReactNode;
  /** 화면 낭독기용 이름 */
  label: string;
  /** 같은 값이 이어지는 항목을 묶어 머리를 붙인다(원문 순서 유지). */
  groupBy?: (item: T) => string;
  empty?: ReactNode;
  className?: string;
};

/** 목록에서 하나를 고른다. ↑/↓·Home/End로 옮기면 바로 선택되고, 고른 항목이 보이도록 스크롤한다. */
export function ListBox<T>({ items, getKey, value, onChange, render, label, groupBy, empty, className = '' }: Props<T>) {
  const base = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const optionId = (key: string) => `${base}-opt-${key.replace(/[^\w-]/g, '_')}`;
  const index = items.findIndex(item => getKey(item) === value);

  useEffect(() => {
    if (value === null) return;
    const el = document.getElementById(optionId(value));
    el?.scrollIntoView?.({ block: 'nearest' });
    // value가 바뀔 때만 따라간다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (!items.length) return;
    let next = -1;
    if (event.key === 'ArrowDown') next = Math.min(items.length - 1, index + 1);
    else if (event.key === 'ArrowUp') next = Math.max(0, index < 0 ? 0 : index - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = items.length - 1;
    else if (event.key === 'PageDown') next = Math.min(items.length - 1, index + 10);
    else if (event.key === 'PageUp') next = Math.max(0, index - 10);
    if (next < 0) return;
    event.preventDefault();
    onChange(getKey(items[next]));
  };

  if (!items.length) return <div className={`ui-listbox ${className}`}>{empty ?? <div className="ui-listbox-empty">항목이 없습니다.</div>}</div>;

  let lastGroup: string | null = null;
  return <ul ref={listRef} className={`ui-listbox ${className}`} role="listbox" aria-label={label} tabIndex={0}
    aria-activedescendant={value !== null && index >= 0 ? optionId(value) : undefined} onKeyDown={onKeyDown}>
    {items.map(item => {
      const key = getKey(item);
      const selected = key === value;
      const group = groupBy?.(item) ?? null;
      const header = group !== null && group !== lastGroup;
      lastGroup = group;
      return <Fragment key={key}>
        {header && <li className="ui-listbox-group" role="presentation">{group}</li>}
        <li id={optionId(key)} role="option" aria-selected={selected} className={'ui-option' + (selected ? ' is-active' : '')}
          onMouseDown={event => event.preventDefault()} onClick={() => { onChange(key); listRef.current?.focus(); }}>
          {render(item, { selected })}
        </li>
      </Fragment>;
    })}
  </ul>;
}
