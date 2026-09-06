"""cli.py — 简单命令行接口。

用法:
    python cli.py <db文件> put <key> <value>
    python cli.py <db文件> get <key>
    python cli.py <db文件> scan [start] [end]
    python cli.py <db文件> stat

示例:
    python cli.py my.db put name claude
    python cli.py my.db get name
    python cli.py my.db scan
"""

import sys

from db import MiniDB, DBError

# Windows 控制台默认 GBK,强制 UTF-8 避免中文输出乱码
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path, cmd = argv[1], argv[2]
    args = argv[3:]
    db = MiniDB(path)
    try:
        if cmd == "put" and len(args) == 2:
            db.put(args[0], args[1])
            print("OK")
        elif cmd == "get" and len(args) == 1:
            print(db.get(args[0]))
        elif cmd == "scan":
            start = args[0] if len(args) > 0 else None
            end = args[1] if len(args) > 1 else None
            for k, v in db.scan(start, end):
                print("%r  =>  %r" % (k, v))
        elif cmd == "stat":
            for k, v in db.stats().items():
                print("%-16s %s" % (k, v))
            print("rows            %d" % db.count())
        else:
            print(__doc__)
            return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except DBError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
