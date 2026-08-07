"""hash_guard 判重逻辑测试：hash 匹配语义与决策。

_sha_matches_indexed 的 16 位前缀比较是历史兼容写法（文件字节 sha 与
content sha 前 16 位比较），用测试钉住当前行为，改动前需先更新测试。
"""

from rag_core.application.ingest_flow.hash_guard import _sha_matches_indexed


def test_sha_matches_full_equality() -> None:
    assert _sha_matches_indexed("abc123", "abc123") is True
    assert _sha_matches_indexed("ABC123", "abc123") is True  # 大小写不敏感


def test_sha_matches_16_prefix_fallback() -> None:
    # 兼容旧数据：索引里只有 content sha 前 16 位时，文件 sha 前缀匹配即视为相同
    assert _sha_matches_indexed("abcdef1234567890zzzz", "abcdef1234567890") is True


def test_sha_mismatch_when_prefix_differs() -> None:
    assert _sha_matches_indexed("abcdef1234567890aaaa", "abcdef1234567891") is False
    assert _sha_matches_indexed("abc", "abcdef1234567890") is False


def test_sha_16_prefix_only_matches_prefix() -> None:
    # 索引 sha 为 16 位时不能与任意 16 位前缀相同的串误判
    assert _sha_matches_indexed("deadbeef00000000", "deadbeef00000001") is False
