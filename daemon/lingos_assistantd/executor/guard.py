"""executor/guard.py —— 黑名单/敏感路径/决策引擎（PRD 3.3、5.4、10.1）。

设计原则：
- 默认拒绝（未知工具 → DENY）
- 黑名单命令命中 → DENY 不可确认（不提供确认按钮）
- 正则 + shlex 解析双重检测，防单层绕过
- 敏感路径（~/.ssh、~/.config、/etc 等）文件工具 → DENY
- 一切写/执行类工具 → CONFIRM（需用户逐条确认）
- system_info 只读 → AUTO_ALLOW
"""

from __future__ import annotations

import difflib
import os
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

MAX_PREVIEW_DIFF_LINES = 200


class Decision(str, Enum):
    DENY = "deny"  # 不可确认，直接拒绝
    CONFIRM = "confirm"  # 需用户确认
    AUTO_ALLOW = "auto_allow"  # 只读安全操作，自动放行


@dataclass
class GuardResult:
    decision: Decision
    reason: str = ""
    risk: str = "low"  # low / medium / high
    preview: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ================================================================ 命令黑名单（正则层）
# 命中任意一条 → DENY(reason=<name>)，不可确认（PRD 5.4）

_DENY_REGEX_RULES: list[tuple[str, re.Pattern[str]]] = [
    # rm -rf / 变体（含 -fr、-r -f、多个短参组合、目标 / ~ $HOME）
    (
        "rm_root",
        re.compile(
            r"\brm\s+[^|;&<>]*(?:\s-\w*r\w*\s*|\s-\w*f\w*){1,}[^|;&<>]*\s(--no-preserve-root|/(\s|$)|~(\s|$)|\$HOME(\s|$))"
        ),
    ),
    ("no_preserve_root", re.compile(r"--no-preserve-root")),
    ("mkfs", re.compile(r"\bmkfs(\.\w+)?\b")),
    ("dd_to_device", re.compile(r"\bdd\b[^|;&]*\bof=/dev/\w+")),
    ("fork_bomb", re.compile(r":\s*\(\s*\)\s*\{[^}]*\}\s*;\s*:")),
    ("chmod_777_root", re.compile(r"\bchmod\s+[^|;&]*\s777\s+(/|~|\$HOME)(\s|$)")),
    (
        "shutdown_family",
        re.compile(
            r"(^|[;&|(]\s*|\b)(shutdown|reboot|halt|poweroff|systemctl\s+(reboot|poweroff|halt|suspend))\b"
        ),
    ),
    ("init_runlevel", re.compile(r"\binit\s+[06]\b")),
    ("write_block_device", re.compile(r"[>]{1,2}\s*/dev/(sd|nvme|vd|hd)\w+")),
    ("firewall", re.compile(r"\b(iptables|ip6tables|ufw|nft|firewalld)\b")),
    ("privilege_escalation", re.compile(r"(^|[;&|(]\s*)\b(sudo|su|pkexec|doas|sudoedit)\b")),
    ("net_pipe_shell", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|fi|k)?sh\b")),
    (
        "base64_pipe_shell",
        re.compile(r"\b(base64(\s+-d)?|openssl\s+enc\s+-d[^|]*)\b[^|]*\|\s*(ba|z|fi|k)?sh\b"),
    ),
    ("echo_pipe_shell", re.compile(r"\becho\b[^|]*\|\s*(sudo\s+)?(ba|z|fi|k)?sh\b")),
    (
        "shell_write_protected",
        re.compile(r"(>|>>)\s*(/etc/|/boot/|/usr/|/sys/|/proc/sys/|/dev/sd|/dev/nvme)"),
    ),
    (
        "mutate_protected",
        re.compile(
            r"\b(rm|mv|chmod|chown|chattr|tee|truncate|shred|ln|install)\b[^|;&]*(\s|=)(/etc/|/boot/|/usr/|~/\.ssh|~/\.gnupg|~/\.config/|\.ssh/|\.gnupg/)"
        ),
    ),
    (
        "protected_ssh_config",
        re.compile(r"\b(rm|mv|chmod|chown|tee|cat\s*>|>)\b[^|;&]*~/\.(ssh|gnupg)"),
    ),
    ("overwrite_shadow", re.compile(r"[>]{1,2}\s*/etc/(shadow|passwd|sudoers|fstab)\b")),
    (
        "gitforce_root",
        re.compile(r"\bgit\s+push\s+[^|;&]*--force\b"),
    ),  # 防误伤之外的高危示例，标记为 deny 由 policy 决定
    ("crontab_write", re.compile(r"\bcrontab\s+[^|;&]*\b(r|-e)\b")),
    ("chown_recursive_root", re.compile(r"\bchown\s+[^|;&]*-R[^|;&]*\s+(/|~|\$HOME)(\s|$)")),
]

# ================================================================ shlex 层

_WRITE_CMDS = {"rm", "mv", "chmod", "chown", "chattr", "tee", "truncate", "shred", "ln", "install"}
_PROTECTED_PREFIXES = (
    "/etc",
    "/boot",
    "/usr",
    "/sys",
    "/proc/sys",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
)
_HOME_PROTECTED = (".ssh", ".gnupg", ".config", ".local/share/keyrings")
_SHELL_NAMES = {"sh", "bash", "zsh", "fish", "ksh", "dash"}
_NET_FETCHERS = {"curl", "wget", "echo", "base64", "openssl"}
_SPLIT_RE = re.compile(r"[|;&]+")


def _expand_target(t: str) -> Path:
    if t.startswith("~"):
        return Path(os.path.expanduser(t)).resolve()
    if t.startswith("$HOME"):
        return Path(os.path.expandvars(t)).resolve()
    return Path(t).resolve()


def _norm_posix(s: str) -> str:
    """统一为 posix 形式；Windows 盘符前缀去掉，便于与 /etc 等绝对前缀比较。"""
    s = s.replace("\\", "/")
    if len(s) > 2 and s[1] == ":":
        s = s[2:]
    return s.rstrip("/") or "/"


def _is_protected_path(p: Path, raw: str | None = None) -> bool:
    """检查原始输入与解析后的路径是否落在保护目录（跨平台：同时比较两者）。"""
    home = _norm_posix(str(Path.home()))
    candidates: list[str] = []
    if raw:
        candidates.append(_norm_posix(os.path.expandvars(os.path.expanduser(raw))))
    candidates.append(_norm_posix(str(p)))
    for s in candidates:
        for pref in _PROTECTED_PREFIXES:
            if s == pref or s.startswith(pref + "/"):
                return True
        for sub in _HOME_PROTECTED:
            hp = f"{home}/{sub}"
            if s == hp or s.startswith(hp + "/"):
                return True
    return False


def _deny_shlex(command: str) -> str | None:
    """shlex 解析层黑名单检测。返回命中规则名或 None。"""
    try:
        tokens = shlex.split(command)
    except ValueError:
        # 引号不闭合等畸形输入 → 交给正则层；均未命中时按 CONFIRM+high 处理
        return None
    if not tokens:
        return None

    # 按管道/分隔符切分为子命令
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in ("|", ";", "&&", "||", "&"):
            segments.append([])
        else:
            segments[-1].append(tok)

    for seg in segments:
        if not seg:
            continue
        head = Path(seg[0]).name
        # 提权前缀
        if head in ("sudo", "su", "pkexec", "doas"):
            return "privilege_escalation"
        # 关机/格式化类
        if head in (
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "mkfs",
            "mkfs.ext4",
            "mkfs.btrfs",
            "mkfs.xfs",
            "mkfs.vfat",
        ) or head.startswith("mkfs."):
            return (
                "shutdown_family" if head in ("shutdown", "reboot", "halt", "poweroff") else "mkfs"
            )
        # rm -rf 保护目标
        if head == "rm":
            flags = [t for t in seg[1:] if t.startswith("-") and not t.startswith("--")]
            joined = "".join(flags)
            long_r = "--recursive" in seg or "--force" in seg
            has_r = "r" in joined or long_r
            has_f = "f" in joined or long_r
            if "--no-preserve-root" in seg:
                return "no_preserve_root"
            if has_r and has_f:
                for t in seg[1:]:
                    if t.startswith("-"):
                        continue
                    if (
                        t in ("/", "~", "$HOME", "/*")
                        or str(_expand_target(t)) == "/"
                        or _is_protected_path(_expand_target(t), raw=t)
                    ):
                        return "rm_root"
        # chmod -R 777 /
        if head == "chmod" and ("-R" in seg or "--recursive" in seg):
            if "777" in seg:
                for t in seg[seg.index("777") + 1 :]:
                    if t in ("/", "~", "$HOME") or _is_protected_path(_expand_target(t), raw=t):
                        return "chmod_777_root"
        # dd of=/dev/*
        if head == "dd":
            for t in seg:
                if t.startswith("of=/dev/"):
                    return "dd_to_device"
        # 管道到 shell（来自网络/echo/base64）
        if head in _NET_FETCHERS and len(segments) > 1:
            for other in segments:
                if other and Path(other[0]).name in _SHELL_NAMES:
                    return "net_pipe_shell"
        # 写类命令触碰保护路径
        if head in _WRITE_CMDS:
            for t in seg[1:]:
                if t.startswith("-"):
                    continue
                if _is_protected_path(_expand_target(t), raw=t):
                    return "mutate_protected"
        # cp 的目标（最后一个参数）在保护路径
        if head == "cp" and len(seg) >= 3:
            dest = seg[-1]
            if not dest.startswith("-") and _is_protected_path(_expand_target(dest), raw=dest):
                return "mutate_protected"
    return None


# ================================================================ 敏感路径（文件工具）

_SENSITIVE_NAME_PATTERNS = [
    re.compile(r".*\.token$", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r"id_rsa.*", re.IGNORECASE),
    re.compile(r".*_rsa$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r".*\.keystore$", re.IGNORECASE),
    re.compile(r"^authorized_keys$", re.IGNORECASE),
    re.compile(r"^known_hosts$", re.IGNORECASE),
]

_KEYRING_DIR = ".local/share/keyrings"


def is_sensitive_path(path: str) -> bool:
    """PRD 5.4 敏感路径黑名单：~/.ssh、~/.gnupg、~/.config、keyrings、/etc、/boot、*.token、*.pem、id_rsa*。"""
    p = _expand_target(path)
    if _is_protected_path(p, raw=path):
        return True
    name = p.name
    for pat in _SENSITIVE_NAME_PATTERNS:
        if pat.fullmatch(name):
            return True
    s = _norm_posix(str(p))
    return any(seg in (".ssh", ".gnupg", "keyrings") for seg in s.split("/"))


# ================================================================ gsettings 白名单

GSETTINGS_WHITELIST: set[tuple[str, str]] = {
    ("org.gnome.desktop.interface", "color-scheme"),
    ("org.gnome.desktop.interface", "gtk-theme"),
    ("org.gnome.desktop.interface", "icon-theme"),
    ("org.gnome.desktop.interface", "enable-hot-corners"),
    ("org.gnome.desktop.interface", "clock-format"),
    ("org.gnome.desktop.interface", "show-battery-percentage"),
    ("org.gnome.desktop.background", "picture-uri"),
    ("org.gnome.desktop.background", "picture-uri-dark"),
    ("org.gnome.desktop.background", "picture-options"),
    ("org.gnome.desktop.peripherals.mouse", "natural-scroll"),
    ("org.gnome.desktop.peripherals.touchpad", "tap-to-click"),
    ("org.gnome.desktop.wm.preferences", "button-layout"),
    ("org.gnome.mutter", "center-new-windows"),
    ("org.gnome.system.locale", "region"),
}


# ================================================================ 风险分级

_HIGH_RISK = re.compile(
    r"\b(rm|dd|mkfs|chmod|chown|shred|mv|kill|pkill|killall|truncate)\b"
    r"|\bapt(-get)?\s+(remove|purge|autoremove)\b|\bpip3?\s+uninstall\b"
    r"|\bgit\s+(reset\s+--hard|clean\s+-fd|checkout\s+--\s)\b|[>]{2}"
)
_MEDIUM_RISK = re.compile(
    r"\bapt(-get)?\s+install\b|\bpip3?\s+install\b|\b(curl|wget)\b|\bsystemctl\b"
    r"|\bgsettings\b|\bgit\s+(push|pull)\b|\bsnap\b|\bflatpak\b|\btee\b"
)
_LOW_RISK = re.compile(
    r"^(ls|cat|df|du|head|tail|echo|find|grep|pwd|whoami|uname|free|ps|date|wc|sort|uniq|file|stat|which|id|uptime|lscpu|lsblk|ip\s+addr|ifconfig)\b"
)


def classify_risk(command: str) -> str:
    if _HIGH_RISK.search(command):
        return "high"
    if _MEDIUM_RISK.search(command):
        return "medium"
    return "low"


# ================================================================ 决策入口（PRD 3.3 伪代码的实现）


def evaluate_tool_call(tool: str, args: dict[str, Any]) -> GuardResult:
    if tool == "shell":
        command = str(args.get("command", ""))
        name = _deny_regex(command)
        if name is None:
            name = _deny_shlex(command)
        if name:
            return GuardResult(Decision.DENY, reason=name, risk="high", preview=command)
        return GuardResult(Decision.CONFIRM, risk=classify_risk(command), preview=command)

    if tool in ("file_write", "file_delete"):
        path = str(args.get("path", ""))
        if is_sensitive_path(path):
            return GuardResult(Decision.DENY, reason="sensitive_path", risk="high", preview=path)
        if tool == "file_write":
            preview = _diff_preview(path, str(args.get("content", "")))
            return GuardResult(Decision.CONFIRM, risk="medium", preview=preview)
        return GuardResult(Decision.CONFIRM, risk="high", preview=f"删除文件（移入回收站）: {path}")

    if tool == "file_read":
        path = str(args.get("path", ""))
        if is_sensitive_path(path):
            return GuardResult(Decision.DENY, reason="sensitive_path", risk="high", preview=path)
        return GuardResult(Decision.CONFIRM, risk="low", preview=path)

    if tool == "gsettings_set":
        schema = str(args.get("schema", ""))
        key = str(args.get("key", ""))
        if (schema, key) not in GSETTINGS_WHITELIST:
            return GuardResult(
                Decision.DENY, reason="not_whitelisted", risk="high", preview=f"{schema} {key}"
            )
        return GuardResult(
            Decision.CONFIRM,
            risk="low",
            preview=f"{schema}.{key}: 当前值 → {args.get('value')!r}",
        )

    if tool == "system_info":
        return GuardResult(
            Decision.AUTO_ALLOW, reason="readonly", risk="low", preview="读取系统摘要"
        )

    return GuardResult(Decision.DENY, reason="unknown_tool", risk="high")


def _deny_regex(command: str) -> str | None:
    for name, pat in _DENY_REGEX_RULES:
        if pat.search(command):
            return name
    return None


def _diff_preview(path: str, new_content: str) -> str:
    """file_write 的 diff 预览（PRD 3.4：展示路径 + diff 预览）。"""
    p = Path(os.path.expanduser(path))
    old_lines: list[str] = []
    if p.exists():
        try:
            old_lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            old_lines = [f"（无法读取原文件：{path}）\n"]
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{p.name}",
        tofile=f"b/{p.name}",
        n=2,
    )
    text = "".join(diff)
    if len(text.splitlines()) > MAX_PREVIEW_DIFF_LINES:
        text = "\n".join(text.splitlines()[:MAX_PREVIEW_DIFF_LINES]) + "\n…（截断）"
    if not text:
        text = "（内容无变化）"
    return f"写入文件: {p}\n{text}"
