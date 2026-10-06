# final/mcp — MCP 도구 (area 01)

**파일 1개 = MCP 등록 단위 1개.** 전부 **LLM 을 부르지 않는 결정적 도구**만 담는다.
그래서 워크플로우가 마음 놓고 직접 호출할 수 있고, 판정 결과로 캔버스 분기를 걸 수 있다.

---

## ⚠️ MCP 는 서빙이 아니라 파일이다

GenOS MCP 등록은 코드서빙과 다르게 동작한다:

- **소스 파일 한 개**를 등록한다. 패키지로 쪼갤 수 없다.
- `mcp` 객체를 **런타임이 전역으로 주입**한다. 우리가 만들지 않는다.
- 도구는 `@mcp.tool()` 데코레이터로 등록하고 **JSON 문자열**을 돌려준다.
- 엔벨로프(JSON-RPC, `content[].text` 포장)는 런타임이 씌운다. 우리 몫이 아니다.
- FastAPI 앱도 `/health` 도 `$PORT` 도 `requirements.txt` 도 **없다.**

디렉토리로 쪼개거나 서빙처럼 만들지 말 것 — `check_deploy_contract.check_mcp_files()` 가 막는다.

---

## 도구 파일 4개

| 파일 | 접두어 | 도구 | 추가 의존 |
|---|---|---|---|
| `genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` | 없음 (stdlib) |
| `genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 없음 (stdlib) |
| `genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 없음 (stdlib) |
| `genon_pii_audit.py` | `PA` | `pii_audit` `pii_scan_text` `pii_detectors` | 없음 (stdlib) |

> **`genon_pii_audit` 은 워크플로우가 부르지 않는다.** 야간·주간처럼
> **사람이 직접 돌리는 감사**용이라 기능 응답 경로에 붙이지 않는다 — 매 응답마다
> 도는 판정이 아니고, 응답에 실으면 그 값이 화면 계약이 되어 나중에 바꿀 때 발이
> 묶인다. 판정부는 `Test/eval/eval_mcp/pii_metrics.py` 의 **사본**이고 `check_mcp_tools`
> 가 두 구현을 같은 입력으로 대조한다.

---

## 파일 하나가 지켜야 하는 것

### 0. `print()` 를 쓰지 않는다 — 대신 **stderr 로깅**

`print()` 는 stdout 으로 나간다. MCP 는 **stdout 이 전송 채널이 될 수 있어서**(stdio 방식)
로그 한 줄이 프로토콜을 깨뜨린다 — `Test/eval/` 이 stderr 전용 로깅을 쓰는 이유와 같고,
§C 도 print 를 금지한다.

그렇다고 `logging` 으로 바꾸기만 하면 **더 나쁘다**: 설정이 없는 프로세스에서
`logger.info` 는 **아무 데도 나오지 않는다**(기본 최후 핸들러가 WARNING 부터다).
부팅·적재 메시지가 소리 없이 사라진다. 그래서 각 파일이 자기 **stderr 핸들러**를 붙인다:

```python
_XXlog = logging.getLogger("genon_xxx")     # 로거 이름 = 파일 이름
def _XXsetup_logging() -> None:             # 핸들러가 이미 있으면 아무것도 안 한다
    ...  logging.StreamHandler(sys.stderr) ...  propagate = False
_XXsetup_logging()
```

`propagate=False` 가 중요하다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
`check_deploy_contract.check_mcp_files()` 가 **print 금지와 stderr 핸들러 유무를 함께**
본다(둘은 한 쌍이라 하나만 보면 반대쪽으로 조용히 무너진다).

### 1. 최상위 심볼에 파일별 접두어

**한 서버에 여러 도구 파일이 함께 로드될 수 있다.** 그때 이름이 겹치면 나중에 로드된
쪽이 앞엣것을 덮고, 그 실패는 **"도구가 이상한 값을 낸다"** 로만 드러난다 — 예를 들어
두 파일이 같은 이름의 `supported_payload` 를 정의하면 `list_languages` 가 **문체 목록**을
돌려준다. `check_mcp_tools.py` 가 네 파일을 **한 네임스페이스에 넣어** 이걸 확인한다.

**도구 함수 이름만 예외다.** 그건 LLM 에 노출되는 계약이라 접두어를 붙일 수 없다.

### 2. `mcp` 미주입 대비 shim

```python
try:
    mcp  # noqa: F821
except NameError:
    class _XXLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator
    mcp = _XXLocalMCP()
```

런타임이 주입하지만, 없을 때 `NameError` 로 죽으면 **로컬에서 파일을 열어 볼 수조차
없다.** 점검도 이 자리에 도구를 걷어가는 가짜를 심어 동작한다.

데코레이터는 **함수를 그대로 돌려줘야** 한다. 감싸서 다른 것을 돌려주면 파일 안에서
도구끼리 부르는 경우에 동작이 달라진다.

### 3. 도구는 `async def … -> str`

**JSON 문자열**을 돌려주는 계약이다. dict 를 돌려주면 런타임이 알아서 감싸 주지 않는다.

### 4. GenOS 는 빈 값을 `None` 이 아니라 `""` 로 준다

그래서 선택 인자를 `int`/`float`/`bool` 로만 선언하면 **MCP 가 본문에 닿기 전에 타입
검증에서 죽는다.** `int | str | None` 처럼 문자열도 받고 본문에서 캐스팅한다.

```python
async def some_tool(text: str = "", max_chars: int | str | None = None) -> str:
    ...
    if max_chars is not None and max_chars != "":
        arguments["max_chars"] = max_chars
```

### 4-0. `diff_changes` 는 **양쪽 좌표와 표시용 사본 둘**을 낸다

변경을 "본문 위 하이라이트" 로 보여 주려면 응답에 두 가지가 필요하다:

- **좌표** — 없으면 화면이 `after` 문자열을 본문에서 다시 찾아야 하고, **같은 낱말이 두 번
  나오면 어느 쪽을 칠할지 결정할 수 없다.**
- **`<mark>` 를 입힌 사본** — **정본은 손대지 않는다** (내려받기가 정본을 그대로 파일로
  만든다 — 번역의 `markdown_highlighted` 와 같은 규약).

화면이 원문과 되쓴 글을 **좌우로 놓고 비교**하므로 좌표도 사본도 **양쪽**이다.
`_TGwords` 가 before·after 양쪽을 문서 절대 좌표로 편다.

| 변경 | `source_span` | `target_span` | 화면 |
|---|---|---|---|
| 치환 | 있음 | 있음 | 양쪽 형광 |
| **삭제** | **있음** | `null` | **왼쪽만** |
| 삽입 | `null` | 있음 | 오른쪽만 |

빈 쪽 좌표는 `null` 이다 — 0 을 넣으면 문서 맨 앞이 칠해진다.

- **사본 조립기는 하나다.** `tgbuild_highlighted(text, changes, key=...)` 를 `key` 만
  바꿔 두 번 부른다. 원문 전용 경로를 두면 겹침 병합·보호 구간 규칙이 두 벌이 되고,
  한쪽만 고치는 실수는 **표가 깨지는 형태로만** 드러난다.
- **보호 구간은 각 텍스트에서 따로 계산한다.** 코드펜스·HTML 태그 위치가 원문과 되쓴
  글에서 다르므로, 한쪽 좌표를 다른 쪽에 쓰면 `<td rowspan="2">` 한가운데를 가른다.
- **`span` 필드는 두지 않는다.** 좌표가 둘인데 필드를 셋 두면 남는 하나는 언제나
  다른 하나의 사본이고, 읽는 쪽이 어느 것이 정본인지 모른다.

그리고 **낱말 단위**로 낸다. 문장 쌍은 "이 문장이 바뀌었다" 까지만 말하고, 그대로
칠하면 문장 전체가 형광이 되어 어느 낱말을 손질했는지가 오히려 묻힌다.

칠하지 않는 구간이 둘 있다 — **코드펜스 안**(태그가 화면에 글자로 나온다)과 **HTML 태그**
(`<td rowspan="2">` 가운데를 가르면 표가 통째로 깨진다). 대신 낱말을 끊을 때 **HTML 태그를
따로 끊는다** — 공백으로만 끊으면 전처리기가 낸 한 줄 HTML 표가 통째로 낱말 하나가 되고,
그 구간은 태그에 걸치므로 **HTML 표 안 변경은 영영 칠하지 못한다.**

#### 건수 상한을 두지 않는다

사본을 변경 목록으로 만들기 때문에 목록 상한이 곧 **하이라이트 상한**이 된다 — 상한
뒤의 변경에는 `<mark>` 가 아예 붙지 않아, 봐야 할 자리를 못 찾는다. 변경을 보여준다는
이 도구의 목적과 충돌한다.

크기의 실제 상한은 **입력 길이**(`_TGMAX_TEXT_CHARS` = 400,000자)가 잡는다.
넘으면 자르지 않고 `TOO_LONG_*` 로 요청을 세우므로 조용히 빠지는 경로가 아니다.
`truncated` 같은 필드도 두지 않는다 — 언제나 false 인 필드는 읽는 쪽이 "확인했다" 고
믿게 만든다.

> 글다듬이 워크플로우 스텝은 지금 `diff_changes` 를 부르지 않는다(원문·다듬은 글을
> 하이라이트 없이 낸다). 도구는 남아 있다.

### 4-1. 선택지가 있는 인자는 **스키마에 선택지를 싣는다**

언어·문체·문서유형·톤처럼 **백엔드가 표를 갖고 있는 값**을 맨 `str` 로 받으면, 노출되는
도구 스키마에는 "문자열" 이라고만 적힌다. 그러면 호출부(캔버스 화면·워크플로우 변수·
도구를 고르는 LLM)가 **자기 목록을 들고 있게 되고**, 언어가 늘거나 빠질 때 한쪽만
고친다. 그 상태는 예외를 내지 않는다 — 빈 드롭다운이나 "지원하지 않는 언어입니다" 로만
드러나고, 사용자에게는 백엔드가 막은 것처럼 보인다.

표에서 `enum` 을 **만들어서** 얹는다. 표가 유일한 출처라 사본이 생기지 않는다:

```python
try:  # FastMCP 가 스키마를 만들 때 이미 쓰는 패키지다 — 따로 설치할 것이 아니다.
    from pydantic import Field as _LPPydanticField
except Exception:      # 없으면 맨 str 로 떨어진다. 판정은 그대로다.
    _LPPydanticField = None

_LPTargetLangArg = Annotated[str, _LPPydanticField(
    description="… 선택지: ko(한국어), en(영어), …",
    json_schema_extra={"enum": ["ko", "en", "zh", "th", "vi", "ru", ""]})]

async def validate_direction(sample: str = "", target_lang: _LPTargetLangArg = "") -> str:
```

**`Literal[...]` 로 하지 않는다.** 스키마에 enum 이 실리는 것은 같지만, 지원 밖 값이
**도구 본문에 닿기 전에** 타입 검증에서 죽는다. 그러면 두 가지를 잃는다:

1. **별칭이 죽는다.** `lpresolve`·`lpresolve_register`·`glnormalize_lang` 은 `"한국어"`·
   `"korean"`·`"KO"`·`"문어체"` 를 일부러 흡수한다 (화면·워크플로우 변수 표기가 제각각
   이라 한 곳에서 정규화한다).
2. **거부가 판정이 아니라 오류가 된다.** `validate_direction` 은 "거부는 오류가 아니라
   판정 결과"(`allowed=false` + 고정 한국어 안내문)를 계약으로 삼는다. `resolve_tone` 의
   `tone_overridden`·`resolve_register` 의 `fell_back` 도 같이 사라진다.

**그래서 스키마에는 선택지를 싣되 판정은 본문이 한다** — 강제와 그물을 둘 다 둔다.
빈 문자열은 **항상** 선택지에 넣는다 (§4 — GenOS 가 미지정을 `""` 로 주입한다).

지금 실린 자리:

| 파일 | 도구 | 인자 | 선택지 출처 |
|---|---|---|---|
| `genon_lang_policy.py` | `validate_direction` | `target_lang`·`source_lang` | `LPSUPPORTED_LANGUAGES` |
| | `resolve_register` | `register` | `LPREGISTERS` |
| | `resolve_tone` | `doc_type`·`tone` | `LPDOC_TYPE_POLICIES`·`LPTONE_PRESETS` |
| `genon_glossary.py` | `glossary_lookup`·`glossary_status` | `target_lang` | `_GLLANGUAGE_CODES` |

용어사전 쪽 선택지에서 `zh`·`th`·`vi`·`ru` 를 **빼지 않는다.** 사전이 없는 언어로 물어
"이 언어에는 사전이 없다"(`enabled=false` + 사유)를 받는 것이, 호출부가 미적용 사유를
응답에 실을 수 있는 유일한 경로다. 빼면 그 질문 자체를 못 하게 된다.

`genon_glossary.py` 의 `target_lang` 은 **색인의 키로 그대로 쓰인다.** 그래서 enum 과
함께 `glnormalize_lang` 을 둔다 — 없으면 `"KO"`·`"한국어"` 가 `language_missing` 으로
떨어져 **용어사전만 조용히 빠진 번역**이 나가고, 대조할 용어가 없으니 준수율은 늘 1.0
이라 정상으로 보인다.

### 4-2. 원문 언어는 **선언과 문서를 대조한다**

`validate_direction` 은 대상 언어(선택)와 **문서**(선택이 아니다)를 함께 본다.
요구사항 §2 가 사용자에게 고르게 하는 것은 대상 언어와 문체뿐이고, §6("한국어가 아닌
쌍은 고려 X")을 집행하려면 원문 언어를 알아야 하는데 그 값은 선택으로 들어오지 않는다 —
**감지가 §6 의 유일한 집행 수단이다.** 선택지 enum(§4-1)이 대체하지 못한다.

`source_lang` 이 와도 **항상 감지하고 대조**한다. 선언만 믿으면 "한국어→러시아어" 를
고르고 영어 문서를 올렸을 때 실제 방향 `en→ru` 가 통과한다. 다만 **정본은 선언값**이다
(감지가 사용자의 선택을 조용히 덮으면 안 된다). 감지는 **거부의 근거로만**, §6 이 실제로
깨질 때만 쓴다.

**거부 판정을 최빈값으로 하지 않는다.** `본 사업 KPI 는 ROI, TCO, SLA 로 관리한다` 는
라틴 문자가 62% 라 최빈값으로는 영어이고, 문턱을 60% 로 두면 이 **멀쩡한 한국어
문장이 거부된다** — 우회할 방법이 없는 오차단이다. 그래서 **"선언한 언어의 문자가 문서에
사실상 없는가"**(`declared_share < 10%`)로 본다.

응답에 세 값이 더 실린다 — `detected_lang`(문서에서 감지한 최빈 언어)·
`source_declared`(사용자가 명시했는가)·`source_mismatch`(**통과한** 충돌). 마지막 것이
없으면 "원문 언어를 잘못 골랐다" 는 사실이 어디에도 남지 않는다.

**같은 판정이 번역 코드서빙 `office/languages.py` 에도 있다** — 직접 업로드
(`POST /translate/*`)는 MCP 를 지나지 않으므로, 한쪽만 고치면 그 경로에 뒷문이 남는다.

### 4-3. 톤·문서유형 표

내장 표는 톤 **4종**(격식·정중 `polite` / 친절·안내 `friendly` / 명확·간결 `clear` /
사실·객관 `objective`) · 문서유형 **5종**(메일 · 게시글 · 고객발송문구 + 톤 고정군 채무
사유 · 심사역 의견, 둘 다 `objective` 고정)이다.

- **옛 톤 코드 `report` 는 `LPLEGACY_TONE_ALIASES` 가 `clear` 로 받는다** — 없으면
  캔버스에 남은 값이 "모르는 톤" 이 되어 **조용히 기본 톤으로** 떨어진다. 별칭은 **지금
  표에 없을 때만** 탄다.
- `LPTONE_PRESETS`·`LPDOC_TYPE_POLICIES` 가 **선택지의 유일한 출처다.**
- **이 파일은 admin-api 를 부르지 않는다.** 프롬프트를 라이브러리에서 받는 것은 글다듬이
  코드서빙이고(`system_<tone>`·`doc_type_<code>` 이름=ID 매칭), 이 파일이 하는 일은
  **강제 톤 판정** 하나다. 그 판정에 필요한 것은 표뿐이다.
- **`policy_source`/`policy_reason` 을 응답에 싣지 않는다** — 출처가 하나라 언제나 같은
  값이고, 그런 필드는 읽는 쪽이 "확인했다" 고 믿게 만든다.
- **표가 2벌이다** — 여기와 글다듬이 `tone_presets.py`. 화면 목록은 글다듬이가 그리고
  **강제 톤 판정은 여기가** 하므로 갈리면 "고른 톤이 조용히 무시된다".
  `check_tone_policy.py` 가 표를 대조하고, `check_mcp_tools.py` 가 **도구를 실제로 불러**
  그 표가 판정을 지나는지 본다(표만 맞고 판정이 안 쓰면 아무 일도 안 일어난다).
- **톤을 늘리려면 두 표에 함께** 넣고 eval `TONE_RULES` 도 넣는다 — 안 넣으면 그 톤은
  채점에서 `skipped` 로 드러난다(통과로 세지 않는다).

### 5. 입력 오류를 예외로 올리지 않는다

`ok=false` + `error_type` 으로 낸다. MCP 도구가 예외로 죽으면 호출부(워크플로우 스텝)에
오는 것은 **전송 실패와 구분되지 않는다** — 그러면 스텝이 "재시도 무의미" 를 판단하지
못하고, 사용자에게 고정 안내문 대신 일반 오류가 간다.

예외 원문은 응답에 싣지 않는다 (3.8절). **클래스 이름만 stderr 로그로** 남긴다(§0).

### 6. 비표준 패키지는 부팅 설치 절차를 지난다 — **지금은 해당 없음**

MCP 기본 이미지에 무엇이 있는지 보장이 없고 `requirements.txt` 라는 개념이 없으므로,
비표준 패키지가 필요하면 파일 안에서 설치해야 한다.

네 파일은 **전부 stdlib 만 쓴다.** 그래서 폐쇄망 mirror 접근이 없어도 다 뜬다 — 절차가
필요해지면 아래 모양이다:

```python
def _xx_ensure_packages():
    for pkg, install_name in (("lxml", "lxml"),):
        if not importlib.util.find_spec(pkg):
            subprocess.check_call([sys.executable, "-m", "pip", "install", install_name])
```

### 7. 기동 훅이 없다 — 필요하면 첫 호출에서 한다

`genon_glossary.py` 가 그렇다. 용어사전을 **import 시점이 아니라 첫 도구 호출에서**
적재한다 — import 가 느리면 서빙이 왜 안 뜨는지 드러나지 않지만, 첫 호출로 미루면 그
지연이 그 호출의 지연으로 보인다.

---

## 호출 경로

워크플로우 스텝이 게이트웨이를 통해 부른다:

```
{GENOS_URL}/api/gateway/mcp/{serving_id}/mcp     JSON-RPC  {"method": "tools/call"}
```

응답의 `result.content[].text` 를 JSON 으로 파싱한다. 부르는 스텝(다듬-1·2, 번역-1·2)마다
`_mcp_call` 이 그 일을 하며, **자기완결 규율상 공용 모듈로 뺄 수 없어 스텝마다 사본이다.**
Accept 헤더 등 전송 규약은 `final/workflow/README.md` "MCP 호출 형식" 절.

스텝이 서빙을 찾는 환경변수는 **둘뿐이다**: `LANG_POLICY_MCP_ID`(번역-1·글다듬이-1) ·
`TEXT_GUARD_MCP_ID`(번역-2·글다듬이-2).

`genon_glossary`·`genon_pii_audit` 은 워크플로우 호출부가 없다: 전자는 코드서빙이 자기
`glossary_store.py` 로 하고, 후자는 사람이 직접 돌린다.

---

## 의도된 중복

판정 모듈은 원본 배포 단위에도 **그대로 남아 있다.** 배포 단위 간 import 이 금지이고,
코드서빙이 자기 안에서 같은 검증을 직접 부르는 경로가 있기 때문이다.
**eval 이 세 배포 단위를 import 하지 않는 것과 같은 규칙**이며, 사본이 갈리는지는
`Test/check/` 의 대조 점검이 잡는다:

| 사본 | 벌 수 | 점검 |
|---|---|---|
| 톤 프리셋 | 3 | `check_tone_policy.py` (원본은 `genon_lang_policy.py` 의 `LPTONE_PRESETS`) |
| **옛 톤 별칭표** (`report`→`clear`) | 2 | `check_tone_policy.py` (표가 같은가 + **판정을 실제로 지나는가**) |
| 용어사전 적용 언어 (ko·en) | 2 | `check_mcp_tools.py` (`genon_glossary.py` ↔ 번역 `languages.py`) |
| 언어 코드·별칭 표 | 2 | `check_mcp_tools.py` (`genon_lang_policy.py` ↔ `genon_glossary.py`) |
| 언어 감지 + 방향 판정 | 2 | `check_mcp_tools.py` ↔ `check_unit_endpoints.py` (`genon_lang_policy.py` ↔ 번역 `office/languages.py`) |
| PII 검출 규칙 | 2 | `check_mcp_tools.py` (`genon_pii_audit.py` ↔ eval `pii_metrics.py`) |
| 용어사전 적재 | 2 | 대조 점검 없음 — 번역 `glossary_store.py` 와 **함께 고친다** |

---

## 검증

```bash
export PYTHONIOENCODING=utf-8
python Test/run_all.py mcp_tools        # 공존·결정적 판정·빈 문자열 주입
                                        # + 용어사전 적용 언어 사본 대조
                                        # + 선택지가 스키마에 실리는가(enum ↔ 표)
                                        # + 언어 표기 정규화 + 원문 언어 교차검증
                                        # + PII 검출 사본 대조
python Test/run_all.py deploy_contract  # 파일 계약 — 접두어·`async … -> str`·shim·
                                        # 상대 import 금지·부팅 설치·print 금지·stderr 로깅
```

`check_mcp_tools.py` 는 HTTP 를 흉내 내지 않는다. 파일을 실어 `@mcp.tool()` 로 등록된
함수를 직접 부른다 — GenOS 가 하는 일과 같은 모양이다.
