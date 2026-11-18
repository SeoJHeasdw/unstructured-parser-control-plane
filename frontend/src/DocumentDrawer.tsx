import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft, ArrowRight, Clipboard, FileSearch, GitCompareArrows, Info, Link2, TriangleAlert, Workflow, X,
} from 'lucide-react';
import type { DocumentItem, Relation } from './types';
import { FileIcon, Status, attention } from './DocumentCommon';
import { Tabs } from './ui';
import './documents.css';

type Props = {
  doc: DocumentItem;
  relations: Relation[];
  onClose: () => void;
  onCompare: () => void;
  onPipeline: () => void;
  onOpenRelated?: (id: string) => boolean;
};

type View = 'info' | 'process' | 'relation';
type HistoryEntry = { id: string; name: string };
const FOCUSABLE = 'button:not([disabled]):not([tabindex="-1"]), [href], input:not([disabled]), select:not([disabled]), [tabindex="0"]';

export function DocumentDrawer({ doc, relations, onClose, onCompare, onPipeline, onOpenRelated }: Props) {
  const [view, setView] = useState<View>('info');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [feedback, setFeedback] = useState('');
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const documentName = useRef<HTMLHeadingElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const moveFocusToName = useRef(false);
  const dialogTitle = useId();
  const related = relations.filter(relation => relation.sourceId === doc.id || relation.targetId === doc.id);
  const previous = history.at(-1);
  const routeFirst = doc.simulated || doc.status === '형식 확인 필요' || doc.status === '처리 실패';
  const hasIssue = attention(doc.status);
  const NoteIcon = hasIssue ? TriangleAlert : Info;
  const properties = [
    ['원천', doc.source], ['파일 크기', doc.size], ['최근 처리', doc.updated],
    ['현재 단계', doc.stage], ['처리 경로', doc.parser],
    ['OCR', doc.simulated ? '실행 전' : doc.ocr ? '적용 예시' : '미적용 예시'],
  ];

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const shell = document.getElementById('root');
    const wasInert = shell?.inert ?? false;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    if (shell) shell.inert = true;
    closeRef.current?.focus({ preventScroll: true });
    return () => {
      if (shell) shell.inert = wasInert;
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    if (moveFocusToName.current) {
      documentName.current?.focus({ preventScroll: true });
      moveFocusToName.current = false;
    }
  }, [doc.id]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (!items?.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === documentName.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const openRelated = (id: string) => {
    if (id === doc.id || !onOpenRelated?.(id)) {
      setFeedback('예시 목록에서 연결 문서를 찾을 수 없습니다.');
      return;
    }
    setHistory(items => [...items, { id: doc.id, name: doc.name }]);
    setFeedback('');
    setView('info');
    moveFocusToName.current = true;
  };

  const goBack = () => {
    if (!previous || !onOpenRelated?.(previous.id)) return;
    setHistory(items => items.slice(0, -1));
    setFeedback('');
    setView('relation');
    moveFocusToName.current = true;
  };

  const copyId = async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(doc.id);
      setFeedback('문서 ID가 복사되었습니다.');
    } catch {
      setFeedback('복사 기능을 사용할 수 없습니다. 문서 ID를 선택해 복사하세요.');
    }
  };

  const comparisonAction = (
    <button type="button" className={routeFirst ? 'inventory-secondary' : 'inventory-primary'} onClick={onCompare}>
      <GitCompareArrows size={17} aria-hidden="true" />파싱 결과 비교
    </button>
  );
  const pipelineAction = (
    <button type="button" className={routeFirst ? 'inventory-primary' : 'inventory-secondary'} onClick={onPipeline}>
      <Workflow size={17} aria-hidden="true" />처리 경로 보기
    </button>
  );

  return createPortal(
    <div className="inventory-drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="inventory-drawer" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={dialogTitle} onKeyDown={onKeyDown}>
        <header className="inventory-drawer-header">
          <div><FileSearch size={19} strokeWidth={1.8} aria-hidden="true" /><h2 id={dialogTitle}>문서 상세</h2></div>
          <button type="button" ref={closeRef} className="inventory-icon-button" aria-label="문서 상세 닫기" onClick={onClose}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <div className="inventory-drawer-scroll" ref={scrollRef}>
          <div className="inventory-drawer-summary">
            {previous && <button type="button" className="inventory-back inventory-text-button" onClick={goBack}>
              <ArrowLeft size={16} aria-hidden="true" /><span>{previous.name}</span>
            </button>}
            <div className="inventory-drawer-file">
              <FileIcon format={doc.format} />
              <div>
                <div className="inventory-drawer-meta">
                  <code>{doc.id}</code>
                  <span className="inventory-format">{doc.format}</span>
                  <button type="button" className="inventory-icon-button inventory-copy" aria-label="문서 ID 복사" title="문서 ID 복사"
                    onClick={() => void copyId()}><Clipboard size={16} aria-hidden="true" /></button>
                </div>
                <h3 ref={documentName} tabIndex={-1}>{doc.name}</h3>
                <Status status={doc.status} />
              </div>
            </div>
            {feedback && <p className="inventory-drawer-feedback" role="status">{feedback}</p>}
            {doc.note && <div className={`inventory-drawer-note${hasIssue ? ' is-warning' : ''}${doc.status === '처리 실패' ? ' is-error' : ''}`}>
              <NoteIcon size={18} strokeWidth={1.8} aria-hidden="true" /><p>{doc.note}</p>
            </div>}
          </div>

          <Tabs<View> className="inventory-drawer-tabs" items={[
            { id: 'info', label: '문서 정보' },
            { id: 'process', label: '처리 이력' },
            { id: 'relation', label: '문서 간 참조', badge: related.length },
          ]} value={view} onChange={setView} label="문서 세부 정보">
            {active => (
              <div className="inventory-detail-body">
                {active === 'info' && <dl className="inventory-properties">
                  {properties.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '기록 없음'}</dd></div>)}
                </dl>}
                {active === 'process' && <ol className="inventory-timeline" aria-label="예시 처리 이력">
                  <li><span aria-hidden="true" /><div><b>파일 정보 확인</b><p>파일 형식 · {doc.format}</p></div></li>
                  <li className="is-current"><span aria-hidden="true" /><div><b>{doc.stage}</b><p>{doc.updated}</p></div><Status status={doc.status} /></li>
                </ol>}
                {active === 'relation' && (
                  related.length ? <ul className="inventory-relations">{related.map(relation => {
                    const outgoing = relation.sourceId === doc.id;
                    const anotherId = outgoing ? relation.targetId : relation.sourceId;
                    const name = outgoing ? relation.target : relation.source;
                    return <li key={relation.id}>
                      <div className="inventory-relation-head">
                        <span className="inventory-relation-icon"><Link2 size={18} strokeWidth={1.8} aria-hidden="true" /></span>
                        <div><span>{outgoing ? '나가는 참조' : '들어오는 참조'}</span><strong>{name}</strong></div>
                        <Status status={relation.status} />
                      </div>
                      <p className="inventory-relation-meta">{relation.location} · {relation.method}</p>
                      {relation.evidence && <blockquote>{relation.evidence}</blockquote>}
                      {anotherId && anotherId !== doc.id && onOpenRelated && (
                        <button type="button" className="inventory-text-button" aria-label={`${name} 열기`} onClick={() => openRelated(anotherId)}>
                          연결 문서 열기 <ArrowRight size={15} aria-hidden="true" />
                        </button>
                      )}
                    </li>;
                  })}</ul> : <div className="inventory-detail-empty"><Link2 size={23} aria-hidden="true" /><p>표시할 참조 관계가 없습니다.</p></div>
                )}
              </div>
            )}
          </Tabs>
        </div>
        <footer className="inventory-drawer-footer">
          <span>{doc.simulated ? '직접 추가한 파일 정보' : '예시 문서 및 처리 기록'}</span>
          <div>{routeFirst ? <>{pipelineAction}{comparisonAction}</> : <>{comparisonAction}{pipelineAction}</>}</div>
        </footer>
      </aside>
    </div>,
    document.body,
  );
}
