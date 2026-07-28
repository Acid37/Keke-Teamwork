"""从 backend.events 的 dataclass 定义自动生成前端 TypeScript 类型。

用法::

    python -m backend.export_schema                    # 输出到 frontend/src/generated/events.ts
    python -m backend.export_schema --output path.ts   # 自定义输出路径

生成的文件包含：
- EventMap：所有事件类型 → payload 映射
- EventPayloadOf<T>：按事件名取 payload 类型
- 事件类型常量（与 Python 端完全一致）
"""

from __future__ import annotations

import argparse
import inspect
import os
import re
import sys
import textwrap
from dataclasses import fields
from pathlib import Path

from backend.events import EVENT_REGISTRY

# ─── Python → TypeScript 类型映射 ───

_TYPE_MAP: dict[str, str] = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "dict": "Record<string, unknown>",
    "list[dict]": "Record<string, unknown>[]",
    "list[str]": "string[]",
}

# 正则匹配
_RE_LIST = re.compile(r"^list\[(.+)\]$")
_RE_UNION = re.compile(r"^(.+) \| None$")
_RE_GENERIC_DICT = re.compile(r"^dict\[str,\s*(.+)\]$")


def py_type_to_ts(py_type: str, optional: bool = False) -> str:
    """将 Python 类型注解转换为 TypeScript 类型字符串。"""
    # 移除前导 typing.
    py_type = py_type.replace("typing.", "").strip()

    # 处理 Optional（X | None）
    if m := _RE_UNION.match(py_type):
        inner = py_type_to_ts(m.group(1).strip(), optional=True)
        return inner

    # 处理 list[X]
    if m := _RE_LIST.match(py_type):
        inner = py_type_to_ts(m.group(1).strip())
        return f"{inner}[]"

    # 处理 dict[str, X]
    if m := _RE_GENERIC_DICT.match(py_type):
        value = py_type_to_ts(m.group(1).strip())
        return f"Record<string, {value}>"

    # 直接映射
    if py_type in _TYPE_MAP:
        ts = _TYPE_MAP[py_type]
        return f"{ts} | null" if optional else ts

    # fallback
    return "unknown"


def generate_interface(name: str, field_list: list) -> list[str]:
    """为一个 dataclass 生成 TypeScript interface。"""
    lines = [f"export interface {name} {{"]
    for f in field_list:
        if f.name == "_event_type":
            continue
        optional = False
        py_t = str(f.type)
        # 检测 Optional
        if " | None" in py_t or py_t.startswith("Optional["):
            optional = True
        ts_type = py_type_to_ts(py_t, optional)
        q = "?" if optional else ""
        lines.append(f"  {f.name}{q}: {ts_type};")
    lines.append("}")
    return lines


def generate_event_map() -> list[str]:
    """生成 EventMap 联合类型和辅助工具类型。"""
    lines: list[str] = []
    lines.append("// ─── 事件类型常量 ───")
    lines.append("")

    # 常量
    for event_type in EVENT_REGISTRY:
        const_name = event_type.replace(".", "_").upper()
        lines.append(f"export const {const_name} = \"{event_type}\";")

    lines.append("")
    lines.append("// ─── Payload 接口 ───")
    lines.append("")

    # 每个 event 生成一个 payload interface
    for event_type, cls in EVENT_REGISTRY.items():
        const_name = event_type.replace(".", "_").upper()
        iface_name = f"{const_name}Payload"
        field_list = [f for f in fields(cls) if f.name != "_event_type"]
        lines.extend(generate_interface(iface_name, field_list))
        lines.append("")

    # EventMap
    lines.append("// ─── EventMap：事件类型 → payload ───")
    lines.append("")
    lines.append("export interface EventMap {")
    for event_type in EVENT_REGISTRY:
        const_name = event_type.replace(".", "_").upper()
        lines.append(f"  \"{event_type}\": {const_name}Payload;")
    lines.append("}")
    lines.append("")

    # 辅助类型
    lines.append("// ─── 辅助类型 ───")
    lines.append("")
    lines.append("/** 按事件类型名提取 payload 类型 */")
    lines.append("export type EventPayloadOf<K extends keyof EventMap> = EventMap[K];")
    lines.append("")
    lines.append("/** 所有事件类型名 */")
    lines.append("export type EventType = keyof EventMap;")
    lines.append("")
    lines.append("/** WS 消息结构 */")
    lines.append("export interface WSMessage<T extends EventType = EventType> {")
    lines.append("  type: T;")
    lines.append("  payload: EventMap[T];")
    lines.append("}")

    return lines


def render_file(content_lines: list[str]) -> str:
    """添加文件头注释。"""
    header = textwrap.dedent("""\
    // ──────────────────────────────────────────────────────────────
    // 自动生成文件 — 请勿手动修改
    // 生成命令: python -m backend.export_schema
    // 源定义:  backend/events.py → EVENT_REGISTRY
    // ──────────────────────────────────────────────────────────────

    """)
    return header + "\n".join(content_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="从 events.py 生成 TypeScript 类型")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出路径（默认: frontend/src/generated/events.ts）",
    )
    args = parser.parse_args()

    # 确定输出路径
    project_root = Path(__file__).resolve().parent.parent
    output_path = Path(args.output) if args.output else project_root / "frontend" / "src" / "generated" / "events.ts"

    # 生成内容
    lines = generate_event_map()
    content = render_file(lines)

    # 确保目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    event_count = len(EVENT_REGISTRY)
    print(f"Generated {event_count} event types → {output_path}")


if __name__ == "__main__":
    main()
