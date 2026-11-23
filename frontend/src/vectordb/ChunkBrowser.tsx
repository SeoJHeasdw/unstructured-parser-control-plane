import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { ChevronLeft, ChevronRight, ChevronsLeft, Info, LoaderCircle, RefreshCw, SlidersHorizontal, TriangleAlert, X } from 'lucide-react';
import { browseChunks, type BrowseResult, type ChunkRow, type CollectionDetail, type SourceKey } from '../api/vectordb';
import { fmtCount, fmtValue, oneLine, PALETTE, ROLE_LABEL, shortPk, useStored, VectorStrip } from './ui';

type Props = {
  source: SourceKey; detail: CollectionDetail; textField: string | null; onTextField: (value: string | null) => void;
  partition: string | null; onPartition: (value: string | null) => void; onOpen: (pk: string) => void; activePk: string | null;
};

export default function ChunkBrowser({ source, detail, textField, onTextField, partition, onPartition, onOpen, activePk }: Props) {
  const [optionsOpen, setOptionsOpen] = useStored<boolean>('open.options', false);
  const [pageSize, setPageSize] = useStored<number>('pageSize', 20);
  const [includeVector, setIncludeVector] = useStored<boolean>('vectorSummary', true);
  const [draft, setDraft] = useState('');
  const [applied, setApplied] = useState('');
  const [outputFields, setOutputFields] = useState<string[] | null>(null);
  const [data, setData] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [hoverDoc, setHoverDoc] = useState<string | null>(null);

  const optionsId = useId();
  const roles = useMemo(() => {
    const map: Record<string, string> = {};
    Object.entries(detail.detected).forEach(([role, name]) => { if (name && !map[name]) map[name] = role; });
    return map;
  }, [detail]);
  const pk = detail.detected.pk ?? 'pk';
  const textChoices = detail.fields.filter(f => !f.primary_key && (f.type === 'VARCHAR' || f.type === 'STRING'));
  const effectiveText = textField ?? detail.detected.text;
  const scalarChoices = detail.fields.filter(f => !f.is_vector && !f.primary_key && f.name !== effectiveText);
  const queryKey = JSON.stringify([applied, partition, outputFields, textField, pageSize, includeVector]);
  const [page, setPage] = useState({ key: '', offset: 0 });
  const offset = page.key === queryKey ? page.offset : 0;
  const setOffset = (value: number) => setPage({ key: queryKey, offset: Math.max(0, value) });

  useEffect(() => {
    let alive = true;
    setLoading(true); setError(''); setData(null);
    setHoverDoc(null);
    browseChunks(source, { db: detail.db, collection: detail.name }, { filter: applied, partition, output_fields: outputFields, text_field: textField, limit: pageSize, offset, include_vector: includeVector })
      .then(result => { if (alive) { setData(result); setLoading(false); } })
      .catch((err: Error) => { if (alive) { setError(err.message); setLoading(false); } });
    return () => { alive = false; };
  }, [source, detail.db, detail.name, queryKey, offset, retry]);

  const submit = (event: FormEvent) => { event.preventDefault(); setApplied(draft.trim()); };
  const clearFilter = () => { setDraft(''); setApplied(''); };
  const resetQuery = () => { clearFilter(); onPartition(null); };
  const rows = data?.rows ?? [];
  const columns = (data?.output_fields ?? []).filter(name => name !== pk);
  const total = data?.total ?? null;
  const maxWindow = data?.max_window ?? 16384;
  const end = offset + rows.length;
  const nextDisabled = loading || rows.length < pageSize || (total !== null && end >= total) || offset + pageSize * 2 >= maxWindow;
  const customised = (applied ? 1 : 0) + (outputFields ? 1 : 0) + (textField !== null ? 1 : 0) + (includeVector ? 0 : 1);
  const first = rows[0];
  const examples = [
    detail.detected.doc && first?.fields[detail.detected.doc] !== undefined ? `${detail.detected.doc} == ${JSON.stringify(String(first.fields[detail.detected.doc]))}` : null,
    detail.detected.order ? `${detail.detected.order} < 3` : null,
    effectiveText ? `${effectiveText} like "%${firstWord(first?.text)}%"` : null,
  ].filter((x): x is string => !!x);
  const toggleField = (name: string) => {
    const current = outputFields ?? scalarChoices.map(f => f.name);
    const next = current.includes(name) ? current.filter(n => n !== name) : [...current, name];
    setOutputFields(next.length === scalarChoices.length && scalarChoices.every(f => next.includes(f.name)) ? null : scalarChoices.map(f => f.name).filter(n => next.includes(n)));
  };
  const chosen = outputFields ?? scalarChoices.map(f => f.name);
  const docField = detail.detected.doc;
  const docOf = (row: ChunkRow) => docField && row.fields[docField] !== undefined && row.fields[docField] !== null ? String(row.fields[docField]) : null;
  const partColor = (name: string | null) => { const i = name ? detail.partitions.findIndex(p => p.name === name) : -1; return i < 0 ? '#c4cad6' : PALETTE[i % PALETTE.length]; };

  return <div className="vdb-browser">
    <div className="vdb-toolbar" role="group" aria-label="청크 목록 도구">
      <label className="vdb-select"><span>파티션</span>
        <select value={partition ?? ''} onChange={event => onPartition(event.target.value || null)} aria-label="파티션 선택">
          <option value="">전체 ({fmtCount(detail.row_count)})</option>
          {detail.partitions.map(p => <option key={p.name} value={p.name}>{p.name} ({fmtCount(p.row_count)})</option>)}
        </select>
      </label>
      <button type="button" className={`vdb-opt-toggle ${optionsOpen ? 'is-open' : ''}`} aria-expanded={optionsOpen} aria-controls={optionsId} onClick={() => setOptionsOpen(!optionsOpen)}>
        <SlidersHorizontal size={14} aria-hidden /> 조건·필드{customised > 0 && <em aria-label={`${customised}개 적용 중`}>{customised}</em>}
      </button>
      {applied && !optionsOpen && <span className="vdb-chip is-filter" title={applied}><code>{oneLine(applied, 48)}</code><button type="button" aria-label="조건 지우기" onClick={clearFilter}><X size={12} /></button></span>}
      <span className="vdb-toolbar-gap" />
      <span className="vdb-range" aria-live="polite">{loading ? <LoaderCircle size={14} className="vdb-spin" aria-label="불러오는 중" /> : rows.length ? `${fmtCount(offset + 1)}–${fmtCount(end)}` : '0건'}{total !== null && <> / <b>{fmtCount(total)}</b>건</>}</span>
      <div className="vdb-pager">
        <button type="button" className="plain-icon" aria-label="첫 페이지" disabled={loading || offset === 0} onClick={() => setOffset(0)}><ChevronsLeft size={16} /></button>
        <button type="button" className="plain-icon" aria-label="이전 페이지" disabled={loading || offset === 0} onClick={() => setOffset(offset - pageSize)}><ChevronLeft size={16} /></button>
        <button type="button" className="plain-icon" aria-label="다음 페이지" disabled={nextDisabled} onClick={() => setOffset(offset + pageSize)}><ChevronRight size={16} /></button>
      </div>
    </div>

    {optionsOpen && <div className="vdb-options" id={optionsId}>
      <form className="vdb-expr-row" onSubmit={submit}>
        <label htmlFor={`${optionsId}-expr`}>조건식</label>
        <input id={`${optionsId}-expr`} className="vdb-expr" value={draft} onChange={event => setDraft(event.target.value)} placeholder={examples[0] ?? 'Milvus 필터 식'} spellCheck={false} autoComplete="off" />
        <button type="submit" className="button-primary">적용</button>
        <button type="button" className="button-secondary" onClick={clearFilter} disabled={!draft && !applied}>지우기</button>
      </form>
      {examples.length > 0 && <div className="vdb-examples" aria-label="조건식 예시">{examples.map(ex => <button type="button" key={ex} onClick={() => setDraft(ex)}><code>{ex}</code></button>)}</div>}
      <div className="vdb-opt-grid">
        <label className="vdb-select"><span>텍스트 필드</span>
          <select value={textField ?? ''} onChange={event => onTextField(event.target.value || null)} aria-label="텍스트 필드">
            <option value="">자동{detail.detected.text ? ` (${detail.detected.text})` : ' (없음)'}</option>
            {textChoices.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </label>
        <label className="vdb-select"><span>쪽당</span>
          <select value={pageSize} onChange={event => setPageSize(Number(event.target.value))} aria-label="한 쪽에 보일 청크 수">{[20, 50, 100].map(n => <option key={n} value={n}>{n}개</option>)}</select>
        </label>
        <label className="vdb-check"><input type="checkbox" checked={includeVector} onChange={event => setIncludeVector(event.target.checked)} /> 벡터 요약</label>
      </div>
      <fieldset className="vdb-fieldset"><legend>출력 필드 <small>{chosen.length}/{scalarChoices.length}</small></legend>
        {scalarChoices.map(f => <label key={f.name} className={`vdb-field-chip ${chosen.includes(f.name) ? 'is-on' : ''}`}><input type="checkbox" checked={chosen.includes(f.name)} onChange={() => toggleField(f.name)} />{f.name}{roles[f.name] && <small>{ROLE_LABEL[roles[f.name]]}</small>}</label>)}
        {outputFields && <button type="button" className="text-button" onClick={() => setOutputFields(null)}>모두</button>}
      </fieldset>
      {data && <p className="vdb-effective">적용 조건 <code>{data.effective_filter}</code>{!data.user_filter && <small> (조건이 없으면 전체 청크를 기본 키 순으로 봅니다)</small>}</p>}
    </div>}

    {effectiveText
      ? <p className="vdb-truth" title="벡터는 텍스트로 되돌릴 수 없습니다."><Info size={13} aria-hidden /><span>글은 함께 저장된 <code>{effectiveText}</code> 필드 값입니다.</span></p>
      : <p className="vdb-truth is-warn" role="note"><TriangleAlert size={14} aria-hidden /><span>텍스트 필드가 없어 청크 내용을 읽을 수 없습니다. 벡터는 텍스트로 되돌릴 수 없습니다.</span></p>}
    {error && <div className="vdb-problem" role="alert"><TriangleAlert size={18} aria-hidden="true" /><div><strong>청크를 불러오지 못했습니다</strong><p>{error}</p></div><button type="button" className="button-secondary" onClick={() => setRetry(value => value + 1)}><RefreshCw size={15} aria-hidden="true" /> 다시 시도</button></div>}

    <div className={`vdb-table-wrap ${loading ? 'is-loading' : ''}`} aria-busy={loading} tabIndex={0} role="region" aria-label="저장된 청크 표">
      <table className={`vdb-table is-chunks ${hoverDoc !== null ? 'is-dimmed' : ''}`}>
        <thead><tr>
          <th scope="col" className="is-pk">{pk}</th>
          <th scope="col" className="is-text">{effectiveText ?? '텍스트'}</th>
          {columns.map(name => <th scope="col" key={name}>{name}{roles[name] && <small>{ROLE_LABEL[roles[name]]}</small>}</th>)}
          <th scope="col">파티션</th>
          {includeVector && <th scope="col">벡터</th>}
        </tr></thead>
        <tbody>
          {rows.map(row => {
            const doc = docOf(row);
            return <tr key={row.pk} className={`${row.pk === activePk ? 'is-active' : ''} ${hoverDoc !== null && doc === hoverDoc ? 'is-lit' : ''}`}
              onMouseEnter={() => setHoverDoc(doc)} onMouseLeave={() => setHoverDoc(null)}>
            <td className="is-pk" title={row.pk}><code>{shortPk(row.pk)}</code></td>
            <td className="is-text">
              <button type="button" className="vdb-open" aria-label={`청크 ${shortPk(row.pk)} 열기`} onClick={() => onOpen(row.pk)}
                onFocus={() => setHoverDoc(doc)} onBlur={() => setHoverDoc(null)}>
                {row.text ? oneLine(row.text, 150) : <i>텍스트 없음</i>}
              </button>
            </td>
            {columns.map(name => <td key={name} title={typeof row.fields[name] === 'string' ? String(row.fields[name]) : undefined}>{fmtValue(row.fields[name], 28)}</td>)}
            <td className="is-part">{row.partition ? <><i className="vdb-swatch" style={{ background: partColor(row.partition) }} aria-hidden />{row.partition}</> : '—'}</td>
            {includeVector && <td className="is-vec">{row.vector?.head ? <><span>{row.vector.dim}차원</span><VectorStrip values={row.vector.head} /></> : row.vector ? <span>{row.vector.type}</span> : '—'}</td>}
          </tr>;
          })}
          {!loading && !rows.length && !error && <tr><td colSpan={columns.length + 3 + Number(includeVector)} className="vdb-empty"><div className="vdb-empty-chunks"><strong>{applied || partition ? '조건에 맞는 청크가 없습니다' : '저장된 청크가 없습니다'}</strong>{(applied || partition) && <button type="button" className="button-secondary" onClick={resetQuery}>전체 청크 보기</button>}</div></td></tr>}
        </tbody>
      </table>
    </div>
    {data?.total_basis === 'stats' && <p className="vdb-foot">전체 건수는 Milvus 통계값입니다. 삭제 직후에는 실제 조회 건수와 다를 수 있습니다.</p>}
    {offset + pageSize * 2 >= maxWindow && <p className="vdb-foot">Milvus 조회는 앞에서 {fmtCount(maxWindow)}건 안쪽만 넘겨 볼 수 있습니다. 조건식으로 범위를 좁혀 주세요.</p>}
  </div>;
}

function firstWord(text: string | null | undefined) {
  const word = (text ?? '').split(/\s+/).find(w => w.length >= 2 && /[가-힣A-Za-z]/.test(w));
  return (word ?? '').replace(/[^가-힣A-Za-z0-9]/g, '').slice(0, 6) || '검색어';
}
