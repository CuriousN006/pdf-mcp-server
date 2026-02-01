# PDF MCP Server

**v0.3.0**

PDF 파일을 멀티모달 LLM이 읽을 수 있게 해주는 MCP 서버입니다.

## 특징

- **페이지 이미지 변환**: PDF 페이지를 이미지로 렌더링하여 LLM에 직접 전달
- **전체 PDF 한 번에 읽기**: `read_pdf_all`로 모든 페이지를 한 번에 처리
- **스마트 읽기**: `read_pdf_smart`로 텍스트/이미지 페이지 자동 판단

- **벡터 그래픽 감지**: 드로잉(그래프, 도표) 개수도 함께 표시
- **레이아웃 완벽 지원**: 2단 레이아웃, 벡터 그래프, 표 등 모두 정확히 표현
- **스마트 캐싱**: PDF 수정 시 자동으로 캐시 갱신, 캐시 삭제 도구 제공

## 설치

### 기본 설치

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

### `read_pdf_smart` ⭐ (권장 - 효율적)
**페이지 내용을 분석하여 최적의 방식으로 읽기**
- 텍스트만 있는 페이지 → 텍스트로 반환 (빠름, 토큰 절약)
- 이미지/드로잉이 있는 페이지 → 이미지로 렌더링

```
read_pdf_smart(path="d:/path/to/file.pdf")
read_pdf_smart(path="d:/path/to/file.pdf", start_page=1, end_page=5)
```

### `read_pdf_all`
**전체 PDF를 이미지로 읽기** - 모든 페이지를 이미지로 변환

```
read_pdf_all(path="d:/path/to/file.pdf")
read_pdf_all(path="d:/path/to/file.pdf", start_page=1, end_page=10)  # 범위 지정
```

### `read_pdf_page`
특정 페이지만 이미지로 읽기

```
read_pdf_page(path="d:/path/to/file.pdf", page_number=1)
```

### `read_pdf_info`
PDF 메타데이터 읽기 (페이지 수, 제목, 저자, 이미지/드로잉 개수 등)

```
read_pdf_info(path="d:/path/to/file.pdf")
```

출력 예시:
```
📋 페이지 요약:
  [1] 이미지: 0개, 드로잉: 5개 | 텍스트 미리보기...
  [2] 이미지: 2개, 드로잉: 0개 | 텍스트 미리보기...
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



### `clear_pdf_cache`
PDF 캐시 삭제

```
clear_pdf_cache(path="d:/path/to/file.pdf")              # 실제 삭제
clear_pdf_cache(path="d:/path/to/file.pdf", dry_run=True)  # 미리보기만
```

## 캐시 구조

```
📁 example.pdf
📁 example_pdf_cache/        ← 자동 생성
   ├── .cache_meta.json      ← PDF 수정 감지용 메타데이터
   ├── page_001.png          ← 페이지 1 이미지
   ├── page_002.png          ← 페이지 2 이미지
   └── ...
```

- PDF 파일이 수정되면 캐시가 자동으로 갱신됩니다
- `clear_pdf_cache`로 수동 삭제 가능

## LLM 사용 가이드

### 권장 사용 패턴

```
# 효율적으로 전체 읽기 (텍스트/이미지 자동 판단)
read_pdf_smart(path="d:/path/to/paper.pdf")

# 특정 범위만 읽기
read_pdf_smart(path="d:/path/to/paper.pdf", start_page=5, end_page=10)

# 전부 이미지로 읽기 (레이아웃 중요할 때)
read_pdf_all(path="d:/path/to/paper.pdf")

# 특정 페이지만 읽기
read_pdf_page(path="d:/path/to/paper.pdf", page_number=3)
```

- `read_pdf_smart`: 토큰 절약하면서 그래프/도표도 정확히 보기
- `read_pdf_all`: 모든 페이지를 이미지로 보기 (레이아웃 완벽)

- 이미지로 변환되므로 `view_file` 호출 없이 바로 표시됩니다

## 버전 히스토리

### v0.3.0
- **코드 리팩토링 및 최적화**
  - DEPRECATED 코드 정리 (불필요한 Marker 관련 코드 제거)
  - Context Manager 패턴 적용 (`with` 문으로 리소스 관리 개선)
  - 매직 넘버 상수화 (코드 가독성 향상)
  - PEP 8 스타일 정규화
  - 약 225줄의 코드 정리로 유지보수성 향상
- 성능이나 기능 변화 없음 (코드 품질 개선 릴리스)

### v0.2.1
- `read_pdf_marker` 비활성화: 딥러닝 모델 로딩이 지나치게 시간이 소요되어 실용성 부족
- marker-pdf 의존성 제거로 설치 크기 감소

### v0.2.0
- ~~`read_pdf_marker`: Marker 딥러닝 기반 PDF 변환 추가~~ (v0.2.1에서 비활성화)
- `clear_pdf_cache`: 캐시 삭제 도구 추가
- 캐시 자동 갱신: PDF 수정 시 캐시 무효화
- 리소스 누수 방지 개선

### v0.1.0
- 최초 릴리스
- `read_pdf_smart`, `read_pdf_all`, `read_pdf_page` 등 기본 기능

