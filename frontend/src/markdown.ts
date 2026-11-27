/**
 * 파싱 결과 Markdown(Docling 출력 + 콘솔 보충 구획)을 읽기 보기용 블록으로 나눈다.
 * HTML로 바꿔 주입하지 않는다. 블록과 글자 조각만 만들고 React가 그린다(문서 안의 스크립트·링크가 실행되지 않는다).
 * 원문의 어떤 줄도 버리지 않는다: 해석하지 못한 줄은 문단으로, 주석은 작은 표시로 남긴다.
 */

export type Align = 'left' | 'center' | 'right' | null;
export type ListItem = { depth: number; ordered: boolean; marker: string; text: string };
export type Block =
  | { kind: 'heading'; level: number; text: string; line: number }
  | { kind: 'paragraph'; text: string; line: number }
  | { kind: 'list'; items: ListItem[]; line: number }
  | { kind: 'table'; header: string[]; rows: string[][]; align: Align[]; line: number }
  | { kind: 'code'; lang: string; text: string; line: number }
  | { kind: 'figure'; text: string; line: number }
  | { kind: 'supplement'; line: number }
  | { kind: 'comment'; text: string; line: number }
  | { kind: 'rule'; line: number }
  | { kind: 'quote'; text: string; line: number };

/** CommonMark ATX 제목: 0~3칸 들여쓰기, # 1~6개, 그 뒤 공백·탭(또는 줄 끝). '#LOT-7'·'    # 코드'는 제목이 아니다. */
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$/;
/** 닫는 # 묶음: 앞에 공백·탭이 있을 때만(또는 내용 전체가 #일 때). '# C#'의 #은 글자다. '\###'은 이스케이프라 글자다. */
const CLOSING = /(?:^|[ \t]+)#+[ \t]*$/;

/** 한 줄이 ATX 제목이면 단계와 글(닫는 #을 뺀 것). 표·코드 안의 줄인지는 parseMarkdown이 가른다. */
export function headingOf(line: string): { level: number; text: string } | null {
  const match = HEADING.exec(line);
  if (!match) return null;
  let text = match[2] ?? '';
  const closing = CLOSING.exec(text);
  if (closing) text = text.slice(0, closing.index);
  return { level: match[1].length, text: text.trim() };
}
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const SEPARATOR = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;
const COMMENT = /^\s*<!--\s*([\s\S]*?)\s*-->\s*$/;
const IMAGE = /^\s*!\[([^\]]*)\]\(([^)]*)\)\s*$/;
const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
export const SUPPLEMENT_MARK = 'docops:supplement';

/** 표 한 줄 → 칸. 이스케이프한 \| 는 칸 경계가 아니다. */
export function splitRow(line: string): string[] {
  let body = line.trim();
  if (body.startsWith('|')) body = body.slice(1);
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1);
  const cells: string[] = [];
  let current = '';
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === '\\' && body[i + 1] === '|') { current += '|'; i++; continue; }
    if (ch === '|') { cells.push(current.trim()); current = ''; continue; }
    current += ch;
  }
  cells.push(current.trim());
  return cells;
}

function alignOf(cell: string): Align {
  const left = cell.startsWith(':'), right = cell.endsWith(':');
  return left && right ? 'center' : right ? 'right' : left ? 'left' : null;
}

const isTableStart = (lines: string[], i: number) =>
  lines[i].trimStart().startsWith('|') && i + 1 < lines.length && lines[i + 1].includes('-') && SEPARATOR.test(lines[i + 1]);

export function parseMarkdown(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const number = i + 1;
    if (!line.trim()) { i++; continue; }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(fence[1]) && FENCE.test(lines[i]))) body.push(lines[i++]);
      i++;
      blocks.push({ kind: 'code', lang: fence[2], text: body.join('\n'), line: number });
      continue;
    }
    const comment = COMMENT.exec(line);
    if (comment) {
      const text = comment[1];
      blocks.push(text === 'image' ? { kind: 'figure', text: '', line: number }
        : text === SUPPLEMENT_MARK ? { kind: 'supplement', line: number } : { kind: 'comment', text, line: number });
      i++;
      continue;
    }
    const image = IMAGE.exec(line);
    if (image) { blocks.push({ kind: 'figure', text: image[1], line: number }); i++; continue; }
    const heading = headingOf(line);
    if (heading) { blocks.push({ kind: 'heading', level: heading.level, text: heading.text, line: number }); i++; continue; }
    if (isTableStart(lines, i)) {
      const header = splitRow(line);
      const align = splitRow(lines[i + 1]).map(alignOf);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trimStart().startsWith('|')) rows.push(splitRow(lines[i++]));
      const width = Math.max(header.length, ...rows.map(row => row.length));
      const pad = (row: string[]) => row.concat(Array(width - row.length).fill(''));
      blocks.push({ kind: 'table', header: pad(header), rows: rows.map(pad), align: Array.from({ length: width }, (_, c) => align[c] ?? null), line: number });
      continue;
    }
    if (RULE.test(line)) { blocks.push({ kind: 'rule', line: number }); i++; continue; }
    if (LIST.test(line)) {
      const items: ListItem[] = [];
      const indents: number[] = [];
      while (i < lines.length && lines[i].trim() && !isTableStart(lines, i)) {
        const match = LIST.exec(lines[i]);
        if (!match) {
          // 목록 항목에 이어지는 줄(들여 쓴 줄)은 앞 항목에 붙인다. 표·제목·주석이 오면 목록을 끝낸다.
          if (HEADING.test(lines[i]) || COMMENT.test(lines[i]) || !/^\s/.test(lines[i]) || !items.length) break;
          items[items.length - 1].text += '\n' + lines[i].trim();
          i++;
          continue;
        }
        const indent = match[1].replace(/\t/g, '    ').length;
        while (indents.length && indents[indents.length - 1] > indent) indents.pop();
        if (!indents.length || indents[indents.length - 1] < indent) indents.push(indent);
        items.push({ depth: indents.length - 1, ordered: /\d/.test(match[2]), marker: match[2], text: match[3] });
        i++;
      }
      blocks.push({ kind: 'list', items, line: number });
      continue;
    }
    if (line.trimStart().startsWith('>')) {
      const body: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith('>')) body.push(lines[i++].trimStart().replace(/^>\s?/, ''));
      blocks.push({ kind: 'quote', text: body.join('\n'), line: number });
      continue;
    }
    const body: string[] = [];
    while (i < lines.length && lines[i].trim() && !isTableStart(lines, i) && !HEADING.test(lines[i]) && !COMMENT.test(lines[i])
      && !FENCE.test(lines[i]) && !(body.length && LIST.test(lines[i]))) body.push(lines[i++]);
    blocks.push({ kind: 'paragraph', text: body.join('\n'), line: number });
  }
  return blocks;
}

export type Span = { text: string; bold?: boolean; italic?: boolean; code?: boolean; strike?: boolean; href?: string };

const INLINE = /(`+)([\s\S]*?)\1|\*\*([\s\S]+?)\*\*|__([\s\S]+?)__|~~([\s\S]+?)~~|\*([^*\s][^*]*?)\*|(?<![\w\\])_([^_\s][^_]*?)_(?!\w)|\[([^\]]+)\]\(([^)\s]+)\)/g;
const ESCAPE = /\\([\\`*_{}[\]()#+\-.!|<>~])/g;

/** 굵게·기울임·코드·취소선·링크만 알아본다. 링크는 주소를 보여 줄 뿐 열지 않는다. */
export function parseInline(text: string, inherited: Omit<Span, 'text'> = {}): Span[] {
  const spans: Span[] = [];
  let last = 0;
  const push = (value: string, style: Omit<Span, 'text'> = {}) => {
    if (value) spans.push({ text: style.code ? value : value.replace(ESCAPE, '$1'), ...inherited, ...style });
  };
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > 0 && text[index - 1] === '\\') continue;
    push(text.slice(last, index));
    if (match[1]) push(match[2], { code: true });
    else if (match[3] ?? match[4]) spans.push(...parseInline((match[3] ?? match[4])!, { ...inherited, bold: true }));
    else if (match[5]) spans.push(...parseInline(match[5], { ...inherited, strike: true }));
    else if (match[6] ?? match[7]) spans.push(...parseInline((match[6] ?? match[7])!, { ...inherited, italic: true }));
    else if (match[8]) push(match[8], { href: match[9] });
    last = index + match[0].length;
  }
  push(text.slice(last));
  return spans;
}

/** 숫자(단위 포함)만 든 칸. 오른쪽 정렬해 자릿수를 맞춘다. */
export const isNumeric = (cell: string) => /^[-−+±≤≥<>~]?\s*\d[\d,]*(\.\d+)?\s*(%|‰|℃|°C|[a-zA-Zµμ²³/·]{1,8})?$/.test(cell.trim());

/** 화면 폭으로 센 글자 수(한글·한자·전각은 2칸). 표 칸 너비 비율에 쓴다. */
export function displayWidth(text: string) {
  let width = 0;
  for (const ch of text) width += /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/.test(ch) ? 2 : 1;
  return width;
}

export type TableLine = { role: 'head' | 'rule' | 'row'; cells: string[]; columns: string };
/** 줄 단위 화면(원문 대조)이 쓰는 줄 해석. 읽기 보기와 같은 블록 해석기(parseMarkdown)에서 나온다. */
export type LineKind = TableLine | { role: 'heading'; level: number; text: string } | { role: 'code' };

/** 줄 번호 → 표 줄·제목 줄·코드 줄. 같은 표의 줄은 같은 칸 너비를 쓴다. 코드 블록 안의 '# …'은 제목이 아니다. */
export function lineKinds(markdown: string): Map<number, LineKind> {
  const result = new Map<number, LineKind>();
  for (const block of parseMarkdown(markdown)) {
    if (block.kind === 'heading') result.set(block.line, { role: 'heading', level: block.level, text: block.text });
    else if (block.kind === 'code') {
      const lines = block.text ? block.text.split('\n').length : 0;
      for (let n = block.line; n <= block.line + lines + 1; n++) result.set(n, { role: 'code' });
    } else if (block.kind === 'table') {
      const widths = block.header.map((cell, c) => Math.min(40, Math.max(3, displayWidth(cell), ...block.rows.map(row => displayWidth(row[c] ?? '')))));
      const columns = widths.map(w => `minmax(0, ${w}fr)`).join(' ');
      result.set(block.line, { role: 'head', cells: block.header, columns });
      result.set(block.line + 1, { role: 'rule', cells: [], columns });
      block.rows.forEach((row, index) => result.set(block.line + 2 + index, { role: 'row', cells: row, columns }));
    }
  }
  return result;
}

/** 줄 번호 → 표 줄 정보(lineKinds의 표 줄만). */
export function tableLines(markdown: string): Map<number, TableLine> {
  const result = new Map<number, TableLine>();
  for (const [line, kind] of lineKinds(markdown)) if (kind.role === 'head' || kind.role === 'rule' || kind.role === 'row') result.set(line, kind);
  return result;
}
