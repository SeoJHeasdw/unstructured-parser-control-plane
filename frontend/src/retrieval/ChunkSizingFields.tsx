import { useEffect, useState } from 'react';
import type { Preset, StrategyParams, Unit } from '../api/retrieval';

const range: Record<Unit, [number, number]> = { chars: [50, 20_000], tokens: [20, 8_000] };

export function SizeInput({ label, value, min, max, onCommit }: {
  label: string; value: number; min: number; max: number; onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const n = Number(draft);
    const next = draft.trim() && Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : value;
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };
  return <label><span>{label}</span><input type="number" value={draft} min={min} max={max} step={1}
    onChange={e => setDraft(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}/></label>;
}

export function ChunkSizingFields({ preset, onChange }: { preset: Preset; onChange: (params: StrategyParams) => void }) {
  const {kind, params} = preset;
  const [min, max] = range[params.unit];
  const hasOverlap = ['element', 'parent_child', 'fixed', 'recursive'].includes(kind);
  function resize(size: number, unit = params.unit) {
    const next = {...params, unit, size};
    if (hasOverlap && next.overlap !== undefined) next.overlap = Math.min(next.overlap, Math.floor(size / 2));
    if (kind === 'parent_child') next.parent_size = Math.min(range[unit][1], Math.max(size, next.parent_size ?? size * 4));
    if (kind === 'markdown' && next.min_size !== undefined) next.min_size = Math.min(next.min_size, size);
    onChange(next);
  }
  return <>
    <SizeInput label={kind === 'parent_child' ? '자식 청크 크기' : kind === 'page' ? '쪽 최대 크기' : '청크 크기'} value={params.size} min={min} max={max} onCommit={v => resize(v)}/>
    <label><span>길이 단위</span><select value={params.unit} onChange={e => {
      const unit = e.target.value as Unit;
      resize(Math.min(range[unit][1], Math.max(range[unit][0], params.size)), unit);
    }}><option value="chars">글자</option><option value="tokens">추정 토큰</option></select></label>
    {hasOverlap && <SizeInput label="겹침" value={params.overlap ?? (['fixed','recursive'].includes(kind) ? Math.floor(params.size / 8) : 0)}
      min={0} max={Math.floor(params.size / 2)} onCommit={overlap => onChange({...params, overlap})}/>}
    {kind === 'parent_child' && <SizeInput label="부모 청크 크기" value={params.parent_size ?? Math.min(max, params.size * 4)} min={params.size} max={max}
      onCommit={parent_size => onChange({...params, parent_size})}/>}
    {kind === 'sentence' && <SizeInput label="겹칠 문장 수" value={params.overlap_sentences ?? 1} min={0} max={5}
      onCommit={overlap_sentences => onChange({...params, overlap_sentences})}/>}
    {kind === 'markdown' && (params.merge_small ?? true) && <SizeInput label="작은 절 합침 기준" value={params.min_size ?? Math.floor(params.size / 4)} min={0} max={params.size}
      onCommit={min_size => onChange({...params, min_size})}/>}
  </>;
}
