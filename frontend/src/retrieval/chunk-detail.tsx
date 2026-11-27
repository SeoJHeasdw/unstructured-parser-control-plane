import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowUpRight, Pencil, Ruler } from 'lucide-react';
import type { Chunk, ChunkSource, EmbedConnection, ModelSpec, StrategyParams, TokenMeasure } from '../api/retrieval';
import { measureTokens } from '../api/retrieval';
import { ListBox, Modal, Tabs } from '../ui';
import { workspaceHref } from '../navigation';
import { ELEMENT_META } from './elements';
import { DocChunks, chunkElementIds, chunksByElement, elementName, kindLabel, outcomePhrase, pathText } from './chunk-board';
import type { Column } from './chunk-board';
import { IMAGE_POLICY, STRATEGY_HINT, STRATEGY_LABEL, TABLE_POLICY, TOKEN_NOTE, describeParams, errorText, flagMeta, fmtInt, isBaseline } from './shared';

/**
 * 청크 원문: 마크다운 표 줄('|')은 표로, '#' 줄은 제목으로, 나머지는 문단으로 보여 준다.
 * 머리행은 바로 아래 구분 줄('| --- |')이 있을 때만 머리행으로 그린다. 잘린 표 조각은 머리행 없이 보인다.
 */
const isTableLine = (line: string) => line.trimStart().startsWith('|');
const isRule = (line: string) => /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.includes('-');
const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
export function ChunkText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length) {
    if (isTableLine(lines[i])) {
      const block: string[] = [];
      while (i < lines.length && isTableLine(lines[i])) block.push(lines[i++]);
      const hasHead = block.length > 1 && isRule(block[1]) && !isRule(block[0]);
      const rows = block.filter(line => !isRule(line)).map(cells);
      const [head, body] = hasHead ? [rows[0], rows.slice(1)] : [null, rows];
      blocks.push(<div key={`t${i}`} className="cb-mdtable"><table>
        {head && <thead><tr>{head.map((cell, k) => <th key={k}>{cell}</th>)}</tr></thead>}
        <tbody>{body.map((row, r) => <tr key={r}>{row.map((cell, k) => <td key={k}>{cell}</td>)}</tr>)}</tbody>
      </table></div>);
      continue;
    }
    const heading = /^#{1,6}\s+(.*)$/.exec(lines[i].trim());
    if (heading) { blocks.push(<p key={`h${i}`} className="cb-para is-h">{heading[1]}</p>); i++; continue; }
    const start = i;
    while (i < lines.length && !isTableLine(lines[i]) && !/^#{1,6}\s/.test(lines[i].trim())) i++;
    const para = lines.slice(start, i).join('\n').trim();
    if (para) blocks.push(<p key={`p${start}`} className="cb-para">{para}</p>);
  }
  return <div className="cb-text">{blocks}</div>;
}

/** 목록에서 바로 보여 줄 문제 표시. 나머지 표시는 오른쪽 상세에서 설명한다. */
const LIST_FLAGS = ['unverified', 'over-limit', 'table-cut', 'table-no-header', 'caption-detached'];
const SEVERITY_WORD = { high: '높음', medium: '보통', low: '낮음' } as const;
const uniqueKinds = (chunk: Chunk) => [...new Set(chunk.element_kinds ?? [])].filter(kind => kind !== 'heading');

export type StrategyTab = 'chunks' | 'doc' | 'settings';
type StrategyProps = {
  source: ChunkSource; column: Column; tab: StrategyTab; index: number;
  onTab: (tab: StrategyTab) => void; onIndex: (index: number) => void; onClose: () => void; onEdit: () => void;
  measure: ReactNode;
};
/** 전략 하나의 상세: 청크(목록 + 상세) · 문서 위 청크 · 설정. */
export function StrategyModal({ source, column, tab, index, onTab, onIndex, onClose, onEdit, measure }: StrategyProps) {
  const result = column.result;
  const chunks = result.chunks;
  const at = Math.min(Math.max(0, index), Math.max(0, chunks.length - 1));
  const byEl = useMemo(() => chunksByElement(result, source.elements), [result, source.elements]);
  const subtitle = [column.params ? describeParams(column.params) : '', `청크 ${fmtInt(chunks.length)}개`, result.parents?.length ? `맥락 ${fmtInt(result.parents.length)}개` : ''].filter(Boolean).join(' · ');
  const tabs = <Tabs<StrategyTab> label="전략 상세" value={tab} onChange={onTab}
    items={[{ id: 'chunks', label: '청크', badge: chunks.length }, { id: 'doc', label: '문서 위 청크' }, { id: 'settings', label: '설정' }]} />;
  const title = <>{column.name}{isBaseline(column.kind) && <span className="cb-base cb-base-lg">기준선</span>}</>;

  let body: ReactNode;
  if (result.error) body = <div className="ui-empty" role="alert"><b>나누지 못했습니다</b>{result.error}</div>;
  else if (tab === 'chunks') body = !chunks.length ? <div className="ui-empty"><b>청크가 없습니다</b></div> : <div className="ui-split">
    <div className="cb-listcol"><ListBox label="청크 목록" items={chunks} getKey={chunk => String(chunk.index)} value={String(chunks[at].index)}
      onChange={key => onIndex(chunks.findIndex(chunk => String(chunk.index) === key))}
      render={(chunk, { selected }) => {
        const i = chunks.indexOf(chunk);
        const flag = chunk.flags.find(f => LIST_FLAGS.includes(f));
        return <span className={`cb-copt${selected ? ' is-on' : ''}`}>
          <b className="cb-copt-no">{i + 1}</b>
          <span className="cb-copt-main">
            <span className="cb-copt-path">{chunk.heading_path.length ? chunk.heading_path[chunk.heading_path.length - 1] : '제목 없음'}</span>
            {flag && <span className="cb-copt-flag">{flagMeta(flag).label}</span>}
          </span>
          <span className="cb-swatches" aria-hidden="true">{uniqueKinds(chunk).map(kind => <i key={kind} style={{ background: ELEMENT_META[kind].color }} />)}</span>
          <span className={`cb-copt-len${chunk.flags.includes('over-limit') ? ' is-bad' : ''}`}>{fmtInt(chunk.chars)}</span>
        </span>;
      }} /></div>
    <ChunkPane source={source} column={column} chunk={chunks[at]} number={at + 1} byEl={byEl} />
  </div>;
  else if (tab === 'doc') body = <div className="cb-doc-scroll"><DocChunks source={source} result={result} name={column.name} picked={at} onPick={i => { onIndex(i); onTab('chunks'); }} /></div>;
  else body = <Settings column={column} onEdit={onEdit} />;

  return <Modal open onClose={onClose} size="xl" flush title={title} subtitle={subtitle} tabs={tabs} extra={measure}>{body}</Modal>;
}

function ChunkPane({ source, column, chunk, number, byEl }: { source: ChunkSource; column: Column; chunk: Chunk; number: number; byEl: Map<string, number[]> }) {
  const result = column.result;
  const els = chunkElementIds(chunk, source.elements).map(id => source.elements.find(el => el.id === id)).filter((el): el is NonNullable<typeof el> => !!el);
  const parent = chunk.parent !== null && chunk.parent !== undefined ? result.parents?.[chunk.parent] : undefined;
  const regions = (chunk.regions ?? []).map(region => 'page' in region ? `${region.page}쪽` : `시트 ${region.sheet}`);
  const meta = [`${fmtInt(chunk.chars)}자`, `약 ${fmtInt(chunk.est_tokens)}토큰`, regions.length ? regions.slice(0, 4).join('·') + (regions.length > 4 ? ` 외 ${regions.length - 4}` : '') : chunk.page ? `${chunk.page}쪽` : '', pathText(chunk.heading_path)].filter(Boolean).join(' · ');
  return <div className="cb-pane" aria-label={`${number}번 청크`}>
    <h3 className="cb-pane-title">{number}번 청크</h3>
    <p className="cb-pane-meta">{meta}</p>
    {source.run_id && <p className="cb-pane-meta" data-tip={`본문 SHA-256 ${source.text_sha256 ?? '-'}`}>실행 {source.run_id.slice(0, 8)}{source.is_stale ? ' · 이전 성공본' : ''}{source.qc?.label ? ` · 문서 판정 ${source.qc.label}` : ''}</p>}
    {!!chunk.qc?.length && source.doc_id && <section className="cb-qc" aria-label="확인 안 된 지점">
      <h4 className="cb-h4">확인 안 된 지점 {fmtInt(chunk.qc_total ?? chunk.qc.length)}</h4>
      <ul>{chunk.qc.map(spot => <li key={spot.id ?? spot.key}>
        <b className={`cb-qc-sev is-${spot.severity}`}>{spot.key} · {SEVERITY_WORD[spot.severity]}</b>
        <span>{spot.message}{spot.source_layer === 'pdf_hidden_layer' ? ' (보이지 않는 글자 층)' : ''}</span>
        <a href={workspaceHref({ page: 'live', doc: source.doc_id!, review: 'source', focus: { check: spot.id ?? spot.key, run: source.run_id ?? undefined,
          page: spot.page ?? undefined, sheet: spot.sheet ?? undefined, cell: spot.cell ?? undefined, line: spot.line ?? undefined } })}>원문 대조<ArrowUpRight size={13} aria-hidden="true" /></a>
      </li>)}</ul>
    </section>}
    {parent && <p className="cb-pane-meta">답변 맥락 {(chunk.parent ?? 0) + 1}번 · {fmtInt(parent.chars)}자</p>}
    {chunk.flags.length > 0 && <ul className="cb-flag-list">{chunk.flags.map(flag => {
      const m = flagMeta(flag);
      return <li key={flag}><b className={m.tone === 'bad' || m.tone === 'warn' ? 'is-bad' : ''}>{m.label}</b><span>{m.desc}</span></li>;
    })}</ul>}
    <ChunkText text={chunk.text} />
    {els.length > 0 && <>
      <h4 className="cb-h4">담긴 요소 {fmtInt(els.length)}</h4>
      <ul className="cb-els">{els.map(el => {
        const phrase = outcomePhrase(el, result.outcomes?.[el.id], byEl.get(el.id)?.length ?? 0);
        return <li key={el.id}><i style={{ background: ELEMENT_META[el.kind].color }} /><span className="cb-els-kind">{kindLabel(el.kind)}</span>
          <span className="cb-els-name">{elementName(el, source.text, 60)}</span><b className={phrase.bad ? 'is-bad' : ''}>{phrase.text}</b></li>;
      })}</ul>
    </>}
  </div>;
}

/** 설정을 말로 풀어 쓴다. */
export function paramLines(kind: Column['kind'], p: StrategyParams | undefined): [string, string][] {
  if (!kind || !p) return [];
  const unit = p.unit === 'chars' ? '자' : '토큰';
  const n = (v: number | undefined) => `${fmtInt(v ?? 0)}${unit}`;
  const lines: [string, string][] = [['방식', STRATEGY_LABEL[kind]]];
  if (kind === 'parent_child') lines.push(['크기', `찾을 때 ${n(p.size)} · 답할 때 ${n(p.parent_size)} 맥락`]);
  else if (kind === 'page') lines.push(['크기', `쪽마다 하나, ${n(p.size)}를 넘으면 요소 경계에서 나눔`]);
  else if (kind === 'semantic') {
    lines.push(['크기', `${n(p.size)}까지, ${n(p.min_size)} 미만 묶음은 다음 묶음과 합침`]);
    lines.push(['경계', `이웃 문장 거리가 문서에서 상위 ${100 - (p.breakpoint ?? 90)}%인 곳 · 앞뒤 ${p.buffer ?? 1}문장을 함께 비교`]);
    lines.push(['임베딩 모델', p.model || '임베딩 연결의 첫 모델']);
    lines.push(['표·코드', '통째로 두고 위 제목과 함께']);
    return lines;
  } else lines.push(['크기', `${n(p.size)}까지`]);
  if (p.overlap) lines.push(['겹침', `앞 청크와 ${n(p.overlap)}`]);
  if (p.overlap_sentences) lines.push(['겹침', `앞 묶음과 ${p.overlap_sentences}문장`]);
  if (p.merge_small) lines.push(['작은 절', `${n(p.min_size)} 미만이면 이웃 절과 합침`]);
  if (isBaseline(kind)) { lines.push(['표·그림·캡션', '구분하지 않고 글자로만 자름']); return lines; }
  lines.push(['표', p.table === 'rows' ? `${p.table_rows ?? 5}행씩 묶고 묶음마다 머리행 반복` : TABLE_POLICY[p.table ?? 'whole']]);
  lines.push(['그림', IMAGE_POLICY[p.image ?? 'caption']]);
  lines.push(['캡션', p.attach_caption === false ? '따로 둠' : '대상과 같은 청크에']);
  lines.push(['반복 머리말·꼬리말', p.drop_furniture === false ? '그대로 둠' : '제거']);
  return lines;
}

function Settings({ column, onEdit }: { column: Column; onEdit: () => void }) {
  return <div className="cb-settings">
    {column.kind && <p className="cb-settings-hint">{STRATEGY_HINT[column.kind]}</p>}
    <dl className="cb-dl">{paramLines(column.kind, column.params).map(([k, v], i) => <div key={`${k}${i}`}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
    <button type="button" data-strategy-action="edit" className="button-secondary cb-btn" onClick={onEdit}><Pencil size={14} /> 수정</button>
  </div>;
}

/* ---------- 토큰 실측: 외부 모델 호출이라 누를 때만 보낸다 ---------- */
type MeasureProps = {
  column: Column; connections: EmbedConnection[]; specs: ModelSpec[]; conn: string; model: string;
  onPick: (conn: string, model: string) => void; onClose: () => void;
};
export function TokenModal({ column, connections, specs, conn: connKey, model: modelId, onPick, onClose }: MeasureProps) {
  const conn = connections.find(c => c.key === connKey) ?? connections[0];
  const models = conn?.models.length ? conn.models : specs.map(s => s.id);
  const model = models.includes(modelId) ? modelId : models[0] ?? '';
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [measured, setMeasured] = useState<{ result: TokenMeasure; picks: number[] } | null>(null);
  /* 표본: 가장 긴 청크 다섯 개와 길이 중앙 청크 하나 */
  const picks = useMemo(() => {
    const order = column.result.chunks.map((chunk, i) => ({ i, chars: chunk.chars })).sort((a, b) => b.chars - a.chars);
    const out = order.slice(0, 5).map(o => o.i);
    const mid = order[Math.floor(order.length / 2)];
    if (mid && !out.includes(mid.i)) out.push(mid.i);
    return out.filter(i => column.result.chunks[i].text.length <= 60_000);
  }, [column]);
  const run = async () => {
    if (!conn || !model || !picks.length) return;
    setBusy(true); setError('');
    try { setMeasured({ result: await measureTokens(conn.key, model, picks.map(i => column.result.chunks[i].text)), picks }); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  return <Modal open onClose={onClose} size="md" title="토큰 실측" subtitle={`${column.name} · 표본 청크 ${fmtInt(picks.length)}개`}
    footer={<><button type="button" className="button-quiet cb-btn" onClick={onClose}>전략 상세로</button><span className="ui-foot-note">표본을 연결된 임베딩 모델에 보냅니다.</span>
      <button type="button" className="button-primary cb-btn" disabled={busy || !model || !picks.length} onClick={() => void run()}><Ruler size={14} /> {busy ? '재는 중…' : '재기'}</button></>}>
    <div className="cb-measure-bar">
      <label className="cb-field"><span>연결</span><select aria-label="임베딩 연결" value={conn?.key ?? ''} onChange={e => onPick(e.target.value, '')}>{connections.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>
      <label className="cb-field"><span>모델</span><select aria-label="모델" value={model} onChange={e => onPick(conn?.key ?? '', e.target.value)}>{models.map(m => <option key={m} value={m}>{m}</option>)}</select></label>
    </div>
    {error && <p className="cb-error" role="alert">{error}</p>}
    {measured && <>
      {!measured.result.usage_reported && <p className="cb-note">이 서비스는 토큰 수를 돌려주지 않습니다.</p>}
      <table className="cb-plain"><thead><tr><th>청크</th><th className="num">추정</th><th className="num">실측</th><th className="num">실측 ÷ 추정</th><th>상태</th></tr></thead>
        <tbody>{measured.result.items.map((item, k) => <tr key={k}>
          <td>{(measured.picks[k] ?? 0) + 1}번</td><td className="num">{fmtInt(item.est_tokens)}</td><td className="num">{fmtInt(item.tokens)}</td>
          <td className="num">{item.tokens && item.est_tokens ? (item.tokens / item.est_tokens).toFixed(2) : '—'}</td>
          <td className={item.error ? 'is-bad' : ''}>{item.error ? (item.over_limit ? '입력 한도 초과' : item.error) : '측정'}</td>
        </tr>)}</tbody></table>
    </>}
    <p className="cb-note">{TOKEN_NOTE}</p>
  </Modal>;
}
