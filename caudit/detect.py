"""冲突检测：把「同一字段在不同文件里取值不一致」变成一张可处置的清单。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field as dc_field

from rapidfuzz import fuzz

from .dictionary import LABEL_WORDS as _LABEL_WORDS
from .dictionary import Field, find_values
from .extract import Segment
from .normalize import digit_core, normalize, same_char_multiset

__all__ = ["Occurrence", "Finding", "Report", "audit"]

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SEV_LABEL = {"high": "高", "medium": "中", "low": "低"}


@dataclass
class Occurrence:
    field_key: str
    field_name: str
    raw: str
    norm: str
    rel: str
    locator: str

    @property
    def where(self) -> str:
        return f"{self.rel} · {self.locator}"


@dataclass
class Finding:
    kind: str  # conflict / typo / format / missing
    severity: str
    field: Field
    title: str
    detail: str = ""
    occurrences: list[Occurrence] = dc_field(default_factory=list)

    @property
    def rank(self) -> int:
        return SEV_ORDER[self.severity]


@dataclass
class Report:
    files: list[str]
    fields: list[Field]
    findings: list[Finding]
    occurrences: dict[str, list[Occurrence]]
    segments: list[Segment]

    @property
    def counts(self) -> dict[str, int]:
        c = {"high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            c[f.severity] += 1
        return c

    def coverage(self) -> dict[str, dict[str, bool]]:
        """字段 × 文件 的覆盖矩阵：哪个字段在哪份材料里压根没出现。"""
        matrix: dict[str, dict[str, bool]] = {}
        for fld in self.fields:
            per_file = {rel: False for rel in self.files}
            for occ in self.occurrences.get(fld.key, []):
                per_file[occ.rel] = True
            matrix[fld.key] = per_file
        return matrix


def _looks_typo(a: str, b: str) -> bool:
    """判断两个取值是否像「同一个东西打错了」。

    只用字符重排判据，不用普通模糊相似度——
    相似度阈值 85% 以下会把 0484352 / 0484325 这类转置错误整批漏掉，
    而放宽到 80% 又会把两个真实不同的编号误报。
    """
    if len(a) < 5:
        return False
    digits = len(digit_core(a))
    if digits < 4 and len(a) < 8:
        return False
    return same_char_multiset(a, b)


def _pair_typos(values: list[str]) -> list[tuple[str, str, str, float]]:
    """返回疑似笔误的取值对：(a, b, 类型, 相似度)。

    两种类型要分开说，因为它们指向完全不同的修法：
      reorder —— 字符组成完全相同、只是顺序不同，典型是数字转置，
                 必须靠字符重排判据，普通模糊匹配会漏；
      similar —— 高度相似但长度不等，典型是漏字/多字，
                 修法是补齐而不是换顺序。
    把这两件事都笼统说成「转置」，会让人去查一个根本不存在的问题。
    """
    out: list[tuple[str, str, str, float]] = []
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            if _looks_typo(a, b):
                out.append((a, b, "reorder", 100.0))
                continue
            score = fuzz.ratio(a, b)
            if score >= 90 and len(a) >= 8 and len(b) >= 8:
                out.append((a, b, "similar", score))
    return out


def _pair_table_cells(segments: list[Segment], fields: list[Field],
                      occurrences: dict[str, list[Occurrence]]) -> None:
    """表格里字段名与取值分列，普通「别名+值」规则抓不到。

    例如一行是 ['姓名', '张三', '关系', '父亲']：
    只按文本匹配，「姓名」这一格后面没有值可抓；必须按位置把右侧相邻的
    非空单元格配过来。这是真实报名表的常态，不做这一步等于漏掉整张表。
    """
    import re

    alias_to_field: dict[str, Field] = {}
    for fld in fields:
        for a in fld.aliases:
            alias_to_field.setdefault(a, fld)

    seen: set[tuple[str, str, str]] = {
        (o.field_key, o.rel, o.locator)
        for occ_list in occurrences.values()
        for o in occ_list
    }

    for seg in segments:
        if seg.kind != "cell" or not seg.cells or seg.cell_index is None:
            continue
        head = seg.text.strip()
        fld = alias_to_field.get(head)
        if fld is None:
            continue
        if (fld.key, seg.rel, seg.locator) in seen:
            continue

        for j in range(seg.cell_index + 1, len(seg.cells)):
            val = seg.cells[j].strip().strip(" \t\u3000:：|｜*`")
            if not val or val == head:
                continue
            if val in alias_to_field or val in _LABEL_WORDS:  # 撞到表头，说明这一行没填值
                break
            norm = fld.resolve(val)
            if norm is None:  # 这一格不是值，是标签或说明文字
                break
            loc = re.sub(r"第\s*\d+\s*列$", f"第 {j + 1} 列", seg.locator)
            occurrences[fld.key].append(
                Occurrence(fld.key, fld.name, val, norm, seg.rel, loc)
            )
            seen.add((fld.key, seg.rel, loc))
            break


def audit(segments: list[Segment], fields: list[Field]) -> Report:
    occurrences: dict[str, list[Occurrence]] = defaultdict(list)

    for seg in segments:
        for fld in fields:
            for raw in find_values(seg.text, fld):
                norm = fld.resolve(raw)
                if norm is None:
                    continue
                occurrences[fld.key].append(
                    Occurrence(fld.key, fld.name, raw, norm, seg.rel, seg.locator)
                )

    _pair_table_cells(segments, fields, occurrences)

    files = sorted({s.rel for s in segments})
    findings: list[Finding] = []

    for fld in fields:
        occs = occurrences.get(fld.key, [])

        # 1) 缺失（必填字段一个都没抓到）
        if not occs:
            if fld.required:
                findings.append(
                    Finding(
                        "missing",
                        fld.severity,
                        fld,
                        f"必填字段「{fld.name}」在所有材料里都没有出现",
                        "检查材料是否漏页，或别名是否漏配（可在字典里补 alias）",
                    )
                )
            continue

        # 2) 格式违规
        bad = [o for o in occs if not fld.format_ok(o.norm)]
        if bad:
            findings.append(
                Finding(
                    "format",
                    fld.severity,
                    fld,
                    f"「{fld.name}」有 {len(bad)} 处不符合声明格式",
                    f"约束：{fld.pattern}",
                    bad,
                )
            )

        # 3) 取值冲突
        groups: dict[str, list[Occurrence]] = defaultdict(list)
        for o in occs:
            groups[o.norm].append(o)
        if len(groups) > 1:
            values = sorted(groups)
            typos = _pair_typos(values)
            kinds = {t[2] for t in typos}
            if kinds == {"reorder"}:
                suffix, kind = "，其中含疑似数字转置", "typo"
            elif kinds == {"similar"}:
                suffix, kind = "，其中含高度相似的值（疑似漏字/多字）", "typo"
            elif kinds:
                suffix, kind = "，其中含疑似笔误", "typo"
            else:
                suffix, kind = "", "conflict"
            title = f"「{fld.name}」存在 {len(groups)} 个不同取值" + suffix
            detail_parts = []
            for v in values:
                places = "；".join(o.where for o in groups[v])
                detail_parts.append(f"`{v}`（{len(groups[v])} 处）：{places}")
            for a, b, k, score in typos:
                if k == "reorder":
                    detail_parts.append(
                        f"疑似数字转置：`{a}` ↔ `{b}`（字符组成完全相同，仅顺序不同）"
                    )
                else:
                    detail_parts.append(
                        f"高度相似：`{a}` ↔ `{b}`（相似度 {score:.0f}%，长度不同，疑似漏字或多字）"
                    )
            findings.append(
                Finding(
                    kind,
                    fld.severity,
                    fld,
                    title,
                    "\n".join(detail_parts),
                    [o for v in values for o in groups[v]],
                )
            )

    findings.sort(key=lambda f: (f.rank, f.field.key))
    return Report(files, fields, findings, dict(occurrences), segments)
