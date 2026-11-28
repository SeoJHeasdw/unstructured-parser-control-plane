import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ImageOff } from 'lucide-react';
import { Segmented } from './ui';
import { isNumeric, parseInline, parseMarkdown } from './markdown';
import type { Block, ListItem } from './markdown';
import './markdownView.css';

export type ResultMode = 'read' | 'raw';
const MODE_KEY = 'document-ops:result-view';

export function useResultMode(): [ResultMode, (mode: ResultMode) => void] {
  const [mode, setMode] = useState<ResultMode>(() => { try { return localStorage.getItem(MODE_KEY) === 'raw' ? 'raw' : 'read'; } catch { return 'read'; } });
  return [mode, next => { setMode(next); try { localStorage.setItem(MODE_KEY, next); } catch { } }];
}

export function ResultModeSwitch({ value, onChange }: { value: ResultMode; onChange: (mode: ResultMode) => void }) {
  return <Segmented<ResultMode> label="추출 결과 보기 방식" value={value} onChange={onChange}
    options={[{ id: 'read', label: '읽기 보기' }, { id: 'raw', label: 'Markdown 원문' }]} />;
}

const PAGE = 400; // 큰 결과도 화면이 멈추지 않게 나눠 그린다.

function Inline({ text }: { text: string }) {
  return <>{parseInline(text).map((span, index) => {
    let node: ReactNode = span.text;
    if (span.code) node = <code>{node}</code>;
    if (span.href) node = <span className="md-link" data-tip={span.href}>{node}</span>;
    if (span.strike) node = <s>{node}</s>;
    if (span.italic) node = <em>{node}</em>;
    if (span.bold) node = <strong>{node}</strong>;
    return <span key={index}>{node}</span>;
  })}</>;
}

type Tree = { item: ListItem; children: Tree[] };

function nest(items: ListItem[]): Tree[] {
  const root: Tree[] = [];
  const stack: { depth: number; children: Tree[] }[] = [{ depth: -1, children: root }];
  for (const item of items) {
    while (stack.length > 1 && stack[stack.length - 1].depth >= item.depth) stack.pop();
    const node = { item, children: [] };
    stack[stack.length - 1].children.push(node);
    stack.push({ depth: item.depth, children: node.children });
  }
  return root;
}

function List({ nodes }: { nodes: Tree[] }) {
  const ordered = nodes.every(node => node.item.ordered);
  const start = ordered ? parseInt(nodes[0]?.item.marker ?? '1', 10) : undefined;
  const items = nodes.map((node, index) => <li key={index} data-marker={ordered ? undefined : node.item.ordered ? node.item.marker : undefined}>
    <Inline text={node.item.text} />{node.children.length > 0 && <List nodes={node.children} />}
  </li>);
  return ordered ? <ol start={start && start !== 1 ? start : undefined}>{items}</ol> : <ul>{items}</ul>;
}

function Table({ block }: { block: Extract<Block, { kind: 'table' }> }) {
  const numeric = block.header.map((_, column) => {
    const values = block.rows.map(row => row[column]).filter(Boolean);
    return values.length > 0 && values.every(isNumeric);
  });
  const align = (column: number) => block.align[column] ?? (numeric[column] ? 'right' : undefined);
  return <div className="md-table-wrap" role="region" aria-label={`표 · ${block.rows.length}행 ${block.header.length}열`} tabIndex={0}>
    <table className="md-table">
      <thead><tr>{block.header.map((cell, c) => <th key={c} style={{ textAlign: align(c) }}><Inline text={cell} /></th>)}</tr></thead>
      <tbody>{block.rows.map((row, r) => <tr key={r}>{row.map((cell, c) =>
        <td key={c} style={{ textAlign: align(c) }} className={cell ? undefined : 'is-empty'}>{cell ? <Inline text={cell} /> : null}</td>)}</tr>)}</tbody>
    </table>
    <span className="md-table-size">{block.rows.length}행 × {block.header.length}열</span>
  </div>;
}

function render(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case 'heading': {
      const Tag = `h${Math.min(block.level + 1, 6)}` as 'h2';  // 화면 제목(h1) 아래에 둔다
      return <Tag key={key} className={`md-h md-h${block.level}`}><Inline text={block.text} /></Tag>;
    }
    case 'paragraph': return <p key={key} className="md-p"><Inline text={block.text} /></p>;
    case 'list': return <div key={key} className="md-list"><List nodes={nest(block.items)} /></div>;
    case 'table': return <Table key={key} block={block} />;
    case 'code': return <pre key={key} className="md-code">{block.text}</pre>;
    case 'figure': return <p key={key} className="md-figure"><ImageOff size={15} aria-hidden="true" />그림 자리{block.text ? ` · ${block.text}` : ''}<small>그림 안 글자는 이 자리에 없습니다</small></p>;
    case 'supplement': return <p key={key} className="md-supplement">아래는 파서가 놓쳐 콘솔이 원본에서 보충한 글자입니다. 원래 위치가 아닙니다.</p>;
    case 'comment': return <p key={key} className="md-comment"><code>{`<!-- ${block.text} -->`}</code></p>;
    case 'rule': return <hr key={key} className="md-rule" />;
    case 'quote': return <blockquote key={key} className="md-quote"><Inline text={block.text} /></blockquote>;
  }
}

export function MarkdownView({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);
  const [shown, setShown] = useState(PAGE);
  if (!blocks.length) return <p className="md-empty">텍스트 결과가 비어 있습니다.</p>;
  const tables = blocks.filter(block => block.kind === 'table').length;
  return <div className="md-view">
    {blocks.slice(0, shown).map(render)}
    {shown < blocks.length && <button type="button" className="lw-btn md-more" onClick={() => setShown(n => n + PAGE)}>
      다음 {Math.min(PAGE, blocks.length - shown)}개 블록 더 보기 <small>남은 {blocks.length - shown}개{tables ? ` · 표 포함` : ''}</small></button>}
  </div>;
}
