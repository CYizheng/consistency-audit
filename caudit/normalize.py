"""值归一化：把同一字段的不同写法收敛成可比较的形式。

设计原则：只做「无损」变换（全角转半角、去空白、统一日期分隔符），
不做「猜测性」变换（例如自动补年份、自动展开简称），因为核查器的价值
在于把差异如实报告出来，而不是替人做主。
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "normalize",
    "same_char_multiset",
    "digit_core",
    "NORMALIZERS",
]

_WS = re.compile(r"\s+")
_DATE_SEP = re.compile(r"[./\-年月日\s]")


def _nfkc(s: str) -> str:
    """全角转半角、康熙部首兼容等。NFKC 会把 '（' 变 '('、'１' 变 '1'。"""
    return unicodedata.normalize("NFKC", s).strip()


def _compact(s: str) -> str:
    """去掉所有空白。用于登记号、证书号、编号类字段。"""
    return _WS.sub("", _nfkc(s))


def _date_month(s: str) -> str:
    """2025.3 / 2025-03 / 2025年3月 / 2025/03/01 → 2025-03。"""
    t = _DATE_SEP.sub("-", _nfkc(s))
    m = re.match(r"(\d{4})-(\d{1,2})", t)
    if not m:
        return t
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def _date_day(s: str) -> str:
    """统一到 YYYY-MM-DD；只有年月时返回 YYYY-MM。"""
    t = _DATE_SEP.sub("-", _nfkc(s))
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{4})-(\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return t


def _org(s: str) -> str:
    """单位名：去首尾标点与空白，保留全称差异（不擅自缩写）。"""
    t = _nfkc(s)
    t = t.strip(" ，,。.、；;：:")
    return _WS.sub("", t)


def _text(s: str) -> str:
    return _WS.sub(" ", _nfkc(s)).strip()


NORMALIZERS = {
    "compact": _compact,
    "date_month": _date_month,
    "date_day": _date_day,
    "org": _org,
    "text": _text,
}


def normalize(value: str, mode: str = "text") -> str:
    fn = NORMALIZERS.get(mode)
    if fn is None:
        raise ValueError(f"未知的归一化方式：{mode}（可选：{', '.join(NORMALIZERS)}）")
    return fn(value)


def same_char_multiset(a: str, b: str) -> bool:
    """两串是否只是字符顺序不同（等长、字频相同）。

    这是抓「数字转置笔误」的核心判据：
    2024SR1234567 与 2024SR1234576 长度相同、字频相同，
    但 Levenshtein 相似度只有 85%，用普通模糊匹配会被阈值漏掉。
    """
    if len(a) != len(b) or a == b:
        return False
    return sorted(a) == sorted(b)


def digit_core(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())
