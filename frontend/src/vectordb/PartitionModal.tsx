import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LoaderCircle, TriangleAlert } from 'lucide-react';
import { browseChunks, getCollection, type ChunkRow, type CollectionDetail, type SourceKey, type Target } from '../api/vectordb';
import { ListBox, Modal, Tabs } from '../ui';
import { DetailPane, docFieldChoices, DocumentReader, type PanelState } from './VdbPanel';
import { fmtCount, fmtValue, oneLine, shortPk } from './ui';

export type PartRef = { db: string; collection: string; partition: string; rows: number | null };
type Tab = 'chunks' | 'docs';
const PAGE = 50;
const DOC_SCAN = 200;
const DOC_SCAN_MAX = 2000;

/** 파티션 하나를 여는 팝업. 청크(목록 + 상세)와 문서별(문서 목록 + 다시 읽기) 두 탭. */
export default function PartitionModal({ source, part, onClose }: { source: SourceKey; part: PartRef; onClose: () => void }) {
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [tab, setTab] = useState<Tab>('chunks');
  const [stack, setStack] = useState<PanelState[]>([]);
  const [doc, setDoc] = useState<string | null>(null);
  const [docsSeen, setDocsSeen] = useState(false);
  const focusPane = useRef<Tab | null>(null);
  const paneRefs = useRef(new Map<Tab, HTMLElement>());
  const target = useMemo<Target>(() => ({ db: part.db, collection: part.collection }), [part.db, part.collection]);

  useEffect(() => {
    let alive = true;
    getCollection(source, part.db, part.collection).then(result => { if (alive) setDetail(result); }).catch((err: Error) => { if (alive) setDetailError(err.message); });
    return () => { alive = false; };
  }, [source, part.db, part.collection]);

  useEffect(() => {
    if (!focusPane.current) return;
    paneRefs.current.get(focusPane.current)?.focus({ preventScroll: true });
    focusPane.current = null;
  }, [tab, doc, stack]);
  useEffect(() => { if (tab === 'docs') setDocsSeen(true); }, [tab]);

  const pickChunk = useCallback((pk: string) => setStack([{ mode: 'chunk', pk }]), []);
  const navigate = (next: PanelState) => {
    if (next.mode === 'document') {
      if (next.value === null) return;
      focusPane.current = 'docs'; setDoc(next.value); setTab('docs');
    } else setStack(current => [...current, next]);
  };
  const openFromDoc = (pk: string) => { focusPane.current = 'chunks'; setStack(current => [...current, { mode: 'chunk', pk }]); setTab('chunks'); };
  const paneRef = (key: Tab) => (el: HTMLElement | null) => { if (el) paneRefs.current.set(key, el); else paneRefs.current.delete(key); };

  const tabs = <Tabs<Tab> label="파티션 보기" value={tab} onChange={setTab} items={[{ id: 'chunks', label: '청크' }, { id: 'docs', label: '문서별' }]} />;
  const subtitle = `${part.collection} · 청크 ${fmtCount(part.rows)}개`;

  return <Modal open onClose={onClose} size="xl" flush title={part.partition} subtitle={subtitle} tabs={tabs}>
    {detailError ? <div className="vdb-pop is-pad"><p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{detailError}</span></p></div>
      : !detail ? <div className="vdb-pop is-pad"><p className="vdb-loading"><LoaderCircle size={16} className="mw-spin" aria-hidden /> 컬렉션 정보를 불러오는 중</p></div>
        : <>
          <div className="vdb-tabbody" hidden={tab !== 'chunks'}>
            <ChunkTab source={source} target={target} part={part} detail={detail} stack={stack} onPick={pickChunk} onNavigate={navigate}
              onBack={() => setStack(current => current.slice(0, -1))} paneRef={paneRef('chunks')} />
          </div>
          {(docsSeen || tab === 'docs') && <div className="vdb-tabbody" hidden={tab !== 'docs'}>
            <DocTab source={source} target={target} part={part} detail={detail} doc={doc} onDoc={setDoc} onOpenChunk={openFromDoc} paneRef={paneRef('docs')} />
          </div>}
        </>}
  </Modal>;
}

type TabProps = { source: SourceKey; target: Target; part: PartRef; detail: CollectionDetail; paneRef: (el: HTMLElement | null) => void };

function ChunkTab({ source, target, part, detail, stack, onPick, onNavigate, onBack, paneRef }: TabProps & {
  stack: PanelState[]; onPick: (pk: string) => void; onNavigate: (next: PanelState) => void; onBack: () => void;
}) {
  const [rows, setRows] = useState<ChunkRow[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [maxWindow, setMaxWindow] = useState(16384);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    browseChunks(source, target, { filter: '', partition: part.partition, output_fields: null, text_field: null, limit: PAGE, offset, include_vector: false })
      .then(result => {
        if (!alive) return;
        setRows(current => offset === 0 ? result.rows : [...current, ...result.rows.filter(r => !current.some(c => c.pk === r.pk))]);
        setTotal(result.total); setMaxWindow(result.max_window); setLoading(false);
      })
      .catch((err: Error) => { if (alive) { setError(err.message); setLoading(false); } });
    return () => { alive = false; };
  }, [source, target, part.partition, offset]);

  useEffect(() => { if (!stack.length && rows[0]) onPick(rows[0].pk); }, [rows, stack.length, onPick]);

  const det = detail.detected;
  const top = stack[stack.length - 1];
  const selected = top?.mode === 'chunk' && rows.some(r => r.pk === top.pk) ? top.pk : stack[0]?.mode === 'chunk' ? stack[0].pk : null;
  const more = !loading && (total === null ? rows.length === offset + PAGE : rows.length < total) && offset + PAGE * 2 <= maxWindow;

  if (!loading && !error && !rows.length) return <div className="ui-empty"><b>청크가 없습니다</b>이 파티션에 저장된 청크가 없습니다.</div>;
  return <div className="ui-split vdb-pop">
    <div className="vdb-plist">
      <ListBox<ChunkRow> label="청크 목록" items={rows} getKey={row => row.pk} value={selected} onChange={onPick}
        render={row => {
          const doc = det.doc ? row.fields[det.doc] : null;
          const order = det.order ? row.fields[det.order] : null;
          return <div className="vdb-opt">
            <div className="vdb-opt-top">
              <b>{doc === null || doc === undefined ? '문서 정보 없음' : fmtValue(doc, 40)}</b>
              {order !== null && order !== undefined && <span className="ui-num">#{fmtValue(order)}</span>}
              <code>{shortPk(row.pk)}</code>
            </div>
            <p>{row.text ? oneLine(row.text, 120) : '텍스트 없음'}</p>
          </div>;
        }} />
      <div className="vdb-plist-foot">
        {error ? <span className="is-error">{error}</span>
          : <span className="ui-num">{loading ? '불러오는 중' : total !== null && rows.length < total ? `${fmtCount(rows.length)} / ${fmtCount(total)}개` : `${fmtCount(rows.length)}개`}</span>}
        {more && <button type="button" className="button-secondary" onClick={() => setOffset(offset + PAGE)}>더 불러오기</button>}
      </div>
    </div>
    <div ref={paneRef} tabIndex={-1} className="vdb-pane" aria-label="청크 상세">
      {top ? <DetailPane source={source} detail={detail} textField={null} stack={stack} onBack={onBack} onNavigate={onNavigate} showPartition={false} />
        : loading ? <p className="vdb-loading"><LoaderCircle size={16} className="mw-spin" aria-hidden /> 청크를 불러오는 중</p> : null}
    </div>
  </div>;
}

type DocCount = { value: string; count: number };

function DocTab({ source, target, part, detail, doc, onDoc, onOpenChunk, paneRef }: TabProps & { doc: string | null; onDoc: (value: string) => void; onOpenChunk: (pk: string) => void }) {
  const docField = detail.detected.doc ?? docFieldChoices(detail)[0]?.name ?? null;
  const [docs, setDocs] = useState<DocCount[] | null>(null);
  const [scanned, setScanned] = useState({ rows: 0, truncated: false });
  const [error, setError] = useState('');

  useEffect(() => {
    if (!docField) return;
    let alive = true;
    (async () => {
      const counts = new Map<string, number>();
      let offset = 0, seen = 0, truncated = false;
      for (;;) {
        const page = await browseChunks(source, target, { filter: '', partition: part.partition, output_fields: [docField], text_field: null, limit: DOC_SCAN, offset, include_vector: false });
        if (!alive) return;
        page.rows.forEach(row => {
          const value = row.fields[docField];
          const key = value === null || value === undefined ? '' : String(value);
          counts.set(key, (counts.get(key) ?? 0) + 1);
        });
        seen += page.rows.length; offset += DOC_SCAN;
        if (page.rows.length < DOC_SCAN || (page.total !== null && seen >= page.total)) break;
        if (offset >= DOC_SCAN_MAX || offset + DOC_SCAN > page.max_window) { truncated = true; break; }
      }
      const list = [...counts].filter(([value]) => value !== '').map(([value, count]) => ({ value, count }))
        .sort((a, b) => a.value.localeCompare(b.value, 'ko', { numeric: true }));
      setDocs(list); setScanned({ rows: seen, truncated });
    })().catch((err: Error) => { if (alive) setError(err.message); });
    return () => { alive = false; };
  }, [source, target, part.partition, docField]);

  useEffect(() => { if (docs?.length && doc === null) onDoc(docs[0].value); }, [docs, doc, onDoc]);

  if (!docField) return <div className="ui-empty"><b>문서를 나눌 필드가 없습니다</b>문서를 구분할 스칼라 필드가 없습니다.</div>;
  if (error) return <div className="vdb-pop is-pad"><p className="vdb-error" role="alert"><TriangleAlert size={14} aria-hidden /><span>{error}</span></p></div>;
  if (docs && !docs.length) return <div className="ui-empty"><b>문서가 없습니다</b>이 파티션의 청크에 {docField} 값이 없습니다.</div>;
  const current = docs?.find(d => d.value === doc) ?? null;
  return <div className="ui-split vdb-pop">
    <div className="vdb-plist">
      {!docs ? <p className="vdb-loading is-pad"><LoaderCircle size={14} className="mw-spin" aria-hidden /> 문서를 모으는 중</p>
        : <ListBox<DocCount> label="문서 목록" items={docs} getKey={d => d.value} value={doc} onChange={onDoc}
          render={d => <div className="vdb-opt is-doc"><b>{d.value}</b><span className="ui-num">{fmtCount(d.count)}</span></div>} />}
      {docs && <div className="vdb-plist-foot"><span className="ui-num">문서 {fmtCount(docs.length)}개{scanned.truncated ? ` · 앞 ${fmtCount(scanned.rows)}개 청크에서 찾음` : ''}</span></div>}
    </div>
    <div ref={paneRef} tabIndex={-1} className="vdb-pane" aria-label="문서 본문">
      {doc && <DocumentReader source={source} detail={detail} textField={null} docField={docField} value={doc} onOpenChunk={onOpenChunk}
        expected={scanned.truncated ? undefined : current?.count} />}
    </div>
  </div>;
}
