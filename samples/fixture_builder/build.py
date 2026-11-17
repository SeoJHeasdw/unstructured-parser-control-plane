"""Generate, verify, and package the three synthetic-corpus phases."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
import zipfile

from core import *
from packages import build_pkgs, build_pdf_variants, build_scan_assets
from questions import build_questions
from reports import build_edge_words, build_reports, certificates
from sheets import build_sheets
from slides import build_slides
from sop import build_sops
from verify_corpus import verify
from visuals import build_visuals, VISUAL_TEXT


def qualify_truth(assets):
    for file_id, entry in MANIFEST.items():
        path=file_path(file_id)
        payload=path.read_bytes()
        entry['bytes']=len(payload)
        entry['sha256']=digest(payload)
        gold=GOLD[file_id]
        stored_values=[entry['value'] for entry in gold['key_values']]
        stored_values.extend(gold['text_snippets'])
        stored_values.extend(caption['text'] for caption in gold['captions'])
        stored_values.extend(value for table in gold['tables'] for row in table['rows'] for value in row)
        gold['numbers_with_units']=numbers(stored_values)
        if str(path) in VISUAL_TEXT:
            gold['visible_image_text']=VISUAL_TEXT[str(path)]
        if not entry['elements'] and gold['tables']:
            entry['elements']={'tables':len(gold['tables'])}

    extra_visuals={
        'SOP-A3':VISUAL_TEXT[str(assets['swab'])],
        'SOP-C1':VISUAL_TEXT[str(assets['chromatogram'])],
        'RPT-2':VISUAL_TEXT[str(assets['fishbone'])],
        'RPT-1P':VISUAL_TEXT[str(assets['stamp'])],
        'PPT-1':VISUAL_TEXT[str(WORK/'slides-field.png')],
    }
    QUESTIONS.sort(key=lambda q:q['phase'])
    for i,q in enumerate(QUESTIONS,1):
        q['id']=f'q-{i:03d}'
        if q['requires_ocr']:
            fid=q['doc_file_id']
            gold=GOLD[fid]
            visible=extra_visuals.get(fid,[]) + gold.get('visible_image_text',[])
            visible += [v['value'] for v in gold['key_values']]
            visible += gold['text_snippets']
            visible += [v for table in gold['tables'] for row in table['rows'] for v in row]
            assert any(q['answer'] in text for text in visible),(fid,q['answer'])
            evidence(fid,visual_evidence=[dict(question_id=q['id'],text=q['answer'],location=q['location'])])


def truth_at(phase):
    records=[deepcopy(m) for m in MANIFEST.values() if int(m['priority'][1])+1<=phase]
    records.sort(key=lambda m:(m['priority'],m['path']))
    ids={m['file_id'] for m in records}
    refs=[]
    for m in records:
        if m['pair_with'] not in ids:
            m['pair_with']=None
        for link in m['links']:
            expected=link['expected_target_file_ids']
            link['expected_target_file_ids']=[target for target in expected if target in ids]
            if expected and not link['expected_target_file_ids']:
                link['expected_state']='missing'
            if link['latest_file_id'] not in ids:
                link['latest_file_id']=None
            refs.append(dict(source_file_id=m['file_id'],location=link['location'],written_as=link['target'],
                             kind=link['kind'],expected_state=link['expected_state'],
                             expected_target_file_ids=link['expected_target_file_ids'],latest_file_id=link['latest_file_id']))
    questions=[{k:v for k,v in q.items() if k!='phase'} for q in QUESTIONS if q['phase']<=phase]
    return records,refs,questions


def make_truth_dir(phase, stage):
    truth=stage/'ground_truth'
    (truth/'gold').mkdir(parents=True,exist_ok=True)
    records,refs,questions=truth_at(phase)
    for m in records:
        file_id=m['file_id']
        source=file_path(file_id)
        target=stage/'corpus'/m['path']
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            target.hardlink_to(source)
        (truth/'gold'/f'{file_id}.json').write_text(dump(GOLD[file_id]),encoding='utf-8')
    (truth/'manifest.json').write_text(dump(records),encoding='utf-8')
    (truth/'references.json').write_text(dump(refs),encoding='utf-8')
    (truth/'questions.jsonl').write_text(
        ''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in questions),encoding='utf-8')
    return records


def log_for(phase, reports, records):
    counts=Counter(r['priority'] for r in records)
    lines=[
        '# Fabrikam Bio 합성 검증 코퍼스 생성 기록',
        '',
        f'- 누적 단계: {phase}/3',
        '- 배포 기준: 단계별 신규 원본과 누적 정답. 통합 검증은 단계 번호 순으로 같은 곳에 푼 뒤 실행한다.',
        '- 파일 수: '+', '.join(f'{key} {value}개' for key,value in sorted(counts.items())),
        '- 자료 범위: 합성 문서, 가상 설비 사진, 배열·문서 구조의 검증 데이터.',
        '',
        '## 구현 상세 및 적용한 예외',
        '',
        '- macOS의 Apple SD Gothic Neo 글꼴을 fc-list로 확인했다. PDF 한글은 Core Text로 렌더링했다.',
        '- LibreOffice CLI 변환이 종료 코드 1을 반환했고 이 환경에서 ReportLab·pypdf·matplotlib 설치가 제한되었다. 디지털 PDF는 공유 페이지 모델에 Swift/Core Graphics, 페이지·텍스트·회전·첨부에는 PDFium, 차트와 스캔 그래픽에는 Pillow와 NumPy를 사용했다.',
        '- Word·디지털 PDF 비교본은 동일한 본문·표·그림 데이터로 생성했다. Word는 페이지 나눔과 표 머리글 반복을 포함하며 Word 렌더러의 실제 줄바꿈은 앱·설치 글꼴에 따라 달라질 수 있다. DOCX 페이지 수는 패키지에 설정한 페이지 수와 나눔 구조로 검사했다.',
        '- COA 스캔은 보안 표시를 포함한 원본 페이지를 200 dpi로 이미지화하고 2쪽에 손글씨 재확인을 추가했다. 200 dpi 외부 교정 스캔과 TIFF에는 가벼운 기울기와 노이즈를 적용했다.',
        '- 사진에는 이미지 생성으로 만든 무문자 가상 설비를 사용했다. 가상 고지 문구는 텍스트형 문서와 코드 렌더링한 양식에 넣었다. 설비 원본 JPG, 순수 사진 PDF, 빈·손상 파일은 형식 목적상 본문 고지를 생략했다.',
        '- CSV의 헤더와 행 수를 고정하기 위해 가상 고지를 첫 데이터 행의 메모성 필드에 넣었다. 0바이트 TXT는 지시된 대로 빈 파일이다.',
        '- 문서별 비교는 기본 텍스트/수치 보존을 기준으로 했다. Rev.2 교정 SOP 충돌은 같은 개정번호와 개정 이력 아래 시행일·저울 주기가 의도적으로 다르다. 카탈로그에 명시된 구판 교정 SOP의 2023년 발행일을 그대로 사용했다.',
        '- 참조 상태는 해당 단계까지 파일을 합친 결과를 기준으로 한다. 예를 들어 1단계의 CAPA 참조는 누락, 2단계부터는 연결로 기록한다. 근거가 같은 복제본/내보내기는 동일 문서 가족으로 유지한다.',
        '- OCR이 필요한 질문은 생성에 사용한 시각 요소의 문자와 위치를 정답에 기록했다. 독립 OCR 출력의 정답 일치 여부는 검증 항목에서 제외했다.',
    ]
    if phase>=3:
        lines.extend([
            '- 선택 항목 XLS-5(XLSM)는 동작이 검증된 VBA 프로젝트를 확보하지 못해 생략했다.',
            '- 선택 항목 HWPX는 Hancom Office에서 OWPML 패키지를 열어 확인할 환경이 없어 생략했다.',
        ])
    lines.extend(['', '## 단계별 재열기 검증 결과',''])
    for number, entries in enumerate(reports,1):
        lines.append(f'### 단계 {number}')
        lines.extend(f'- {value}' for value in entries)
        lines.append('')
    lines.extend([
        '## 검증 실행',
        '',
        '문서 검증에 쓰는 Python 패키지는 python-docx, openpyxl, python-pptx, Pillow, lxml, pypdfium2이다.',
        '',
        '    python verify_corpus.py .',
        '',
        '암호 PDF 열기 암호는 fabrikam-test이다.',
        '',
    ])
    return '\n'.join(lines)


def package():
    reports=[]
    verifier=Path(__file__).with_name('verify_corpus.py')
    for phase in [1,2,3]:
        stage=ROOT/f'phase-{phase}'
        if stage.exists():
            shutil.rmtree(stage)
        records=make_truth_dir(phase,stage)
        lines=verify(stage)
        reports.append(lines)
        log=log_for(phase,reports,records)
        (stage/'generation_log.md').write_text(log,encoding='utf-8')
        shutil.copyfile(verifier,stage/'verify_corpus.py')
        target=OUTPUT/f'corpus_phase{phase}.zip'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for record in records:
                if record['priority']==f'P{phase-1}':
                    path=record['path']
                    archive.write(stage/'corpus'/path,'corpus/'+path)
            for source in sorted((stage/'ground_truth').rglob('*')):
                if source.is_file():
                    archive.write(source,source.relative_to(stage).as_posix())
            for relative in ['generation_log.md','verify_corpus.py']:
                archive.write(stage/relative,relative)
        with zipfile.ZipFile(target) as proof:
            assert proof.testzip() is None
            expected={f'corpus/{r["path"]}' for r in records if r['priority']==f'P{phase-1}'}
            assert {p for p in proof.namelist() if p.startswith('corpus/')}==expected
        print(f'Phase {phase}: {target} / {target.stat().st_size:,} bytes',flush=True)
        print('\n'.join(lines),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--photo-grid',type=Path,required=True)
    args=parser.parse_args()
    assets=build_visuals(args.photo_grid)
    build_sops(assets)
    build_reports(assets)
    certificates(assets)
    build_edge_words(assets)
    build_sheets()
    build_slides(assets)
    pdfs=render_digital_pdfs()
    temp=build_pdf_variants(pdfs,assets)
    build_pkgs(assets,temp)
    build_scan_assets()
    build_questions()
    qualify_truth(assets)
    package()


if __name__=='__main__':
    main()
