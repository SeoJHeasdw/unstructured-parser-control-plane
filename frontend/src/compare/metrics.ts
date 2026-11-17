/**
 * 같은 원본을 두 번 파싱한 결과를 수치로 비교한다.
 * 정답 자료가 없으면 '무엇이 바뀌었나'(변화량)만 말할 수 있고, 정답 자료가 있으면 '무엇이 맞았나'(재현율)를 잰다.
 */
export type RunMetrics = {
  chars: number; lines: number; headings: number; tables: number; cells: number; images: number;
  numbers: Set<string>; docNumbers: Set<string>; broken: number; pages: number | null;
};

const UNIT = String.raw`(?:°C|℃|%RH|%|mg/mL|µg/mL|μg/mL|mL|mg|kg|g|µS/cm|μS/cm|ppm|ppb|CFU/mL|EU/mg|bar|mm/s|rpm|cm²|nm|V|Hz|분|시간|개월|일)`;
const NUMBER_UNIT = new RegExp(String.raw`[<>≤≥±]?\s?\d[\d,]*(?:\.\d+)?\s?(?:~\s?\d[\d,]*(?:\.\d+)?\s?)?${UNIT}`, 'g');
const DOC_NUMBER = /\b[A-Z]{2,5}-(?:[A-Z0-9]+-)*\d[A-Z0-9]*\b/g;
const squash = (value: string) => value.replace(/\s+/g, '').replace(/μ/g, 'µ').replace(/℃/g, '°C');

export function measure(markdown: string, locations?: { page: number | null }[]): RunMetrics {
  const rows = markdown.split('\n');
  let tables = 0, cells = 0, inTable = false;
  for (const raw of rows) {
    const line = raw.trim();
    const isRow = line.startsWith('|');
    if (isRow && !inTable) tables += 1;
    inTable = isRow;
    if (isRow && !/^\|?\s*:?-{3,}/.test(line)) cells += line.replace(/^\||\|$/g, '').split('|').length;
  }
  const pages = locations?.length ? new Set(locations.map(item => item.page).filter(page => page !== null)).size || null : null;
  return {
    chars: markdown.replace(/\s/g, '').length,
    lines: rows.filter(line => line.trim()).length,
    headings: rows.filter(line => /^ {0,3}#{1,6}\s/.test(line)).length,
    tables, cells,
    images: (markdown.match(/<!--\s*image\s*-->|!\[[^\]]*\]\(/g) ?? []).length,
    numbers: new Set((markdown.match(NUMBER_UNIT) ?? []).map(squash)),
    docNumbers: new Set(markdown.match(DOC_NUMBER) ?? []),
    broken: (markdown.match(/�|\(cid:\d+\)/g) ?? []).length,
    pages,
  };
}

export const lost = (before: Set<string>, after: Set<string>) => [...before].filter(item => !after.has(item));
export const gained = (before: Set<string>, after: Set<string>) => [...after].filter(item => !before.has(item));

/* ---------- 정답 자료(gold) 대조 ---------- */
export type Gold = {
  file_id?: string; title?: string;
  key_values?: { label?: string; value: string }[];
  tables?: { id?: string; caption?: string; header?: string[]; rows?: string[][] }[];
  captions?: { text: string }[];
  numbers_with_units?: string[];
  headings?: string[];
  text_snippets?: string[];
};
export type GoldCategory = { id: string; label: string; items: string[] };
export type GoldScore = { id: string; label: string; total: number; found: number; missing: string[] };

export function isGold(value: unknown): value is Gold {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const gold = value as Record<string, unknown>;
  return ['key_values', 'tables', 'captions', 'numbers_with_units', 'headings', 'text_snippets'].some(key => Array.isArray(gold[key]));
}

export function goldCategories(gold: Gold): GoldCategory[] {
  const cells = (gold.tables ?? []).flatMap(table => [...(table.header ?? []), ...(table.rows ?? []).flat()]).map(cell => String(cell ?? '').trim()).filter(Boolean);
  const out: GoldCategory[] = [
    { id: 'key_values', label: '핵심 값', items: (gold.key_values ?? []).map(item => String(item.value ?? '').trim()) },
    { id: 'cells', label: '표 칸 값', items: cells },
    { id: 'numbers', label: '숫자·단위', items: (gold.numbers_with_units ?? []).map(String) },
    { id: 'headings', label: '제목', items: (gold.headings ?? []).map(String) },
    { id: 'captions', label: '캡션', items: (gold.captions ?? []).map(item => String(item.text ?? '')) },
    { id: 'snippets', label: '문장', items: (gold.text_snippets ?? []).map(String) },
  ];
  return out.map(category => ({ ...category, items: [...new Set(category.items.filter(item => item.trim()))] })).filter(category => category.items.length);
}

/** 띄어쓰기는 무시하고, 정답 값이 결과 안에 그대로 있는지 본다. 위치·순서는 보지 않는다. */
export function scoreGold(markdown: string, categories: GoldCategory[]): GoldScore[] {
  const hay = squash(markdown);
  return categories.map(category => {
    const missing = category.items.filter(item => !hay.includes(squash(item)));
    return { id: category.id, label: category.label, total: category.items.length, found: category.items.length - missing.length, missing };
  });
}
