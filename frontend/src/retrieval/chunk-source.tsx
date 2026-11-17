import { useState } from 'react';
import type { ElementKind, RetrievalDoc, Sample } from '../api/retrieval';
import { ListBox, Modal } from '../ui';
import { CompositionBar } from './chunk-compare';

export type SourceKey = `sample:${string}` | `doc:${string}`;
type Item = { key: SourceKey; group: string; name: string; note: string; composition?: Partial<Record<ElementKind, number>>; stale?: boolean };

/** 원문 고르기: 예시 문서와 실제 문서를 한 목록에서, 각자의 구성과 함께 본다. */
export function SourceModal({ samples, docs, current, currentComposition, onPick, onClose }: {
  samples: Sample[]; docs: RetrievalDoc[]; current: SourceKey | null; currentComposition: Partial<Record<ElementKind, number>> | null;
  onPick: (key: SourceKey) => void; onClose: () => void;
}) {
  const items: Item[] = [
    ...samples.map(s => ({ key: `sample:${s.id}` as SourceKey, group: '예시 문서', name: s.name, note: [s.pages ? `${s.pages}쪽` : '', s.description].filter(Boolean).join(' · '), composition: s.composition })),
    ...docs.map(d => ({ key: `doc:${d.id}` as SourceKey, group: '실제 문서', name: d.name, note: [d.format.toUpperCase(), d.updated_at ? d.updated_at.slice(0, 10) : ''].filter(Boolean).join(' · '),
      composition: current === `doc:${d.id}` ? currentComposition ?? undefined : undefined, stale: d.is_stale })),
  ];
  const [pending, setPending] = useState<SourceKey | null>(current && items.some(i => i.key === current) ? current : items[0]?.key ?? null);
  const confirm = () => { if (pending) onPick(pending); };
  return <Modal open onClose={onClose} size="md" flush title="원문" subtitle={docs.length ? undefined : '처리가 끝난 실제 문서가 아직 없습니다.'}
    footer={<><button type="button" className="button-quiet cb-btn" onClick={onClose}>취소</button>
      <button type="button" className="button-primary cb-btn" disabled={!pending} onClick={confirm}>이 문서로 나누기</button></>}>
    <div className="cb-source-list" onDoubleClick={confirm} onKeyDown={event => { if (event.key === 'Enter' && pending) { event.preventDefault(); confirm(); } }}>
      <ListBox label="원문 목록" items={items} getKey={i => i.key} value={pending} onChange={key => setPending(key as SourceKey)} groupBy={i => i.group}
        render={item => <span className="cb-sopt">
          <span className="cb-sopt-head"><b>{item.name}</b>{item.stale && <span className="ui-pill is-warn">이전 처리 결과</span>}</span>
          {item.note && <span className="cb-sopt-note">{item.note}</span>}
          {item.composition && <CompositionBar composition={item.composition} bar={false} />}
        </span>} />
    </div>
  </Modal>;
}
