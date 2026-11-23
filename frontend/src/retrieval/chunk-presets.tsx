import { useState } from 'react';
import type { ReactNode } from 'react';
import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import type { ImagePolicy, Preset, StrategyKind, StrategyParams, TablePolicy } from '../api/retrieval';
import { ChunkSizingFields, SizeInput } from './ChunkSizingFields';
import { ListBox, Modal } from '../ui';
import { BASELINE_KINDS, ELEMENT_KINDS, IMAGE_POLICY, STRATEGY_HINT, STRATEGY_LABEL, TABLE_POLICY, defaultParams, describeParams, isBaseline } from './shared';

/** 한 번에 비교하는 전략 수. 바꾸면 바로 저장해 임베딩 평가에서도 쓴다. */
export const MAX_SELECTED = 6;
const MAX_PRESETS = 12;
const newId = () => `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

type Props = {
  presets: Preset[]; selected: string[]; initial: string | null; returnToDetail: boolean;
  onChange: (next: Preset[]) => void; onToggle: (id: string) => void; onReset: () => void; onClose: () => void;
};
/** 전략 설정: 왼쪽 목록에서 고르고(체크 = 비교에 포함), 오른쪽에서 말로 된 설정을 고친다. */
export function PresetModal({ presets, selected, initial, returnToDetail, onChange, onToggle, onReset, onClose }: Props) {
  /* 요소 인지 계열을 먼저, 기준선을 뒤에 둔다. */
  const ordered = [...presets.filter(p => !isBaseline(p.kind)), ...presets.filter(p => isBaseline(p.kind))];
  const [current, setCurrent] = useState<string | null>(initial && presets.some(p => p.id === initial) ? initial : ordered[0]?.id ?? null);
  const preset = presets.find(p => p.id === current) ?? ordered[0];
  const update = (id: string, patch: Partial<Preset>) => onChange(presets.map(p => p.id === id ? { ...p, ...patch } : p));
  const add = () => {
    const next: Preset = { id: newId(), name: `요소 인지 ${presets.length + 1}`, kind: 'element', params: defaultParams('element') };
    onChange([...presets, next]);
    setCurrent(next.id);
  };
  const remove = (id: string) => {
    const rest = presets.filter(p => p.id !== id);
    onChange(rest);
    setCurrent(rest[0]?.id ?? null);
  };
  return <Modal open onClose={onClose} size="lg" flush title="전략 설정" subtitle="저장한 전략은 임베딩 평가에서도 씁니다."
    footer={<>
      <span className="ui-foot-note">비교에 {selected.length}개 포함 · 최대 {MAX_SELECTED}개</span>
      <button type="button" className="button-quiet cb-btn" onClick={onReset}><RotateCcw size={14} /> 기본값으로</button>
      <button type="button" className="button-secondary cb-btn" disabled={presets.length >= MAX_PRESETS} onClick={add}><Plus size={14} /> 전략 추가</button>
      <button type="button" className="button-primary cb-btn" onClick={onClose}>{returnToDetail ? '전략 상세로' : '완료'}</button>
    </>}>
    <div className="ui-split cb-preset-split">
      <div className="cb-listcol" onKeyDown={event => {
        /* 목록에서 Space: 고른 전략을 비교에 넣거나 뺀다. */
        if (event.key === ' ' && (event.target as HTMLElement).getAttribute('role') === 'listbox' && preset) { event.preventDefault(); onToggle(preset.id); }
      }}>
        <ListBox label="전략 목록" items={ordered} getKey={p => p.id} value={preset?.id ?? null} onChange={setCurrent}
          groupBy={p => isBaseline(p.kind) ? '기준선 · 글자로만 자름' : '요소 인지'}
          render={p => {
            const on = selected.includes(p.id);
            const full = !on && selected.length >= MAX_SELECTED;
            return <span className="cb-popt">
              <input type="checkbox" checked={on} disabled={full} aria-label={`${p.name} 비교에 포함`} tabIndex={-1}
                onClick={event => event.stopPropagation()} onChange={() => onToggle(p.id)} />
              <span className="cb-popt-main"><b>{p.name}</b><span>{describeParams(p.params)}</span></span>
            </span>;
          }} />
      </div>
      {preset ? <PresetForm key={preset.id} preset={preset} onUpdate={patch => update(preset.id, patch)} onDelete={presets.length > 1 ? () => remove(preset.id) : undefined} />
        : <div className="ui-empty"><b>전략이 없습니다</b></div>}
    </div>
  </Modal>;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="cb-frow"><span className="cb-flabel">{label}</span><div className="cb-fctl">{children}</div></div>;
}

function PresetForm({ preset: p, onUpdate, onDelete }: { preset: Preset; onUpdate: (patch: Partial<Preset>) => void; onDelete?: () => void }) {
  const set = (patch: Partial<StrategyParams>) => onUpdate({ params: { ...p.params, ...patch } });
  const aware = ELEMENT_KINDS.includes(p.kind);
  const radios = <T extends string>(name: string, value: T | undefined, options: { value: T; label: string; off?: string }[], onPick: (v: T) => void) =>
    <div className="cb-radios" role="radiogroup" aria-label={name}>{options.map(option => <label key={option.value} className={option.off ? 'is-off' : ''}>
      <input type="radio" name={`${p.id}-${name}`} checked={value === option.value} disabled={!!option.off} onChange={() => onPick(option.value)} />
      <span>{option.label}</span>{option.off && <small>{option.off}</small>}
    </label>)}</div>;
  return <div className="cb-form">
    <Row label="이름"><input className="cb-input" aria-label="전략 이름" value={p.name} maxLength={40} onChange={event => onUpdate({ name: event.target.value })} /></Row>
    <Row label="방식">
      <select className="cb-input" aria-label="나누는 방식" value={p.kind} onChange={event => { const kind = event.target.value as StrategyKind; onUpdate({ kind, params: defaultParams(kind, p.params.unit) }); }}>
        <optgroup label="요소 인지">{ELEMENT_KINDS.map(kind => <option key={kind} value={kind}>{STRATEGY_LABEL[kind]}</option>)}</optgroup>
        <optgroup label="기준선">{BASELINE_KINDS.map(kind => <option key={kind} value={kind}>{STRATEGY_LABEL[kind]}</option>)}</optgroup>
      </select>
      <p className="cb-hint">{STRATEGY_HINT[p.kind]}</p>
    </Row>
    <Row label="분할 설정"><div className="cb-sizing"><ChunkSizingFields preset={p} onChange={params => onUpdate({params})}/></div></Row>
    {p.kind === 'markdown' && <Row label="작은 절 처리"><label className="cb-checks">
      <input type="checkbox" checked={p.params.merge_small ?? true} onChange={e => set({merge_small:e.target.checked})}/>작은 절 합치기
    </label></Row>}
    {aware ? <>
      <Row label="표 처리">
        {radios<TablePolicy>('표 처리', p.params.table ?? 'whole', (Object.keys(TABLE_POLICY) as TablePolicy[]).map(value => ({ value, label: TABLE_POLICY[value] })), table => set({ table, table_rows: p.params.table_rows ?? 5 }))}
      </Row>
      {p.params.table === 'rows' && <div className="cb-sizing cb-table-rows"><SizeInput label="행 묶음 크기" min={1} max={500}
        value={p.params.table_rows ?? 10} onCommit={table_rows => set({table_rows})}/></div>}
      <Row label="그림 처리">
        {radios<ImagePolicy | 'describe'>('그림 처리', p.params.image ?? 'caption', [
          ...(Object.keys(IMAGE_POLICY) as ImagePolicy[]).map(value => ({ value, label: IMAGE_POLICY[value] })),
          { value: 'describe', label: '그림 설명 생성', off: '시각 모델 연결 필요' },
        ], image => { if (image !== 'describe') set({ image }); })}
      </Row>
      <Row label="캡션·머리말">
        <div className="cb-checks">
          <label><input type="checkbox" checked={p.params.attach_caption ?? true} onChange={event => set({ attach_caption: event.target.checked })} />캡션을 대상과 함께</label>
          <label><input type="checkbox" checked={p.params.drop_furniture ?? true} onChange={event => set({ drop_furniture: event.target.checked })} />반복 머리말·꼬리말 제거</label>
        </div>
      </Row>
    </> : <Row label="표·그림"><p className="cb-hint">구분하지 않습니다. 비교용 기준선입니다.</p></Row>}
    {onDelete && <div className="cb-form-foot"><button type="button" className="button-quiet cb-btn cb-del" onClick={onDelete}><Trash2 size={14} /> 이 전략 삭제</button></div>}
  </div>;
}
