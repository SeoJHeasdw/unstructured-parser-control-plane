import type { ReactNode } from 'react';
import { ArrowRight, X } from 'lucide-react';
import { CHILD_KIND, FLAG, LINK_KIND } from '../StructurePanel';
import type { LineageData, LnFamily } from '../api/lineage';
import { LATEST_META, MATCH_LABEL, STATE_META, holderText, sizeText, targetText, timeText } from './model';
import type { Pin } from './FamilyView';
import { entryTone } from './FamilyView';

type Props = { data: LineageData; pin: Pin; current: LnFamily | null; onClose: () => void; onFamily: (id: string, entry?: string) => void };
const KICKER = { entry: '판', instance: '파일', group: '참조', family: '문서군' };

/** 클릭으로 고정한 항목의 상세. X 또는 Escape로 닫는다. */
export function DetailPanel({ data, pin, current, onClose, onFamily }: Props) {
  const familyOf = (id: string | null | undefined) => id ? data.families.find(item => item.id === id) ?? null : null;
  const goFamily = (id: string | null | undefined, entry?: string | null, label = '이 문서군 보기') => {
    if (!id || (current?.id === id && !entry)) return null;
    return <button className="ln-go" onClick={() => onFamily(id, entry ?? undefined)}>{label} <ArrowRight size={13} /></button>;
  };
  let title = ''; let body: ReactNode = null;

  if (pin.type === 'entry' && data.entries[pin.id]) {
    const entry = data.entries[pin.id];
    const family = familyOf(entry.family)!;
    const status = family.latest.status === 'hold' ? (entry.is_latest ? '임시 최신(판단 보류)' : entry.candidate ? '최신 후보(판단 보류)' : '이전 판') : entry.is_latest ? (family.entries.length > 1 ? '최신' : '단일 판') : entry.co_latest ? '최신 · 다른 형식' : '이전 판';
    const conflicts = entry.is_latest ? family.latest.conflicts : family.latest.conflicts.filter(conflict => conflict.entries.includes(entry.id));
    title = `${entry.label}`;
    body = <>
      <p className="ln-panel-sub">{family.title} · <span className={`ln-state is-${entryTone(family, entry)}`}>{status}</span></p>
      {entry.signals.length > 0 && <div className="ln-panel-chips">{entry.signals.map(signal => <span key={signal.code + signal.text} className="ln-reason">{signal.label} <b>{signal.text}</b></span>)}</div>}
      {entry.is_latest && family.latest.reasons.length > 0 && <section><h4>최신 판단 근거</h4><ul className="ln-plain">{family.latest.reasons.map(reason => <li key={reason.code}><b>{reason.label}</b> {reason.detail}</li>)}</ul></section>}
      {conflicts.length > 0 && <section><h4>판단 보류 이유</h4><ul className="ln-plain is-warn">{conflicts.map(conflict => <li key={conflict.message}>{conflict.message}</li>)}</ul></section>}
      <section><h4>파일 {entry.instances.length}개{entry.duplicates ? ' · 같은 내용' : ''}</h4>
        <ul className="ln-files">{entry.instances.map(id => { const file = data.instances[id]; const holder = holderText(data, id); return <li key={id}>
          <b>{file.name}</b>
          <small>{holder ? `${holder} 안 · ${CHILD_KIND[file.kind] ?? file.kind}` : '업로드된 파일'} · {timeText(file.uploaded_at)} · {sizeText(file.size)}{file.analysed ? '' : ' · 구조 분석 전'}</small>
        </li>; })}</ul>
      </section>
      {entry.notes.map(note => <p key={note} className="ln-panel-note">{note}</p>)}
      {goFamily(entry.family)}
    </>;
  } else if (pin.type === 'instance' && data.instances[pin.id]) {
    const node = data.instances[pin.id];
    const family = familyOf(node.family);
    const holder = holderText(data, node.id);
    const refs = data.references.filter(ref => ref.source === node.id);
    title = node.name;
    body = <>
      <p className="ln-panel-sub">{node.depth ? `${CHILD_KIND[node.kind] ?? node.kind}${holder ? ` · ${holder} 안` : ''}` : '업로드된 파일'}</p>
      <dl className="ln-dl">
        {node.location && <><dt>위치</dt><dd>{node.location}</dd></>}
        <dt>크기</dt><dd>{sizeText(node.size)}</dd>
        {node.depth === 0 && <><dt>반입</dt><dd>{timeText(node.uploaded_at)}</dd><dt>구조 분석</dt><dd>{node.analysed ? (node.inspected_at ? timeText(node.inspected_at) : '완료') : '분석 전'}</dd></>}
        {family && <><dt>문서군</dt><dd>{family.title} · {data.entries[node.entry ?? '']?.label}</dd></>}
        {node.same_as && <><dt>같은 내용</dt><dd>{data.instances[node.same_as]?.name}</dd></>}
        {node.flags.length > 0 && <><dt>표시</dt><dd>{node.flags.map(flag => <span key={flag} className={`st-flag is-${FLAG[flag]?.tone ?? 'info'}`}>{FLAG[flag]?.label ?? flag}</span>)}</dd></>}
      </dl>
      {refs.length > 0 && <section><h4>이 파일의 참조 {refs.length}건</h4><ul className="ln-plain">{refs.slice(0, 40).map(ref => { const target = targetText(data, ref); return <li key={ref.id}><span className={`ln-state is-${STATE_META[ref.state].tone}`}>{STATE_META[ref.state].short}</span> {target.text}{target.sub ? ` · ${target.sub}` : ''} <small>{ref.location}</small></li>; })}</ul></section>}
      {family && current?.id !== family.id && goFamily(family.id, node.entry)}
    </>;
  } else if (pin.type === 'family' && familyOf(pin.id)) {
    const family = familyOf(pin.id)!;
    const latest = data.entries[family.latest.entry];
    title = family.title;
    body = <>
      <p className="ln-panel-sub"><span className={`ln-state is-${LATEST_META[family.latest.status].tone}`}>{LATEST_META[family.latest.status].label}</span> {latest.label} · {data.instances[latest.primary].name}</p>
      <dl className="ln-dl"><dt>판</dt><dd>{family.entries.length}개</dd><dt>파일</dt><dd>{family.files}개</dd><dt>포함 파일</dt><dd>{family.counts.contained}개</dd>
        <dt>가리키는 곳</dt><dd>{Object.values(family.counts.in).reduce((a, b) => a + b, 0)}건</dd></dl>
      {goFamily(family.id)}
    </>;
  } else if (pin.type === 'group') {
    const group = pin.group;
    const first = group.refs[0];
    const meta = STATE_META[group.state];
    title = group.text;
    body = <>
      <p className="ln-panel-sub"><span className={`ln-state is-${meta.tone}`}>{meta.label}</span> {group.sub}</p>
      {first.note && <p className={`ln-panel-note${group.state === 'linked' ? '' : ' is-warn'}`}>{first.note}</p>}
      <p className="ln-panel-meta">{LINK_KIND[first.kind] ?? first.kind}{first.match ? ` · ${MATCH_LABEL[first.match] ?? first.match}` : ''}</p>
      {group.state === 'ambiguous' && first.candidates.length > 0 && <section><h4>후보</h4><ul className="ln-plain">{first.candidates.map((candidate, index) => {
        const family = familyOf(candidate.family); const file = candidate.instance ? data.instances[candidate.instance] : null;
        return <li key={index}>{file ? `${file.name} · ${timeText(file.uploaded_at)} 반입` : family?.title}{family && current?.id !== family.id && <button className="ln-link" onClick={() => onFamily(family.id, candidate.entry ?? undefined)}>보기</button>}</li>;
      })}</ul></section>}
      <section><h4>근거 {group.refs.length}곳</h4>
        <div className="ln-table-wrap"><table className="ln-table"><thead><tr><th>출발 파일</th><th>위치</th><th>근거</th></tr></thead><tbody>
          {group.refs.slice(0, 200).map(ref => <tr key={ref.id}><td title={holderText(data, ref.source)}>{data.instances[ref.source]?.name}</td><td>{ref.location || '—'}</td><td>{ref.evidence ? <q>{ref.evidence}</q> : <span className="ln-muted">{ref.target}</span>}</td></tr>)}
        </tbody></table></div>
      </section>
      <div className="ln-panel-actions">
        {group.family && goFamily(group.family, group.entry, '대상 문서군 보기')}
        {group.sourceFamily && goFamily(group.sourceFamily, null, '출발 문서군 보기')}
      </div>
    </>;
  } else {
    title = '항목을 찾을 수 없습니다';
    body = <p className="ln-panel-sub">목록을 다시 불러오면서 사라진 항목입니다.</p>;
  }
  return <aside className="ln-panel" aria-label="상세">
    <header><div><span>{KICKER[pin.type]}</span><h3 title={title}>{title}</h3></div><button className="ln-close" onClick={onClose} aria-label="상세 닫기" title="닫기 (Esc)"><X size={15} /></button></header>
    <div className="ln-panel-body">{body}</div>
  </aside>;
}
