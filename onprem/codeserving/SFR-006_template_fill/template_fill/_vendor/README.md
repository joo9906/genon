# 벤더 사본 — python-hwpx

> 상류: `hwpx-genon` (= `python-hwpx` 6.0.2 포크), Apache-2.0, 리비전 **`caeb9cf`**
> 가져온 시점: 2026-08-10 · 라이선스 전문: `LICENSE-python-hwpx`
> 도입 판단의 근거는 `onprem/docs/hwpx_library_adoption.md` 가 정본이다.

## 왜 pip 의존이 아니라 사본인가

`python-hwpx` wheel 이 **폐쇄망 사내 registry 에 있으리라는 보장이 없다.** 없으면
`pip install -r requirements.txt` 가 조용히 그 줄만 건너뛰는 것이 아니라, 있으면 켜지고
없으면 꺼지는 검사가 된다 — 즉 **배포 환경에 따라 산출물이 검증 없이 나간다.**
그 불확실성이 도입 문서 §6·§8에 미확인으로 남아 있었다.

사본으로 두면 그 분기가 사라진다. 검사기는 이미지에 항상 들어 있고, 켜짐/꺼짐은
`TEMPLATE_FILL_VERIFY_OUTPUT`·`TEMPLATE_FILL_CHECK_OVERFLOW` 라는 **우리가 정한 스위치**
하나로만 결정된다.

## 무엇을 가져왔나

| 경로 | 줄 수 | 쓰는 곳 | 상류 대비 |
|---|---|---|---|
| `hwpx/form_fit/measure.py` | 489 | `overflow.py` | 그대로 |
| `hwpx/tools/package_validator.py` | 728 | `hwpx_verify.py` | **셋을 잘라냄**(아래) |
| `hwpx/opc/relationships.py` | 197 | 위 검사기 | 그대로 |
| `hwpx/opc/security.py` | 110 | 위 검사기 | 그대로 |
| `hwpx/oxml/namespaces.py` | 149 | 위 검사기 | 그대로 |

`__init__.py` 다섯 개는 **우리가 쓴 빈 스텁**이다. 상류의 `__init__` 을 그대로 쓰면
`from ..oxml.namespaces import ...` 한 줄이 문서 모델 40k 줄을 통째로 끌어온다.
비어 있는 것이 곧 "그 아래로는 의존하지 않는다"는 선언이다.

**이 트리의 import 는 stdlib + `lxml` 로 닫힌다.** 기계적 확인:
`python onprem/test/check_vendor_closure.py`

## `package_validator.py` 에서 잘라낸 것

1. `EditorOpenSafetyReport` / `validate_editor_open_safety`
2. `main()` 과 `if __name__ == "__main__"` CLI 진입점 (+ `argparse`·`Sequence` import)

`validate_editor_open_safety` 는 셋을 합친 함수였다 — `validate_package`(가져옴),
`validate_document`(우리가 다시 씀), **재개봉**(포기). 재개봉만 `HwpxDocument` 를 요구하고,
그것 하나 때문에 문서 모델 전체가 따라온다.

**왜 재개봉을 우리 코드로 다시 만들지 않았나.** 이 검사의 가치는 *다른 코드베이스가*
우리 산출물을 실제로 파싱해 본다는 데 있다. 우리 파서로 우리 writer 의 출력을 다시 열면
구조상 통과한다 — 검사가 항등식이 되고, 그런데도 "재개봉 통과"라는 이름을 달고 있으면
없는 것보다 나쁘다. 그래서 **하지 않고, 하지 않았다고 말한다**(`VerifyResult.reopen_checked`).

잘라낸 부분을 남겨 두지 않은 이유: 함수 안 `from ..document import HwpxDocument` 가
`except Exception` 에 걸려 있어 **ImportError 가 조용히 삼켜진다.** 그대로 두면 호출자가
"재개봉 실패"를 문서 결함으로 오해한다.

## 재동기화 절차

1. 상류를 갱신하고 새 리비전을 확인한다.
2. 위 표의 5개 파일을 덮어쓴다 (`__init__.py` 스텁은 **덮어쓰지 않는다**).
3. `package_validator.py` 에서 위 두 블록을 다시 잘라내고 `__all__` 을 맞춘다.
4. `python onprem/test/check_vendor_closure.py` — import 폐포 확인.
5. `python onprem/test/check_output_safety.py` — 동작 확인.
6. 이 파일의 리비전·줄 수 표를 갱신한다.

## 고치지 말 것

동작을 바꾸고 싶으면 **우리 어댑터 층**(`overflow.py`·`hwpx_verify.py`)에서 감싼다.
여기를 고치면 다음 재동기화에서 조용히 되돌아간다.
