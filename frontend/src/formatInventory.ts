/** 사용자가 이전 대화에서 알려준 초기 대상. 전체 범위를 제한하지 않는다. */
export const REPORTED_FORMAT_GROUPS = [
  {label:'문서 · 슬라이드', formats:['PDF','DOCX','DOCM','DOC','PPTX','PPT']},
  {label:'스프레드시트', formats:['XLSX','XLSM','XLS','CSV']},
  {label:'메일 · 웹', formats:['EML','MSG','MHT','HTM']},
  {label:'이미지', formats:['PNG','JPG']},
  {label:'텍스트 · 로그', formats:['TXT','LOG']},
  {label:'압축', formats:['ZIP']},
] as const;
export const REPORTED_FORMATS: readonly string[] = REPORTED_FORMAT_GROUPS.flatMap(group=>[...group.formats]);
