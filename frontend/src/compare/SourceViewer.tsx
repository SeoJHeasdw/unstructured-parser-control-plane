import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, ExternalLink, FileText, Maximize2 } from 'lucide-react';
import type { SourcePreview } from '../api/live';
import { Modal } from '../ui';
import type { ReviewLocation } from './ResultReview';
import { cellCoordinates } from './worksheet';

type OriginalProps = {
  name: string;
  label: string;
  href?: string;
  downloadName?: string;
  preview?: (expanded: boolean) => ReactNode;
  fallback?: ReactNode;
};

export function OriginalPane({ name, label, href, downloadName, preview, fallback }: OriginalProps) {
  const [expanded, setExpanded] = useState(false);
  const originalLink = href && (downloadName
    ? <a className="button-secondary" href={href} download={downloadName} title={downloadName}><ArrowDownToLine size={15} aria-hidden="true" />원본 다운로드</a>
    : <a className="button-secondary" href={href} target="_blank" rel="noreferrer">원본 열기 <ExternalLink size={15} aria-hidden="true" /></a>);
  return <section className="panel compare-original" aria-label="원본 문서">
    <header>
      <div className="compare-original-identity">
        <div className="compare-original-label">
          <h2><FileText size={18} aria-hidden="true" />원본 문서</h2>
          <span className="compare-source-badge">{label}</span>
        </div>
        <p className="compare-source-filename" title={name}>{name}</p>
      </div>
      <div className="compare-original-actions">
        {preview && <button type="button" className="button-secondary compare-enlarge" aria-haspopup="dialog" onClick={() => setExpanded(true)}><Maximize2 size={14} aria-hidden="true" />크게 보기</button>}
        {originalLink}
      </div>
    </header>
    {expanded ? <div className="compare-source-placeholder"><p>원본을 확대해 보고 있어요.</p></div>
      : preview ? preview(false) : <div className="compare-source-placeholder">{fallback}</div>}
    {expanded && <Modal open title="원본 문서" subtitle={name} size="xl" flush onClose={() => setExpanded(false)} extra={originalLink}>
      <div className="compare-source-expanded">{preview ? preview(true) : <div className="compare-source-placeholder">{fallback}</div>}</div>
    </Modal>}
  </section>;
}

export function PdfSource({ href, page, expanded, pages, onPage }: {
  href: string; page: number; expanded: boolean; pages?: number; onPage?: (page: number) => void;
}) {
  return <div className="compare-pdf-source">
    {!expanded && pages !== undefined && pages > 1 && onPage && <div className="compare-source-pages" role="group" aria-label="원본 PDF 페이지">
      <button type="button" className="plain-icon" aria-label="이전 원본 페이지" onClick={() => onPage(page - 1)} disabled={page <= 1}><ArrowLeft size={16} aria-hidden="true" /></button>
      <span aria-live="polite">{page} / {pages}쪽</span>
      <button type="button" className="plain-icon" aria-label="다음 원본 페이지" onClick={() => onPage(page + 1)} disabled={page >= pages}><ArrowRight size={16} aria-hidden="true" /></button>
    </div>}
    <iframe key={`${href}#${page}`} title="PDF 원문" src={`${href}#page=${page}&view=FitH${expanded ? '' : '&toolbar=0'}`} />
  </div>;
}

export type Worksheet = Extract<SourcePreview, { kind: 'sheet' }>;

export function WorksheetSource({ data, onLocation }: { data: Worksheet; onLocation: (location: ReviewLocation) => void }) {
  const [address, setAddress] = useState(data.cell);
  function goToCell(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('cell') as HTMLInputElement;
    const cell = address.trim().toUpperCase();
    if (!cellCoordinates(cell)) {
      input.setCustomValidity('시트 범위의 셀 주소를 입력하세요. 예 A1, B12');
      input.reportValidity();
      return;
    }
    onLocation({ page: null, sheet: data.sheet, cell });
  }

  return <div className="compare-sheet-preview">
    <div className="compare-sheet-selector">
      <label className="compare-sheet-select">시트 <select value={data.sheet} onChange={event => onLocation({ page: null, sheet: event.target.value, cell: 'A1' })}>
        {data.sheets.map(name => <option key={name}>{name}</option>)}
      </select></label>
      <form className="compare-cell-control" onSubmit={goToCell}>
        <input aria-label="원본 셀 주소" name="cell" value={address} autoComplete="off" maxLength={10}
          onChange={event => { event.target.setCustomValidity(''); setAddress(event.target.value); }} />
        <button type="submit" className="button-secondary">이동</button>
      </form>
    </div>
    <div className="compare-sheet-scroll" role="region" aria-label="시트 원본 셀 값" tabIndex={0}><table>
      <thead><tr><td />{data.columns.map(column => <th key={column} scope="col">{column}</th>)}</tr></thead>
      <tbody>{data.rows.map((row, index) => <tr key={data.first_row + index}><th scope="row">{data.first_row + index}</th>
        {row.map((value, col) => <td key={data.columns[col]} className={data.cell === `${data.columns[col]}${data.first_row + index}` ? 'is-cell' : ''} title={value}>{value}</td>)}
      </tr>)}</tbody>
    </table></div>
  </div>;
}

export function TextSource({ text, truncated }: { text: string; truncated: boolean }) {
  return <div className="compare-paper"><pre>{text || '빈 원본 파일입니다.'}</pre>{truncated && <p>원본의 처음 60,000자</p>}</div>;
}
