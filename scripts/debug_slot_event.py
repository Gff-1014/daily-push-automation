# -*- coding: utf-8 -*-
"""调试：SCF 定时触发器事件形态对 slot 解析的影响。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_like_handler(event):
    """复刻 main_handler 的 slot 解析路径（注意 main_handler 对字符串 event 的行为）。"""
    event = event or {}
    action = event.get("action", "run") if isinstance(event, dict) else None
    if isinstance(event, str):
        try:
            parsed = json.loads(event)
            event = parsed if isinstance(parsed, dict) else {}
            action = event.get("action", "run")
        except json.JSONDecodeError:
            event = {}
            action = "run"
    slot = event.get("slot", "morning")
    if slot not in ("morning", "evening"):
        slot = "morning"
    return action, slot


def main() -> int:
    # 形态 1：SCF 定时触发器把 CustomArgument 原文作为事件体（字符串）
    s = '{"action": "run", "slot": "evening"}'
    try:
        # 当前 main_handler 直接用 event.get：字符串会抛 AttributeError
        slot = s.get("slot", "morning")
        print("字符串形态 →", slot)
    except AttributeError:
        print("字符串形态 → 当前代码抛 AttributeError（说明需要兼容）")
    print("兼容解析后 →", parse_like_handler(s)[1])
    print("字典形态 →", parse_like_handler({"action": "run", "slot": "evening"})[1])
    print("空事件 →", parse_like_handler({})[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
