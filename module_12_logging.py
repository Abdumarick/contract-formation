"""
Module 12: Logging and Audit Trail (v2 — Fully Automated)

Records what was extracted, what was guessed, what was skipped,
and why files were rejected. Critical for batch processing of hundreds of PDFs.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


LOG_EXTRACTED  = "EXTRACTED"
LOG_GUESSED    = "GUESSED"
LOG_SKIPPED    = "SKIPPED"
LOG_WARNING    = "WARNING"
LOG_ERROR      = "ERROR"
LOG_REJECTED   = "REJECTED"
LOG_INFO       = "INFO"


@dataclass
class AuditEntry:
    timestamp: str
    level: str
    module: str
    field: Optional[str]
    value: Any
    note: str

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "level":     self.level,
            "module":    self.module,
            "field":     self.field,
            "value":     str(self.value)[:200],
            "note":      self.note,
        }


class AuditLogger:
    def __init__(self, hotel_name: str = "unknown", log_dir: str = "."):
        self.hotel_name = hotel_name
        self.log_dir    = log_dir
        self.entries: List[AuditEntry] = []
        self._setup_logger()

    def _setup_logger(self):
        self._logger = logging.getLogger(f"hotel_parser.{self.hotel_name}")
        if not self._logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"
            ))
            self._logger.addHandler(h)
        self._logger.setLevel(logging.DEBUG)

    def _add(self, level: str, module: str, field: Optional[str], value: Any, note: str):
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            level=level, module=module, field=field, value=value, note=note,
        )
        self.entries.append(entry)
        fn = {
            LOG_ERROR:    self._logger.error,
            LOG_REJECTED: self._logger.error,
            LOG_WARNING:  self._logger.warning,
            LOG_SKIPPED:  self._logger.info,
            LOG_GUESSED:  self._logger.info,
            LOG_EXTRACTED:self._logger.debug,
            LOG_INFO:     self._logger.info,
        }.get(level, self._logger.info)
        fn(f"[{module}] {field or ''}: {note} | {str(value)[:80]}")

    # ── Convenience methods ───────────────────────────────────────────────────
    def extracted(self, module, field, value, note=""):
        self._add(LOG_EXTRACTED, module, field, value, note or "Extracted from source")

    def guessed(self, module, field, value, note=""):
        self._add(LOG_GUESSED, module, field, value, note or "Inferred/assumed")

    def skipped(self, module, field, value, reason=""):
        self._add(LOG_SKIPPED, module, field, value, reason or "Skipped — unsupported")

    def warning(self, module, note, field=None, value=""):
        self._add(LOG_WARNING, module, field, value, note)

    def error(self, module, note, field=None, value=""):
        self._add(LOG_ERROR, module, field, value, note)

    def rejected(self, module, reason, value=""):
        self._add(LOG_REJECTED, module, "FILE_REJECTED", value, reason)

    def info(self, module, note):
        self._add(LOG_INFO, module, None, "", note)

    # ── Export ────────────────────────────────────────────────────────────────
    def save_json(self, filename_override: Optional[str] = None) -> str:
        os.makedirs(self.log_dir, exist_ok=True)
        if filename_override:
            path = os.path.join(self.log_dir, filename_override)
        else:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = self.hotel_name.replace(" ", "_")[:40]
            path = os.path.join(self.log_dir, f"audit_{safe}_{ts}.json")

        data = {
            "hotel_name":    self.hotel_name,
            "generated":     datetime.now().isoformat(),
            "total_entries": len(self.entries),
            "summary":       self._build_summary(),
            "entries":       [e.to_dict() for e in self.entries],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Audit JSON saved : {path}")
        return path

    def save_txt(self, filename_override: Optional[str] = None) -> str:
        os.makedirs(self.log_dir, exist_ok=True)
        if filename_override:
            path = os.path.join(self.log_dir, filename_override)
        else:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = self.hotel_name.replace(" ", "_")[:40]
            path = os.path.join(self.log_dir, f"audit_{safe}_{ts}.txt")

        with open(path, "w", encoding="utf-8") as f:
            f.write(f"AUDIT TRAIL — {self.hotel_name}\n")
            f.write(f"Generated : {datetime.now()}\n")
            f.write("=" * 90 + "\n\n")
            for e in self.entries:
                f.write(
                    f"[{e.timestamp}] {e.level:<10} | {e.module:<25} | "
                    f"{(e.field or ''):<22} | {e.note}\n"
                )
            f.write("\n" + "=" * 90 + "\n")
            f.write(self.print_summary(return_str=True))

        print(f"Audit TXT saved  : {path}")
        return path

    def _build_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.entries:
            counts[e.level] = counts.get(e.level, 0) + 1
        return counts

    def print_summary(self, return_str=False) -> str:
        counts = self._build_summary()
        lines  = ["\n── Audit Summary ──────────────────────"]
        for level, count in sorted(counts.items()):
            lines.append(f"  {level:<14}: {count}")
        text = "\n".join(lines)
        if not return_str:
            print(text)
        return text


# ── Module-level singleton ────────────────────────────────────────────────────
_current_logger: Optional[AuditLogger] = None


def init_logger(hotel_name: str, log_dir: str = ".") -> AuditLogger:
    global _current_logger
    _current_logger = AuditLogger(hotel_name=hotel_name, log_dir=log_dir)
    return _current_logger


def get_logger() -> AuditLogger:
    global _current_logger
    if _current_logger is None:
        _current_logger = AuditLogger()
    return _current_logger
