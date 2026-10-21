"""报告渲染：Markdown 给人读，HTML 给人看。"""

from __future__ import annotations

import datetime as _dt
import html
import os

from .detect import SEV_LABEL, Report

__all__ = ["to_markdown", "to_html", "to_json_dict"]

KIND_LABEL = {
    "conflict": "取值冲突",
    "typo": "疑似笔误",
    "format": "格式违规",
    "missing": "字段缺失",
}


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def to_markdown(report: Report, source: str) -> str:
    c = report.counts
    lines: list[str] = []
    add = lines.append

    add("# 材料一致性核查报告")
    add("")
    add(f"- 生成时间：{_stamp()}")
    add(f"- 输入：`{source}`")
    add(f"- 文件 {len(report.files)} 份，字段 {len(report.fields)} 个，段落/单元格 {len(report.segments)} 个")
    add("")
    add("## 结论")
    add("")
    total = sum(c.values())
    if total == 0:
        add("未发现冲突。所有字段在全部材料中取值一致、格式合规。")
    else:
        add(f"共 {total} 项问题：**高 {c['high']}** · 中 {c['medium']} · 低 {c['low']}。")
    add("")

    if total:
        add("| # | 级别 | 类型 | 字段 | 说明 |")
        add("|---|---|---|---|---|")
        for i, f in enumerate(report.findings, 1):
            add(
                f"| {i} | {SEV_LABEL[f.severity]} | {KIND_LABEL.get(f.kind, f.kind)} "
                f"| {f.field.name} | {f.title} |"
            )
        add("")

        for i, f in enumerate(report.findings, 1):
            add(f"### {i}. [{SEV_LABEL[f.severity]}] {f.title}")
            add("")
            if f.detail:
                for ln in f.detail.splitlines():
                    add(f"- {ln}")
                add("")
            if f.occurrences:
                add("<details><summary>全部出现位置（%d 处）</summary>" % len(f.occurrences))
                add("")
                add("| 取值 | 位置 |")
                add("|---|---|")
                for o in f.occurrences:
                    add(f"| `{o.raw}` | {o.where} |")
                add("")
                add("</details>")
                add("")
            if f.field.note:
                add(f"> 口径备注：{f.field.note}")
                add("")

    # 覆盖矩阵
    add("## 字段覆盖矩阵")
    add("")
    add("`Y` 表示该字段在这份材料里出现过。整列为空说明这份材料没有被任何字段命中——")
    add("要么它确实不含这些字段，要么需要给它补别名。")
    add("")
    matrix = report.coverage()
    header = "| 字段 | " + " | ".join(f.replace("\\", "/") for f in report.files) + " |"
    add(header)
    add("|---" * (len(report.files) + 1) + "|")
    for fld in report.fields:
        cells = [
            "Y" if matrix[fld.key].get(rel) else "·" for rel in report.files
        ]
        add(f"| {fld.name} | " + " | ".join(cells) + " |")
    add("")
    return "\n".join(lines)


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def to_html(report: Report, source: str) -> str:
    c = report.counts
    total = sum(c.values())

    rows = []
    for i, f in enumerate(report.findings, 1):
        detail = "<br>".join(_esc(x) for x in f.detail.splitlines())
        occ = "".join(
            f"<li><code>{_esc(o.raw)}</code> — {_esc(o.where)}</li>"
            for o in f.occurrences
        )
        rows.append(
            f"""<tr class="sev-{f.severity}">
  <td class="num">{i}</td>
  <td><span class="badge b-{f.severity}">{SEV_LABEL[f.severity]}</span></td>
  <td>{_esc(KIND_LABEL.get(f.kind, f.kind))}</td>
  <td><b>{_esc(f.field.name)}</b></td>
  <td><div class="t">{_esc(f.title)}</div>
      {f'<div class="d">{detail}</div>' if detail else ''}
      {f'<details><summary>全部位置（{len(f.occurrences)}）</summary><ul>{occ}</ul></details>' if occ else ''}
  </td>
</tr>"""
        )

    matrix = report.coverage()
    head = "".join(
        f"<th>{_esc(x.replace(chr(92), '/'))}</th>" for x in report.files
    )
    mrows = []
    for fld in report.fields:
        cells = "".join(
            f'<td class="{"yes" if matrix[fld.key].get(rel) else "no"}">'
            f'{"Y" if matrix[fld.key].get(rel) else "·"}</td>'
            for rel in report.files
        )
        mrows.append(f"<tr><th>{_esc(fld.name)}</th>{cells}</tr>")

    body_rows = "".join(rows) or (
        '<tr><td colspan="5" class="ok">未发现冲突</td></tr>'
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>材料一致性核查报告</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e7eb;
--hi:#b42318;--hi-bg:#fef3f2;--md:#b54708;--md-bg:#fffaeb;--lo:#175cd3;--lo-bg:#eff8ff;--ok:#067647}}
*{{box-sizing:border-box}}
body{{margin:0;padding:40px 24px;background:var(--bg);color:var(--fg);
font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1040px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 6px}}
.meta{{color:var(--mut);font-size:13px;margin-bottom:24px}}
.cards{{display:flex;gap:12px;margin:0 0 28px}}
.card{{flex:1;background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px}}
.card .n{{font-size:26px;font-weight:600;line-height:1.2}}
.card .k{{color:var(--mut);font-size:12px;margin-top:4px}}
.c-hi .n{{color:var(--hi)}} .c-md .n{{color:var(--md)}} .c-lo .n{{color:var(--lo)}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);
border-radius:10px;overflow:hidden;font-size:14px}}
th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:#f6f7f9;font-size:12px;color:var(--mut);font-weight:600}}
tr:last-child td,tr:last-child th{{border-bottom:none}}
td.num{{color:var(--mut);width:38px}}
.badge{{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}}
.b-high{{background:var(--hi-bg);color:var(--hi)}} .b-medium{{background:var(--md-bg);color:var(--md)}}
.b-low{{background:var(--lo-bg);color:var(--lo)}}
.t{{font-weight:500}} .d{{color:var(--mut);font-size:13px;margin-top:6px}}
.d code,li code{{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:12.5px}}
details{{margin-top:8px;font-size:13px;color:var(--mut)}}
summary{{cursor:pointer;color:var(--lo)}}
.h2{{font-size:17px;margin:36px 0 12px}}
td.yes{{color:var(--ok);font-weight:600;text-align:center}}
td.no{{color:#d0d5dd;text-align:center}}
.ok{{text-align:center;color:var(--ok);padding:24px}}
</style></head><body><div class="wrap">
<h1>材料一致性核查报告</h1>
<div class="meta">生成于 {_stamp()} · 输入 <code>{_esc(source)}</code> · {len(report.files)} 份文件 · {len(report.fields)} 个字段</div>
<div class="cards">
  <div class="card c-hi"><div class="n">{c['high']}</div><div class="k">高优先级</div></div>
  <div class="card c-md"><div class="n">{c['medium']}</div><div class="k">中优先级</div></div>
  <div class="card c-lo"><div class="n">{c['low']}</div><div class="k">低优先级</div></div>
  <div class="card"><div class="n">{total}</div><div class="k">问题合计</div></div>
</div>
<table><thead><tr><th>#</th><th>级别</th><th>类型</th><th>字段</th><th>说明与证据</th></tr></thead>
<tbody>{body_rows}</tbody></table>
<div class="h2">字段覆盖矩阵</div>
<table><thead><tr><th>字段</th>{head}</tr></thead><tbody>{''.join(mrows)}</tbody></table>
</div></body></html>"""


def to_json_dict(report: Report, source: str) -> dict:
    return {
        "generated_at": _stamp(),
        "source": source,
        "files": report.files,
        "counts": report.counts,
        "findings": [
            {
                "kind": f.kind,
                "severity": f.severity,
                "field": f.field.key,
                "field_name": f.field.name,
                "title": f.title,
                "detail": f.detail,
                "occurrences": [
                    {"raw": o.raw, "norm": o.norm, "file": o.rel, "locator": o.locator}
                    for o in f.occurrences
                ],
            }
            for f in report.findings
        ],
    }
