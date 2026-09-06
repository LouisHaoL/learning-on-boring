# Git 内部原理

> 本文所有结论均在本地实验仓库中用底层命令(plumbing)亲手构建并验证过,
> 命令与输出的完整记录见 `experiments/git-internals/README.md`。
> 环境:git 2.53.0.windows.3,Windows / Git Bash。

Git 与其他版本控制系统最本质的区别只有一句话:**Git 不是"记录文件变化的差异"的系统,而是一个"内容寻址的文件系统",版本控制只是架在它上面的一层应用**。理解了这一点,分支、合并、stash、rebase 这些"高级功能"全都会变成显而易见的实现细节。

## 1. 对象:一切皆 "头 + 内容" 的哈希

Git 对象库 `.git/objects` 里只有四种对象,格式完全统一:

```
对象内容 = "<类型> <内容字节数>\0" + 原始数据
对象哈希 = sha1(对象内容)
磁盘文件 = .git/objects/<哈希前2位>/<剩余38位>   (zlib 压缩)
```

四种对象:

| 类型   | 内容是什么                                    | 指向谁                     |
|--------|-----------------------------------------------|----------------------------|
| blob   | 文件内容(只有内容,不含文件名!)              | 不指向任何对象             |
| tree   | 目录快照:一组 `<mode> <类型> <sha> <文件名>`  | blob 和(子)tree           |
| commit | 指向一个 tree + 父提交 + 作者/提交者 + 消息   | tree + 0..n 个 commit      |
| tag    | 指向一个对象 + 类型 + tag 名 + tagger + 消息  | 任意对象(通常是 commit)   |

### 1.1 亲手验证哈希算法

写入一段内容,然后手动重算 SHA-1:

```
$ printf 'hello world\n' | git hash-object -w --stdin
3b18e512dba79e4c8300dd08aeb37f8e728b8dad

$ { printf 'blob 12\0'; printf 'hello world\n'; } | sha1sum
3b18e512dba79e4c8300dd08aeb37f8e728b8dad        # 完全一致
```

commit 对象同理(实验中手工重算 `sha1("commit 171\0" + commit 原文)`,结果与真实哈希一致)。

几个由这条公式直接推出的性质:

- **同样内容永远同一个哈希**,与仓库无关、与时间无关(实验:在两个不同仓库对 `hello world\n` 做 `hash-object`,都得到 `3b18e512...`)。跨仓库复用对象、`git clone` 的本地 hardlink/复用,都建立在这个性质上。
- **重复写入自动去重**:`hash-object -w` 跑三遍,磁盘上仍只有一个对象文件。
- **完整性自带校验**:哈希覆盖了类型头和长度,任何字节被篡改,哈希立刻对不上。
- 哈希中不含路径:blob 与文件名彻底解耦,**文件名只存在于 tree 里**。这就是为什么改文件名只改一个 tree、所有 blob 原样复用。

### 1.2 `.git/objects` 目录结构(松散对象期)

```
.git/objects/
├── 3b/18e512dba79e4c8300dd08aeb37f8e728b8dad    # blob "hello world"
├── 54/c93d41f82430a513543df550973d2c47cfe96a    # tree(根目录)
├── a5/7c345175ed3cbcb30c54d22d5addf1f9c4427a    # commit(根提交)
├── info/        # 空占位
└── pack/        # packfile(见第 6 节)与空占位
```

这种一个文件一个对象的形态叫 **loose object(松散对象)**。用 `cat-file` 三件套读取任意对象:

```
$ git cat-file -t <sha>    # 看类型
$ git cat-file -s <sha>    # 看大小
$ git cat-file -p <sha>    # 按类型友好地打印内容
```

### 1.3 一次提交在对象图里的样子

实验中用三个文件(含两层子目录)构建的完整对象图:

```
commit a57c345 (根提交)
 │
 └── tree 54c93d4 ────┬─ blob 11b15b1  hello.py
                      └─ tree e4ac9ab  src/
                                        ├─ blob fc72a5c  readme.md
                                        └─ tree 9be6fdc  lib/
                                                           └─ blob f083797  math.py

第二个提交 24df7f9:
tree de3a2eb ──┬─ blob <新的 hello.py blob>   ← 只有这里变了,新 blob
               └─ tree e4ac9ab  src/          ← 未变,复用同一个 tree 对象
```

**快照,不是 diff**。每个 commit 存的是当时的完整目录树;因为内容寻址去重,没变的文件/tree 直接复用旧对象,效果上"像"增量,机制上是全量快照。

tree 条目的 mode 字段(实验输出里可见):

```
100644 blob ...  普通文件
100755 blob ...  可执行文件
120000 blob ...  符号链接(存链接目标路径)
040000 tree ...  子目录
160000 commit ...  gitlink(子模块指向的提交)
```

### 1.4 commit 与 tag

commit 对象原文(实验 6 的真实输出):

```
tree 54c93d41f82430a513543df550973d2c47cfe96a
author Lab <lab@example.com> 1788660000 +0800
committer Lab <lab@example.com> 1788660000 +0800

first commit (built by hand)
```

- 没有 `parent` 行 = 根提交;`parent` 出现两次 = merge 提交。
- `author`(写代码的人)与 `committer`(实际落提交的人)是两个独立字段,时间戳也各自独立。
- commit 只指向 tree,不指向文件;两个 commit 之间没有直接指针,父子关系只体现在 `parent` 字段里。

annotated tag 是第四种对象(实验 12):

```
object 8970169c8553495075ca7603af4f6b771b1f76a1
type commit
tag v1.0
tagger Lab <lab@example.com> 1788670800 +0800

release v1.0
```

lightweight tag 则**不产生任何对象**,只是一个指向 commit 的 ref 文件。

## 2. refs 与 HEAD:给哈希起名字

40 位 SHA-1 没法用人脑记,引用(refs)就是"名字 → 哈希"的映射,全部是普通文本文件:

```
.git/refs/heads/master   内容:24df7f925f5c7520ea1c1ec38dc73ec7e451e60d
.git/refs/tags/v1.0      内容:12b75e3416b22d9c019f44f6de5f09a3b3e9fbab
.git/HEAD                内容:ref: refs/heads/master
```

`HEAD` 是特殊的**符号引用**(symref):它的内容不是哈希,而是"再去看某个 ref"。两种形态(实验 9 实测):

```
$ cat .git/HEAD
ref: refs/heads/master          # 挂在分支上(正常状态)

$ git checkout --detach 24df7f9
$ cat .git/HEAD
24df7f925f5c7520ea1c1ec38dc73ec7e451e60d   # detached:直接写哈希

$ git symbolic-ref HEAD
fatal: ref HEAD is not a symbolic ref      # detached 时报这个错
```

还有一个"幽灵状态":`git init` 之后 HEAD 指向 `refs/heads/master`,但该文件不存在(没有任何提交可指),`git rev-parse HEAD` 直接报错——分支在第一次写入提交之前并不存在(unborn branch)。

### 2.1 分支的廉价性(常见误解澄清)

> 误解:"分支是一份完整拷贝/很重的结构,所以合并才慢。"

实际测量(实验 10):

```
$ time git update-ref refs/heads/dev a57c345...
real    0m0.018s

$ wc -c .git/refs/heads/dev
41 .git/refs/heads/dev
```

**一个分支 = 一个 41 字节的文本文件**(40 个十六进制字符 + 1 个换行符)。建一千个分支也就一千次 41 字节的文件写入。分支之间没有任何从属、嵌套或拷贝关系,`git log --graph` 里画出的分支线,纯粹是从 commit 的 parent 关系回溯出来的形状——`git branch -d` 之所以要求"已合并",是因为删掉这个 41 字节文件后,那条没有 ref 指向的提交链将变成不可达对象,会被 gc 回收。

### 2.2 reflog:引用的操作日志

`.git/logs/` 下是纯文本日志,每次 ref 变动(包括 `update-ref`、reset、checkout)追加一行:

```
0000000000000000000000000000000000000000 24df7f9... dev <...> 1788663600 +0800
24df7f9... 24df7f9... dev <...> 1788684534 +0800  checkout: moving from master to 24df7f9
```

每行 = `<旧值> <新值> <身份> <时间戳> <动作描述>`。要点:

- reflog 是**引用视角**的历史(这个 ref 曾经历过什么),不是提交历史的一部分。`HEAD@{1}`、`master@{2.days.ago}` 语法的数据源就是它。
- 这是"误操作后悔药"的真正机制:`git reset --hard` 丢掉的提交,只要 reflog 里还有记录、对象未被 gc,就能 `git reset --hard HEAD@{1}` 找回。
- gc 时 reflog 会被按过期策略修剪,reflog 里不再提到的不可达对象才会被真正删除。

### 2.3 packed-refs

ref 文件多了以后,gc 会把它们合并进一个文件 `.git/packed-refs`(实验 13 实测):

```
# pack-refs with: peeled fully-peeled sorted 
e029e0a... refs/heads/big
12b75e34... refs/tags/v1.0
^8970169c8553495075ca7603af4f6b771b1f76a1     # ^ 行 = annotated tag 剥离后的目标
```

## 3. 三层结构:工作区、index、对象库

Git 的日常操作其实一直在维护三份"目录状态":

```
    工作区(working tree)          你眼睛看到的文件
        │  git add = hash-object -w + update-index
        ▼
    index(.git/index)             "下一次提交的候选内容"(扁平列表,不含目录层次)
        │  git commit = write-tree + commit-tree + update-ref
        ▼
    对象库(.git/objects)          不可变的快照(commit ← tree ← blob)
```

`git status` 的两列 XY 正是两条比较边(实验 8 实测):

```
X(第一列)= index vs HEAD      Y(第二列)= 工作区 vs index

工作区改了、没 add:      M  (X=空格,Y=M)
add 了、没 commit:       M  (X=M,Y=空格)
```

对应的 diff 也有三条命令,各管一条边:

```
git diff              工作区 vs index
git diff --cached     index vs HEAD(即"这次 commit 将会提交什么")
git diff HEAD         工作区 vs HEAD
```

`.git/index` 是有格式的二进制文件,魔数 `DIRC`(实验:od 前 12 字节为 `44 49 52 43` = "DIRC",随后是版本号)。查看它的内容用:

```
$ git ls-files --stage
100644 2a2455aa... 0	bigfile.txt
100644 9632fab6... 0	hello.py
100644 f083797c... 0	src/lib/math.py
```

index 是**扁平的路径列表**,没有目录结构——目录层次是 `write-tree` 时才根据路径前缀现场构建出来的(实验 5:只写过 blob,子目录 tree 是 `write-tree` 生成的)。

### 3.1 高层命令 ≈ 底层命令的组合

这也是本次实验的方法论:`git add` / `git commit` 没有任何魔法,完全等价于:

```
git add <file>      ≈  git hash-object -w <file>      # 内容 -> blob
                       git update-index <file>        # 登记进 index

git commit          ≈  git write-tree                 # index -> tree
                       git commit-tree <tree> -p <parent>   # -> commit
                       git update-ref refs/heads/<branch> <commit>  # 移动分支
```

实验 6–7、11 全程未使用 `git add` / `git commit`,纯用右侧命令构建出了带 merge 的完整历史。

## 4. merge 的本质:三方合并

> 误解:"merge 是把两个分支的文件互相比较。"

Git 的 merge 是**三方合并(three-way merge)**:对每个路径取三个 blob —— 共同祖先(base,由 `git merge-base` 算出)、ours(HEAD 一侧)、theirs(对方一侧):

```
$ git merge-base master dev
a57c345175ed3cbcb30c54d22d5addf1f9c4427a
```

判定规则:

| base | ours | theirs | 结果                          |
|------|------|--------|-------------------------------|
| A    | A    | B      | 取 B(theirs 改了,ours 没改) |
| A    | B    | A      | 取 B(ours 改了)              |
| A    | B    | B      | 取 B(两侧改成了一样的)        |
| A    | B    | C      | **冲突**,进入人工解决          |

冲突时 Git 的动作(实验 11 实测)很有启发性——把三个版本同时放进 index 的三个 stage:

```
$ git ls-files --stage
100644 11b15b1a... 1	hello.py        # stage 1 = base   (共同祖先的 blob)
100644 6d6c3a99... 2	hello.py        # stage 2 = ours   (HEAD 的 blob)
100644 b9f2c3c9... 3	hello.py        # stage 3 = theirs (dev 的 blob)
100644 5215bb42... 0	src/readme.md   # 无冲突路径直接落到 stage 0
```

工作区写入冲突标记(`<<<<<<<` / `=======` / `>>>>>>>`)只是给你看的;真正的状态机在 index 里:stage 0 = 已解决,1/2/3 = 冲突中。手动解决冲突 = 把内容改成你要的,再 `update-index`(即 `git add`)把该路径归零到 stage 0。

### 4.1 merge commit 没有特殊机制

解决冲突后,合并的"提交"动作就是写一个**有 2 个 parent 的普通 commit**(实验 11 手工完成):

```
$ MC=$(echo "Merge branch 'dev' (built by hand)" | git commit-tree $MTREE -p HEAD -p dev)
$ git cat-file -p $MC
tree e5bfcaddd861005d2eb9d52c50cce5d8cc8aa145
parent 24df7f925f5c7520ea1c1ec38dc73ec7e451e60d
parent d3c62dcc6f258b291bc81d59db31e024594723ac
...

$ git log --graph --oneline --all
*   8970169 Merge branch 'dev' (built by hand)
|\
| * d3c62dc dev commit (divergent)
* | 24df7f9 second commit, parent=...
|/
* a57c345 first commit (built by hand)
```

`HEAD^1` 是第一父提交(合并时你所在的分支),`HEAD^2` 是第二父提交(被合进来的分支)。注意 `^n` 与 `~n` 语义不同(全部实测):

```
HEAD^  = HEAD^1 = HEAD~1     第一父提交
HEAD^2                       第二父提交(只有 merge commit 才有)
HEAD^^ = HEAD~2              沿第一父链往上两代
```

顺带一提,fast-forward 只是 merge 的特例:如果 ours 是 base 的直系后代(theirs 没有独有提交),根本不需要新 commit,把分支 ref 文件改写一下就行——又一次回到"分支就是 41 字节文件"。

## 5. 底层命令速查

本次实验用到的 plumbing 及其在高层命令中的角色:

| 命令                     | 作用                                   | 相当于高层命令的哪一步        |
|--------------------------|----------------------------------------|-------------------------------|
| `hash-object -w`         | 内容 → blob,写对象库                  | `git add` 的前半步            |
| `cat-file -t/-s/-p`      | 读对象:类型 / 大小 / 内容              | (只读)                       |
| `update-index --add`     | 把 blob 登记进 index                   | `git add` 的后半步            |
| `ls-files --stage`       | 打印 index 内容(含冲突 stage)         | `git status` 的数据源之一     |
| `write-tree`             | index → tree 对象                      | `git commit` 的前半步         |
| `ls-tree`                | 读 tree 的条目                         | `git ls-files` 的对象库版本   |
| `commit-tree [-p ...]`   | tree(+父提交们)→ commit 对象        | `git commit` 的中段           |
| `update-ref`             | 原子地把 ref 指向新哈希                | `git commit` 的收尾           |
| `symbolic-ref`           | 读/写符号引用                          | `git checkout <branch>` 换 ref |
| `rev-parse`              | 任意"名字"(ref、HEAD~2 等)→ 哈希   | (到处都在用)                |
| `merge-base`             | 求共同祖先                             | merge/rebase 的第一步         |
| `verify-pack`            | 检查 packfile 内容与 delta 链          | (调试用)                    |
| `count-objects -v`       | 对象库统计                             | (调试用)                    |

## 6. packfile 与 delta 压缩

松散对象多了以后(每个对象一个文件,还有 zlib 的固定开销),Git 把它们打包进 **packfile**:`.git/objects/pack/` 下的 `.pack`(数据)+ `.idx`(索引)+ `.rev`。文件头(实测):

```
$ od -A d -t x1z -N 16 .git/objects/pack/pack-7c2e9ad2....pack
0000000 50 41 43 4b 00 00 00 02 00 00 00 2b ...
         P  A  C  K   版本=2     对象数=43
```

### 6.1 实验:8 个 9.5KB 版本 → 1 份全文 + 7 份 18 字节差量

构造 8 个提交,每次只改 bigfile.txt(约 9519 字节)的第一行,然后 `git gc`:

```
$ git count-objects -v        # gc 前
count: 48        size: 17     # 48 个松散对象
$ du -sk .git/objects
80                            # 约 80KB

$ git gc
$ git count-objects -v        # gc 后
count: 0                      # 松散对象清零
in-pack: 48                   # 全部进包
size-pack: 9                  # 约 9KB
```

用 `verify-pack -v` 看 pack 内部(输出列:`<sha> <type> <原始大小> <包内大小> <偏移> [链深 基准sha]`):

```
2a2455aa... blob   9519 1743 3281                    # 存的是全文
91ba1ceb... blob     18   30 5024 1 2a2455aa...       # delta!基于 2a2455aa
63efe735... blob     18   30 5054 1 2a2455aa...
60271a70... blob     18   30 5084 1 2a2455aa...
9d084d4e... blob     18   30 5114 1 2a2455aa...
5693db7d... blob     18   30 5144 1 2a2455aa...
20ed9fab... blob     18   30 5174 1 2a2455aa...
61827d0d... blob     18   30 5204 1 2a2455aa...
```

7 个版本各存成 18 字节的 delta,全部指向同一个全文基准对象。delta 可以指向 delta(链),链深过长会影响读取性能,gc 时会控制。

关键体验:**这一切对上层完全透明**。读 delta 对象时 `cat-file` 沿基准链解开:

```
$ git cat-file -p 91ba1ceb | head -1
VERSION 7 header line with some text
```

### 6.2 git gc 到底做了什么

`git gc` = 一组维护操作的集合:

1. **打包**:松散对象 → packfile,并寻找 delta 基准做压缩(上文)。
2. **pack-refs**:散落的 ref 文件合并进 `.git/packed-refs`。
3. **清理不可达对象**:没有任何 ref/reflog 能到达的对象不会立刻删,而是放进带 `.mtimes` 的 **cruft pack**,超过宽限期才删除。这就是 `git fsck` 显示 `dangling blob/commit`,以及"rebase/reset 误操作后大多能救回来"的原因。
4. **修剪 reflog**(按 `gc.reflogExpire`,默认 90 天)。

push/fetch 时网络传输用的也是同一套 pack 机制:发送方现场把对方缺的对象打成 pack(还可以按需重算 delta),接收方落盘。

## 7. 常见误解清单

1. **"Git 存的是 diff"** —— 错。存的是全量快照(blob 按 SHA 去重);delta 只是 packfile 里的**存储压缩**手段,与"提交之间记录差异"是两码事。
2. **"分支是文件的拷贝 / 开分支很贵"** —— 错。分支 = 41 字节 ref 文件,创建实测 18ms;贵的是"分支未合并就删掉会丢提交"这种语义,不是结构。
3. **"merge 是比较两个分支"** —— 不准确。是基于 merge-base 的三方逐 blob 合并;冲突时 index 用 stage 1/2/3 同时保存 base/ours/theirs。
4. **"merge commit 是特殊对象"** —— 错。就是 parent 有 2 个的普通 commit,`commit-tree -p` 写两次即可手工构造。
5. **"HEAD 是分支"** —— HEAD 是指向 ref 的符号引用;detached 时它直接装哈希,这时"在 HEAD 上提交"不会移动任何分支,提交会变成仅 reflog 可达的对象。
6. **"SHA-1 相同 = 文件相同,所以 Git 靠哈希判断改动"** —— 反了:Git 根本不判断"改动",每次都为当前内容算哈希、查对象库,哈希命中就是"没变"。内容寻址让"比较"退化成"查找"。
7. **"`git gc` 会删除我的数据"** —— gc 只删"不可达且超过宽限期"的对象,且先送进 cruft pack;可达对象(ref、reflog、index、远端引用能到的)永远安全。
8. **"`git commit --amend`/rebase 改了提交"** —— 对象不可变;这些操作是**新建对象 + 移动 ref**,旧提交仍留在库里等 gc。
9. **"SHA-1 哈希碰撞是 Git 的现实风险"** —— Git 的对象哈希还混入了类型与长度前缀,且校验时按内容重验;Git 已支持 `--object-format=sha256`(本机实测可用,`hello world\n` 在 sha256 仓库中得到 64 位哈希)。

## 8. 结语:一张全景图

```
                     ┌─────────────────────────────────────────────┐
                     │              .git/objects(不可变)          │
                     │                                             │
                     │   tag 12b75e3 ──> commit 8970169 (merge)    │
                     │                      │ │                    │
                     │             parent ↓  │  ↓ parent           │
                     │   commit 24df7f9      │    commit d3c62dc   │
                     │      │                 │        │           │
                     │    tree de3a2eb   tree e5bfca  tree <...>   │
                     │      │  ...层层指向 blob...                    │
                     └──────────▲───────────────▲───────────────────┘
                                │               │
   .git/refs/heads/* ───────────┘               └── .git/refs/tags/*   (41字节文件)
            ▲                                                   │
            │ ref:                                              │ peel
   .git/HEAD ──┘                                     .git/packed-refs
            ▲
            │ 每次移动都记一笔
   .git/logs/* (reflog)

   工作区 ──(hash-object + update-index)──> .git/index ──(write-tree)──> 对象库
```

把这张图记住,再回头看任何 Git 命令,看到的无非是:算哈希、写对象、移动 ref、更新 index——四种动作的组合。
