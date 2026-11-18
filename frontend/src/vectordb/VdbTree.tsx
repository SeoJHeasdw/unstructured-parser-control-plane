import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { ChevronRight, Database, Layers, Search, TriangleAlert, X } from 'lucide-react';
import type { CollectionNode, SourceKey, Tree } from '../api/vectordb';
import { fmtCount, fmtPct, loadLabel, PALETTE, useFloating, useStored } from './ui';

type Item = { id: string; level: 1 | 2 | 3; kind: 'db' | 'coll' | 'part'; db: string; coll?: CollectionNode; part?: string; rows?: number | null; color?: string; expandable: boolean; expanded: boolean; parent: string | null; setsize: number; pos: number; error?: string | null };
type Selection = { db: string; collection: string } | null;

/** 데이터베이스 → 컬렉션 → 파티션. 화살표로 이동, →/← 펼치기·접기, Enter로 선택. */
export default function VdbTree({ source, tree, selected, partition, onSelect }: { source: SourceKey; tree: Tree; selected: Selection; partition: string | null; onSelect: (db: string, collection: string, partition: string | null) => void }) {
  const [toggled, setToggled] = useStored<string[]>(`tree.${source}`, []);
  const [query, setQuery] = useState('');
  const [focusId, setFocusId] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLDivElement>());
  const pending = useRef<string | null>(null);
  const tip = useFloating();
  const q = query.trim().toLowerCase();

  const items = useMemo(() => {
    const flipped = new Set(toggled);
    const isOpen = (id: string, fallback: boolean) => flipped.has(id) ? !fallback : fallback;
    const out: Item[] = [];
    tree.databases.forEach((db, di) => {
      const colls = q && !db.name.toLowerCase().includes(q) ? db.collections.filter(c => c.name.toLowerCase().includes(q)) : db.collections;
      if (q && !colls.length) return;
      const dbId = `db:${db.name}`;
      const dbOpen = q ? true : isOpen(dbId, true);
      out.push({ id: dbId, level: 1, kind: 'db', db: db.name, expandable: db.collections.length > 0, expanded: dbOpen, parent: null, setsize: tree.databases.length, pos: di + 1, rows: db.collections.length, error: db.error });
      if (!dbOpen) return;
      colls.forEach((coll, ci) => {
        const cId = `c:${db.name}/${coll.name}`;
        const current = selected?.db === db.name && selected.collection === coll.name;
        const cOpen = isOpen(cId, current);
        out.push({ id: cId, level: 2, kind: 'coll', db: db.name, coll, expandable: coll.partitions.length > 0, expanded: cOpen, parent: dbId, setsize: colls.length, pos: ci + 1, rows: coll.row_count, error: coll.error });
        if (!cOpen) return;
        coll.partitions.forEach((p, pi) => out.push({ id: `p:${db.name}/${coll.name}/${p.name}`, level: 3, kind: 'part', db: db.name, coll, part: p.name, rows: p.row_count, color: PALETTE[pi % PALETTE.length], expandable: false, expanded: false, parent: cId, setsize: coll.partitions.length, pos: pi + 1, error: p.error }));
      });
    });
    return out;
  }, [tree, toggled, selected, q]);

  useEffect(() => {
    if (pending.current) { refs.current.get(pending.current)?.focus(); pending.current = null; }
  }, [items]);

  const selectedId = selected ? (partition ? `p:${selected.db}/${selected.collection}/${partition}` : `c:${selected.db}/${selected.collection}`) : null;
  const tabbable = items.some(i => i.id === focusId) ? focusId : items.some(i => i.id === selectedId) ? selectedId : items[0]?.id;
  const toggle = (item: Item) => {
    const set = new Set(toggled);
    if (set.has(item.id)) set.delete(item.id); else set.add(item.id);
    setToggled([...set]);
  };
  const activate = (item: Item) => {
    if (item.kind === 'db') toggle(item);
    else if (item.coll) onSelect(item.db, item.coll.name, item.kind === 'part' ? item.part ?? null : null);
  };
  const move = (id: string | undefined) => {
    if (!id) return;
    setFocusId(id); pending.current = id;
    refs.current.get(id)?.focus();
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>, item: Item, index: number) => {
    const key = event.key;
    if (key === 'ArrowDown') move(items[index + 1]?.id);
    else if (key === 'ArrowUp') move(items[index - 1]?.id);
    else if (key === 'Home') move(items[0]?.id);
    else if (key === 'End') move(items[items.length - 1]?.id);
    else if (key === 'ArrowRight') { if (item.expandable && !item.expanded) toggle(item); else if (item.expanded) move(items[index + 1]?.id); }
    else if (key === 'ArrowLeft') { if (item.expanded) toggle(item); else if (item.parent) move(item.parent); }
    else if (key === 'Enter' || key === ' ') activate(item);
    else if (key === 'Escape') { tip.hide(); return; }
    else return;
    event.preventDefault();
  };

  return <div className="vdb-tree-wrap">
    <div className="vdb-tree-head"><Layers size={17} aria-hidden="true" /><h2>컬렉션 탐색</h2></div>
    <div className="vdb-tree-search"><Search size={16} aria-hidden="true" />
      <input value={query} onChange={event => setQuery(event.target.value)} placeholder="DB 또는 컬렉션 검색" aria-label="데이터베이스 또는 컬렉션 검색" />
      {query && <button type="button" className="plain-icon" onClick={() => setQuery('')} aria-label="검색 지우기"><X size={15} aria-hidden="true" /></button>}
    </div>
    <div className="vdb-tree" role="tree" aria-label="데이터베이스, 컬렉션, 파티션">
      {items.map((item, index) => {
        const isSelected = item.id === selectedId;
        const current = item.kind === 'coll' && selected?.db === item.db && selected.collection === item.coll?.name;
        const share = item.kind === 'part' && item.coll?.row_count ? (item.rows ?? 0) / item.coll.row_count : 0;
        const tipBind = item.kind === 'part' ? tip.bind(item.id, () => <><b>{item.part}</b><span>{fmtCount(item.rows)}행 · 컬렉션의 {fmtPct(item.rows ?? 0, item.coll?.row_count ?? 0)}</span>{item.error && <span className="is-error">{item.error}</span>}</>)
          : item.kind === 'coll' && item.coll ? tip.bind(item.id, () => <><b>{item.coll!.name}</b><span>{fmtCount(item.rows)}행 · 파티션 {item.coll!.partitions.length}개 · {loadLabel(item.coll!.load_state)}</span>{item.coll!.dim && <span>벡터 {item.coll!.dim}차원{item.coll!.metric ? ` · ${item.coll!.metric}` : ''}</span>}{item.error && <span className="is-error">{item.error}</span>}</>, 'tip', 350) : null;
        return <div key={item.id} ref={el => { if (el) refs.current.set(item.id, el); else refs.current.delete(item.id); }}
          role="treeitem" aria-level={item.level} aria-setsize={item.setsize} aria-posinset={item.pos} aria-expanded={item.expandable ? item.expanded : undefined} aria-selected={isSelected}
          tabIndex={item.id === tabbable ? 0 : -1} className={`vdb-ti is-${item.kind} ${isSelected ? 'is-selected' : ''} ${current ? 'is-current' : ''}`} style={{ '--vdb-level': item.level } as CSSProperties}
          onClick={() => { setFocusId(item.id); activate(item); }} onKeyDown={event => onKey(event, item, index)}
          onMouseEnter={tipBind?.onMouseEnter} onMouseLeave={tipBind?.onMouseLeave} onBlur={tipBind?.onBlur} aria-describedby={tipBind?.['aria-describedby']}
          onFocus={event => { setFocusId(item.id); tipBind?.onFocus(event); }}>
          <span className="vdb-ti-chev" aria-hidden onClick={event => { if (item.expandable && item.kind !== 'db') { event.stopPropagation(); toggle(item); } }}>{item.expandable && <ChevronRight size={13} className={item.expanded ? 'is-open' : ''} />}</span>
          {item.kind === 'db' && <><Database size={14} className="vdb-ti-icon" aria-hidden /><span className="vdb-ti-name" title={item.db}>{item.db}</span><span className="vdb-ti-meta">{item.rows ? `컬렉션 ${item.rows}` : '컬렉션 없음'}</span></>}
          {item.kind === 'coll' && item.coll && <><Layers size={14} className="vdb-ti-icon" aria-hidden /><span className="vdb-ti-name" title={item.coll.name}>{item.coll.name}</span>
            {item.coll.dim && <span className="vdb-dim">{item.coll.dim}d</span>}<span className="vdb-ti-meta">{fmtCount(item.rows)}</span>
            <i className={`vdb-load ${item.coll.load_state === 'LoadStateLoaded' ? 'is-on' : ''}`} aria-label={loadLabel(item.coll.load_state)} /></>}
          {item.kind === 'part' && <><i className="vdb-swatch" style={{ background: item.color }} aria-hidden /><span className="vdb-ti-name" title={item.part}>{item.part}</span>
            <span className="vdb-ti-bar" aria-hidden><i style={{ width: `${Math.max(share * 100, item.rows ? 3 : 0)}%`, background: item.color }} /></span><span className="vdb-ti-meta">{fmtCount(item.rows)}</span></>}
          {item.error && <TriangleAlert size={13} className="vdb-ti-warn" aria-label="일부 정보를 읽지 못함" />}
        </div>;
      })}
      {!items.length && <p className="vdb-empty">{q ? '일치하는 데이터베이스나 컬렉션이 없습니다.' : '컬렉션이 없습니다.'}</p>}
    </div>
    {tip.layer}
  </div>;
}
