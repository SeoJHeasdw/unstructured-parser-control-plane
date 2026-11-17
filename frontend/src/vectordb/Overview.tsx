import { useState, type CSSProperties } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { CollectionNode, PartitionNode, Tree } from '../api/vectordb';
import { Modal } from '../ui';
import type { PartRef } from './PartitionModal';
import { fmtCount, fmtPct, loadLabel, PALETTE, useFloating } from './ui';

const SHOW = 8;
type Part = PartitionNode & { color: string };
type Tip = ReturnType<typeof useFloating>;

/** 많은 순, 빈 파티션·읽지 못한 파티션은 뒤로. 색은 트리와 같은(원래 순서) 색. */
function sortParts(coll: CollectionNode): Part[] {
  const parts = coll.partitions.map((p, i) => ({ ...p, color: PALETTE[i % PALETTE.length] }));
  const live = (p: Part) => !p.error && (p.row_count ?? 0) > 0;
  return [...parts.filter(live).sort((a, b) => (b.row_count ?? 0) - (a.row_count ?? 0)), ...parts.filter(p => !live(p))];
}

/** 개요: 컬렉션마다 파티션 타일. 타일을 누르면 파티션 팝업을 연다. */
export default function Overview({ tree, onOpen }: { tree: Tree; onOpen: (part: PartRef) => void }) {
  const tip = useFloating();
  const [more, setMore] = useState<{ db: string; coll: CollectionNode } | null>(null);
  const sections = tree.databases.flatMap(db => db.collections.map(coll => ({ db: db.name, coll })));
  const bare = tree.databases.filter(db => !db.collections.length);
  const open = (db: string, coll: CollectionNode, p: PartitionNode) => onOpen({ db, collection: coll.name, partition: p.name, rows: p.row_count });

  return <div className="panel vdb-ov">
    {sections.map(({ db, coll }) => {
      const parts = sortParts(coll);
      const shown = parts.length > SHOW ? parts.slice(0, SHOW - 1) : parts;
      const rest = parts.slice(shown.length);
      const loaded = coll.load_state === 'LoadStateLoaded';
      return <section key={`${db}/${coll.name}`} className="vdb-ov-sec" aria-labelledby={`vdb-ov-${db}-${coll.name}`}>
        <header className="vdb-ov-head">
          <h3 id={`vdb-ov-${db}-${coll.name}`}>{coll.name}</h3>
          <span className="vdb-ov-db">{db}</span>
          <span className="vdb-toolbar-gap" />
          <span className="vdb-ov-fact">청크 <b className="ui-num">{fmtCount(coll.row_count)}</b></span>
          {coll.dim && <span className="vdb-ov-fact"><b className="ui-num">{fmtCount(coll.dim)}</b>차원{coll.metric ? ` · ${coll.metric}` : ''}</span>}
          <span className={`ui-pill ${loaded ? 'is-ok' : 'is-warn'}`}>{loadLabel(coll.load_state)}</span>
        </header>
        {coll.error && <p className="vdb-ov-err"><TriangleAlert size={14} aria-hidden /> {coll.error}</p>}
        {parts.length ? <div className="vdb-tiles" role="list" aria-label={`${coll.name} 파티션`}>
          {shown.map(p => <div role="listitem" key={p.name}><Tile part={p} total={coll.row_count ?? 0} tip={tip} tipKey={`${db}/${coll.name}/${p.name}`} onOpen={() => open(db, coll, p)} /></div>)}
          {rest.length > 0 && <div role="listitem"><MoreTile parts={rest} total={coll.row_count ?? 0} onOpen={() => { tip.hide(); setMore({ db, coll }); }} /></div>}
        </div> : !coll.error && <p className="vdb-ov-none">파티션 정보가 없습니다.</p>}
      </section>;
    })}
    {!sections.length && <p className="ui-empty"><b>컬렉션이 없습니다</b></p>}
    {bare.length > 0 && <p className="vdb-ov-none">{bare.map(db => db.name).join(', ')} · 컬렉션 없음</p>}
    {tip.layer}
    {more && <MoreModal db={more.db} coll={more.coll} onClose={() => setMore(null)} onPick={p => { setMore(null); open(more.db, more.coll, p); }} />}
  </div>;
}

function Tile({ part, total, tip, tipKey, onOpen }: { part: Part; total: number; tip: Tip; tipKey: string; onOpen: () => void }) {
  const rows = part.row_count;
  const share = total > 0 && rows ? rows / total : 0;
  const style = { '--c': part.color } as CSSProperties;
  const body = <>
    <span className="vdb-tile-name"><i className="vdb-swatch" aria-hidden /><span>{part.name}</span>{part.error && <TriangleAlert size={14} className="vdb-tile-warn" aria-label="읽지 못함" />}</span>
    <span className="vdb-tile-count ui-num">{fmtCount(rows)}</span>
    <span className="vdb-tile-bar" aria-hidden><i style={{ width: `${Math.max(share * 100, share ? 2 : 0)}%` }} /></span>
  </>;
  if (rows === 0 && !part.error) return <div className="vdb-tile is-muted is-empty" style={style}>{body}</div>;
  const binding = tip.bind(tipKey, () => part.error
    ? <><b>읽지 못했습니다</b><span className="is-error">{part.error}</span></>
    : <span>컬렉션 청크의 {fmtPct(rows ?? 0, total)}</span>);
  return <button type="button" className={`vdb-tile ${part.error || rows === null ? 'is-muted' : ''}`} style={style} data-part={part.name}
    aria-label={`${part.name}, 청크 ${fmtCount(rows)}개`} onClick={() => { tip.hide(); onOpen(); }} {...binding}>{body}</button>;
}

function MoreTile({ parts, total, onOpen }: { parts: Part[]; total: number; onOpen: () => void }) {
  const rows = parts.reduce((sum, p) => sum + (p.row_count ?? 0), 0);
  const share = total > 0 ? rows / total : 0;
  return <button type="button" className="vdb-tile is-more" onClick={onOpen} aria-label={`파티션 ${parts.length}개 더 보기`}>
    <span className="vdb-tile-name"><span>{parts.length}개 더</span></span>
    <span className="vdb-tile-count ui-num">{fmtCount(rows)}</span>
    <span className="vdb-tile-bar" aria-hidden><i style={{ width: `${Math.max(share * 100, share ? 2 : 0)}%` }} /></span>
  </button>;
}

/** 파티션이 많을 때 전체 목록. 고르면 이 팝업을 닫고 파티션 팝업을 연다. */
function MoreModal({ db, coll, onClose, onPick }: { db: string; coll: CollectionNode; onClose: () => void; onPick: (p: PartitionNode) => void }) {
  const parts = sortParts(coll);
  const total = coll.row_count ?? 0;
  return <Modal open onClose={onClose} size="md" title={`${coll.name} 파티션`} subtitle={`${db} · 파티션 ${fmtCount(parts.length)}개 · 청크 ${fmtCount(coll.row_count)}개`}>
    <ul className="vdb-plist-all" aria-label="파티션 목록">
      {parts.map(p => {
        const share = total > 0 && p.row_count ? p.row_count / total : 0;
        const muted = !p.row_count || !!p.error;
        return <li key={p.name}><button type="button" className={muted ? 'is-muted' : ''} style={{ '--c': p.color } as CSSProperties} disabled={p.row_count === 0 && !p.error} onClick={() => onPick(p)}>
          <i className="vdb-swatch" aria-hidden /><span className="vdb-pa-name">{p.name}</span>
          {p.error ? <span className="vdb-pa-err">{p.error}</span> : <span className="vdb-tile-bar" aria-hidden><i style={{ width: `${share * 100}%` }} /></span>}
          <span className="vdb-pa-pct ui-num">{p.error ? '' : fmtPct(p.row_count ?? 0, total)}</span>
          <span className="vdb-pa-count ui-num">{fmtCount(p.row_count)}</span>
        </button></li>;
      })}
    </ul>
  </Modal>;
}
