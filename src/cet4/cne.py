# -*- coding: utf-8 -*-
"""每日汉译英一句：早间 / 晚间各一句，用当日新词出题，参考答案紧随其后（空行分隔）。"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List

from src.cet4.llm import chat, make_llm_settings, parse_json

SAMPLE_CNE: Dict[str, str] = {
    "prompt": "越来越多的人认识到，保护环境对人们的健康起着重要作用。",
    "answer": "More and more people have realized that protecting the environment plays an important role in people's health.",
    "hint": "现在完成时 have realized；宾语从句 that...；固定搭配 play an important role in；动名词 protecting the environment 作主语",
    "clause": {
        "type": "定语从句",
        "prompt": "住在城市里的人们越来越重视空气的质量。",
        "answer": "People who live in cities are paying more and more attention to the quality of the air.",
        "explain": "先行词 people；关系代词 who 引导定语从句（who live in cities 修饰 people）；定语从句作主语修饰语。",
    },
}

CLAUSE_TYPES = ["宾语从句", "定语从句", "状语从句", "主语从句", "表语从句", "同位语从句"]

# 内置句子池：LLM 不可用/返回重复时的兜底，按"未用过优先"轮换，保证每天句子不同
CNE_POOL: List[Dict[str, Any]] = [
    {
        "prompt": "只有通过努力学习，学生才能实现他们的梦想。",
        "answer": "Only by studying hard can students realize their dreams.",
        "hint": "only+介词短语置于句首引起部分倒装；realize one's dream",
        "clause": {"type": "状语从句", "prompt": "只要坚持练习，你就能说一口流利的英语。", "answer": "As long as you keep practicing, you will be able to speak fluent English.", "explain": "as long as 引导条件状语从句；主将从现。"},
    },
    {
        "prompt": "随着科技的发展，人们的生活方式发生了巨大的变化。",
        "answer": "With the development of science and technology, great changes have taken place in people's way of life.",
        "hint": "with+名词短语作伴随状语；现在完成时；take place",
        "clause": {"type": "主语从句", "prompt": "众所周知，智能手机在我们的日常生活中扮演着重要角色。", "answer": "It is well known that smart phones play an important role in our daily life.", "explain": "It 作形式主语，that 从句为真正主语。"},
    },
    {
        "prompt": "这个传统节日已经有几千年的历史了。",
        "answer": "This traditional festival has a history of thousands of years.",
        "hint": "现在完成时；have a history of；thousands of",
        "clause": {"type": "表语从句", "prompt": "问题是传统文化能否在现代社会得以传承。", "answer": "The question is whether traditional culture can be passed down in modern society.", "explain": "系动词 is 后接 whether 引导的表语从句。"},
    },
    {
        "prompt": "医生建议人们每天进行至少三十分钟的锻炼。",
        "answer": "Doctors suggest that people should take at least thirty minutes of exercise every day.",
        "hint": "suggest+that 宾语从句用 should+动词原形；take exercise",
        "clause": {"type": "宾语从句", "prompt": "研究表明，充足的睡眠对学生的成绩有很大影响。", "answer": "Studies show that enough sleep has a great influence on students' performance.", "explain": "show 后接 that 引导的宾语从句；have a great influence on。"},
    },
    {
        "prompt": "政府正在采取有效措施来解决交通拥堵问题。",
        "answer": "The government is taking effective measures to solve the problem of traffic jams.",
        "hint": "现在进行时；take measures to do；solve the problem of",
        "clause": {"type": "定语从句", "prompt": "我们应该减少那些对环境有害的行为。", "answer": "We should reduce those activities that are harmful to the environment.", "explain": "先行词 activities；关系代词 that 引导定语从句；be harmful to。"},
    },
    {
        "prompt": "这个项目旨在帮助学生培养独立思考的能力。",
        "answer": "This project is designed to help students develop the ability to think independently.",
        "hint": "be designed to do；develop the ability to do；不定式作目的状语",
        "clause": {"type": "主语从句", "prompt": "对学生来说，掌握一门外语是很重要的。", "answer": "It is important for students to master a foreign language.", "explain": "It 作形式主语，真正主语为不定式短语 to master a foreign language。"},
    },
    {
        "prompt": "人们普遍认为网络给我们的生活带来了便利。",
        "answer": "It is generally believed that the Internet has brought convenience to our life.",
        "hint": "It is believed that... 被动语态固定句型；bring convenience to",
        "clause": {"type": "同位语从句", "prompt": "我们听到了一个消息，说学校将举办一次英语演讲比赛。", "answer": "We heard the news that the school would hold an English speech contest.", "explain": "that 从句解释说明 news 的内容，为同位语从句。"},
    },
    {
        "prompt": "节约用水是我们每个人都应该做的事情。",
        "answer": "Saving water is something that every one of us should do.",
        "hint": "动名词 Saving water 作主语；定语从句 that...",
        "clause": {"type": "表语从句", "prompt": "这就是为什么越来越多的人选择绿色出行。", "answer": "That is why more and more people choose green travel.", "explain": "why 引导表语从句，说明原因。"},
    },
    {
        "prompt": "如果你经常锻炼，你就不容易生病。",
        "answer": "If you exercise regularly, you will not get sick easily.",
        "hint": "if 条件状语从句主将从现；regularly 副词",
        "clause": {"type": "状语从句", "prompt": "无论遇到什么困难，我们都应该保持乐观。", "answer": "No matter what difficulties we meet, we should stay optimistic.", "explain": "No matter what 引导让步状语从句；stay optimistic 系表结构。"},
    },
    {
        "prompt": "越来越多的人开始重视传统文化的保护。",
        "answer": "More and more people are beginning to attach importance to the protection of traditional culture.",
        "hint": "现在进行时；attach importance to；beginning to do",
        "clause": {"type": "定语从句", "prompt": "这是一个有着悠久历史的城市。", "answer": "This is a city which has a long history.", "explain": "先行词 city；关系代词 which 引导定语从句。"},
    },
    {
        "prompt": "志愿者工作对社会的发展起着积极的作用。",
        "answer": "Volunteer work plays a positive role in the development of society.",
        "hint": "一般现在时表客观事实；play a positive role in",
        "clause": {"type": "主语从句", "prompt": "很明显，教育对个人发展非常重要。", "answer": "It is obvious that education is of great importance to personal development.", "explain": "It 作形式主语，that 从句为真正主语；be of great importance。"},
    },
    {
        "prompt": "老师鼓励我们参加各种课外活动。",
        "answer": "The teacher encourages us to take part in various after-school activities.",
        "hint": "encourage sb to do；take part in；various",
        "clause": {"type": "宾语从句", "prompt": "我认为我们应该把更多时间花在阅读上。", "answer": "I think that we should spend more time on reading.", "explain": "think 后接 that 宾语从句；spend time on sth。"},
    },
    {
        "prompt": "这款新软件使得人们能够更方便地交流。",
        "answer": "This new software makes it possible for people to communicate more conveniently.",
        "hint": "make it+形容词+for sb to do；副词修饰动词",
        "clause": {"type": "表语从句", "prompt": "原因是我们每天都依赖手机。", "answer": "The reason is that we depend on mobile phones every day.", "explain": "The reason is that... 表语从句；depend on。"},
    },
    {
        "prompt": "缺乏锻炼可能会导致许多健康问题。",
        "answer": "Lack of exercise may lead to many health problems.",
        "hint": "lack of 名词短语作主语；may lead to",
        "clause": {"type": "同位语从句", "prompt": "有证据表明锻炼能改善情绪。", "answer": "There is evidence that exercise can improve mood.", "explain": "that 从句解释 evidence 的内容，为同位语从句。"},
    },
    {
        "prompt": "我们应该采取措施减少空气污染。",
        "answer": "We should take measures to reduce air pollution.",
        "hint": "take measures to do；不定式作目的状语",
        "clause": {"type": "状语从句", "prompt": "既然下雨了，我们最好待在家里。", "answer": "Since it is raining, we had better stay at home.", "explain": "Since 引导原因状语从句；had better do。"},
    },
    {
        "prompt": "这个博物馆每年吸引成千上万的游客。",
        "answer": "This museum attracts thousands of visitors every year.",
        "hint": "一般现在时；thousands of",
        "clause": {"type": "定语从句", "prompt": "这是我读过的最有趣的一本书。", "answer": "This is the most interesting book that I have ever read.", "explain": "先行词 book 被最高级修饰，定语从句用 that；现在完成时 have ever read。"},
    },
    {
        "prompt": "大学教育在塑造一个人的性格方面发挥着重要作用。",
        "answer": "College education plays an important part in shaping one's character.",
        "hint": "play an important part in；动名词 shaping 作介词宾语",
        "clause": {"type": "主语从句", "prompt": "是否参加这次活动由你自己决定。", "answer": "Whether you will take part in the activity is up to you.", "explain": "Whether 引导主语从句置于句首；be up to sb。"},
    },
    {
        "prompt": "互联网使人们能够足不出户了解世界。",
        "answer": "The Internet enables people to know about the world without leaving home.",
        "hint": "enable sb to do；without doing；不定式作宾补",
        "clause": {"type": "宾语从句", "prompt": "科学家相信人工智能将改变我们的生活。", "answer": "Scientists believe that artificial intelligence will change our life.", "explain": "believe 后接 that 宾语从句；一般将来时。"},
    },
    {
        "prompt": "政府已经采取措施来保护森林资源。",
        "answer": "The government has taken measures to protect forest resources.",
        "hint": "现在完成时；take measures to do；不定式作目的状语",
        "clause": {"type": "表语从句", "prompt": "这就是我们为什么必须节约能源。", "answer": "That is why we must save energy.", "explain": "why 引导表语从句说明原因。"},
    },
]

LLM_SYSTEM = """你是英语四级备考的出题老师。请用给定的 1-3 个四级词汇，生成一句标准的四级翻译题型中文句子：
1. 句子 20-40 字，话题贴近四级翻译常考内容（校园、社会、科技、文化、环境、健康等）；
2. 必须书面化、正式，严禁口语化表达（如"哦、好的、那个家伙、挺、真让人无奈"等一律禁止）；
3. 句子必须包含明确考点：至少一个语法点（时态、被动语态、定语从句、状语从句、宾语从句、非谓语、比较级、倒装等）
   和至少一个固定短语搭配（如 make full use of、play an important role in、be of great importance、
   pay attention to、be used to doing 等，出题时只用中文呈现）；
4. 题目只给中文，不出现英文，不能把答案直接写在题目里；
5. 参考译文必须自然使用给定词汇（可变形），并体现上述语法点与短语；
6. 另需按给定的从句类型，生成一条「从句应用」练习（中文句子 + 英文参考译文 + 通俗讲解），
   句型必须体现该从句类型，作为该日从句考点的应用示范；
7. 输出必须是合法 JSON：
   {"prompt": "中文题目", "answer": "参考英文译文", "hint": "考点提示（语法点 + 固定短语 + 词汇用词提示）",
    "clause": {"type": "从句类型", "prompt": "从句应用中文句子", "answer": "英文参考译文", "explain": "通俗讲解（先行词/关系词/引导词/位置等）"}}。
"""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _new_word_hints(plan: Dict[str, Any]) -> List[str]:
    """从当日新词取最多 3 个作为出题用词。"""
    words: List[str] = []
    for items in plan.get("new", {}).values():
        for it in items:
            if len(words) >= 3:
                return words
            words.append(it.get("word", ""))
    return words


def _pick_pool_cne(state) -> Dict[str, Any]:
    """从内置句子池取一句未用过的题目；全部用过则按顺序轮换。"""
    used = state.cne_used_prompts(60) if state is not None else []
    for item in CNE_POOL:
        if item["prompt"] not in used:
            return dict(item)
    return dict(CNE_POOL[len(used) % len(CNE_POOL)])


def build_cne(
    cfg: Dict[str, Any],
    plan: Dict[str, Any],
    today: date,
    slot: str,
    state=None,
) -> Dict[str, Any]:
    settings = make_llm_settings(cfg)
    if not cfg.get("cne", {}).get("enabled", True):
        return {}
    if _env("CNE_MOCK") == "1" or not settings.deepseek_api_key:
        return dict(SAMPLE_CNE)
    hints = _new_word_hints(plan)
    if not hints:
        return _pick_pool_cne(state)
    used = state.cne_used_prompts(30) if state is not None else []
    clause_type = CLAUSE_TYPES[today.toordinal() % len(CLAUSE_TYPES)]
    history_block = (
        "\n近期已用题目（新题不得与其中任何一句相同或雷同）：\n"
        + "\n".join(f"- {p}" for p in used[-15:])
        if used
        else ""
    )
    try:
        messages = [
            {"role": "system", "content": LLM_SYSTEM + history_block},
            {
                "role": "user",
                "content": f"给定词汇：{'、'.join(hints)}\n今日从句类型：{clause_type}",
            },
        ]
        data = parse_json(chat(settings, messages, max_tokens=6000) or "")
        prompt = (data.get("prompt") or "").strip() if data else ""
        answer = (data.get("answer") or "").strip() if data else ""
        if prompt and answer and prompt not in used:
            clause = data.get("clause") or {}
            clause_item = (
                {
                    "type": (clause.get("type") or clause_type).strip(),
                    "prompt": (clause.get("prompt") or "").strip(),
                    "answer": (clause.get("answer") or "").strip(),
                    "explain": (clause.get("explain") or "").strip(),
                }
                if (clause.get("prompt") or "").strip() and (clause.get("answer") or "").strip()
                else {}
            )
            return {
                "prompt": prompt,
                "answer": answer,
                "hint": (data.get("hint") or "").strip(),
                "clause": clause_item,
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[汉译英] LLM 生成失败，改用内置句子池：{exc!r}")
    return _pick_pool_cne(state)
