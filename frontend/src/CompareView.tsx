import { useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowRight, Database, FileSearch, FlaskConical, Highlighter, Layers2, PanelLeft, TriangleAlert } from 'lucide-react';
import type { DocumentItem } from './types';
import { CompareState, LiveCompare } from './compare/LiveCompare';
import { ResultReview } from './compare/ResultReview';
import { RunSummary } from './compare/RunSummary';
import { SampleOriginal } from './compare/SampleOriginal';
import { lines } from './compare/diff';
import type { ReviewLocation } from './compare/ResultReview';
import './compare/compare.css';

export type CompareSource = 'sample' | 'live';
type Props = {
  docs: DocumentItem[];
  selectedId: string;
  onChange: (id: string) => void;
  onOpenDoc: (id: string) => void;
  source: CompareSource;
  onSourceChange: (source: CompareSource) => void;
  liveId: string;
  onLiveChange: (id: string) => void;
  active: boolean;
  sampleStatus: 'loading' | 'error' | 'ready';
  onRetrySample: () => void;
  onOpenLive?: () => void;
};

export function CompareView({ docs, selectedId, onChange, onOpenDoc, source, onSourceChange, liveId, onLiveChange, active,
  sampleStatus, onRetrySample, onOpenLive }: Props) {
  const [showOriginal, setShowOriginal] = useState(true);
  const [showAlternative, setShowAlternative] = useState(true);
  const [highlight, setHighlight] = useState(true);
  const doc = docs.find(item => item.id === selectedId) ?? docs[0];
  const options = { showOriginal, showAlternative, highlight };
  const ready = doc && !doc.simulated && (doc.status === '처리 완료' || doc.status === '검토 필요');
  const example = docs.find(item => !item.simulated && (item.status === '처리 완료' || item.status === '검토 필요'));
  const switches = <div className="compare-switches" role="group" aria-label="검수 보기 설정">
    <button type="button" onClick={() => setShowOriginal(!showOriginal)} aria-pressed={showOriginal}><PanelLeft size={16} aria-hidden="true" />원문 보기</button>
    <button type="button" onClick={() => setShowAlternative(!showAlternative)} aria-pressed={showAlternative}><Layers2 size={16} aria-hidden="true" />현재 실행 보기</button>
    <button type="button" onClick={() => setHighlight(!highlight)} aria-pressed={highlight}><Highlighter size={16} aria-hidden="true" />차이 강조</button>
  </div>;
  const sourceTabs = <div className="compare-source-group">
    <span className="compare-control-label">데이터 출처</span>
    <div className="compare-source" role="group" aria-label="비교 데이터">
      <button type="button" aria-pressed={source === 'sample'} onClick={() => onSourceChange('sample')}><FlaskConical size={16} aria-hidden="true" />예시 데이터</button>
      <button type="button" aria-pressed={source === 'live'} onClick={() => onSourceChange('live')}><Database size={16} aria-hidden="true" />실제 실행</button>
    </div>
  </div>;

  return <div className="compare-space">
    {source === 'live' ? <LiveCompare active={active} selectedId={liveId} onChange={onLiveChange}
      sourceTabs={sourceTabs} switches={switches} options={options} onShowOriginal={() => setShowOriginal(true)} onOpenLive={onOpenLive}
      onOpenExample={() => onSourceChange('sample')} />
      : <>
        <section className="panel compare-controls" aria-label="비교 설정">
          <div className="compare-controls-start">{sourceTabs}{doc && <div className="compare-document">
            <label className="compare-control-label" htmlFor="compare-document">비교 문서</label>
            <select id="compare-document" title={doc.name} value={doc.id} onChange={event => onChange(event.target.value)}>
              {docs.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
            </select>
          </div>}</div>
          <div className="compare-controls-end">{doc &&
            <button type="button" className="button-secondary" onClick={() => onOpenDoc(doc.id)}>문서 상세 <ArrowRight size={15} aria-hidden="true" /></button>}
          </div>
        </section>
        {doc && ready ? <SampleComparison key={doc.id} doc={doc} controls={switches} options={options} onShowOriginal={() => setShowOriginal(true)} /> : doc ? <CompareState icon={FileSearch} title="이 문서에는 비교할 결과가 없습니다" message={doc.note}
          actions={example && <button type="button" className="button-secondary" onClick={() => onChange(example.id)}>비교 가능한 예시 열기 <ArrowRight size={15} aria-hidden="true" /></button>} />
        : sampleStatus === 'error' ? <CompareState icon={TriangleAlert} tone="error" title="예시 문서를 불러오지 못했어요"
          actions={<button type="button" className="button-secondary" onClick={onRetrySample}>다시 시도</button>} />
        : sampleStatus === 'loading' ? <CompareState title="예시 문서를 불러오는 중" tone="loading" />
        : <CompareState icon={FileSearch} title="비교할 예시 문서가 없습니다" />}
      </>}
  </div>;
}

function SampleComparison({ doc, controls, options, onShowOriginal }: {
  doc: DocumentItem; controls: ReactNode; options: { showOriginal: boolean; showAlternative: boolean; highlight: boolean }; onShowOriginal: () => void;
}) {
  const [location, setLocation] = useState<ReviewLocation>();
  const evidenceLine = doc.id === 'DOC-0842' ? lines(doc.text).findIndex(line => line.includes('SOP-PD-0076 Rev.3')) + 1 : 0;
  const locations = evidenceLine > 0 ? [{ start_line: evidenceLine, end_line: evidenceLine, page: 3, sheet: null, row: null, column: null, columns: null }] : undefined;
  return <>
    <RunSummary before={{ text: doc.text, label: doc.parser }} after={{ text: doc.compare, label: '다른 설정' }} />
    <ResultReview {...options} controls={controls}
      baseline={{ text: doc.text, meta: <p className="compare-run-meta">{doc.parser}</p>, locations }}
      candidate={{ text: doc.compare, meta: <p className="compare-run-meta">다른 설정</p> }}
      onLocation={(value, reveal) => { if (value) setLocation(value); if (reveal) onShowOriginal(); }}
      original={<SampleOriginal doc={doc} location={location} onLocation={setLocation} />} />
  </>;
}
