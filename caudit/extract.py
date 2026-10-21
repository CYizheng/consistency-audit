"""把不同格式的材料切成「可定位的文本片段」。

核查器要能说清「冲突出现在哪个文件的哪一段」，所以每种格式都产出一个
Segment，带 locator。locator 的措辞直接给人看，写清楚比写短更重要。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

__all__ = ["Segment", "extract_dir", "extract_file", "SUPPORTED"]

SUPPORTED = {".docx", ".pdf", ".md", ".txt", ".markdown", ".csv"}


@dataclass
class Segment:
    """一段文本 + 它在源文件里的位置。

    表格单元格额外带 cells / cell_index：真实报名表里字段名和值是**分列的**
    （「姓名」在一格、「张三」在下一格），只有拿到整行才能把它们配起来。
    """

    file: str          # 绝对路径
    rel: str           # 相对输入根目录的路径，报告里显示这个
    locator: str       # 人话位置，如「第 12 段」「表 2 第 3 行第 2 列」「第 5 页」
    text: str
    kind: str = "para"  # para / cell / line / page
    cells: list[str] | None = None
    cell_index: int | None = None

    @property
    def short(self) -> str:
        return f"{self.rel} · {self.locator}"


def _docx_segments(path: str, rel: str) -> list[Segment]:
    """段落和表格都要读——真实材料里「毕业时间」常常只出现在表格里。"""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    out: list[Segment] = []

    # 按文档顺序遍历 body 的直接子元素，段落与表格交错出现也保序
    body = doc.element.body
    p_i = 0
    t_i = 0
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p_i += 1
            para = Paragraph(child, doc)
            txt = para.text.strip()
            if txt:
                out.append(Segment(path, rel, f"第 {p_i} 段", txt, "para"))
        elif tag == "tbl":
            t_i += 1
            table = Table(child, doc)
            for r, row in enumerate(table.rows, 1):
                cells = [c.text.strip() for c in row.cells]
                for c_i, ctext in enumerate(cells, 1):
                    if not ctext:
                        continue
                    out.append(
                        Segment(
                            path, rel, f"表 {t_i} 第 {r} 行第 {c_i} 列",
                            ctext, "cell", cells, c_i - 1,
                        )
                    )
    return out


def _pdf_segments(path: str, rel: str) -> list[Segment]:
    import pdfplumber

    out: list[Segment] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            txt = (page.extract_text() or "").strip()
            if txt:
                out.append(Segment(path, rel, f"第 {i} 页", txt, "page"))
    return out


def _text_segments(path: str, rel: str) -> list[Segment]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    return [
        Segment(path, rel, f"第 {i} 行", ln.strip(), "line")
        for i, ln in enumerate(lines, 1)
        if ln.strip()
    ]


_EXTRACTORS = {
    ".docx": _docx_segments,
    ".pdf": _pdf_segments,
    ".md": _text_segments,
    ".markdown": _text_segments,
    ".txt": _text_segments,
    ".csv": _text_segments,
}


def extract_file(path: str, rel: str | None = None) -> list[Segment]:
    """抽一个文件。格式不支持或解析失败时返回空列表并给出提示，不中断整批。"""
    ext = os.path.splitext(path)[1].lower()
    fn = _EXTRACTORS.get(ext)
    if fn is None:
        return []
    rel = rel or os.path.basename(path)
    try:
        return fn(path, rel)
    except Exception as exc:  # 单个坏文件不该让整批失败
        print(f"  ! 跳过 {rel}：{type(exc).__name__}: {exc}")
        return []


def extract_dir(root: str, exclude: Iterable[str] = ()) -> list[Segment]:
    """递归抽取一个目录下所有支持的文件。"""
    root = os.path.abspath(root)
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    segs: list[Segment] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "~"))]
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.normcase(full) in skip:
                continue
            if os.path.splitext(name)[1].lower() not in SUPPORTED:
                continue
            rel = os.path.relpath(full, root)
            segs.extend(extract_file(full, rel))
    return segs
