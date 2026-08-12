# 意图路由规则加载器：从 config/intent_rules.yaml 读取规则定义，
# 供 application/chat_flow/steps/route.py 的 route_question_intent_rules 调用。
#
# 设计目标：
# - 规则可配置（修改 YAML + 重启即生效，无需改代码）
# - 启动时校验规则合法性（正则 compile 失败立即报错）
# - 命中时打印规则名（便于排查 + 收集真实流量命中分布）
# - YAML 不存在/解析失败 → 路由回退到内置默认规则（保持向后兼容）

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import yaml

from rag_core.core.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_YAML_PATH = CONFIG_DIR / "intent_rules.yaml"


@dataclass(frozen=True)
class IntentRule:
    """单条意图路由规则（不可变，启动时 freeze 后所有线程共享）。"""

    name: str
    branch: str  # "direct" | "vector_only" | "graph_only"
    type: str    # "regex_fullmatch" | "regex_search" | "length"
    patterns: tuple[str, ...] = ()
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    case_insensitive: bool = False
    description: str = ""
    # 编译后的正则元组（frozen 字段内不存可哈希对象，用 object.__setattr__ 注入）
    _compiled: tuple = field(default=(), repr=False, compare=False, hash=False)

    def __post_init__(self):
        if self.type in ("regex_fullmatch", "regex_search"):
            flags = re.IGNORECASE if self.case_insensitive else 0
            try:
                compiled = tuple(re.compile(p, flags) for p in self.patterns)
            except re.error as exc:
                raise ValueError(f"规则 {self.name!r} 的正则编译失败: {exc}") from exc
            object.__setattr__(self, "_compiled", compiled)


def _parse_rule(d: dict) -> IntentRule:
    """单条 YAML 字典 → IntentRule（抛出 ValueError 让上层记录并跳过）。"""
    if not isinstance(d, dict):
        raise ValueError(f"规则项必须是字典，实际是 {type(d).__name__}")
    name = d.get("name")
    branch = d.get("branch")
    type_ = d.get("type")
    if not name or not isinstance(name, str):
        raise ValueError("规则缺少 name（字符串）")
    if branch not in ("direct", "vector_only", "graph_only"):
        raise ValueError(f"规则 {name!r} 的 branch 必须是 direct/vector_only/graph_only")
    if type_ not in ("regex_fullmatch", "regex_search", "length"):
        raise ValueError(f"规则 {name!r} 的 type 必须是 regex_fullmatch/regex_search/length")
    patterns = tuple(d.get("patterns") or ())
    if type_ in ("regex_fullmatch", "regex_search") and not patterns:
        raise ValueError(f"规则 {name!r} type={type_} 必须提供 patterns")
    return IntentRule(
        name=name,
        branch=branch,
        type=type_,
        patterns=patterns,
        min_length=d.get("min_length"),
        max_length=d.get("max_length"),
        case_insensitive=bool(d.get("case_insensitive", False)),
        description=d.get("description", "") or "",
    )


def load_intent_rules(path: Optional[Path] = None) -> list[IntentRule]:
    """从 YAML 加载规则；文件不存在/解析失败时返回空列表（调用方走硬编码 fallback）。

    单条规则解析失败会跳过该条并记录错误日志，不会让整个加载失败。
    """
    target = path or DEFAULT_YAML_PATH
    if not target.is_file():
        logger.info("[INTENT-RULES] %s 不存在，使用硬编码默认规则", target)
        return []
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.error("[INTENT-RULES] %s 解析失败，使用硬编码默认规则: %s", target, exc)
        return []
    if not isinstance(raw, dict):
        logger.error("[INTENT-RULES] %s 顶层必须是字典，实际 %s", target, type(raw).__name__)
        return []
    rules_raw = raw.get("rules", [])
    if not isinstance(rules_raw, list):
        logger.error("[INTENT-RULES] %s 的 rules 字段必须是列表", target)
        return []

    rules: list[IntentRule] = []
    for idx, item in enumerate(rules_raw, start=1):
        try:
            rules.append(_parse_rule(item))
        except (ValueError, TypeError) as exc:
            logger.error("[INTENT-RULES] %s 第 %d 条规则解析失败，已跳过: %s", target, idx, exc)
    logger.info("[INTENT-RULES] 从 %s 加载 %d 条规则", target, len(rules))
    for r in rules:
        logger.debug(
            "[INTENT-RULES]   - %-22s branch=%-12s type=%-16s desc=%s",
            r.name, r.branch, r.type, r.description[:40],
        )
    return rules


# 单例缓存：启动时加载一次，全进程复用（规则不可变，线程安全）
_cached_rules: Optional[list[IntentRule]] = None


def get_intent_rules() -> list[IntentRule]:
    """返回 YAML 加载的规则列表（懒加载 + 进程级缓存）。"""
    global _cached_rules
    if _cached_rules is None:
        _cached_rules = load_intent_rules()
    return _cached_rules


def reset_intent_rules_cache() -> None:
    """清空缓存（测试用，下次调用 get_intent_rules 会重新加载）。"""
    global _cached_rules
    _cached_rules = None


def match_rule(rule: IntentRule, question: str) -> bool:
    """判断单条规则是否命中问题。"""
    if rule.type == "length":
        qlen = len(question)
        if rule.min_length is not None and qlen < rule.min_length:
            return False
        if rule.max_length is not None and qlen > rule.max_length:
            return False
        return True
    # regex_fullmatch / regex_search 都用 max_length 先做长度截断，
    # 避免对长问题做正则扫描浪费 CPU
    if rule.max_length is not None and len(question) > rule.max_length:
        return False
    if rule.type == "regex_fullmatch":
        return any(p.fullmatch(question) for p in rule._compiled)
    # regex_search
    return any(p.search(question) for p in rule._compiled)


def route_by_rules(
    question: str, rules: list[IntentRule], *, strict: bool
) -> tuple[Optional[str], Optional[str]]:
    """通用规则路由：按优先级返回 (branch, matched_rule_name)。

    优先级：
      1. direct 命中即返回；strict 模式下退化为 vector_only
      2. graph_only 命中即返回（首个 graph_only 命中即生效）
      3. vector_only 仅在没有任何 graph_only 命中时返回
      4. 都没命中 → (None, None)（调用方进 LLM）

    返回 (branch_str, matched_rule_name)：branch_str 可能是 None 表示未命中。
    """
    graph_rule_name: Optional[str] = None
    vector_rule_name: Optional[str] = None

    for rule in rules:
        if not match_rule(rule, question):
            continue
        if rule.branch == "direct":
            if strict:
                return "vector_only", f"{rule.name} (direct→strict→vector_only)"
            return "direct", rule.name
        if rule.branch == "graph_only":
            graph_rule_name = rule.name
            break  # 首个 graph_only 命中即生效，不再继续
        if rule.branch == "vector_only":
            vector_rule_name = vector_rule_name or rule.name

    if graph_rule_name:
        return "graph_only", graph_rule_name
    if vector_rule_name:
        return "vector_only", vector_rule_name
    return None, None