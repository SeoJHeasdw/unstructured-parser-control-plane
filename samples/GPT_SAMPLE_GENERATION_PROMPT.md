# Synthetic Test Corpus for an Unstructured-Document Console — Generation Brief

You are going to build a **synthetic test corpus** of enterprise documents (Korean-language, biopharmaceutical manufacturing / quality domain) together with **machine-readable ground truth**. The corpus will be uploaded into a document-processing console that we are developing, so that we can measure and visualise how well it handles messy, real-world, unstructured files.

Read this whole brief before producing anything. Then work in the phases described in §10, delivering a ZIP after each phase.

---

## 0. TL;DR

- Produce ~60 files across DOCX, PDF (digital, scanned, mixed, with attachments, encrypted), XLSX/CSV, PPTX, EML, ZIP, PNG/JPG/TIFF, plus a few deliberately broken edge cases.
- All content is **fictional**. Company: **Fabrikam Bio (가상의 회사)**. No real companies, people, products, addresses, phone numbers, regulators' document IDs, or brand names.
- Documents are mostly **Korean**, with natural English mixed in (units, instrument names, abbreviations), the way Korean GMP documents really look.
- Every file has an entry in `ground_truth/manifest.json`, and the corpus ships with `ground_truth/questions.jsonl`, `ground_truth/references.json`, and per-file `ground_truth/gold/<file_id>.json`.
- Use **code** (Python) to build documents and any image that contains text. Use **image generation** only for photorealistic visuals **without legible text** (equipment, pipes, gauges without numbers, lab benches), then place them into documents with captions.
- Verify everything you produce by re-opening it programmatically (§9).

---

## 1. What the console does (so you know what to stress)

The console under test has these capabilities. Each file you create should exercise one or more of them; the manifest records which (`purposes`).

| Capability | What it does | What the corpus must contain |
|---|---|---|
| `parse` | Converts PDF/DOCX/PPTX/XLSX/TXT/CSV/MD into Markdown (Docling-style). OCR is **off** by default. | Real text, headings, lists, tables (simple, merged cells, long, wide, spanning pages), figures with captions, headers/footers, footnotes, two-column layouts, text boxes. |
| `ocr` | (Future) OCR for scanned pages. | Image-only PDFs, mixed PDFs (some pages scanned), photos of paper, TIFF, rotated/skewed/noisy pages, stamps, handwriting marks. |
| `compare` | Shows two parses of the same content side by side. | The **same content** in two forms: DOCX ↔ digital PDF, digital PDF ↔ scanned PDF. Numbers, units, document numbers must be identical across the pair. |
| `structure` | Opens files and finds **documents inside documents** and **links**: ZIP entries (nested), e-mail attachments (nested e-mails), PDF file attachments, Office embedded objects, hyperlinks, external workbook references in XLSX formulas, shared-folder paths (`\\server\share\...`), document numbers in text; flags encryption, extension mismatch, macros. | ZIPs (nested, with CP949 file names), EMLs with attachments and attached EMLs, PDFs with embedded file attachments, XLSX with hyperlinks + external references, DOCX/PPTX with hyperlinks to other files, an encrypted PDF, a file whose extension lies, (optional) a macro workbook. |
| `lineage` | Groups files into **document families** (same document across revisions/copies), decides which one is **latest** (or puts the decision **on hold** when evidence conflicts), and resolves references between documents into states: `linked`, `outdated` (points to an old revision), `missing` (target not in corpus), `ambiguous` (several candidates), `external` (URL). | Revision families with realistic file-name chaos (`Rev.3`, `_v2`, `(최종)`, `최종_수정`, `복사본 - `), an exact duplicate, a family with conflicting "latest" evidence, and references of every state. |
| `chunking` | Splits parsed Markdown into chunks with element awareness: prose, lists, tables, images, captions, repeated headers/footers. | Long tables (20+ rows) that cross page boundaries with repeated header rows, wide tables (8–40 columns), figures with captions ("그림 N. …", "표 N. …"), pages with repeated running headers and page numbers, an image with no caption, a page that is only a scan. |
| `embedding_eval` | Measures retrieval accuracy of embedding models by question type: **text**, **table**, **image** (answer lives in an image caption / visible image text). | `questions.jsonl` whose answers appear **verbatim** in the documents (see §7). |
| `vectordb` | Browses stored chunks by collection/partition/document. | Nothing special — just enough distinct documents (≥ 40) across a few departments (QC, QA, 설비/Engineering, 생산/Manufacturing) to make partitions meaningful. |

---

## 2. Global rules

### 2.1 Fictional universe (use consistently everywhere)

- Company: **Fabrikam Bio (가상)**, plant names: **제1공장 (Plant 1)**, **제2공장 (Plant 2)**. File server: `\\fabrikam-fs01\qa\...`, `\\fabrikam-fs01\eng\...`. E-mail domain: `@fabrikam.example`. Intranet URL: `https://intranet.fabrikam.example/...`.
- Product: **FBX-101** (가상 단일클론항체, fictional monoclonal antibody). Lots: `2026A031`, `2026A032`, `2026B007`.
- People: use roles plus masked fictional names only: `QC 시험담당 김O준`, `QA 승인 이O희`, `설비팀 박O수`. Never full real-looking names, never real titles of real people.
- Phone numbers: `02-000-0000` style only. No real addresses (use `가상시 가상구 1번지`).
- Equipment IDs: `EQ-COOL-02` (냉각수 순환설비), `EQ-HPLC-07`, `EQ-FRZ-D` (냉동고 D), `EQ-UF-03` (초저온 냉동고), `EQ-INC-H` (항온 배양기), `EQ-PUMP-P1`, `EQ-PUMP-P2`.
- Document number patterns: `SOP-QC-0040`, `SOP-QC-0012`, `SOP-QC-014`, `SOP-EQ-0101`, `RPT-EQ-2026-031`, `DEV-2026-0117`, `CAPA-2026-0042`, `COA-FBX101-2026A031`, `WI-QC-052`. Revisions: `Rev.1`…`Rev.5`, sometimes `v2`, `v3`.
- Dates in 2024–2026, formats mixed realistically: `2026-02-14`, `2026.02.14`, `2026년 2월 14일`.
- Every document's first page (or first sheet/slide) carries a small notice: `본 문서는 시험용으로 만든 가상 문서이며 실제 조직·제품·인물과 관계가 없습니다.`

### 2.2 Language and realism

- Body text in natural, formal Korean as used in GMP SOPs/reports ("~한다", "~할 것", numbered clauses 1., 1.1, 1.1.1). Mix in English terms naturally: HPLC, UV, pH, CIP/SIP, TOC, OOS, CAPA, LOD/LOQ, %RSD.
- Use real units and number formats: `°C`, `%RH`, `mL`, `mg/mL`, `µS/cm`, `ppm`, `CFU/mL`, `bar`, `mm/s`, `rpm`, `±0.5 °C`, `≤ 10 ppm`, `1.2E+03`, thousands separators `1,250`.
- Main documents must be **dense enough to chunk**: ≥ 1,500 Korean characters of body text, typically 3–15 pages. Avoid filler; write plausible procedure steps, findings, rationales.
- Keep facts **consistent** across all forms of the same document (DOCX vs PDF vs scan vs e-mail attachment) and across references (if a report says the limit is `≤ 10 ppm per SOP-QC-0040 Rev.4`, then Rev.4 must actually say 10 ppm and Rev.5 must say something else).

### 2.3 Fonts (important — check first)

Before generating any PDF or text-bearing image, run `fc-list :lang=ko` (or check `matplotlib.font_manager`) for a Korean-capable font (Noto Sans KR / Noto Sans CJK / NanumGothic / Malgun Gothic). If none exists, **stop and ask me to upload a Korean `.ttf`/`.otf`**; do not produce PDFs or images with Korean text rendered as empty boxes (tofu). Use one sans font for body and optionally one serif/handwriting-like font for "handwritten" marks.

### 2.4 Image generation vs. code

- **Image generation** (photoreal or illustration) is for: equipment photos (pumps, heat exchanger, piping with corrosion, freezer interior with racks, HPLC instrument on a bench, control cabinet exterior), a lab bench with sample vials, a cleanroom corridor, swab sampling on stainless steel. Prompt for **no visible text, no logos, no brand names**; blank labels or out-of-focus labels are fine.
- **Code** (Pillow/matplotlib/reportlab) is for anything with readable text or numbers: charts, P&ID-style diagrams, flowcharts, fishbone diagrams, equipment nameplates, gauge dials with numbers, scanned forms, handwriting marks, stamps (`승인`, `QA 확인` in a red circle), signature scribbles.
- To make a **"photo of paper"**: render the page with code → apply perspective warp, slight rotation (1–4°), uneven lighting gradient, blur, JPEG artifacts, paper texture/noise, a coffee-ring stain, a shadow at one edge.
- To make a **scan**: render at 200–300 dpi grayscale → slight skew (0.5–2°), salt-and-pepper noise, faint bleed-through, optional one page rotated 90°, then embed as image-only PDF pages (no text layer).

### 2.5 Libraries (Python)

`python-docx`, `openpyxl`, `python-pptx`, `reportlab` (or `fpdf2`) with a registered Korean TTF, `pypdf` (attachments, encryption, merging), `Pillow`, `numpy`, `matplotlib`, stdlib `email`, `zipfile`, `csv`, `json`. If a library is missing, use an alternative and note it in `generation_log.md`.

---

## 3. Output layout

```
corpus/
  01_sop/              procedures (DOCX + PDF exports), revision families
  02_reports/          inspection, deviation, CAPA reports (photo-heavy, mixed PDFs, PDFs with attachments)
  03_certificates/     certificates of analysis, test result sheets (table-heavy), digital vs scanned pairs
  04_spreadsheets/     XLSX / CSV logs, master lists, external references
  05_presentations/    PPTX
  06_mail/             EML (attachments, attached e-mails)
  07_archives/         ZIP (nested, CP949 names)
  08_scans/            image-only PDFs, TIFF, photos of documents
  09_images/           standalone images (photos, diagrams, charts, nameplates)
  10_edge_cases/       encrypted, wrong extension, empty, truncated, huge, two-column
ground_truth/
  manifest.json
  references.json
  questions.jsonl
  gold/<file_id>.json
generation_log.md
```

File names are part of the test: keep Korean names, spaces, parentheses and version markers exactly as specified. Each file has a stable `file_id` (e.g. `SOP-A3`) used in ground truth.

---

## 4. File catalogue

Priority: **P0** = must have (phase 1), **P1** = phase 2, **P2** = phase 3 / best effort.
Page counts are targets (±2). "Elements" lists what must be present so that chunking and parsing can be measured.

### 4.1 `01_sop/` — Family A: 세척 밸리데이션 절차 (cleaning validation), revisions and copies

| file_id | P | File name | Notes |
|---|---|---|---|
| SOP-A1 | P0 | `SOP-QC-0040_세척밸리데이션_Rev.3.docx` | Issued 2024-03-11. 6 pages. |
| SOP-A2 | P0 | `SOP-QC-0040_세척밸리데이션_Rev.4.docx` | Issued 2025-01-20. Changes vs Rev.3: residue limit `≤ 20 ppm` → `≤ 10 ppm`; one sampling location added (row 21); revision history table gains a row. |
| SOP-A3 | P0 | `SOP-QC-0040 세척 밸리데이션 절차 Rev.5 (최종).docx` | Issued 2026-02-14. **Latest.** TOC limit changed to `≤ 500 ppb`; new section "7. 시각 검사 기준" with a photo figure; revision history updated. |
| SOP-A3P | P0 | `SOP-QC-0040_Rev5.pdf` | Digital PDF export of SOP-A3 (text layer, same content, same pagination as far as possible). Pair for `compare`. |
| SOP-A4 | P0 | `복사본 - SOP-QC-0040_세척밸리데이션_Rev.4.docx` | **Byte-identical copy** of SOP-A2 (copy the bytes; do not regenerate). |

Common structure for SOP-A1…A3 (adapt per revision):
- Running **header** on every page: `Fabrikam Bio | SOP-QC-0040 | Rev.N | 세척 밸리데이션 절차` and **footer**: `페이지 X / Y` + `대외비 · 가상 문서`. (These are the "repeated furniture" the chunker must strip.)
- Cover block: 문서번호, 개정번호, 시행일, 작성/검토/승인 roles (masked names), a 3×4 approval table.
- Sections: 1. 목적, 2. 적용 범위 (bulleted list), 3. 책임과 권한 (3.1, 3.2 subsections), 4. 용어 정의 (definition table: 용어 | 정의, 8 rows), 5. 허용 기준 (**table: 항목 | 기준 | 시험법 | 근거**, 6 rows, with units), 6. 절차 (numbered steps 6.1–6.6, each 3–6 sentences), 6.4 has **표 2. 스왑 채취 위치** — a **20-row table** (번호 | 설비 | 위치 | 재질 | 면적(cm²) | 비고) that **must break across a page** with the header row repeated on the next page, 7. 기록, 8. 참고 문서 (list with document numbers: `SOP-QC-0012 Rev.2`, `WI-QC-052`, `SOP-EQ-0101`), 9. 개정 이력 (table).
- **Figure**: `그림 1. 스왑 채취 위치 배치도` — a code-drawn top-view diagram of a tank and piping with numbered sampling points (labels in Korean). Caption below the figure.
- One **footnote** in section 5 explaining the ppm basis.
- One **hyperlink** in section 8 to `\\fabrikam-fs01\qa\SOP\SOP-QC-0012_Rev2.docx` and one to `https://intranet.fabrikam.example/sop/SOP-QC-0040`.

### 4.2 `01_sop/` — Family B: 시험기기 교정 (calibration) — conflicting "latest"

| file_id | P | File name | Notes |
|---|---|---|---|
| SOP-B1 | P0 | `SOP-QC-0012_시험기기_교정_Rev.2.docx` | Says Rev.2, 시행일 2025-06-10. Calibration interval `12개월`. |
| SOP-B2 | P0 | `SOP-QC-0012_시험기기교정_Rev2_수정.docx` | **Also says Rev.2**, 시행일 2025-06-12, interval `6개월` for balances only, otherwise same. Revision history does **not** mention this change. This family must end up "on hold" for latest. |
| SOP-B0 | P1 | `SOP-QC-0012_시험기기_교정_Rev.1.pdf` | Older revision, digital PDF, 2023-09-01. |

Each 4–6 pages; include an instrument calibration table (기기 | 관리번호 | 교정 주기 | 허용 오차 | 교정 기관) with 15 rows, and a list of forms.

### 4.3 `01_sop/` — others

| file_id | P | File name | Notes |
|---|---|---|---|
| SOP-C1 | P0 | `SOP-QC-014_HPLC_시스템적합성_v3.docx` | HPLC system suitability. Tables: system suitability criteria (theoretical plates ≥ 2000, tailing ≤ 2.0, %RSD ≤ 2.0 % for n=5), mobile phase preparation steps, a chromatogram figure (code-drawn with matplotlib: peaks, retention times labelled) with caption `그림 1. 표준액 크로마토그램 예시`. Mentions `EQ-HPLC-07`. |
| SOP-C2 | P1 | `WI-QC-052_pH미터_일상점검.docx` | Work instruction, 3 pages, checklist table with ☐ marks, references SOP-QC-0012 (no revision → resolves to family B, ambiguous latest). |
| SOP-C3 | P1 | `SOP-EQ-0102_냉동고_관리.docx` | Freezer management. **Two-column** layout section (use docx section columns) and a text box with a warning. Mentions `EQ-FRZ-D`, `EQ-UF-03`. |
| SOP-C4 | P2 | `문서번호없는_파일명_보관조건.docx` | File name has no document number, but the cover page says `SOP-QC-0040 Rev.2` (an old revision not otherwise in the corpus). Lineage must use content, not just the name. |

### 4.4 `02_reports/` — photo-heavy and mixed

| file_id | P | File name | Notes |
|---|---|---|---|
| RPT-1 | P0 | `RPT-EQ-2026-031_냉각수순환설비_정기점검보고서.docx` | 7–9 pages, **image-heavy**: 6 figures with captions — (1) photo: cooling water skid overview, (2) photo: pump P-2 close-up, (3) photo: corroded pipe joint, (4) code chart: vibration trend 2026-07…10 for P-1/P-2 with a 4.5 mm/s limit line, (5) code diagram: simplified P&ID of the loop with tags EQ-PUMP-P1/P2, HX-01, TK-01, (6) photo: control cabinet exterior (no readable text). One image **without caption** right after (7). Findings table (번호 | 점검 항목 | 측정값 | 기준 | 판정 | 조치), 12 rows, mixed 양호/주의/불량. References: `SOP-QC-0040 Rev.4` (→ outdated, because Rev.5 exists), `SOP-EQ-0101` (→ missing), `SOP-QC-014` (→ linked), hyperlink to `\\fabrikam-fs01\eng\equipment\EQ-COOL-02\점검이력.xlsx` (shared path, not in corpus). |
| RPT-1P | P0 | `RPT-EQ-2026-031_점검보고서_서명본.pdf` | **Mixed PDF**: pages 1–3 and 5–7 are digital (same content as RPT-1), **page 4 is a scanned image-only page**: a filled field-check form with handwritten check marks and a red `승인` stamp. A signature image on the last page. |
| RPT-2 | P0 | `DEV-2026-0117_일탈보고서_온도이탈.docx` | Deviation: freezer EQ-FRZ-D exceeded `-15 °C` for 47 minutes on 2026-10-03. Timeline table (시각 | 사건 | 담당), a code-drawn **fishbone diagram** (Korean labels: 인력/설비/방법/환경/자재/측정), root cause narrative, CAPA list referencing `CAPA-2026-0042`, impact assessment table listing affected lots `2026A031`, `2026A032`. |
| RPT-2P | P0 | `DEV-2026-0117_일탈보고서_첨부포함.pdf` | Digital PDF of RPT-2 **with embedded file attachments** (PDF file attachments, via `pypdf` `add_attachment`): `온도기록_원본_EQ-FRZ-D_2026-10-03.csv` (5-minute readings for that day) and `현장사진_냉동고D.jpg`. |
| RPT-3 | P1 | `CAPA-2026-0042_시정예방조치_계획.docx` | CAPA plan, 4 pages, action table with owners (roles), due dates, status; references DEV-2026-0117 (linked) and SOP-EQ-0102 (linked). |
| RPT-4 | P1 | `월간_품질동향_보고서_2026-10.pdf` | Digital PDF, 10 pages, **two-column layout** on pages 2–6 (reportlab frames), 4 charts (matplotlib), 3 tables, footnotes, a sidebar box. |

### 4.5 `03_certificates/` — table-heavy

| file_id | P | File name | Notes |
|---|---|---|---|
| COA-1 | P0 | `COA_FBX-101_Lot-2026A031.pdf` | Digital PDF, 3 pages. Header block (제품명, 로트, 제조일, 유효기한, 규격 문서 `SPEC-FBX101 Rev.2`). **Results table of 24 rows** (시험 항목 | 시험법 | 기준 | 결과 | 판정) spanning pages 1–2 **with the header row repeated** on page 2; include values like `pH 6.0 ± 0.3` / `6.1`, `단백질 함량 10.0 ± 0.5 mg/mL` / `10.2 mg/mL`, `순도(SEC) ≥ 95.0 %` / `98.7 %`, `엔도톡신 ≤ 0.5 EU/mg` / `< 0.1 EU/mg`, `생균수 ≤ 10 CFU/mL` / `0 CFU/mL`. A **9-column** raw-material table (원료명 | 공급처(가상) | 로트 | 입고일 | 유효기한 | 시험번호 | 결과 | 판정 | 비고). Signature block with QA stamp image. |
| COA-1S | P0 | `COA_FBX-101_Lot-2026A031_스캔.pdf` | **Scanned** version of COA-1 (image-only, no text layer), 3 pages, page 2 slightly skewed, faint noise, a handwritten note `재확인 완료 10/14` near one row. Pair for `compare`/`ocr`. |
| COA-2 | P1 | `시험성적서_원료검수_2026-10.xlsx` | Sheets: `요약` (merged title cells, 2-level merged headers, conditional formatting for 부적합), `원자료` (600 rows × 12 columns of test readings with dates, units, formulas computing mean/RSD), `기준` (**hidden sheet**), `차트` (a native Excel line chart). Cell comments on two outliers. Number formats (%, 0.00, dates). |
| COA-3 | P1 | `COA_FBX-101_Lot-2026A032.docx` | Same template as COA-1 but DOCX, different lot values; one result `부적합` (OOS) with a footnote. |

### 4.6 `04_spreadsheets/` — links, external references, logs

| file_id | P | File name | Notes |
|---|---|---|---|
| XLS-1 | P0 | `장비마스터_목록_2026.xlsx` | Sheet `장비` (60 rows: 장비번호, 장비명, 위치, 관리 SOP, 최근 교정일, 다음 교정일, 상태). Column "관리 SOP" contains **document numbers** (some with revision, e.g. `SOP-QC-0040 Rev.3` → outdated). Column "문서" contains **hyperlinks** to relative paths (`../01_sop/SOP-QC-014_HPLC_시스템적합성_v3.docx`), to the file server, and one https URL. Sheet `교정` uses **external workbook references** in formulas: `='[교정일정_2026.xlsx]일정'!C5` (target exists: XLS-2) and `='[구매요청_집계.xlsx]Sheet1'!B3` (target **not** in corpus → missing). Store cached values so the formulas display numbers. |
| XLS-2 | P0 | `교정일정_2026.xlsx` | Sheet `일정`: 12 months × 40 instruments calendar, merged month headers, colour fills. |
| XLS-3 | P0 | `온도기록_냉장고A_2026-10.csv` | UTF-8 **with BOM**, 5-minute readings for 31 days (8,928 rows): `일시,설정온도(°C),측정온도(°C),습도(%RH),경보`. Include one excursion window matching nothing (noise) and blank `경보` mostly. |
| XLS-3C | P1 | `온도기록_냉장고A_2026-10_cp949.csv` | Same data, **CP949** encoding, no BOM, first 2,000 rows only. |
| XLS-4 | P1 | `배치기록_요약_2026Q3.xlsx` | **Wide**: 40 columns × 300 rows, freeze panes at C3, grouped columns, two header rows, totals row with SUM formulas. |
| XLS-5 | P2 | `세척검증_스왑결과_집계.xlsm` | Only if you can produce a **valid** `.xlsm` containing a `vbaProject.bin` (e.g. a tiny macro that recalculates). If you cannot, skip it and record that in the log. |

### 4.7 `05_presentations/`

| file_id | P | File name | Notes |
|---|---|---|---|
| PPT-1 | P0 | `2026_Q3_품질지표_리뷰.pptx` | 12 slides: title; agenda (bullets); KPI slide with a **native PPTX table** (지표 | 목표 | Q2 | Q3 | 추세); a **native chart** (deviation counts by month); a slide whose table is **only a PNG screenshot** (render a table image with code) — tests OCR need; two photo slides with captions; a slide citing `DEV-2026-0117` and `CAPA-2026-0042` with a hyperlink to the intranet; a slide with **speaker notes** containing a fact that appears nowhere else (`다음 분기 목표 일탈 건수는 월 2건 이하`); closing slide. |
| PPT-2 | P1 | `설비교체_검토_v2.pptx` | 8 slides; options table (3 vendors, fictional names `벤더 A/B/C`), cost chart. |
| PPT-3 | P1 | `설비교체_검토_v3_최종.pptx` | v3 of PPT-2: different recommendation, updated cost numbers. Family with PPT-2 (latest = v3). |

### 4.8 `06_mail/` — e-mails

| file_id | P | File name | Notes |
|---|---|---|---|
| EML-1 | P0 | `FW_ 냉각수설비 점검결과 공유.eml` | `multipart/mixed` with `multipart/alternative` (text + HTML body; HTML contains a small table), Korean **RFC 2047**-encoded subject, From/To/Cc at `@fabrikam.example`, Date 2026-10-16. **Attachments**: RPT-1 (`.docx`) and XLS-1 (`.xlsx`) with Korean file names encoded per RFC 2231. Body mentions `RPT-EQ-2026-031`. |
| EML-2 | P0 | `RE_ 일탈 DEV-2026-0117 원인조사 요청.eml` | Reply thread (quoted text with `>`), and an **attached e-mail** (`message/rfc822`, the original request) which itself has an attachment `현장사진_모음.zip` (contains 3 JPGs). Three levels: eml → eml → zip → jpg. |
| EML-3 | P1 | `회의록_공유_2026-10-20.eml` | Plain text only, no attachments, contains a meeting summary with action items and document numbers (for text-only parsing). |

### 4.9 `07_archives/`

| file_id | P | File name | Notes |
|---|---|---|---|
| ZIP-1 | P0 | `점검자료_2026-10.zip` | Folder tree: `보고서/RPT-EQ-2026-031_…docx`, `사진/` (4 JPG), `기록/온도기록_…csv`, and a **nested** `사진원본.zip` containing 5 more JPGs. UTF-8 file names with the UTF-8 flag set. |
| ZIP-2 | P0 | `윈도우압축_cp949.zip` | 3 small files with Korean names encoded in **CP949 without the UTF-8 flag** (how Windows Explorer zips them). Contents: a short DOCX, a TXT, a PNG. |
| ZIP-3 | P1 | `감사대응_자료.zip` | Contains EML-2 (eml → eml → zip) plus COA-1S. Deep nesting test (zip → eml → eml → zip → jpg). |

### 4.10 `08_scans/`

| file_id | P | File name | Notes |
|---|---|---|---|
| SCN-1 | P0 | `스캔_교정성적서_2026-09.pdf` | 3 image-only pages: an external calibration certificate (fictional lab `가상교정연구소`), table of measured points vs reference, **page 3 rotated 90°**, coffee stain on page 1, handwritten tick marks. |
| SCN-2 | P0 | `현장일지_사진.jpg` | Photo-of-paper of a filled daily log sheet (form rendered by code, handwriting-like entries, perspective warp, shadow). Visible text includes `EQ-COOL-02` and `압력 2.6 bar`. |
| SCN-3 | P1 | `보관조건_점검표.tif` | **Multi-page TIFF** (3 pages), grayscale, checklist form. |
| SCN-4 | P1 | `설비명판_EQ-UF-03.png` | Equipment nameplate rendered by code: model `UF-700 (가상)`, serial `SN-2023-0417`, `-86 °C`, `220 V 60 Hz`, manufacturer `가상냉동(주)`, slight metallic texture and glare. |

### 4.11 `09_images/` — standalone

| file_id | P | File name | Notes |
|---|---|---|---|
| IMG-1 | P0 | `냉각수설비_전경.jpg` | Image-gen photo (no text). Reused in RPT-1. |
| IMG-2 | P0 | `펌프P2_근접.jpg` | Image-gen photo (no text). |
| IMG-3 | P0 | `배관_부식부위.jpg` | Image-gen photo (no text). |
| IMG-4 | P0 | `진동추이_2026Q3.png` | matplotlib chart, Korean axis labels, limit line. |
| IMG-5 | P0 | `냉각수계통_PID.png` | Code-drawn simplified P&ID with tag labels. |
| IMG-6 | P1 | `공정흐름도_FBX101.png` | Code-drawn process flow (세포배양 → 수확 → 정제 1·2 → 바이러스 불활화 → 여과 → 충전), Korean labels. |
| IMG-7 | P1 | `시료보관_냉동고_내부.jpg` | Image-gen photo of freezer racks with blank labels. |

### 4.12 `10_edge_cases/`

| file_id | P | File name | Notes |
|---|---|---|---|
| EDGE-1 | P0 | `암호설정_공급계약_요약.pdf` | Digital PDF **encrypted** with user password `fabrikam-test` (record it in the manifest). |
| EDGE-2 | P0 | `확장자불일치_보고서.docx` | Actually a **PDF** (copy RPT-1P bytes and rename). |
| EDGE-3 | P0 | `빈문서.docx` | Valid DOCX with no text. |
| EDGE-4 | P1 | `손상된파일_일부잘림.docx` | A valid DOCX truncated to 60 % of its bytes. |
| EDGE-5 | P1 | `대용량_교육자료_120쪽.pdf` | Digital PDF, 120 pages of varied text and 30 tables (performance). |
| EDGE-6 | P1 | `이미지만_있는_문서.pdf` | 2 pages, each a single photo, no text at all. |
| EDGE-7 | P2 | `0byte.txt` | Empty file. |
| EDGE-8 | P2 | `README_현장공유.md` | Markdown with a table, a code block, links to other corpus files by name. |
| EDGE-9 | P2 | `특수문자_파일명 #1 (복사) [최종]…v2.docx` | Short valid DOCX; tests odd file names. |

(Optional, P2) **HWPX**: only if you can produce a valid OWPML package that Hancom Office would open (`mimetype`, `Contents/section0.xml`, `Contents/header.xml`, `META-INF/…`). Otherwise skip and log it. Do **not** attempt binary `.hwp`.

---

## 5. Reference graph (must be realised in the files)

Record every reference in `ground_truth/references.json`. Required examples:

| Source (file_id, location) | Written as | Expected state | Why |
|---|---|---|---|
| RPT-1 §참고 | `SOP-QC-0040 Rev.4` | `outdated` | Rev.5 (SOP-A3) is latest |
| RPT-1 §참고 | `SOP-EQ-0101` | `missing` | not in corpus |
| RPT-1 §참고 | `SOP-QC-014` | `linked` | SOP-C1 |
| RPT-1 hyperlink | `\\fabrikam-fs01\eng\equipment\EQ-COOL-02\점검이력.xlsx` | `missing` (shared path) | not in corpus |
| SOP-A3 §8 | `SOP-QC-0012 Rev.2` | `ambiguous` | SOP-B1 and SOP-B2 both claim Rev.2 |
| SOP-C2 | `SOP-QC-0012` | `ambiguous` | family B latest is on hold |
| XLS-1 `교정` formula | `[교정일정_2026.xlsx]` | `linked` | XLS-2 |
| XLS-1 `교정` formula | `[구매요청_집계.xlsx]` | `missing` | not in corpus |
| XLS-1 `장비` row 7 | `SOP-QC-0040 Rev.3` | `outdated` | Rev.5 exists |
| PPT-1 slide 9 | `https://intranet.fabrikam.example/...` | `external` | URL |
| RPT-3 | `DEV-2026-0117` | `linked` | RPT-2 / RPT-2P family |
| SOP-C4 cover | `SOP-QC-0040 Rev.2` | `outdated` | content-only reference |

Add more as they arise naturally (≥ 25 references in total).

---

## 6. Ground truth formats

### 6.1 `ground_truth/manifest.json`

A JSON array, one object per file:

```json
{
  "file_id": "RPT-1P",
  "path": "02_reports/RPT-EQ-2026-031_점검보고서_서명본.pdf",
  "format": "pdf",
  "true_format": "pdf",
  "bytes": 1834221,
  "sha256": "…",
  "priority": "P0",
  "purposes": ["parse", "ocr", "compare", "chunking", "lineage"],
  "language": "ko",
  "department": "설비",
  "doc_number": "RPT-EQ-2026-031",
  "revision": null,
  "issued": "2026-10-15",
  "family_id": "RPT-EQ-2026-031",
  "is_latest_expected": true,
  "latest_status_expected": "single | confirmed | hold",
  "duplicate_of": null,
  "pages": 7,
  "scanned_pages": [4],
  "elements": { "headings": 14, "paragraphs": 38, "lists": 3, "tables": 2, "images": 7, "captions": 6, "uncaptioned_images": 1, "footnotes": 0, "repeated_header_lines": 7, "page_number_lines": 7 },
  "tables": [ { "id": "t1", "title": "표 1. 점검 결과", "rows": 12, "cols": 6, "spans_pages": false, "header_repeated": false, "merged_cells": false } ],
  "embedded_children": [ { "name": "…", "kind": "attachment | zip_entry | email_attachment | ole_object | pdf_attachment", "path_inside": "…", "true_format": "csv" } ],
  "links": [ { "kind": "hyperlink | external_workbook | shared_path | doc_number | url", "target": "…", "location": "p.6 §8", "expected_state": "linked | outdated | missing | ambiguous | external" } ],
  "flags": { "encrypted": false, "password": null, "extension_mismatch": false, "macro": false, "truncated": false, "empty": false },
  "pair_with": "RPT-1",
  "notes": "Page 4 is an image-only scan of the field form."
}
```

### 6.2 `ground_truth/gold/<file_id>.json`

Facts a correct parser must recover, for measuring extraction quality:

```json
{
  "file_id": "COA-1",
  "title": "시험성적서 FBX-101 Lot 2026A031",
  "key_values": [ { "label": "로트", "value": "2026A031", "page": 1 }, { "label": "유효기한", "value": "2028-03-31", "page": 1 } ],
  "tables": [ { "id": "t1", "caption": "표 1. 시험 결과", "header": ["시험 항목", "시험법", "기준", "결과", "판정"], "rows": [["pH", "USP <791>", "6.0 ± 0.3", "6.1", "적합"], ["…"]] } ],
  "captions": [ { "kind": "figure", "text": "그림 1. …", "page": 3 } ],
  "numbers_with_units": ["10.2 mg/mL", "98.7 %", "< 0.1 EU/mg"],
  "headings": ["1. 제품 정보", "2. 시험 결과", "3. 원료 정보", "4. 판정"],
  "text_snippets": ["본 로트는 규격에 적합함을 확인한다."]
}
```

Tables must be complete (every row and cell as displayed). For scans, gold is the **visible** content.

### 6.3 `ground_truth/references.json`

```json
[ { "source_file_id": "RPT-1", "location": "p.6 §8 참고 문서", "written_as": "SOP-QC-0040 Rev.4", "kind": "doc_number", "expected_state": "outdated", "expected_target_file_ids": ["SOP-A2", "SOP-A4"], "latest_file_id": "SOP-A3" } ]
```

---

## 7. Retrieval questions — `ground_truth/questions.jsonl`

Write **≥ 90 questions** (≥ 30 per kind) in Korean, one JSON object per line:

```json
{"id": "q-017", "question": "냉동고 D의 온도 이탈은 몇 분 동안 지속되었나?", "doc_file_id": "RPT-2", "doc_path": "02_reports/DEV-2026-0117_일탈보고서_온도이탈.docx", "answer": "47분", "kind": "text", "location": "p.2 §2 사건 개요", "requires_ocr": false, "difficulty": "easy"}
```

Rules:
- `answer` must appear **verbatim** (exact substring, same spacing and units) in the extracted text of `doc_path` — for `requires_ocr: false`, in the text layer / cell values; keep answers short (2–30 characters).
- `kind`:
  - `text` — answer is in prose or a list item.
  - `table` — answer is a cell value (ask about a specific row/column, e.g. "COA 로트 2026A031의 SEC 순도 결과는?" → `98.7 %`).
  - `image` — answer is in a **figure caption** or in **text visible inside an image** (chart axis/legend, nameplate, P&ID tag). Set `requires_ocr: true` when it is only inside the image pixels.
- Include **hard** cases: answers inside the page-2 continuation of a long table; answers that differ between revisions (ask about Rev.5 explicitly vs. "현재 기준"); facts only in PPTX speaker notes; facts only inside a PDF attachment or a ZIP/EML child; near-duplicate numbers in the same table (to punish sloppy chunks).
- Balance across departments and formats; at least 10 questions must target files nested inside ZIP/EML/PDF attachments (use `doc_path` like `07_archives/점검자료_2026-10.zip!/기록/온도기록_….csv`).
- Paraphrase: questions should **not** copy the sentence that contains the answer.

---

## 8. Quality bar

- Looks like a real Korean manufacturing company's documents, not a template: varied lengths, realistic numbering, occasional typos in handwritten marks only, real-looking tables with units and footnotes.
- No placeholder text (`Lorem ipsum`, `TBD`, `[내용]`).
- No contradictions except the deliberate ones listed in §4–§5 (record each deliberate contradiction in the manifest `notes`).
- Images: photoreal ones must not contain text or logos; code-rendered ones must have crisp, correctly rendered Korean.
- File sizes: keep each file < 15 MB (EDGE-5 < 40 MB). Compress JPEG at quality 85.

---

## 9. Self-verification (do this before delivering each phase)

Write and run a verification script, include its output in `generation_log.md`:

1. Re-open every DOCX/XLSX/PPTX/PDF with its library; record page/slide/sheet counts and compare to the manifest.
2. Extract text from digital PDFs (`pypdf`) and DOCX/PPTX/XLSX; assert that Korean characters are present and that no `�`/tofu appears; assert image-only PDFs have **no** text layer.
3. For every non-OCR question, assert `answer in extracted_text(doc_path)` (for nested paths, extract the child first). Report any failures and fix them.
4. Assert PDF attachments exist (`reader.attachments`), the encrypted PDF needs the password, ZIP nesting depth and CP949 names are as specified, EML attachments decode with the right file names.
5. Assert SOP-A4 is byte-identical to SOP-A2 and EDGE-2 starts with `%PDF`.
6. Assert every `link` in the manifest actually exists in the file (hyperlink rel, formula text, or literal string).
7. Compute `bytes` and `sha256` for the manifest.

---

## 10. Delivery plan

Work in phases. After each phase, give me **one ZIP** (`corpus_phaseN.zip`) containing the new files **and** the cumulative `ground_truth/` and `generation_log.md`. Keep `file_id`s and paths stable across phases.

- **Phase 1 (P0, foundations):** fonts check → SOP family A (A1–A4, A3P), family B (B1, B2), SOP-C1, RPT-1, RPT-1P, RPT-2, RPT-2P, COA-1, COA-1S, XLS-1, XLS-2, XLS-3, PPT-1, EML-1, EML-2, ZIP-1, ZIP-2, SCN-1, SCN-2, IMG-1…5, EDGE-1…3; manifest, references, gold for these, and ≥ 45 questions.
- **Phase 2 (P1):** remaining P1 files, gold, questions up to ≥ 90.
- **Phase 3 (P2, best effort):** P2 files and optional HWPX/XLSM; list anything skipped and why.

If something in this brief is impossible in your environment, do the closest faithful thing, say exactly what you changed in `generation_log.md`, and keep going. Ask me only when blocked (e.g. no Korean font available).

---

## 11. Do not

- Do not use real company, product, person, regulator-document, or vendor names; do not imitate real logos or letterheads.
- Do not put readable text inside image-generation outputs (render text with code instead).
- Do not regenerate a file that must be a byte-identical copy — copy the bytes.
- Do not change file names, `file_id`s, or deliberate contradictions between phases.
- Do not summarise the corpus in place of producing files — I need the actual files.
