import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import type { DocumentItem } from './types';
import { CompareState } from './compare/LiveCompare';
import { ReviewDesk } from './compare/ReviewDesk';
import { RunSummary } from './compare/RunSummary';
import { SampleOriginal } from './compare/SampleOriginal';
import { lines } from './compare/diff';
import type { ReviewLocation } from './compare/ResultReview';
import type { ReviewMode } from './navigation';

export function CompareView({ docs, selectedId, onChange, onOpenDoc }: {
  docs: DocumentItem[]; selectedId: string; onChange: (id: string) => void; onOpenDoc: (id: string) => void;
}) {
  const doc = docs.find(d => d.id === selectedId) ?? docs[0];
  if (!doc) return <CompareState title="비교할 예시 문서가 없습니다"/>;
  const ready = (d: DocumentItem) => !d.simulated && ['처리 완료','검토 필요'].includes(d.status);
  const example = docs.find(ready);
  return <div className="compare-space"><section className="panel compare-controls" aria-label="예시 문서 선택">
    <label className="compare-document">비교 문서<select value={doc.id} onChange={e => onChange(e.target.value)}>{docs.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
    <button className="button-secondary" onClick={() => onOpenDoc(doc.id)}>문서 상세 <ArrowRight size={15}/></button></section>
    {ready(doc) ? <SampleComparison key={doc.id} doc={doc}/> : <CompareState title="이 문서에는 비교할 결과가 없습니다" message={doc.note}
      actions={example && <button className="button-secondary" onClick={() => onChange(example.id)}>비교 가능한 예시 열기</button>}/>}
  </div>;
}
function SampleComparison({ doc }: {doc: DocumentItem}) {
  const [location, setLocation] = useState<ReviewLocation>();
  const [mode, setMode] = useState<ReviewMode>('source');
  const evidenceLine = doc.id === 'DOC-0842' ? lines(doc.text).findIndex(line => line.includes('SOP-PD-0076 Rev.3')) + 1 : 0;
  const locations = evidenceLine > 0 ? [{ start_line:evidenceLine, end_line:evidenceLine, page:3, sheet:null, row:null, column:null, columns:null }] : undefined;
  const before = {text:doc.text, locations, meta:<p>{doc.parser}</p>};
  return <ReviewDesk mode={mode} onMode={setMode} canCompare baseline={before} candidate={{text:doc.compare,meta:<p>다른 설정</p>}} sourcePane={before}
    onLocation={setLocation} original={<SampleOriginal doc={doc} location={location} onLocation={setLocation}/>}
    summary={<RunSummary before={{text:doc.text,label:doc.parser}} after={{text:doc.compare,label:'다른 설정'}}/>}/>;
}
