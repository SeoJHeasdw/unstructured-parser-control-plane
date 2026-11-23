import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, BookOpenText, Copy, FileText, LoaderCircle, Search, TriangleAlert } from 'lucide-react';
import { findSimilar, getChunk, listDocuments, readDocument, type ChunkDetail, type CollectionDetail, type DocumentRead, type DocValues, type SimilarResult, type SourceKey } from '../api/vectordb';
import { Modal } from '../ui';
import { escapeHides, fmtCount, fmtValue, metricHint, oneLine, shortPk, useFloating, useStored, VectorStrip } from './ui';

/** 청크·문서 상세. 컬렉션 탭의 팝업과 파티션 팝업이 같은 조각을 쓴다. */
export type PanelState = { mode: 'chunk'; pk: string } | { mode: 'document'; field: string | null; value: string | null };
type Common = { source: SourceKey; detail: CollectionDetail; textField: string | null; onNavigate: (next: PanelState) => void };

/** 컬렉션 탭에서 청크를 열면 뜨는 팝업. 이전 보기와 문서로 다시 읽기를 팝업 안에서 오간다. */
export function ChunkModal({ stack, onBack, onClose, ...common }: Common & { stack: PanelState[]; onBack: () => void; onClose: () => void }) {
  const top = stack[stack.length - 1] ?? null;
  const title = !top ? '' : top.mode === 'chunk' ? `청크 ${shortPk(top.pk)}` : top.value ?? '문서로 다시 읽기';
  const subtitle = !top ? '' : top.mode === 'chunk' ? common.detail.name : `${common.detail.name} · 문서로 다시 읽기`;
  return <Modal open={!!top} onClose={onClose} size="lg" title={title} subtitle={subtitle} extra={<span className="ui-pill is-accent">{common.source === 'example' ? '예시 데이터' : 'Milvus 데이터'}</span>}>
    {top && <div className="vdb-pop is-sheet"><DetailPane stack={stack} onBack={onBack} {...common} /></div>}
  </Modal>;
}

/** 쌓인 보기의 맨 위를 보여 준다. 안에서 옮겨 가면 초점을 상세 첫머리로 옮긴다(Escape가 계속 팝업에 닿도록). */
export function DetailPane({ stack, onBack, onNavigate, showPartition = true, ...rest }: Common & { stack: PanelState[]; onBack: () => void; showPartition?: boolean }) {
  const top = stack[stack.length - 1];
  const rootRef = useRef<HTMLDivElement>(null);
  const moved = useRef(false);
  const topKey = top ? (top.mode === 'chunk' ? `c:${top.pk}` : `d:${top.field}|${top.value}`) : '';
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    rootRef.current?.focus({ preventScroll: true });
    rootRef.current?.scrollIntoView?.({ block: 'start' });
  }, [topKey, stack.length]);
  if (!top) return null;
  const go = (next: PanelState) => { moved.current = true; onNavigate(next); };
  const back = () => { moved.current = true; onBack(); };
  return <div ref={rootRef} className="vdb-detail" tabIndex={-1}>
    {stack.length > 1 && <button type="button" className="vdb-back" onClick={back}><ArrowLeft size={14} aria-hidden /> 이전 보기</button>}
    {top.mode === 'chunk'
      ? <ChunkView key={top.pk} pk={top.pk} showPartition={showPartition} onNavigate={go} {...rest} />
      : <DocumentView key={`${top.field}|${top.value}`} field={top.field} value={top.value} onNavigate={go} {...rest} />}
  </div>;
}

export function ChunkView({ source, detail, textField, pk, onNavigate, showPartition = true }: Common & { pk: string; showPartition?: boolean }) {
  const [chunk, setChunk] = useState<ChunkDetail | null>(null);
  const [similar, setSimilar] = useState<SimilarResult | null>(null);
  const [error, setError] = useState('');
  const [similarError, setSimilarError] = useState('');
  const [hoverDoc, setHoverDoc] = useState<string | null>(null);
  const tip = useFloating();
  useEffect(() => {
    let alive = true;
    const target = { db: detail.db, collection: detail.name };
    getChunk(source, target, pk, textField).then(result => { if (alive) setChunk(result); }).catch((err: Error) => { if (alive) setError(err.message); });
    findSimilar(source, target, pk, textField).then(result => { if (alive) setSimilar(result); }).catch((err: Error) => { if (alive) setSimilarError(err.message); });
    return () => { alive = false; };
  }, [source, detail.db, detail.name, pk, textField]);
  if (error) return <p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{error}</span></p>;
  if (!chunk) return <p className="vdb-loading"><LoaderCircle size={16} className="vdb-spin" aria-hidden /> 청크를 불러오는 중</p>;
  const det = chunk.detected;
  const docValue = det.doc ? chunk.fields[det.doc] : undefined;
  const has = (field: string | null) => !!field && chunk.fields[field] !== undefined && chunk.fields[field] !== null && chunk.fields[field] !== '';
  const meta = ([['문서', det.doc], ['순서', det.order], ['쪽', det.page], ['출처', det.source]] as [string, string | null][]).filter(([, field]) => has(field)) as [string, string][];
  const inMeta = new Set(meta.map(([, field]) => field));
  const rest = Object.entries(chunk.fields).filter(([k]) => !inMeta.has(k));
  const vector = chunk.vector;
  return <div className="vdb-cv">
    <div className="vdb-cv-top">
      <dl className="vdb-cv-meta">
        {showPartition && chunk.partition && <div><dt>파티션</dt><dd>{chunk.partition}</dd></div>}
        {meta.map(([label, field]) => {
          const full = String(chunk.fields[field]);
          const text = fmtValue(chunk.fields[field], 48);
          return <div key={label} className={label === '문서' && hoverDoc !== null && String(docValue) === hoverDoc ? 'is-doc-hl' : ''}>
            <dt>{label}</dt><dd data-tip={full} data-tip-overflow={text !== full ? undefined : true}>{text}</dd>
          </div>;
        })}
      </dl>
      <div className="vdb-cv-actions">
        {det.doc && docValue !== undefined && docValue !== null && <button type="button" className="button-secondary" onClick={() => onNavigate({ mode: 'document', field: det.doc, value: String(docValue) })}><BookOpenText size={14} aria-hidden /> 이 문서 다시 읽기</button>}
        <button type="button" className="button-quiet" onClick={() => { void navigator.clipboard?.writeText(chunk.pk).catch(() => undefined); }}><Copy size={14} aria-hidden /> pk 복사</button>
      </div>
    </div>

    <section className="vdb-sec" aria-label="청크 텍스트">
      <h3>본문 {chunk.text_field && <small>{chunk.text_field} · {fmtCount(chunk.text?.length ?? 0)}자</small>}</h3>
      {chunk.text ? <p className="vdb-fulltext">{chunk.text}</p> : <p className="vdb-truth is-warn"><TriangleAlert size={14} aria-hidden /><span>텍스트 필드가 없어 내용을 보여 줄 수 없습니다. 벡터는 텍스트로 되돌릴 수 없습니다.</span></p>}
    </section>

    <div className="vdb-cv-grid">
      <section className="vdb-sec" aria-label="필드">
        <h3>필드 <small>{rest.length}개</small></h3>
        {rest.length ? <dl className="vdb-kv">{rest.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{typeof v === 'string' ? v : fmtValue(v, 400)}</dd></div>)}</dl> : <p className="vdb-muted">—</p>}
      </section>
      <section className="vdb-sec" aria-label="벡터 요약">
        <h3>벡터 {vector && detail.detected.vector && <small>{detail.detected.vector}</small>}</h3>
        {vector?.head ? <div className="vdb-vec">
          <dl className="vdb-vec-stats">
            <div><dt>차원</dt><dd>{fmtCount(vector.dim)}</dd></div><div><dt>L2 노름</dt><dd>{vector.norm?.toFixed(4)}</dd></div>
            <div><dt>최소 ~ 최대</dt><dd>{vector.min?.toFixed(3)} ~ {vector.max?.toFixed(3)}</dd></div><div><dt>평균</dt><dd>{vector.mean?.toFixed(5)}</dd></div>
          </dl>
          <VectorStrip values={vector.head} size="lg" />
          <p className="vdb-legend"><i className="is-pos" /> 양수 <i className="is-neg" /> 음수 · 앞 {vector.head.length}개 값, 진할수록 절댓값이 큼</p>
        </div> : vector ? <p className="vdb-muted">{vector.type}{vector.nnz !== undefined ? ` · 0이 아닌 값 ${vector.nnz}개` : ''}</p> : <p className="vdb-muted">벡터 필드가 없습니다.</p>}
      </section>
    </div>

    <section className="vdb-sec" aria-label="비슷한 청크">
      <h3>비슷한 청크 <small>{similar ? metricHint(similar.metric, similar.higher_is_closer) : '이 청크의 벡터로 검색'}</small></h3>
      {similarError && <p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{similarError}</span></p>}
      {!similar && !similarError && <p className="vdb-loading"><LoaderCircle size={14} className="vdb-spin" aria-hidden /> 검색 중</p>}
      {similar && <SimilarList result={similar} hoverDoc={hoverDoc} onHoverDoc={setHoverDoc} onOpen={pk2 => onNavigate({ mode: 'chunk', pk: pk2 })} tip={tip} />}
    </section>
    {tip.layer}
  </div>;
}

function SimilarList({ result, hoverDoc, onHoverDoc, onOpen, tip }: { result: SimilarResult; hoverDoc: string | null; onHoverDoc: (doc: string | null) => void; onOpen: (pk: string) => void; tip: ReturnType<typeof useFloating> }) {
  const scores = result.hits.map(h => h.score ?? 0);
  const lo = Math.min(...scores), hi = Math.max(...scores);
  const strength = (s: number) => hi === lo ? 1 : result.higher_is_closer === false ? (hi - s) / (hi - lo) : (s - lo) / (hi - lo);
  const same = result.hits.filter(h => h.same_document).length;
  if (!result.hits.length) return <p className="vdb-muted">다른 청크가 없습니다.</p>;
  return <>
    {result.doc_field && <p className="vdb-muted">상위 {result.hits.length}개 중 같은 문서 {same}개</p>}
    <ol className={`vdb-sim ${hoverDoc !== null ? 'is-dimmed' : ''}`}>
      {result.hits.map(hit => {
        const doc = hit.doc === null || hit.doc === undefined ? null : String(hit.doc);
        const lit = hoverDoc !== null && doc === hoverDoc;
        const where = [hit.order !== null && hit.order !== undefined ? `순서 ${fmtValue(hit.order)}` : '', hit.page !== null && hit.page !== undefined ? `${fmtValue(hit.page)}쪽` : ''].filter(Boolean).join(' · ');
        const binding = tip.bind(`sim:${hit.pk}`, () => <><b>{doc ?? '문서 정보 없음'}</b>{where && <span>{where}</span>}<span>{oneLine(hit.text, 220)}</span></>, 'tip', 300);
        return <li key={hit.pk} className={lit ? 'is-lit' : ''}>
          <button type="button" onClick={() => { tip.hide(); onOpen(hit.pk); }} onKeyDown={escapeHides(tip)}
            onMouseEnter={event => { onHoverDoc(doc); binding.onMouseEnter(event); }} onMouseLeave={() => { onHoverDoc(null); binding.onMouseLeave(); }}
            onFocus={event => { onHoverDoc(doc); binding.onFocus(event); }} onBlur={() => { onHoverDoc(null); binding.onBlur(); }} aria-describedby={binding['aria-describedby']}>
            <span className="vdb-sim-rank">{hit.rank}</span>
            <span className="vdb-sim-score"><i style={{ width: `${Math.round(18 + 82 * strength(hit.score ?? 0))}%` }} /><b>{hit.score === null ? '—' : hit.score.toFixed(4)}</b></span>
            <span className="vdb-sim-text">{hit.text ? oneLine(hit.text, 90) : shortPk(hit.pk)}</span>
            <span className="vdb-badge-doc">{hit.same_document === false ? '다른 문서' : ''}</span>
          </button>
        </li>;
      })}
    </ol>
  </>;
}

export const docFieldChoices = (detail: CollectionDetail) => detail.fields.filter(f => !f.is_vector && !f.primary_key && ['VARCHAR', 'STRING', 'INT8', 'INT16', 'INT32', 'INT64'].includes(f.type));

/** 문서 고르기 + 다시 읽기(컬렉션 탭 팝업). */
function DocumentView({ source, detail, textField, field, value, onNavigate }: Common & { field: string | null; value: string | null }) {
  const candidates = docFieldChoices(detail);
  const docField = field ?? detail.detected.doc ?? candidates[0]?.name ?? null;
  const [values, setValues] = useState<DocValues | null>(null);
  const [valuesError, setValuesError] = useState('');
  const [query, setQuery] = useState('');
  const [picking, setPicking] = useState(!value);
  const target = useMemo(() => ({ db: detail.db, collection: detail.name }), [detail.db, detail.name]);
  useEffect(() => {
    if (!docField) return;
    let alive = true;
    listDocuments(source, target, docField).then(result => { if (alive) setValues(result); }).catch((err: Error) => { if (alive) setValuesError(err.message); });
    return () => { alive = false; };
  }, [source, target, docField]);
  if (!docField) return <p className="vdb-truth is-warn"><TriangleAlert size={14} aria-hidden /><span>문서를 구분할 스칼라 필드가 없습니다.</span></p>;
  const open = (next: string) => { setPicking(false); onNavigate({ mode: 'document', field: docField, value: next }); };
  const filtered = (values?.values ?? []).filter(v => v.value.toLowerCase().includes(query.trim().toLowerCase()));
  const pickerControls = <>
    <label className="vdb-select"><span>문서 필드</span>
      <select value={docField} onChange={event => onNavigate({ mode: 'document', field: event.target.value, value: null })} aria-label="문서 필드">
        {candidates.map(f => <option key={f.name} value={f.name}>{f.name}{f.name === detail.detected.doc ? ' (자동)' : ''}</option>)}
      </select>
    </label>
    {value !== null && <button type="button" className="button-quiet" aria-expanded={picking} onClick={() => setPicking(!picking)}><FileText size={14} aria-hidden /> 문서 바꾸기</button>}
  </>;
  const picker = (picking || value === null) ? <div className="vdb-doc-pick">
    <label className="vdb-tree-search"><Search size={14} aria-hidden /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={`${docField} 값 찾기`} aria-label="문서 값 찾기"
      onKeyDown={event => { if (event.key === 'Enter' && filtered[0]) { event.preventDefault(); open(filtered[0].value); } }} /></label>
    {valuesError && <p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{valuesError}</span></p>}
    {!values && !valuesError && <p className="vdb-loading"><LoaderCircle size={14} className="vdb-spin" aria-hidden /> 문서 목록을 모으는 중</p>}
    {values && <>
      <ul className="vdb-doc-list" aria-label="문서 목록">{filtered.map(v => <li key={v.value}><button type="button" className={v.value === value ? 'is-on' : ''} onClick={() => open(v.value)}><span>{v.value}</span><small>{v.count}</small></button></li>)}</ul>
      <p className="vdb-muted">문서 {fmtCount(values.values.length)}개{values.truncated ? ` · 앞 ${fmtCount(values.scanned)}개 청크에서 찾음` : ''}</p>
    </>}
  </div> : null;
  if (value === null) return <><div className="vdb-doc-controls">{pickerControls}</div>{picker}</>;
  return <DocumentReader source={source} detail={detail} textField={textField} docField={docField} value={value} controls={pickerControls} below={picker}
    onOpenChunk={pk => onNavigate({ mode: 'chunk', pk })} />;
}

/** 한 문서의 청크를 순서대로 이어 읽는다. 겹친 부분은 한 번만 쓸 수 있다. */
export function DocumentReader({ source, detail, textField, docField, value, onOpenChunk, controls, below, expected }: {
  source: SourceKey; detail: CollectionDetail; textField: string | null; docField: string; value: string; onOpenChunk: (pk: string) => void;
  controls?: ReactNode; below?: ReactNode; expected?: number;
}) {
  const [order, setOrder] = useState<string>('auto');
  const [dedupe, setDedupe] = useStored<boolean>('dedupe', true);
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [docError, setDocError] = useState('');
  const [loading, setLoading] = useState(false);
  const tip = useFloating();
  const target = useMemo(() => ({ db: detail.db, collection: detail.name }), [detail.db, detail.name]);
  useEffect(() => {
    let alive = true;
    setLoading(true); setDocError('');
    readDocument(source, target, docField, value, order === 'auto' ? null : order, textField)
      .then(result => { if (alive) { setDoc(result); setLoading(false); } })
      .catch((err: Error) => { if (alive) { setDocError(err.message); setLoading(false); } });
    return () => { alive = false; };
  }, [source, target, docField, value, order, textField]);
  const orderChoices = detail.fields.filter(f => !f.is_vector && !f.primary_key && f.type !== 'JSON' && f.type !== 'ARRAY' && f.type !== 'BOOL');
  return <div className="vdb-reader">
    <div className="vdb-doc-controls">
      {controls}
      <label className="vdb-select"><span>순서</span>
        <select value={order} onChange={event => setOrder(event.target.value)} aria-label="청크 순서 기준">
          <option value="auto">자동{detail.detected.order ? ` (${detail.detected.order})` : ' (기본 키)'}</option>
          <option value="">기본 키 순</option>
          {orderChoices.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
        </select>
      </label>
      <label className="vdb-check"><input type="checkbox" checked={dedupe} onChange={event => setDedupe(event.target.checked)} /> 겹친 부분 한 번만</label>
    </div>
    {below}
    {docError && <p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{docError}</span></p>}
    {loading && !doc && <p className="vdb-loading"><LoaderCircle size={14} className="vdb-spin" aria-hidden /> 청크를 순서대로 모으는 중</p>}
    {doc && <div className={loading ? 'is-loading' : ''}>
      <p className="vdb-doc-stats">
        <span>청크 <b>{fmtCount(doc.total)}</b>개</span><span>순서 <code>{doc.ordered_by}</code></span>
        <span>겹침 <b>{doc.overlaps}</b>곳{doc.overlaps ? ` · 평균 ${doc.overlap_avg}자` : ''}</span>
        {doc.truncated && <span className="is-warn">앞 {fmtCount(doc.total)}개만 표시</span>}
        {expected !== undefined && !doc.truncated && doc.total > expected && <span className="is-warn">다른 파티션의 청크 {fmtCount(doc.total - expected)}개 포함</span>}
      </p>
      {!doc.text_field ? <p className="vdb-truth is-warn"><TriangleAlert size={14} aria-hidden /><span>텍스트 필드가 없어 문서를 다시 읽을 수 없습니다. 벡터는 텍스트로 되돌릴 수 없습니다.</span></p>
        : <article className={`vdb-doc-text ${dedupe ? 'is-dedupe' : ''}`} aria-label={`${doc.value} 본문`}>
          {doc.chunks.map((c, i) => <DocChunkText key={c.pk} chunk={c} n={i + 1} dedupe={dedupe} tip={tip} onOpen={() => onOpenChunk(c.pk)} />)}
        </article>}
      {doc.overlaps > 0 && <p className="vdb-legend"><mark className="vdb-overlap">겹침</mark> 앞뒤 청크에 함께 들어 있는 부분{dedupe ? '' : ' (다음 청크 앞에서 반복)'}</p>}
    </div>}
    {tip.layer}
  </div>;
}

function DocChunkText({ chunk, n, dedupe, tip, onOpen }: { chunk: DocumentRead['chunks'][number]; n: number; dedupe: boolean; tip: ReturnType<typeof useFloating>; onOpen: () => void }) {
  const text = chunk.text ?? '';
  const head = Math.min(chunk.head_skip, text.length);
  const cut = dedupe && chunk.tail ? Math.max(head, chunk.tail[0]) : text.length;
  const binding = tip.bind(`seam:${chunk.pk}`, () => <><b>청크 #{n}</b><span>pk {shortPk(chunk.pk)}{chunk.order !== null ? ` · 순서 ${fmtValue(chunk.order)}` : ''}{chunk.page !== null ? ` · ${fmtValue(chunk.page)}쪽` : ''}</span><span>{chunk.overlap ? `앞 청크와 ${chunk.overlap}자 겹침` : '앞 청크와 겹침 없음'}</span></>);
  const parts: ReactNode[] = [];
  if (head) parts.push(<mark key="h" className={`vdb-overlap ${dedupe ? '' : 'is-repeat'}`}>{text.slice(0, head)}</mark>);
  parts.push(<span key="b">{text.slice(head, cut)}</span>);
  return <span className="vdb-doc-chunk">
    <button type="button" className="vdb-seam" aria-label={`청크 ${n} 열기`} onClick={() => { tip.hide(); onOpen(); }} onKeyDown={escapeHides(tip)} {...binding}>{n}</button>
    {parts}
  </span>;
}
