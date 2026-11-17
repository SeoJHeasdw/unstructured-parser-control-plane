import type { LineageData, LnFamily, LnInstance, LnReference, RefState } from '../api/lineage';

export type Tone = 'ok' | 'warn' | 'error' | 'amb' | 'muted' | 'info';
export const STATE_META: Record<RefState, { label: string; tone: Tone; short: string }> = {
  linked: { label: '연결됨', tone: 'ok', short: '연결' },
  outdated: { label: '구버전 참조', tone: 'warn', short: '구버전' },
  missing: { label: '대상 미발견', tone: 'error', short: '미발견' },
  ambiguous: { label: '후보 여러 개', tone: 'amb', short: '후보 여럿' },
  external: { label: '외부 주소', tone: 'muted', short: '외부' },
};
export const LATEST_META: Record<LnFamily['latest']['status'], { label: string; tone: Tone }> = {
  confirmed: { label: '최신 확정', tone: 'ok' }, hold: { label: '판단 보류', tone: 'warn' }, single: { label: '단일 판', tone: 'muted' },
};
export const MATCH_LABEL: Record<string, string> = {
  'exact-name': '파일 이름 일치', docno: '문서번호 일치', 'docno-version': '문서번호와 Rev 일치', 'docno-prefix': '문서번호 일부 일치',
  'name-rule': '판 표시를 뺀 이름 일치', 'name-rule-version': '판 표시를 뺀 이름과 판 일치',
};
export type Filter = 'all' | 'hold' | 'outdated' | 'missing' | 'ambiguous' | 'duplicate' | 'not-analysed';
export const FILTERS: { id: Filter; label: string; essential?: boolean }[] = [
  { id: 'all', label: '전체', essential: true }, { id: 'hold', label: '판단 보류', essential: true }, { id: 'outdated', label: '구버전 참조', essential: true },
  { id: 'missing', label: '미발견 참조' }, { id: 'ambiguous', label: '후보 여러 개' }, { id: 'duplicate', label: '중복' }, { id: 'not-analysed', label: '구조 분석 전' },
];
export const familyMatches = (family: LnFamily, filter: Filter) => filter === 'all' || family.flags.includes(filter);

export const sizeText = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
export const timeText = (value: string | null | undefined) => {
  if (!value) return '시각 없음';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
};

export function within(id: string, root: string) { return id === root || id.startsWith(root + '/'); }

export function subtree(instances: LineageData['instances'], root: string, out: string[] = []) {
  const node = instances[root];
  if (!node) return out;
  out.push(root);
  node.children.forEach(child => subtree(instances, child, out));
  return out;
}

export function ancestors(instances: LineageData['instances'], id: string) {
  const out: LnInstance[] = [];
  let current = instances[id]?.parent ?? null;
  while (current && instances[current]) { out.unshift(instances[current]); current = instances[current].parent; }
  return out;
}

export function holderText(data: LineageData, id: string) {
  const chain = ancestors(data.instances, id).map(item => item.name);
  return chain.length ? chain.join(' › ') : '';
}

/** 참조를 대상(또는 출발) 기준으로 묶는다. 같은 대상을 여러 곳에서 가리키면 한 줄로 본다. */
export type RefGroup = { key: string; state: RefState; refs: LnReference[]; family: string | null; entry: string | null; instance: string | null; text: string; sub: string; sourceFamily: string | null; sourceRoot: string };

export function targetText(data: LineageData, ref: LnReference) {
  const family = ref.family ? data.families.find(f => f.id === ref.family) : null;
  if (family) return { text: family.title, sub: ref.entry ? data.entries[ref.entry]?.label ?? '' : ref.wanted ? `${ref.wanted} (파일 없음)` : '' };
  if (ref.instance && data.instances[ref.instance]) { const holder = holderText(data, ref.instance); return { text: data.instances[ref.instance].name, sub: holder ? `${holder} 안` : '' }; }
  return { text: ref.target, sub: ref.wanted ?? '' };
}

export function groupOutgoing(data: LineageData, refs: LnReference[]): RefGroup[] {
  const groups = new Map<string, RefGroup>();
  for (const ref of refs) {
    const key = `o|${ref.state}|${ref.family ?? ''}|${ref.entry ?? ''}|${ref.instance ?? ''}|${ref.family || ref.instance ? ref.wanted ?? '' : ref.target}`;
    const existing = groups.get(key);
    if (existing) { existing.refs.push(ref); continue; }
    const { text, sub } = targetText(data, ref);
    groups.set(key, { key, state: ref.state, refs: [ref], family: ref.family, entry: ref.entry, instance: ref.instance, text, sub, sourceFamily: ref.source_family, sourceRoot: ref.source_root });
  }
  return sortGroups([...groups.values()]);
}

export function groupIncoming(data: LineageData, refs: LnReference[]): RefGroup[] {
  const groups = new Map<string, RefGroup>();
  for (const ref of refs) {
    const key = `i|${ref.state}|${ref.source_root}|${ref.entry ?? ref.wanted ?? ''}`;
    const existing = groups.get(key);
    if (existing) { existing.refs.push(ref); continue; }
    const root = data.instances[ref.source_root];
    const sourceFamily = root?.family ? data.families.find(f => f.id === root.family) : null;
    const entry = root?.entry ? data.entries[root.entry] : null;
    groups.set(key, { key, state: ref.state, refs: [ref], family: ref.family, entry: ref.entry, instance: ref.instance, text: sourceFamily?.title ?? root?.name ?? ref.source,
      sub: entry ? `${entry.label}${entry.is_latest || entry.co_latest ? '' : ' · 이전 판'}` : '', sourceFamily: root?.family ?? null, sourceRoot: ref.source_root });
  }
  return sortGroups([...groups.values()]);
}

const STATE_ORDER: RefState[] = ['outdated', 'missing', 'ambiguous', 'linked', 'external'];
const sortGroups = (groups: RefGroup[]) => groups.sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || b.refs.length - a.refs.length || a.text.localeCompare(b.text, 'ko'));

export function refsFrom(data: LineageData, root: string) { return data.references.filter(ref => within(ref.source, root)); }

export function refsInto(data: LineageData, family: LnFamily) {
  const roots = family.entries.map(id => data.entries[id].primary);
  return data.references.filter(ref => (ref.family === family.id || ref.candidates.some(c => c.family === family.id)) && !roots.some(root => within(ref.source, root)));
}

/** 목록에서 마우스를 올린 문서군과 참조로 이어진 문서군. */
export function relatedFamilies(data: LineageData, familyId: string) {
  const related = new Set<string>([familyId]);
  for (const ref of data.references) {
    const targets = [ref.family, ...ref.candidates.map(c => c.family)].filter(Boolean) as string[];
    const sources = [ref.source_family, data.instances[ref.source_root]?.family].filter(Boolean) as string[];
    if (sources.includes(familyId)) targets.forEach(id => related.add(id));
    if (targets.includes(familyId)) sources.forEach(id => related.add(id));
  }
  return related;
}

/* ----- 화면 설정(보기 방식·접힘 상태)은 이 브라우저에만 남긴다. ----- */
export type UiPrefs = { summaryOpen: boolean; moreFilters: boolean; view: 'tree' | 'graph'; refTab: 'out' | 'in' };
const PREFS_KEY = 'document-ops:lineage-ui:v1';
export const DEFAULT_PREFS: UiPrefs = { summaryOpen: false, moreFilters: false, view: 'tree', refTab: 'out' };
export function loadPrefs(): UiPrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFS_KEY) ?? 'null') as Partial<UiPrefs> | null;
    if (!raw || typeof raw !== 'object') return DEFAULT_PREFS;
    return { summaryOpen: raw.summaryOpen === true, moreFilters: raw.moreFilters === true, view: raw.view === 'graph' ? 'graph' : 'tree', refTab: raw.refTab === 'in' ? 'in' : 'out' };
  } catch { return DEFAULT_PREFS; }
}
export function savePrefs(prefs: UiPrefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch { /* 저장할 수 없어도 화면은 동작한다. */ }
}

/* ----- 강조: 마우스를 올리거나 초점을 둔 항목과 이어진 것만 또렷하게 ----- */
export type Hover = { type: 'entry' | 'instance' | 'group' | 'family'; id: string } | null;
export type Highlight = { instances: Set<string>; entries: Set<string>; groups: Set<string> } | null;

export function computeHighlight(data: LineageData, hover: Hover, groups: RefGroup[], treeRoot: string | null): Highlight {
  if (!hover || hover.type === 'family') return null;
  const result = { instances: new Set<string>(), entries: new Set<string>(), groups: new Set<string>() };
  if (hover.type === 'instance') {
    result.instances.add(hover.id);
    ancestors(data.instances, hover.id).forEach(item => result.instances.add(item.id));
    for (const group of groups) if (group.refs.some(ref => within(ref.source, hover.id))) result.groups.add(group.key);
    return result;
  }
  if (hover.type === 'entry') {
    result.entries.add(hover.id);
    for (const group of groups) if (group.refs.some(ref => ref.entry === hover.id)) result.groups.add(group.key);
    if (treeRoot && data.entries[hover.id]?.primary === treeRoot) subtree(data.instances, treeRoot).forEach(id => result.instances.add(id));
    return result;
  }
  const group = groups.find(item => item.key === hover.id);
  if (!group) return null;
  result.groups.add(group.key);
  for (const ref of group.refs) {
    result.instances.add(ref.source);
    ancestors(data.instances, ref.source).forEach(item => result.instances.add(item.id));
    if (ref.entry) result.entries.add(ref.entry);
  }
  return result;
}

export const hlClass = (set: Set<string> | undefined, id: string, active: boolean) => !active || !set ? '' : set.has(id) ? ' is-hl' : ' is-dim';
