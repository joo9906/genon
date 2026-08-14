# onprem/mcp — MCP 도구 (area 01)

**파일 1개 = MCP 등록 단위 1개.** 전부 **LLM 을 부르지 않는 결정적 도구**만 담는다.
그래서 워크플로우가 마음 놓고 직접 호출할 수 있고, 판정 결과로 캔버스 분기를 걸 수 있다.

---

## ⚠️ MCP 는 서빙이 아니라 파일이다 (2026-08-11 정정)

처음에 **MCP 를 코드서빙처럼 만들었다** — 디렉토리마다 FastAPI 앱을 두고 `/health`·
`$PORT`·`requirements.txt` 를 갖추고 `/mcp` JSON-RPC 라우트를 손으로 구현했다.
**전부 틀렸다.** GenOS MCP 등록은 이렇게 동작한다:

- **소스 파일 한 개**를 등록한다. 패키지로 쪼갤 수 없다.
- `mcp` 객체를 **런타임이 전역으로 주입**한다. 우리가 만들지 않는다.
- 도구는 `@mcp.tool()` 데코레이터로 등록하고 **JSON 문자열**을 돌려준다.
- 엔벨로프(JSON-RPC, `content[].text` 포장)는 런타임이 씌운다. 우리 몫이 아니다.
- FastAPI 앱도 `/health` 도 `$PORT` 도 **없다.**

그래서 네 서빙 디렉토리를 네 파일로 합쳤다. 다시 디렉토리로 쪼개지 말 것 —
`check_deploy_contract.check_mcp_files()` 가 막는다.

---

## 도구 파일 4개

| 파일 | 접두어 | 도구 | 추가 의존 |
|---|---|---|---|
| `genon_text_guard.py` | `TG` | `markdown_structure_issues` `fact_issues` `numeric_issues` `diff_changes` `evidence_check` | 없음 (stdlib) |
| `genon_lang_policy.py` | `LP` | `detect_language` `validate_direction` `list_languages` `list_registers` `resolve_register` `resolve_tone` | 없음 (stdlib) |
| `genon_glossary.py` | `GL` | `glossary_lookup` `glossary_status` `glossary_reload` | 없음 (stdlib) |
| `genon_hwpx_text.py` | `HX` | `hwpx_to_markdown` | `lxml` (부팅 시 설치) |

---

## 파일 하나가 지켜야 하는 것

### 0. `print()` 를 쓰지 않는다 — 대신 **stderr 로깅** (2026-08-14)

`print()` 는 stdout 으로 나간다. MCP 는 **stdout 이 전송 채널이 될 수 있어서**(stdio 방식)
로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용 로깅을 쓰는 이유와 같고,
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
쪽이 앞엣것을 덮고, 그 실패는 **"도구가 이상한 값을 낸다"** 로만 드러난다.

가상의 위험이 아니다. 합치는 도중 실제로 밟았다 — `languages.py` 와 `registers.py` 가
둘 다 `supported_payload` 를 정의해서, 합친 뒤 `list_languages` 가 **문체 목록**을
돌려줬다. `check_mcp_tools.py` 가 네 파일을 **한 네임스페이스에 넣어** 이걸 확인한다.

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
async def diff_changes(source: str = "", revised: str = "",
                       max_items: int | str | None = None) -> str:
    ...
    if max_items is not None and max_items != "":
        arguments["max_items"] = max_items
```

### 5. 입력 오류를 예외로 올리지 않는다

`ok=false` + `error_type` 으로 낸다. MCP 도구가 예외로 죽으면 호출부(워크플로우 스텝)에
오는 것은 **전송 실패와 구분되지 않는다** — 그러면 스텝이 "재시도 무의미" 를 판단하지
못하고, 사용자에게 고정 안내문 대신 일반 오류가 간다.

예외 원문은 응답에 싣지 않는다 (3.8절). **클래스 이름만 stderr 로그로** 남긴다(§0).

### 6. 비표준 패키지는 부팅 설치 절차를 지난다

MCP 기본 이미지에 무엇이 있는지 보장이 없다. `requirements.txt` 라는 개념이 없으므로
파일 안에서 설치한다 (`genon_hwpx_text.py` 의 `lxml` 하나뿐이다):

```python
def _hx_ensure_packages():
    for pkg, install_name in (("lxml", "lxml"),):
        if not importlib.util.find_spec(pkg):
            subprocess.check_call([sys.executable, "-m", "pip", "install", install_name])
```

### 7. 기동 훅이 없다 — 필요하면 첫 호출에서 한다

`genon_glossary.py` 가 그렇다. 용어사전을 **import 시점이 아니라 첫 도구 호출에서**
적재한다 — import 가 느리면 서빙이 왜 안 뜨는지 드러나지 않지만, 첫 호출로 미루면 그
지연이 그 호출의 지연으로 보인다.

### 8. ~~`print()` 를 쓴다~~ — **2026-08-14 에 뒤집었다**

"MCP 파일에는 로깅 설정이 없다" 가 그때의 근거였다. 그 근거를 §0 이 없앴다(파일마다
자기 stderr 핸들러를 붙인다). stdout 은 전송 채널일 수 있으므로 거기 쓰지 않는다.

---

## 호출 경로

워크플로우 스텝이 게이트웨이를 통해 부른다:

```
{GENOS_URL}/api/gateway/mcp/{serving_id}/mcp     JSON-RPC  {"method": "tools/call"}
```

응답의 `result.content[].text` 를 JSON 으로 파싱한다. 스텝 파일마다 `_mcp_call` 이
그 일을 하며, **자기완결 규율상 공용 모듈로 뺄 수 없어 9번 중복돼 있다.**

**게이트웨이가 JSON-RPC 를 그대로 통과시키는지는 아직 실물로 확인되지 않았다.**
형식이 다르면 `_mcp_call` 을 스텝마다 고쳐야 한다.

스텝이 서빙을 찾는 환경변수: `LANG_POLICY_MCP_ID` · `TEXT_GUARD_MCP_ID` ·
`HWPX_TEXT_MCP_ID`.

---

## 의도된 중복

판정 모듈은 원본 배포 단위에도 **그대로 남아 있다.** 배포 단위 간 import 이 금지이고,
코드서빙이 자기 안에서 같은 검증을 직접 부르는 경로가 있기 때문이다
(`mv` 가 아니라 `cp` 인 이유). **eval 이 세 배포 단위를 import 하지 않는 것과 같은 규칙**
이며, 사본이 갈리는지는 `onprem/test/` 의 대조 점검이 잡는다:

| 사본 | 벌 수 | 점검 |
|---|---|---|
| 표 격자 규칙 | 4 | `check_table_grid.py` (MCP·번역·FAQ·006 미리보기) |
| 톤 프리셋 | 3 | `check_tone_policy.py` (원본은 `genon_lang_policy.py` 의 `LPTONE_PRESETS`) |
| 용어사전 적용 언어 (ko·en) | 2 | `check_mcp_tools.py` (`genon_glossary.py` ↔ 번역 `languages.py`) |

톤 프리셋이 4벌에서 3벌이 됐다 — 2026-08-12 에 006 의 톤 변환 기능을 없애면서 그 사본이
사라졌다. `hwpx_preprocessor.py`(area 05)도 같은 격자 규칙을 쓰지만 **`check_table_grid`
대상이 아니다** — 표를 언제나 HTML 로 내는 앞단 판정이 그 파일에만 있기 때문이고,
격자 규칙 자체를 고칠 때는 여전히 넷과 함께 맞춰야 한다.

---

## 검증

```bash
export PYTHONIOENCODING=utf-8
python onprem/test/check_mcp_tools.py        # 40건 — 공존·결정적 판정·빈 문자열 주입
                                             #        + 용어사전 적용 언어 사본 대조
python onprem/test/check_deploy_contract.py  # 파일 계약 — 접두어·`async … -> str`·shim·
                                             # 상대 import 금지·부팅 설치·**print 금지·stderr 로깅**
```

`check_mcp_tools.py` 는 HTTP 를 흉내 내지 않는다. 파일을 실어 `@mcp.tool()` 로 등록된
함수를 직접 부른다 — GenOS 가 하는 일과 같은 모양이다.
