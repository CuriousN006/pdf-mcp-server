# PDF MCP Server

PDF 파일을 멀티모달 LLM이 읽을 수 있게 해주는 MCP 서버입니다.

## 특징

- **페이지 이미지 변환**: PDF 페이지를 이미지로 렌더링하여 LLM에 직접 전달
- **전체 PDF 한 번에 읽기**: `read_pdf_all`로 모든 페이지를 한 번에 처리
- **레이아웃 완벽 지원**: 2단 레이아웃, 벡터 그래프, 표 등 모두 정확히 표현
- **이미지 캐싱**: 렌더링된 이미지를 캐시하여 재사용

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

### `read_pdf_all` ⭐ (권장)
**전체 PDF를 한 번에 읽기** - 모든 페이지를 이미지로 변환하여 반환

```
read_pdf_all(path="d:/path/to/file.pdf")
```

### `read_pdf_page`
특정 페이지만 이미지로 읽기

```
read_pdf_page(path="d:/path/to/file.pdf", page_number=1)
```

### `read_pdf_info`
PDF 메타데이터 읽기 (페이지 수, 제목, 저자 등)

```
read_pdf_info(path="d:/path/to/file.pdf")
```

### `read_pdf_text`
텍스트만 추출 (검색/복사용)

```
read_pdf_text(path="d:/path/to/file.pdf", start_page=1, end_page=5)
```

### `render_pdf_page`
페이지를 특정 DPI로 렌더링

```
render_pdf_page(path="d:/path/to/file.pdf", page_number=1, dpi=150)
```

## 캐시 구조

```
📁 example.pdf
📁 example_pdf_cache/        ← 자동 생성
   ├── page_001.png          ← 페이지 1 이미지
   ├── page_002.png          ← 페이지 2 이미지
   └── ...
```

## LLM 사용 가이드

### 권장 사용 패턴

```
# 전체 PDF 읽기 (한 번에)
read_pdf_all(path="d:/path/to/paper.pdf")

# 특정 페이지만 읽기
read_pdf_page(path="d:/path/to/paper.pdf", page_number=3)
```

- 이미지로 변환되므로 레이아웃, 그래프, 표가 완벽하게 보입니다
- `view_file` 호출 없이 바로 이미지가 표시됩니다
