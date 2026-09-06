"""可插拔哈希函数:统一接口 hash_bytes(data: bytes) -> int(64 位非负整数)。

- md5:     MD5 摘要取前 8 字节(64 位截断),密码学哈希,分布质量最好,但最慢
- fnv1a:   FNV-1a 64 位,乘法+异或,极快,分布良好
- mmh3:   MurmurHash3 的 x64 变体简化实现(纯 Python,非官方版本),
           模拟 memcached/Redis 客户端常用的 MurmurHash 思路
- builtin: Python 内置 hash(),加盐稳定版(进程内确定性),仅作对照,不建议生产使用
"""

import hashlib
import zlib

MASK64 = (1 << 64) - 1
FNV_OFFSET = 0xcbf29ce484222325
FNV_PRIME = 0x100000001b3


def md5_64(data: bytes) -> int:
    """MD5 截断前 8 字节,大端解释为 64 位无符号整数。"""
    return int.from_bytes(hashlib.md5(data).digest()[:8], "big")


def fnv1a_64(data: bytes) -> int:
    """FNV-1a 64 位。"""
    h = FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & MASK64
    return h


def _fmix64(k: int) -> int:
    """MurmurHash3 的 64 位 finalizer(雪崩混合)。"""
    k ^= k >> 33
    k = (k * 0xff51afd7ed558ccd) & MASK64
    k ^= k >> 33
    k = (k * 0xc4ceb9fe1a85ec53) & MASK64
    k ^= k >> 33
    return k


def mmh3_like_64(data: bytes, seed: int = 0) -> int:
    """简化版 MurmurHash3 x64:分块滚动乘法混合 + fmix64 finalizer。

    注意:这不是与 C++ MurmurHash3 位级兼容的实现,只是同思路的纯 Python
    快速非密码学哈希,用于观察分布特性足够了。
    """
    h = (seed ^ (len(data) * 0x9E3779B97F4A7C15)) & MASK64
    nblocks = len(data) // 8
    for i in range(nblocks):
        k = int.from_bytes(data[i * 8:(i + 1) * 8], "little")
        k = (k * 0x87c37b91114253d5) & MASK64
        k = ((k << 31) | (k >> 33)) & MASK64
        k = (k * 0x4cf5ad432745937f) & MASK64
        h ^= k
        h = ((h << 27) | (h >> 37)) & MASK64
        h = (h * 5 + 0x52dce729) & MASK64
    tail = data[nblocks * 8:]
    if tail:
        k = int.from_bytes(tail + b"\x00" * (8 - len(tail)), "little")
        k = (k * 0x87c37b91114253d5) & MASK64
        k = ((k << 31) | (k >> 33)) & MASK64
        k = (k * 0x4cf5ad432745937f) & MASK64
        h ^= k
    return _fmix64(h ^ len(data))


_SALT = b"py-ch-demo:"


def builtin_hash_64(data: bytes) -> int:
    """内置 hash() 作用于加盐字符串(规避 str 的随机化影响可复现性,加固定盐
    保证同进程内确定),映射到 64 位无符号。跨 Python 进程/版本不保证一致,
    仅作对照,不建议生产使用。
    """
    return hash(_SALT + data) & MASK64


HASHERS = {
    "md5": md5_64,
    "fnv1a": fnv1a_64,
    "mmh3": mmh3_like_64,
    "builtin": builtin_hash_64,
}


def get_hasher(name: str):
    try:
        return HASHERS[name]
    except KeyError:
        raise ValueError(f"unknown hasher {name!r}, choose from {sorted(HASHERS)}") from None
