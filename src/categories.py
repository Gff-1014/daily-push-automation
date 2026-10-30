# -*- coding: utf-8 -*-
"""分类常量与来源频道兜底分类。"""
from __future__ import annotations

MAIN_CATEGORIES = ["政治", "经济", "科技", "生活", "国际", "社会"]
SUB_CATEGORIES = ["文化教育", "军事国防", "生态环境"]

CHANNEL_FALLBACK_CATEGORY = {
    "china": "政治",
    "law": "政治",
    "economy": "经济",
    "tech": "科技",
    "world": "国际",
    "life": "生活",
    "health": "生活",
    "society": "社会",
    "ent": "次类",
    "edu": "次类",
    "military": "军事国防",
    "telegraph": "经济",
    "depth": "经济",
    "gj": "国际",
    "kejiyy": "科技",
    "junshi": "军事国防",
    "zhongguo": "政治",
    "xwlb": "政治",
    "cwtx": "政治",
}
