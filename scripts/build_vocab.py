# -*- coding: utf-8 -*-
"""词库构建：下载 → 查重 → 四分类（6研共有/6级独有/小初共有/考研独有）+ 音标 + 词频 → 产出 words.json + 预览文件。

音标兜底依赖构建期可选包 eng_to_ipa（仅构建时需要，运行时不需要）：
    uv pip install eng_to_ipa

用法:
    python scripts/build_vocab.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "vocab" / "raw"
OUT_DIR = ROOT / "data" / "vocab"

SOURCES: List[Tuple[str, str]] = [
    (
        "https://raw.githubusercontent.com/busiyiworld/maimemo-export/main/exported/translation/2018%E8%80%83%E7%A0%94%E8%8B%B1%E8%AF%AD%E5%A4%A7%E7%BA%B2%E8%AF%8D%E6%B1%875500.csv",
        "kaoyan5500.csv",
    ),
    (
        "https://raw.githubusercontent.com/busiyiworld/maimemo-export/main/exported/translation/%E5%85%AD%E7%BA%A7%E6%96%B0%E5%A4%A7%E7%BA%B2%E8%AF%8D%E6%B1%87%E8%A1%A8.csv",
        "cet6_new.csv",
    ),
    (
        "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/5%20%E8%80%83%E7%A0%94-%E4%B9%B1%E5%BA%8F.txt",
        "kaoyan_kb.txt",
    ),
    (
        "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/4%20%E5%85%AD%E7%BA%A7-%E4%B9%B1%E5%BA%8F.txt",
        "cet6.txt",
    ),
    (
        "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/3%20%E5%9B%9B%E7%BA%A7-%E4%B9%B1%E5%BA%8F.txt",
        "cet4.txt",
    ),
    (
        "https://raw.githubusercontent.com/open-dict-data/ipa-dict/master/data/en_US.txt",
        "ipa_en.txt",
    ),
    (
        "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt",
        "en_50k.txt",
    ),
    (
        "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/1%20%E5%88%9D%E4%B8%AD-%E4%B9%B1%E5%BA%8F.txt",
        "junior.txt",
    ),
    (
        "https://raw.githubusercontent.com/busiyiworld/maimemo-export/main/exported/word/%E5%B0%8F%E5%AD%A6%E8%8B%B1%E8%AF%AD%E5%A4%A7%E7%BA%B2%E8%AF%8D%E6%B1%87.txt",
        "elementary.txt",
    ),
]

POS_RE = re.compile(r"(?<![a-zA-Z])(n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int|abbr|det)\.")
GROUP_ORDER = {"6研共有": 0, "6级独有": 1, "考研独有": 2, "小初共有": 3}
NO_RANK = 10**9

# 口语/俚语/粗俗词：统一归类到最低优先级「次次选」
SLANG_WORDS = {
    "shit", "fuck", "bitch", "ass", "damn", "bloody", "jerk", "suck", "screw",
    "cock", "pot", "weed", "coke", "heroin", "acid", "joint", "buzz",
    "okay", "ok", "hey", "hi", "cool", "awesome", "buddy", "hell", "holy", "christ",
}


def _download(url: str, dest: Path) -> None:
    print(f"[下载] {dest.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)


def ensure_sources() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for url, name in SOURCES:
        dest = RAW_DIR / name
        if not dest.exists():
            _download(url, dest)


def load_csv_map(path: Path) -> Dict[str, str]:
    """大纲类 CSV：word, meaning（多行释义折叠为一行）。"""
    out: Dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            word = row[0].strip().lower()
            meaning = ""
            if len(row) > 1:
                meaning = "；".join(
                    line.strip() for line in row[1].splitlines() if line.strip()
                )
            if word and meaning:
                out[word] = meaning
    return out


def load_txt_map(path: Path) -> Dict[str, str]:
    """KyleBing 乱序 txt：word\\tPOS. 释义；同词多条取最完整的一条。"""
    entries: Dict[str, List[str]] = {}
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
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        w = line.strip().lower()
        if w:
            out.add(w)
    return out


def load_ipa(path: Path) -> Dict[str, str]:
    """ipa-dict：word\t/音标/"""
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
}


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

    kaoyan_csv = load_csv_map(RAW_DIR / "kaoyan5500.csv")
    cet6_csv = load_csv_map(RAW_DIR / "cet6_new.csv")
    kaoyan_kb = load_txt_map(RAW_DIR / "kaoyan_kb.txt")
    cet6_kb = load_txt_map(RAW_DIR / "cet6.txt")
    cet4_kb = load_txt_map(RAW_DIR / "cet4.txt")
    cet4_set = set(cet4_kb)
    elementary_set = load_plain_words(RAW_DIR / "elementary.txt")
    junior_set = set(load_txt_map(RAW_DIR / "junior.txt"))
    ipa_map = load_ipa(RAW_DIR / "ipa_en.txt")
    freq_map = load_freq(RAW_DIR / "en_50k.txt")

    kaoyan_set = set(kaoyan_csv)
    cet6_set = set(cet6_csv)
    core = kaoyan_set & cet6_set
    sub1 = cet6_set - kaoyan_set  # 次选：六级独有
    union = kaoyan_set | cet6_set | cet4_set  # 考研 ∪ 六级 ∪ 四级（全部常见词）
    base_common = elementary_set | junior_set  # 小初共有：小学 ∪ 初中
    core_set = (kaoyan_set & cet6_set) | cet4_set  # 6研共有：考研∩六级 ∪ 四级
    sub1_set = cet6_set - kaoyan_set  # 6级独有：六级独有

    def pick_meaning(word: str) -> str:
        for m in (
            kaoyan_kb.get(word),
            cet6_kb.get(word),
            cet4_kb.get(word),
            kaoyan_csv.get(word),
            cet6_csv.get(word),
        ):
            if m:
                return clean_meaning(m)
        return ""

    items = []
    missing = []
    for word in sorted(union):
        if word in SLANG_WORDS:
            group = "考研独有"
        elif word in base_common:
            group = "小初共有"  # 基础词优先（小学/初中）
        elif word in core_set:
            group = "6研共有"
        elif word in sub1_set:
            group = "6级独有"
        else:
            group = "考研独有"
        meaning = pick_meaning(word)
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

    # 预览 txt：分组分段
    lines = ["考研词汇表 ∪ 六级词汇表（去重后）", f"共 {len(items)} 词（缺失释义 {len(missing)}；缺失音标 {sum(1 for it in items if not it['phonetic'])}）", ""]
    for group in sorted(GROUP_ORDER, key=GROUP_ORDER.get):
        group_items = [it for it in items if it["group"] == group]
        lines.append(f"===== {group}（{len(group_items)} 词）=====")
        for it in group_items:
            ipa = it["phonetic"] or "-"
            lines.append(f"{it['word']}\t{ipa}\t{it['meaning']}")
        lines.append("")
    (OUT_DIR / "词汇表.txt").write_text("\n".join(lines), encoding="utf-8")

    # 预览 csv：便于 Excel 查看
    with open(OUT_DIR / "词汇表.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["单词", "词性", "音标", "汉意", "分类"])
        for it in items:
            writer.writerow([it["word"], it["pos"], it["phonetic"], it["meaning"], it["group"]])

    print(f"考研大纲表: {len(kaoyan_set)}")
    print(f"六级新大纲表: {len(cet6_set)}")
    print(f"6研共有(考研∩六级 ∪ 四级): {len(core_set)}")
    print(f"6级独有(六级独有): {len(sub1_set)}")
    print(f"小初共有(小学∪初中): {len(base_common)}")
    print(f"并集(全部推送): {len(items)}（缺失释义 {len(missing)}）")
    print(f"缺失音标: {sum(1 for it in items if not it['phonetic'])}")
    print(f"有词频排名: {sum(1 for it in items if it['freq_rank'] is not None)}")
    print(f"输出: {OUT_DIR / 'words.json'}")
    print(f"输出: {OUT_DIR / '词汇表.txt'}")
    print(f"输出: {OUT_DIR / '词汇表.csv'}")
    if missing:
        print("缺失释义示例:", missing[:20])
    return 0


if __name__ == "__main__":
    sys.exit(main())
