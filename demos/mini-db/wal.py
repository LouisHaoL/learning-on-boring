"""wal.py — Write-Ahead Log。

日志文件由一条条定长头部 + 变长 payload 的记录顺序组成。
字节布局(全部小端):

    +---------+------+------+---------+---------+-----+
    | len u32 | type u8 | txid u64 | payload ...  | crc32 u32 |
    +---------+---------+----------+--------------+-----------+
      4 字节     1 字节    8 字节      len-21 字节      4 字节

    len   = 本条记录总长度(含 len 字段自身到 crc 为止)
    crc32 = 对 [type 起始, crc 之前) 即 record[4:len-4] 的校验

记录类型:
    1 BEGIN   事务开始,payload 为空
    2 PUT     payload = klen u16 + key + vlen u16 + value(逻辑 redo 记录)
    3 COMMIT  事务提交,payload 为空
    4 ABORT   事务放弃,payload 为空

恢复规则:从文件头顺序扫描,遇到第一条不完整(len 越界 / crc 不对 /
数据不足)的记录即停止 —— 崩溃时写在半路的"尾巴"被天然丢弃。
只有出现在 COMMIT 记录之前(含)的事务会被重放。

提交协议(见 db.py):BEGIN -> 每个修改一条 PUT -> COMMIT,fsync WAL,
然后再把脏页写数据文件并 fsync,最后清空 WAL(checkpoint)。
因此崩溃只可能发生在:WAL fsync 之前(事务等于没发生)、
WAL 之后数据落盘之前(重放 WAL 补齐)、或全部落盘之后(无事可做)。
"""

import os
import struct
import zlib

REC_BEGIN = 1
REC_PUT = 2
REC_COMMIT = 3
REC_ABORT = 4

_HDR = struct.Struct("<IBQ")   # len, type, txid
_TYPE_TXID = struct.Struct("<BQ")
_CRC = struct.Struct("<I")
_HDR_SIZE = _HDR.size          # 13
_OVERHEAD = _HDR_SIZE + _CRC.size  # 17


class WALCorrupt(Exception):
    pass


class WAL:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "a+b")
        self.size = self.f.tell()

    def append(self, rtype, txid, payload=b""):
        body = _HDR.pack(_OVERHEAD + len(payload), rtype, txid) + payload
        crc = zlib.crc32(body[4:]) & 0xFFFFFFFF
        rec = body + _CRC.pack(crc)
        self.f.seek(0, os.SEEK_END)
        self.f.write(rec)
        self.f.flush()
        self.size += len(rec)

    def flush(self):
        self.f.flush()
        os.fsync(self.f.fileno())

    def truncate(self):
        """checkpoint:所有已提交修改均已落到数据文件,日志可以清空。"""
        self.f.seek(0)
        self.f.truncate(0)
        self.f.flush()
        self.size = 0

    def read_records(self):
        """顺序解析全部完整记录,返回 [(type, txid, payload), ...]。

        遇到残缺尾部(长度不够 / len 非法 / crc 不匹配)立即停止,
        剩余字节视为崩溃产生的垃圾,直接忽略。
        """
        self.f.seek(0)
        data = self.f.read()
        recs = []
        pos = 0
        n = len(data)
        while pos + _OVERHEAD <= n:
            (rec_len,) = _CRC.unpack_from(data, pos)  # len 字段也是 u32
            if rec_len < _OVERHEAD or pos + rec_len > n:
                break  # 长度非法或记录被截断 —— torn write
            rtype, txid = _TYPE_TXID.unpack_from(data, pos + 4)
            (crc,) = _CRC.unpack_from(data, pos + rec_len - 4)
            if zlib.crc32(data[pos + 4:pos + rec_len - 4]) & 0xFFFFFFFF != crc:
                break  # 校验失败 —— 半条记录
            payload = bytes(data[pos + _HDR_SIZE:pos + rec_len - 4])
            recs.append((rtype, txid, payload))
            pos += rec_len
        return recs

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass
