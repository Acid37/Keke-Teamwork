"""Shell 命令风险分级。

将命令分为三个风险级别：
- read_only:  可安全自动放行（git status, ls 等）
- normal:     普通命令，走标准审批流程
- dangerous:  高危命令，即使 YOLO 模式也强制审批
"""

from __future__ import annotations

import re
import shlex
from enum import Enum


class CommandRisk(str, Enum):
    """Shell 命令的风险级别。"""
    read_only = "read_only"
    normal = "normal"
    dangerous = "dangerous"


# ─── 只读命令白名单 ───

# 仅读取信息且无副作用的命令。
# 匹配命令的第一个 token（去除环境变量前缀后）。
_READ_ONLY_COMMANDS: frozenset[str] = frozenset({
    "ls", "dir", "cat", "head", "tail", "less", "more",
    "pwd", "echo", "whoami", "hostname", "date", "uptime",
    "git",  # git 本身安全，具体子命令在下方检查
    "grep", "rg", "find", "which", "where", "whereis",
    "python", "python3", "node",  # 仅 --version 时只读
    "npm",  # 仅 list/info 时只读
})

# git 只读子命令
_GIT_READ_ONLY_SUB: frozenset[str] = frozenset({
    "status", "log", "diff", "show", "branch", "tag",
    "remote", "ls-files", "ls-tree", "blame", "shortlog",
    "describe", "rev-parse", "config", "--version",
})

# npm 只读子命令
_NPM_READ_ONLY_SUB: frozenset[str] = frozenset({
    "list", "ls", "outdated", "view", "info", "--version",
})

# ─── 高危命令模式 ───

# 可能造成不可逆损害的命令。
# 以正则子串匹配方式检查完整命令字符串。
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    # 递归强制删除
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*\s+)?-?[a-z]*r[a-z]*\s+", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s", re.IGNORECASE),  # Windows 递归 rmdir
    re.compile(r"\bdel\s+/[a-z]*s", re.IGNORECASE),  # Windows 递归 del
    # 磁盘格式化 / 分区
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\b.*\bof=", re.IGNORECASE),
    # 关机 / 重启
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bhalt\b", re.IGNORECASE),
    re.compile(r"\bpoweroff\b", re.IGNORECASE),
    # 强制 git push / reset --hard / clean
    re.compile(r"\bgit\s+push\s+.*--force", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+-f\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-[a-z]*[a-z]*x", re.IGNORECASE),
    # chmod 777
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),
    # 杀死所有进程
    re.compile(r"\bkillall\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\s+-1\b", re.IGNORECASE),
    # curl/wget 管道到 shell
    re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE),
    # 包管理器卸载
    re.compile(r"\bapt(-get)?\s+(remove|purge|autoremove)\b", re.IGNORECASE),
    re.compile(r"\byum\s+remove\b", re.IGNORECASE),
    re.compile(r"\bpip\s+uninstall\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+uninstall\b", re.IGNORECASE),
]


def _strip_env_vars(command: str) -> str:
    """去除开头的环境变量赋值（FOO=bar baz=qux cmd ...）。"""
    tokens = command.strip().split()
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    return " ".join(tokens)


def _get_base_command(command: str) -> tuple[str, list[str]]:
    """提取基础命令及其参数。

    返回 (base_command, args_list)。处理环境变量前缀和 sudo 前缀。
    """
    stripped = _strip_env_vars(command.strip())
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # Windows 路径反斜杠回退
        tokens = stripped.split()

    # 去除 sudo 前缀
    if tokens and tokens[0] == "sudo":
        tokens = tokens[1:]

    if not tokens:
        return "", []

    return tokens[0], tokens[1:]


def classify_command(command: str) -> CommandRisk:
    """将 shell 命令分类为风险级别。

    参数：
        command: 完整的 shell 命令字符串。

    返回：
        CommandRisk.read_only、CommandRisk.normal 或 CommandRisk.dangerous
    """
    if not command or not command.strip():
        return CommandRisk.normal

    # 先检查高危模式——优先级最高
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return CommandRisk.dangerous

    base, args = _get_base_command(command)
    if not base:
        return CommandRisk.normal

    base_lower = base.lower()

    # 检查只读命令
    if base_lower in _READ_ONLY_COMMANDS:
        # git：检查子命令
        if base_lower == "git":
            if args:
                sub = args[0].lstrip("-").lower()
                if sub in _GIT_READ_ONLY_SUB:
                    return CommandRisk.read_only
            return CommandRisk.normal

        # npm：检查子命令
        if base_lower == "npm":
            if args:
                sub = args[0].lstrip("-").lower()
                if sub in _NPM_READ_ONLY_SUB:
                    return CommandRisk.read_only
            return CommandRisk.normal

        # python/node：仅 --version 只读
        if base_lower in ("python", "python3", "node"):
            if args and args[0] in ("--version", "-V", "-c"):
                if args[0] == "-c":
                    return CommandRisk.normal  # -c 会执行代码
                return CommandRisk.read_only
            return CommandRisk.normal

        # echo、ls、cat 等——始终只读
        return CommandRisk.read_only

    return CommandRisk.normal