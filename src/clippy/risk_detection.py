from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)

RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "encoded or obfuscated PowerShell command",
        re.compile(
            r"\b(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*"
            r"(?:-(?:e|en|enc|enco|encodedcommand)\b|FromBase64String\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "download piped directly into a command interpreter",
        re.compile(
            r"\b(?:curl|wget|iwr|Invoke-WebRequest)\b[^\r\n|]{0,1000}\|\s*"
            r"(?:sh|bash|zsh|cmd|powershell|pwsh|iex|Invoke-Expression)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PowerShell download-and-execute behavior",
        re.compile(
            r"(?:\b(?:iex|Invoke-Expression)\b[^\r\n]{0,1000}"
            r"(?:DownloadString|Invoke-WebRequest|\biwr\b)|"
            r"(?:DownloadString|Invoke-WebRequest|\biwr\b)[^\r\n]{0,1000}"
            r"\b(?:iex|Invoke-Expression)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "Windows security controls are being disabled",
        re.compile(
            r"(?:Set-MpPreference[^\r\n]*-DisableRealtimeMonitoring\s+\$?true|"
            r"netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential-dumping behavior",
        re.compile(
            r"\b(?:mimikatz|sekurlsa::logonpasswords|procdump(?:\.exe)?[^\r\n]*\blsass|"
            r"secretsdump(?:\.py)?|reg\s+save\s+HKLM\\(?:SAM|SECURITY|SYSTEM))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system-wide destructive deletion command",
        re.compile(
            r"(?:^|[;&|]\s*)(?:sudo\s+)?rm\s+-[a-z]*r[a-z]*f[a-z]*\s+"
            r"(?:/|/\*|~|\$HOME)(?:\s|$)|"
            r"(?:^|[;&|]\s*)del\s+/[a-z]*s[a-z]*\s+/[a-z]*q[a-z]*\s+[A-Za-z]:\\",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "disk erase or format command",
        re.compile(
            r"(?:^|[;&|]\s*)(?:format\s+[A-Za-z]:|diskpart[^\r\n]*(?:clean|format)|"
            r"dd\s+[^\r\n]*\bof=/dev/(?:sd|nvme|hd))",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "suspicious Windows downloader utility",
        re.compile(
            r"\b(?:certutil(?:\.exe)?\s+-urlcache|bitsadmin(?:\.exe)?\s+/transfer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "script persistence command",
        re.compile(
            r"\b(?:schtasks(?:\.exe)?\s+/create|reg(?:\.exe)?\s+add\s+"
            r"[^\r\n]*(?:\\Run|\\RunOnce))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "executable script URI",
        re.compile(r"^\s*(?:javascript|data):", re.IGNORECASE),
    ),
)

SHORTENER_HOSTS = frozenset(
    {
        "bit.ly",
        "cutt.ly",
        "is.gd",
        "rb.gy",
        "rebrand.ly",
        "shorturl.at",
        "tiny.cc",
        "tinyurl.com",
        "t.co",
    }
)

RISKY_DOWNLOAD_SUFFIXES = (
    ".appinstaller",
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".hta",
    ".iso",
    ".js",
    ".lnk",
    ".msi",
    ".ps1",
    ".scr",
    ".vbs",
)


def detect_risk(text: str, custom_patterns: list[str]) -> str | None:
    for reason, pattern in RISK_RULES:
        if pattern.search(text):
            return reason

    urls = [_clean_url(match.group(0)) for match in URL_PATTERN.finditer(text)]
    for url in urls:
        reason = _risky_url_reason(url)
        if reason:
            return reason

    return _match_custom_sources(text, urls, custom_patterns)


def _risky_url_reason(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return "URL cannot be safely parsed"
    if not host:
        return "URL has no valid host"
    if parsed.username or parsed.password:
        return "URL hides its destination behind user-info syntax"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "URL uses a raw IP address"
    if any(label.startswith("xn--") for label in host.split(".")):
        return "URL uses an internationalized punycode host"
    if host in SHORTENER_HOSTS:
        return "URL uses a link-shortening service"
    path = parsed.path.casefold()
    if path.endswith(RISKY_DOWNLOAD_SUFFIXES):
        return "URL points directly to an executable or script download"
    return None


def _match_custom_sources(text: str, urls: list[str], patterns: list[str]) -> str | None:
    folded_text = text.casefold()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern:
            continue
        folded_pattern = pattern.casefold()
        try:
            if folded_pattern.startswith("re:"):
                if re.search(pattern[3:], text, re.IGNORECASE | re.MULTILINE):
                    return f"matched custom risk regex: {pattern[3:]}"
                continue
            if folded_pattern.startswith(("keyword:", "source:")):
                marker = pattern.split(":", 1)[1].strip()
                if marker and marker.casefold() in folded_text:
                    return f"matched custom risky source: {marker}"
                continue
            if folded_pattern.startswith("domain:"):
                domain = pattern.split(":", 1)[1].strip()
                if _urls_match_domain(urls, domain):
                    return f"matched custom risky domain: {domain}"
                continue
            if folded_pattern.startswith("url:"):
                prefix = pattern.split(":", 1)[1].strip()
                if prefix and any(url.casefold().startswith(prefix.casefold()) for url in urls):
                    return f"matched custom risky URL: {prefix}"
                continue
            if "://" in pattern:
                if any(url.casefold().startswith(folded_pattern) for url in urls):
                    return f"matched custom risky URL: {pattern}"
                continue
            if _urls_match_domain(urls, pattern):
                return f"matched custom risky domain: {pattern}"
            if folded_pattern in folded_text:
                return f"matched custom risky source: {pattern}"
        except (re.error, ValueError):
            continue
    return None


def _urls_match_domain(urls: list[str], domain: str) -> bool:
    expected = domain.casefold().strip().strip(".")
    if not expected:
        return False
    for url in urls:
        try:
            host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        except ValueError:
            continue
        if host == expected or host.endswith(f".{expected}"):
            return True
    return False


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}")
