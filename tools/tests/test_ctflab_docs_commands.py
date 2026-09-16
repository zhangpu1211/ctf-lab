#!/usr/bin/env python3
"""文档命令回归测试：文档里的 ctflab 命令必须能被当前 CLI 正确解析。

检查分两层：

- fenced 代码块中的命令（视为可复制执行的示例）做完整校验：子命令、选项、
  位置参数数量，以及带 choices 的位置参数取值；
- 行内代码只校验子命令与选项是否存在（正文常以 ``ctflab inspect`` 形式引用命令，
  不带位置参数，不适合做位置参数校验）。

文档里出现的、尚未通过 ``onboard`` 建立的示例 profile 需要列入
``PLACEHOLDER_PROFILES``，否则按无效 profile 报错。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shlex
import sys
import unittest

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402

FENCED_BLOCK = re.compile(r"```[a-zA-Z0-9]*\n(.*?)```", re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
COMMAND = re.compile(r"(?:\./tools/)?ctflab\s+([a-z][a-z0-9-]*)((?:[^\n`#&|;]*))")
DOC_PATHS = [PROJECT_ROOT / "README.md"] + sorted((PROJECT_ROOT / "docs").glob("*.md"))

# 文档示例中尚未 onboard 的候选 profile（inspect/onboard 之后才会存在）。
PLACEHOLDER_PROFILES = {"machine-1", "new-machine"}


def command_spec() -> tuple[dict[str, argparse.ArgumentParser], dict[str, argparse.Action]]:
    parser = ctflab.build_parser()
    subcommands: dict[str, argparse.ArgumentParser] = {}
    for action in parser._subparsers._group_actions:
        subcommands.update(action.choices)
    global_options: dict[str, argparse.Action] = {}
    for action in parser._actions:
        for option in action.option_strings:
            global_options[option] = action
    return subcommands, global_options


def nested_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """两级子命令（`app build`、`dist prepare`、`content unpack` 等）的下一级解析器。"""
    group = getattr(parser, "_subparsers", None)
    if group is None:
        return {}
    choices: dict[str, argparse.ArgumentParser] = {}
    for action in group._group_actions:
        choices.update(action.choices)
    return choices


def arity(action: argparse.Action) -> tuple[int, float]:
    nargs = action.nargs
    if nargs is None:
        return 1, 1
    if nargs == "?":
        return 0, 1
    if nargs == "*":
        return 0, float("inf")
    if nargs == "+":
        return 1, float("inf")
    if isinstance(nargs, int):
        return nargs, nargs
    return 0, float("inf")


def check_command(sub: argparse.ArgumentParser, tokens: list[str],
                  global_options: dict[str, argparse.Action]) -> list[str]:
    """按 argparse 定义校验选项与位置参数，返回问题列表。"""
    problems: list[str] = []
    options: dict[str, argparse.Action] = dict(global_options)
    for action in sub._actions:
        for option in action.option_strings:
            options[option] = action

    positionals: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            name, _, inline_value = token.partition("=")
            action = options.get(name)
            if action is None:
                problems.append(f"不支持的选项 {name}")
                index += 1
                continue
            takes_value = action.nargs != 0
            if takes_value and not inline_value:
                index += 1  # 跳过选项值
            index += 1
            continue
        positionals.append(token)
        index += 1

    actions = [action for action in sub._actions if not action.option_strings]
    minimum = sum(arity(action)[0] for action in actions)
    maximum = sum(arity(action)[1] for action in actions)
    if not minimum <= len(positionals) <= maximum:
        expected = (
            f"{minimum}" if minimum == maximum
            else f"{minimum}~{'N' if maximum == float('inf') else int(maximum)}"
        )
        problems.append(f"位置参数数量应为 {expected}，实际 {len(positionals)} 个：{positionals}")

    for action, value in zip(actions, positionals):
        choices = getattr(action, "choices", None)
        if choices and value not in choices and value not in PLACEHOLDER_PROFILES:
            problems.append(f"位置参数 {action.dest}={value!r} 不是有效取值")
    return problems


def extra_rules(name: str, tokens: list[str]) -> list[str]:
    """CLI 在 argparse 之外补充的约束。"""
    if name == "stop" and not any(not token.startswith("-") for token in tokens) \
            and "--all" not in tokens:
        return ["stop 需要 profile 或 --all"]
    return []


def iter_documented_commands():
    """产出 (文档路径, 命令文本, 是否 fenced 代码块)。"""
    for path in DOC_PATHS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for segment in FENCED_BLOCK.findall(text):
            yield path, segment, True
        for segment in INLINE_CODE.findall(text):
            yield path, segment, False


class DocumentedCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.subcommands, self.global_options = command_spec()

    def allowed_options(self, name: str, tail: str = "") -> set[str]:
        allowed = set(self.global_options)
        parser = self.subcommands[name]
        nested = nested_choices(parser)
        first = tail.strip().split()[0] if tail.strip() else ""
        if nested and first in nested:
            parser = nested[first]
        for action in parser._actions:
            allowed.update(action.option_strings)
        return allowed

    def test_documented_subcommands_and_flags_exist(self) -> None:
        problems: list[str] = []
        seen = 0
        for path, segment, _fenced in iter_documented_commands():
            normalized = segment.replace("\\\n", " ")
            for match in COMMAND.finditer(normalized):
                name, tail = match.group(1), match.group(2)
                seen += 1
                if name not in self.subcommands:
                    problems.append(f"{path.name}: 未知子命令 ctflab {name}")
                    continue
                allowed = self.allowed_options(name, tail)
                for flag in re.findall(r"(?<![\w-])--?[A-Za-z][A-Za-z0-9-]*", tail):
                    if flag not in allowed:
                        problems.append(f"{path.name}: ctflab {name} 不支持 {flag}")
        self.assertGreater(seen, 20, "文档中应能找到足够多的命令样例")
        self.assertEqual(problems, [])

    def test_fenced_commands_parse_with_positional_arguments(self) -> None:
        problems: list[str] = []
        seen = 0
        for path, segment, fenced in iter_documented_commands():
            if not fenced:
                continue
            normalized = segment.replace("\\\n", " ")
            for match in COMMAND.finditer(normalized):
                raw = match.group(0).strip().rstrip("`")
                try:
                    tokens = shlex.split(raw)
                except ValueError as exc:
                    problems.append(f"{path.name}: 无法解析 {raw!r}：{exc}")
                    continue
                tokens = [t for t in tokens if t not in ("./tools/ctflab", "ctflab")]
                name, rest = tokens[0], tokens[1:]
                if name not in self.subcommands:
                    continue  # 已由上一个用例报告
                seen += 1
                parser_under_test = self.subcommands[name]
                nested = nested_choices(parser_under_test)
                if nested and rest and rest[0] in nested:
                    parser_under_test = nested[rest[0]]
                    rest = rest[1:]
                found = check_command(parser_under_test, rest, self.global_options)
                found += extra_rules(name, rest)
                for problem in found:
                    problems.append(f"{path.name}: ctflab {name}：{problem}")
        self.assertGreater(seen, 15, "代码块中应能找到足够多的可执行命令样例")
        self.assertEqual(problems, [])

    def test_checker_rejects_known_bad_commands(self) -> None:
        """确认校验器不是空转：坏命令必须被拦住。"""
        bad = [
            ("import", ["smoke-1.0.0.ctflab"]),                  # 位置参数不足
            ("import", ["smoke-1.0.0.ctflab", "/tmp/x.qcow2"]),  # profile 取值无效
            ("reset", ["smok"]),                                 # profile 拼写错误
            ("inspect", []),                                     # 缺少 source
            ("import", ["smoke", "/tmp/x.qcow2", "extra"]),      # 位置参数过多
            ("run", []),                                         # 至少一个 profile
        ]
        for name, tokens in bad:
            with self.subTest(command=f"{name} {' '.join(tokens)}"):
                problems = check_command(self.subcommands[name], tokens, self.global_options)
                self.assertTrue(problems, f"{name} {tokens} 应被判为无效")
        with self.subTest(command="stop"):
            self.assertTrue(extra_rules("stop", ["--graceful"]),
                            "stop 没有 profile 也没有 --all 时应在执行阶段被拒绝")
            self.assertEqual(extra_rules("stop", ["--all"]), [])
            self.assertEqual(extra_rules("stop", ["kali-arm64"]), [])

    def test_unsupported_flag_is_reported(self) -> None:
        problems = check_command(self.subcommands["stop"], ["--graceful", "--nonsense"],
                                 self.global_options)
        self.assertIn("不支持的选项 --nonsense", problems)

    def test_ctflab_package_examples_do_not_replace_source_import(self) -> None:
        """内容包已可校验，但在实施计划的原始镜像示例中不能被误写成 import 源文件。"""
        plan = (PROJECT_ROOT / "docs" / "ctflab-mac-mvp-implementation-plan.md").read_text(encoding="utf-8")
        self.assertNotIn("ctflab import smoke-1.0.0.ctflab", plan)
        self.assertNotIn("ctflab import basic-pentesting-2-1.0.0.ctflab", plan)
        self.assertIn("Task 6", plan)


if __name__ == "__main__":
    unittest.main()
