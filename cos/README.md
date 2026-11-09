# cos — 코드스페이스에서 번역 + 용어사전 실제 검증 · 부하 테스트

GenOS **코드스페이스**에서 번역 기능을 **실제 LLM 게이트웨이 · 실제 용어사전 API** 로 한 번에 돌려 본다.
워크플로우를 올리거나 MCP 를 등록하지 않는다.

- 번역 코드서빙(`final/SFR-018-translate/request`)을 **사본 없이 그대로 import** 해서 프로세스 안에서 띄운다.
  그래서 여기서 나온 결과는 배포한 번역 서빙과 같은 코드의 결과다.
- 용어사전은 서빙이 평소처럼 **`데이터 > 용어사전` API 를 직접 호출**해서 받는다
  (`GET {API}/data/glossaries/{id}/attributes` · `/terms`). 파일을 읽지 않는다.
- 응답은 번역 기능과 같다 — 번역문에 **`<mark>` 하이라이트**가 붙고 **준수율**이 나온다.

## 준비

저장소를 코드스페이스에 받은 뒤:

```bash
pip install -r final/SFR-018-translate/request/requirements.txt

# LLM 게이트웨이
export GENOS_URL=...                 # 게이트웨이 주소 (/api/gateway 는 코드가 붙인다)
export LLM_SERVING_ID=...            # 번역에 쓸 서빙 id
export GENOS_TOKEN=...               # 게이트웨이 토큰

# 용어사전
export TRANSLATE_GLOSSARY_ID=...     # 데이터 > 용어사전 의 id
# 필요할 때만
export TRANSLATE_GLOSSARY_API_URL=...   # 비우면 https://genos.genon.ai/api/admin
export TRANSLATE_GLOSSARY_TOKEN=...     # 관리 API 토큰이 게이트웨이 토큰과 다를 때
export TRANSLATE_GLOSSARY_KO_ATTR=ko    # 속성 이름이 다를 때 (기본 ko / en)
export TRANSLATE_GLOSSARY_EN_ATTR=en
```

export 대신 같은 `KEY=값` 줄을 **`cos/.env`** 에 적어 두면 스크립트가 시작할 때 읽는다
(셸에 이미 있는 값이 우선, `.gitignore` 대상). 필수 넷 중 하나라도 없으면 실행 전에 멈추고 무엇이 없는지 알려 준다.

## 실행

```bash
python cos/run_translation_glossary.py                    # cos/dataset 의 문서 10개 전부
python cos/run_translation_glossary.py --docs cos/dataset/ko_03_mortgage_terms.md
python cos/run_translation_glossary.py --docs 내문서.md    # 아무 .md 나 (파일명 ko_/en_ 이면 원문 언어로 쓴다)
python cos/run_translation_glossary.py --no-baseline       # 사전 미적용 회차 생략 (LLM 호출 절반)
python cos/run_translation_glossary.py --quiet             # 번역문은 콘솔 말고 파일로만
```

방향은 원문이 한국어면 영어로, 영어면 한국어로 번역한다(용어사전은 한·영에만 있다).

## 무엇을 보여 주나

맨 먼저 **용어사전 적재 상태**(`loaded` · `reason` · 언어별 건수)와 **프롬프트 출처**를 찍는다.
`loaded: false` 면 `reason` 이 원인이다 — `fetch_failed_401`(토큰) · `attribute_not_found`(속성 이름) 등.

문서마다 **두 번** 번역한다.

| 회차 | 뜻 |
|---|---|
| 사전 적용 | 운영과 같다 — 문서에 나온 용어가 프롬프트에 실린다 |
| 사전 미적용 | 프롬프트에서 용어 절만 뺀다. 준수율은 같은 사전으로 잰다 |

두 준수율의 차이가 **사전이 실제로 바꾼 만큼**이다. 콘솔에 문서별로:

- HTTP · 걸린 시간 · LLM 호출 수 · **준수율 (적용/매칭)** · 오류 · 폴백률 · 숫자 경고
- 프롬프트에 실린 용어 줄 수, **사전을 실었는데 안 따른 용어**, **사전 덕분에 맞춘 용어**
- **동형어 함정** 결과 — `dataset/expect.json` 에 적은, 금융 뜻이 아닌 낱말(`감정이 상한` · `principal reason` 등)이 사전에 걸리면 FAIL
- **`<mark>` 하이라이트 번역문** (번역 기능 응답의 `markdown_highlighted` 그대로)

마지막 줄은 **전체 준수율**(사전 적용 / 미적용)이다.

결과 파일은 `cos/reports/<시각>/` 에 남는다(git 에 안 올라간다).

| 파일 | 내용 |
|---|---|
| `summary.md` | 문서별 표 + 프롬프트에 실린 용어 · 안 따른 용어 |
| `report.json` | 전체 응답(`hits` · `term_map` · `pairs` 등) |
| `<문서>.with.highlighted.md` | 번역문 `<mark>` 판 |
| `<문서>.source.highlighted.md` | 원문 `<mark>` 판 |
| `<문서>.with.md` / `.without.md` | 사전 적용 / 미적용 번역문 |

## 데이터셋 (`dataset/`)

실제로 번역에 들어올 만한 금융 문서 10개다. 한국어 5 · 영어 5.

| 파일 | 종류 |
|---|---|
| `ko_01_loan_product.md` | 개인 신용대출 상품설명서 (표 포함) |
| `ko_02_customer_reply_email.md` | 연체 고객 문의에 대한 은행 답변 메일 |
| `ko_03_mortgage_terms.md` | 주택담보대출 약정서 발췌 (조항 · 표) |
| `ko_04_aml_internal_notice.md` | 준법감시팀 해외 송금 · 자금세탁방지 내부 공지 |
| `ko_05_market_report.md` | 주간 채권시장 동향 리포트 |
| `en_01_delinquency_notice.md` | 미국식 연체 · 대출조건 조정 안내문 (표 포함) |
| `en_02_credit_card_agreement.md` | 신용카드 회원 약관 핵심 조항 |
| `en_03_partner_bank_email.md` | 해외 파트너 은행의 자산유동화 협의 메일 |
| `en_04_kyc_questionnaire.md` | 환거래 은행 KYC 질의서 |
| `en_05_customer_hardship_letter.md` | 실직 고객의 상환 유예 요청 편지 |

문서마다 금융 뜻이 아닌 동형어를 일부러 섞었다(`감정` · `지수` · `이전` · `principal reason` · `Note:` ·
`title` · `capital` · `in charge of` · `interest in`). 걸리면 안 되는 목록이 `expect.json` 이다.
문서를 더하려면 `.md` 를 넣기만 하면 된다 — 파일명을 `ko_`/`en_` 로 시작하면 원문 언어가 정해진다.

## 부하 테스트 (`load/`) — 젠포탈 `/api/genportal/chat`

**번역 · 글다듬이**를 동시 사용자 26명으로 한꺼번에 요청한다. **합격 기준: 모든 요청의 첫 토큰이 10초 안에 나오고 전부 성공**.
코드서빙이 아니라 젠포탈 앞단을 때리므로 위의 환경변수는 필요 없다(`httpx` 만 있으면 된다).

```bash
python cos/load/load_test.py --dry-run                     # 보낼 본문부터 확인 (보내지 않는다)
python cos/load/load_test.py                               # 번역+글다듬이 섞어서 26명 동시, 1회씩
python cos/load/load_test.py --scenario translate          # 번역만
python cos/load/load_test.py --scenario polish --rounds 3  # 글다듬이만, 사용자당 3회 연속
python cos/load/load_test.py --message "테스트 문장" --scenario polish   # 입력을 직접 줘서
```

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `--url` | `http://10.168.31.100:30908/api/genportal/chat` | 요청 주소 |
| `--users` | 26 | 동시 사용자 수. 첫 요청은 모두 같은 순간에 출발한다 |
| `--rounds` | 1 | 사용자당 요청 횟수 (앞 요청이 끝나면 다음) |
| `--ramp` | 0 | 출발을 이 초 동안 고르게 펼친다 (0 = 동시) |
| `--ttft-limit` | 10 | 첫 토큰 합격 한도(초) |
| `--token-pattern` | (없음) | 이 정규식에 맞는 조각부터 첫 토큰으로 친다 |
| `--header` | — | `"Authorization: Bearer …"` 처럼 헤더 추가 (여러 번 가능) |
| `--same-session` | 끔 | 켜면 사용자마다 세션 하나를 계속 쓴다 (기본은 요청마다 새 세션) |
| `--timeout` | 600 | 요청 하나의 최대 시간(초) |

- **payload 는 `load/scenarios.json` 에서 그대로 고친다.** 템플릿의 `{message}` · `{session_id}` · `{file_ids}` ·
  `{source_lang}` · `{target_lang}` 만 채워진다(번역 언어는 입력이 한글 위주면 ko→en, 아니면 en→ko).
  endpoint 이름 · `overrideConfig` 키가 실제와 다르면 여기만 고치면 된다.
- **입력**은 `load/messages/*.txt`(`---` 만 있는 줄로 구분 — 짧은 문장 · 메일 · 표 · 회의록 · 보고 등) 와
  `dataset/*.md`(번역만). 사용자마다 입력을 차례로 돌려 같은 문장만 보내지 않는다. 입력을 늘리려면 파일에 `---` 로 덧붙인다.
- **첫 토큰** = 내용이 있는 첫 조각(빈 줄 · SSE 주석 `:` · keep-alive 제외). 첫 실행 뒤 `summary.md` 의
  "첫 토큰으로 센 조각 예시" 를 본다 — 메타데이터가 먼저 오는 응답이면 `--token-pattern` 으로 좁힌다
  (예: `--token-pattern '"event"\s*:\s*"token"'`).
- **성공** = HTTP 2xx 이고 본문에 `"error": …` 가 없을 것(정상 응답에는 `error` 키가 없다 — `FRONT.md` §1.2).
- 결과: 콘솔에 요청마다 한 줄 + 시나리오별 표(성공 · 첫 토큰 10초 이내 건수 · p50/p95/최대 · PASS/FAIL) + **최종 판정**.
  파일은 `cos/reports/load_<시각>/requests.jsonl`(요청별 상세) · `summary.md`.
- FAQ · 템플릿 채우기는 아직 없다 — 나중에 `scenarios.json` 블록을 복사해 endpoint · overrideConfig 를 바꾸고
  `requires`(`file_ids` → `--file-id`, `template_id` → `--template-id`)를 달면 된다.

## 읽는 법

- **준수율이 낮다** → `사전을 실었는데 안 따른 용어` 를 본다. 번역문을 열어 실제로 틀렸는지, 사전 표기가
  어색해서 LLM 이 더 나은 말을 골랐는지 가른다. 뒤쪽이면 사전을 고친다.
- **사전 적용과 미적용 준수율이 같다** → LLM 이 사전 없이도 그 용어를 맞춘다는 뜻이다. 그 용어는 사전에 둘 이유가 약하다.
- **`translation_error` 가 있다 / 폴백률이 1.0** → LLM 호출이 실패했다(번역문이 원문 그대로다). 게이트웨이 설정을 본다.
- **준수율 1.0 인데 매칭 0** → 사전이 비었거나 안 걸렸다. 맨 위 적재 상태를 본다.
