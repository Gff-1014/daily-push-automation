# -*- coding: utf-8 -*-
"""六级单词推送：调度 / SRS / 状态 单元测试。"""
from __future__ import annotations

import sys
import unittest
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vocab.config import DEFAULT, load_vocab_config  # noqa: E402
from src.vocab.main import run_slot  # noqa: E402
from src.vocab.notifier import send_email  # noqa: E402
from src.vocab.plan import build_plan, commit_plan, simulate  # noqa: E402
from src.vocab.reading import build_reading, SAMPLE_ARTICLE  # noqa: E402
from src.vocab.render import annotated_to_plain, annotate_article, extract_article_glossary, render_email, render_plain, split_meaning, word_lookup  # noqa: E402
from src.vocab.state import GROUPS, VocabState  # noqa: E402
from src.vocab.words import daily_quota, group_map, split_quota  # noqa: E402


def make_cfg(tmp: str) -> dict:
    cfg = dict(DEFAULT)
    cfg["state_file"] = f"{tmp}/state.json"
    cfg["words_file"] = f"{tmp}/words.json"
    return cfg


def make_items() -> list:
    """构造 40 个词的假词库：四组各 10 个（含示例文章高频词，便于生词表测试）。"""
    items = []
    base_words = ["ability", "cities", "transport", "pollution", "encouraging", "officials", "diesel", "gases", "expanding", "quality"]
    for gi, g in enumerate(GROUPS):
        for i in range(10):
            w = base_words[i] if gi == 0 else f"{g[0]}{gi}{i}"
            items.append({"word": w, "group": g, "meaning": "测试", "phonetic": "", "pos": "n."})
    return items


class TestQuota(unittest.TestCase):
    def test_100_day_finish(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            totals = {g: 10 for g in GROUPS}
            got = {g: 0 for g in GROUPS}
            day = date(2026, 8, 27)
            for i in range(100):
                q = daily_quota(cfg, state, totals, day)
                for g in GROUPS:
                    got[g] += q[g]
                    state.advance_cursor(g, q[g])
                day = day.fromordinal(day.toordinal() + 1)
            self.assertEqual(got, totals)
            # 最后一天配额把剩余推完
            self.assertLessEqual(max(q.values()) if q else 0, 40)

    def test_split_quota_roundtrip(self) -> None:
        quota = {"6研共有": 41, "6级独有": 7, "考研独有": 4, "小初共有": 19}
        m, e = split_quota(quota, 0.5)
        for g in GROUPS:
            self.assertEqual(m[g] + e[g], quota[g])
            self.assertLessEqual(abs(m[g] - e[g]), 1)


class TestSrs(unittest.TestCase):
    def test_morning_word_dued_same_evening(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            groups = group_map(make_items())
            plan = build_plan(cfg, state, groups, date(2026, 8, 27), "morning")
            commit_plan(cfg, state, plan)
            # 晚间：早间新词 next_review=当天 → 出现在复习
            evening = build_plan(cfg, state, groups, date(2026, 8, 27), "evening")
            morning_words = [it["word"] for v in plan["new"].values() for it in v]
            basic_words = {it["word"] for it in groups["小初共有"]}
            self.assertTrue(morning_words)
            for w in morning_words:
                # 小初共有基础词不进入复习板块
                if w in basic_words:
                    self.assertNotIn(w, evening["review"])
                    continue
                self.assertIn(w, evening["review"])
            commit_plan(cfg, state, evening)
            # 次日：间隔推进到第 1 天
            nxt = build_plan(cfg, state, groups, date(2026, 8, 28), "morning")
            self.assertIn(morning_words[0], nxt["review"])

    def test_review_excludes_basic_group(self) -> None:
        """复习板块永不包含小初共有分类的词。"""
        from datetime import timedelta

        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            groups = group_map(make_items())
            # 造一批到期复习词：各分类都有
            today = date(2026, 8, 30)
            for g in GROUPS:
                for it in groups[g][:5]:
                    state.mark_learned(it["word"], today - timedelta(days=3))
            plan = build_plan(cfg, state, groups, today, "morning")
            basic_words = {it["word"] for it in groups["小初共有"]}
            self.assertTrue(plan["review"])
            self.assertFalse(any(w in basic_words for w in plan["review"]))

    def test_evening_takes_remainder_not_full_quota(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            groups = group_map(make_items())
            morning = build_plan(cfg, state, groups, date(2026, 8, 27), "morning")
            commit_plan(cfg, state, morning)
            evening = build_plan(cfg, state, groups, date(2026, 8, 27), "evening")
            for g in GROUPS:
                m = len(morning["new"][g])
                e = len(evening["new"][g])
                self.assertEqual(m + e, morning["quota"][g])


class TestSimulate(unittest.TestCase):
    def test_preview_finishes(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            groups = group_map(make_items())
            rows = simulate(cfg, groups, 100, date(2026, 8, 27))
            self.assertEqual(rows[-1]["learned_total"], 40)
            self.assertEqual(len(rows), 100)


class TestRender(unittest.TestCase):
    def _plan_and_lookup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            items = make_items()
            groups = group_map(items)
            plan = build_plan(cfg, state, groups, date(2026, 8, 27), "morning")
            return cfg, plan, word_lookup(items)

    def test_render_body_sections(self) -> None:
        cfg, plan, lookup = self._plan_and_lookup()
        subject, body = render_plain(cfg, plan, SAMPLE_ARTICLE, lookup, learned_total=37)
        self.assertIn("今日新词", body)
        self.assertIn("回忆单词", body)
        self.assertIn("今日阅读", body)
        self.assertIn("文中生词与重难词汇", body)
        self.assertIn("阅读翻译", body)
        # 阅读板块顺序：生难词 → 文章 → 翻译
        self.assertLess(body.index("文中生词与重难词汇"), body.index("今日阅读"))
        self.assertLess(body.index("今日阅读"), body.index("阅读翻译"))
        self.assertIn("【六级单词打卡】", subject)
        self.assertIn("Day1，37/40", subject)

    def test_render_html_font_and_lines(self) -> None:
        cfg, plan, lookup = self._plan_and_lookup()
        subject, body = render_email(cfg, plan, SAMPLE_ARTICLE, lookup, learned_total=37)
        self.assertIn("font-size:20px", body)
        self.assertIn("<b>", body)
        self.assertIn("【6研共有】", body)
        self.assertIn("文中生词与重难词汇", body)
        self.assertLess(body.index("文中生词与重难词汇"), body.index("阅读翻译"))
        self.assertLess(body.index("文中生词与重难词汇"), body.index("今日阅读"))
        # 文章字号调大 + 下划线/上标标注（词间距已回退为原始排版）
        self.assertIn("font-size:22px;line-height:1.9", body)
        self.assertNotIn("word-spacing", body)
        self.assertIn("<u", body)
        self.assertIn("<sup", body)

    def test_split_meaning(self) -> None:
        segs = split_meaning("v. 离弃，丢弃；遗弃，抛弃；放弃")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["pos"], "v.")
        self.assertIn("离弃", segs[0]["text"])
        segs2 = split_meaning("n. 放任；狂热 v. 遗弃；放弃")
        self.assertEqual(len(segs2), 2)
        self.assertEqual(segs2[0]["pos"], "n.")
        self.assertEqual(segs2[1]["pos"], "v.")
        segs3 = split_meaning("")
        self.assertEqual(segs3, [])

    def test_annotate_article(self) -> None:
        article = "The ability to act quickly matters."
        items = [{"word": "ability", "meaning": "n. 能力", "group": "6研共有", "phonetic": ""}]
        out, matched = annotate_article(article, items)
        self.assertIn('<u style="text-decoration:underline', out)
        self.assertIn("<sup", out)
        self.assertEqual(len(matched), 1)
        # 不命中子串
        out2, matched2 = annotate_article("abilities are useful", items)
        self.assertNotIn("<u", out2)
        self.assertEqual(matched2, [])

    def test_annotate_article_index_sequence(self) -> None:
        article = "Good data matters. Data drives decisions."
        items = [
            {"word": "good", "meaning": "adj. 好的", "group": "6研共有", "phonetic": ""},
            {"word": "data", "meaning": "n. 数据", "group": "6研共有", "phonetic": ""},
        ]
        out, _ = annotate_article(article, items)
        # 编号按生词表全局顺序：good=1, data=2；data 出现两次均为 2
        self.assertIn(">1<", out)
        self.assertEqual(out.count(">2<"), 2)

    def test_extract_article_glossary(self) -> None:
        lookup = {
            "ability": {"word": "ability", "group": "6研共有", "meaning": "n. 能力", "phonetic": ""},
            "basic": {"word": "basic", "group": "小初共有", "meaning": "adj. 基础的", "phonetic": ""},
            "graduate": {"word": "graduate", "group": "考研独有", "meaning": "v. 毕业", "phonetic": ""},
        }
        article = "The ability of every graduate relies on basic skills. Ability matters."
        gloss = extract_article_glossary(article, lookup)
        words = [it["word"] for it in gloss]
        # 按首次出现顺序、去重、跳过小初共有
        self.assertEqual(words, ["ability", "graduate"])


class TestReading(unittest.TestCase):
    def test_mock_returns_sample(self) -> None:
        import os

        os.environ["READING_MOCK"] = "1"
        try:
            cfg = dict(DEFAULT)
            result = build_reading(cfg, date(2026, 8, 27), "morning")
            self.assertIn("article", result)
            self.assertIn("translation", result)
            self.assertGreater(len(result["article"]), 100)
        finally:
            os.environ.pop("READING_MOCK", None)

    def test_llm_rewrite_retries_on_bad_response(self) -> None:
        from unittest import mock

        from src.vocab import reading as reading_mod

        calls = {"n": 0}

        def fake_chat(settings, messages, *, max_tokens=8000):
            calls["n"] += 1
            if calls["n"] == 1:
                return "not json"
            return '{"title": "T", "article": "A short article.", "translation": "一篇短文。"}'

        settings = mock.MagicMock()
        news = {"title": "N", "link": "http://x", "source": "s"}
        with mock.patch.object(reading_mod, "chat", side_effect=fake_chat), mock.patch.object(
            reading_mod, "time", mock.MagicMock()
        ):
            result = reading_mod._llm_rewrite(settings, news, "text", 300, 3000)
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


class TestRunSlot(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["READING_MOCK"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("READING_MOCK", None)

    def _run(self, send_result: bool):
        from unittest import mock

        with TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = VocabState(cfg)
            state.ensure_started(date(2026, 8, 27))
            items = make_items()
            groups = group_map(items)
            lookup = word_lookup(items)
            with mock.patch("src.vocab.main.send_email", return_value=send_result):
                rc = run_slot(
                    cfg, state, groups, lookup, date(2026, 8, 27), "morning",
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
            state.ensure_started(date(2026, 8, 27))
            state.data["email_failures"] = 2
            items = make_items()
            groups = group_map(items)
            with mock.patch("src.vocab.main.send_email", return_value=False), mock.patch(
                "src.vocab.main.send_alert", return_value=False
            ):
                rc = run_slot(cfg, state, groups, word_lookup(items), date(2026, 8, 27), "morning",
                              send=True, commit_only=False)
            self.assertEqual(rc, 1)
            self.assertTrue(state.paused)

    def test_main_handler_parses_timer_event_slot(self) -> None:
        """SCF 定时触发器把入参放 Message 字段，main_handler 应正确解析 slot。"""
        from unittest import mock

        import src.vocab.main as vocab_main

        captured: dict = {}

        def fake_run_slot(cfg, state, groups, lookup, today, slot, *, send, commit_only):
            captured["slot"] = slot
            return 0

        def fake_state(cfg):
            return mock.MagicMock()

        with mock.patch.object(vocab_main, "load_vocab_config", return_value={}), mock.patch.object(
            vocab_main, "run_slot", side_effect=fake_run_slot
        ), mock.patch.object(vocab_main, "make_vocab_state", side_effect=fake_state), mock.patch.object(
            vocab_main, "load_words", return_value=[]
        ), mock.patch.object(vocab_main, "group_map", return_value={}), mock.patch.object(
            vocab_main, "word_lookup", return_value={}
        ):
            timer_event = {
                "Type": "Timer",
                "TriggerName": "v1800",
                "Time": "2026-08-28T10:00:00Z",
                "Message": '{"action": "run", "slot": "evening"}',
            }
            rc = vocab_main.main_handler(timer_event)
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("slot"), "evening")


class TestRealWordlist(unittest.TestCase):
    def test_counts(self) -> None:
        import json

        path = ROOT / "data" / "vocab" / "words.json"
        if not path.exists():
            self.skipTest("words.json 未构建")
        items = json.loads(path.read_text(encoding="utf-8"))
        from collections import Counter

        c = Counter(it["group"] for it in items)
        self.assertEqual(sum(c.values()), 6900)
        self.assertEqual(c["6研共有"], 4010)
        self.assertEqual(c["6级独有"], 663)
        self.assertEqual(c["考研独有"], 343)
        self.assertEqual(c["小初共有"], 1884)


if __name__ == "__main__":
    unittest.main()
