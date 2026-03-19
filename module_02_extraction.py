"""
Module 2: Text Extraction and OCR
Extracts raw text from the PDF.
- Text-based PDFs: direct extraction via pdfplumber
- Scanned PDFs: page-to-image conversion + pytesseract OCR
"""

import io
from typing import List
import pdfplumber
from PIL import Image
import pytesseract
from pdf2image import convert_from_path

PAGE_SEPARATOR = "\n--- PAGE {page} ---\n"


def extract_text(file_path: str, pdf_type: str) -> str:
    """
    Returns the full raw text of the PDF with page separators.
    pdf_type: "text" or "scanned"
    """
    if pdf_type == "text":
        return _extract_text_based(file_path)
    else:
        return _extract_scanned(file_path)


def _extract_text_based(file_path: str) -> str:
    """Direct text extraction using pdfplumber."""
    pages_text: List[str] = []

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            # Try normal text first
            text = page.extract_text() or ""

            # If page has tables, also try to extract them as text grids
            table_text = _extract_tables_as_text(page)
            if table_text:
                text = text + "\n" + table_text

            pages_text.append(PAGE_SEPARATOR.format(page=i) + text)

    return "\n".join(pages_text)


def _extract_tables_as_text(page) -> str:
    """Extract tables from a pdfplumber page as readable text rows."""
    result_lines = []
    try:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                if row:
                    cleaned = [str(cell).strip() if cell else "" for cell in row]
                    result_lines.append(" | ".join(cleaned))
    except Exception:
        pass
    return "\n".join(result_lines)


def _extract_scanned(file_path: str) -> str:
    """Convert each page to image and apply OCR."""
    pages_text: List[str] = []

    try:
        images = convert_from_path(file_path, dpi=300)
    except Exception as e:
        if "poppler" in str(e).lower() or "Unable to get page count" in str(e):
            raise RuntimeError(
                "Poppler is not installed or not in PATH. This is required for processing scanned PDFs.\n\n"
                "To fix this issue:\n"
                "1. Download Poppler from: http://blog.alivate.com.au/poppler-windows/\n"
                "2. Extract to: C:\\Program Files\\poppler\n"
                "3. Add C:\\Program Files\\poppler\\bin to your system PATH\n"
                "4. Restart your command prompt/terminal\n\n"
                f"Technical details: {e}"
            )
        else:
            raise RuntimeError(f"Failed to convert PDF to images: {e}")

    for i, img in enumerate(images, start=1):
        # Enhance image for better OCR
        img_gray = img.convert("L")
        ocr_text = pytesseract.image_to_string(img_gray, config="--psm 6")
        pages_text.append(PAGE_SEPARATOR.format(page=i) + ocr_text)

    return "\n".join(pages_text)


def get_page_texts(raw_text: str) -> List[str]:
    """Split raw text back into individual page strings."""
    import re
    parts = re.split(r"--- PAGE \d+ ---", raw_text)
    return [p.strip() for p in parts if p.strip()]


if __name__ == "__main__":
    import sys
    from module_01_intake import identify_pdf
    meta = identify_pdf(sys.argv[1])
    raw = extract_text(meta.file_path, meta.pdf_type)
    print(raw[:2000])
