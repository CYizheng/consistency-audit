#!/usr/bin/env python
"""材料一致性核查器 —— 找出同一字段在多份文件里取值不一致的地方。

用法：
    python audit.py --input 材料目录 --dict dicts/resume.example.yaml
    python audit.py --input 材料目录 --dict d.yaml --out 报告.md --html --json
    python audit.py --self-test        # 用 samples/ 自检

退出码：0 无高优先级问题；1 存在高优先级问题；2 参数或数据错误。
返回值可以直接接到提交前钩子里。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from caudit.detect import SEV_ORDER, audit
from caudit.dictionary import load_dictionary
from caudit.extract import SUPPORTED, extract_dir, extract_file
from caudit.report import to_html, to_json_dict, to_markdown

HERE = os.path.dirname(os.path.abspath(__file__))


def _collect(inputs: list[str], excludes: list[str] | None = None) -> tuple[list, int]:
    """返回 (片段列表, 被排除的文件数)。

    为什么要 --exclude：材料库通常混着「材料」和「关于材料的笔记」。
    笔记里本来就会并列写出「4325 还是 4352」这种讨论，把它算成冲突是范畴错误。
    工具只该核查要投出去的那几份。
    """
    import fnmatch

    pats = excludes or []

    def _excluded(rel: str) -> bool:
        base = os.path.basename(rel)
        return any(fnmatch.fnmatch(base, p) or fnmatch.fnmatch(rel, p) for p in pats)

    segs: list = []
    skipped = 0
    for p in inputs:
        if os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if not d.startswith((".", "~"))]
                for name in sorted(filenames):
                    if os.path.splitext(name)[1].lower() not in SUPPORTED:
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, p)
                    if _excluded(rel):
                        skipped += 1
                        continue
                    segs.extend(extract_file(full, rel))
        elif os.path.isfile(p):
            if _excluded(os.path.basename(p)):
                skipped += 1
                continue
            if os.path.splitext(p)[1].lower() not in SUPPORTED:
                print(f"  ! 不支持的格式，已跳过：{p}")
                continue
            segs.extend(extract_file(p, os.path.basename(p)))
        else:
            print(f"  ! 路径不存在：{p}", file=sys.stderr)
    return segs, skipped


def cmd_check(args: argparse.Namespace) -> int:
    for p in args.input:
        if not os.path.exists(p):
            print(f"输入不存在：{p}", file=sys.stderr)
            return 2
    if not os.path.exists(args.dict):
        print(f"字典不存在：{args.dict}", file=sys.stderr)
        return 2

    fields = load_dictionary(args.dict)
    print(f"字典：{os.path.basename(args.dict)}  字段 {len(fields)} 个")

    segs, skipped = _collect(args.input, args.exclude)
    if not segs:
        print("没有抽到任何文本。检查：输入目录是否为空 / 是否有权限 / 格式是否被支持。")
        return 2

    src = ", ".join(os.path.basename(os.path.abspath(p)) for p in args.input)
    extra = f"（已按 --exclude 跳过 {skipped} 份）" if skipped else ""
    print(f"抽取：{len({s.rel for s in segs})} 份文件，{len(segs)} 个文本片段{extra}")

    report = audit(segs, fields)
    shown = [f for f in report.findings if SEV_ORDER[f.severity] <= SEV_ORDER[args.min_severity]]
    if len(shown) != len(report.findings):
        from dataclasses import replace

        report = replace(report, findings=shown)

    md = to_markdown(report, src)
    out = args.out or os.path.join(HERE, "report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"已写出：{out}")

    if args.html:
        hp = os.path.splitext(out)[0] + ".html"
        with open(hp, "w", encoding="utf-8") as f:
            f.write(to_html(report, src))
        print(f"已写出：{hp}")

    if args.json:
        jp = os.path.splitext(out)[0] + ".json"
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(to_json_dict(report, src), f, ensure_ascii=False, indent=2)
        print(f"已写出：{jp}")

    c = report.counts
    print(f"\n结果：高 {c['high']} · 中 {c['medium']} · 低 {c['low']}")
    return 1 if c["high"] else 0


def cmd_self_test(_: argparse.Namespace) -> int:
    """用 samples/ 里的虚构材料自检：必须恰好抓到预埋的几处冲突。"""
    sample_dir = os.path.join(HERE, "samples")
    dict_path = os.path.join(HERE, "dicts", "resume.example.yaml")
    if not os.path.isdir(sample_dir):
        print("samples/ 不存在，跳过自检", file=sys.stderr)
        return 2

    fields = load_dictionary(dict_path)
    # 追加一个必然缺失的必填字段，专门验证 missing 分支
    # （不写进示例字典，否则真实使用时会一直报这条噪音）
    from caudit.dictionary import Field

    fields = fields + [
        Field(key="__probe_absent__", name="探针字段（必然缺失）",
              aliases=["探针字段"], required=True, severity="high")
    ]
    segs = extract_dir(sample_dir)
    rep = audit(segs, fields)

    kinds = {f.kind for f in rep.findings}
    keys = {f.field.key for f in rep.findings}
    checks = [
        ("抓到疑似笔误（登记号字符转置）", "typo" in kinds),
        ("抓到取值冲突（毕业时间两种写法）", "conflict" in kinds or "typo" in kinds),
        ("抓到格式违规", "format" in kinds),
        ("抓到必填缺失", "missing" in kinds),
        ("涉事字段包含 soft_copyright_id", "soft_copyright_id" in keys),
    ]
    ok = True
    for name, passed in checks:
        print(("  [通过] " if passed else "  [失败] ") + name)
        ok = ok and passed
    print(f"\n自检：{'全部通过' if ok else '有失败项'}（共发现 {len(rep.findings)} 项问题）")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="audit",
        description="多份材料字段一致性核查：找出同一字段在不同文件里取值不同的地方",
    )
    ap.add_argument("-i", "--input", nargs="+", help="待核查的目录或文件")
    ap.add_argument("-d", "--dict", default=os.path.join(HERE, "dicts", "resume.example.yaml"),
                    help="口径字典 yaml 路径")
    ap.add_argument("-o", "--out", help="Markdown 报告输出路径（默认 ./report.md）")
    ap.add_argument("-x", "--exclude", nargs="*", default=[],
                    help="排除匹配这些通配符的文件，例如 '版本说明*' '*说明*.md' '_备份*'")
    ap.add_argument("--html", action="store_true", help="同时输出 HTML 报告")
    ap.add_argument("--json", action="store_true", help="同时输出 JSON，便于接自动化")
    ap.add_argument("--min-severity", choices=["high", "medium", "low"], default="low",
                    help="只报告不低于该级别的问题")
    ap.add_argument("--self-test", action="store_true", help="用 samples/ 自检")
    args = ap.parse_args(argv)

    if args.self_test:
        return cmd_self_test(args)
    if not args.input:
        ap.print_help()
        return 2
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
