import { ArrowRight, CircleCheck, TriangleAlert } from 'lucide-react';
import type { DocumentFilter, DocumentItem } from './types';
import { attention, Status } from './DocumentCommon';

export default function Dashboard({ docs, onOpenDoc, onNavigate }: {
  docs: DocumentItem[]; onOpenDoc: (id: string) => void; onNavigate: (page: 'documents', filter?: DocumentFilter) => void;
}) {
  const issues = docs.filter(doc => attention(doc.status));
  return <section className="workspace-sheet">
    <header className="sheet-heading"><div><h2><TriangleAlert size={19} />확인이 필요한 문서</h2><p>처리 실패, 형식 확인 또는 검토가 필요한 예시 문서입니다.</p></div>
      <button className="button-secondary" onClick={() => onNavigate('documents', { status: '확인 필요 전체' })}>확인 필요 {issues.length}건 <ArrowRight size={16}/></button></header>
    {issues.length ? <ul className="exception-list">{issues.map(doc => <li key={doc.id}>
      <button onClick={() => onOpenDoc(doc.id)}><span><strong>{doc.name}</strong><small>{doc.note}</small></span><Status status={doc.status}/></button>
    </li>)}</ul> : <p className="workspace-empty"><CircleCheck size={20}/>확인이 필요한 예시 문서가 없습니다.</p>}
  </section>;
}
