"""
Module 1: PDF Intake and Identification
Receives the PDF, determines if it is text-based or scanned,
and stores basic metadata.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional
import pdfplumber


@dataclass
class PDFMetadata:
    file_path: str
    file_name: str
    pdf_type: str  # "text" or "scanned"
    total_pages: int
    hotel_name_guess: Optional[str] = None
    contract_year_guess: Optional[str] = None
    extra_info: dict = field(default_factory=dict)


def identify_pdf(file_path: str) -> PDFMetadata:
    """
    Opens the PDF and determines its type.
    Returns a PDFMetadata object with basic info.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF not found: {file_path}")

    file_name = os.path.basename(file_path)
    pdf_type = "text"
    total_pages = 0
    hotel_name_guess = None
    contract_year_guess = None
    sample_text = ""

    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)

        # Sample first 3 pages to check for selectable text
        text_chars = 0
        for i, page in enumerate(pdf.pages[:3]):
            text = page.extract_text() or ""
            text_chars += len(text.strip())
            if i == 0:
                sample_text = text

        # If very little text is selectable, treat as scanned
        if text_chars < 50:
            pdf_type = "scanned"

    # Try to guess hotel name from filename or first page text
    hotel_name_guess = _guess_hotel_name(file_name, sample_text)
    contract_year_guess = _guess_contract_year(file_name, sample_text)

    return PDFMetadata(
        file_path=file_path,
        file_name=file_name,
        pdf_type=pdf_type,
        total_pages=total_pages,
        hotel_name_guess=hotel_name_guess,
        contract_year_guess=contract_year_guess,
    )


def _guess_hotel_name(file_name: str, sample_text: str) -> Optional[str]:
    """Attempt to extract hotel name from filename or first page text."""
    # Try filename first (strip extension, underscores, digits)
    base = os.path.splitext(file_name)[0]
    base_clean = re.sub(r"[_\-]+", " ", base).strip()
    # Remove year-like tokens
    base_clean = re.sub(r"\b(20\d{2})\b", "", base_clean).strip()
    if len(base_clean) > 3:
        return base_clean.title()

    # Try first non-empty line from sample text
    for line in sample_text.splitlines():
        line = line.strip()
        if len(line) > 5 and not re.match(r"^\d", line):
            return line[:80]

    return None


def _guess_contract_year(file_name: str, sample_text: str) -> Optional[str]:
    """Try to find a 4-digit year in the filename or first-page text."""
    combined = file_name + " " + sample_text
    match = re.search(r"\b(20\d{2})\b", combined)
    if match:
        return match.group(1)
    return None


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    meta = identify_pdf(path)
    print(vars(meta))
