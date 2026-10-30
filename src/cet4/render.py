# -*- coding: utf-8 -*-
"""邮件正文渲染（HTML：字体大三档 + 单词/音标/分词性释义；附纯文本版供 CLI/测试）。

排版要点：
    - 生词/重难词：灰色横下划线 + 上标编号
    - 长难句：浅红波浪下划线（与生词横线不重合）
    - 板块顺序：新词 → 回忆 → 阅读 → 生词 → 长难句分析 → 阅读翻译 → 听力 → 汉译英
    - 答案：紧贴练习之后，空 4-5 行 + 提示行分隔，避免做题时误看
"""
from __future__ import annotations

import html as html_mod
import re
from typing import Any, Dict, List, Tuple

from src.cet4.state import GROUPS

SLOT_LABEL = {"morning": "早间", "evening": "晚间"}
POS_RE = re.compile(r"(?<![a-zA-Z])(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int|abbr|det)\.(?=\s)")

# 浅色系，避免颜色太重影响阅读（可按需调整深浅）
WAVY_COLOR = "#c97070"      # 长难句波浪线：浅红
GLOSSARY_COLOR = "#8a8a8a"  # 生词横线：浅灰
SUP_COLOR = "#a33"          # 生词编号：暗红
ANSWER_HINT_COLOR = "#999"  # 答案提示行：浅灰

ANSWER_BLANK_LINES = 5      # 答案前空行数


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
    """从文章正文提取生词/重难词：命中词库、跳过基础词、按首次出现去重排序。"""
    EXCLUDE_GROUPS = {"基础词", "基础补强"}
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


# ---------------------------------------------------------------------------
# 文章标注：生词横线 + 上标编号；长难句浅红波浪线（两线不重合）
# ---------------------------------------------------------------------------

def _find_word_spans(article_lower: str, glossary_items: List[dict]) -> Tuple[List[tuple], List[dict]]:
    spans: List[tuple] = []
    matched: List[dict] = []
    for idx, it in enumerate(glossary_items, 1):
        w = (it.get("word") or "").lower()
        if not w:
            continue
        start = 0
        first = True
        while True:
            m = re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", article_lower[start:])
            if not m:
                break
            spans.append((start + m.start(), start + m.end(), it, idx))
            if first:
                matched.append(it)
                first = False
            start = start + m.end()
    return spans, matched


def _find_sentence_spans(article_lower: str, complex_sentences: List[dict]) -> List[tuple]:
    spans: List[tuple] = []
    for s in complex_sentences or []:
        text = (s.get("sentence") or "").strip().lower()
        if not text:
            continue
        start = 0
        while True:
            m = re.search(re.escape(text), article_lower[start:])
            if not m:
                break
            spans.append((start + m.start(), start + m.end()))
            start = start + m.end()
    return spans


def _render_seg(seg: str, active_word: tuple | None, active_sent: bool) -> str:
    esc = _esc(seg)
    if active_word:
        _, idx = active_word
        return (
            f'<u style="text-decoration:underline;text-decoration-thickness:1px;'
            f'text-decoration-color:{GLOSSARY_COLOR};">{esc}</u>'
            f'<sup style="font-size:0.65em;color:{SUP_COLOR};font-weight:bold;">{idx}</sup>'
        )
    return esc


def annotate_article(
    article: str,
    glossary_items: List[dict],
    complex_sentences: List[dict] | None = None,
) -> Tuple[str, List[dict]]:
    """给文章加标注：生词（横线+编号）优先，长难句（浅红波浪线）跳过已标生词，两线不重合。

    返回 (带标记的 HTML 文本, 实际命中的生词列表)。
    """
    article = article or ""
    lower = article.lower()
    word_spans, matched = _find_word_spans(lower, glossary_items)
    sent_spans = _find_sentence_spans(lower, complex_sentences or [])

    events: List[tuple] = []
    for s, e, it, idx in word_spans:
        events.append((s, "word_start", it, idx))
        events.append((e, "word_end", None, None))
    for s, e in sent_spans:
        events.append((s, "sent_start", None, None))
        events.append((e, "sent_end", None, None))
    events.sort(key=lambda x: (x[0], 0 if x[1].endswith("start") else 1))

    out: List[str] = []
    pos = 0
    active_word: tuple | None = None
    active_sent = 0
    for ev in events:
        p = ev[0]
        if p > pos:
            out.append(_render_seg(article[pos:p], active_word, active_sent > 0))
        kind = ev[1]
        if kind == "sent_start":
            out.append(
                f'<span style="text-decoration:underline wavy {WAVY_COLOR};'
                f'text-decoration-thickness:1px;">'
            )
            active_sent += 1
        elif kind == "sent_end":
            out.append("</span>")
            active_sent = max(0, active_sent - 1)
        elif kind == "word_start":
            active_word = (ev[2], ev[3])
        elif kind == "word_end":
            active_word = None
        pos = max(pos, p)
    if pos < len(article):
        out.append(_render_seg(article[pos:], active_word, active_sent > 0))
    return "".join(out), matched


def annotated_to_plain(annotated_html: str) -> str:
    """把带 <span wavy>/<u>/<sup> 的标记转成纯文本：长难句 ~...~，生词 词[编号]。"""
    out = re.sub(
        r'<span[^>]*style="text-decoration:underline wavy[^"]*"[^>]*>(.*?)</span>',
        r"~\1~",
        annotated_html or "",
        flags=re.S,
    )
    out = re.sub(
        r"<u[^>]*>([^<]+)</u><sup[^>]*>(\d+)</sup>",
        r"\1[\2]",
        out,
    )
    out = re.sub(r"<[^>]+>", "", out)
    return html_mod.unescape(out)


def _new_word_blocks(plan: Dict[str, Any]) -> List[Tuple[str, List[dict]]]:
    return [(g, plan["new"].get(g, [])) for g in GROUPS if plan["new"].get(g)]


def _matched_blocks(matched: List[dict]) -> List[Tuple[str, List[dict]]]:
    return [(g, [it for it in matched if it.get("group") == g]) for g in GROUPS]


def _answer_separator_plain() -> List[str]:
    return [""] * ANSWER_BLANK_LINES + ["（以下为答案，先做完再看）", ""]


def _answer_separator_html() -> str:
    blocks = "".join(
        f'<div style="height:1.6em;line-height:1.6em;">&nbsp;</div>' for _ in range(ANSWER_BLANK_LINES)
    )
    return (
        blocks
        + f'<div style="color:{ANSWER_HINT_COLOR};font-size:18px;margin:4px 0 8px;">'
        + "（以下为答案，先做完再看）"
        + "</div>"
    )


def _render_common(cfg, plan, reading, listening, cne, lookup, learned_total) -> Tuple[Dict[str, Any], str, str]:
    today = plan["date"]
    slot = plan["slot"]
    label = SLOT_LABEL.get(slot, slot)
    date_str = today.isoformat()
    total = len(lookup)
    subject = f"【四级备考打卡】{date_str} {label}（Day{plan['day_no']}，{learned_total}/{total}）"
    new_items = [it for g, lst in _new_word_blocks(plan) for it in lst]
    review_items = [lookup[w] for w in plan["review"] if w in lookup]
    article = reading.get("article", "")
    sentences = list(reading.get("sentences", []) or [])
    glossary_items = extract_article_glossary(article, lookup)
    annotated, matched = annotate_article(article, glossary_items, sentences)
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
        "sentences": sentences,
        "listening": listening or {},
        "cne": cne or {},
    }
    return ctx, subject, ""


def render_plain(cfg, plan, reading, listening, cne, lookup, learned_total) -> Tuple[str, str]:
    """纯文本版（CLI dry-run / 测试用）。"""
    ctx, subject, _ = _render_common(cfg, plan, reading, listening, cne, lookup, learned_total)
    greeting = "上午好" if plan["slot"] == "morning" else "晚上好"
    lines: List[str] = [subject, "", f"{greeting}，亲爱的蕾蕾同学！今天是第 {plan['day_no']} 天。", ""]

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
        lines.append(f"三、文中生词与重难词汇（{ctx['glossary_total']} 个，先看词再读文章）")
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

    if ctx["sentences"]:
        lines.append(f"五、长难句分析（{len(ctx['sentences'])} 句）")
        for i, s in enumerate(ctx["sentences"], 1):
            lines.append(f"{i}. {s.get('sentence', '')}")
            lines.append(f"   分析：{s.get('analysis', '')}")
        lines.append("")

    lines.append("六、阅读翻译")
    lines.append(ctx["reading"].get("translation", ""))
    lines.append("")
    if ctx["reading"].get("source"):
        lines.append(f"（来源：{ctx['reading']['source']}）")
    lines.append("")

    listening = ctx["listening"]
    if listening:
        excerpt = listening.get("excerpt_seconds") or 0
        excerpt_txt = f"（摘选 {int(excerpt)} 秒）" if excerpt else ""
        lines.append(f"七、听力训练{excerpt_txt}")
        page_url = listening.get("page_url", "")
        if page_url:
            lines.append(f"听力对照页（边听边看原文）：{page_url}")
            if listening.get("title"):
                lines.append(f"标题：{listening['title']}")
            lines.append("（对照页内含播放器与三档倍速，可边听边对照原文）")
        else:
            # 兜底：对照页生成失败时才列出直链
            files = listening.get("files", {}) or {}
            if files:
                lines.append(f"快速 1.25x：{files.get('1.25', '')}")
                lines.append(f"正常 1x：{files.get('1.0', '')}")
                lines.append(f"慢速 0.75x：{files.get('0.75', '')}")
            else:
                lines.append(f"音频：{listening.get('play_url', '') or listening.get('mp3_url', '')}")
            if listening.get("title"):
                lines.append(f"标题：{listening['title']}")
            lines.append("英文原文：")
            lines.append(listening.get("transcript", ""))
            lines.extend(_answer_separator_plain())
            lines.append("中文翻译（答案）：")
            lines.append(listening.get("translation", ""))
        lines.append("")

    cne = ctx["cne"]
    if cne:
        lines.append("八、汉译英")
        lines.append("① 翻译练习")
        lines.append(f"题目：{cne.get('prompt', '')}")
        lines.extend(_answer_separator_plain())
        lines.append(f"参考答案：{cne.get('answer', '')}")
        if cne.get("hint"):
            lines.append(f"考点提示：{cne['hint']}")
        clause = cne.get("clause") or {}
        if clause:
            lines.append("")
            lines.append(f"② 从句应用（今日：{clause.get('type', '')}）")
            lines.append(f"中文：{clause.get('prompt', '')}")
            lines.extend(_answer_separator_plain())
            lines.append(f"英文参考：{clause.get('answer', '')}")
            if clause.get("explain"):
                lines.append(f"讲解：{clause['explain']}")
        lines.append("")

    lines.append("辛苦了！咱们今晚见！" if plan["slot"] == "morning" else "辛苦了！咱们明天见！")
    return subject, "\n".join(lines)


def render_email(cfg, plan, reading, listening, cne, lookup, learned_total) -> Tuple[str, str]:
    """HTML 版（邮件正文，全文字体大三档 ≈ 20px）。"""
    ctx, subject, _ = _render_common(cfg, plan, reading, listening, cne, lookup, learned_total)
    h = _esc
    html_parts: List[str] = []
    greeting = "上午好" if plan["slot"] == "morning" else "晚上好"
    html_parts.append(
        '<div style="font-size:22px;font-weight:bold;margin:0 0 12px;">'
        f'{greeting}，亲爱的蕾蕾同学！今天是第 {plan["day_no"]} 天。</div>'
    )
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
        html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">三、文中生词与重难词汇（{ctx["glossary_total"]} 个，先看词再读文章）</div>')
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

    if ctx["sentences"]:
        html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">五、长难句分析（{len(ctx["sentences"])} 句）</div>')
        for i, s in enumerate(ctx["sentences"], 1):
            html_parts.append(
                f'<div style="margin:8px 0;"><span style="font-size:20px;color:#333;">{i}. '
                f'<span style="text-decoration:underline wavy {WAVY_COLOR};">{h(s.get("sentence", ""))}</span></span></div>'
            )
            html_parts.append(f'<div style="font-size:19px;line-height:1.8;color:#444;margin-left:1.4em;">{h(s.get("analysis", ""))}</div>')

    html_parts.append('<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">六、阅读翻译</div>')
    html_parts.append(f'<div style="line-height:1.9;">{h(ctx["reading"].get("translation", ""))}</div>')
    if ctx["reading"].get("source"):
        html_parts.append(f'<div style="color:#888;margin-top:12px;">（来源：{h(ctx["reading"]["source"])}）</div>')

    listening = ctx["listening"]
    if listening:
        excerpt = listening.get("excerpt_seconds") or 0
        excerpt_txt = f"（摘选 {int(excerpt)} 秒）" if excerpt else ""
        html_parts.append(f'<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">七、听力训练{excerpt_txt}</div>')
        inline_data = listening.get("inline_data") or {}
        if inline_data:
            # 内嵌播放器：iOS 系统自带播放器控件（audio controls），音频 base64 内嵌，无外链
            for label, rate in (("第一遍 · 1.25x 快速听大意", "1.25"), ("第二遍 · 1x 正常精听", "1.0"), ("第三遍 · 0.75x 慢速核对", "0.75")):
                b64 = inline_data.get(rate, "")
                if not b64:
                    continue
                html_parts.append(f'<div style="font-size:19px;font-weight:bold;margin:12px 0 2px;">{label}</div>')
                html_parts.append(
                    '<audio controls preload="none" style="width:100%;margin:0 0 6px;">'
                    f'<source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">'
                    "您的邮件客户端不支持音频播放，请用手机浏览器打开本邮件。</audio>"
                )
            if listening.get("title"):
                html_parts.append(f'<div style="font-size:19px;color:#666;margin:2px 0 8px;">{h(listening["title"])}</div>')
            html_parts.append('<div style="font-size:20px;font-weight:bold;margin:14px 0 4px;">英文原文：</div>')
            html_parts.append(f'<div style="font-size:20px;line-height:1.9;">{h(listening.get("transcript", ""))}</div>')
            html_parts.append(_answer_separator_html())
            html_parts.append('<div style="font-size:20px;font-weight:bold;margin:8px 0 4px;">中文翻译（答案）：</div>')
            html_parts.append(f'<div style="font-size:20px;line-height:1.9;">{h(listening.get("translation", ""))}</div>')
            html_parts.append(
                '<div style="font-size:15px;color:#999;margin:8px 0 0;">'
                "（建议在手机浏览器中打开本邮件，播放后切到其他 App 可继续收听）</div>"
            )
        else:
            page_url = listening.get("page_url", "")
            if page_url:
                html_parts.append(
                    f'<div style="font-size:21px;margin:8px 0;">听力对照页（边听边看原文）：'
                    f'<a href="{h(page_url)}" style="color:#2b6cb0;font-weight:bold;">打开听力对照页</a>'
                    f'<span style="font-size:16px;color:#888;word-break:break-all;"> {h(page_url)}</span></div>'
                )
                html_parts.append('<div style="font-size:16px;color:#999;margin:2px 0 8px;">（页面内含播放器与三档倍速，可边听边对照原文）</div>')
                if listening.get("title"):
                    html_parts.append(f'<div style="font-size:19px;color:#666;margin:2px 0 8px;">{h(listening["title"])}</div>')
            else:
                # 兜底：对照页生成失败时才列出直链与原文
                files = listening.get("files", {}) or {}
                if files:
                    for label, rate in (("快速 1.25x", "1.25"), ("正常 1x", "1.0"), ("慢速 0.75x", "0.75")):
                        url = files.get(rate, "")
                        html_parts.append(
                            f'<div style="font-size:20px;margin:6px 0;">{label}：'
                            f'<a href="{h(url)}" style="color:#2b6cb0;font-weight:bold;">点击播放/下载</a></div>'
                        )
                else:
                    audio_url = listening.get("play_url", "") or listening.get("mp3_url", "")
                    html_parts.append(
                        f'<div style="font-size:20px;margin:10px 0 4px;">音频：'
                        f'<a href="{h(audio_url)}" style="color:#2b6cb0;font-weight:bold;">点击播放/下载</a></div>'
                    )
                if listening.get("title"):
                    html_parts.append(f'<div style="font-size:19px;color:#666;margin:2px 0 8px;">{h(listening["title"])}</div>')
                html_parts.append('<div style="font-size:20px;font-weight:bold;margin:14px 0 4px;">英文原文：</div>')
                html_parts.append(f'<div style="font-size:20px;line-height:1.9;">{h(listening.get("transcript", ""))}</div>')
                html_parts.append(_answer_separator_html())
                html_parts.append('<div style="font-size:20px;font-weight:bold;margin:8px 0 4px;">中文翻译（答案）：</div>')
                html_parts.append(f'<div style="font-size:20px;line-height:1.9;">{h(listening.get("translation", ""))}</div>')

    cne = ctx["cne"]
    if cne:
        html_parts.append('<div style="font-size:22px;font-weight:bold;margin:18px 0 6px;">八、汉译英</div>')
        html_parts.append('<div style="font-size:20px;font-weight:bold;margin:8px 0 4px;">① 翻译练习</div>')
        html_parts.append(f'<div style="font-size:21px;line-height:1.9;">{h(cne.get("prompt", ""))}</div>')
        html_parts.append(_answer_separator_html())
        html_parts.append(f'<div style="font-size:20px;margin:6px 0;"><b>参考答案：</b>{h(cne.get("answer", ""))}</div>')
        if cne.get("hint"):
            html_parts.append(f'<div style="font-size:19px;color:#666;">考点提示：{h(cne["hint"])}</div>')
        clause = cne.get("clause") or {}
        if clause:
            html_parts.append(f'<div style="font-size:20px;font-weight:bold;margin:16px 0 4px;">② 从句应用（今日：{h(clause.get("type", ""))}）</div>')
            html_parts.append(f'<div style="font-size:21px;line-height:1.9;">{h(clause.get("prompt", ""))}</div>')
            html_parts.append(_answer_separator_html())
            html_parts.append(f'<div style="font-size:20px;margin:6px 0;"><b>英文参考：</b>{h(clause.get("answer", ""))}</div>')
            if clause.get("explain"):
                html_parts.append(f'<div style="font-size:19px;color:#666;">讲解：{h(clause["explain"])}</div>')

    ending = "辛苦了！咱们今晚见！" if plan["slot"] == "morning" else "辛苦了！咱们明天见！"
    html_parts.append(
        f'<div style="font-size:21px;font-weight:bold;color:#333;margin-top:16px;">{ending}</div>'
    )
    body = (
        '<div style="font-size:20px;line-height:1.7;color:#222;'
        'font-family:&quot;Microsoft YaHei&quot;,Arial,sans-serif;">'
        + "".join(html_parts)
        + "</div>"
    )
    return subject, body
