"""
INTI - TAS (AI Agent Version) — Tool Scanner (Malware Detection)
=============================================
Static analysis + VirusTotal hash check for downloaded tools.
Runs before any community tool is registered.

Checks:
  1. Dangerous Python patterns (eval, exec, subprocess with URLs, etc.)
  2. Network exfiltration (raw sockets, base64 URLs, hardcoded IPs)
  3. Obfuscated code (base64 imports, compile/marshal)
  4. File hash against VirusTotal (if API key available)

Returns a risk score 0.0 (clean) → 1.0 (definitely malicious)
and a detailed findings report.

Risk: LOW — read-only analysis.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Patterns that indicate potentially dangerous code
DANGEROUS_PATTERNS = [
    # Code execution
    (r'\beval\s*\(', "eval() call — arbitrary code execution", 0.4),
    (r'\bexec\s*\(', "exec() call — arbitrary code execution", 0.5),
    (r'\bcompile\s*\(', "compile() call — dynamic code generation", 0.3),
    (r'\b__import__\s*\(', "__import__() — dynamic module import", 0.3),

    # System commands
    (r'\bos\.system\s*\(', "os.system() — shell command execution", 0.4),
    (r'\bos\.popen\s*\(', "os.popen() — shell command execution", 0.4),
    (r'\bsubprocess\.(call|run|Popen|check_output)\s*\(', "subprocess execution", 0.3),

    # Network (suspicious in a tool context)
    (r'\bsocket\.socket\s*\(', "Raw socket creation", 0.3),
    (r'\brequests\.(post|put|delete)\s*\(', "HTTP mutation request", 0.2),
    (r'https?://\d+\.\d+\.\d+\.\d+', "Hardcoded IP address in URL", 0.4),

    # File system attacks
    (r'\bshutil\.rmtree\s*\(', "Recursive directory deletion", 0.4),
    (r'\bos\.remove\s*\(', "File deletion", 0.2),
    (r'(\/etc\/passwd|C:\\\\Windows\\\\System32)', "System path reference", 0.5),

    # Obfuscation
    (r'\bbase64\.b64decode\s*\(', "Base64 decoding — possible obfuscation", 0.3),
    (r'\bmarshal\.loads\s*\(', "marshal.loads — bytecode deserialization", 0.5),
    (r'\bpickle\.loads\s*\(', "pickle.loads — arbitrary object deserialization", 0.5),
    (r'\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}', "Hex-encoded strings", 0.2),

    # Crypto mining
    (r'\b(stratum|mining|hashrate|coinminer)\b', "Crypto mining reference", 0.6),

    # Keylogging / screen capture
    (r'\b(pynput|keyboard\.on_press|keylogger)\b', "Keylogging library", 0.5),
    (r'\b(ctypes\.windll|win32api)\b', "Windows API access", 0.2),
]


class ToolScannerTool(Tool):
    """
    Scan Python files for malicious patterns before installing as tools.
    Returns a risk score and detailed findings report.
    """

    name = "tool_scanner"
    description = (
        "Scan Python files or directories for malicious code patterns. "
        "Used before registering community tools. Returns risk score "
        "and findings report."
    )
    category = ToolCategory.UTILITY
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("action", "One of: scan_file, scan_dir, check_hash", "string", True),
        ToolParam("path", "File or directory path to scan", "string", False),
        ToolParam("file_hash", "SHA256 hash to check against VirusTotal", "string", False),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if action == "scan_file":
            path = kwargs.get("path", "")
            if not path:
                return ToolResult(success=False, error="Missing 'path' parameter")
            return self._scan_file(Path(path))

        elif action == "scan_dir":
            path = kwargs.get("path", "")
            if not path:
                return ToolResult(success=False, error="Missing 'path' parameter")
            return self._scan_directory(Path(path))

        elif action == "check_hash":
            file_hash = kwargs.get("file_hash", "")
            path = kwargs.get("path", "")
            if not file_hash and not path:
                return ToolResult(success=False, error="Need 'file_hash' or 'path'")
            if path and not file_hash:
                file_hash = self._compute_sha256(Path(path))
            return await self._check_virustotal(file_hash)

        return ToolResult(
            success=False,
            error=f"Unknown action: {action}. Use: scan_file, scan_dir, check_hash",
        )

    # ================================================================
    # Static Analysis
    # ================================================================

    def _scan_file(self, file_path: Path) -> ToolResult:
        """Scan a single Python file for dangerous patterns."""
        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(success=False, error=f"Cannot read file: {e}")

        findings = []
        risk_score = 0.0

        for pattern, description, weight in DANGEROUS_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                count = len(matches)
                findings.append({
                    "pattern": description,
                    "count": count,
                    "weight": weight,
                    "contribution": round(weight * min(count, 3), 3),
                })
                risk_score += weight * min(count, 3)  # Cap at 3 occurrences

        # Normalize to 0-1 range
        risk_score = min(risk_score, 1.0)

        # Additional heuristic: very short files with dangerous patterns
        lines = content.count("\n") + 1
        if lines < 20 and risk_score > 0.2:
            findings.append({
                "pattern": "Suspiciously short file with dangerous code",
                "count": 1,
                "weight": 0.2,
                "contribution": 0.2,
            })
            risk_score = min(risk_score + 0.2, 1.0)

        verdict = "clean"
        if risk_score >= 0.7:
            verdict = "DANGEROUS"
        elif risk_score >= 0.4:
            verdict = "SUSPICIOUS"
        elif risk_score >= 0.15:
            verdict = "CAUTION"

        return ToolResult(
            success=True,
            output={
                "file": str(file_path),
                "risk_score": round(risk_score, 3),
                "verdict": verdict,
                "findings_count": len(findings),
                "findings": findings,
                "lines": lines,
                "sha256": self._compute_sha256(file_path),
            },
            metadata={"risk_score": round(risk_score, 3), "verdict": verdict},
        )

    def _scan_directory(self, dir_path: Path) -> ToolResult:
        """Scan all Python files in a directory."""
        if not dir_path.exists() or not dir_path.is_dir():
            return ToolResult(success=False, error=f"Directory not found: {dir_path}")

        file_results = []
        total_risk = 0.0
        files_scanned = 0

        for py_file in dir_path.rglob("*.py"):
            result = self._scan_file(py_file)
            if result.success:
                files_scanned += 1
                file_risk = result.output.get("risk_score", 0)
                total_risk = max(total_risk, file_risk)  # Worst file wins
                file_results.append({
                    "file": str(py_file.relative_to(dir_path)),
                    "risk_score": file_risk,
                    "verdict": result.output.get("verdict", "unknown"),
                    "findings_count": result.output.get("findings_count", 0),
                })

        verdict = "clean"
        if total_risk >= 0.7:
            verdict = "DANGEROUS"
        elif total_risk >= 0.4:
            verdict = "SUSPICIOUS"
        elif total_risk >= 0.15:
            verdict = "CAUTION"

        return ToolResult(
            success=True,
            output={
                "directory": str(dir_path),
                "files_scanned": files_scanned,
                "max_risk_score": round(total_risk, 3),
                "verdict": verdict,
                "file_results": sorted(
                    file_results, key=lambda x: x["risk_score"], reverse=True
                ),
            },
            metadata={"risk_score": round(total_risk, 3), "verdict": verdict},
        )

    # ================================================================
    # VirusTotal Integration
    # ================================================================

    async def _check_virustotal(self, file_hash: str) -> ToolResult:
        """Check a file hash against VirusTotal API."""
        from config.settings import load_service_env

        api_key = load_service_env("VIRUSTOTAL_API_KEY")
        if not api_key:
            return ToolResult(
                success=True,
                output={
                    "hash": file_hash,
                    "status": "skipped",
                    "reason": "VIRUSTOTAL_API_KEY not configured in .env.services",
                },
            )

        try:
            import requests

            resp = requests.get(
                f"https://www.virustotal.com/api/v3/files/{file_hash}",
                headers={"x-apikey": api_key},
                timeout=10,
            )

            if resp.status_code == 404:
                return ToolResult(
                    success=True,
                    output={
                        "hash": file_hash,
                        "status": "not_found",
                        "message": "File hash not in VirusTotal database (likely safe)",
                    },
                )

            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("attributes", {})
                stats = data.get("last_analysis_stats", {})
                malicious = stats.get("malicious", 0)
                total = sum(stats.values()) if stats else 0

                return ToolResult(
                    success=True,
                    output={
                        "hash": file_hash,
                        "status": "found",
                        "malicious_detections": malicious,
                        "total_engines": total,
                        "detection_rate": round(malicious / max(total, 1), 3),
                        "verdict": "DANGEROUS" if malicious > 3 else (
                            "SUSPICIOUS" if malicious > 0 else "clean"
                        ),
                    },
                )

            return ToolResult(
                success=False,
                error=f"VirusTotal API error: {resp.status_code}",
            )

        except ImportError:
            return ToolResult(
                success=True, output={"status": "skipped", "reason": "requests not installed"},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"VirusTotal check failed: {e}")

    # ================================================================
    # Utilities
    # ================================================================

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        try:
            sha = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            return sha.hexdigest()
        except Exception:
            return ""
