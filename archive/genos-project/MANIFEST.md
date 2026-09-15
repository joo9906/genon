# MANIFEST.md — 패키지 내용물

**총 17개 원본 파일 + 문서 3개.** 원본은 `source/`에 **바이트 단위 그대로** 담았다 (`diff -r` 검증 완료, 변형/재인코딩 없음).

## 구조
```
genos-project/
├── CLAUDE.md              # Claude Code 작업 지시서 (루트에 두면 자동 로드)
├── MANIFEST.md            # 이 파일
├── docs/
│   ├── GENOS_RULES.md     # 개발가이드 v1.02 강제 규칙 + 체크리스트
│   └── AUDIT.md           # 현재 코드 가이드 위반 목록
└── source/                # 프로젝트 지식 원본 17개 (무변경)
```

## 파일 목록

### 코드 서빙 — Office/HWPX 번역 파이프라인 (area 03)
| 파일 | 크기 | 역할 |
|---|---|---|
| `main.py` | 3,019 B | FastAPI 진입점. `/health`, `/translate` |
| `pipeline.py` | 1,947 B | 오케스트레이션. `run_translation_job()` |
| `translation_modes.py` | 5,471 B | llm/mock/noop 분기, 배치 분할, 단건 폴백 |
| `llm.py` | 4,209 B | Gateway 경유 LLM 호출. 재시도 상한 |
| `config.py` | 1,655 B | 환경변수. 시크릿 기본값 없음 |
| `error_codes.py` | 2,703 B | **오류 코드 단일 소스** (03-000200xx) |
| `types.py` | 1,244 B | TranslationUnit / Artifacts / Deps |
| `units.py` | 1,462 B | 노드 ↔ 번역단위 변환 |
| `prompt_builder.py` | 1,828 B | 프롬프트 빌더 |
| `validation.py` | 1,661 B | LLM 배치 응답 검증 |
| `logging_utils.py` | 468 B | 로거 래퍼 (print 금지) |

### HWPX 처리
| 파일 | 크기 | 역할 |
|---|---|---|
| `hwpx_report.py` | 5,767 B | HWPX 템플릿 채우기 PoC. ZIP 해제 → lxml 치환 → 재압축. **가이드 미준수, 리팩터링 대상** |

### 전처리기 참조 구현 (GenOS 제공, 읽기 전용)
| 파일 | 크기 | 역할 |
|---|---|---|
| `첨부용_전처리기` | 96,028 B | v2.2.2. **확장자 없음 = Python.** `HwpProcessor` 네이티브 경로 + 3단 폴백. HWP/HWPX는 이쪽이 우수 |
| `지능형_전처리기` | 151,591 B | **확장자 없음 = Python.** 무조건 PDF 변환 후 처리 → 구조 손실 |

### 워크플로우 / Flowise
| 파일 | 크기 | 역할 |
|---|---|---|
| `전처리기_적용시_데이터_위치__및_채팅_답변_노출_방법` | 1,484 B | **확장자 없음 = Python.** `run(data)` 스트리밍 템플릿. `genosUploaded` 읽는 위치 + socket.io token/result 패턴 |
| `Weaviate_적재_코드` | 19,268 B | **확장자 없음 = Python.** quick_search MCP 도구 + Weaviate 적재. CRLF 개행. 403 미해결 |

### 레퍼런스
| 파일 | 크기 | 역할 |
|---|---|---|
| `260721_GenOS_엔지니어_개발가이드_v1_02.pdf` | 8,879,005 B | **원문 가이드.** 판단이 애매하면 이 문서가 최종 근거 |

---

## ⚠️ 확장자 없는 Python 파일 4개

`첨부용_전처리기`, `지능형_전처리기`, `전처리기_적용시_데이터_위치__및_채팅_답변_노출_방법`, `Weaviate_적재_코드`
— 전부 Python 소스다. 원본 보존을 위해 이름을 바꾸지 않았다.

에디터/린터 인식이 필요하면:
```bash
cd source
for f in 첨부용_전처리기 지능형_전처리기 Weaviate_적재_코드 전처리기_적용시_데이터_위치__및_채팅_답변_노출_방법; do
  cp "$f" "$f.py"
done
```

---

## 무결성 (SHA-256)

```
fee2812f050390cf7c304f007a5275209cb6a588322c49becd7dae665363f6c0  260721_GenOS_엔지니어_개발가이드_v1_02.pdf
56b0a22603820576186842343c460f629c7d6bac4221b995642f1c6af4208770  Weaviate_적재_코드
b3aa8b32ec6d8b01432e5c3606dd3369aaa60a1dbaecdc6ae9b5704b0c2613ab  config.py
05e43fc23571613a99b356db2388d4e76723b21954694566ae1cbe8def89974f  error_codes.py
7b99702ef8f16b105e42807828c119f4570a5d9b026e481190f5260813479085  hwpx_report.py
a6158779b697b44e5ba778da4ddbe01e7dcf93ddca878a19bfe265243fc4b9cc  llm.py
f8edaaab71553e3981b6a21c6c5ca61a211cc7052393afe23d13d2ba78a47bbc  logging_utils.py
841465bcb18e13d4d5fb19f16f52b6dafdf29866a3f3653a0886f3cca5da8704  main.py
2ece4fcce438d3d92a2cb2b969dc3f02012a065cd74d64e65c0e5f4986312c14  pipeline.py
5f383627b9618341c663e8aa3d3ad42d058ea1bd178488b7498a92784cde9c09  prompt_builder.py
218321e16f4f09dec07e755207acfd44b8897242336bcf2580b934af30a45d43  translation_modes.py
33d36a00f9847bff283ad2b0de91369d3d88c01f46f12de96d7be58b6e3f535c  types.py
ed608395c592694a48ebb749067b9238a1172dcf578ca192b81cb73ef216d873  units.py
c7b067990fa941118e8c530245bc11f2b6dbdcec232f5b15e44711d10d3906cb  validation.py
5d8f7301c38a61bcd8c0f68309284e81795a79dfa40b487bb4a11ad19e33dbcc  전처리기_적용시_데이터_위치__및_채팅_답변_노출_방법
472d39be1511766b2e60562a1eaedafc12007cf6fc02c3633a28d5f6694bb441  지능형_전처리기
0efba9939fc97f50dbc83d230e3db29ed54b73dbfcdadc572e0f26360293b353  첨부용_전처리기
```

검증:
```bash
cd source && sha256sum -c ../CHECKSUMS.txt
```

## 참고 — source/의 실제 배치 경로
`source/`는 평면 구조지만, 코드 서빙 파일들의 원래 패키지 경로는 이렇다 (`CLAUDE.md` §2 참고):
```
translation_pipeline/common/  ← config, error_codes, llm, logging_utils, prompt_builder, validation
translation_pipeline/office/  ← types, units, translation_modes, pipeline
translation_pipeline/main.py
```
