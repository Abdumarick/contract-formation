"""
Module 3: Text Cleaning and Normalization
Cleans raw extracted text without changing meanings.
Removes noise like repeated headers/footers, page numbers,
repeated emails, and normalises whitespace.
"""

import re
from collections import Counter
from typing import List


def clean_text(raw_text: str) -> str:
    """Full cleaning pipeline. Returns clean, readable text."""
    text = raw_text

    text = _remove_page_numbers(text)
    text = _remove_repeated_lines(text)
    text = _remove_emails(text)
    text = _remove_urls(text)
    text = _fix_line_breaks(text)
    text = _normalize_whitespace(text)
    text = _fix_common_ocr_errors(text)

    return text.strip()


def _remove_page_numbers(text: str) -> str:
    """Remove standalone page number lines like 'Page 3 of 12' or just '3'."""
    # "Page X of Y" patterns
    text = re.sub(r"(?im)^\s*page\s+\d+\s*(of\s+\d+)?\s*$", "", text)
    # Standalone digit lines (likely page numbers)
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)
    return text


def _remove_repeated_lines(text: str, threshold: int = 3) -> str:
    """
    Detect lines that appear more than `threshold` times across the document
    and remove them (typical headers/footers).
    """
    lines = text.splitlines()
    line_counts = Counter(line.strip() for line in lines if line.strip())

    repeated = {line for line, count in line_counts.items() if count >= threshold and len(line) > 5}

    filtered = [line for line in lines if line.strip() not in repeated]
    return "\n".join(filtered)


def _remove_emails(text: str) -> str:
    """Remove email addresses that clutter the text."""
    return re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", text)


def _remove_urls(text: str) -> str:
    """Remove URLs."""
    return re.sub(r"https?://\S+|www\.\S+", "", text)


def _fix_line_breaks(text: str) -> str:
    """
    Normalize line breaks:
    - Preserve paragraph breaks (double newlines)
    - Join lines that look like continuation of a sentence
    - Preserve table row structure (lines with pipe separators)
    """
    lines = text.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Preserve page separators
        if re.match(r"--- PAGE \d+ ---", line.strip()):
            result.append(line)
            i += 1
            continue

        # Preserve table-like lines
        if "|" in line:
            result.append(line)
            i += 1
            continue

        # Empty line = paragraph break, preserve it
        if not line.strip():
            result.append("")
            i += 1
            continue

        # Check if next line looks like a continuation (no caps start, no bullet)
        if (i + 1 < len(lines)
                and lines[i + 1].strip()
                and not re.match(r"^[A-Z0-9•\-\*]", lines[i + 1].strip())
                and not re.match(r"--- PAGE", lines[i + 1].strip())
                and not line.strip().endswith((".", ":", ";"))):
            # Merge continuation line
            result.append(line.rstrip() + " " + lines[i + 1].strip())
            i += 2
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple blank lines into max two, and strip trailing spaces."""
    # Replace 3+ blank lines with 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing spaces per line
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines)


def _fix_common_ocr_errors(text: str) -> str:
    """Fix common OCR misreadings in hotel contract context."""
    replacements = {
        r"\bl\b(?=\d)": "1",          # lowercase L before digit → 1
        r"(?<=\d)O(?=\d)": "0",       # O between digits → 0
        r"\bS\b(?=\d)": "5",          # S before digit → 5
        r"€": "EUR",                  # normalise euro sign
        r"\$": "USD",
        r"£": "GBP",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


if __name__ == "__main__":
    import sys
    sample = open(sys.argv[1]).read() if len(sys.argv) > 1 else "Test\nTest\nPage 1\nHello world"
    print(clean_text(sample))
