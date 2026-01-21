"""
PDF MCP Server
==============
PDF 파일의 텍스트와 이미지를 읽기 위한 MCP 서버입니다.

MCP(Model Context Protocol)란?
- AI와 외부 도구 간의 표준 통신 프로토콜입니다.
- 이 서버를 통해 AI가 PDF 파일의 내용을 읽을 수 있습니다.

핵심 기능:
- 텍스트와 이미지를 **원본 순서대로** 추출
- 이미지는 파일로 저장하여 멀티모달 LLM이 직접 볼 수 있게 함
- 추출된 이미지 캐싱 (재사용 가능)

사용하는 라이브러리:
- mcp: MCP 프로토콜 구현체 (FastMCP 프레임워크 포함)
- pymupdf (fitz): PDF 파일을 파싱하고 이미지를 추출하는 라이브러리
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent
import fitz  # PyMuPDF
from pathlib import Path
from typing import Optional, List, Union
import os
import base64
import shutil
import json
import re
import io
from datetime import datetime

# Marker (PDF to Markdown) - lazy loading
_marker_converter = None

def _get_marker_converter():
    """
    Marker 모델을 lazy loading으로 초기화합니다.
    첫 호출 시에만 모델을 로드하여 메모리를 절약합니다.
    """
    global _marker_converter
    if _marker_converter is None:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        _marker_converter = PdfConverter(artifact_dict=create_model_dict())
    return _marker_converter


# ============================================================
# MCP 서버 초기화
# ============================================================
# FastMCP: MCP 서버를 쉽게 만들 수 있게 해주는 고수준 프레임워크

mcp = FastMCP("PDF Reader")


# ============================================================
# 헬퍼 함수들
# ============================================================

# 캐시 메타데이터 파일명
_CACHE_META_FILE = ".cache_meta.json"


def _is_cache_valid(pdf_path: Path, cache_dir: Path) -> bool:
    """
    캐시가 유효한지 검사합니다.

    PDF 파일의 수정 시간(mtime)과 크기(size)를 비교하여
    캐시가 최신 상태인지 확인합니다.

    Args:
        pdf_path: PDF 파일 경로
        cache_dir: 캐시 디렉토리 경로

    Returns:
        True면 캐시 유효, False면 캐시 무효 (재생성 필요)
    """
    meta_file = cache_dir / _CACHE_META_FILE

    if not meta_file.exists():
        return False

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # PDF 파일의 현재 상태
        pdf_stat = pdf_path.stat()
        current_mtime = pdf_stat.st_mtime
        current_size = pdf_stat.st_size

        # 저장된 값과 비교
        if meta.get("pdf_mtime") != current_mtime:
            return False
        if meta.get("pdf_size") != current_size:
            return False

        return True
    except (json.JSONDecodeError, KeyError, OSError):
        # 메타 파일이 손상되었거나 읽기 실패 시 캐시 무효
        return False


def _invalidate_cache(cache_dir: Path) -> None:
    """
    캐시 디렉토리 전체를 삭제합니다.

    Args:
        cache_dir: 삭제할 캐시 디렉토리 경로
    """
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def _save_cache_meta(pdf_path: Path, cache_dir: Path) -> None:
    """
    PDF 메타정보를 캐시 디렉토리에 저장합니다.

    Args:
        pdf_path: PDF 파일 경로
        cache_dir: 캐시 디렉토리 경로
    """
    pdf_stat = pdf_path.stat()
    meta = {
        "pdf_path": str(pdf_path.absolute()),
        "pdf_mtime": pdf_stat.st_mtime,
        "pdf_size": pdf_stat.st_size,
        "created_at": datetime.now().isoformat()
    }

    meta_file = cache_dir / _CACHE_META_FILE
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _get_cache_dir(pdf_path: str) -> Path:
    """
    PDF 파일과 같은 폴더에 캐시 디렉토리를 생성하고 경로를 반환합니다.

    PDF 파일이 수정되었으면 기존 캐시를 삭제하고 새로 생성합니다.

    예: example.pdf → example_pdf_cache/
    """
    pdf_path = Path(pdf_path)
    cache_dir_name = f"{pdf_path.stem}_pdf_cache"
    cache_dir = pdf_path.parent / cache_dir_name

    # 캐시 디렉토리가 이미 존재하면 유효성 검사
    if cache_dir.exists():
        if not _is_cache_valid(pdf_path, cache_dir):
            # 캐시 무효 → 삭제 후 재생성
            _invalidate_cache(cache_dir)

    # 캐시 디렉토리 생성
    cache_dir.mkdir(exist_ok=True)

    # 메타 파일이 없으면 생성
    meta_file = cache_dir / _CACHE_META_FILE
    if not meta_file.exists():
        _save_cache_meta(pdf_path, cache_dir)

    return cache_dir


def _load_pdf(path: str) -> fitz.Document:
    """
    PDF 파일을 열어서 Document 객체로 반환합니다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {path}")
    return fitz.open(path)


def _save_image(pixmap: fitz.Pixmap, cache_dir: Path, filename: str) -> str:
    """
    Pixmap 이미지를 PNG 파일로 저장하고 절대 경로를 반환합니다.
    """
    image_path = cache_dir / filename
    pixmap.save(str(image_path))
    return str(image_path.absolute())

# ============================================================
# [DEPRECATED] 미사용 코드 - 주석 처리 (2026-01-18)
# ============================================================
# 아래 함수는 텍스트와 이미지를 Y좌표 기준으로 정렬하여 원본 순서대로
# interleave하려는 시도였으나, 다음 문제로 인해 폐기되었습니다:
#   1. 벡터 그래픽(그래프, 도표)은 get_images()로 감지 불가
#   2. 2단 레이아웃에서 Y좌표만으로는 왼쪽/오른쪽 열 구분 불가
#   3. 복잡한 레이아웃(표, 캡션, 각주)에서 순서 결정 어려움
# 
# 대신 read_pdf_smart에서 페이지 전체를 이미지로 렌더링하는 방식을
# 사용합니다. 향후 필요시 참고용으로 남겨둡니다.
# ============================================================
#
# def _extract_page_elements(page: fitz.Page, cache_dir: Path, page_num: int) -> List[Tuple[float, str, str]]:
#     """
#     페이지에서 텍스트 블록과 이미지를 추출하고 Y좌표 기준으로 정렬합니다.
#     
#     Returns:
#         List of (y_position, element_type, content)
#         - element_type: "text" 또는 "image"
#         - content: 텍스트 내용 또는 이미지 파일 경로
#     """
#     elements = []
#     
#     # 1. 텍스트 블록 추출
#     # get_text("dict")는 페이지 내 모든 블록의 상세 정보를 반환
#     text_dict = page.get_text("dict")
#     
#     for block in text_dict.get("blocks", []):
#         bbox = block.get("bbox", (0, 0, 0, 0))  # (x0, y0, x1, y1)
#         y_pos = bbox[1]  # y0 좌표 (위에서부터의 거리)
#         
#         if block.get("type") == 0:  # 텍스트 블록
#             # 블록 내 모든 라인의 텍스트를 합침
#             text_lines = []
#             for line in block.get("lines", []):
#                 line_text = ""
#                 for span in line.get("spans", []):
#                     line_text += span.get("text", "")
#                 if line_text.strip():
#                     text_lines.append(line_text)
#             
#             if text_lines:
#                 text_content = "\n".join(text_lines)
#                 elements.append((y_pos, "text", text_content))
#     
#     # 2. 이미지 추출 - 각 이미지의 실제 위치(bbox)를 사용
#     # get_images()로 이미지 목록을 가져오고, get_image_rects()로 위치 확인
#     for img_idx, img_info in enumerate(page.get_images(full=True)):
#         xref = img_info[0]
#         
#         try:
#             # 이미지의 실제 위치(bbox) 가져오기
#             img_rects = page.get_image_rects(xref)
#             if not img_rects:
#                 continue  # 위치를 알 수 없으면 건너뜀
#             
#             # 첫 번째 rect의 y0 좌표 사용 (이미지가 여러 곳에 있을 수 있지만 첫 번째 사용)
#             y_pos = img_rects[0].y0
#             
#             # 이미지 데이터 추출
#             base_image = page.parent.extract_image(xref)
#             if base_image:
#                 image_bytes = base_image["image"]
#                 image_ext = base_image["ext"]
#                 
#                 # 이미지 저장
#                 filename = f"img_p{page_num + 1}_{img_idx + 1:03d}.{image_ext}"
#                 image_path = cache_dir / filename
#                 
#                 # 이미 캐시된 이미지가 있으면 재사용
#                 if not image_path.exists():
#                     with open(image_path, "wb") as f:
#                         f.write(image_bytes)
#                 
#                 elements.append((y_pos, "image", str(image_path.absolute())))
#         except Exception:
#             pass  # 이미지 추출 실패 시 무시
#     
#     # Y좌표 기준 정렬 (위에서 아래로)
#     elements.sort(key=lambda x: x[0])
#     
#     return elements


# ============================================================
# MCP 도구들
# ============================================================

@mcp.tool()
def read_pdf_info(path: str) -> str:
    """
    PDF 파일의 메타데이터를 읽어 반환합니다.

    Args:
        path: PDF 파일의 절대 경로

    Returns:
        PDF 기본 정보 (페이지 수, 제목, 저자 등)
    """
    doc = _load_pdf(path)
    try:
        result = []
        result.append(f"📄 PDF: {Path(path).name}")
        result.append(f"   총 페이지 수: {len(doc)}")

        # 메타데이터
        metadata = doc.metadata
        if metadata:
            if metadata.get("title"):
                result.append(f"   제목: {metadata['title']}")
            if metadata.get("author"):
                result.append(f"   저자: {metadata['author']}")
            if metadata.get("subject"):
                result.append(f"   주제: {metadata['subject']}")
            if metadata.get("creator"):
                result.append(f"   생성 프로그램: {metadata['creator']}")
            if metadata.get("creationDate"):
                result.append(f"   생성일: {metadata['creationDate']}")

        # 각 페이지 정보 요약
        result.append("")
        result.append("📋 페이지 요약:")
        result.append("-" * 40)

        for page_num in range(min(len(doc), 10)):  # 최대 10페이지까지만 요약
            page = doc[page_num]
            text_preview = page.get_text()[:50].replace('\n', ' ')
            img_count = len(page.get_images())
            drawing_count = len(page.get_drawings())
            result.append(f"  [{page_num + 1}] 이미지: {img_count}개, 드로잉: {drawing_count}개 | {text_preview}...")

        if len(doc) > 10:
            result.append(f"  ... 외 {len(doc) - 10}페이지 더 있음")

        return "\n".join(result)
    finally:
        doc.close()


@mcp.tool()
def read_pdf_text(
    path: str,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None
) -> str:
    """
    PDF에서 텍스트만 추출합니다. (이미지 제외)

    Args:
        path: PDF 파일의 절대 경로
        start_page: 시작 페이지 (1부터 시작, None이면 처음부터)
        end_page: 끝 페이지 (포함, None이면 끝까지)

    Returns:
        추출된 텍스트
    """
    doc = _load_pdf(path)
    try:
        # 페이지 범위 설정
        total_pages = len(doc)
        start = (start_page - 1) if start_page else 0
        end = end_page if end_page else total_pages

        # 범위 검증
        start = max(0, min(start, total_pages - 1))
        end = max(start + 1, min(end, total_pages))

        result = []
        result.append(f"📄 PDF: {Path(path).name}")
        result.append(f"   페이지 범위: {start + 1} ~ {end}")
        result.append("")
        result.append("=" * 60)

        for page_num in range(start, end):
            page = doc[page_num]
            text = page.get_text()

            result.append(f"\n📖 페이지 {page_num + 1}")
            result.append("-" * 40)
            result.append(text.strip() if text.strip() else "(텍스트 없음)")
            result.append("")

        return "\n".join(result)
    finally:
        doc.close()
@mcp.tool()
def read_pdf_page(
    path: str,
    page_number: int
) -> List[Union[TextContent, ImageContent]]:
    """
    PDF 페이지의 텍스트와 이미지를 **원본 순서대로** 추출합니다.

    이 도구는 멀티모달 LLM이 PDF를 읽는 것처럼 텍스트와 이미지를
    순서대로 확인할 수 있도록 합니다.

    이미지는 캐시 폴더에 저장되며, 반환된 경로를 view_file 도구로
    열어서 실제 이미지를 볼 수 있습니다.

    Args:
        path: PDF 파일의 절대 경로
        page_number: 읽을 페이지 번호 (1부터 시작)

    Returns:
        텍스트와 이미지 경로가 순서대로 포함된 마크다운
    """
    doc = _load_pdf(path)
    try:
        # 페이지 번호 검증
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"페이지 번호 {page_number}가 유효하지 않습니다. 유효 범위: 1 ~ {len(doc)}")

        page = doc[page_number - 1]
        cache_dir = _get_cache_dir(path)

        # 페이지 전체를 이미지로 렌더링 (150 DPI)
        filename = f"page_{page_number:03d}.png"
        image_path = cache_dir / filename

        # 캐시가 없을 때만 렌더링
        if not image_path.exists():
            zoom = 150 / 72
            matrix = fitz.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix)
            pixmap.save(str(image_path))

        # 이미지를 base64로 인코딩
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # 결과 반환
        return [
            TextContent(type="text", text=f"📖 페이지 {page_number} / {len(doc)}\n"),
            ImageContent(type="image", data=image_data, mimeType="image/png")
        ]
    finally:
        doc.close()


@mcp.tool()
def read_pdf_all(
    path: str,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None
) -> List[Union[TextContent, ImageContent]]:
    """
    PDF 전체를 한 번에 읽어서 모든 페이지를 이미지로 반환합니다.

    각 페이지를 이미지로 렌더링하여 순서대로 반환합니다.
    페이지 수가 많은 PDF의 경우 토큰 비용이 클 수 있습니다.

    Args:
        path: PDF 파일의 절대 경로
        start_page: 시작 페이지 (1부터 시작, None이면 처음부터)
        end_page: 끝 페이지 (포함, None이면 끝까지)

    Returns:
        모든 페이지의 텍스트 헤더와 이미지를 순서대로 포함한 리스트
    """
    doc = _load_pdf(path)
    try:
        cache_dir = _get_cache_dir(path)

        # 페이지 범위 설정
        total_pages = len(doc)
        start = (start_page - 1) if start_page else 0
        end = end_page if end_page else total_pages

        # 범위 검증
        start = max(0, min(start, total_pages - 1))
        end = max(start + 1, min(end, total_pages))

        range_text = f"페이지 {start + 1}~{end}" if (start_page or end_page) else f"전체 {total_pages}페이지"
        result = [
            TextContent(type="text", text=f"📄 PDF: {Path(path).name} ({range_text})\n{'='*60}\n")
        ]

        zoom = 150 / 72
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(start, end):
            page = doc[page_num]

            # 페이지 렌더링 (캐시가 없을 때만)
            filename = f"page_{page_num + 1:03d}.png"
            image_path = cache_dir / filename

            if not image_path.exists():
                pixmap = page.get_pixmap(matrix=matrix)
                pixmap.save(str(image_path))

            # 이미지 base64 인코딩
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            # 페이지 헤더와 이미지 추가
            result.append(TextContent(type="text", text=f"\n📖 페이지 {page_num + 1}\n"))
            result.append(ImageContent(type="image", data=image_data, mimeType="image/png"))

        return result
    finally:
        doc.close()


@mcp.tool()
def read_pdf_smart(
    path: str,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None
) -> List[Union[TextContent, ImageContent]]:
    """
    페이지 내용을 분석하여 최적의 방식으로 PDF를 읽습니다.

    - 텍스트만 있는 페이지 → 텍스트로 반환 (빠름, 토큰 절약)
    - 이미지/드로잉(그래프, 도표)이 있는 페이지 → 이미지로 렌더링

    Args:
        path: PDF 파일의 절대 경로
        start_page: 시작 페이지 (1부터 시작, None이면 처음부터)
        end_page: 끝 페이지 (포함, None이면 끝까지)

    Returns:
        텍스트와 이미지가 페이지 순서대로 포함된 리스트
    """
    doc = _load_pdf(path)
    try:
        cache_dir = _get_cache_dir(path)

        # 페이지 범위 설정
        total_pages = len(doc)
        start = (start_page - 1) if start_page else 0
        end = end_page if end_page else total_pages

        # 범위 검증
        start = max(0, min(start, total_pages - 1))
        end = max(start + 1, min(end, total_pages))

        range_text = f"페이지 {start + 1}~{end}" if (start_page or end_page) else f"전체 {total_pages}페이지"
        result = [
            TextContent(type="text", text=f"📄 PDF: {Path(path).name} ({range_text}) [스마트 모드]\n{'='*60}\n")
        ]

        zoom = 150 / 72
        matrix = fitz.Matrix(zoom, zoom)

        text_page_count = 0
        image_page_count = 0

        for page_num in range(start, end):
            page = doc[page_num]

            # 이미지/드로잉 존재 여부 확인
            has_images = len(page.get_images()) > 0
            has_drawings = len(page.get_drawings()) > 0

            if has_images or has_drawings:
                # 이미지/드로잉이 있으면 페이지 전체를 이미지로 렌더링 (캐시가 없을 때만)
                image_page_count += 1
                filename = f"page_{page_num + 1:03d}.png"
                image_path = cache_dir / filename

                if not image_path.exists():
                    pixmap = page.get_pixmap(matrix=matrix)
                    pixmap.save(str(image_path))

                with open(image_path, "rb") as f:
                    image_data = base64.standard_b64encode(f.read()).decode("utf-8")

                result.append(TextContent(type="text", text=f"\n📖 페이지 {page_num + 1} 🖼️\n"))
                result.append(ImageContent(type="image", data=image_data, mimeType="image/png"))
            else:
                # 텍스트만 있으면 텍스트로 반환
                text_page_count += 1
                text = page.get_text().strip()
                result.append(TextContent(
                    type="text",
                    text=f"\n📖 페이지 {page_num + 1} 📝\n{'-'*40}\n{text if text else '(텍스트 없음)'}\n"
                ))

        # 요약 정보 추가
        result.append(TextContent(
            type="text",
            text=f"\n{'='*60}\n📊 처리 결과: 텍스트 {text_page_count}페이지, 이미지 {image_page_count}페이지"
        ))

        return result
    finally:
        doc.close()

@mcp.tool()
def render_pdf_page(
    path: str,
    page_number: int,
    dpi: int = 150
) -> str:
    """
    PDF 페이지 전체를 이미지로 렌더링합니다.

    복잡한 레이아웃이나 스캔된 PDF의 경우, 페이지 전체를 이미지로
    렌더링하여 멀티모달 LLM이 직접 볼 수 있게 합니다.

    Args:
        path: PDF 파일의 절대 경로
        page_number: 렌더링할 페이지 번호 (1부터 시작)
        dpi: 렌더링 해상도 (기본값: 150)

    Returns:
        렌더링된 이미지 파일의 절대 경로
    """
    doc = _load_pdf(path)
    try:
        # 페이지 번호 검증
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"페이지 번호 {page_number}가 유효하지 않습니다. 유효 범위: 1 ~ {len(doc)}")

        page = doc[page_number - 1]
        cache_dir = _get_cache_dir(path)

        # 파일명에 DPI 포함 (DPI별로 다른 캐시 파일 사용)
        filename = f"page_{page_number:03d}_{dpi}dpi.png"
        image_path = cache_dir / filename

        # 캐시가 없을 때만 렌더링
        if not image_path.exists():
            zoom = dpi / 72  # 72 DPI가 기본
            matrix = fitz.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix)
            pixmap.save(str(image_path))
            width, height = pixmap.width, pixmap.height
        else:
            # 캐시된 이미지의 크기 정보는 파일에서 읽어야 하지만,
            # 간단히 "캐시 사용" 메시지만 표시
            width, height = "캐시", "사용"

        result = []
        result.append(f"🖼️ 페이지 {page_number} 렌더링 완료")
        result.append(f"   해상도: {dpi} DPI")
        result.append(f"   크기: {width} x {height}")
        result.append("")
        result.append(f"📁 이미지 경로: {image_path.absolute()}")
        result.append("")
        result.append("💡 view_file 도구로 위 경로를 열어서 이미지를 확인하세요.")

        return "\n".join(result)
    finally:
        doc.close()


def _parse_markdown_with_images(
    markdown_text: str,
    images: dict
) -> List[tuple]:
    """
    마크다운 텍스트에서 이미지 참조를 찾아 텍스트와 이미지로 분리합니다.

    Args:
        markdown_text: Marker가 생성한 마크다운 텍스트
        images: Marker가 추출한 이미지 딕셔너리 {파일명: PIL Image}

    Returns:
        [("text", "텍스트 내용"), ("image", "파일명"), ...] 형태의 리스트
    """
    # 마크다운 이미지 패턴: ![alt text](filename)
    image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

    segments = []
    last_end = 0

    for match in image_pattern.finditer(markdown_text):
        # 이미지 앞의 텍스트
        text_before = markdown_text[last_end:match.start()]
        if text_before.strip():
            segments.append(("text", text_before))

        # 이미지 파일명 추출
        image_filename = match.group(2)
        segments.append(("image", image_filename))

        last_end = match.end()

    # 마지막 이미지 뒤의 텍스트
    text_after = markdown_text[last_end:]
    if text_after.strip():
        segments.append(("text", text_after))

    return segments


@mcp.tool()
def read_pdf_marker(path: str) -> List[Union[TextContent, ImageContent]]:
    """
    Marker를 사용하여 PDF를 읽고, 텍스트와 이미지를 원본 순서대로 반환합니다.

    딥러닝 기반으로 복잡한 레이아웃(2단, 표, 각주 등)을 자동 분석하고,
    텍스트와 이미지를 원본 PDF의 읽기 순서대로 추출합니다.

    - 벡터 그래픽(차트, 도표)도 이미지로 변환하여 포함
    - 표, 수식(LaTeX), 코드 블록 등을 정확하게 추출

    ⚠️ 첫 실행 시 모델 로딩에 시간이 걸릴 수 있습니다 (약 10-30초).

    Args:
        path: PDF 파일의 절대 경로

    Returns:
        텍스트와 이미지가 원본 순서대로 포함된 리스트
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {path}")

    # Marker 변환 실행
    converter = _get_marker_converter()
    rendered = converter(path)

    # 결과 추출
    from marker.output import text_from_rendered
    markdown_text, _, images = text_from_rendered(rendered)

    # 마크다운을 텍스트/이미지 세그먼트로 분리
    segments = _parse_markdown_with_images(markdown_text, images)

    # MCP Content 리스트 생성
    result = [
        TextContent(
            type="text",
            text=f"📄 PDF: {Path(path).name} [Marker 딥러닝 변환]\n{'='*60}\n"
        )
    ]

    for segment_type, content in segments:
        if segment_type == "text":
            result.append(TextContent(type="text", text=content))
        elif segment_type == "image":
            # images 딕셔너리에서 PIL Image 가져오기
            pil_image = images.get(content)
            if pil_image:
                # PIL Image를 base64로 인코딩
                buffer = io.BytesIO()
                # PNG 형식으로 저장 (JPEG보다 품질이 좋음)
                pil_image.save(buffer, format="PNG")
                image_data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
                result.append(ImageContent(type="image", data=image_data, mimeType="image/png"))
            else:
                # 이미지를 찾을 수 없으면 텍스트로 대체
                result.append(TextContent(type="text", text=f"\n[이미지: {content}]\n"))

    # 요약 정보
    image_count = sum(1 for s in segments if s[0] == "image")
    result.append(TextContent(
        type="text",
        text=f"\n{'='*60}\n📊 추출 결과: 이미지 {image_count}개 포함"
    ))

    return result


@mcp.tool()
def clear_pdf_cache(path: str, dry_run: bool = False) -> str:
    """
    PDF 파일의 캐시를 삭제합니다.

    캐시 디렉토리 전체를 삭제하여 다음 호출 시 새로 생성되도록 합니다.
    디스크 공간을 확보하거나 캐시 문제 해결 시 사용하세요.

    Args:
        path: PDF 파일의 절대 경로
        dry_run: True면 삭제하지 않고 삭제될 내용만 미리보기

    Returns:
        삭제 결과 또는 미리보기 메시지
    """
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {path}")

    # 캐시 디렉토리 경로 계산 (생성하지 않음)
    cache_dir_name = f"{pdf_path.stem}_pdf_cache"
    cache_dir = pdf_path.parent / cache_dir_name

    if not cache_dir.exists():
        return f"ℹ️ 캐시가 존재하지 않습니다: {cache_dir}"

    # 캐시 내용 분석
    files = list(cache_dir.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    size_mb = total_size / (1024 * 1024)

    result = []

    if dry_run:
        result.append(f"🔍 캐시 미리보기: {cache_dir_name}")
        result.append(f"   📁 위치: {cache_dir}")
        result.append(f"   📊 파일 수: {file_count}개")
        result.append(f"   💾 총 크기: {size_mb:.2f} MB")
        result.append("")
        result.append("   파일 목록:")
        for f in sorted(files)[:20]:  # 최대 20개만 표시
            if f.is_file():
                f_size = f.stat().st_size / 1024
                result.append(f"   - {f.name} ({f_size:.1f} KB)")
        if file_count > 20:
            result.append(f"   ... 외 {file_count - 20}개 파일")
        result.append("")
        result.append("ℹ️ 실제 삭제를 원하면 dry_run=False로 호출하세요.")
    else:
        # 실제 삭제
        shutil.rmtree(cache_dir)
        result.append(f"🗑️ 캐시 삭제 완료: {cache_dir_name}")
        result.append(f"   📁 위치: {cache_dir}")
        result.append(f"   📊 삭제된 파일: {file_count}개")
        result.append(f"   💾 확보된 공간: {size_mb:.2f} MB")

    return "\n".join(result)


# ============================================================
# 서버 실행
# ============================================================

def main():
    """
    MCP 서버를 실행합니다.
    """
    mcp.run()


if __name__ == "__main__":
    main()
