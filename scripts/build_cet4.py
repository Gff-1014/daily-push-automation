# -*- coding: utf-8 -*-
"""四级词库构建：产出 data/cet4/words.json（三分类 · 基础补强版）。

词表范围（已确认 = 基础补强版）：
    四级大纲词表（KyleBing cet4.txt，4543 词）
    ∪ 小初基础词（小学 elementary.txt + 初中 junior.txt，用于判定基础词与基础补强）
    = 全量 5115 词（四级大纲词 3096 / 基础词 1447 / 基础补强 572）

释义来源顺序：四级词表 → 初中词表 → 六级/考研词库兜底 → 手工补表（19 个纯小学词）。
音标：ipa-dict → 手工表；词频：FrequencyWords en_50k（组内按词频降序）。

用法:
    python scripts/build_cet4.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "vocab" / "raw"
OUT_DIR = ROOT / "data" / "cet4"

# =====================================================================
# 词表范围（基础补强版）：role = cet4 / elementary / junior / ipa / freq
# =====================================================================
SCOPE: List[dict] = [
    {
        "name": "四级大纲词表",
        "path": "cet4.txt",
        "role": "cet4",
        "url": "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/3%20%E5%9B%9B%E7%BA%A7-%E4%B9%B1%E5%BA%8F.txt",
    },
    {
        "name": "小学词表",
        "path": "elementary.txt",
        "role": "elementary",
        "url": "https://raw.githubusercontent.com/busiyiworld/maimemo-export/main/exported/word/%E5%B0%8F%E5%AD%A6%E8%8B%B1%E8%AF%AD%E5%A4%A7%E7%BA%B2%E8%AF%8D%E6%B1%87.txt",
    },
    {
        "name": "初中词表",
        "path": "junior.txt",
        "role": "junior",
        "url": "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/1%20%E5%88%9D%E4%B8%AD-%E4%B9%B1%E5%BA%8F.txt",
    },
    {
        "name": "音标",
        "path": "ipa_en.txt",
        "role": "ipa",
        "url": "https://raw.githubusercontent.com/open-dict-data/ipa-dict/master/data/en_US.txt",
    },
    {
        "name": "词频",
        "path": "en_50k.txt",
        "role": "freq",
        "url": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt",
    },
]

# 19 个纯小学词（不在四级/初中/六级/考研任何释义表内），手工补释义
MANUAL_MEANINGS: Dict[str, str] = {
    "children": "n. 孩子们（child 的复数）",
    "excited": "adj. 兴奋的，激动的",
    "feet": "n. 脚（foot 的复数）",
    "grandma": "n. （口语）奶奶，外婆",
    "grandpa": "n. （口语）爷爷，外公",
    "has": "v. 有（have 的第三人称单数）",
    "ice cream": "n. 冰淇淋",
    "men": "n. 男人们（man 的复数）",
    "mice": "n. 老鼠（mouse 的复数）",
    "mr": "n. 先生（用于男子姓名前）",
    "mrs": "n. 夫人，太太（用于已婚女子姓名前）",
    "mrs.": "n. 夫人，太太（用于已婚女子姓名前）",
    "ms": "n. 女士（婚姻状况不明时用）",
    "ms.": "n. 女士（婚姻状况不明时用）",
    "mum": "n. （英式口语）妈妈",
    "pe": "n. 体育课（physical education 的缩写）",
    "physical education": "n. 体育，体育课",
    "ping-pong": "n. 乒乓球",
    "women": "n. 女人们（woman 的复数）",
    "colour": "n. 颜色；v. 给……着色（= color，英式拼写）",
    "email": "n. 电子邮件；v. 给……发电子邮件",
    "goodbye": "n. 再见",
    "o'clock": "adv. ……点钟",
}

POS_RE = re.compile(r"(?<![a-zA-Z])(n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int|abbr|det)\.")
GROUP_ORDER = {"四级大纲词": 0, "基础词": 1, "基础补强": 2}
NO_RANK = 10**9

BR_TO_US = {
    "flavour": "flavor",
    "tumour": "tumor",
    "vapour": "vapor",
    "appal": "appall",
    "cigaret": "cigarette",
    "despatch": "dispatch",
    "enrol": "enroll",
    "gaol": "jail",
    "gramme": "gram",
    "instal": "install",
    "kilogramme": "kilogram",
    "paralyse": "paralyze",
    "waggon": "wagon",
    "yoghurt": "yogurt",
    "fulfil": "fulfill",
    "labour": "labor",
    "favour": "favor",
    "colour": "color",
    "honour": "honor",
    "behaviour": "behavior",
}

MANUAL_IPA = {
    "up-to-date": "/ˌʌp tə ˈdeɪt/",
    "preposition": "/ˌprɛpəˈzɪʃən/",
    "motorway": "/ˈmoʊtərˌweɪ/",
    "smartphone": "/ˈsmɑrtˌfoʊn/",
    "well-off": "/ˌwɛlˈɔf/",
    "vigour": "/ˈvɪɡər/",
    "instalment": "/ɪnˈstɔlmənt/",
    "antonym": "/ˈæntənɪm/",
    "jetlag": "/ˈdʒɛtˌlæɡ/",
    "knowhow": "/ˈnoʊˌhaʊ/",
    "rigour": "/ˈrɪɡər/",
    "sportswoman": "/ˈspɔrtsˌwʊmən/",
    "webcast": "/ˈwɛbˌkæst/",
    "maths": "/mæθs/",
    "aeroplane": "/ˈɛrəˌpleɪn/",
    "analyse": "/ˈænəˌlaɪz/",
    "favourable": "/ˈfeɪvərəbəl/",
    "reflexion": "/rɪˈflɛkʃən/",
    "systematical": "/ˌsɪstəˈmætɪkəl/",
    "o.k.": "/ˌoʊˈkeɪ/",
    "jewellery": "/ˈdʒuːəlri/",
    "civilisation": "/ˌsɪvələˈzeɪʃən/",
    "organise": "/ˈɔrɡəˌnaɪz/",
    "manoeuvre": "/məˈnuːvər/",
    "litre": "/ˈliːtər/",
    "criticise": "/ˈkrɪtəˌsaɪz/",
    "sympathise": "/ˈsɪmpəˌθaɪz/",
    "skilful": "/ˈskɪlfəl/",
    "fantastical": "/fænˈtæstɪkəl/",
    "specialise": "/ˈspɛʃəˌlaɪz/",
    "fertiliser": "/ˈfɜrtəˌlaɪzər/",
    "minimise": "/ˈmɪnəˌmaɪz/",
    "characterise": "/ˈkɛrəktəˌraɪz/",
    "civilise": "/ˈsɪvəˌlaɪz/",
    "emphasise": "/ˈɛmfəˌsaɪz/",
    "gasolene": "/ˈɡæsəˌlin/",
    "generalise": "/ˈdʒɛnərəˌlaɪz/",
    "industrialise": "/ɪnˈdʌstriəˌlaɪz/",
    "mobilise": "/ˈmoʊbəˌlaɪz/",
    "modernisation": "/ˌmɑdərnəˈzeɪʃən/",
    "normalisation": "/ˌnɔrmələˈzeɪʃən/",
    "statical": "/ˈstætɪkəl/",
    "summarise": "/ˈsʌməˌraɪz/",
    "trolly": "/ˈtrɑli/",
    "utilise": "/ˈjuːtəˌlaɪz/",
    "toothache": "/ˈtuθˌeɪk/",
    "dishonour": "/dɪsˈɑnər/",
    "accessary": "/əkˈsɛsəri/",
    "advocator": "/ˈædvəkeɪtər/",
    "aviate": "/ˈeɪviˌeɪt/",
    "expressiveness": "/ɪkˈsprɛsɪvnəs/",
    "groundlessly": "/ˈɡraʊndləsli/",
    "groundsheet": "/ˈɡraʊndˌʃit/",
    "impermanency": "/ɪmˈpɜrmənənsi/",
    "impermanent": "/ɪmˈpɜrmənənt/",
    "postgraduate": "/ˌpoʊstˈɡrædʒuət/",
    "reframe": "/riˈfreɪm/",
    "remonstrate": "/rɪˈmɑnstreɪt/",
    "repave": "/riˈpeɪv/",
    "pe": "/ˌpiː ˈiː/",
    "adj.": "/ˈædʒɪktɪv/",
    "rusia": "/ˈrʌʃə/",
    "schoolbag": "/ˈskuːlˌbæɡ/",
    "vcd": "/ˌviː siː ˈdiː/",
}


def _download(url: str, dest: Path) -> None:
    print(f"[下载] {dest.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)


def ensure_sources() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for item in SCOPE:
        dest = RAW_DIR / item["path"]
        if not dest.exists():
            _download(item["url"], dest)


def load_txt_map(path: Path) -> Dict[str, str]:
    """KyleBing 乱序 txt：word\\tPOS. 释义；同词多条取最完整的一条。"""
    entries: Dict[str, List[str]] = {}
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            word, meaning = line.split("\t", 1)
            word = word.strip().lower()
            meaning = meaning.strip()
            if word and meaning:
                entries.setdefault(word, []).append(meaning)
    out: Dict[str, str] = {}
    for word, meanings in entries.items():
        out[word] = max(meanings, key=len)
    return out


def load_plain_words(path: Path) -> set:
    """纯单词列表（一行一词）。"""
    if not path.exists():
        return set()
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        w = line.strip().lower()
        if w:
            out.add(w)
    return out


def load_ipa(path: Path) -> Dict[str, str]:
    """ipa-dict：word\\t/音标/"""
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line:
                continue
            word, ipa = line.split("\t", 1)
            word = word.strip().lower()
            ipa = ipa.strip()
            if word and ipa:
                out[word] = ipa
    return out


def load_freq(path: Path) -> Dict[str, int]:
    """FrequencyWords en_50k：按词频降序排列，行号即频率排名。"""
    if not path.exists():
        return {}
    out: Dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for rank, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            word = line.split()[0].strip().lower()
            if word:
                out[word] = rank
    return out


def _eng_to_ipa_word(word: str) -> str:
    try:
        import eng_to_ipa as ipa
    except ImportError:
        return ""
    candidates = [word, word.replace("-", "")]
    base = word.replace("-", "")
    candidates.append(BR_TO_US.get(base, base))
    for c in candidates:
        try:
            s = ipa.convert(c, keep_punct=False, stress_marks="both")
        except Exception:  # noqa: BLE001
            s = ""
        if s and "*" not in s:
            return s
    return ""


def load_phonetic(ipa_map: Dict[str, str], words) -> Dict[str, str]:
    """音标：ipa-dict → 手工表 → eng_to_ipa 兜底。"""
    out: Dict[str, str] = {}
    for w in words:
        if w in ipa_map:
            out[w] = ipa_map[w]
        elif w in MANUAL_IPA:
            out[w] = MANUAL_IPA[w]
    missing = [w for w in words if w not in out]
    for w in missing:
        got = _eng_to_ipa_word(w)
        if got:
            out[w] = got
    return out


def clean_meaning(meaning: str) -> str:
    """清理释义格式：合并空格、去除中文标点后多余空格、去尾部标点。"""
    s = re.sub(r"\s+", " ", meaning.strip())
    s = re.sub(r"([，。；：、,;])\s+", r"\1", s)
    s = re.sub(r"\s+([，。；：、,;])", r"\1", s)
    s = re.sub(r"[\s；;]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_pos(meaning: str) -> str:
    if not meaning:
        return ""
    seen: List[str] = []
    for m in POS_RE.findall(meaning):
        tag = f"{m}."
        if tag not in seen:
            seen.append(tag)
    return "/".join(seen)


def main() -> int:
    ensure_sources()

    cet4_kb: Dict[str, str] = {}
    junior_kb: Dict[str, str] = {}
    elementary_set: set = set()
    ipa_map: Dict[str, str] = {}
    freq_map: Dict[str, int] = {}
    for item in SCOPE:
        path = RAW_DIR / item["path"]
        role = item.get("role", "")
        if role == "cet4":
            cet4_kb = load_txt_map(path)
        elif role == "junior":
            junior_kb = load_txt_map(path)
        elif role == "elementary":
            elementary_set = load_plain_words(path)
        elif role == "ipa":
            ipa_map = load_ipa(path)
        elif role == "freq":
            freq_map = load_freq(path)

    # 释义兜底（只读复用 raw 目录，不属于词表范围）
    cet6_kb = load_txt_map(RAW_DIR / "cet6.txt")
    kaoyan_kb = load_txt_map(RAW_DIR / "kaoyan_kb.txt")

    # 三分类（基础补强版）
    cet4_set = set(cet4_kb)
    junior_set = set(junior_kb)
    base_common = elementary_set | junior_set
    items = []
    missing = []
    scope_words = cet4_set | base_common  # 词表范围 = 四级 ∪ 小初基础
    for word in sorted(scope_words):
        if word in cet4_set and word in base_common:
            group = "基础词"
        elif word in cet4_set:
            group = "四级大纲词"
        else:
            group = "基础补强"
        meaning = clean_meaning(
            cet4_kb.get(word)
            or junior_kb.get(word)
            or cet6_kb.get(word)
            or kaoyan_kb.get(word)
            or MANUAL_MEANINGS.get(word, "")
        )
        if not meaning:
            missing.append(word)
            continue
        items.append(
            {
                "word": word,
                "pos": extract_pos(meaning),
                "meaning": meaning,
                "group": group,
                "phonetic": "",
                "freq_rank": freq_map.get(word),
            }
        )

    # 音标：ipa-dict → 手工表 → eng_to_ipa 兜底
    phon_map = load_phonetic(ipa_map, [it["word"] for it in items])
    for it in items:
        ph = phon_map.get(it["word"], "")
        if ph and not (ph.startswith("/") and ph.endswith("/")):
            ph = f"/{ph}/"
        it["phonetic"] = ph

    items.sort(
        key=lambda it: (
            GROUP_ORDER[it["group"]],
            it["freq_rank"] if it["freq_rank"] is not None else NO_RANK,
            it["word"],
        )
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "words.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 预览 txt
    lines = ["四级大纲词表 ∪ 小初基础（去重后）", f"共 {len(items)} 词（缺失释义 {len(missing)}；缺失音标 {sum(1 for it in items if not it['phonetic'])}）", ""]
    for group in sorted(GROUP_ORDER, key=GROUP_ORDER.get):
        group_items = [it for it in items if it["group"] == group]
        lines.append(f"===== {group}（{len(group_items)} 词）=====")
        for it in group_items:
            ipa = it["phonetic"] or "-"
            lines.append(f"{it['word']}\t{ipa}\t{it['meaning']}")
        lines.append("")
    (OUT_DIR / "词汇表.txt").write_text("\n".join(lines), encoding="utf-8")

    c = Counter(it["group"] for it in items)
    print(f"四级词表: {len(cet4_set)}")
    print(f"小初基础(小学∪初中): {len(base_common)}")
    print(f"词表范围(四级∪小初): {len(scope_words)}")
    print(f"分类: {dict(c)}")
    print(f"缺失释义: {len(missing)}；缺失音标: {sum(1 for it in items if not it['phonetic'])}")
    print(f"输出: {OUT_DIR / 'words.json'}")
    if missing:
        print("缺失释义示例:", missing[:20])
    return 0


if __name__ == "__main__":
    sys.exit(main())
