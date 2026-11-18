import type { DocumentItem } from '../types';
import type { ReviewLocation } from './ResultReview';
import { OriginalPane, PdfSource, WorksheetSource } from './SourceViewer';
import type { Worksheet } from './SourceViewer';
import { cellCoordinates, columnName, MAX_WORKSHEET_COLUMN, MAX_WORKSHEET_ROW } from './worksheet';
import bmr from './sources/bmr-2026-0842.pdf?url';
import coa from './sources/coa-260118.pdf?url';
import sop from './sources/sop-qc-0040-rev5.pdf?url';
import workbook from './sources/equipment-inspection-2026.xlsx?url';
import deviation from './sources/dev-2026-018.docx?url';
import workbookRows from './sources/equipment-inspection-2026.json';

type SampleFile = { href: string; pages?: number; sheets?: Record<string, string[][]> };
const sources: Readonly<Record<string, SampleFile>> = {
  'DOC-0842': { href: bmr, pages: 3 },
  'DOC-0841': { href: workbook, sheets: workbookRows },
  'DOC-0840': { href: coa, pages: 1 },
  'DOC-0836': { href: deviation },
  'DOC-0835': { href: sop, pages: 6 },
};

function worksheet(sheets: Record<string, string[][]>, location?: ReviewLocation): Worksheet {
  const names = Object.keys(sheets);
  const sheet = location?.sheet && names.includes(location.sheet) ? location.sheet : names[0];
  const cell = location?.cell ?? 'A1';
  const { row, column } = cellCoordinates(cell) ?? { row: 1, column: 1 };
  const firstRow = Math.max(1, row - 3);
  const firstColumn = Math.max(1, column - 2);
  const columns = Array.from({ length: Math.min(MAX_WORKSHEET_COLUMN, column + 4) - firstColumn + 1 }, (_, offset) => columnName(firstColumn + offset));
  return { kind: 'sheet', sheets: names, sheet, cell, first_row: firstRow, columns,
    rows: Array.from({ length: Math.min(MAX_WORKSHEET_ROW, row + 8) - firstRow + 1 }, (_, rowIndex) =>
      columns.map((_, columnIndex) => sheets[sheet][firstRow - 1 + rowIndex]?.[firstColumn - 1 + columnIndex] ?? '')) };
}

export function SampleOriginal({ doc, location, onLocation }: { doc: DocumentItem; location?: ReviewLocation; onLocation: (location: ReviewLocation) => void }) {
  const source = doc.simulated ? undefined : sources[doc.id];
  if (!source) return <OriginalPane name={doc.name} label="예시 문서" fallback={<p>이 예시에는 연결된 원본 파일이 없어요.</p>} />;
  const { href, pages, sheets } = source;
  if (pages) {
    const page = location?.page ?? 1;
    return <OriginalPane name={doc.name} label="예시 PDF" href={`${href}#page=${page}`}
      preview={expanded => <PdfSource href={href} page={page} expanded={expanded} pages={pages} onPage={next => onLocation({ page: next, sheet: null })} />} />;
  }
  if (sheets) {
    const data = worksheet(sheets, location);
    return <OriginalPane name={doc.name} label="예시 XLSX 셀 값" href={href} downloadName={doc.name}
      preview={() => <WorksheetSource key={`${data.sheet}!${data.cell}`} data={data} onLocation={onLocation} />} />;
  }
  return <OriginalPane name={doc.name} label="예시 DOCX" href={href} downloadName={doc.name}
    fallback={<div><strong>Word에서 열어 확인하세요</strong><p>원본을 다운로드하면 페이지 배치와 서식을 그대로 확인할 수 있어요.</p></div>} />;
}
