# -*- coding: utf-8 -*-
"""邮件正文渲染（HTML：字体大三档 + 单词/音标/分词性释义；附纯文本版供 CLI/测试）。"""
from __future__ import annotations

import html as html_mod
import re
from typing import Any, Dict, List, Tuple

from src.vocab.state import GROUPS

SLOT_LABEL = {"morning": "早间", "evening": "晚间"}
POS_RE = re.compile(r"(?<![a-zA-Z])(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int|abbr|det)\.(?=\s)")


def word_lookup(items: List[dict]) -> Dict[str, dict]:
    return {it["word"]: it for it in items}


def split_meaning(meaning: str) -> List[dict]:
    """把「v. 离弃；n. 放任」拆成 [{'pos':'v.','text':'离弃'}, {'pos':'n.','text':'放任'}]。"""
    meaning = (meaning or "").strip()
    if not meaning:
        return []
    matches = list(POS_RE.finditer(meaning))
    if not matches:
        return [{"pos": "", "text": meaning}]
    segs: List[dict] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(meaning)
        seg = meaning[start:end].strip(" ；\t")
        if not seg:
            continue
        pos = m.group(0)
        text = seg[len(pos):].strip(" ；\t")
        segs.append({"pos": pos, "text": text})
    return segs or [{"pos": "", "text": meaning}]


def _esc(s: Any) -> str:
    return html_mod.escape(str(s or ""))


def word_lines(it: dict) -> List[str]:
    """纯文本单词块：第一行 单词 音标；其后每行 词性 + 对应释意。"""
    ph = (it.get("phonetic") or "").strip()
    lines = [f"{it['word']} {ph}".rstrip()]
    for seg in split_meaning(it.get("meaning", "")):
        lines.append(f"{seg['pos']} {seg['text']}".strip())
    return lines


def extract_article_glossary(article: str, lookup: Dict[str, dict]) -> List[dict]:
    """从文章正文提取生词/重难词：命中词库、跳过小初基础词、按首次出现去重排序。"""
    EXCLUDE_GROUPS = {"小初共有"}
    seen: set = set()
    out: List[dict] = []
    if not article:
        return out
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", article)
    for w in words:
        key = w.strip("'-").lower()
        if not key or key in seen:
            continue
        it = lookup.get(key)
        if not it or it.get("group") in EXCLUDE_GROUPS:
            continue
        seen.add(key)
        out.append(it)
    return out


def _word_html(it: dict, idx: int | None = None) -> str:
    prefix = f"{idx}. " if idx else ""
    ph = (it.get("phonetic") or "").strip()
    parts = [
        f'<div><b>{_esc(prefix)}{_esc(it["word"])}</b>'
        f'<span style="color:#667;">&nbsp;{_esc(ph)}</span></div>'
    ]
    for seg in split_meaning(it.get("meaning", "")):
        parts.append(f'<div style="color:#333;">&nbsp;&nbsp;{_esc(seg["pos"])} {_esc(seg["text"])}</div>')
    return "".join(parts)


def annotate_article(article: str, glossary_items: List[dict]) -> Tuple[str, List[dict]]:
    """给文中生词/重难词加细下划线 + 上标编号（编号 = 生词表全局序号）。

    返回 (带 <u><sup> 标记的 HTML 文本, 实际命中的生词列表)。
    """
    article_out = html_mod.escape(article or "")
    matched: List[dict] = []
    for idx, it in enumerate(glossary_items, 1):
        w = it["word"]
        pattern = re.compile(
            rf"(?<![a-zA-Z])({re.escape(w)})(?![a-zA-Z])",
            re.IGNORECASE,
        )
        if not pattern.search(article_out):
            continue
        article_out = pattern.sub(
            rf'<u style="text-decoration:underline;text-decoration-thickness:1px;">\1</u>'
            rf'<sup style="font-size:0.65em;color:#a33;font-weight:bold;">{idx}</sup>',
            article_out,
        )
        matched.append(it)
    return article_out, matched


def annotated_to_plain(annotated_html: str) -> str:
    """把带 <u>/<sup> 的文章标记转成纯文本：词[编号]。"""
    out = re.sub(
        r"<u[^>]*>([^<]+)</u><sup[^>]*>(\d+)</sup>",
        r"\1[\2]",
        annotated_html or "",
    )
    out = re.sub(r"<[^>]+>", "", out)
    return html_mod.unescape(out)


def _new_word_blocks(plan: Dict[str, Any]) -> List[Tuple[str, List[dict]]]:
    return [(g, plan["new"].get(g, [])) for g in GROUPS if plan["new"].get(g)]


def _matched_blocks(matched: List[dict]) -> List[Tuple[str, List[dict]]]:
    return [(g, [it for it in matched if it.get("group") == g]) for g in GROUPS]


def _render_common(cfg, plan, reading, lookup, learned_total) -> Tuple[Dict[str, Any], str, str]:
    today = plan["date"]
    slot = plan["slot"]
    label = SLOT_LABEL.get(slot, slot)
    date_str = today.isoformat()
    total = len(lookup)
    subject = f"【六级单词打卡】{date_str} {label}（Day{plan['day_no']}，{learned_total}/{total}）"
    new_items = [it for g, lst in _new_word_blocks(plan) for it in lst]
    review_items = [lookup[w] for w in plan["review"] if w in lookup]
    article = reading.get("article", "")
    glossary_items = extract_article_glossary(article, lookup)
    annotated, matched = annotate_article(article, glossary_items)
    ctx = {
        "subject": subject,
        "new_items": new_items,
        "new_blocks": _new_word_blocks(plan),
        "review_items": review_items,
        "reading": reading,
        "article": annotated,
        "words_n": len(article.split()) if article else 0,
        "glossary_items": glossary_items,
        "glossary_blocks": _matched_blocks(glossary_items),
        "glossary_total": len(glossary_items),
    }
    return ctx, subject, ""


def render_plain(cfg, plan, reading, lookup, learned_total) -> Tuple[str, str]:
    """纯文本版（CLI dry-run / 测试用）。"""
    ctx, subject, _ = _render_common(cfg, plan, reading, lookup, learned_total)
    lines: List[str] = [subject, ""]
    lines.append(f"一、今日新词（{len(ctx['new_items'])} 个）")
    counter = 0
    for g, items in ctx["new_blocks"]:
        lines.append(f"【{g}】（{len(items)} 个）")
        for it in items:
            counter += 1
            wl = word_lines(it)
            lines.append(f"{counter}. {wl[0]}")
            for sub in wl[1:]:
                lines.append(f"   {sub}")
        lines.append("")
    lines.append(f"二、回忆单词（{len(ctx['review_items'])} 个）")
    for i, it in enumerate(ctx["review_items"], 1):
        wl = word_lines(it)
        lines.append(f"{i}. {wl[0]}")
        for sub in wl[1:]:
            lines.append(f"   {sub}")
    lines.append("")
    if ctx["glossary_total"]:
        lines.append(f"三、文中生词与重难词汇（{ctx['glossary_total']} 个）")
        counter = 0
        for g, items in ctx["glossary_blocks"]:
            if not items:
                continue
            lines.append(f"【{g}】（{len(items)} 个）")
            for it in items:
                counter += 1
                wl = word_lines(it)
                lines.append(f"{counter}. {wl[0]}")
                for sub in wl[1:]:
                    lines.append(f"   {sub}")
            lines.append("")
    lines.append(f"四、今日阅读（约 {ctx['words_n']} 词）")
    lines.append(ctx["reading"].get("title", ""))
    lines.append(annotated_to_plain(ctx["article"]))
    lines.append("")
    lines.append("五、阅读翻译")
    lines.append(ctx["reading"].get("translation", ""))
    lines.append("")
    if ctx["reading"].get("source"):
        lines.append(f"（来源：{ctx['reading']['source']}）")
    lines.append("")
    lines.append("—— 晚上 18:00 见，晚间推送包含当日回测 + 第二篇阅读。" if plan["slot"] == "morning"
                 else "—— 明天 08:00 见，早间推送包含新词 + 复习 + 第一篇阅读。")
    return subject, "\n".join(lines)


def render_email(cfg, plan, reading, lookup, learned_total) -> Tuple[str, str]:
    """HTML 版（邮件正文，全文字体大三档 ≈ 20px）。"""
    ctx, subject, _ = _render_common(cfg, plan, reading, lookup, learned_total)
    h = _esc
    html_parts: List[str] = []
    html_parts.append(f'<div style="font-size:24px;font-weight:bold;margin-bottom:16px;">{h(subject)}</div>')

    html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">一、今日新词（{len(ctx["new_items"])} 个）</div>')
    counter = 0
    for g, items in ctx["new_blocks"]:
        html_parts.append(f'<div style="font-size:21px;font-weight:bold;margin:10px 0 4px;">【{h(g)}】（{len(items)} 个）</div>')
        for it in items:
            counter += 1
            html_parts.append(f'<div style="margin:6px 0;">{_word_html(it, counter)}</div>')

    html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">二、回忆单词（{len(ctx["review_items"])} 个）</div>')
    for i, it in enumerate(ctx["review_items"], 1):
        html_parts.append(f'<div style="margin:6px 0;">{_word_html(it, i)}</div>')

    if ctx["glossary_total"]:
        html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">三、文中生词与重难词汇（{ctx["glossary_total"]} 个）</div>')
        counter = 0
        for g, items in ctx["glossary_blocks"]:
            if not items:
                continue
            html_parts.append(f'<div style="font-size:21px;font-weight:bold;margin:10px 0 4px;">【{h(g)}】（{len(items)} 个）</div>')
            for it in items:
                counter += 1
                html_parts.append(f'<div style="margin:6px 0;">{_word_html(it, counter)}</div>')

    html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">四、今日阅读（约 {ctx["words_n"]} 词）</div>')
    html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin-bottom:6px;">{h(ctx["reading"].get("title", ""))}</div>')
    html_parts.append(f'<div style="font-size:22px;line-height:1.9;">{ctx["article"]}</div>')

    html_parts.append('<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">五、阅读翻译</div>')
    html_parts.append(f'<div style="line-height:1.9;">{h(ctx["reading"].get("translation", ""))}</div>')

    if ctx["reading"].get("source"):
        html_parts.append(f'<div style="color:#888;margin-top:12px;">（来源：{h(ctx["reading"]["source"])}）</div>')
    html_parts.append(
        '<div style="color:#888;margin-top:10px;">—— 晚上 18:00 见，晚间推送包含当日回测 + 第二篇阅读。</div>'
        if plan["slot"] == "morning"
        else '<div style="color:#888;margin-top:10px;">—— 明天 08:00 见，早间推送包含新词 + 复习 + 第一篇阅读。</div>'
    )
    body = (
        '<div style="font-size:20px;line-height:1.7;color:#222;'
        'font-family:&quot;Microsoft YaHei&quot;,Arial,sans-serif;">'
        + "".join(html_parts)
        + "</div>"
    )
    return subject, body
