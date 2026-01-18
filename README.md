# PDF MCP Server

PDF 파일의 텍스트와 이미지를 읽기 위한 MCP 서버입니다.

## 특징

- **원본 순서 유지**: 텍스트와 이미지를 PDF 원본 순서대로 추출
- **멀티모달 LLM 지원**: 이미지를 파일로 저장하여 LLM이 `view_file`로 직접 확인 가능
- **이미지 캐싱**: 추출된 이미지를 캐시하여 재사용

## 설치

```powershell
cd d:\PythonPractice\pdf-mcp-server
pip install -e .
```

## VS Code 설정

`settings.json`에 다음을 추가:

```json
"mcpServers": {
  "pdf-reader": {
    "command": "pdf-mcp",
    "args": []
  }
}
```

## 사용 가능한 도구

### `read_pdf_info`
PDF 메타데이터 읽기 (페이지 수, 제목, 저자 등)

```
read_pdf_info(path="d:/path/to/file.pdf")
```

### `read_pdf_text`
텍스트만 추출 (전체 또는 페이지 범위)

```
read_pdf_text(path="d:/path/to/file.pdf", start_page=1, end_page=5)
```

### `read_pdf_page`
**핵심 도구** - 텍스트와 이미지를 순서대로 추출

```
read_pdf_page(path="d:/path/to/file.pdf", page_number=1)
```

반환 예시:
```
📖 페이지 1 / 10
============================================================

첫 번째 텍스트 단락...

[이미지: d:/path/to/file_pdf_cache/img_p1_001.png]

두 번째 텍스트 단락...

============================================================
💡 이미지를 보려면 view_file 도구로 위 경로를 열어주세요.
```

### `render_pdf_page`
페이지 전체를 이미지로 렌더링 (복잡한 레이아웃/스캔 PDF용)

```
render_pdf_page(path="d:/path/to/file.pdf", page_number=1, dpi=150)
```

## 캐시 구조

```
📁 example.pdf
📁 example_pdf_cache/        ← 자동 생성
   ├── page_001.png          ← 페이지 전체 렌더링
   ├── img_p1_001.png        ← 페이지 1의 첫 번째 이미지
   └── ...
```

## LLM 사용 가이드

PDF를 읽을 때는 **순서대로** 텍스트와 이미지를 확인해야 합니다:

### 권장 사용 패턴

1. `read_pdf_page` 도구로 페이지 내용 조회
2. 출력에서 `[이미지: 경로]`가 나오면 **바로** `view_file`로 해당 이미지 확인
3. 이미지 확인 후 다음 텍스트 계속 읽기

### 예시

```
1. read_pdf_page(path, page_number=4) 호출
   → 텍스트: "Figure 1은 와류 분포를 보여줍니다..."
   → [이미지: .../img_p4_001.png]
   
2. view_file(".../img_p4_001.png") 호출
   → 이미지 직접 확인
   
3. 다음 텍스트 계속: "Figure 1: Example of..."
```

이렇게 하면 원본 PDF를 읽는 것처럼 텍스트와 이미지를 순서대로 이해할 수 있습니다.
