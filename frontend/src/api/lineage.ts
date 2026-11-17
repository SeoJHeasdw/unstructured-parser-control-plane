/** 문서 계보 조회(읽기 전용). 실제 파일 또는 예시 데이터로 계산한 버전·포함·참조 관계를 받는다. */
export type LineageSource = 'live' | 'example';
export type RefState = 'linked' | 'outdated' | 'missing' | 'ambiguous' | 'external';
export type StateCounts = Record<RefState, number>;
export type LnSignal = { code: string; label: string; text: string };
export type LnInstance = {
  id: string; doc_id: string; root: string; parent: string | null; depth: number; children: string[]; name: string; ext: string; kind: string; location: string;
  size: number; hash: string | null; detected: string | null; flags: string[]; uploaded_at: string | null; status: string | null; analysed: boolean;
  inspected_at: string | null; structure_state: string | null; family: string | null; entry: string | null; same_as: string | null; signals: LnSignal[]; version_label: string; links: number;
};
export type LnEntry = {
  id: string; family: string; instances: string[]; primary: string; label: string; signals: LnSignal[]; ext: string; uploaded_at: string | null;
  contained_only: boolean; duplicates: number; is_latest: boolean; co_latest: boolean; candidate: boolean; order: number; notes: string[];
};
export type LnReason = { code: string; label: string; detail: string };
export type LnConflict = { code: string; message: string; entries: string[] };
export type LnFamily = {
  id: string; title: string; docno: string | null; ext_family: string; formats: string[]; files: number; analysed: 'all' | 'partial' | 'none'; notes: string[]; related: string[]; entries: string[];
  latest: { status: 'confirmed' | 'hold' | 'single'; entry: string; reasons: LnReason[]; conflicts: LnConflict[]; candidates: string[] };
  counts: { files: number; versions: number; duplicates: number; contained: number; self_mentions: number; out: StateCounts; out_all: StateCounts; in: StateCounts };
  flags: string[];
};
export type LnCandidate = { family: string | null; entry: string | null; instance: string | null };
export type LnReference = {
  id: string; source: string; source_root: string; source_family: string | null; kind: string; target: string; location: string; evidence: string; state: RefState;
  match: string | null; family: string | null; entry: string | null; instance: string | null; candidates: LnCandidate[]; wanted: string | null; note: string;
};
export type LineageData = {
  source: LineageSource; as_of: string | null; generated_at: string;
  documents: { total: number; analysed: number; not_analysed: number; structure_errors: number };
  summary: { families: number; versioned: number; hold: number; contained: number; duplicates: number; references: StateCounts };
  families: LnFamily[]; entries: Record<string, LnEntry>; instances: Record<string, LnInstance>; references: LnReference[];
};

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

/** 화면이 깨지지 않도록 서로 가리키는 식별자까지 확인한다. */
export function isLineageData(body: unknown): body is LineageData {
  if (!isObject(body) || !Array.isArray(body.families) || !isObject(body.entries) || !isObject(body.instances) || !Array.isArray(body.references) || !isObject(body.summary) || !isObject(body.documents)) return false;
  const entries = body.entries as Record<string, unknown>; const instances = body.instances as Record<string, unknown>;
  const familyIds = new Set<string>();
  for (const family of body.families as unknown[]) {
    if (!isObject(family) || typeof family.id !== 'string' || typeof family.title !== 'string' || !Array.isArray(family.entries) || !family.entries.length || !isObject(family.latest) || !isObject(family.counts)) return false;
    for (const id of family.entries) { const entry = entries[id as string]; if (!isObject(entry) || !Array.isArray(entry.instances) || typeof entry.primary !== 'string' || !isObject(instances[entry.primary])) return false; }
    if (typeof family.latest.entry !== 'string' || !isObject(entries[family.latest.entry])) return false;
    familyIds.add(family.id);
  }
  for (const value of Object.values(instances)) if (!isObject(value) || typeof value.id !== 'string' || typeof value.name !== 'string' || !Array.isArray(value.children) || value.children.some(child => !isObject(instances[child as string]))) return false;
  for (const ref of body.references as unknown[]) {
    if (!isObject(ref) || typeof ref.source !== 'string' || !isObject(instances[ref.source]) || typeof ref.state !== 'string' || !Array.isArray(ref.candidates)) return false;
    if ((ref.family && !familyIds.has(ref.family as string)) || (ref.entry && !isObject(entries[ref.entry as string])) || (ref.instance && !isObject(instances[ref.instance as string]))) return false;
  }
  return true;
}

export async function getLineage(source: LineageSource, signal?: AbortSignal): Promise<LineageData> {
  const response = await fetch(`/api/lineage?source=${source}`, { signal });
  if (!response.ok) {
    let message = `문서 계보를 불러오지 못했습니다. (HTTP ${response.status})`;
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === 'string') message = body.detail; } catch { /* 상태 코드만 표시한다. */ }
    throw new Error(message);
  }
  let body: unknown;
  try { body = await response.json(); } catch { throw new Error('문서 계보 응답을 읽을 수 없습니다.'); }
  if (!isLineageData(body)) throw new Error('문서 계보 응답 형식을 확인할 수 없습니다.');
  return body;
}
