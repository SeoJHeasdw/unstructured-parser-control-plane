import { FileArchive, FileImage, FileSpreadsheet, FileText } from 'lucide-react';

export function FileIcon({format}:{format:string}) {const Icon=format.includes('XL')||format==='CSV'?FileSpreadsheet:format==='ZIP'?FileArchive:['JPG','JPEG','PNG','HEIC'].includes(format)?FileImage:FileText;return <span className={'file-glyph '+(['XLSX','XLS','CSV'].includes(format)?'sheet':format==='PDF'?'pdf':format==='ZIP'?'zip':'')}><Icon size={17}/></span>}
export function Status({status}:{status:string}) {const color=['처리 완료','연결 완료'].includes(status)?'green':status==='처리 실패'?'red':['검토 필요','형식 확인 필요','대상 미발견','후보 확인 필요'].includes(status)?'amber':status==='처리 중'?'blue':'gray';return <span className={'status-pill '+color}><i/>{status}</span>}
export const attention = (status:string)=>['검토 필요','형식 확인 필요','처리 실패'].includes(status);

