# -*- coding: utf-8 -*-
"""标题归一化与指纹。"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_PUNCT = re.compile(r"[\s\u3000，。！？；：、（）()【】\[\]《》<>\"'“”‘’·—–\-_|/\\:：,.!?;]+")
_MEDIA_PREFIX = re.compile(r"^(央视网|新华网|中新网|人民网|环球网|参考消息|财联社|人民日报|新华社|中国新闻网)")
_DIGITS = re.compile(r"[0-9０-９]+")


def normalize_title(title: str) -> str:
    """归一化：去标点空格、去媒体名前缀、数字归一化、转小写。"""
    t = unicodedata.normalize("NFKC", title or "")
    t = _MEDIA_PREFIX.sub("", t)
    t = _PUNCT.sub("", t)
    t = _DIGITS.sub("N", t)
    return t.lower()


def fingerprint(title: str, url: str = "") -> str:
    """标题指纹；URL 后缀 id 作为附加信号。"""
    base = normalize_title(title)
    m = re.search(r"([A-Za-z0-9]{12,})$", url.strip().rstrip("/"))
    if m:
        base += m.group(1)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()
