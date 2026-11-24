# OCR 모델 비교 (2026-11-24, 이 Mac)

> 라이브러리 OCR(EasyOCR 등)은 쓰지도 재지도 않는다는 결정(`docs/DECISIONS.md`)에 따라 **문서 OCR 모델만** 비교했다. 모든 수치는 표본 기준이라 오차가 크다. 순위가 아니라 방향을 정하는 자료로 쓴다.

## 결론

1. **모델을 어떻게 부르느냐가 모델 선택보다 크다.** 영역 단위로 학습된 모델(PaddleOCR-VL, GLM-OCR)에 쪽 전체를 한 번에 넣으면 빽빽한 쪽에서 같은 문장을 되풀이하고 표가 무너진다(표 TEDS 0.15).
2. **GLM-OCR은 한국어 글자 인식이 약하다.** 깨끗한 본문(KDI)에서도 0.69(PaddleOCR-VL 0.90). `오대독신`→`오대특신`, `고령자`→`고량자` 같은 오인이 잦다. 후보에서 뺀다.
3. **도메인 숫자는 모델 하나로 충분하다.** Docling 레이아웃 + PaddleOCR-VL 영역 호출로 합성 스캔 5종의 숫자+단위 **61/62(98.4%)**, 핵심 값 31/32, 표 칸 267/286(93%). 같은 스캔 COA를 EasyOCR은 11/26으로 읽었다. 단, PaddleOCR-VL은 `±`·`≥`를 `\(\pm\)`·`\(\geq\)`처럼 LaTeX로 내므로 **기호 변환 후처리가 필요**하다(변환 전 56/62).
4. **앙상블은 지금 필요 없다.** KoOCR 총점 0.7대는 읽기 순서·머리말·빽빽한 표까지 쪽 단위로 세는 어려운 기준이다(상용 1위 Mistral OCR도 0.77, 범용 VLM Gemini flash-lite 0.74). 숫자·표 칸에 한해 교차 확인(불일치면 '검토 필요')은 실제 고객 스캔에서 오류가 보이면 붙인다.
5. **연결 방식 두 가지를 모두 지원한다**(게이트웨이 OpenAI 호환 API):
   - **영역 방식**: Docling 레이아웃(우리 쪽, 이미 설치) → 영역별 VL 모델 호출. PaddleOCR-VL-1.6(0.9B, Apache-2.0) 시험 완료. 이 Mac에서 쪽당 약 7초. 표는 공식 파이프라인 수준(TEDS 0.61), 본문 읽기 순서는 공식보다 낮다(0.63 대 0.72) → 겹친 영역 정리·읽기 순서 보강 필요.
   - **쪽 방식**: 쪽 하나를 한 번 호출, 모델이 레이아웃·HTML 표·좌표까지 낸다. Schift `schift-ocr-1-beta`(한국어 특화, MIT, 약 4B)·Unlimited-OCR. 공개 예측 기준 0.73/0.53. CUDA(vLLM)가 필요해 이 Mac에서는 못 돌렸다.

## 1. KoOCR-Bench 표본 60쪽

[schift-io/KoOCR-Bench](https://huggingface.co/datasets/schift-io/KoOCR-Bench)(실제 한국어 문서 623쪽, 평가 전용)에서 6개 영역 × 10쪽. 채점은 공개 채점기의 지표 정의를 따라 다시 구현했다(`scripts/ocr-bench/koocr_eval.py`): 글자는 1−CER(태그 제거, NFKC, 글자·숫자만, 외국 문자 벌점), 표는 TEDS. 공개 채점기 자체는 실행하지 않았다. 공개 PaddleOCR 예측을 이 채점기로 재면 공개 순위표와 표본 오차 안에서 비슷하지만 kostat 표는 낮게 나와(0.53 대 0.74), 절대값은 공개 순위표와 바로 비교하지 않는다.

| 방식 | 글자 1−CER | 표 TEDS | 쪽당 초 | 비고 |
|---|---|---|---|---|
| PaddleOCR-VL-1.6, 쪽 전체 1회 호출 (직접) | 0.540 | 0.145 | 11.3 | 반복 폭주 |
| GLM-OCR, 쪽 전체 1회 호출 (직접) | 0.489 | 0.136 | 15.3 | 한국어 오인 |
| **Docling 레이아웃 + PaddleOCR-VL 영역 호출 (직접)** | **0.628** | **0.452** | **6.9** | 표 영역 0.608 |
| PaddleOCR-VL-1.6 공식 파이프라인 (공개 예측) | 0.716 | 0.567 | - | 레이아웃 PP-DocLayout |
| MinerU (공개 예측) | 0.750 | 0.525 | - | 라이선스 확인 필요 |
| champ 체크포인트 (공개 예측, Schift로 추정) | 0.729 | 0.533 | - | 쪽 방식 |
| Unlimited-OCR (공개 예측) | 0.713 | 0.526 | - | 쪽 방식, Schift의 기반 |
| DeepSeek-OCR (공개 예측) | 0.566 | 0.491 | - | |

영역별(1−CER / TEDS):

| 영역 | 레이아웃+Paddle | 공식 Paddle | champ |
|---|---|---|---|
| 관보(표 많은 공문) | 0.652 | 0.852 | 0.853 |
| KDI 보고서 본문 | 0.884 | 0.807 | 0.889 |
| 사용자 업로드 문서 | 0.403 | 0.525 | 0.522 |
| 수능(2단) | 0.575 | 0.678 | 0.653 |
| 표(정책 첨부) TEDS | 0.608 | 0.606 | 0.586 |
| 통계표(넓은 표) TEDS | 0.295 | 0.527 | 0.480 |

## 2. 합성 도메인 정답

`samples/generated/ground_truth`의 스캔·이미지 파일. Docling 레이아웃 + PaddleOCR-VL 영역 호출, LaTeX 기호 변환 후 채점(`scripts/ocr-bench/domain_eval.py`).

| 파일 | 핵심 값 | 숫자+단위 | 표 칸 | 쪽당 초 |
|---|---|---|---|---|
| COA 스캔 PDF(3쪽) | 5/5 | 26/26 | 136/147 | 5 |
| 교정성적서 스캔 PDF(얼룩·회전) | 12/12 | 27/27 | 75/75 | 2 |
| 현장일지 사진 JPG | 3/3 | 3/3 | 16/16 | 1 |
| 보관조건 점검표 TIF(3쪽) | 5/6 | 2/3 | 40/48 | 7 |
| 설비 명판 PNG | 6/6 | 3/3 | - | 1 |

도표 이미지 3종(진동 추이·계통도·공정 흐름도)은 레이아웃이 '그림'으로 분류해 건너뛰어 제목만 읽었다. 그림 영역도 OCR해야 한다.

## 3. 다시 재는 법

원자료(KoOCR 이미지·정답·예측, 도메인 결과)는 `bench-data/`(git 제외)에 있다.

```bash
# PaddleOCR-VL-1.6 (llama.cpp, 처음 실행 때 자동 내려받기)
llama-server -hf PaddlePaddle/PaddleOCR-VL-1.6-GGUF --host 127.0.0.1 --port 8091 --temp 0 -c 16384 -ngl 99
# 영역 방식 60쪽
backend/.venv/bin/python scripts/ocr-bench/region_ocr.py bench-data/koocr paddle-region2 http://127.0.0.1:8091/v1 PaddlePaddle/PaddleOCR-VL-1.6-GGUF "OCR:" "Table Recognition:"
# 채점(apted·lxml·rapidfuzz가 있는 가상환경)
python scripts/ocr-bench/koocr_eval.py bench-data/koocr region=bench-data/koocr/pred/paddle-region2.jsonl pub=bench-data/koocr/pred/published-paddle.jsonl
# 도메인 정답
DOMAIN_OUT=bench-data/domain-out backend/.venv/bin/python scripts/ocr-bench/domain_eval.py paddle-region http://127.0.0.1:8091/v1 PaddlePaddle/PaddleOCR-VL-1.6-GGUF "OCR:" "Table Recognition:" COA-1S SCN-1 SCN-2 SCN-3 SCN-4
```

## 4. 하지 않은 것

- Schift·Unlimited-OCR 직접 실행(CUDA 필요). 게이트웨이에 올린 뒤 같은 스크립트로 잰다.
- PaddleOCR 공식 파이프라인을 이 Mac에서 재현(paddlepaddle 설치 필요).
- 실제 고객 문서. 합성 스캔은 실제보다 깨끗하다.
- 영역 방식의 겹친 영역 정리·읽기 순서 개선, 그림 영역 OCR.
