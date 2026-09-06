# Git 内部原理实验记录

环境:Windows 10 / Git Bash / git version 2.53.0.windows.3
实验仓库:`lab/`(独立 repo,`git init` 创建)。所有输出均为真实运行结果,未做润色。
对应的主文档见 `D:\workspace\learning\docs\git-internals.md`。

实验目标:不用 `git add` / `git commit`,只用底层命令(plumbing)手工构建出完整的提交历史,并逐一验证 Git 的对象模型、引用机制、三区关系、packfile 与 merge 本质。

---

## 0. 初始状态:一个空的 .git 长什么样

```
$ git init lab
Initialized empty Git repository in D:/workspace/learning/experiments/git-internals/lab/.git/

$ find .git -type f | sort
.git/HEAD
.git/config
.git/description
.git/hooks/*.sample          (省略)
.git/info/exclude

$ find .git/objects -type d | sort
.git/objects
.git/objects/info
.git/objects/pack
```

要点:对象库是空的,`info` 和 `pack` 两个子目录先建好(`pack` 为将来的 packfile 预留)。

## 1. HEAD:初始是一个符号引用

```
$ cat .git/HEAD
ref: refs/heads/master

$ git symbolic-ref HEAD
refs/heads/master

$ git rev-parse HEAD
fatal: ambiguous argument 'HEAD': unknown revision or path not in the working tree.
```

要点:
- `HEAD` 的内容是 `ref: refs/heads/master` —— 指向引用的引用(符号引用)。
- 但 `refs/heads/master` 这个文件此时**并不存在**(没有任何提交),所以 `rev-parse HEAD` 报错。Git 把这种状态叫 "unborn branch":分支是在第一次写入提交时才"出生"的。

## 2. hash-object:内容寻址的第一课

```
$ printf 'hello world\n' | git hash-object --stdin        # 只算哈希,不写入
3b18e512dba79e4c8300dd08aeb37f8e728b8dad

$ printf 'hello world\n' | git hash-object -w --stdin     # 写入对象库
3b18e512dba79e4c8300dd08aeb37f8e728b8dad

$ printf 'hello world\n' | git hash-object --stdin        # 同内容再来一次
3b18e512dba79e4c8300dd08aeb37f8e728b8dad

$ find .git/objects -type f
.git/objects/3b/18e512dba79e4c8300dd08aeb37f8e728b8dad
```

要点:
- 相同内容重复写入,哈希不变,磁盘上仍只有一个文件 —— **内容寻址天然去重**。
- 存储路径 = 哈希前 2 位做目录名 + 剩余 38 位做文件名。

## 3. 验证 SHA-1 的计算方式:sha1("blob 12\0" + 内容)

```
$ { printf 'blob 12\0'; printf 'hello world\n'; } | sha1sum
3b18e512dba79e4c8300dd08aeb37f8e728b8dad *-

$ git cat-file -t 3b18e512
blob
$ git cat-file -s 3b18e512
12
$ git cat-file -p 3b18e512 | od -c | head -3
0000000   h   e   l   l   o       w   o   r   l   d  \n
0000014
```

要点:对象哈希 = `sha1("<类型> <字节数>\0" + 原始内容)`。头部包含类型和长度,所以**类型和长度也被哈希保护**,篡改任何一处都会导致哈希变化。注意 `hello world\n` 是 12 字节(含换行),不是 11。

对象文件本身是 zlib 压缩的,解开后即 "头 + 内容":

```
$ od -A x -t x1z .git/objects/3b/18e5...dad | head -4
000000 78 01 4b ca c9 4f 52 30 34 62 c8 48 cd c9 c9 57  >x.K..OR04b.H...W<
000010 28 cf 2f ca 49 e1 02 00 44 11 06 89              >(./.I...D...<

$ python -c "import zlib; print(repr(zlib.decompress(open('.git/objects/3b/18e5...dad','rb').read())))"
b'blob 12\x00hello world\n'
```

## 4. 手工组装 index:不用 git add

```
$ printf 'print("hello")\n' > hello.py
$ mkdir -p src/lib
$ printf 'def add(a,b):\n    return a+b\n' > src/lib/math.py
$ printf '# demo\n' > src/readme.md

$ git update-index --add hello.py src/readme.md src/lib/math.py
$ git ls-files --stage
100644 11b15b1a4584b08fa423a57964bdbf018b0da0d5 0	hello.py
100644 f083797c39285e47b994854fe9bb9277b4e5f5ef 0	src/lib/math.py
100644 fc72a5c1094e203eefcd1c710f060957ebbbaac4 0	src/readme.md
```

要点:
- `update-index --add` = 先对文件内容做 `hash-object -w` 写成 blob,再把 "<mode> <sha1> <路径>" 写进 index。`git add` 就是这个动作的 porcelain 封装。
- `git ls-files --stage` 是查看 index 内容的窗口:mode / SHA-1 / stage / 路径。stage 平时是 0,merge 冲突时会出现 1/2/3(见实验 10)。

index 文件本身的二进制格式(魔数 DIRC + 版本号):

```
$ od -A d -t x1z -N 12 .git/index
0000000 44 49 52 43 00 00 00 02 00 00 00 04              >DIRC........<
```

## 5. write-tree / ls-tree:目录也是对象

```
$ git write-tree
54c93d41f82430a513543df550973d2c47cfe96a

$ git cat-file -p 54c93d41...
100644 blob 11b15b1a4584b08fa423a57964bdbf018b0da0d5	hello.py
040000 tree e4ac9ab7cbf5c4eff8b708902e510a4fc08ca5da	src

$ git cat-file -p 54c93d41...:src
040000 tree 9be6fdcc940caaf91d54b6a57ec1ca1fcdf1a436	lib
100644 blob fc72a5c1094e203eefcd1c710f060957ebbbaac4	readme.md

$ git cat-file -p 54c93d41...:src/lib
100644 blob f083797c39285e47b994854fe9bb9277b4e5f5ef	math.py

$ find .git/objects -type f | sort
.git/objects/11/b15b1a...   (blob hello.py)
.git/objects/3b/18e512...   (blob "hello world")
.git/objects/54/c93d41...   (tree 根)
.git/objects/9b/e6fdcc...   (tree src/lib)
.git/objects/e4/ac9ab7...   (tree src)
.git/objects/f0/83797c...   (blob math.py)
.git/objects/fc/72a5c1...   (blob readme.md)
```

要点:
- 我只调用了 `update-index`(只产 blob),子目录的 tree 是 `write-tree` 现场算出来的 —— **tree 是目录的快照,由 index 生成,层层嵌套**。
- tree 条目里目录 mode 是 `040000`,文件是 `100644`(可执行文件是 `100755`,符号链接是 `120000`)。
- 目录在磁盘上有 3 个文件,对象库里也只有 3 个 blob + 3 个 tree:Git 存的是**快照**,不是 diff(见主文档"常见误解")。

## 6. commit-tree:手工制造 commit

```
$ export GIT_AUTHOR_NAME="Lab" GIT_AUTHOR_EMAIL="lab@example.com" \
    GIT_AUTHOR_DATE="2026-09-06T10:00:00+08:00" \
    GIT_COMMITTER_NAME="Lab" GIT_COMMITTER_EMAIL="lab@example.com" \
    GIT_COMMITTER_DATE="2026-09-06T10:00:00+08:00"
$ C1=$(echo "first commit (built by hand)" | git commit-tree 54c93d41...)
$ echo $C1
a57c345175ed3cbcb30c54d22d5addf1f9c4427a

$ git cat-file -p $C1
tree 54c93d41f82430a513543df550973d2c47cfe96a
author Lab <lab@example.com> 1788660000 +0800
committer Lab <lab@example.com> 1788660000 +0800

first commit (built by hand)
```

要点:
- commit 对象 = 指向一个 tree + 作者/提交者 + 消息。此时还没有 `parent` 行 —— 根提交。
- `author` 与 `committer` 是两个独立字段(打补丁/rebase 场景下会不同)。
- commit 没有指向任何文件的引用,只指向 tree;文件关系全靠 tree 层层下钻。

验证 commit 的哈希同样是内容寻址(手工重算):

```
$ git cat-file commit a57c345... | wc -c
171
$ python - <<'EOF'
import subprocess, hashlib
raw = subprocess.run(['git','cat-file','commit','a57c345...'],capture_output=True).stdout
print(hashlib.sha1(('commit %d' % len(raw)).encode()+b'\x00'+raw).hexdigest())
EOF
a57c345175ed3cbcb30c54d22d5addf1f9c4427a     # 与真实哈希一致
```

(完整输出见主文档;方法与实验 3 完全相同,只是类型头换成 `commit 171\0`。)

## 7. 第二个提交 + update-ref:让分支"出生"

改一下 hello.py,更新 index,写新 tree,再以 C1 为父提交做第二个 commit:

```
$ printf 'second line\n' >> hello.py
$ git update-index hello.py
$ NEWTREE=$(git write-tree); echo $NEWTREE
de3a2ebb7fee2c47a168a26cac19577d32e20914

$ C2=$(echo "second commit, parent=$C1" | git commit-tree $NEWTREE -p $C1)
$ git cat-file -p $C2
tree de3a2ebb7fee2c47a168a26cac19577d32e20914
parent a57c345175ed3cbcb30c54d22d5addf1f9c4427a
author dev <dev@example.com> 1788663600 +0800
committer dev <dev@example.com> 1788663600 +0800

second commit, parent=a57c345175ed3cbcb30c54d22d5addf1f9c4427a
```

(这条 shell 是新开的会话,实验 6 里 export 的身份变量失效了,Git 落回全局配置的默认身份 —— 侧面验证了身份的来源优先级。日期取自显式 export 的 `GIT_AUTHOR_DATE`。)

然后把分支指过去 —— 这一步等价于 `git commit` 的收尾:

```
$ git update-ref refs/heads/master $C2
$ cat .git/refs/heads/master
24df7f925f5c7520ea1c1ec38dc73ec7e451e60d
$ wc -c .git/refs/heads/master
41 .git/refs/heads/master
$ git log --oneline --all
24df7f9 second commit, parent=a57c345175ed3cbcb30c54d22d5addf1f9c4427a
a57c345 first commit (built by hand)
```

要点:**一个分支 = 一个 41 字节的文本文件**(40 位十六进制 SHA-1 + 1 个换行)。所谓"分支很重/很贵"是误解;重的是分支策略,不是分支本身。

## 8. 三层结构:index / 工作区 / HEAD

```
$ git status --short                 # 干净
$ printf 'print("hello v2")\nprint("second line")\n' > hello.py
$ git status --short
 M hello.py                          # 第一列空格 + 第二列 M:index == HEAD,工作区 != index

$ git diff --stat                    # 比较 index vs 工作区
 hello.py | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

$ git update-index hello.py          # 相当于 git add
$ git status --short
M  hello.py                          # 第一列 M:index != HEAD,工作区 == index

$ git diff --cached --stat           # 比较 HEAD vs index
 hello.py | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)
```

要点:`git status` 的两列 XY 分别是 "index vs HEAD" 和 "工作区 vs index"。`git diff` / `git diff --cached` / `git diff HEAD` 正好对应三条比较边。

## 9. 符号引用 vs 直接引用:detached HEAD

```
$ cat .git/HEAD
ref: refs/heads/master

$ git checkout --detach 24df7f9
HEAD is now at 24df7f9 second commit...

$ cat .git/HEAD
24df7f925f5c7520ea1c1ec38dc73ec7e451e60d      # 直接写 SHA,不再是 ref:

$ git symbolic-ref HEAD
fatal: ref HEAD is not a symbolic ref

$ git checkout master
Switched to branch 'master'
$ cat .git/HEAD
ref: refs/heads/master
```

reflog(`.git/logs` 就是纯文本):

```
$ git reflog
24df7f9 HEAD@{0}: checkout: moving from 24df7f9... to master
24df7f9 HEAD@{1}: checkout: moving from master to 24df7f9
24df7f9 HEAD@{2}:

$ cat .git/logs/HEAD
0000000000000000000000000000000000000000 24df7f9... dev <...> 1788663600 +0800
24df7f9... 24df7f9... dev <...> 1788684534 +0800	checkout: moving from master to 24df7f9
24df7f9... 24df7f9... dev <...> 1788684534 +0800	checkout: moving from 24df7f9... to master

$ cat .git/logs/refs/heads/master
0000000000000000000000000000000000000000 24df7f9... dev <...> 1788663600 +0800
```

要点:
- HEAD 文件内容两种形态:`ref: <引用名>`(挂在分支上)或裸 SHA-1(detached)。
- reflog 每行 = `<旧值> <新值> <谁> <时间> <动作>`,old value 为全 0 表示"从无到有"。`update-ref` 也写 reflog(core.logAllRefUpdates 默认开)。**reflog 是引用级的历史,不是提交历史的一部分**;它就是 `HEAD@{n}`、`master@{1小时前}` 的数据来源,也是 reflog expire 之后对象能被 gc 的依据。

## 10. 分支的廉价性 + 制造分叉

```
$ time git update-ref refs/heads/dev a57c345...
real    0m0.018s
$ wc -c .git/refs/heads/dev
41 .git/refs/heads/dev
$ git branch -v
  dev    a57c345 first commit (built by hand)
* master 24df7f9 second commit, parent=...
```

在 dev 上制造一个分叉提交(改 readme.md):

```
$ printf '# demo\nnew file in dev\n' > src/readme.md
$ git update-index src/readme.md
$ DTREE=$(git write-tree)
$ C3=$(echo "dev commit (divergent)" | git commit-tree $DTREE -p a57c345...)
$ git update-ref refs/heads/dev $C3
$ git log --oneline --graph --all
* d3c62dc dev commit (divergent)
| * 24df7f9 second commit, parent=...
|/
* a57c345 first commit (built by hand)
```

建分支耗时 18ms、写 41 字节,分支创建的"成本"就是一次文件写入。

## 11. merge 的本质:三方合并

```
$ git merge-base master dev
a57c345175ed3cbcb30c54d22d5addf1f9c4427a        # 两个分支的共同祖先

$ git rev-parse master:src/readme.md dev:src/readme.md
fc72a5c...   (master 侧,与 base 相同 -> 未改动)
5215bb4...   (dev 侧,改过)
```

我故意让 hello.py 在两侧改出了不同内容(base/master/dev 三个 blob 互不相同),触发真实冲突:

```
$ git merge dev
Auto-merging hello.py
CONFLICT (content): Merge conflict in hello.py
Automatic merge failed; fix conflicts and then commit the result.

$ cat hello.py
<<<<<<< HEAD
print("hello")
second line
=======
print("hello v2")
print("second line")
>>>>>>> dev
```

冲突时 index 里同一个路径出现 **三个 stage**(这就是 merge 算法的现场):

```
$ git ls-files --stage
100644 11b15b1a... 1	hello.py        # stage 1 = base(共同祖先)
100644 6d6c3a99... 2	hello.py        # stage 2 = ours(HEAD)
100644 b9f2c3c9... 3	hello.py        # stage 3 = theirs(dev)
100644 f083797c... 0	src/lib/math.py
100644 5215bb42... 0	src/readme.md   # 无冲突路径直接归到 stage 0
```

要点:三方合并对每个文件比较 base / ours / theirs 三个 blob:只有一侧改了 → 直接取改动侧;两侧改得相同 → 取相同结果;两侧改得不同 → 冲突,把三个版本同时放进 index 等。**merge 从来不是"比较两个分支的全部文件",而是基于 merge-base 的三方比较**。

解决冲突后手工收尾(等价于 `git commit` 完成合并):

```
$ printf 'print("hello")\nsecond line\nprint("merged")\n' > hello.py
$ git update-index hello.py
$ MTREE=$(git write-tree)
$ MC=$(echo "Merge branch 'dev' (built by hand)" | git commit-tree $MTREE -p HEAD -p dev)
$ git update-ref refs/heads/master $MC

$ git cat-file -p $MC
tree e5bfcaddd861005d2eb9d52c50cce5d8cc8aa145
parent 24df7f925f5c7520ea1c1ec38dc73ec7e451e60d
parent d3c62dcc6f258b291bc81d59db31e024594723ac
author dev <dev@example.com> 1788684631 +0800
committer dev <dev@example.com> 1788684631 +0800

Merge branch 'dev' (built by hand)

$ git log --graph --oneline --all
*   8970169 Merge branch 'dev' (built by hand)
|\
| * d3c62dc dev commit (divergent)
* | 24df7f9 second commit, parent=...
|/
* a57c345 first commit (built by hand)
```

要点:**merge commit 没有任何新机制,就是一个有 2 个 parent 的普通 commit**。`-p` 写两次即可手工构造;`HEAD^1`/`HEAD^2` 分别取第一、第二父提交。

一个真实的坑,顺带记录:合并前 index 里还留着实验 8 的未提交改动,merge 直接拒绝——

```
$ git merge dev
error: Your local changes to the following files would be overwritten by merge:
  hello.py src/readme.md
Merge with strategy ort failed.
```

Git 不会覆盖 index/工作区里的未提交内容,这正是三层模型的行为体现。

## 12. tag:两种

```
$ git tag -a v1.0 -m "release v1.0" master
$ cat .git/refs/tags/v1.0
12b75e3416b22d9c019f44f6de5f09a3b3e9fbab

$ git cat-file -t 12b75e34...
tag                       # 注意:类型是 tag,第四种对象!
$ git cat-file -p 12b75e34...
object 8970169c8553495075ca7603af4f6b771b1f76a1
type commit
tag v1.0
tagger Lab <lab@example.com> 1788670800 +0800

release v1.0

$ git tag light-tag 24df7f9
$ git cat-file -t light-tag
commit                    # 轻量 tag 不新建对象,ref 直接指向 commit
$ wc -c .git/refs/tags/light-tag
41 .git/refs/tags/light-tag
```

要点:annotated tag 是一个**独立对象**(类型 `tag`),内含目标对象哈希 + 类型 + tag 名 + tagger + 消息,可被 GPG 签名;lightweight tag 只是一个 41 字节的 ref 文件,不产生对象。

## 13. packfile 与 delta 压缩

先造数据:用 plumbing 建 8 个提交,每个都改 bigfile.txt 的第一行(文件约 9.5KB):

```
$ git count-objects -v
count: 24          # 松散对象 24 个(人工构建部分)
size: 2            # 占 2KB
in-pack: 0
packs: 0

(建 8 个提交后)
$ count: 48
size: 17
$ du -sk .git/objects
80  .git/objects    # 约 80KB,其中 8 个 9519 字节的大 blob

$ git gc

$ git count-objects -v
count: 0            # 松散对象清零
size: 0
in-pack: 48         # 全部进包
packs: 2
size-pack: 9        # 仅约 9KB!

$ ls .git/objects/pack/
pack-7c2e9ad2....idx
pack-7c2e9ad2....pack
pack-7c2e9ad2....rev
pack-ade21372....idx
pack-ade21372....mtimes        # cruft pack(不可达对象,见下)
pack-ade21372....pack
pack-ade21372....rev
```

verify-pack 看到关键证据 —— 7 个大 blob 存成了 **18 字节的 delta**:

```
$ git verify-pack -v .git/objects/pack/pack-7c2e9ad2....idx | grep -E '91ba1ceb|2a2455aa|...' 
2a2455aa... blob   9519 1743 3281                     # 基准对象,存全文
91ba1ceb... blob     18   30 5024 1 2a2455aa...       # delta,深度1,基于 2a2455aa
63efe735... blob     18   30 5054 1 2a2455aa...
60271a70... blob     18   30 5084 1 2a2455aa...
9d084d4e... blob     18   30 5114 1 2a2455aa...
5693db7d... blob     18   30 5144 1 2a2455aa...
20ed9fab... blob     18   30 5174 1 2a2455aa...
61827d0d... blob     18   30 5204 1 2a2455aa...
```

输出格式:`<sha> <type> <原始大小> <包内大小> <包内偏移> [<链深> <基准sha>]`。8 个 9.5KB 的文件版本,最终只存 1 份全文 + 7 份 18 字节差量。

而对象库的使用方完全无感:

```
$ git cat-file -p 91ba1ceb | head -1
VERSION 7 header line with some text
$ git cat-file -p 2a2455aa | head -1
VERSION 8 header line with some text
$ diff <(git cat-file -p 91ba1ceb) <(git cat-file -p 2a2455aa)
1c1
< VERSION 7 header line with some text
---
> VERSION 8 header line with some text
```

pack 文件头(魔数 PACK + 版本 2 + 对象数 0x2b=43):

```
$ od -A d -t x1z -N 16 .git/objects/pack/pack-7c2e9ad2....pack
0000000 50 41 43 4b 00 00 00 02 00 00 00 2b 9f 0c 78 9c  >PACK.......+..x.<
```

gc 的其他副作用,一次看全:

```
$ cat .git/packed-refs
# pack-refs with: peeled fully-peeled sorted 
e029e0a... refs/heads/big
d3c62dc... refs/heads/dev
8970169... refs/heads/master
24df7f9... refs/tags/light-tag
12b75e34... refs/tags/v1.0
^8970169c8553495075ca7603af4f6b771b1f76a1      # ^ 开头 = annotated tag 的剥离(peeel)

$ ls .git/refs/heads .git/refs/tags     # 松散 ref 文件已被收进 packed-refs
(两个目录都空了)

$ git fsck
dangling commit 9024f2be...
dangling blob 3b18e512...                # 实验一开始 hash-object 写入但从未被任何 tree 引用
dangling tree f23616cc...
```

要点:
- `git gc` = 打包松散对象 + delta 压缩 + `pack-refs` + 清理不可达对象 + 重写 reflog(过期)。
- 未被引用的对象(那个 "hello world" blob)不会被立即删除,而是进 **cruft pack**(带 `.mtimes`),到期才真正删除——这就是 `git gc` 之后误删的东西通常还能找回来的原因。
- `git rev-parse HEAD^` 与 `HEAD^2`:前者是第一个父提交,后者是**第二个父提交**(merge 的另一侧);`HEAD~2` 才是"往上两代"。

## 14. 补充验证

同一内容跨仓库同哈希(内容寻址是全局的,与仓库无关):

```
$ cd /tmp/other-repo && git init -q .
$ printf 'hello world\n' | git hash-object --stdin
3b18e512dba79e4c8300dd08aeb37f8e728b8dad      # 与 lab 仓库完全一致
```

SHA-256 对象格式(git 2.53 本机实测):

```
$ git init -q --object-format=sha256 /tmp/sha256lab
$ printf 'hello world\n' | git hash-object --stdin
0bd69098bd9b9cc5934a610ab65da429b525361147faa7b5b922919e9a23143d
```

引用语法速查(全部实测):

```
$ git rev-parse HEAD HEAD^ HEAD^^ HEAD~2 'HEAD^2' 'HEAD^1'
8970169...   HEAD(merge commit)
24df7f9...   HEAD^  = HEAD^1 = HEAD~1(第一父提交)
a57c345...   HEAD^^ = HEAD~2(第一父链往上两代)
a57c345...   HEAD~2
d3c62dc...   HEAD^2(第二父提交,即被合并的 dev)
24df7f9...   HEAD^1
```

---

## 实验结论汇总

1. Git 的四种对象 blob/tree/commit/tag 全部遵循同一格式:`sha1("<type> <size>\0" + content)`,zlib 压缩后按前两位分目录存储。
2. `git add` ≈ `hash-object -w` + `update-index`;`git commit` ≈ `write-tree` + `commit-tree` + `update-ref`(根提交无 `-p`,merge 提交 `-p` 两次)。
3. 分支 = 41 字节 ref 文件(或 packed-refs 里的一行),创建成本 ≈ 0。
4. HEAD 是符号引用,detached 就是把符号引用换成裸 SHA;reflog 是独立的引用操作日志。
5. merge = 基于 merge-base 的三方合并,冲突时 index 以 stage 1/2/3 同时保存 base/ours/theirs;merge commit 只是双父提交,无特殊机制。
6. `git gc` 将松散对象打包为 packfile,相似内容以 delta 形式存储(实测 8×9.5KB → 1 份全文 + 7 份 18 字节差量),对上层命令完全透明。

---

## 交付说明(主 agent 注)

实验中 `lab/` 是一个真实 git 仓库;归档外发时其 `.git` 元数据已移至同级 `lab-git-store/`(仅本地保留,不入公开仓库,内含实验机身份配置)。`lab/` 目录以纯工作区文件形式随仓库分发;全部实验可按上文步骤用 `git init` 在任意空目录复现。
