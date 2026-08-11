"""빈 스텁 — 상류 `hwpx.oxml.__init__` 은 문서 모델 전체를 re-export 한다.

`package_validator` 가 필요로 하는 것은 `namespaces.HWPML_COMPAT_ROOT_NAMESPACES`
하나뿐이라, 그 모듈만 두고 나머지는 가져오지 않았다. 이 파일이 상류 것이면
`from ..oxml.namespaces import ...` 한 줄이 body/table/header 전부를 끌어온다.
"""
