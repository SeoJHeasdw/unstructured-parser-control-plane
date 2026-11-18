import { FileArchive, FileImage, FileSpreadsheet, FileText, Mail, Presentation } from 'lucide-react';

const spreadsheets = new Set(['CSV', 'TSV', 'XLS', 'XLSM', 'XLSX', 'ODS']);
const images = new Set(['GIF', 'HEIC', 'JPEG', 'JPG', 'PNG', 'TIFF', 'WEBP']);
const archives = new Set(['7Z', 'GZ', 'RAR', 'TAR', 'ZIP']);
const slides = new Set(['ODP', 'PPT', 'PPTM', 'PPTX']);

function fileAppearance(format: string) {
  if (spreadsheets.has(format)) return { Icon: FileSpreadsheet, tone: 'sheet' };
  if (images.has(format)) return { Icon: FileImage, tone: 'image' };
  if (archives.has(format)) return { Icon: FileArchive, tone: 'archive' };
  if (slides.has(format)) return { Icon: Presentation, tone: 'slides' };
  if (format === 'EML' || format === 'MSG') return { Icon: Mail, tone: 'mail' };
  return { Icon: FileText, tone: format === 'PDF' ? 'pdf' : 'document' };
}

export function FileIcon({ format }: { format: string }) {
  const { Icon, tone } = fileAppearance(format.toUpperCase());
  return (
    <span className={`inventory-file-icon is-${tone}`} aria-hidden="true">
      <Icon size={20} strokeWidth={1.7} />
    </span>
  );
}

const attentionStatuses = ['검토 필요', '형식 확인 필요', '처리 실패'];
export const attention = (status: string) => attentionStatuses.includes(status);

export function Status({ status }: { status: string }) {
  let tone = 'neutral';
  if (status === '처리 완료' || status === '연결 완료') tone = 'ok';
  else if (status === '처리 실패') tone = 'bad';
  else if (attention(status) || status === '대상 미발견' || status === '후보 확인 필요') tone = 'warn';
  else if (status === '처리 중') tone = 'active';

  return <span className={`inventory-status is-${tone}`}><i aria-hidden="true" />{status}</span>;
}
