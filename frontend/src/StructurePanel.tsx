import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, FileArchive, FileText, GitFork, Link2, LoaderCircle, Mail, Paperclip, ScanSearch, TriangleAlert } from 'lucide-react';
import { getLiveStructure, listLiveDocuments, getStructureOverview, inspectLiveDocument } from './api/live';
import type { LiveDoc, LiveStructure, StructNode, StructureOverview } from './api/live';

export const CHILD_KIND: Record<string, string> = { file: '원본', 'archive-entry': '압축 항목', attachment: '첨부', embedded: '내장 개체' };
export const LINK_KIND: Record<string, string> = {
  hyperlink: '하이퍼링크', url: 'URL', 'unc-path': '공유 폴더 경로', 'file-path': '파일 경로', 'doc-number': '문서번호 후보', 'external-workbook': '외부 통합문서',
  'field-link': '필드 연결', 'linked-object': '연결된 개체', template: '서식 파일', 'linked-image': '연결된 이미지', subdocument: '하위 문서', 'pdf-remote': '다른 PDF', external: '외부 연결',
};
export const FLAG: Record<string, { label: string; tone: 'warn' | 'error' | 'info' }> = {
  encrypted: { label: '암호화', tone: 'error' }, 'drm-suspect': { label: 'DRM·암호화 의심', tone: 'error' }, unreadable: { label: '분석 실패', tone: 'error' },
  'format-mismatch': { label: '확장자와 실제 형식 다름', tone: 'warn' }, macro: { label: '매크로 포함', tone: 'warn' }, truncated: { label: '한도 초과 · 일부만 분석', tone: 'warn' },
  'too-large': { label: '크기 초과', tone: 'warn' }, duplicate: { label: '중복 내용', tone: 'info' }, 'has-images': { label: '이미지 포함 · OCR 검토', tone: 'info' }, 'image-only': { label: '이미지 파일', tone: 'info' },
};
const DETECTED: Record<string, string> = {
  docx: 'Word', xlsx: 'Excel', pptx: 'PowerPoint', doc: 'Word 97', xls: 'Excel 97', ppt: 'PowerPoint 97', msg: 'Outlook 메일', mime: '메일 · MHT', pdf: 'PDF', zip: '압축',
  hwp: '한글', hwpx: '한글(HWPX)', html: 'HTML', text: '텍스트', xml: 'XML', image: '이미지', 'encrypted-ooxml': '암호화된 Office', ole: 'OLE 개체', cfb: 'OLE 복합 문서', unknown: '알 수 없음',
};
const size = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
const iconFor = (node: StructNode) => node.detected === 'zip' ? FileArchive : node.detected === 'mime' || node.detected === 'msg' ? Mail : node.kind === 'attachment' ? Paperclip : FileText;

function Flags({ flags, stats }: { flags: string[]; stats: Record<string, unknown> }) {
  return <>{flags.map(flag => <span key={flag} className={`st-flag is-${FLAG[flag]?.tone ?? 'info'}`}>{flag === 'has-images' && typeof stats.images === 'number' ? `이미지 ${stats.images} · OCR 검토` : FLAG[flag]?.label ?? flag}</span>)}</>;
}

function TreeRow({ node, depth, open, toggle, onSelect, selected }: { node: StructNode; depth: number; open: Set<StructNode>; toggle: (node: StructNode) => void; onSelect: (node: StructNode) => void; selected: StructNode | null }) {
  const Icon = iconFor(node);
  const expanded = open.has(node);
  return <>
    <li className={`st-row${selected === node ? ' is-selected' : ''}`} style={{ paddingLeft: 10 + depth * 18 }}>
      <button className="st-caret" onClick={() => toggle(node)} disabled={!node.children.length} aria-label={expanded ? `${node.name} 접기` : `${node.name} 펼치기`}>{node.children.length ? (expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : null}</button>
      <button className="st-main" onClick={() => onSelect(node)}>
        <Icon size={14} />
        <span className="st-name" title={node.location || node.name}>{node.name}</span>
        {depth > 0 && <span className="st-kind">{CHILD_KIND[node.kind] ?? node.kind}</span>}
        <span className="st-detected">{DETECTED[node.detected ?? 'unknown'] ?? node.detected}</span>
        <span className="st-size">{size(node.size)}</span>
        {node.children.length > 0 && <span className="st-count" title="하위 문서">{node.children.length}</span>}
        {node.links.length > 0 && <span className="st-count is-link" title="링크·참조 후보"><Link2 size={11} />{node.links.length}</span>}
        <Flags flags={node.flags} stats={node.stats} />
      </button>
    </li>
    {expanded && node.children.map((child, index) => <TreeRow key={`${child.location}-${index}`} node={child} depth={depth + 1} open={open} toggle={toggle} onSelect={onSelect} selected={selected} />)}
  </>;
}

function collect(node: StructNode, depth = 0, out: { node: StructNode; depth: number }[] = []) {
  out.push({ node, depth });
  node.children.forEach(child => collect(child, depth + 1, out));
  return out;
}

export function StructurePanel({ doc, onInspected }: { doc: LiveDoc; onInspected?: () => void }) {
  const [structure, setStructure] = useState<LiveStructure | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [tab, setTab] = useState<'tree' | 'links'>('tree');
  const [linkKind, setLinkKind] = useState('all');
  const [open, setOpen] = useState<Set<StructNode>>(new Set());
  const [selected, setSelected] = useState<StructNode | null>(null);
  const expandDefault = (root: StructNode) => setOpen(new Set(collect(root).filter(item => item.depth < 2).map(item => item.node)));
  useEffect(() => {
    const controller = new AbortController();
    setStructure(null); setError(''); setLoadError(''); setSelected(null); setLoading(true);
    getLiveStructure(doc.id, controller.signal).then(result => { if (!controller.signal.aborted) { setStructure(result); if (result) expandDefault(result.root); } })
      .catch(reason => { if (!controller.signal.aborted && reason?.name !== 'AbortError') setLoadError('저장된 구조 분석 결과를 불러오지 못했습니다.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [doc.id]);
  const run = async () => {
    setRunning(true); setError('');
    try { const result = await inspectLiveDocument(doc.id); setStructure(result); expandDefault(result.root); setSelected(null); onInspected?.(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '구조 분석에 실패했습니다.'); }
    finally { setRunning(false); }
  };
  const allLinks = useMemo(() => structure ? collect(structure.root).flatMap(({ node }) => node.links.map(link => ({ ...link, owner: node }))) : [], [structure]);
  const scope = selected ? allLinks.filter(link => link.owner === selected) : allLinks;
  const shown = linkKind === 'all' ? scope : scope.filter(link => link.kind === linkKind);
  const kinds = Object.entries(scope.reduce<Record<string, number>>((acc, link) => { acc[link.kind] = (acc[link.kind] ?? 0) + 1; return acc; }, {})).sort((a, b) => b[1] - a[1]);
  const s = structure?.summary;
  return <section className="st-root" aria-label="문서 구조와 링크">
    <div className="st-head">
      <div><GitFork size={16} /><strong>구조 · 링크</strong>{structure && <small>{new Date(structure.inspected_at).toLocaleString('ko-KR', { hour12: false })} 분석</small>}</div>
      <button className="live-primary st-run" onClick={() => void run()} disabled={running}>{running ? <LoaderCircle size={14} className="live-spin" /> : <ScanSearch size={14} />} {structure ? '다시 분석' : '구조 분석'}</button>
    </div>
    {error && <div className="st-error" role="alert"><TriangleAlert size={14} /> {error}</div>}
    {loadError && !error && <div className="st-empty">{loadError}</div>}
    {loadError ? null : loading ? <div className="st-empty"><LoaderCircle size={15} className="live-spin" /> 분석 결과를 확인하는 중</div> : !structure ? <div className="st-empty">파일 안의 압축 항목·첨부·내장 개체와 다른 문서를 가리키는 링크·문서번호를 찾습니다. 원본은 바꾸지 않고 파싱과도 별개입니다.</div> : <>
      <div className="st-summary">
        <div><span>하위 문서</span><b>{s!.derived}</b></div>
        <div><span>최대 깊이</span><b>{s!.max_depth}</b></div>
        <div><span>링크·참조 후보</span><b>{s!.links}</b></div>
        <div className="st-summary-flags">{Object.entries(s!.flags).map(([flag, count]) => <span key={flag} className={`st-flag is-${FLAG[flag]?.tone ?? 'info'}`}>{FLAG[flag]?.label ?? flag} {count > 1 ? count : ''}</span>)}</div>
      </div>
      <div className="st-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'tree'} className={tab === 'tree' ? 'is-on' : ''} onClick={() => setTab('tree')}>문서 계보 <span>{s!.documents}</span></button>
        <button role="tab" aria-selected={tab === 'links'} className={tab === 'links' ? 'is-on' : ''} onClick={() => setTab('links')}>링크 · 참조 <span>{scope.length}</span></button>
        {selected && <button className="st-scope" onClick={() => setSelected(null)}>선택: {selected.name} ✕</button>}
      </div>
      {tab === 'tree' ? <ul className="st-tree">
        <TreeRow node={structure.root} depth={0} open={open} toggle={node => setOpen(prev => { const next = new Set(prev); next.has(node) ? next.delete(node) : next.add(node); return next; })} onSelect={node => { setSelected(node); setTab(node.links.length ? 'links' : 'tree'); }} selected={selected} />
      </ul> : <>
        <div className="st-kinds"><button className={linkKind === 'all' ? 'is-on' : ''} onClick={() => setLinkKind('all')}>전체 {scope.length}</button>{kinds.map(([kind, count]) => <button key={kind} className={linkKind === kind ? 'is-on' : ''} onClick={() => setLinkKind(kind)}>{LINK_KIND[kind] ?? kind} {count}</button>)}</div>
        {shown.length ? <table className="st-links"><thead><tr><th>종류</th><th>대상</th><th>위치</th><th>있는 문서</th></tr></thead><tbody>
          {shown.slice(0, 300).map((link, index) => <tr key={index}><td><span className={`st-link-kind is-${link.kind}`}>{LINK_KIND[link.kind] ?? link.kind}</span></td><td className="st-target" title={link.evidence || link.target}>{link.target}</td><td>{link.location}</td><td className="st-owner" title={link.owner.location}>{link.owner.name}</td></tr>)}
        </tbody></table> : <div className="st-empty">찾은 링크·참조 후보가 없습니다.</div>}
        {shown.length > 300 && <div className="st-empty">상위 300건만 표시합니다.</div>}
      </>}
      <p className="st-note">문서번호·경로는 형식 규칙으로 찾은 후보입니다. 실제 대상 문서와의 연결은 확인하지 않았습니다.</p>
    </>}
  </section>;
}

export function StructureOverviewStrip({ onInspected }: { onInspected: () => void }) {
  const [documents, setDocuments] = useState<LiveDoc[]>([]);
  const [outcome, setOutcome] = useState('');
  const [overview, setOverview] = useState<StructureOverview | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoadError(false);
    Promise.all([getStructureOverview(), listLiveDocuments()]).then(([value, docs]) => { if (alive) { setOverview(value); setDocuments(docs); } })
      .catch(() => { if (alive) setLoadError(true); });
    return () => { alive = false; };
  }, [revision]);
  if (loadError) return <div className="lw-message is-warning" role="alert">구조 분석 요약을 불러오지 못했습니다.<button onClick={() => setRevision(value => value + 1)}>다시 시도</button></div>;
  if (!overview) return <p className="lw-placeholder" role="status">구조 분석 요약을 불러오는 중입니다.</p>;
  const runAll = async () => {
    setProgress({ done: 0, total: documents.length });
    const failures: string[] = []; setOutcome('');
    for (const [index, doc] of documents.entries()) {
      try { await inspectLiveDocument(doc.id); } catch { failures.push(doc.name); }
      setProgress({ done: index + 1, total: documents.length });
    }
    setOutcome(`성공 ${documents.length - failures.length}건 · 실패 ${failures.length}건${failures.length ? " · " + failures.join(", ") : ""}`);
    setProgress(null); setRevision(n => n + 1);
    onInspected();
  };
  const warn = (overview.flags.encrypted ?? 0) + (overview.flags['drm-suspect'] ?? 0) + (overview.flags['format-mismatch'] ?? 0) + (overview.flags.unreadable ?? 0);
  return <div className="st-overview" aria-label="구조 분석 요약">
    <div><span>구조 분석</span><b>{overview.inspected}<small>/{overview.documents_total}건</small></b></div>
    <div><span>원본 → 발견 문서</span><b>{overview.inspected} → {overview.documents}{overview.expansion ? <small> ×{overview.expansion}</small> : null}</b></div>
    <div><span>최대 깊이</span><b>{overview.max_depth}</b></div>
    <div><span>링크·참조 후보</span><b>{overview.links}</b></div>
    <div className={warn ? 'is-warn' : ''}><span>암호화·불일치·실패</span><b>{warn}</b></div>
    <button className="live-secondary" onClick={() => void runAll()} disabled={!!progress || !documents.length}>{progress ? <><LoaderCircle size={14} className="live-spin" /> {progress.done}/{progress.total}</> : <><ScanSearch size={14} /> {documents.length}개 문서 구조 분석</>}</button>
    {outcome && <p role="status">{outcome}</p>}
  </div>;
}
