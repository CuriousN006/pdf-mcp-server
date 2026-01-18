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
import fitz  # PyMuPDF
from pathlib import Path
from typing import Optional, List, Tuple
import os


# ============================================================
# MCP 서버 초기화
# ============================================================
# FastMCP: MCP 서버를 쉽게 만들 수 있게 해주는 고수준 프레임워크

mcp = FastMCP("PDF Reader")


# ============================================================
# 헬퍼 함수들
# ============================================================

def _get_cache_dir(pdf_path: str) -> Path:
    """
    PDF 파일과 같은 폴더에 캐시 디렉토리를 생성하고 경로를 반환합니다.
    
    예: example.pdf → example_pdf_cache/
    """
    pdf_path = Path(pdf_path)
    cache_dir_name = f"{pdf_path.stem}_pdf_cache"
    cache_dir = pdf_path.parent / cache_dir_name
    cache_dir.mkdir(exist_ok=True)
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


def _extract_page_elements(page: fitz.Page, cache_dir: Path, page_num: int) -> List[Tuple[float, str, str]]:
    """
    페이지에서 텍스트 블록과 이미지를 추출하고 Y좌표 기준으로 정렬합니다.
    
    Returns:
        List of (y_position, element_type, content)
        - element_type: "text" 또는 "image"
        - content: 텍스트 내용 또는 이미지 파일 경로
    """
    elements = []
    
    # 1. 텍스트 블록 추출
    # get_text("dict")는 페이지 내 모든 블록의 상세 정보를 반환
    text_dict = page.get_text("dict")
    
    for block in text_dict.get("blocks", []):
        bbox = block.get("bbox", (0, 0, 0, 0))  # (x0, y0, x1, y1)
        y_pos = bbox[1]  # y0 좌표 (위에서부터의 거리)
        
        if block.get("type") == 0:  # 텍스트 블록
            # 블록 내 모든 라인의 텍스트를 합침
            text_lines = []
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                if line_text.strip():
                    text_lines.append(line_text)
            
            if text_lines:
                text_content = "\n".join(text_lines)
                elements.append((y_pos, "text", text_content))
    
    # 2. 이미지 추출 - 각 이미지의 실제 위치(bbox)를 사용
    # get_images()로 이미지 목록을 가져오고, get_image_rects()로 위치 확인
    for img_idx, img_info in enumerate(page.get_images(full=True)):
        xref = img_info[0]
        
        try:
            # 이미지의 실제 위치(bbox) 가져오기
            img_rects = page.get_image_rects(xref)
            if not img_rects:
                continue  # 위치를 알 수 없으면 건너뜀
            
            # 첫 번째 rect의 y0 좌표 사용 (이미지가 여러 곳에 있을 수 있지만 첫 번째 사용)
            y_pos = img_rects[0].y0
            
            # 이미지 데이터 추출
            base_image = page.parent.extract_image(xref)
            if base_image:
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                
                # 이미지 저장
                filename = f"img_p{page_num + 1}_{img_idx + 1:03d}.{image_ext}"
                image_path = cache_dir / filename
                
                # 이미 캐시된 이미지가 있으면 재사용
                if not image_path.exists():
                    with open(image_path, "wb") as f:
                        f.write(image_bytes)
                
                elements.append((y_pos, "image", str(image_path.absolute())))
        except Exception:
            pass  # 이미지 추출 실패 시 무시
    
    # Y좌표 기준 정렬 (위에서 아래로)
    elements.sort(key=lambda x: x[0])
    
    return elements


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
        result.append(f"  [{page_num + 1}] 이미지: {img_count}개 | {text_preview}...")
    
    if len(doc) > 10:
        result.append(f"  ... 외 {len(doc) - 10}페이지 더 있음")
    
    doc.close()
    return "\n".join(result)


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
    
    doc.close()
    return "\n".join(result)


@mcp.tool()
def read_pdf_page(
    path: str,
    page_number: int
) -> str:
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
    
    # 페이지 번호 검증
    if page_number < 1 or page_number > len(doc):
        doc.close()
        raise ValueError(f"페이지 번호 {page_number}가 유효하지 않습니다. 유효 범위: 1 ~ {len(doc)}")
    
    page = doc[page_number - 1]
    cache_dir = _get_cache_dir(path)
    
    # 페이지 요소 추출 (Y좌표 순서대로)
    elements = _extract_page_elements(page, cache_dir, page_number - 1)
    
    result = []
    result.append(f"📖 페이지 {page_number} / {len(doc)}")
    result.append("=" * 60)
    result.append("")
    
    if not elements:
        result.append("(이 페이지에는 내용이 없습니다)")
    else:
        for y_pos, elem_type, content in elements:
            if elem_type == "text":
                result.append(content)
                result.append("")  # 텍스트 블록 사이 빈 줄
            elif elem_type == "image":
                result.append(f"[이미지: {content}]")
                result.append("")
    
    result.append("=" * 60)
    result.append(f"💡 이미지를 보려면 view_file 도구로 위 경로를 열어주세요.")
    
    doc.close()
    return "\n".join(result)


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
    
    # 페이지 번호 검증
    if page_number < 1 or page_number > len(doc):
        doc.close()
        raise ValueError(f"페이지 번호 {page_number}가 유효하지 않습니다. 유효 범위: 1 ~ {len(doc)}")
    
    page = doc[page_number - 1]
    cache_dir = _get_cache_dir(path)
    
    # 렌더링 (DPI 기반 확대)
    zoom = dpi / 72  # 72 DPI가 기본
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix)
    
    # 파일로 저장
    filename = f"page_{page_number:03d}.png"
    image_path = _save_image(pixmap, cache_dir, filename)
    
    doc.close()
    
    result = []
    result.append(f"🖼️ 페이지 {page_number} 렌더링 완료")
    result.append(f"   해상도: {dpi} DPI")
    result.append(f"   크기: {pixmap.width} x {pixmap.height}")
    result.append("")
    result.append(f"📁 이미지 경로: {image_path}")
    result.append("")
    result.append("💡 view_file 도구로 위 경로를 열어서 이미지를 확인하세요.")
    
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
