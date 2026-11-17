import { useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { FileCheck2, ListChecks } from 'lucide-react';
import { Modal, Tabs } from '../ui';
import { gained, goldCategories, isGold, lost, measure, scoreGold } from './metrics';
import type { Gold, RunMetrics } from './metrics';

export type RunSide = { text: string; label: string; durationMs?: number | null; warnings?: number; locations?: { page: number | null }[] };
type Props = { before?: RunSide; after?: RunSide };

const nf = new Intl.NumberFormat('ko-KR');
const seconds = (ms: number | null | undefined) => ms === null || ms === undefined ? null : ms < 1000 ? `${nf.format(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} 초`;

type Row = { id: string; label: string; before: number | null; after: number | null; better: 'up' | 'down' | 'none'; format?: (value: number) => string };

function rowsOf(a: RunMetrics, b: RunMetrics, before: RunSide, after: RunSide): Row[] {
  return [
    { id: 'time', label: '처리 시간', before: before.durationMs ?? null, after: after.durationMs ?? null, better: 'down', format: value => seconds(value) ?? '—' },
    { id: 'chars', label: '글자 수', before: a.chars, after: b.chars, better: 'none' },
    { id: 'cells', label: '표 칸', before: a.cells, after: b.cells, better: 'none' },
    { id: 'tables', label: '표', before: a.tables, after: b.tables, better: 'none' },
    { id: 'headings', label: '제목', before: a.headings, after: b.headings, better: 'none' },
    { id: 'images', label: '그림 자리', before: a.images, after: b.images, better: 'none' },
    { id: 'numbers', label: '숫자·단위', before: a.numbers.size, after: b.numbers.size, better: 'up' },
    { id: 'docnos', label: '문서번호', before: a.docNumbers.size, after: b.docNumbers.size, better: 'up' },
    { id: 'broken', label: '깨진 글자', before: a.broken, after: b.broken, better: 'down' },
    { id: 'pages', label: '위치가 기록된 쪽', before: a.pages, after: b.pages, better: 'up' },
    { id: 'warnings', label: '경고', before: before.warnings ?? null, after: after.warnings ?? null, better: 'down' },
  ];
}

function Delta({ row }: { row: Row }) {
  if (row.before === null || row.after === null) return <span className="rs-delta">—</span>;
  const diff = row.after - row.before;
  if (diff === 0) return <span className="rs-delta">변화 없음</span>;
  const tone = row.better === 'none' ? '' : (diff > 0) === (row.better === 'up') ? ' is-good' : ' is-bad';
  const text = row.id === 'time' ? `${diff > 0 ? '+' : '−'}${seconds(Math.abs(diff))}${row.before ? ` (${diff > 0 ? '+' : '−'}${Math.round(Math.abs(diff) / row.before * 100)}%)` : ''}`
    : `${diff > 0 ? '+' : '−'}${nf.format(Math.abs(diff))}`;
  return <span className={'rs-delta' + tone}>{text}</span>;
}

const value = (row: Row, side: 'before' | 'after') => { const v = row[side]; return v === null ? '—' : row.format ? row.format(v) : nf.format(v); };
const SUMMARY = ['time', 'chars', 'cells', 'numbers', 'docnos', 'broken'];

/** 두 실행의 수치 변화 요약. 자세한 표와 정답 대조는 팝업으로 연다. */
export function RunSummary({ before, after }: Props) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'change' | 'gold'>('change');
  const [gold, setGold] = useState<{ name: string; data: Gold } | null>(null);
  const [goldError, setGoldError] = useState('');
  const file = useRef<HTMLInputElement>(null);
  const a = useMemo(() => before ? measure(before.text, before.locations) : null, [before?.text, before?.locations]); // eslint-disable-line react-hooks/exhaustive-deps
  const b = useMemo(() => after ? measure(after.text, after.locations) : null, [after?.text, after?.locations]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!before || !after || !a || !b) return null;
  const rows = rowsOf(a, b, before, after);
  const lostNumbers = lost(a.numbers, b.numbers), newNumbers = gained(a.numbers, b.numbers);
  const lostDocs = lost(a.docNumbers, b.docNumbers), newDocs = gained(a.docNumbers, b.docNumbers);
  const categories = gold ? goldCategories(gold.data) : [];
  const scores = gold ? { before: scoreGold(before.text, categories), after: scoreGold(after.text, categories) } : null;

  const loadGold = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    event.target.value = '';
    if (!picked) return;
    try {
      const data = JSON.parse(await picked.text()) as unknown;
      if (!isGold(data)) throw new Error('shape');
      setGold({ name: picked.name, data }); setGoldError('');
    } catch { setGoldError('정답 자료 형식을 읽을 수 없습니다. 핵심 값·표·숫자·제목·캡션·문장 중 하나 이상이 있는 JSON이어야 합니다.'); }
  };

  return <section className="panel rs-strip" aria-label="두 실행의 변화">
    <div className="rs-head">
      <p className="rs-runs"><span>이전 실행</span><b>{before.label}</b><span className="rs-arrow">→</span><span>현재 실행</span><b>{after.label}</b></p>
      <div className="rs-actions">
        <button type="button" className="button-secondary" onClick={() => { setTab('change'); setOpen(true); }}><ListChecks size={14} />변화 자세히</button>
        <button type="button" className="button-secondary" onClick={() => { setTab('gold'); setOpen(true); }}><FileCheck2 size={14} />정답 대조{scores && <em className="rs-badge">{pct(sum(scores.after))}</em>}</button>
      </div>
    </div>
    <dl className="rs-metrics">
      {rows.filter(row => SUMMARY.includes(row.id)).map(row => <div key={row.id}>
        <dt>{row.label}</dt>
        <dd><span className="ui-num">{value(row, 'after')}</span><Delta row={row} /></dd>
        {row.id === 'numbers' && lostNumbers.length > 0 && <dd className="rs-note is-bad">{nf.format(lostNumbers.length)}개 사라짐</dd>}
      </div>)}
    </dl>

    <Modal open={open} onClose={() => setOpen(false)} size="lg" title="두 실행 비교" subtitle={`${before.label} → ${after.label}`}
      tabs={<Tabs label="비교 보기" value={tab} onChange={setTab} items={[{ id: 'change', label: '변화 지표' }, { id: 'gold', label: '정답 대조' }]} />}>
      {tab === 'change' ? <>
        <table className="rs-table">
          <thead><tr><th scope="col">지표</th><th scope="col" className="is-num">이전 실행</th><th scope="col" className="is-num">현재 실행</th><th scope="col" className="is-num">변화</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.id}><th scope="row">{row.label}</th><td className="is-num">{value(row, 'before')}</td><td className="is-num">{value(row, 'after')}</td><td className="is-num"><Delta row={row} /></td></tr>)}</tbody>
        </table>
        <div className="rs-lists">
          <ItemList title="현재 실행에서 사라진 숫자·단위" items={lostNumbers} tone="bad" />
          <ItemList title="현재 실행에 새로 나온 숫자·단위" items={newNumbers} />
          <ItemList title="사라진 문서번호" items={lostDocs} tone="bad" />
          <ItemList title="새로 나온 문서번호" items={newDocs} />
        </div>
        <p className="rs-foot">정답 자료 없이 결과끼리 비교한 값입니다. 어느 쪽이 맞는지는 정답 대조에서 확인합니다.</p>
      </> : <>
        <div className="rs-gold-bar">
          <p>{gold ? <><b>{gold.name}</b>{gold.data.title ? ` · ${gold.data.title}` : ''}</> : '이 문서의 정답 자료(JSON)를 불러오면 두 실행이 정답을 얼마나 찾았는지 잽니다.'}</p>
          <button type="button" className="button-secondary" onClick={() => file.current?.click()}>{gold ? '다른 정답 자료' : '정답 자료 불러오기'}</button>
          <input ref={file} type="file" accept="application/json,.json" hidden onChange={loadGold} aria-label="정답 자료 파일" />
        </div>
        {goldError && <p className="rs-error" role="alert">{goldError}</p>}
        {scores && <>
          <table className="rs-table">
            <thead><tr><th scope="col">항목</th><th scope="col" className="is-num">정답 수</th><th scope="col" className="is-num">이전 실행</th><th scope="col" className="is-num">현재 실행</th></tr></thead>
            <tbody>
              {scores.after.map((row, i) => <tr key={row.id}><th scope="row">{row.label}</th><td className="is-num">{nf.format(row.total)}</td>
                <td className="is-num">{ratio(scores.before[i].found, row.total)}</td><td className="is-num"><b>{ratio(row.found, row.total)}</b></td></tr>)}
              <tr className="rs-total"><th scope="row">전체</th><td className="is-num">{nf.format(scores.after.reduce((n, row) => n + row.total, 0))}</td>
                <td className="is-num">{pct(sum(scores.before))}</td><td className="is-num"><b>{pct(sum(scores.after))}</b></td></tr>
            </tbody>
          </table>
          <div className="rs-lists">
            <ItemList title="현재 실행이 못 찾은 정답" items={scores.after.flatMap(row => row.missing.map(item => `${row.label} · ${item}`))} tone="bad" />
            <ItemList title="이전 실행이 못 찾은 정답" items={scores.before.flatMap(row => row.missing.map(item => `${row.label} · ${item}`))} />
          </div>
          <p className="rs-foot">띄어쓰기는 무시하고 정답 값이 결과에 그대로 있는지만 봅니다. 표 칸의 위치는 아직 보지 않습니다.</p>
        </>}
      </>}
    </Modal>
  </section>;
}

const sum = (rows: { found: number; total: number }[]) => { const total = rows.reduce((n, row) => n + row.total, 0); return total ? rows.reduce((n, row) => n + row.found, 0) / total : 0; };
const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const ratio = (found: number, total: number) => `${nf.format(found)} / ${nf.format(total)} · ${pct(total ? found / total : 0)}`;

function ItemList({ title, items, tone }: { title: string; items: string[]; tone?: 'bad' }) {
  return <div className="rs-list">
    <h3>{title} <span className="ui-num">{nf.format(items.length)}</span></h3>
    {items.length ? <ul className={tone === 'bad' ? 'is-bad' : ''}>{items.slice(0, 40).map(item => <li key={item}>{item}</li>)}{items.length > 40 && <li className="rs-more">외 {nf.format(items.length - 40)}개</li>}</ul>
      : <p className="rs-none">없음</p>}
  </div>;
}
