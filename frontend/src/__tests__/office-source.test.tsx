import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import JSZip from 'jszip';
import { readPptx } from '../compare/pptx';
import type { Shape } from '../compare/pptx';
import OfficeSource from '../compare/OfficeSource';

/* 합성 PPTX·DOCX만 쓴다. 실제 고객 문서를 쓰지 않는다. */
const P = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"';
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const rels = (items: [string, string, string][]) => `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${
  items.map(([id, type, target]) => `<Relationship Id="${id}" Type="${R}/${type}" Target="${target}"/>`).join('')}</Relationships>`;
const xfrm = (x: number, y: number, w: number, h: number) => `<a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${w}" cy="${h}"/></a:xfrm>`;
const ph = (type: string | null, idx?: string) => `<p:nvPr><p:ph${type ? ` type="${type}"` : ''}${idx ? ` idx="${idx}"` : ''}/></p:nvPr>`;
const sp = (name: string, nvPr: string, spPr: string, body = '') =>
  `<p:sp><p:nvSpPr><p:cNvPr id="1" name="${name}"/><p:cNvSpPr/>${nvPr}</p:nvSpPr><p:spPr>${spPr}</p:spPr>${body}</p:sp>`;
const para = (text: string, lvl = 0, rPr = '') => `<a:p>${lvl ? `<a:pPr lvl="${lvl}"/>` : ''}<a:r>${rPr || '<a:rPr lang="ko-KR"/>'}<a:t>${text}</a:t></a:r></a:p>`;
const PNG = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='), c => c.charCodeAt(0));

async function samplePptx() {
  const zip = new JSZip();
  zip.file('ppt/presentation.xml', `<p:presentation ${P}><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/></p:sldIdLst>
    <p:sldSz cx="9144000" cy="6858000"/><p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>`);
  zip.file('ppt/_rels/presentation.xml.rels', rels([['rId1', 'slideMaster', 'slideMasters/slideMaster1.xml'], ['rId2', 'slide', 'slides/slide1.xml'], ['rId3', 'slide', 'slides/slide2.xml']]));
  zip.file('ppt/theme/theme1.xml', `<a:theme ${P}><a:themeElements><a:clrScheme name="t"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
    <a:dk2><a:srgbClr val="1F497D"/></a:dk2><a:lt2><a:srgbClr val="EEECE1"/></a:lt2><a:accent1><a:srgbClr val="4F81BD"/></a:accent1></a:clrScheme>
    <a:fontScheme name="f"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface="맑은 고딕"/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface="맑은 고딕"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>`);
  zip.file('ppt/slideMasters/slideMaster1.xml', `<p:sldMaster ${P}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="F0F0F0"/></a:solidFill></p:bgPr></p:bg><p:spTree>
    ${sp('Title Placeholder', ph('title'), xfrm(457200, 274638, 8229600, 1143000), '<p:txBody><a:bodyPr anchor="ctr"/><a:p/></p:txBody>')}
    ${sp('Text Placeholder', ph('body', '1'), xfrm(457200, 1600200, 8229600, 4525963), '<p:txBody><a:bodyPr/><a:p/></p:txBody>')}
    <p:pic><p:nvPicPr><p:cNvPr id="9" name="로고"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/></p:blipFill><p:spPr>${xfrm(8000000, 6200000, 900000, 500000)}</p:spPr></p:pic>
    </p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1"/>
    <p:txStyles><p:titleStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="4400"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:defRPr></a:lvl1pPr></p:titleStyle>
    <p:bodyStyle><a:lvl1pPr marL="342900" indent="-342900"><a:buChar char="•"/><a:defRPr sz="3200"/></a:lvl1pPr><a:lvl2pPr marL="742950" indent="-285750"><a:buChar char="–"/><a:defRPr sz="2800"/></a:lvl2pPr></p:bodyStyle>
    <p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>`);
  zip.file('ppt/slideMasters/_rels/slideMaster1.xml.rels', rels([['rId1', 'theme', '../theme/theme1.xml'], ['rId2', 'image', '../media/logo.png']]));
  zip.file('ppt/slideLayouts/slideLayout1.xml', `<p:sldLayout ${P}><p:cSld name="제목 및 내용"><p:spTree>
    ${sp('Title 1', ph('title'), '', '<p:txBody><a:bodyPr/><a:p/></p:txBody>')}
    ${sp('Content 2', ph(null, '1'), xfrm(457200, 1700000, 8229600, 4400000), '<p:txBody><a:bodyPr/><a:p/></p:txBody>')}
    </p:spTree></p:cSld></p:sldLayout>`);
  zip.file('ppt/slideLayouts/_rels/slideLayout1.xml.rels', rels([['rId1', 'slideMaster', '../slideMasters/slideMaster1.xml']]));
  zip.file('ppt/slides/slide1.xml', `<p:sld ${P}><p:cSld><p:spTree>
    ${sp('Title 1', ph('title'), '', `<p:txBody><a:bodyPr/>${para('설비 점검 결과')}</p:txBody>`)}
    ${sp('Content 2', ph(null, '1'), '', `<p:txBody><a:bodyPr/>${para('점검 항목')}${para('진동', 1)}${para('소음', 1)}</p:txBody>`)}
    ${sp('TextBox 3', '<p:nvPr/>', `${xfrm(500000, 6000000, 3000000, 400000)}<a:noFill/>`, `<p:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="1400" b="1"><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:rPr><a:t>주의: −70℃ 이하</a:t></a:r><a:r><a:rPr sz="1400" baseline="30000"/><a:t>2</a:t></a:r></a:p></p:txBody>`)}
    <p:grpSp><p:nvGrpSpPr><p:cNvPr id="4" name="그룹"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="1000000" y="1000000"/><a:ext cx="2000000" cy="1000000"/><a:chOff x="0" y="0"/><a:chExt cx="1000000" cy="500000"/></a:xfrm></p:grpSpPr>
      ${sp('그룹 안 상자', '<p:nvPr/>', `${xfrm(500000, 250000, 500000, 250000)}<a:solidFill><a:schemeClr val="accent1"><a:lumMod val="50000"/></a:schemeClr></a:solidFill>`, `<p:txBody><a:bodyPr/>${para('그룹 글자')}</p:txBody>`)}</p:grpSp>
    <p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="표"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="500000" y="3000000"/><a:ext cx="4000000" cy="800000"/></p:xfrm>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblGrid><a:gridCol w="2000000"/><a:gridCol w="2000000"/></a:tblGrid>
      <a:tr h="400000"><a:tc gridSpan="2"><a:txBody><a:bodyPr/>${para('병합 머리글')}</a:txBody></a:tc><a:tc hMerge="1"><a:txBody><a:bodyPr/><a:p/></a:txBody></a:tc></a:tr>
      <a:tr h="400000"><a:tc><a:txBody><a:bodyPr/>${para('온도')}</a:txBody></a:tc><a:tc><a:txBody><a:bodyPr/>${para('−72℃')}</a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>
    <p:pic><p:nvPicPr><p:cNvPr id="6" name="현장 사진"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:srcRect l="10000" r="10000"/></p:blipFill><p:spPr>${xfrm(5000000, 3000000, 2000000, 1500000)}</p:spPr></p:pic>
    <p:pic><p:nvPicPr><p:cNvPr id="7" name="도면"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId5"/></p:blipFill><p:spPr>${xfrm(7000000, 1000000, 1000000, 1000000)}</p:spPr></p:pic>
    <p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="8" name="차트"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="5000000" y="4600000"/><a:ext cx="3000000" cy="1200000"/></p:xfrm>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="rId4"/></a:graphicData></a:graphic></p:graphicFrame>
    </p:spTree></p:cSld></p:sld>`);
  zip.file('ppt/slides/_rels/slide1.xml.rels', rels([['rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml'], ['rId2', 'image', '../media/photo.png'],
    ['rId3', 'notesSlide', '../notesSlides/notesSlide1.xml'], ['rId4', 'chart', '../charts/chart1.xml'], ['rId5', 'image', '../media/drawing.emf']]));
  zip.file('ppt/notesSlides/notesSlide1.xml', `<p:notes ${P}><p:cSld><p:spTree>${sp('Notes', ph('body', '1'), '', `<p:txBody><a:bodyPr/>${para('발표 메모: 재점검 일정 공유')}</p:txBody>`)}</p:spTree></p:cSld></p:notes>`);
  zip.file('ppt/charts/chart1.xml', `<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>월별 온도</a:t></a:r></a:p></c:rich></c:tx></c:title></c:chart></c:chartSpace>`);
  zip.file('ppt/slides/slide2.xml', `<p:sld ${P} show="0"><p:cSld><p:spTree>${sp('Title 1', ph('title'), '', `<p:txBody><a:bodyPr/>${para('숨긴 부록')}</p:txBody>`)}</p:spTree></p:cSld></p:sld>`);
  zip.file('ppt/slides/_rels/slide2.xml.rels', rels([['rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml']]));
  zip.file('ppt/media/logo.png', PNG);
  zip.file('ppt/media/photo.png', PNG);
  zip.file('ppt/media/drawing.emf', new Uint8Array([1, 0, 0, 0]));
  return zip.generateAsync({ type: 'arraybuffer' });
}

const fakeUrl = (_: Uint8Array, mime: string) => `blob:test/${mime}`;
const named = (shapes: Shape[], name: string) => shapes.find(shape => shape.name === name)!;

afterEach(cleanup);

describe('PPTX 원본 모델', () => {
  it('슬라이드 크기·순서·숨김과 자리표시자 상속을 읽는다', async () => {
    const deck = await readPptx(await samplePptx(), fakeUrl);
    expect([deck.width, deck.height, deck.slides.length]).toEqual([9144000, 6858000, 2]);
    expect(deck.slides.map(slide => [slide.number, slide.hidden, slide.layout])).toEqual([[1, false, '제목 및 내용'], [2, true, '제목 및 내용']]);
    const [slide] = deck.slides;
    expect(slide.background).toBe('#f0f0f0'); // 슬라이드·레이아웃에 없으면 마스터 배경
    const title = named(slide.shapes, 'Title 1');
    expect(title.kind === 'shape' && [title.box.x, title.box.y, title.box.w]).toEqual([457200, 274638, 8229600]); // 위치는 마스터에서
    expect(title.kind === 'shape' && title.text && [title.text.anchor, title.text.paras[0].align, title.text.paras[0].runs[0].size, title.text.paras[0].runs[0].color])
      .toEqual(['middle', 'center', 44, '#000000']);
    const body = named(slide.shapes, 'Content 2');
    expect(body.kind === 'shape' && body.box.y).toBe(1700000); // 레이아웃이 마스터보다 가깝다
    expect(body.kind === 'shape' && body.text?.paras.map(p => [p.level, p.bullet, p.runs[0].size, p.marginLeft])).toEqual([
      [0, '•', 32, 342900], [1, '–', 28, 742950], [1, '–', 28, 742950]]);
    expect(slide.notes).toBe('발표 메모: 재점검 일정 공유');
  });

  it('글자 꾸밈·그룹 좌표·테마 색·표 병합·그림·차트 자리를 읽는다', async () => {
    const [slide] = (await readPptx(await samplePptx(), fakeUrl)).slides;
    const note = named(slide.shapes, 'TextBox 3');
    const runs = note.kind === 'shape' ? note.text!.paras[0].runs : [];
    expect(runs.map(run => [run.text, run.size, run.bold, run.color, run.baseline])).toEqual([
      ['주의: −70℃ 이하', 14, true, '#ff0000', undefined], ['2', 14, undefined, '#000000', 30000]]);
    const inGroup = named(slide.shapes, '그룹 안 상자');
    expect(inGroup.kind === 'shape' && [inGroup.box.x, inGroup.box.y, inGroup.box.w, inGroup.box.h, inGroup.fill]).toEqual([2000000, 1500000, 1000000, 500000, '#254061']); // PowerPoint '강조 1, 50% 더 어둡게'와 같은 값
    const table = named(slide.shapes, '표');
    expect(table.kind === 'table' && table.rows.map(row => row.cells.map(cell => [cell.span, cell.hidden, cell.text.paras[0]?.runs[0]?.text ?? '']))).toEqual([
      [[2, false, '병합 머리글'], [1, true, '']], [[1, false, '온도'], [1, false, '−72℃']]]);
    const photo = named(slide.shapes, '현장 사진');
    expect(photo.kind === 'picture' && [photo.src, photo.crop]).toEqual(['blob:test/image/png', [0.1, 0, 0.1, 0]]);
    const drawing = named(slide.shapes, '도면');
    expect(drawing.kind === 'picture' && drawing.unsupported).toBe('EMF 그림(브라우저 표시 불가)');
    const chart = named(slide.shapes, '차트');
    expect(chart.kind === 'placeholder' && [chart.label, chart.texts]).toEqual(['차트', ['월별 온도']]);
    expect(named(slide.shapes, '로고').kind).toBe('picture'); // 마스터의 장식 그림은 그린다
    expect(slide.shapes.some(shape => shape.name === 'Text Placeholder')).toBe(false); // 마스터의 빈 자리표시자는 그리지 않는다
  });

  it('PowerPoint 파일이 아니면 알린다', async () => {
    const zip = new JSZip();
    zip.file('word/document.xml', '<w:document/>');
    await expect(readPptx(await zip.generateAsync({ type: 'arraybuffer' }), fakeUrl)).rejects.toThrow('ppt/presentation.xml');
  });

  it('화면에 슬라이드·숨김·메모·글자를 보인다', async () => {
    render(<OfficeSource kind="pptx" data={await samplePptx()} expanded={false} />);
    expect(await screen.findByText('슬라이드 2장 · 숨긴 슬라이드 1장')).toBeTruthy();
    expect(screen.getByText('설비 점검 결과')).toBeTruthy();
    expect(screen.getByText('숨긴 슬라이드')).toBeTruthy();
    expect(screen.getByText('발표 메모: 재점검 일정 공유')).toBeTruthy();
    expect(screen.getByText('차트 · 그리지 않음')).toBeTruthy();
    expect(screen.getByText(/브라우저에서 다시 그린 원본입니다/)).toBeTruthy();
  });
});

describe('DOCX 원본', () => {
  it('본문을 그리고 javascript: 링크는 열 수 없게 만든다', async () => {
    const zip = new JSZip();
    const W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
    zip.file('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
    zip.file('_rels/.rels', rels([['rId1', 'officeDocument', 'word/document.xml']]));
    zip.file('word/document.xml', `<w:document ${W}><w:body><w:p><w:r><w:t>보관 온도 ≤ −70℃</w:t></w:r></w:p>
      <w:p><w:hyperlink r:id="rId1"><w:r><w:t>위험 링크</w:t></w:r></w:hyperlink><w:hyperlink r:id="rId2"><w:r><w:t>규정 사이트</w:t></w:r></w:hyperlink></w:p>
      <w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>`);
    zip.file('word/_rels/document.xml.rels', `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="${R}/hyperlink" Target="javascript:alert(1)" TargetMode="External"/>
      <Relationship Id="rId2" Type="${R}/hyperlink" Target="https://example.com/sop" TargetMode="External"/></Relationships>`);
    render(<OfficeSource kind="docx" data={await zip.generateAsync({ type: 'arraybuffer' })} expanded={false} />);
    expect(await screen.findByText('보관 온도 ≤ −70℃', {}, { timeout: 4000 })).toBeTruthy();
    await waitFor(() => expect(screen.getByText('위험 링크').closest('a')?.hasAttribute('href')).toBe(false));
    const safe = screen.getByText('규정 사이트').closest('a')!;
    expect([safe.getAttribute('href'), safe.getAttribute('target'), safe.getAttribute('rel')]).toEqual(['https://example.com/sop', '_blank', 'noopener noreferrer']);
    expect(document.querySelector('iframe')).toBeNull();
  });
});

describe('PPTX 숫자 속성 기본값', () => {
  it('글자 자동 맞춤에 비율이 없으면 100%로 본다', async () => {
    const zip = await JSZip.loadAsync(await samplePptx());
    const slide = (await zip.file('ppt/slides/slide1.xml')!.async('string')).replace('<a:bodyPr/><a:p><a:r><a:rPr sz="1400" b="1">', '<a:bodyPr><a:normAutofit/></a:bodyPr><a:p><a:r><a:rPr sz="1400" b="1">');
    zip.file('ppt/slides/slide1.xml', slide);
    const deck = await readPptx(await zip.generateAsync({ type: 'arraybuffer' }), fakeUrl);
    const note = named(deck.slides[0].shapes, 'TextBox 3');
    expect(note.kind === 'shape' && note.text!.paras[0].runs[0].size).toBe(14);
  });
});
