import zipfile
from pathlib import Path

ZIP_PATH = "./genos-project.zip"   # 압축 파일 (상대경로)
EXTRACT_TO = "."                            # 현재 작업 디렉토리 기준 상대경로

def extract_zip(zip_path: str, extract_to: str) -> None:
    zip_path = Path(zip_path)
    extract_to = Path(extract_to)

    if not zip_path.exists():
        raise FileNotFoundError(f"zip 파일을 찾을 수 없습니다: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)

    print(f"압축 해제 완료: {zip_path} -> {extract_to.resolve()}")


if __name__ == "__main__":
    extract_zip(ZIP_PATH, EXTRACT_TO)