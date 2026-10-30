# -*- coding: utf-8 -*-
"""核心逻辑单元测试。"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.categories import CHANNEL_FALLBACK_CATEGORY  # noqa: E402
from src.collector.cls import _sign, _build_url  # noqa: E402
from src.collector.cctv import _parse_time  # noqa: E402
from src.collector.normalize import fingerprint, normalize_title  # noqa: E402
from src.collector.pipeline import filter_xwlb_duplicates, window_bounds  # noqa: E402
from src.collector.xwlb import _parse_items  # noqa: E402
from src.collector.cwtx import _edition_minutes, _parse_brief  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.formatter import format_summary  # noqa: E402
from src.keywords import KeywordScorer  # noqa: E402
from src.models import NewsItem  # noqa: E402
from src.main import _parse_timer_event  # noqa: E402
from src.scoring import _heat_match, _section_key, final_score, select_pushed  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_normalize_title(self) -> None:
        self.assertEqual(normalize_title("央视网：习近平 会见 外宾！"), normalize_title("新华网习近平会见外宾"))

    def test_fingerprint_deterministic(self) -> None:
        self.assertEqual(fingerprint("A标题", "http://x/a"), fingerprint("A标题", "http://x/a"))
        self.assertNotEqual(fingerprint("A标题"), fingerprint("B标题"))


class TestClsSign(unittest.TestCase):
    def test_sign(self) -> None:
        qs = "app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9"
        self.assertEqual(len(_sign(qs)), 32)
        url = _build_url("https://www.cls.cn/api/cache", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9", "name": "telegraph"})
        self.assertIn("sign=", url)
        self.assertIn("name=telegraph", url)


class TestParseTime(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(_parse_time("2026-08-26 14:02:11"), datetime(2026, 8, 26, 14, 2, 11))
        self.assertIsNone(_parse_time(""))


class TestKeywordScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.scorer = KeywordScorer(ROOT / "config" / "keywords.json")

    def test_common_word_hits(self) -> None:
        it = NewsItem(url="u", title="国务院发布重大政策文件", summary="")
        score, words = self.scorer.score(it)
        self.assertGreater(score, 0)
        self.assertTrue(any("国务院" in w or "政策" in w for w in words))

    def test_new_term_boost(self) -> None:
        it = NewsItem(url="u", title="我国首款国产大模型正式发布", summary="")
        score, words = self.scorer.score(it)
        self.assertGreater(score, 0)
        self.assertTrue(any(w in ("首款", "正式上线", "发布") for w in words) or len(words) >= 2)

    def test_cap(self) -> None:
        it = NewsItem(
            url="u",
            title="国务院 党中央 习近平 地震 台风 火灾 疫情 战争 首发 问世 突破",
            summary="",
        )
        score, _ = self.scorer.score(it)
        self.assertLessEqual(score, 1.0)


class TestScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()

    def test_section_key(self) -> None:
        self.assertEqual(_section_key("政治"), "政治")
        self.assertEqual(_section_key("文化教育"), "次类")
        self.assertEqual(_section_key("杂类"), "杂类")

    def test_final_score(self) -> None:
        it = NewsItem(url="u", title="t")
        it.llm_score, it.heat_score, it.keyword_score = 8.0, 0.5, 0.6
        s = final_score(it, {"w_llm": 0.6, "w_heat": 0.25, "w_keyword": 0.15})
        self.assertAlmostEqual(s, 100 * (0.6 * 0.8 + 0.25 * 0.5 + 0.15 * 0.6))

    def test_source_bonus(self) -> None:
        from src.scoring import final_score

        it = NewsItem(url="u", title="t", source="央视网·新闻联播")
        it.llm_score, it.heat_score, it.keyword_score = 6.0, 0.0, 0.0
        base = final_score(it, {"w_llm": 0.6, "w_heat": 0.25, "w_keyword": 0.15})
        self.assertEqual(base, 36.0)

        class _Scorer:
            def score(self, item, match_chars=500):
                return 0.0, []

        # 通过 select_pushed 验证加分：基础 52 分，加 8 分后过 60 门槛
        it2 = NewsItem(url="u2", title="t2", source="央视网·新闻联播", category="政治")
        it2.llm_score, it2.heat_score, it2.keyword_score = 8.0, 0.0, 0.3
        with mock.patch("src.scoring.apply_heat_scores", return_value=True), mock.patch(
            "src.scoring.apply_keyword_scores"
        ):
            _, sections, _ = select_pushed([it2], None, self.settings, "evening", _Scorer())
        self.assertEqual(len(dict(sections)["政治"]), 1)

    def test_heat_match(self) -> None:
        self.assertTrue(_heat_match("巴基斯坦医院火灾", "巴基斯坦首都一医院火灾", ["巴基斯坦"]))
        self.assertTrue(_heat_match("习近平", "国家主席习近平将出席峰会", ["习近平"]))
        self.assertFalse(_heat_match("兵哥哥骑车", "工信部加快算力网建设", ["工信部"]))

    def test_threshold_and_caps(self) -> None:
        items = []
        for i in range(15):
            it = NewsItem(url=f"u{i}", title=f"政治新闻{i}")
            it.category = "政治"
            it.llm_score = 10.0
            it.heat_score = 0.0
            it.keyword_score = 0.0
            it.published_at = datetime(2026, 8, 26, 10, i)
            items.append(it)
        items[0].llm_score = 5.0  # 低于 60 分（60*0.6/0.1=60 → 5.0/10*0.6*100=30 <60）
        from src.scoring import apply_keyword_scores

        class _Scorer:
            def score(self, item, match_chars=500):
                return 0.0, []

        apply_keyword_scores(items, _Scorer(), self.settings)
        # 关闭热度：让 heat 不可用走兜底
        with mock.patch("src.scoring.apply_heat_scores", return_value=False):
            speed, sections, heat_ok = select_pushed(items, None, self.settings, "evening", _Scorer())
        self.assertFalse(heat_ok)
        political = dict(sections)["政治"]
        self.assertLessEqual(len(political), 10)  # 上限 10
        self.assertNotIn(items[0], political)  # 30 分被过滤


class TestFormatter(unittest.TestCase):
    def test_format(self) -> None:
        it = NewsItem(
            url="https://example.com/a",
            title="测试新闻",
            category="文化教育",
            one_line_summary="这是一条测试。",
            source="央视网",
        )
        text = format_summary(
            "morning",
            datetime(2026, 8, 26, 8, 30),
            datetime(2026, 8, 26, 9, 0),
            speed_list=[it],
            sections=[("次类", [it])],
        )
        self.assertIn("8月26日新闻与热点（早间）", text)
        self.assertIn("（文化教育）", text)
        self.assertIn("https://example.com/a", text)

    def test_format_hot_topics(self) -> None:
        text = format_summary(
            "morning",
            datetime(2026, 8, 26, 8, 30),
            datetime(2026, 8, 26, 9, 0),
            speed_list=[NewsItem(url="u", title="速览条目", one_line_summary="速览。")],
            sections=[],
            hot_topics=["话题一", "话题二"],
        )
        self.assertIn("今日热点", text)
        self.assertIn("1. 话题一", text)
        self.assertLess(text.index("今日热点"), text.index("今日要闻速览"))


class TestState(unittest.TestCase):
    def test_prune(self) -> None:
        from src.state import StateStore

        with TemporaryDirectory() as tmp:
            settings = load_settings()
            settings.raw["state"]["local_file"] = str(Path(tmp) / "state.json")
            st = StateStore(settings)
            old = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
            st.data["fingerprints"]["fp_old"] = old
            st.data["recent_titles"] = [{"title": "x", "date": old}]
            st.prune()
            self.assertEqual(st.data["fingerprints"], {})
            self.assertEqual(st.data["recent_titles"], [])


class TestWindow(unittest.TestCase):
    def test_morning_window(self) -> None:
        now = datetime(2026, 8, 26, 8, 30)
        start, end = window_bounds({"window_start": "20:30", "window_prev_day": True}, now)
        self.assertEqual(start, datetime(2026, 8, 25, 20, 30))
        self.assertEqual(end, now)


class TestXwlbDedup(unittest.TestCase):
    def test_filter_duplicates(self) -> None:
        xwlb = [NewsItem(url="x", title="全国夏粮收购进入高峰 累计收购总量超9000万吨")]
        items = [
            NewsItem(url="a", title="全国夏粮收购进入高峰 累计收购总量超9000万吨"),
            NewsItem(url="b", title="台风暴雨强对流 中央气象台三预警齐发"),
            NewsItem(url="c", title="夏粮收购进入高峰 累计收购超9000万吨"),
        ]
        kept, skipped = filter_xwlb_duplicates(items, xwlb)
        self.assertEqual(skipped, 2)
        self.assertEqual(kept[0].url, "b")


class TestXwlbParser(unittest.TestCase):
    def test_parse_items(self) -> None:
        body = (
            "1.【新思想引领新征程】为人民出政绩 以实干出政绩；"
            "2.十四届全国人大常委会第二十四次会议在京举行；"
            "3.国内联播快讯：（1）上半年全国新开工口袋公园超2800个；（2）济南黄岗路黄河隧道今天通车；"
            "4.国际联播快讯：（1）法国南部遭龙卷风袭击。"
        )
        items = _parse_items(body)
        self.assertEqual(len(items), 5)
        self.assertIn("为人民出政绩", items[0])
        self.assertIn("十四届全国人大常委会", items[1])
        self.assertIn("口袋公园", items[2])
        self.assertIn("黄河隧道", items[3])
        self.assertIn("龙卷风", items[4])


class TestCwtxEdition(unittest.TestCase):
    def test_edition_minutes(self) -> None:
        self.assertEqual(_edition_minutes("《朝闻天下》 20260826 08:00"), 8 * 60)
        self.assertEqual(_edition_minutes("《朝闻天下》 20260826 06:00"), 6 * 60)
        self.assertIsNone(_edition_minutes("随便一个标题"))

    def test_parse_brief_semicolon(self) -> None:
        body = "台风暴雨强对流，中央气象台三预警齐发；2026年上半年，数字产业收入超20万亿元；加拿大宣布对美国实施报复性关税。"
        items = _parse_brief(body)
        self.assertEqual(len(items), 3)
        self.assertIn("台风暴雨", items[0])


class TestTimerEvent(unittest.TestCase):
    def test_timer_message(self) -> None:
        ev = _parse_timer_event({"Type": "Timer", "TriggerName": "t2030", "Message": '{"action":"run","slot":"evening"}'})
        self.assertEqual(ev["action"], "run")
        self.assertEqual(ev["slot"], "evening")

    def test_timer_trigger_name_fallback(self) -> None:
        ev = _parse_timer_event({"Type": "Timer", "TriggerName": "t2100"})
        self.assertEqual(ev["action"], "email")
        ev2 = _parse_timer_event({"Type": "Timer", "TriggerName": "t0830"})
        self.assertEqual(ev2["slot"], "morning")

    def test_direct_event(self) -> None:
        ev = _parse_timer_event({"action": "resume"})
        self.assertEqual(ev["action"], "resume")
        ev2 = _parse_timer_event('{"action":"email"}')
        self.assertEqual(ev2["action"], "email")

    def test_evening_window(self) -> None:
        now = datetime(2026, 8, 26, 20, 30)
        start, end = window_bounds({"window_start": "08:30", "window_prev_day": False}, now)
        self.assertEqual(start, datetime(2026, 8, 26, 8, 30))
        self.assertEqual(end, now)


if __name__ == "__main__":
    unittest.main()
