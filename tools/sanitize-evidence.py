#!/usr/bin/env python3
"""Sanitize private GL-E5800 evidence before publishing.

Conservative redaction: IP addresses, MAC addresses, long subscriber/device
identifiers, SSIDs/keys/password-like fields. The source directory is never
modified. SHA256SUMS from the private capture is intentionally not copied.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import re
import shutil
import tempfile
from pathlib import Path

MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
IPV6_CANDIDATE = re.compile(
    r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:/\d{1,3})?(?![0-9a-f:])"
)
LONG_ID = re.compile(r"(?<!\d)\d{14,22}(?!\d)")
SENSITIVE_FIELD = re.compile(
    r'''(?ix)
    (?P<prefix>
      "?\b(?:password|passwd|secret|token|access_token|refresh_token|api_key|
      private_key|private-key|key|psk|authorization|ssid|imei|imsi|iccid|msisdn)\b"?
      \s*[:=]\s*
    )
    (?P<value>
      "(?:\\.|[^"\\])*" |
      '(?:\\.|[^'\\])*' |
      [^\r\n,}\]]+?(?=\s+[A-Za-z_][\w-]*\s*[:=]|[,}\]\r\n]|$)
    )
    '''
)


def _redact_ipv6(match: re.Match[str]) -> str:
    candidate = match.group(0)
    try:
        ipaddress.ip_interface(candidate)
    except ValueError:
        return candidate
    return "[IPv6]"


def sanitize(text: str) -> str:
    had_final_newline = text.endswith("\n")

    def redact_field(match: re.Match[str]) -> str:
        value = match.group("value")
        # The unquoted branch stops before `]`. Preserve our own placeholder
        # rather than matching `[REDACTED` and appending another closing bracket
        # on every sanitizer pass.
        if (
            value.strip() == "[REDACTED"
            and match.end() < len(match.string)
            and match.string[match.end()] == "]"
        ):
            return match.group(0)
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            replacement = f"{value[0]}[REDACTED]{value[0]}"
        else:
            replacement = "[REDACTED]"
        return match.group("prefix") + replacement

    text = SENSITIVE_FIELD.sub(redact_field, text)
    text = MAC.sub("[MAC]", text)
    text = IPV4.sub("[IPv4]", text)
    text = IPV6_CANDIDATE.sub(_redact_ipv6, text)
    text = LONG_ID.sub("[LONG_ID]", text)
    text = "\n".join(line.rstrip(" \t\r") for line in text.splitlines())
    if had_final_newline:
        text += "\n"
    return text


def has_symlink_component(path: Path) -> bool:
    """Return True when path or any existing ancestor is a symlink."""
    absolute = path.absolute()
    return any(component.is_symlink() for component in (absolute, *absolute.parents))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    if has_symlink_component(args.source) or not args.source.is_dir():
        parser.error(f"source is not a directory: {args.source}")
    source = args.source.resolve()
    destination = args.destination.resolve()
    if destination == source or source in destination.parents:
        parser.error("destination must be outside the source directory")
    if args.destination.exists() or has_symlink_component(args.destination):
        parser.error("destination must be new and must not traverse symlinks")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.tmp-",
            dir=destination.parent,
        )
    )

    try:
        manifest: list[str] = []
        for src in sorted(source.glob("*.txt")):
            if src.name == "SHA256SUMS":
                continue
            if src.is_symlink() or not src.is_file():
                raise RuntimeError(f"refusing non-regular source file: {src.name}")
            clean = sanitize(src.read_text(encoding="utf-8", errors="replace"))
            dst = tmp / src.name
            dst.write_text(clean, encoding="utf-8")
            digest = hashlib.sha256(clean.encode()).hexdigest()
            manifest.append(f"{digest}  {src.name}")

        (tmp / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
        os.replace(tmp, destination)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    print(f"Sanitized {len(manifest)} files into {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
