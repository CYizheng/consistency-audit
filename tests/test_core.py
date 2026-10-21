"""核心判据的单元测试。不依赖 pytest，直接 `python tests/test_core.py` 运行。

只测「加了会坏、坏了看不出来」的那几处：归一化、转置判据、取值截断。
报告渲染和文件抽取属于一改就看得见的部分，交给 --self-test 做端到端验证。

本文件内所有编号、证件号、姓名均为虚构。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caudit.dictionary import Field, find_values
from caudit.normalize import normalize, same_char_multiset

PASS, FAIL = 0, 0

REG_A = "2024SR1234567"   # 虚构登记号
REG_B = "2024SR1234576"   # 与 A 字符组成完全相同、仅顺序不同
REG_C = "2024SR1234568"   # 与 A 只差最后一位，字符组成不同


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [通过] {name}")
    else:
        FAIL += 1
        print(f"  [失败] {name} {extra}")


def test_normalize() -> None:
    print("归一化")
    check(
        "全角转半角 + 去空白",
        normalize(" ２０２４ SR 1234567 ", "compact") == REG_A,
        normalize(" ２０２４ SR 1234567 ", "compact"),
    )
    check("点分隔日期转月份", normalize("2027.06", "date_month") == "2027-06")
    check("中文日期转月份", normalize("2027年7月", "date_month") == "2027-07")
    check("中文日期转日", normalize("2000年02月28日", "date_day") == "2000-02-28")
    check("单位名去首尾标点", normalize("，东岭大学。", "org") == "东岭大学")
    check("单位名不擅自缩写", normalize("东岭大学有限公司", "org") == "东岭大学有限公司")


def test_transposition() -> None:
    print("数字转置判据")
    check("转置两串字符组成相同", same_char_multiset(REG_A, REG_B))
    check("相同串不算转置", not same_char_multiset(REG_A, REG_A))
    check("长度不同不算转置", not same_char_multiset("13800001234", "1380001234"))
    check("末位不同不算转置", not same_char_multiset(REG_A, REG_C))


def test_value_capture() -> None:
    print("取值截断")
    f = Field(
        key="reg", name="登记号",
        aliases=["登记号"], pattern=r"^\d{4}SR\d{7}$", normalize="compact",
    )
    got = find_values(f"登记号：{REG_A}", f)
    check("正常取值", got == [REG_A], got)

    got = find_values(f"登记号`{REG_A}`**——末四位", f)
    check("反引号与星号被剥掉", got == [REG_A], got)

    got = find_values("登记号须与证书一致", f)
    check("讲字段的句子不取值", got == [], got)

    f2 = Field(key="n", name="姓名", aliases=["姓名"], max_len=6,
               negatives=["校（院）长"])
    check("负例前缀被排除",
          find_values("校（院）长姓名 陈立言", f2) == [],
          find_values("校（院）长姓名 陈立言", f2))
    check("普通标签仍能取到",
          find_values("姓名 林小舟", f2) == ["林小舟"],
          find_values("姓名 林小舟", f2))


def test_resolve() -> None:
    print("按格式截取合法前缀")
    f = Field(key="id", name="身份证号", aliases=["身份证号"],
              pattern=r"^\d{17}[\dXx]$", normalize="compact")
    check("粘连正文时按前缀截断",
          f.resolve("310101200002290001期望待遇面议") == "310101200002290001",
          f.resolve("310101200002290001期望待遇面议"))
    check("无数字的整句被丢弃", f.resolve("须与身份证一致") is None)
    check("合法值原样返回", f.resolve("310101200002290001") == "310101200002290001")

    g = Field(key="p", name="政治面貌", aliases=["政治面貌"],
              allowed=["群众", "共青团员"])
    check("枚举白名单外丢弃", g.resolve("从事工作及职务") is None)
    check("枚举白名单内保留", g.resolve("共青团员") == "共青团员")


def main() -> int:
    test_normalize()
    test_transposition()
    test_value_capture()
    test_resolve()
    print(f"\n共 {PASS + FAIL} 项：通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
