# -*- coding: utf-8 -*-
"""四级备考推送：调度 / SRS / 渲染 / 听力 / 汉译英 / 状态 单元测试。"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cet4.audio import build_variants  # noqa: E402
from src.cet4.audio import _render_listening_page  # noqa: E402
from src.cet4.cos_client import CosRestClient  # noqa: E402
from src.cet4.cne import SAMPLE_CNE, build_cne  # noqa: E402
from src.cet4.config import DEFAULT  # noqa: E402
from src.cet4.listening import SAMPLE_LISTENING, build_listening  # noqa: E402
from src.cet4.listening import _chunk_text, _translate  # noqa: E402
from src.cet4.main import run_slot  # noqa: E402
from src.cet4.notifier import send_email  # noqa: E402
from src.cet4.plan import build_plan, commit_plan, simulate  # noqa: E402
from src.cet4.reading import SAMPLE_ARTICLE, build_reading  # noqa: E402
from src.cet4.render import (  # noqa: E402
    annotated_to_plain,
    annotate_article,
    extract_article_glossary,
    render_email,
    render_plain,
    split_meaning,
    word_lookup,
)
from src.cet4.state import GROUPS, VocabState  # noqa: E402
from src.cet4.words import daily_quota, group_map, split_quota  # noqa: E402


def make_cfg(tmp: str) -> dict:
    cfg = dict(DEFAULT)
    cfg["state_file"] = f"{tmp}/state.json"
    cfg["words_file"] = f"{tmp}/words.json"
    return cfg


def make_items() -> list:
    """构造 30 个词的假词库：三组各 10 个（示例文章高频词放「四级大纲词」，便于生词表测试）。"""
    items = []
    base_words = ["ability", "cities", "transport", "pollution", "encouraging", "officials", "diesel", "gases", "expanding", "quality"]
    for gi, g in enumerate(GROUPS):
        for i in range(10):
            w = base_words[i] if gi == 0 else f"w{gi}{i}"
            items.append({"word": w, "group": g, "meaning": "测试", "phonetic": "", "pos": "n."})
    return items


class TestQuota(unittest.TestCase):
    def test_100_day_finish(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            totals = {g: 10 for g in GROUPS}
            got = {g: 0 for g in GROUPS}
            day = date(2026, 8, 29)
            for _ in range(100):
                q = daily_quota(cfg, state, totals, day)
                for g in GROUPS:
                    got[g] += q[g]
                    state.advance_cursor(g, q[g])
                day = day.fromordinal(day.toordinal() + 1)
            self.assertEqual(got, totals)

    def test_split_quota_roundtrip(self) -> None:
        quota = {"四级大纲词": 34, "基础词": 16, "基础补强": 6}
        m, e = split_quota(quota, 0.5)
        for g in GROUPS:
            self.assertEqual(m[g] + e[g], quota[g])
            self.assertLessEqual(abs(m[g] - e[g]), 1)


class TestSrs(unittest.TestCase):
    def test_morning_word_dued_same_evening(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            groups = group_map(make_items())
            plan = build_plan(cfg, state, groups, date(2026, 8, 29), "morning")
            commit_plan(cfg, state, plan)
            evening = build_plan(cfg, state, groups, date(2026, 8, 29), "evening")
            morning_words = [it["word"] for v in plan["new"].values() for it in v]
            self.assertTrue(morning_words)
            word_group = {it["word"]: g for g, items in groups.items() for it in items}
            # 复习板块只含四级大纲词（基础词 / 基础补强不复习），且不超过上限
            for w in evening["review"]:
                self.assertEqual(word_group.get(w), "四级大纲词")
            self.assertLessEqual(len(evening["review"]), 20)
            # 早间新学的四级大纲词，当天晚间进入复习
            morning_syllabus = [w for w in morning_words if word_group[w] == "四级大纲词"]
            self.assertTrue(morning_syllabus)
            for w in morning_syllabus:
                self.assertIn(w, evening["review"])
            commit_plan(cfg, state, evening)
            nxt = build_plan(cfg, state, groups, date(2026, 8, 30), "morning")
            self.assertIn(morning_words[0], nxt["review"])

    def test_review_fills_to_target_min(self) -> None:
        """到期词不足时，从已学词里按最早待复习补齐到目标下限（15 个），只取四级大纲词。"""
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            items = [
                {"word": f"syl{i}", "group": "四级大纲词", "meaning": "x", "phonetic": "", "pos": "n."}
                for i in range(40)
            ] + [
                {"word": f"base{i}", "group": "基础词", "meaning": "x", "phonetic": "", "pos": "n."}
                for i in range(10)
            ]
            groups = group_map(items)
            today = date(2026, 10, 15)
            # 5 个四级大纲词已到期，35 个未到期；10 个基础词已到期（应被排除）
            for i in range(40):
                state.data["learned"][f"syl{i}"] = {
                    "learned_on": "2026-08-29",
                    "reviews": 0,
                    "last_review": "2026-08-29",
                    "next_review": "2026-10-15" if i < 5 else f"2026-{(11 + i % 2)}-{i % 28 + 1:02d}",
                }
            for i in range(10):
                state.data["learned"][f"base{i}"] = {
                    "learned_on": "2026-08-29",
                    "reviews": 0,
                    "last_review": "2026-08-29",
                    "next_review": "2026-10-15",
                }
            plan = build_plan(cfg, state, groups, today, "morning")
            review = plan["review"]
            self.assertEqual(len(review), 15)
            self.assertTrue(all(w.startswith("syl") for w in review))

    def test_evening_takes_remainder_not_full_quota(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            groups = group_map(make_items())
            morning = build_plan(cfg, state, groups, date(2026, 8, 29), "morning")
            commit_plan(cfg, state, morning)
            evening = build_plan(cfg, state, groups, date(2026, 8, 29), "evening")
            for g in GROUPS:
                self.assertEqual(len(morning["new"][g]) + len(evening["new"][g]), morning["quota"][g])


class TestSimulate(unittest.TestCase):
    def test_preview_finishes(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            groups = group_map(make_items())
            rows = simulate(cfg, groups, 100, date(2026, 8, 29))
            self.assertEqual(rows[-1]["learned_total"], 30)
            self.assertEqual(len(rows), 100)


class TestRender(unittest.TestCase):
    def _ctx(self):
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            items = make_items()
            groups = group_map(items)
            plan = build_plan(cfg, state, groups, date(2026, 8, 29), "morning")
            return cfg, plan, word_lookup(items)

    def test_render_body_sections(self) -> None:
        cfg, plan, lookup = self._ctx()
        subject, body = render_plain(cfg, plan, SAMPLE_ARTICLE, SAMPLE_LISTENING, SAMPLE_CNE, lookup, learned_total=27)
        for section in ["今日新词", "回忆单词", "今日阅读", "文中生词与重难词汇", "长难句分析", "阅读翻译", "听力训练", "汉译英"]:
            self.assertIn(section, body)
        # 新顺序：生难词 → 文章 → 长难句分析 → 翻译
        self.assertLess(body.index("文中生词与重难词汇"), body.index("今日阅读"))
        self.assertLess(body.index("今日阅读"), body.index("长难句分析"))
        self.assertLess(body.index("长难句分析"), body.index("阅读翻译"))
        # 答案空行分隔
        self.assertIn("以下为答案，先做完再看", body)
        self.assertIn("【四级备考打卡】", subject)
        self.assertIn("Day1，27/30", subject)
        # 邮件只保留对照页链接（三份直链与原文都在页面上）
        self.assertIn("听力对照页", body)
        self.assertIn("边听边看原文", body)
        self.assertIn("摘选 40 秒", body)
        self.assertNotIn("快速 1.25x", body)
        self.assertNotIn("英文原文", body)
        self.assertNotIn("音频直链（备用）", body)
        self.assertNotIn("音频下载", body)
        self.assertIn("② 从句应用", body)
        self.assertIn("定语从句", body)

    def test_render_html_font_and_lines(self) -> None:
        cfg, plan, lookup = self._ctx()
        subject, body = render_email(cfg, plan, SAMPLE_ARTICLE, SAMPLE_LISTENING, SAMPLE_CNE, lookup, learned_total=27)
        self.assertIn("font-size:20px", body)
        self.assertIn("<b>", body)
        self.assertIn("【四级大纲词】", body)
        self.assertLess(body.index("文中生词与重难词汇"), body.index("今日阅读"))
        self.assertLess(body.index("今日阅读"), body.index("阅读翻译"))
        self.assertIn("长难句分析", body)
        self.assertIn("听力训练", body)
        self.assertIn("汉译英", body)
        self.assertIn("underline wavy", body)
        self.assertIn("以下为答案，先做完再看", body)
        self.assertIn("font-size:22px;line-height:1.9", body)

    def test_split_meaning(self) -> None:
        segs = split_meaning("v. 离弃，丢弃；遗弃，抛弃；放弃")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["pos"], "v.")
        self.assertIn("离弃", segs[0]["text"])
        segs2 = split_meaning("n. 放任；狂热 v. 遗弃；放弃")
        self.assertEqual(len(segs2), 2)
        self.assertEqual(segs2[0]["pos"], "n.")
        self.assertEqual(segs2[1]["pos"], "v.")
        self.assertEqual(split_meaning(""), [])

    def test_annotate_article_wavy_skips_glossary_words(self) -> None:
        sentence = "However, they also point out that changing the habits of millions of commuters will take time and money."
        article = sentence
        items = [{"word": "commuters", "meaning": "n. 通勤者", "group": "四级大纲词", "phonetic": ""}]
        sentences = [{"sentence": sentence, "analysis": "主谓宾拆分。"}]
        out, matched = annotate_article(article, items, sentences)
        self.assertEqual(len(matched), 1)
        # 波浪线整句包裹；生词横线+编号嵌套在波浪线 span 内（子元素装饰覆盖波浪线，两线不重叠）
        wavy_open = out.index('<span style="text-decoration:underline wavy')
        wavy_close = out.index("</span>", wavy_open)
        u_pos = out.index("<u", wavy_open)
        self.assertTrue(wavy_open < u_pos < wavy_close)
        # 纯文本：整句 ~~~...~~~，生词带编号
        plain = annotated_to_plain(out)
        self.assertIn("commuters[1]", plain)
        self.assertEqual(plain.count("~"), 2)

    def test_annotate_article_index_sequence(self) -> None:
        article = "Good data matters. Data drives decisions."
        items = [
            {"word": "good", "meaning": "adj. 好的", "group": "四级大纲词", "phonetic": ""},
            {"word": "data", "meaning": "n. 数据", "group": "四级大纲词", "phonetic": ""},
        ]
        out, _ = annotate_article(article, items, [])
        self.assertIn(">1<", out)
        self.assertEqual(out.count(">2<"), 2)

    def test_extract_article_glossary(self) -> None:
        lookup = {
            "ability": {"word": "ability", "group": "四级大纲词", "meaning": "n. 能力", "phonetic": ""},
            "basic": {"word": "basic", "group": "基础词", "meaning": "adj. 基础的", "phonetic": ""},
            "graduate": {"word": "graduate", "group": "基础补强", "meaning": "v. 毕业", "phonetic": ""},
        }
        article = "The ability of every graduate relies on basic skills. Ability matters."
        gloss = extract_article_glossary(article, lookup)
        # 基础词 / 基础补强 均不进生词表，只收四级大纲词
        self.assertEqual([it["word"] for it in gloss], ["ability"])


class TestListening(unittest.TestCase):
    def test_mock_returns_sample(self) -> None:
        os.environ["LISTENING_MOCK"] = "1"
        try:
            result = build_listening(dict(DEFAULT), date(2026, 8, 29), "morning")
            self.assertIn("transcript", result)
            self.assertIn("translation", result)
            self.assertEqual(result["speeds"], [1.25, 1.0, 0.75])
            self.assertEqual(set(result["files"]), {"1.25", "1.0", "0.75"})
            self.assertTrue(result["page_url"])
        finally:
            os.environ.pop("LISTENING_MOCK", None)

    def test_chunk_text(self) -> None:
        text = " ".join([f"Sentence {i}." for i in range(200)])
        chunks = _chunk_text(text, 500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 520 for c in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))

    def test_translate_failure_marker(self) -> None:
        from unittest import mock

        from src.cet4 import listening as listening_mod

        settings = mock.MagicMock()
        settings.deepseek_api_key = ""
        with mock.patch.object(listening_mod, "chat", return_value=None), mock.patch.object(
            listening_mod, "time", mock.MagicMock()
        ):
            result = _translate(settings, "A short text.")
        self.assertIn("翻译生成失败", result)


class TestAudio(unittest.TestCase):
    def test_no_cos_falls_back_empty(self) -> None:
        # 未配置 COS 桶时不做三份处理，返回 {}（调用方回退原始直链）
        result = build_variants(dict(DEFAULT), "http://x/raw.mp3", date(2026, 8, 29), "morning")
        self.assertEqual(result, {})

    def test_listening_page_contains_player_and_transcript(self) -> None:
        page = _render_listening_page(
            {
                "title": "标题",
                "files": {
                    "1.25": "https://x/1.25.mp3",
                    "1.0": "https://x/1.0.mp3",
                    "0.75": "https://x/0.75.mp3",
                },
                "excerpt_seconds": 35,
                "transcript": "Some English transcript.",
                "translation": "中文翻译。",
            }
        )
        # 移动端兼容 + 后台播放：<audio> 元素播放（切后台继续），playbackRate 三档倍速，
        # 「用系统播放器打开」作兜底（系统播放器天然支持后台播放）
        self.assertIn("<audio", page)
        self.assertIn("playbackRate", page)
        self.assertIn("开始播放", page)
        self.assertIn("重听", page)
        self.assertIn("系统播放器", page)
        self.assertNotIn("音频下载", page)
        self.assertIn("英文原文", page)
        self.assertIn("中文翻译", page)
        self.assertIn("1.25.mp3", page)
        self.assertIn("0.75.mp3", page)
        self.assertIn("本次摘选 35 秒", page)

    def test_presigned_inline_url(self) -> None:
        cli = CosRestClient("bucket-x", "ap-guangzhou", "sid", "skey")
        url = cli.presigned_url(
            "cet4/listening/2026-08-29-morning/1.0.mp3",
            {"response-content-disposition": "inline"},
            expires_seconds=3600,
        )
        self.assertIn("response-content-disposition=inline", url)
        self.assertIn("q-url-param-list=response-content-disposition", url)
        self.assertIn("q-signature=", url)
        self.assertIn("q-sign-time=", url)


class TestCne(unittest.TestCase):
    def test_mock_returns_sample(self) -> None:
        os.environ["CNE_MOCK"] = "1"
        try:
            plan = {"new": {"四级大纲词": [{"word": "reduce"}], "基础词": [], "基础补强": []}}
            result = build_cne(dict(DEFAULT), plan, date(2026, 8, 29), "morning")
            self.assertIn("prompt", result)
            self.assertIn("answer", result)
            self.assertIn("clause", result)
            self.assertEqual(result["clause"]["type"], "定语从句")
        finally:
            os.environ.pop("CNE_MOCK", None)

    def test_pool_rotation_when_llm_fails(self) -> None:
        """LLM 不可用时从内置池取句，已用过的句子不再重复。"""
        from unittest import mock

        from src.cet4.cne import CNE_POOL, build_cne
        from src.cet4.state import VocabState

        with TemporaryDirectory() as tmp:
            state = VocabState(make_cfg(tmp))
            plan = {"new": {"四级大纲词": [{"word": "reduce"}], "基础词": [], "基础补强": []}}
            os.environ["DEEPSEEK_API_KEY"] = "test-key"
            try:
                with mock.patch("src.cet4.cne.chat", side_effect=RuntimeError("llm down")):
                    r1 = build_cne(dict(DEFAULT), plan, date(2026, 8, 29), "morning", state)
                    state.record_cne(r1["prompt"])
                    r2 = build_cne(dict(DEFAULT), plan, date(2026, 8, 29), "evening", state)
                    state.record_cne(r2["prompt"])
                self.assertIn(r1["prompt"], [p["prompt"] for p in CNE_POOL])
                self.assertNotEqual(r1["prompt"], r2["prompt"])
                self.assertTrue(r1["clause"])
                self.assertTrue(r2["clause"])
            finally:
                os.environ.pop("DEEPSEEK_API_KEY", None)


class TestReading(unittest.TestCase):
    def test_mock_returns_sample(self) -> None:
        os.environ["READING_MOCK"] = "1"
        try:
            result = build_reading(dict(DEFAULT), date(2026, 8, 29), "morning")
            self.assertIn("article", result)
            self.assertIn("translation", result)
            self.assertIn("sentences", result)
            self.assertGreater(len(result["article"]), 100)
        finally:
            os.environ.pop("READING_MOCK", None)

    def test_pick_news_skips_used_articles(self) -> None:
        """选稿应跳过已用过的文章（链接或标题命中历史即跳过）。"""
        from unittest import mock

        from src.cet4.reading import _pick_news

        cfg = {"reading": {"morning_sources": ["npr_science"], "feeds": {"npr_science": "http://feed"}}}
        items = [
            {"title": "A", "link": "http://a", "summary": "", "pub_date": ""},
            {"title": "B", "link": "http://b", "summary": "", "pub_date": ""},
        ]
        with mock.patch("src.cet4.reading.fetch_rss", return_value=[dict(x) for x in items]):
            news = _pick_news(None, cfg, "morning", date(2026, 10, 20), used=["http://a"])
            self.assertEqual(news["link"], "http://b")
            fresh = _pick_news(None, cfg, "morning", date(2026, 10, 20), used=[])
            self.assertEqual(fresh["link"], "http://a")

    def test_parse_rss_tolerates_trailing_junk(self) -> None:
        from src.cet4.reading import _parse_rss

        xml = '<?xml version="1.0"?><rss><channel><item><title>T</title></item></channel></rss> junk after doc'
        root = _parse_rss(xml)
        self.assertIsNotNone(root)

    def test_state_records_reading_once(self) -> None:
        with TemporaryDirectory() as tmp:
            state = VocabState(make_cfg(tmp))
            state.record_reading("http://a")
            state.record_reading("http://a")
            state.record_reading("http://b")
            self.assertEqual(state.reading_used_keys(), ["http://a", "http://b"])

    def test_llm_rewrite_retries_on_bad_response(self) -> None:
        from unittest import mock

        from src.cet4 import reading as reading_mod

        calls = {"n": 0}

        def fake_chat(settings, messages, *, max_tokens=8000):
            calls["n"] += 1
            if calls["n"] == 1:
                return "not json"
            return '{"title": "T", "article": "A short article.", "translation": "一篇短文。", "sentences": []}'

        settings = mock.MagicMock()
        news = {"title": "N", "link": "http://x", "source": "s"}
        with mock.patch.object(reading_mod, "chat", side_effect=fake_chat), mock.patch.object(
            reading_mod, "time", mock.MagicMock()
        ):
            result = reading_mod._llm_rewrite(settings, news, "text", 220, 3000)
        self.assertIsNotNone(result)
        self.assertEqual(result["article"], "A short article.")
        self.assertEqual(calls["n"], 2)


class TestNotifier(unittest.TestCase):
    def test_smtp_send(self) -> None:
        captured: dict = {}

        class FakeServer:
            def __init__(self, *a, **k) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, user, code) -> None:
                captured["login"] = (user, code)

            def sendmail(self, frm, to, msg) -> None:
                captured["mail"] = (frm, to, msg)

        from unittest import mock

        cfg = dict(DEFAULT)
        with mock.patch("smtplib.SMTP_SSL", FakeServer), mock.patch.dict(
            os.environ,
            {"SMTP_USER": "u@x.com", "SMTP_AUTH_CODE": "code", "MAIL_TO": "me@x.com", "EMAIL_WEBHOOK_URL": ""},
            clear=False,
        ):
            ok = send_email("主题", "正文", cfg)
        self.assertTrue(ok)
        self.assertEqual(captured["login"], ("u@x.com", "code"))

    def test_smtp_send_with_attachment(self) -> None:
        captured: dict = {}

        class FakeServer:
            def __init__(self, *a, **k) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, user, code) -> None:
                captured["login"] = (user, code)

            def sendmail(self, frm, to, msg) -> None:
                captured["mail"] = (frm, to, msg)

        from unittest import mock

        cfg = dict(DEFAULT)
        with mock.patch("smtplib.SMTP_SSL", FakeServer), mock.patch.dict(
            os.environ,
            {"SMTP_USER": "u@x.com", "SMTP_AUTH_CODE": "code", "MAIL_TO": "me@x.com", "EMAIL_WEBHOOK_URL": ""},
            clear=False,
        ):
            ok = send_email(
                "主题", "正文", cfg,
                attachment={"filename": "listening-test.mp3", "data": b"ID3-fake-mp3"},
            )
        self.assertTrue(ok)
        raw = captured["mail"][2]
        self.assertIn("audio/mpeg", raw)
        self.assertIn("listening-test.mp3", raw)
        self.assertIn("SUQzLWZha2UtbXAz", raw)  # b"ID3-fake-mp3" 的 base64


class TestRunSlot(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["READING_MOCK"] = "1"
        os.environ["LISTENING_MOCK"] = "1"
        os.environ["CNE_MOCK"] = "1"

    def tearDown(self) -> None:
        for k in ("READING_MOCK", "LISTENING_MOCK", "CNE_MOCK"):
            os.environ.pop(k, None)

    def _run(self, send_result: bool):
        from unittest import mock

        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            items = make_items()
            groups = group_map(items)
            lookup = word_lookup(items)
            with mock.patch("src.cet4.main.send_email", return_value=send_result):
                rc = run_slot(
                    cfg, state, groups, lookup, date(2026, 8, 29), "morning",
                    send=True, commit_only=False,
                )
            return rc, state

    def test_success_commits(self) -> None:
        rc, state = self._run(True)
        self.assertEqual(rc, 0)
        self.assertTrue(any(state.cursor(g) > 0 for g in GROUPS))
        self.assertIsNone(state.pending())
        self.assertEqual(state.data["email_failures"], 0)

    def test_failure_sets_pending(self) -> None:
        rc, state = self._run(False)
        self.assertEqual(rc, 1)
        self.assertIsNotNone(state.pending())
        self.assertEqual(state.data["email_failures"], 1)
        self.assertFalse(state.paused)

    def test_three_failures_pauses(self) -> None:
        from unittest import mock

        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 29))
            state.data["email_failures"] = 2
            items = make_items()
            groups = group_map(items)
            with mock.patch("src.cet4.main.send_email", return_value=False), mock.patch(
                "src.cet4.main.send_alert", return_value=False
            ):
                rc = run_slot(cfg, state, groups, word_lookup(items), date(2026, 8, 29), "morning",
                              send=True, commit_only=False)
            self.assertEqual(rc, 1)
            self.assertTrue(state.paused)

    def test_main_handler_parses_timer_message(self) -> None:
        """定时触发器把自定义入参放在 Message 字符串里，必须解析出 slot=evening。"""
        from unittest import mock

        from src.cet4.main import main_handler

        with TemporaryDirectory() as tmp, mock.patch(
            "src.cet4.main.load_cet4_config", return_value=make_cfg(tmp)
        ), mock.patch(
            "src.cet4.main.load_words", return_value=make_items()
        ), mock.patch("src.cet4.main.run_slot", return_value=0) as run_mock:
            event = {
                "Type": "Timer",
                "TriggerName": "c1800",
                "Time": "2026-08-29T18:00:00+08:00",
                "Message": json.dumps({"action": "run", "slot": "evening"}),
            }
            rc = main_handler(event)
            self.assertEqual(rc, 0)
            self.assertEqual(run_mock.call_args.args[5], "evening")
            self.assertTrue(run_mock.call_args.kwargs["send"])


class TestRealWordlist(unittest.TestCase):
    def test_counts(self) -> None:
        path = ROOT / "data" / "cet4" / "words.json"
        if not path.exists():
            self.skipTest("words.json 未构建")
        items = json.loads(path.read_text(encoding="utf-8"))
        c = Counter(it["group"] for it in items)
        self.assertEqual(sum(c.values()), 5115)
        self.assertEqual(c["四级大纲词"], 3096)
        self.assertEqual(c["基础词"], 1447)
        self.assertEqual(c["基础补强"], 572)
        # 释义与音标全覆盖
        self.assertEqual(sum(1 for it in items if not it["meaning"]), 0)
        self.assertEqual(sum(1 for it in items if not it["phonetic"]), 0)


if __name__ == "__main__":
    unittest.main()
