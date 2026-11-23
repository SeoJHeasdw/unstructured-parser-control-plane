import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Box, ChevronDown, ChevronRight, FileArchive, FileStack, FileText, GitBranch, Link2, ListTree, Mail, Network, Paperclip, TriangleAlert } from 'lucide-react';
import { CHILD_KIND, FLAG, LINK_KIND } from '../StructurePanel';
import type { LineageData, LnEntry, LnFamily, LnInstance } from '../api/lineage';
import { LATEST_META, MATCH_LABEL, STATE_META, computeHighlight, groupIncoming, groupOutgoing, hlClass, holderText, refsFrom, refsInto, timeText } from './model';
import type { Hover, RefGroup } from './model';
import { useHoverProps } from './Tip';
import { LineageGraph } from './LineageGraph';
import { Tabs } from '../ui';

export type Pin = { type: 'entry' | 'instance' | 'family'; id: string } | { type: 'group'; id: string; group: RefGroup };

type Props = {
  data: LineageData; family: LnFamily; entryId: string; onEntry: (id: string) => void; view: 'tree' | 'graph'; onView: (view: 'tree' | 'graph') => void;
  refTab: 'out' | 'in'; onRefTab: (tab: 'out' | 'in') => void; pin: Pin | null; onPin: (pin: Pin) => void; onFamily: (id: string) => void; onOpenLive?: (doc?: string) => void;
};

export const entryTone = (family: LnFamily, entry: LnEntry) => entry.candidate && family.latest.status === 'hold' ? 'warn' : entry.is_latest || entry.co_latest ? 'ok' : 'muted';
const entryBadge = (family: LnFamily, entry: LnEntry) => family.latest.status === 'hold' ? (entry.is_latest ? '임시 최신' : entry.candidate ? '후보' : '') : entry.is_latest ? (family.entries.length > 1 ? '최신' : '') : entry.co_latest ? '최신 · 다른 형식' : '';
const iconFor = (node: LnInstance) => node.detected === 'zip' ? FileArchive : node.detected === 'mime' || node.detected === 'msg' ? Mail : node.kind === 'attachment' ? Paperclip : node.kind === 'embedded' ? Box : FileText;

export function FamilyView({ data, family, entryId, onEntry, view, onView, refTab, onRefTab, pin, onPin, onFamily, onOpenLive }: Props) {
  const hover = useHoverProps();
  const [hovered, setHovered] = useState<Hover>(null);
  const [showExternal, setShowExternal] = useState(false);
  const entry = data.entries[entryId] ?? data.entries[family.latest.entry];
  const root = data.instances[entry.primary];
  const outgoing = useMemo(() => groupOutgoing(data, refsFrom(data, root.id)), [data, root.id]);
  const incoming = useMemo(() => groupIncoming(data, refsInto(data, family)), [data, family]);
  const groups = refTab === 'out' ? outgoing : incoming;
  const hl = useMemo(() => computeHighlight(data, hovered, groups, root.id), [data, hovered, groups, root.id]);
  useEffect(() => { setHovered(null); setShowExternal(false); }, [family.id, entryId, refTab]);
  const meta = LATEST_META[family.latest.status];
  const latest = data.entries[family.latest.entry];
  const pinnedId = pin?.type === 'group' ? pin.group.key : pin?.id;
  const internal = groups.filter(group => group.state !== 'external');
  const external = groups.filter(group => group.state === 'external');
  const hoverOn = (next: Hover) => (on: boolean) => setHovered(on ? next : null);

  return <section className="ln-family" aria-label={`${family.title} 계보`}>
    <header className="ln-fhead">
      <div className="ln-fhead-title">
        <span className="ln-family-icon"><FileStack size={21} aria-hidden="true" /></span>
        <div className="ln-family-heading">
          <h2>{family.title}</h2>
          <div className="ln-family-meta">
            {family.docno && <span className="ln-tag">{family.docno}</span>}
            <span className="ln-tag is-quiet">{family.formats.join(' · ') || '형식 없음'}</span>
            <span className={`ln-state is-${meta.tone}`}>{meta.label}</span>
            {family.related.map(id => { const other = data.families.find(item => item.id === id); return other ? <button key={id} type="button" className="ln-tag is-link" onClick={() => onFamily(id)} title="이름이 같고 형식이 다른 문서군">{other.formats.join('·')} 판 보기 <ArrowRight size={13} aria-hidden="true" /></button> : null; })}
          </div>
        </div>
      </div>
      <div className="ln-seg" role="group" aria-label="보기 방식">
        <button aria-pressed={view === 'tree'} className={view === 'tree' ? 'is-on' : ''} onClick={() => onView('tree')}><ListTree size={16} aria-hidden="true" /> 계층</button>
        <button aria-pressed={view === 'graph'} className={view === 'graph' ? 'is-on' : ''} onClick={() => onView('graph')}><Network size={16} aria-hidden="true" /> 관계 그래프</button>
      </div>
    </header>

    <div className="ln-version-heading"><GitBranch size={16} aria-hidden="true" /><h3>판 이력</h3><span>{family.entries.length}개 판</span></div>
    <ol className="ln-lane" aria-label="판 순서: 왼쪽이 오래된 판, 오른쪽이 최신">
      {family.entries.map(id => {
        const item = data.entries[id];
        const tone = entryTone(family, item);
        const badge = entryBadge(family, item);
        return <li key={id}>
          <button className={`ln-ver is-${tone}${id === entry.id ? ' is-on' : ''}${pinnedId === id ? ' is-pinned' : ''}${hlClass(hl?.entries, id, !!hl && hl.entries.size > 0)}`} aria-pressed={id === entry.id}
            onClick={() => { onEntry(id); onPin({ type: 'entry', id }); }} {...hover(`ver:${id}`, () => <EntryTip data={data} family={family} entry={item} />, hoverOn({ type: 'entry', id }))}>
            <i className={`ln-dot is-${tone}`} aria-hidden="true" />
            <b>{item.label}</b>
            {family.formats.length > 1 && <small>{item.ext}</small>}
            {item.duplicates > 0 && <small title="같은 내용 파일">×{item.duplicates + 1}</small>}
            {item.contained_only && <Box size={11} aria-label="다른 파일 안에만 있음" />}
            {badge && <em>{badge}</em>}
          </button>
        </li>;
      })}
    </ol>
    <Verdict family={family} latest={latest} onMore={() => onPin({ type: 'entry', id: family.latest.entry })} />

    {view === 'graph' ? <LineageGraph data={data} family={family} entry={entry} onPin={onPin} onFamily={onFamily} /> : <div className="ln-body">
      <section className="ln-pane" aria-label="포함 구조">
        <div className="ln-pane-head"><ListTree size={16} aria-hidden="true" /><h3>포함 구조</h3><span title={root.name}>{entry.label} · {root.name}</span></div>
        {entry.contained_only && <p className="ln-crumb">{holderText(data, root.id)} 안</p>}
        <TreeOrState data={data} root={root} hl={hl} pinnedId={pinnedId} onPin={onPin} onHover={setHovered} onOpenLive={onOpenLive} />
      </section>
      <section className="ln-pane" aria-label="참조">
        <Tabs label="참조 방향" value={refTab} onChange={onRefTab} className="ln-tabs"
          items={[
            { id: 'out', label: '나가는 참조', badge: outgoing.filter(group => group.state !== 'external').length },
            { id: 'in', label: '들어오는 참조', badge: incoming.length },
          ]}>
          {() => <div className="ln-refs">
            {refTab === 'out' && !root.analysed ? <p className="ln-empty-line">구조 분석 전이라 이 판이 가리키는 문서를 알 수 없습니다.</p>
              : !internal.length && !external.length ? <p className="ln-empty-line">{refTab === 'out' ? '다른 문서를 가리키는 참조가 없습니다.' : '이 문서군을 가리키는 문서가 없습니다.'}{refTab === 'in' && data.documents.not_analysed > 0 ? ` 구조 분석 전 문서 ${data.documents.not_analysed}건은 확인하지 못했습니다.` : ''}</p>
              : <ul className="ln-reflist">
                {internal.map(group => <RefRow key={group.key} data={data} group={group} direction={refTab} hl={hl} pinned={pinnedId === group.key} onPin={onPin} onHover={setHovered} />)}
                {external.length > 0 && <li className="ln-ext-toggle"><button aria-expanded={showExternal} onClick={() => setShowExternal(!showExternal)}>{showExternal ? <ChevronDown size={13} /> : <ChevronRight size={13} />} 외부 주소 {external.reduce((sum, g) => sum + g.refs.length, 0)}건</button></li>}
                {showExternal && external.map(group => <RefRow key={group.key} data={data} group={group} direction={refTab} hl={hl} pinned={pinnedId === group.key} onPin={onPin} onHover={setHovered} />)}
              </ul>}
          </div>}
        </Tabs>
      </section>
    </div>}
  </section>;
}

function Verdict({ family, latest, onMore }: { family: LnFamily; latest: LnEntry; onMore: () => void }) {
  const hover = useHoverProps();
  const status = family.latest.status;
  return <div className={`ln-verdict is-${LATEST_META[status].tone}`}>
    {status === 'hold' ? <>
      <TriangleAlert size={14} aria-hidden="true" /><b>판단 보류</b><span className="ln-verdict-text">{family.latest.conflicts[0]?.message}</span>
      <button className="ln-link" onClick={onMore}>{family.latest.conflicts.length > 1 ? `충돌 ${family.latest.conflicts.length}건 보기` : '자세히'}</button>
    </> : status === 'single' ? <>
      <b>판 1개</b><span className="ln-verdict-text">{latest.duplicates ? `같은 내용 파일 ${latest.duplicates + 1}개를 한 판으로 묶었습니다.` : '다른 판이 없습니다.'}</span>
    </> : <>
      <b>최신 {latest.label}</b>
      <span className="ln-verdict-text">판단 근거</span>
      {family.latest.reasons.map(reason => <span key={reason.code} tabIndex={0} className={`ln-reason${reason.code === 'upload' ? ' is-weak' : ''}`} {...hover(`reason:${family.id}:${reason.code}`, () => <><strong>{reason.label}</strong><span>{reason.detail}</span></>)}>{reason.label}</span>)}
    </>}
    {family.notes.map(note => <span key={note} className="ln-verdict-note">{note}</span>)}
  </div>;
}

export function EntryTip({ data, family, entry }: { data: LineageData; family: LnFamily; entry: LnEntry }) {
  const file = data.instances[entry.primary];
  const holder = holderText(data, file.id);
  const conflicts = family.latest.conflicts.filter(conflict => conflict.entries.includes(entry.id));
  return <>
    <strong>{file.name}</strong>
    <span>{holder ? `${holder} 안 · ` : ''}{timeText(entry.uploaded_at)} 반입</span>
    {entry.signals.length > 0 && <span>판 표시: {entry.signals.map(signal => `${signal.label} ${signal.text}`).join(', ')}</span>}
    {entry.is_latest && family.latest.status !== 'hold' && family.latest.reasons.length > 0 && <span className="is-ok">최신 근거: {family.latest.reasons.map(reason => reason.label).join(', ')}</span>}
    {conflicts.map(conflict => <span key={conflict.message} className="is-warn">{conflict.message}</span>)}
    {entry.duplicates > 0 && <span>같은 내용 파일 {entry.duplicates + 1}개</span>}
    <span className="ln-tip-muted">클릭하면 상세를 고정합니다.</span>
  </>;
}

function TreeOrState({ data, root, hl, pinnedId, onPin, onHover, onOpenLive }: { data: LineageData; root: LnInstance; hl: ReturnType<typeof computeHighlight>; pinnedId?: string; onPin: (pin: Pin) => void; onHover: (hover: Hover) => void; onOpenLive?: (doc?: string) => void }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set([root.id]));
  useEffect(() => { setOpen(new Set([root.id])); }, [root.id]);
  if (!root.analysed) {
    const sourceRoot = data.instances[root.root];
    return <div className="ln-state-box">
      <strong>{sourceRoot?.structure_state === 'error' ? '저장된 구조 분석 결과를 읽을 수 없습니다' : '구조 분석 전'}</strong>
      <p>{data.source === 'example' ? '예시에서 구조 분석을 하지 않은 파일로 둔 문서입니다. 이름으로만 판을 묶었습니다.' : '이름으로 판을 묶었습니다. 포함 파일과 참조를 보려면 실제 파일 처리에서 이 파일의 구조 분석을 실행하세요.'}</p>
      {data.source === 'live' && onOpenLive && <button type="button" className="button-secondary" onClick={() => onOpenLive(root.doc_id)}>문서 구조 열기 <ArrowRight size={15} aria-hidden="true" /></button>}
    </div>;
  }
  const toggle = (id: string) => setOpen(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  return <>
    <ul className="ln-tree" aria-label="포함 구조 목록">
      <TreeRow data={data} node={root} depth={0} open={open} toggle={toggle} hl={hl} pinnedId={pinnedId} onPin={onPin} onHover={onHover} />
    </ul>
    {!root.children.length && <p className="ln-empty-line">안에 포함된 파일이 없습니다.</p>}
  </>;
}

function TreeRow({ data, node, depth, open, toggle, hl, pinnedId, onPin, onHover }: { data: LineageData; node: LnInstance; depth: number; open: Set<string>; toggle: (id: string) => void; hl: ReturnType<typeof computeHighlight>; pinnedId?: string; onPin: (pin: Pin) => void; onHover: (hover: Hover) => void }) {
  const hover = useHoverProps();
  const Icon = iconFor(node);
  const expanded = open.has(node.id);
  const warn = node.flags.find(flag => FLAG[flag]?.tone === 'error') ?? node.flags.find(flag => FLAG[flag]?.tone === 'warn');
  const family = node.family && depth > 0 ? data.families.find(item => item.id === node.family) : null;
  return <>
    <li className={`ln-trow${pinnedId === node.id ? ' is-pinned' : ''}${hlClass(hl?.instances, node.id, !!hl && hl.instances.size > 0)}`} style={{ paddingLeft: 6 + Math.min(depth, 8) * 12 }}>
      <button className="ln-caret" onClick={() => toggle(node.id)} disabled={!node.children.length} aria-label={expanded ? `${node.name} 접기` : `${node.name} 펼치기`} aria-expanded={node.children.length ? expanded : undefined}>{node.children.length ? (expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : null}</button>
      <button type="button" className="ln-tmain" aria-pressed={pinnedId === node.id} onClick={() => onPin({ type: 'instance', id: node.id })} {...hover(`inst:${node.id}`, () => <InstanceTip data={data} node={node} />, on => onHover(on ? { type: 'instance', id: node.id } : null))}>
        <Icon size={15} aria-hidden="true" />
        <span className="ln-tname">{node.name}</span>
        {depth > 0 && <span className="ln-kind">{CHILD_KIND[node.kind] ?? node.kind}</span>}
        {family && <span className="ln-kind is-fam" title={`문서군: ${family.title}`}>{data.entries[node.entry ?? '']?.label ?? '문서군'}</span>}
        {node.same_as && <span className="ln-kind is-dup">사본</span>}
        {warn && <i className={`ln-dot is-${FLAG[warn].tone === 'error' ? 'error' : 'warn'}`} aria-label={FLAG[warn].label} />}
        {node.links > 0 && <span className="ln-count"><Link2 size={10} aria-hidden="true" />{node.links}</span>}
        {node.children.length > 0 && !expanded && <span className="ln-count">{node.children.length}</span>}
      </button>
    </li>
    {expanded && node.children.map(child => <TreeRow key={child} data={data} node={data.instances[child]} depth={depth + 1} open={open} toggle={toggle} hl={hl} pinnedId={pinnedId} onPin={onPin} onHover={onHover} />)}
  </>;
}

export function InstanceTip({ data, node }: { data: LineageData; node: LnInstance }) {
  const family = node.family ? data.families.find(item => item.id === node.family) : null;
  const same = node.same_as ? data.instances[node.same_as] : null;
  return <>
    <strong>{node.name}</strong>
    <span>{node.depth ? `${CHILD_KIND[node.kind] ?? node.kind}${node.location ? ` · ${node.location}` : ''}` : '업로드된 파일'}</span>
    {family && <span>문서군: {family.title} · {data.entries[node.entry ?? '']?.label}</span>}
    {same && <span>업로드된 '{same.name}'과 같은 내용</span>}
    {node.flags.length > 0 && <span>{node.flags.map(flag => FLAG[flag]?.label ?? flag).join(', ')}</span>}
    {node.links > 0 && <span>링크·참조 후보 {node.links}건</span>}
  </>;
}

function RefRow({ data, group, direction, hl, pinned, onPin, onHover }: { data: LineageData; group: RefGroup; direction: 'out' | 'in'; hl: ReturnType<typeof computeHighlight>; pinned: boolean; onPin: (pin: Pin) => void; onHover: (hover: Hover) => void }) {
  const hover = useHoverProps();
  const meta = STATE_META[group.state];
  const first = group.refs[0];
  const target = direction === 'in' && first.entry ? data.entries[first.entry]?.label : direction === 'in' && first.wanted ? first.wanted : '';
  return <li>
    <button className={`ln-ref is-${meta.tone}${pinned ? ' is-pinned' : ''}${hlClass(hl?.groups, group.key, !!hl && hl.groups.size > 0)}`} aria-pressed={pinned} onClick={() => onPin({ type: 'group', id: group.key, group })}
      {...hover(`grp:${group.key}`, () => <RefTip data={data} group={group} />, on => onHover(on ? { type: 'group', id: group.key } : null))}>
      <span className="ln-sr">{meta.label} </span>
      <span className="ln-ref-main">
        <b>{group.text}</b>
        {(group.sub || target) && <small>{direction === 'in' ? `${group.sub}${target ? ` → ${target}` : ''}` : group.sub}</small>}
        <span className={`ln-state is-${meta.tone}`} aria-hidden="true">{meta.label}</span>
      </span>
      <span className="ln-count">{group.refs.length}곳 <ChevronRight size={15} aria-hidden="true" /></span>
    </button>
  </li>;
}

export function RefTip({ data, group }: { data: LineageData; group: RefGroup }) {
  const first = group.refs[0];
  const source = data.instances[first.source];
  return <>
    <strong>{STATE_META[group.state].label} · {group.text}</strong>
    <span>{source?.name} · {first.location || '위치 정보 없음'}</span>
    {first.evidence && <q>{first.evidence}</q>}
    <span>{LINK_KIND[first.kind] ?? first.kind}{first.match ? ` · ${MATCH_LABEL[first.match] ?? first.match}` : ''}</span>
    {first.note && <span className={group.state === 'linked' ? '' : 'is-warn'}>{first.note}</span>}
    {group.refs.length > 1 && <span className="ln-tip-muted">외 {group.refs.length - 1}곳 · 클릭하면 모두 봅니다.</span>}
  </>;
}
