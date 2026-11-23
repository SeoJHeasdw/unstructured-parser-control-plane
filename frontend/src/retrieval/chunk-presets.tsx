import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { BookOpen, Brain, Columns3, FileStack, Heading, Layers, ListOrdered, Plus, RotateCcw, Ruler, Scissors, Trash2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { EmbedConnection, ImagePolicy, Preset, StrategyKind, StrategyParams, TablePolicy, Unit } from '../api/retrieval';
import { ListBox, Modal } from '../ui';
import { BASELINE_KINDS, BREAKPOINTS, ELEMENT_KINDS, IMAGE_POLICY, SEMANTIC_KINDS, STRATEGY_HINT, STRATEGY_LABEL, STRATEGY_SHORT, TABLE_POLICY, defaultParams, describeParams, familyOf, fmtInt } from './shared';

/** 한 번에 비교하는 전략 수. 바꾸면 바로 저장해 임베딩 평가에서도 쓴다. */
export const MAX_SELECTED = 6;
export const MAX_PRESETS = 12;
export const newPresetId = () => `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

const KIND_ICON: Record<StrategyKind, LucideIcon> = {
  element: Columns3, parent_child: Layers, page: FileStack, semantic: Brain,
  fixed: Ruler, recursive: Scissors, sentence: ListOrdered, markdown: Heading,
};
const FAMILIES: { label: string; kinds: StrategyKind[] }[] = [
  { label: '요소 인지', kinds: ELEMENT_KINDS }, { label: '의미 기반', kinds: SEMANTIC_KINDS }, { label: '기준선 · 글자로만 자름', kinds: BASELINE_KINDS },
];
const RANGE: Record<Unit, [number, number]> = { chars: [50, 20_000], tokens: [20, 8_000] };
const QUICK: Record<Unit, number[]> = { chars: [300, 500, 800, 1200], tokens: [150, 250, 400, 600] };
const QUICK_PAGE: Record<Unit, number[]> = { chars: [2000, 3000, 5000], tokens: [1000, 1500, 2500] };
const TABLE_SUMMARY: Record<TablePolicy, string> = { whole: '표 통째', rows: '표 행 묶음', row_text: '표 행→문장' };
const unitWord = (unit: Unit) => unit === 'chars' ? '자' : '토큰';

type Parallel = { value: number; max: number; info: string; onChange: (value: number) => void };
type Props = {
  presets: Preset[]; selected: string[]; initial: string | null; returnToDetail: boolean; connections: EmbedConnection[]; parallel: Parallel;
  onChange: (next: Preset[]) => void; onToggle: (id: string) => void; onReset: () => void; onClose: () => void;
};

/** 전략 설정: 왼쪽 목록에서 고르고(체크 = 비교에 포함), 오른쪽에서 말로 된 설정을 고친다. */
export function PresetModal({ presets, selected, initial, returnToDetail, connections, parallel, onChange, onToggle, onReset, onClose }: Props) {
  const ordered = FAMILIES.flatMap(f => presets.filter(p => f.kinds.includes(p.kind)));
  const [current, setCurrent] = useState<string | null>(initial && presets.some(p => p.id === initial) ? initial : ordered[0]?.id ?? null);
  const preset = presets.find(p => p.id === current) ?? ordered[0];
  const update = (id: string, patch: Partial<Preset>) => onChange(presets.map(p => p.id === id ? { ...p, ...patch } : p));
  const add = () => {
    const next: Preset = { id: newPresetId(), name: `요소 인지 ${presets.length + 1}`, kind: 'element', params: defaultParams('element') };
    onChange([...presets, next]);
    setCurrent(next.id);
  };
  const remove = (id: string) => {
    const rest = presets.filter(p => p.id !== id);
    onChange(rest);
    setCurrent(rest[0]?.id ?? null);
  };
  return <Modal open onClose={onClose} size="lg" flush title="전략 설정" subtitle="고친 값은 바로 비교에 반영되고, 임베딩 평가에서도 씁니다."
    footer={<>
      <span className="ui-foot-note">비교에 {selected.length}개 포함 · 최대 {MAX_SELECTED}개</span>
      <label className="cb-parallel" data-tip={parallel.info || '여러 전략을 동시에 계산합니다. 문서가 클 때 빨라집니다.'}>전략 동시 실행
        <select value={parallel.value} disabled={parallel.max <= 1} onChange={event => parallel.onChange(Number(event.target.value))}>
          {Array.from({ length: Math.max(1, parallel.max) }, (_, i) => <option key={i} value={i + 1}>{i === 0 ? '1개 · 순차' : `최대 ${i + 1}개`}</option>)}
        </select></label>
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
          groupBy={p => FAMILIES.find(f => f.kinds.includes(p.kind))?.label ?? '기준선'}
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
      {preset ? <PresetForm key={preset.id} preset={preset} connections={connections} onUpdate={patch => update(preset.id, patch)} onDelete={presets.length > 1 ? () => remove(preset.id) : undefined} />
        : <div className="ui-empty"><b>전략이 없습니다</b></div>}
    </div>
  </Modal>;
}

function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return <div className="cb-frow"><span className="cb-flabel">{label}{hint && <small>{hint}</small>}</span><div className="cb-fctl">{children}</div></div>;
}

/** 숫자 칸: 입력 중에는 그대로 두고, 벗어나거나 Enter를 누를 때 범위 안으로 맞춰 반영한다. */
function NumberField({ label, value, min, max, suffix, onCommit }: { label: string; value: number; min: number; max: number; suffix?: string; onCommit: (value: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const n = Number(draft);
    const next = draft.trim() && Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : value;
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };
  return <label className="cb-numfield"><input type="number" aria-label={label} value={draft} min={min} max={max} step={1}
    onChange={event => setDraft(event.target.value)} onBlur={commit} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} />{suffix && <span>{suffix}</span>}</label>;
}

/** 자주 쓰는 값은 버튼으로, 그 밖의 값은 옆 칸에 직접. */
function Choice({ label, value, options, min, max, suffix, onChange }: {
  label: string; value: number; options: { value: number; label: string }[]; min: number; max: number; suffix: string; onChange: (value: number) => void;
}) {
  return <div className="cb-choice">
    <div className="cb-quick" role="group" aria-label={`${label} 빠른 선택`}>
      {options.map(option => <button key={option.label} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}>{option.label}</button>)}
    </div>
    <NumberField label={label} value={value} min={min} max={max} suffix={suffix} onCommit={onChange} />
  </div>;
}

/** 크기를 바꿀 때 겹침·맥락·최소 크기를 함께 맞춘다. */
function resize(kind: StrategyKind, params: StrategyParams, size: number, unit: Unit = params.unit): StrategyParams {
  const next = { ...params, unit, size };
  if (next.overlap !== undefined) next.overlap = Math.min(next.overlap, Math.floor(size / 2));
  if (kind === 'parent_child') next.parent_size = Math.min(RANGE[unit][1], Math.max(size, next.parent_size ?? size * 4));
  if (next.min_size !== undefined) next.min_size = Math.min(next.min_size, size);
  return next;
}

function PresetForm({ preset: p, connections, onUpdate, onDelete }: { preset: Preset; connections: EmbedConnection[]; onUpdate: (patch: Partial<Preset>) => void; onDelete?: () => void }) {
  const params = p.params;
  const set = (patch: Partial<StrategyParams>) => onUpdate({ params: { ...params, ...patch } });
  const aware = ELEMENT_KINDS.includes(p.kind);
  const [min, max] = RANGE[params.unit];
  const unit = unitWord(params.unit);
  const quick = (p.kind === 'page' ? QUICK_PAGE : QUICK)[params.unit].map(value => ({ value, label: `${fmtInt(value)}${unit}` }));
  const hasOverlap = ['element', 'parent_child', 'fixed', 'recursive'].includes(p.kind);
  const radios = <T extends string>(name: string, value: T | undefined, options: { value: T; label: string; off?: string }[], onPick: (v: T) => void) =>
    <div className="cb-radios" role="radiogroup" aria-label={name}>{options.map(option => <label key={option.value} className={option.off ? 'is-off' : ''}>
      <input type="radio" name={`${p.id}-${name}`} checked={value === option.value} disabled={!!option.off} onChange={() => onPick(option.value)} />
      <span>{option.label}</span>{option.off && <small>{option.off}</small>}
    </label>)}</div>;
  const models = connections.filter(c => c.configured).flatMap(c => c.models.map(model => ({ key: `${c.key}|${model}`, label: model, conn: c.label })));
  const modelValue = params.model ? `${params.connection || 'embed'}|${params.model}` : '';
  const sizeLabel = p.kind === 'parent_child' ? '검색 청크 크기' : p.kind === 'page' ? '쪽 최대 크기' : p.kind === 'semantic' ? '최대 크기' : '청크 크기';
  const switchUnit = (u: Unit) => {
    if (u === params.unit) return;
    const converted = u === 'tokens' ? Math.round(params.size / 2) : params.size * 2;
    onUpdate({ params: resize(p.kind, params, Math.min(RANGE[u][1], Math.max(RANGE[u][0], converted)), u) });
  };

  return <div className="cb-form">
    <Row label="이름"><input className="cb-input" aria-label="전략 이름" value={p.name} maxLength={40} onChange={event => onUpdate({ name: event.target.value })} /></Row>
    <Row label="나누는 방식">
      <div className="cb-kinds" role="radiogroup" aria-label="나누는 방식">
        {FAMILIES.map(family => <div className="cb-kind-group" key={family.label}><span>{family.label}</span>
          {family.kinds.map(kind => { const Icon = KIND_ICON[kind]; return <label key={kind} className={'cb-kind' + (p.kind === kind ? ' is-on' : '')}>
            <input type="radio" name={`${p.id}-kind`} checked={p.kind === kind} onChange={() => onUpdate({ kind, params: defaultParams(kind, params.unit) })} />
            <Icon size={17} aria-hidden="true" /><span><b>{STRATEGY_LABEL[kind]}</b><small>{STRATEGY_SHORT[kind]}</small></span>
          </label>; })}
        </div>)}
      </div>
      <p className="cb-hint">{STRATEGY_HINT[p.kind]}</p>
    </Row>
    <Row label={sizeLabel} hint={p.kind === 'parent_child' ? '질문과 맞춰 볼 작은 조각' : '검색 결과 하나에 담기는 길이'}>
      <Choice label={sizeLabel} value={params.size} options={quick} min={min} max={max} suffix={unit} onChange={size => onUpdate({ params: resize(p.kind, params, size) })} />
      <div className="cb-unit ui-seg" role="radiogroup" aria-label="길이 단위">
        {(['chars', 'tokens'] as Unit[]).map(u => <button key={u} type="button" role="radio" aria-checked={params.unit === u} onClick={() => switchUnit(u)}>
          {u === 'chars' ? '글자' : '추정 토큰'}</button>)}
      </div>
    </Row>
    {p.kind === 'parent_child' && <Row label="함께 넘길 맥락" hint="답할 때 모델에 주는 큰 조각">
      <Choice label="부모 청크 크기" value={params.parent_size ?? params.size * 4} min={params.size} max={max} suffix={unit} onChange={parent_size => set({ parent_size })}
        options={[3, 5, 8].map(k => ({ value: Math.min(max, params.size * k), label: `×${k}` }))} />
    </Row>}
    {hasOverlap && <Row label="앞 청크와 겹침" hint="경계에 걸친 문장을 놓치지 않게">
      <Choice label="겹침" value={params.overlap ?? 0} min={0} max={Math.floor(params.size / 2)} suffix={unit} onChange={value => set({ overlap: value })}
        options={[{ value: 0, label: '없음' }, { value: Math.round(params.size * 0.1), label: '10%' }, { value: Math.round(params.size * 0.2), label: '20%' }]} />
    </Row>}
    {p.kind === 'sentence' && <Row label="겹칠 문장">
      <div className="cb-quick" role="group" aria-label="겹칠 문장 수">{[0, 1, 2, 3].map(n => <button key={n} type="button" aria-pressed={(params.overlap_sentences ?? 1) === n}
        onClick={() => set({ overlap_sentences: n })}>{n ? `${n}문장` : '없음'}</button>)}</div>
    </Row>}
    {p.kind === 'markdown' && <Row label="작은 절">
      <label className="cb-checks cb-inline"><input type="checkbox" checked={params.merge_small ?? true} onChange={event => set({ merge_small: event.target.checked })} />이웃 절과 합치기</label>
      {(params.merge_small ?? true) && <NumberField label="작은 절 합침 기준" value={params.min_size ?? Math.floor(params.size / 4)} min={0} max={params.size} suffix={`${unit} 미만`} onCommit={min_size => set({ min_size })} />}
    </Row>}
    {p.kind === 'semantic' && <>
      <Row label="임베딩 모델" hint="문장의 뜻을 비교할 모델">
        {models.length ? <select className="cb-input" aria-label="임베딩 모델" value={modelValue} onChange={event => {
          const [connection, ...rest] = event.target.value.split('|');
          set(event.target.value ? { connection, model: rest.join('|') } : { connection: 'embed', model: '' });
        }}>
          <option value="">임베딩 연결의 첫 모델</option>
          {models.map(m => <option key={m.key} value={m.key}>{m.label} · {m.conn}</option>)}
        </select> : <p className="cb-warn" role="note">임베딩 연결이 없습니다. 설정 › 임베딩 모델에서 사내 게이트웨이를 연결하세요.</p>}
      </Row>
      <Row label="나누는 빈도" hint="뜻 차이가 큰 곳만 나눌지, 자주 나눌지">
        <div className="cb-quick" role="radiogroup" aria-label="나누는 빈도">{BREAKPOINTS.map(b => <button key={b.value} type="button" role="radio" aria-checked={(params.breakpoint ?? 90) === b.value}
          onClick={() => set({ breakpoint: b.value })}>{b.label}<small>상위 {100 - b.value}%</small></button>)}</div>
      </Row>
      <Row label="작은 묶음 합침" hint="너무 짧은 묶음은 다음 묶음과 합침">
        <NumberField label="최소 크기" value={params.min_size ?? Math.floor(params.size / 4)} min={0} max={params.size} suffix={`${unit} 미만`} onCommit={min_size => set({ min_size })} />
      </Row>
    </>}
    {aware && <details className="cb-more">
      <summary><BookOpen size={15} aria-hidden="true" />표·그림·머리말 처리<span>{[TABLE_SUMMARY[params.table ?? 'whole'], params.image === 'drop' ? '그림 버림' : '그림 캡션', params.drop_furniture === false ? '머리말 유지' : '머리말 제거'].join(' · ')}</span></summary>
      <Row label="표 처리">
        {radios<TablePolicy>('표 처리', params.table ?? 'whole', (Object.keys(TABLE_POLICY) as TablePolicy[]).map(value => ({ value, label: TABLE_POLICY[value] })), table => set({ table, table_rows: params.table_rows ?? 5 }))}
        {params.table === 'rows' && <NumberField label="행 묶음 크기" value={params.table_rows ?? 10} min={1} max={500} suffix="행씩" onCommit={table_rows => set({ table_rows })} />}
      </Row>
      <Row label="그림 처리">
        {radios<ImagePolicy | 'describe'>('그림 처리', params.image ?? 'caption', [
          ...(Object.keys(IMAGE_POLICY) as ImagePolicy[]).map(value => ({ value, label: IMAGE_POLICY[value] })),
          { value: 'describe', label: '그림 설명 생성', off: '시각 모델 연결 필요' },
        ], image => { if (image !== 'describe') set({ image }); })}
      </Row>
      <Row label="캡션·머리말">
        <div className="cb-checks">
          <label><input type="checkbox" checked={params.attach_caption ?? true} onChange={event => set({ attach_caption: event.target.checked })} />캡션을 대상과 함께</label>
          <label><input type="checkbox" checked={params.drop_furniture ?? true} onChange={event => set({ drop_furniture: event.target.checked })} />반복 머리말·꼬리말 제거</label>
        </div>
      </Row>
    </details>}
    {!aware && p.kind !== 'semantic' && <p className="cb-hint cb-base-note">표·그림을 구분하지 않는 비교용 기준선입니다.</p>}
    <p className="cb-family">{familyOf(p.kind)} · {describeParams(params)}</p>
    {onDelete && <div className="cb-form-foot"><button type="button" className="button-quiet cb-btn cb-del" onClick={onDelete}><Trash2 size={14} /> 이 전략 삭제</button></div>}
  </div>;
}
