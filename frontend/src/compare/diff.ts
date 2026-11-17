export const LINE_LIMIT = 50_000;
const EDIT_LIMIT = 384;
const LOOKAHEAD = 24;
type Match = [number, number];
type Part = { text: string; changed: boolean };

export function lines(text: string): string[] {
  return text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
}

function nearbyMatches(left: string[], right: string[]): Match[] {
  const matches: Match[] = [];
  let i = 0, j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) { matches.push([i++, j++]); continue; }
    let found = false;
    for (let distance = 1; distance <= LOOKAHEAD; distance++) {
      if (left[i + distance] === right[j]) { i += distance; found = true; break; }
      if (left[i] === right[j + distance]) { j += distance; found = true; break; }
    }
    if (!found) { i++; j++; }
  }
  return matches;
}

/** Ordered Myers matches with bounded trace space for large replacements. */
function matchesOf(left: string[], right: string[]): Match[] {
  if (!left.length || !right.length) return [];
  const trace: Map<number, number>[] = [];
  let frontier = new Map([[1, 0]]);
  for (let distance = 0; distance <= Math.min(EDIT_LIMIT, left.length + right.length); distance++) {
    trace.push(frontier);
    const next = new Map<number, number>();
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      const before = frontier.get(diagonal - 1) ?? -1;
      const after = frontier.get(diagonal + 1) ?? -1;
      let x = diagonal === -distance || (diagonal !== distance && before < after) ? after : before + 1;
      let y = x - diagonal;
      while (x < left.length && y < right.length && left[x] === right[y]) { x++; y++; }
      next.set(diagonal, x);
      if (x < left.length || y < right.length) continue;

      const matches: Match[] = [];
      for (let step = distance; step >= 0; step--) {
        const history = trace[step], k = x - y;
        const low = history.get(k - 1) ?? -1;
        const high = history.get(k + 1) ?? -1;
        const previous = k === -step || (k !== step && low < high) ? k + 1 : k - 1;
        const lastX = history.get(previous) ?? 0;
        const lastY = lastX - previous;
        while (x > lastX && y > lastY) matches.push([--x, --y]);
        x = lastX;
        y = lastY;
      }
      return matches.reverse();
    }
    frontier = next;
  }
  return nearbyMatches(left, right);
}

type Entry = { text: string; line: number };
export type Diagnostic = 'number' | 'reference' | 'table';
export const diagnosticLabels: Record<Diagnostic, string> = {
  number: '수치·단위', reference: '문서번호·Rev', table: '표 셀',
};
export type DiffRow = {
  left?: Entry; right?: Entry; kind: 'same' | 'changed' | 'removed' | 'added';
  notes?: { type: Diagnostic; label: string; detail?: string }[];
  columns?: number[];
};

const REFERENCE = /\b(?:[A-Z][A-Z0-9]*(?:-\p{L}[\p{L}\d]*|-\d[\p{L}\d]*)+-?\d[\p{L}\d-]*|REV\s*\.?\s*[0-9][\d.]*)(?![\p{L}\d])/giu;
const NUMBER = /[+−-]?\d+(?:[,.]\d+)*(?:\s?(?:µg|μg|mcg|kg|mg|g|mL|ml|L|mm|cm|m|ppm|ppb|rpm|kPa|bar|Pa|°[CF]|℃|%|시간|분|초|일|회|개)(?![\p{L}\d]))?/gu;
const summarize = (tokens: string[]) => tokens.slice(0, 4).join(', ') + (tokens.length > 4 ? ' 외' : '');
const changes = (before: string[], after: string[]) => {
  const retained = matchesOf(before, after);
  const left = new Set(retained.map(([i]) => i));
  const right = new Set(retained.map(([, j]) => j));
  const from = before.filter((_, i) => !left.has(i));
  const to = after.filter((_, i) => !right.has(i));
  return [from, to] as const;
};

function tableCells(text: string): string[] | undefined {
  const line = text.trim();
  if (!line.includes('|')) return;
  const cells = line.replace(/^\|/, '').replace(/(?<!\\)\|$/, '').split(/(?<!\\)\|/).map(cell => cell.trim());
  if (cells.length < 2 || cells.every(cell => /^:?-+:?$/.test(cell))) return;
  if (!line.startsWith('|') && !line.endsWith('|') && !/\s\|\s/.test(line)) return;
  return cells;
}

function diagnose(row: DiffRow): DiffRow {
  const left = row.left?.text ?? '', right = row.right?.text ?? '';
  const notes: NonNullable<DiffRow['notes']> = [];
  const lo = tableCells(left), ro = tableCells(right);
  if ((lo || ro) && (!left || !right || (lo && ro))) {
    const columns = Array.from({ length: Math.max(lo?.length ?? 0, ro?.length ?? 0) }, (_, i) => i)
      .filter(i => (lo?.[i] ?? '') !== (ro?.[i] ?? ''));
    if (columns.length) {
      row.columns = columns;
      const missing = columns.some(i => !!lo?.[i] && !ro?.[i]);
      notes.push({ type: 'table', label: !lo ? '표 셀 추가' : missing ? '표 셀 누락' : '표 셀 변경',
        detail: columns.length === 1 ? `${lo?.[columns[0]] || '빈 셀'} → ${ro?.[columns[0]] || '빈 셀'}` : `${columns.length}개 셀` });
    }
  }
  const beforeRefs = left.match(REFERENCE) ?? [], afterRefs = right.match(REFERENCE) ?? [];
  const beforeNums = left.replace(REFERENCE, '').match(NUMBER) ?? [], afterNums = right.replace(REFERENCE, '').match(NUMBER) ?? [];
  for (const [type, before, after] of [['reference', beforeRefs, afterRefs], ['number', beforeNums, afterNums]] as const) {
    if (!before.length && !after.length) continue;
    const [from, to] = changes(before, after);
    if (from.length || to.length) notes.push({ type, label: diagnosticLabels[type],
      detail: `${summarize(from) || '없음'} → ${summarize(to) || '없음'}` });
  }
  row.notes = notes;
  return row;
}

export function alignResults(left: string[], right: string[]): DiffRow[] {
  const matches = matchesOf(left.map(line => line.trim()), right.map(line => line.trim()));
  const rows: DiffRow[] = [];
  let i = 0, j = 0;
  for (const [nextLeft, nextRight] of [...matches, [left.length, right.length] as Match]) {
    while (i < nextLeft || j < nextRight) {
      const a = i < nextLeft ? { text: left[i], line: ++i } : undefined;
      const b = j < nextRight ? { text: right[j], line: ++j } : undefined;
      rows.push(diagnose({ left: a, right: b, kind: a && b ? 'changed' : a ? 'removed' : 'added' }));
    }
    if (i < left.length && j < right.length) {
      rows.push({ left: { text: left[i], line: ++i }, right: { text: right[j], line: ++j }, kind: 'same' });
    }
  }
  return rows;
}

export function highlightParts(left: string, right: string): [Part[], Part[]] {
  const tokenize = (text: string) => text.match(/\s+|[\p{L}\p{N}]+|[^\s]/gu) ?? [];
  if (left.length + right.length > 12_000) return [[{ text: left, changed: true }], [{ text: right, changed: true }]];
  const a = tokenize(left), b = tokenize(right);
  const matches = matchesOf(a, b);
  const from = new Set(matches.map(([i]) => i)), to = new Set(matches.map(([, j]) => j));
  const pieces = (tokens: string[], common: Set<number>) => {
    const result: Part[] = [];
    tokens.forEach((text, index) => {
      const changed = !common.has(index), last = result.at(-1);
      if (last?.changed === changed) last.text += text;
      else result.push({ text, changed });
    });
    return result;
  };
  return [pieces(a, from), pieces(b, to)];
}
