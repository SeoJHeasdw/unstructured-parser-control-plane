import { useEffect, useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { sampleDocId } from '../api/retrieval';
import type { Candidate, ModelSpec, Question, RetrievalConfig, RetrievalDoc, Sample } from '../api/retrieval';
import { ListBox } from '../ui';
import { fmtInt } from './shared';
import { SHORT_INPUT, candidateFor, fmtTokens, modelName, nextId, shortLang, specFor } from './eval-common';

/** 모델 이름 아래 한 줄: 차원 · 입력 한도 · 언어. 입력이 짧은 모델은 한도를 표시로 드러낸다. */
export function ModelFacts({ spec, dims, limit }: { spec: ModelSpec | null; dims?: number | null; limit?: number | null }) {
  const d = spec?.dims ?? dims ?? null;
  const max = limit ?? spec?.max_tokens ?? null;
  if (d === null && max === null) return <span className="ee-facts">사양 정보 없음</span>;
  return <span className="ee-facts">
    {d !== null ? `${d}차원` : '차원 모름'}{' · '}
    {max === null ? '입력 한도 모름' : max <= SHORT_INPUT ? <em className="ee-tag">입력 {fmtTokens(max)}</em> : `입력 ${fmtTokens(max)}`}
    {spec ? ` · ${shortLang(spec.languages)}` : ''}
  </span>;
}

/* ---------- 문서 ---------- */
const composition = (s: Sample) => [s.composition.table ? `표 ${s.composition.table}` : '', s.composition.image ? `그림 ${s.composition.image}` : '', s.pages ? `${s.pages}쪽` : ''].filter(Boolean).join(' · ');

function GroupCheck({ label, ids, selected, onSet }: { label: string; ids: string[]; selected: Set<string>; onSet: (on: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const count = ids.filter(id => selected.has(id)).length;
  useEffect(() => { if (ref.current) ref.current.indeterminate = count > 0 && count < ids.length; }, [count, ids.length]);
  return <label className="ee-check-head">
    <input ref={ref} type="checkbox" checked={ids.length > 0 && count === ids.length} disabled={!ids.length} onChange={e => onSet(e.target.checked)} />
    <span>{label}</span><span className="ee-num">{fmtInt(count)} / {fmtInt(ids.length)}</span>
  </label>;
}

export function DocChoices({ samples, docs, questions, docIds, max, onChange }: {
  samples: Sample[]; docs: RetrievalDoc[]; questions: Question[]; docIds: string[]; max: number; onChange: (ids: string[]) => void;
}) {
  const selected = new Set(docIds);
  const perDoc = new Map<string, number>();
  questions.forEach(q => { if (q.doc_id) perDoc.set(q.doc_id, (perDoc.get(q.doc_id) ?? 0) + 1); });
  const sampleIds = samples.map(s => sampleDocId(s.id));
  const realIds = docs.map(d => d.id);
  const set = (ids: string[]) => onChange([...new Set(ids)].slice(0, max));
  const toggle = (id: string, on: boolean) => set(on ? [...docIds, id] : docIds.filter(x => x !== id));
  const setGroup = (ids: string[], on: boolean) => set(on ? [...docIds, ...ids] : docIds.filter(x => !ids.includes(x)));
  const full = docIds.length >= max;
  return <>
    <section className="ee-checks" aria-label="예시 문서">
      <GroupCheck label="예시 문서" ids={sampleIds} selected={selected} onSet={on => setGroup(sampleIds, on)} />
      {samples.length === 0 ? <p className="ee-quiet">예시 문서를 불러오지 못했습니다.</p>
        : samples.map(s => { const id = sampleDocId(s.id); return <label key={id} className="ee-check">
          <input type="checkbox" checked={selected.has(id)} disabled={!selected.has(id) && full} onChange={e => toggle(id, e.target.checked)} />
          <span className="ee-check-main"><b>{s.name}</b><span>{s.description}</span></span>
          <span className="ee-check-side">{composition(s)}</span>
          <span className="ee-check-q ee-num">질문 {fmtInt(perDoc.get(id) ?? 0)}</span>
        </label>; })}
    </section>
    <section className="ee-checks" aria-label="실제 문서">
      <GroupCheck label="실제 문서" ids={realIds} selected={selected} onSet={on => setGroup(realIds, on)} />
      {docs.length === 0 ? <p className="ee-quiet">파싱이 끝난 문서가 없습니다.</p>
        : docs.map(d => <label key={d.id} className="ee-check">
          <input type="checkbox" checked={selected.has(d.id)} disabled={!selected.has(d.id) && full} onChange={e => toggle(d.id, e.target.checked)} />
          <span className="ee-check-main"><b>{d.name}</b>{d.is_stale && <span className="ee-warn-text">이전 파싱 결과</span>}</span>
          <span className="ee-check-side">{d.format.toUpperCase()}</span>
          <span className="ee-check-q ee-num">질문 {fmtInt(perDoc.get(d.id) ?? 0)}</span>
        </label>)}
    </section>
  </>;
}

/* ---------- 모델 ---------- */
export function ModelChoices({ config, candidates, isDefault, onChange, onReset }: {
  config: RetrievalConfig | null; candidates: Candidate[]; isDefault: boolean; onChange: (list: Candidate[]) => void; onReset: () => void;
}) {
  const [sel, setSel] = useState<string | null>(null);
  const side = useRef<HTMLDivElement>(null);
  /* 누른 버튼(빼기·되돌리기)이 사라지면 초점을 목록으로 옮겨 Escape·방향키가 계속 듣게 한다. */
  const [focusTick, setFocusTick] = useState(0);
  const focusList = () => setFocusTick(n => n + 1);
  useEffect(() => { if (focusTick) side.current?.querySelector<HTMLElement>('[role="listbox"], .ee-add')?.focus(); }, [focusTick]);
  const current = candidates.find(c => c.id === sel) ?? candidates[0] ?? null;
  const max = config?.caps.max_candidates ?? 6;
  const specs = config?.specs ?? [];
  const used = new Set(candidates.map(c => specFor(specs, c.model)?.id ?? c.model));
  const addable = specs.filter(s => !used.has(s.id));
  const full = candidates.length >= max;
  const add = (model: string) => { const c = candidateFor(config, nextId(candidates), model); onChange([...candidates, c]); setSel(c.id); };
  const remove = (id: string) => { const i = candidates.findIndex(c => c.id === id); const next = candidates.filter(c => c.id !== id); onChange(next); setSel(next[Math.min(i, next.length - 1)]?.id ?? null);
 focusList(); };
  const patch = (id: string, change: Partial<Candidate>) => onChange(candidates.map(c => c.id === id ? { ...c, ...change } : c));
  return <>
    <div className="conditions-actions"><span>{fmtInt(candidates.length)} / 최대 {fmtInt(max)}개</span>
      {!isDefault && <button type="button" className="ee-btn" onClick={() => { onReset(); setSel(null); focusList(); }}>기본 모델로 되돌리기</button>}</div>
    <div className="ui-split ee-split">
      <div ref={side}>
        <ListBox items={candidates} getKey={c => c.id} value={current?.id ?? null} onChange={setSel} label="비교할 모델" className="ee-list"
          empty={<div className="ui-listbox-empty">비교할 모델이 없습니다.</div>}
          render={c => <div className="ee-opt"><b>{modelName(c.model)}</b><ModelFacts spec={specFor(specs, c.model)} /></div>} />
        <div className="ee-addbox">
          <p className="ee-group-label">더하기</p>
          {addable.map(s => <button type="button" key={s.id} className="ee-add" disabled={full} onClick={() => add(s.id)}>
            <Plus size={14} aria-hidden /><b>{modelName(s.id)}</b><span>{shortLang(s.languages)}</span></button>)}
          <button type="button" className="ee-add" disabled={full} onClick={() => add('')}><Plus size={14} aria-hidden /><b>직접 입력</b></button>
        </div>
      </div>
      <div>{current ? <ModelForm key={current.id} config={config} candidate={current} onPatch={change => patch(current.id, change)} onRemove={() => remove(current.id)} />
        : <div className="ui-empty"><b>비교할 모델이 없습니다</b></div>}</div>
    </div>
  </>;
}

function ModelForm({ config, candidate: c, onPatch, onRemove }: { config: RetrievalConfig | null; candidate: Candidate; onPatch: (change: Partial<Candidate>) => void; onRemove: () => void }) {
  const specs = config?.specs ?? [];
  const spec = specFor(specs, c.model);
  const suggestions = [...new Set([...(config?.connections.flatMap(x => x.models) ?? []), ...specs.map(s => s.id)])];
  const connections = config?.connections.length ? config.connections : [{ key: c.connection, label: c.connection, configured: false }];
  const setModel = (model: string) => {
    const next = specFor(specs, model);
    onPatch(next ? { model, query_prefix: next.query_prefix, doc_prefix: next.doc_prefix } : { model });
  };
  const about = spec ? [spec.arch, spec.pooling ? `${spec.pooling} 풀링` : '', spec.dims_note ? `차원 ${spec.dims_note}` : '', spec.prefix_note, spec.note].filter(Boolean) : [];
  return <div className="ee-form">
    <div className="ee-form-head">
      <div><h3>{modelName(c.model)}</h3></div>
      <button type="button" className="ee-btn is-quiet is-danger" onClick={onRemove} aria-label={`${modelName(c.model)} 빼기`}>빼기</button>
    </div>
    {about.length > 0 && <p className="ee-about">{about.join(' · ')}</p>}
    <datalist id="ee-model-ids">{suggestions.map(m => <option key={m} value={m} />)}</datalist>
    <label className="ee-label">모델 ID<input list="ee-model-ids" value={c.model} onChange={e => setModel(e.target.value)} spellCheck={false} /></label>
    <label className="ee-label">연결<select value={c.connection} onChange={e => onPatch({ connection: e.target.value })}>
      {connections.map(x => <option key={x.key} value={x.key}>{x.label}{x.configured ? '' : ' · 연결 없음'}</option>)}</select></label>
    <div className="ee-row2">
      <label className="ee-label">질의 접두어<input value={c.query_prefix} onChange={e => onPatch({ query_prefix: e.target.value })} placeholder="없음" spellCheck={false} /></label>
      <label className="ee-label">문서 접두어<input value={c.doc_prefix} onChange={e => onPatch({ doc_prefix: e.target.value })} placeholder="없음" spellCheck={false} /></label>
    </div>
    <label className="ee-label is-narrow">묶음 크기<input type="number" min={1} max={64} value={c.batch_size} onChange={e => onPatch({ batch_size: Math.min(64, Math.max(1, Number(e.target.value) || 1)) })} /></label>
  </div>;
}
