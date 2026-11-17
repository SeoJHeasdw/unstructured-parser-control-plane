import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { DocumentItem } from './types';
import { LiveCompare } from './compare/LiveCompare';
import { ResultReview } from './compare/ResultReview';
import { RunSummary } from './compare/RunSummary';
import { ChunkText } from './retrieval/chunk-detail';
import './compare/compare.css';

export type CompareSource = 'sample' | 'live';
type Props = {
  docs: DocumentItem[]; selectedId: string; onChange: (id: string) => void; onOpenDoc: (id: string) => void;
  source: CompareSource; onSourceChange: (source: CompareSource) => void;
  liveId: string; onLiveChange: (id: string) => void; active: boolean;
  sampleStatus: 'loading' | 'error' | 'ready'; onRetrySample: () => void;
};

export function CompareView({ docs, selectedId, onChange, onOpenDoc, source, onSourceChange, liveId, onLiveChange, active,
  sampleStatus, onRetrySample }: Props) {
  const [showOriginal, setShowOriginal] = useState(true);
  const [showAlternative, setShowAlternative] = useState(true);
  const [highlight, setHighlight] = useState(true);
  const doc = docs.find(item => item.id === selectedId) ?? docs[0];
  const options = { showOriginal, showAlternative, highlight };
  const ready = doc && !doc.simulated && (doc.status === '처리 완료' || doc.status === '검토 필요');
  const switches = <div className="compare-switches">
    <button className={`button-toggle${showOriginal ? ' is-on' : ''}`} onClick={() => setShowOriginal(!showOriginal)} aria-pressed={showOriginal}>원문 보기</button>
    <button className={`button-toggle${showAlternative ? ' is-on' : ''}`} onClick={() => setShowAlternative(!showAlternative)} aria-pressed={showAlternative}>현재 실행 보기</button>
    <button className={`button-toggle${highlight ? ' is-on' : ''}`} onClick={() => setHighlight(!highlight)} aria-pressed={highlight}>차이 강조</button>
  </div>;
  const sourceTabs = <div className="compare-source" role="group" aria-label="비교 데이터">
    <button type="button" aria-pressed={source === 'sample'} onClick={() => onSourceChange('sample')}>예시</button>
    <button type="button" aria-pressed={source === 'live'} onClick={() => onSourceChange('live')}>실제 실행</button>
  </div>;

  return <div className="compare-space">
    {source === 'live' ? <LiveCompare active={active} selectedId={liveId} onChange={onLiveChange}
      sourceTabs={sourceTabs} switches={switches} options={options} onShowOriginal={() => setShowOriginal(true)} />
      : <>
        <section className="panel compare-controls">
          <div className="compare-controls-start">{sourceTabs}{doc && <div className="compare-document">
            <label htmlFor="compare-document">비교 문서</label>
            <select id="compare-document" title={doc.name} value={doc.id} onChange={event => onChange(event.target.value)}>
              {docs.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
            </select>
          </div>}</div>
          <div className="compare-controls-end">{switches}
            {doc && <button className="button-quiet" onClick={() => onOpenDoc(doc.id)}>문서 상세 <ChevronRight size={14} /></button>}
          </div>
        </section>
        {doc && ready && <RunSummary key={`s-${doc.id}`} before={{ text: doc.text, label: `${doc.parser} · 예시` }} after={{ text: doc.compare, label: '다른 설정 · 예시' }} />}
        {doc ? <ResultReview key={doc.id} {...options}
          baseline={ready ? { text: doc.text, meta: <p className="compare-run-meta">{doc.parser} · 예시</p> } : undefined}
          candidate={ready ? { text: doc.compare, meta: <p className="compare-run-meta">다른 설정 · 예시</p> } : undefined}
          original={<section className="panel compare-original">
            <header><h2>원문 미리보기</h2><span>{doc.format}</span></header>
            {ready ? <><article className="compare-sheet" aria-label="예시 문서 1쪽">
              <div className="compare-sheet-head"><span>{doc.name.replace(/\.[^.]+$/, '')}</span><span>{doc.format}</span></div>
              <div className="compare-sheet-body"><ChunkText text={doc.text} /></div>
              <div className="compare-sheet-foot"><span>예시 데이터</span><span>1 / 1</span></div>
            </article><p className="compare-sheet-note">예시 문서는 원본 파일 없이 내용만 쪽 모양으로 보여 줍니다.</p></>
              : <div className="compare-paper"><p>{doc.note}</p></div>}
          </section>} />
          : <div className="panel empty-view" role={sampleStatus === 'error' ? 'alert' : 'status'}>
            {sampleStatus === 'error' ? <>예시 문서를 불러오지 못했어요.<button className="button-secondary" onClick={onRetrySample}>다시 시도</button></>
              : sampleStatus === 'loading' ? '예시 문서를 불러오는 중…' : '비교할 문서가 없습니다.'}
          </div>}
      </>}
  </div>;
}
