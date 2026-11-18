import { useEffect, useId, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, CornerDownLeft, Search } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { Page } from './types';
import { Modal } from './ui';

export type WorkspaceDestination = {
  id: Page;
  label: string;
  description: string;
  group: string;
  icon: LucideIcon;
};

export function WorkspaceFinder({ destinations, current, onClose, onNavigate }: {
  destinations: WorkspaceDestination[];
  current: Page;
  onClose: () => void;
  onNavigate: (page: Page) => void;
}) {
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const terms = query.trim().toLocaleLowerCase().split(/\s+/);
  const matches = destinations.filter(page => {
    const text = `${page.label} ${page.group} ${page.description}`.toLocaleLowerCase();
    return terms.every(term => text.includes(term));
  });
  const highlighted = matches[index];
  const optionId = (id: Page) => `${listId}-${id}`;

  useEffect(() => {
    if (highlighted) document.getElementById(`${listId}-${highlighted.id}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [highlighted, listId]);

  return <Modal open onClose={onClose} title="화면 찾기" subtitle="화면 이름이나 작업을 검색해 바로 이동하세요." initialFocus={input}
    footer={<div className="finder-keys"><span><kbd><ArrowUp size={12}/></kbd><kbd><ArrowDown size={12}/></kbd> 선택</span><span><kbd><CornerDownLeft size={12}/></kbd> 열기</span><span><kbd>Esc</kbd> 닫기</span></div>}>
    <div className="finder-search">
      <Search size={19} aria-hidden="true" />
      <input ref={input} value={query} autoComplete="off" spellCheck={false} placeholder="예: 파일 업로드, 청킹, 모델" role="combobox" aria-label="화면 검색"
        aria-expanded="true" aria-controls={listId} aria-autocomplete="list" aria-activedescendant={highlighted && optionId(highlighted.id)}
        onChange={event => { setQuery(event.target.value); setIndex(0); }}
        onKeyDown={event => {
          if (!matches.length || event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const direction = event.key === 'ArrowDown' ? 1 : -1;
            setIndex((index + direction + matches.length) % matches.length);
          } else if (event.key === 'Enter' && highlighted) {
            event.preventDefault();
            onNavigate(highlighted.id);
          }
        }} />
    </div>
    <ul id={listId} role="listbox" aria-label="이동할 화면" className="finder-list">
      {matches.map(({ id, label, group, description, icon: Icon }, position) => <li key={id} id={optionId(id)} role="option"
        aria-selected={position === index} onMouseDown={event => event.preventDefault()} onClick={() => onNavigate(id)}>
        <span className="finder-icon"><Icon size={17} aria-hidden="true" /></span>
        <span className="finder-text"><strong>{label}</strong><small>{description}</small></span>
        <span className="finder-group">{id === current ? '현재 화면' : group}</span><ArrowRight size={15} aria-hidden="true" />
      </li>)}
    </ul>
    {!matches.length && <p className="finder-empty" role="status">일치하는 화면이 없습니다. 다른 검색어를 입력해 보세요.</p>}
  </Modal>;
}
