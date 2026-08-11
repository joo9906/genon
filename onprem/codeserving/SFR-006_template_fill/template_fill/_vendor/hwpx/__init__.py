"""python-hwpx 의 **부분 사본** — 상류의 facade 는 일부러 가져오지 않았다.

상류 `hwpx/__init__.py` 는 `HwpxDocument` 를 비롯한 문서 모델 전체(약 40k 줄)를
끌어온다. 우리가 쓰는 것은 측정기와 패키지 검사기 둘뿐이라 이 파일은 **비어 있다** —
비워 둔 것이 곧 "그 아래로는 의존하지 않는다" 는 선언이다.

`onprem/test/check_vendor_closure.py` 가 이 트리의 import 가 stdlib + lxml 로만
닫히는지 기계적으로 확인한다.
"""
