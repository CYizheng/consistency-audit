"""口径字典：声明「这个字段叫什么、允许什么格式、算第几级问题」，然后按它去扫材料。

为什么需要字典而不是让程序自己猜字段名：
同一份材料里「毕业时间」可能写成「预计毕业时间」「毕业年月」，
「软著登记号」可能写成「登记号」。这些映射关系是人定的，写下来才能复现、
才能审阅、才能被下一个人接手。程序只负责按字典机械执行。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from .normalize import normalize

__all__ = ["Field", "load_dictionary", "find_values", "SEVERITIES"]

SEVERITIES = ("high", "medium", "low")

# 别名后面允许出现的分隔符，先剥掉再取值
_LEAD_SEP = " \t\u3000:：|｜-—=＝>＞*`「『\"'“”（(【["
# 值到这里为止。真实材料里值后面常常紧跟 Markdown 修饰符或括号注解，
# 不在这里截断就会把 `**`、`（见§三）`、`(监测vs检测` 当成字段值。
_STOP = "|｜;；。\n\r\t`*」』\"'”’）)]】〕>《》,，、：:"
# 取值前后还要再剥一层修饰符
_STRIP = " \t\u3000*`「」『』\"'“”‘’()（）[]【】<>《》,，、;；:：-—"

_MAX_VALUE_LEN = 40

# 真实表单的表头里，字段名右边一格往往还是字段名（「姓名 | 关系 | 工作单位」）。
# 这些词是标签不是取值，遇到就放弃。字典的 allowed 白名单能覆盖枚举类字段，
# 这份清单兜住那些没法枚举的（关系、职务、备注之类）。
LABEL_WORDS = {
    "关系", "称谓", "性别", "年龄", "民族", "籍贯", "出生地", "出生年月",
    "政治面貌", "工作单位", "单位", "职务", "职称", "学历", "学位", "专业",
    "毕业院校", "毕业时间", "备注", "签名", "日期", "时间", "电话", "手机",
    "手机号", "邮箱", "地址", "邮编", "姓名", "婚否", "健康状况", "特长",
    "爱好", "从事工作及职务", "工作单位/职务", "工作单位／职务", "无", "—", "-",
}


def _has_content(v: str) -> bool:
    """值必须含至少一个中日韩字符或字母数字，否则是标点残渣。"""
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in v)


@dataclass
class Field:
    key: str
    name: str
    aliases: list[str]
    pattern: str | None = None
    normalize: str = "text"
    severity: str = "medium"
    required: bool = False
    note: str = ""
    max_len: int | None = None
    allowed: list[str] = dc_field(default_factory=list)
    negatives: list[str] = dc_field(default_factory=list)
    _regex: re.Pattern | None = dc_field(default=None, repr=False)
    _prefix_regex: re.Pattern | None = dc_field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"字段 {self.key} 的 severity 只能是 {SEVERITIES}，收到 {self.severity!r}"
            )
        if self.pattern:
            self._regex = re.compile(self.pattern)
            # 去掉尾部锚点，用同一套格式去「截取合法前缀」
            p = self.pattern[:-1] if self.pattern.endswith("$") else self.pattern
            self._prefix_regex = re.compile(p)

    def format_ok(self, value: str) -> bool:
        """格式校验作用在归一化后的值上，否则「2025 SR 0484352」会被误判。"""
        if self._regex is None:
            return True
        return bool(self._regex.match(value))

    def resolve(self, raw: str) -> str | None:
        """把原始取值变成用于比较的值；判定这一处根本不该算作取值时返回 None。

        三条判据，都是为了在真实材料上把噪声压下去：
        1. 先按 normalize 归一化；
        2. 声明了格式且格式要求数字、而取值里一个数字都没有 —— 这是在讲字段
           （「须与身份证一致」「个人」「出处」），不是在填值，丢弃；
        3. 格式整体不匹配但前缀匹配 —— 值后面粘了正文（PDF 两列粘连、
           「2024SR1234567查证官方名称后统一」），按前缀截断。
        """
        try:
            v = normalize(raw, self.normalize)
        except ValueError:
            v = raw.strip()

        # 长度上限：姓名不该有 17 个字，超了就是抓到了表头或整句
        if self.max_len is not None and len(v) > self.max_len:
            return None

        # 枚举白名单：不在集合里就说明抓到的不是这个字段的值
        if self.allowed and v not in self.allowed:
            return None

        if self._regex is None:
            return v

        if "\\d" in (self.pattern or "") and not any(c.isdigit() for c in v):
            return None

        if self._regex.match(v):
            return v

        if self._prefix_regex is not None:
            m = self._prefix_regex.match(v)
            if m and m.end() > 0:
                return v[: m.end()]
        return v


def load_dictionary(path: str) -> list[Field]:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "fields" not in raw:
        raise ValueError(f"{path} 缺少顶层 fields 列表")

    fields: list[Field] = []
    seen: set[str] = set()
    for item in raw["fields"]:
        if not isinstance(item, dict) or "key" not in item:
            raise ValueError(f"字段定义缺少 key：{item!r}")
        key = item["key"]
        if key in seen:
            raise ValueError(f"字段 key 重复：{key}")
        seen.add(key)
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not aliases:
            raise ValueError(f"字段 {key} 至少要有一个 alias")
        fields.append(
            Field(
                key=key,
                name=item.get("name", key),
                aliases=sorted(aliases, key=len, reverse=True),
                pattern=item.get("pattern"),
                normalize=item.get("normalize", "text"),
                severity=item.get("severity", "medium"),
                required=bool(item.get("required", False)),
                note=item.get("note", ""),
                max_len=item.get("max_len"),
                allowed=list(item.get("allowed") or []),
                negatives=list(item.get("negatives") or []),
            )
        )
    return fields


def find_values(text: str, fld: Field) -> list[str]:
    """在一段文本里找出某字段所有出现处的取值。

    两条判据缺一不可：
    1. 最长别名优先，已消费区间不重复匹配，避免「软著登记号」被「登记号」
       二次命中产生重复记录。
    2. 别名后面必须紧跟分隔符或数字/字母。紧跟汉字时，这句话是在**讲**这个
       字段（「出生年月须与身份证一致」），不是在**填**它，应当跳过——
       否则会把「须与身份证一致」整句当成字段值，这是真实材料上最大的噪声来源。
    """
    taken: list[tuple[int, int]] = []
    hits: list[str] = []

    for alias in fld.aliases:  # 已按长度降序
        start = 0
        while True:
            i = text.find(alias, start)
            if i < 0:
                break
            start = i + len(alias)
            j = i + len(alias)
            if any(a <= i < b for a, b in taken):
                continue

            nxt = text[j] if j < len(text) else ""
            if nxt and nxt not in _LEAD_SEP and not (nxt.isalnum() and nxt.isascii()):
                continue

            # 负例前缀：`校（院）长姓名 陈立言` 里的「姓名」不是本字段。
            # 不能用「左侧是汉字就跳过」这种泛规则——那会把「回执联系手机号」
            # 一起误杀，而它确实是手机号。显式列出不该匹配的前缀，可审计。
            if fld.negatives and any(
                text[i - len(neg) : i] == neg
                for neg in fld.negatives
                if i - len(neg) >= 0
            ):
                continue

            rest = text[j:]
            k = 0
            while k < len(rest) and rest[k] in _LEAD_SEP:
                k += 1
            rest = rest[k:]

            cut = len(rest)
            for stop in _STOP:
                p = rest.find(stop)
                if 0 <= p < cut:
                    cut = p
            value = rest[:cut].strip().strip(_STRIP).strip()
            if not value or len(value) > _MAX_VALUE_LEN or not _has_content(value):
                continue
            if value in LABEL_WORDS:  # 抓到的是相邻单元格的标签，不是值
                continue

            taken.append((i, j + k + len(value)))
            hits.append(value)

    # 按出现位置排序，保证报告里的顺序与原文一致
    hits.sort(key=lambda v: text.find(v))
    return hits


def as_dict(filters: list[str] | None = None) -> dict[str, Any]:
    """给 --print-dict 用，把字段定义以纯文本树打印。"""
    return {"filters": filters or []}
