import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Plus } from 'lucide-react';
import { exportUrl, getExampleQuestions, parseQuestions, sampleDocId, saveQuestions } from '../api/retrieval';
import type { Question, QuestionKind, RetrievalDoc, Sample } from '../api/retrieval';
import { ListBox, Modal, Segmented } from '../ui';
import { QUESTION_KIND_META, QUESTION_KINDS } from './elements';
import { errorText, fmtInt } from './shared';
import { KIND_SHORT } from './eval-common';

type Row = { key: string; q: Question };
type Filter = 'all' | QuestionKind;
type Pending = { what: string; rows: Question[]; errors: string[]; count: number };

let seq = 0;
const toRows = (questions: Question[]): Row[] => questions.map(q => ({ key: q.id ?? `n${++seq}`, q }));

/** 질문 목록 + 편집. 저장을 누르기 전에는 서버에 쓰지 않는다. 닫았다 열어도 고치던 내용은 남는다. */
export function QuestionsModal({ open, onClose, questions, onSaved, samples, docs, maxRows }: {
  open: boolean; onClose: () => void; questions: Question[]; onSaved: (q: Question[]) => void; samples: Sample[]; docs: RetrievalDoc[]; maxRows: number;
}) {
  const [rows, setRows] = useState<Row[]>(() => toRows(questions));
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [pending, setPending] = useState<Pending | null>(null);
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const side = useRef<HTMLDivElement>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  /* 누른 버튼이 사라지면 초점을 목록으로 옮겨 Escape·방향키가 계속 듣게 한다. */
  const [focusTick, setFocusTick] = useState(0);
  const focusList = () => setFocusTick(n => n + 1);
  useEffect(() => { if (focusTick) side.current?.querySelector<HTMLElement>('[role="listbox"]')?.focus(); }, [focusTick]);
  useEffect(() => { if (!dirty) setRows(toRows(questions)); }, [questions]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = filter === 'all' ? rows : rows.filter(r => r.q.kind === filter);
  const current = shown.find(r => r.key === sel) ?? shown[0] ?? null;
  const names = new Map<string, string>([...samples.map(s => [sampleDocId(s.id), s.name] as const), ...docs.map(d => [d.id, d.name] as const)]);
  const edit = (next: Row[]) => { setRows(next.slice(0, maxRows)); setDirty(true); setNote(null); };
  const patch = (key: string, change: Partial<Question>) => edit(rows.map(r => r.key === key ? { ...r, q: { ...r.q, ...change } } : r));
  const add = () => { const row = toRows([{ question: '', doc_id: '', answer: '', kind: filter === 'all' ? null : filter }])[0]; edit([...rows, row]); setSel(row.key); setFresh(row.key); };
  const remove = (key: string) => { const i = shown.findIndex(r => r.key === key); edit(rows.filter(r => r.key !== key)); setSel(shown[i + 1]?.key ?? shown[i - 1]?.key ?? null); focusList(); };

  const save = async () => {
    setSaving(true); setNote(null);
    try {
      const saved = await saveQuestions(rows.map(r => r.q).filter(q => q.question.trim()));
      setDirty(false); onSaved(saved.questions);
      setNote({ tone: 'ok', text: `${fmtInt(saved.questions.length)}개 저장했습니다.` });
      focusList();
    } catch (error) { setNote({ tone: 'bad', text: errorText(error) }); }
    finally { setSaving(false); }
  };
  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    event.target.value = '';
    if (!picked) return;
    try {
      const parsed = await parseQuestions(/\.(jsonl|json|ndjson)$/i.test(picked.name) ? 'jsonl' : 'csv', await picked.text());
      setPending({ what: picked.name, rows: parsed.questions, errors: parsed.errors, count: parsed.error_count });
    } catch (error) { setNote({ tone: 'bad', text: errorText(error) }); }
  };
  const loadExamples = async () => {
    try { setPending({ what: '예시 질문', rows: await getExampleQuestions(), errors: [], count: 0 }); }
    catch (error) { setNote({ tone: 'bad', text: errorText(error) }); }
  };
  const apply = (mode: 'append' | 'replace') => {
    if (!pending) return;
    const added = toRows(pending.rows);
    edit(mode === 'append' ? [...rows, ...added] : added);
    setFilter('all'); setSel(added[0]?.key ?? null); setPending(null); focusList();
  };

  const count = (k: QuestionKind) => rows.filter(r => r.q.kind === k).length;
  const footer = pending
    ? <><span className="ui-foot-note">{pending.what} {fmtInt(pending.rows.length)}개{pending.count ? ` · 확인 필요 ${fmtInt(pending.count)}건${pending.errors[0] ? ` (${pending.errors[0]})` : ''}` : ''}</span>
      <button type="button" className="ee-btn is-quiet" onClick={() => { setPending(null); focusList(); }}>취소</button>
      <button type="button" className="ee-btn" onClick={() => apply('replace')}>모두 바꾸기</button>
      <button type="button" className="ee-btn is-primary" onClick={() => apply('append')} disabled={!pending.rows.length}>기존에 추가</button></>
    : note ? <span className={`ui-foot-note ee-note is-${note.tone}`} role="status">{note.text}</span>
    : dirty ? <span className="ui-foot-note">저장하지 않은 변경이 있습니다.</span> : null;

  return <Modal open={open} onClose={onClose} size="xl" flush title="질문" footer={footer}
    extra={<>
      <button type="button" className="ee-btn is-quiet" onClick={loadExamples}>예시 질문 불러오기</button>
      <button type="button" className="ee-btn is-quiet" onClick={() => file.current?.click()}>가져오기</button>
      <input ref={file} type="file" accept=".csv,.jsonl,.json,.ndjson,.txt" hidden onChange={onFile} aria-label="질문 파일" />
      <details className="ee-menu">
        <summary className="ee-btn is-quiet">내보내기</summary>
        <div role="menu"><a role="menuitem" href={exportUrl('csv')} download>CSV</a><a role="menuitem" href={exportUrl('jsonl')} download>JSONL</a></div>
      </details>
      <button type="button" className="ee-btn is-primary" onClick={save} disabled={!dirty || saving}>{saving ? '저장 중' : '저장'}</button>
    </>}>
    <div className="ui-split ee-split">
      <div ref={side}>
        <div className="ee-split-tools">
          <Segmented label="질문 유형" value={filter} onChange={v => setFilter(v)}
            options={[{ id: 'all' as Filter, label: <>전체 <span className="ee-num">{fmtInt(rows.length)}</span></> },
              ...QUESTION_KINDS.map(k => ({ id: k as Filter, label: <>{KIND_SHORT[k]} <span className="ee-num">{fmtInt(count(k))}</span></> }))]} />
        </div>
        <ListBox items={shown} getKey={r => r.key} value={current?.key ?? null} onChange={setSel} label="질문 목록" className="ee-list"
          empty={<div className="ui-listbox-empty" aria-hidden="true" />}
          render={r => <div className="ee-opt is-q">
            <i className="ee-sw" style={r.q.kind ? { background: QUESTION_KIND_META[r.q.kind].color } : undefined} data-auto={r.q.kind ? undefined : ''} />
            <span><b className="ee-clamp">{r.q.question.trim() || '빈 질문'}</b>
              {r.q.doc_id ? <span>{names.get(r.q.doc_id) ?? '목록에 없는 문서'}</span> : <span className="ee-warn-text">정답 문서 없음</span>}</span>
          </div>} />
        <div className="ee-addbox">
          <button type="button" className="ee-add" onClick={add} disabled={rows.length >= maxRows}><Plus size={14} aria-hidden /><b>질문 추가</b></button>
        </div>
      </div>
      <div>{current ? <QuestionForm key={current.key} row={current} autoFocus={current.key === fresh} samples={samples} docs={docs} known={names} onPatch={change => patch(current.key, change)} onRemove={() => remove(current.key)} />
        : <div className="ui-empty"><b>질문이 없습니다</b><p className="ee-empty-actions"><button type="button" className="ee-btn" onClick={loadExamples}>예시 질문 불러오기</button><button type="button" className="ee-btn is-quiet" onClick={add} disabled={rows.length >= maxRows}>질문 추가</button></p></div>}</div>
    </div>
  </Modal>;
}

type KindChoice = 'auto' | QuestionKind;
function QuestionForm({ row, autoFocus, samples, docs, known, onPatch, onRemove }: { row: Row; autoFocus: boolean; samples: Sample[]; docs: RetrievalDoc[]; known: Map<string, string>; onPatch: (change: Partial<Question>) => void; onRemove: () => void }) {
  const q = row.q;
  return <div className="ee-form">
    <label className="ee-label">질문<textarea rows={3} value={q.question} autoFocus={autoFocus} onChange={e => onPatch({ question: e.target.value })} /></label>
    <div className="ee-label" role="group" aria-label="유형"><span>유형</span>
      <Segmented<KindChoice> label="유형 선택" value={q.kind ?? 'auto'} onChange={v => onPatch({ kind: v === 'auto' ? null : v })}
        options={[{ id: 'auto', label: '자동' }, ...QUESTION_KINDS.map(k => ({ id: k as KindChoice, label: <><i className="ee-sw" style={{ background: QUESTION_KIND_META[k].color }} />{KIND_SHORT[k]}</> }))]} />
    </div>
    <label className="ee-label">정답 문서<select value={q.doc_id} onChange={e => onPatch({ doc_id: e.target.value })} className={q.doc_id ? '' : 'is-empty'}>
      <option value="">선택</option>
      {samples.length > 0 && <optgroup label="예시 문서">{samples.map(s => <option key={s.id} value={sampleDocId(s.id)}>{s.name}</option>)}</optgroup>}
      {docs.length > 0 && <optgroup label="실제 문서">{docs.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</optgroup>}
      {q.doc_id && !known.has(q.doc_id) && <option value={q.doc_id}>목록에 없는 문서</option>}
    </select></label>
    <label className="ee-label">정답 구절<input value={q.answer} onChange={e => onPatch({ answer: e.target.value })} placeholder="없음" /></label>
    <div className="ee-form-foot"><button type="button" className="ee-btn is-quiet is-danger" onClick={onRemove}>질문 삭제</button></div>
  </div>;
}
