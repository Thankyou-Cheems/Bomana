# 02/13 18:03 战雷端口信息分析

> 联网搜索分析战雷8111端口返回的战局信息是什么样的？有没有可能实现对当局玩家列表的读取？





🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...

根据搜索到的资料，以下是对 War Thunder（战争雷霆）`localhost:8111` 本地 API 的详细分析：

## 8111 端口概述

当 War Thunder 运行且进入对局时，游戏会在 `localhost:8111` 暴露一组 HTTP API 端点[[1]](https://deepwiki.com/lucasvmx/WarThunder-localhost-documentation/3-developer-guide)。这是游戏进程自身创建的本地 Web 服务器。最知名的利用该接口的第三方工具是 WTRTI（War Thunder Real Time Information）。

## 可用端点及返回数据

该 API 提供以下主要端点：

**`/indicators`** — 飞行仪表数据（空速、高度、过载等）

**`/state`** — 载具状态参数（发动机温度、油量、部件损伤等）

**`/map_info.json`** — 地图元数据，包含坐标系和网格信息。地图系统使用归一化坐标，位置用 0 到 1 之间的值表示，代表在地图上的相对位置[[2]](https://deepwiki.com/lucasvmx/WarThunder-localhost-documentation/2.2-map-system)。

**`/map_obj.json`** — 返回当前地图上所有对象的数组，包括位置、类型和视觉属性[[3]](https://deepwiki.com/lucasvmx/WarThunder-localhost-documentation/2.2-map-system)。包含飞机、坦克、轰炸点、机场等的坐标和朝向（`dx`、`dy` 方向向量）。

**`/map.img`** — 当前地图的图片。

**`/mission.json`** — 任务目标和状态。

**`/gamechat`** — 游戏内聊天消息。通过 `?lastId=0` 参数访问，返回包含 `id`、`msg`、`sender`、`enemy`、`mode` 字段的 JSON 数组[[4]](https://github.com/lucasvmx/WarThunder-localhost-documentation/issues/1)。这是唯一会出现**玩家昵称**的端点。

**`/hudmsg`** — 类似 gamechat，返回包含 `events` 和 `damage` 两个键的字典[[5]](https://github.com/lucasvmx/WarThunder-localhost-documentation/blob/master/Hudmsg/Hudmsg.md)，记录击杀、击伤等战斗事件。

## 能否读取当局玩家列表？

**直接获取完整玩家列表——不能。** 原因如下：

1. **`/map_obj.json`** 虽然包含地图上的单位对象，但它只返回**在你小地图上可见的单位**的位置和图标类型（`type`、`icon`、`color`），并不包含玩家昵称。在模拟模式中，敌方玩家数据不会显示，友方空中数据仅在约 0.75km 范围内显示[[6]](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/194)。其他模式虽然显示更多，但仍然受限于游戏小地图的可见范围。

2. **`/gamechat`** 和 **`/hudmsg`** 是唯一会泄露玩家名的端点，但前者只在玩家发言时才显示名字，后者只在击杀/被击杀等事件发生时出现名字。这意味着你只能被动地收集在聊天或战斗日志中出现过的玩家名，无法一次性获得完整名单。

3. **没有类似 `/players` 或 `/scoreboard` 的端点**——API 不提供记分板或房间内玩家列表。

## 间接实现方案

虽然不能直接获取，但可以通过以下方式**间接拼凑**当局玩家信息：

- **监听 `/hudmsg`**：持续轮询伤害和击杀事件，从中提取出现的玩家名。随着对局推进，大部分参与交战的玩家名会逐渐被捕获。
- **监听 `/gamechat`**：记录所有发言者的 `sender` 字段。
- **结合第三方网站**：用从上述端点获得的玩家名去查询 Thunderskill 等统计网站的 API，获取更详细的玩家数据。
- **服务器回放（Server Replay）**：对局结束后通过 War Thunder 的服务器回放链接（需要在战绩页面获取回放 URL），可以拿到完整的对局数据，包括所有玩家列表和载具信息——但这不是实时的。

总结来说，`localhost:8111` 的设计目的主要是为了遥测显示和地图辅助，而非提供完整的玩家信息。Gaijin 有意限制了数据范围以避免出现不公平优势。

---

## 📚 参考来源

1. [Developer Guide | lucasvmx/WarThunder-localhost-documentation | DeepWiki](https://deepwiki.com/lucasvmx/WarThunder-localhost-documentation/3-developer-guide)
2, 3. [Map System | lucasvmx/WarThunder-localhost-documentation | DeepWiki](https://deepwiki.com/lucasvmx/WarThunder-localhost-documentation/2.2-map-system)
4. [missing endpoints · Issue #1 · lucasvmx/WarThunder-localhost-documentation](https://github.com/lucasvmx/WarThunder-localhost-documentation/issues/1)
5. [WarThunder-localhost-documentation/Hudmsg/Hudmsg.md at master · lucasvmx/WarThunder-localhost-documentation](https://github.com/lucasvmx/WarThunder-localhost-documentation/blob/master/Hudmsg/Hudmsg.md)
6. [Tools using data provided on port 8111 - #194 by LaPlus_Darknesss - General Discussion - War Thunder — official forum](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/194)


-----

> 我记得有人做了战雷tk队友毒瘤玩家的局内提醒功能，它是如何获取到局内信息的





🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...

好的，根据大量搜索和社区讨论，以下是关于你提到的"TK毒瘤玩家局内提醒"功能的技术实现分析。

## 核心难题：如何获取当局玩家名单？

正如前面分析的，`localhost:8111` 本地 API **不提供玩家名单**。论坛讨论中明确指出，获取玩家名是实现此类工具的最大障碍，因为玩家昵称并不存储在 localhost 接口中[[1]](https://forum.warthunder.com/t/statshark-in-game-overlay/256939)。

那么，已有的工具（包括你提到的 TK 提醒功能、StatShark 的局内追踪等）主要依靠以下几条路径来获取局内玩家信息：

### 方法一：解密 .clog 客户端日志（实时读取）

War Thunder 客户端会生成 `.clog` 日志文件，记录用户在一个游戏会话中的所有操作[[2]](https://wiki.warthunder.com/306-technical-client-logs-clog)，包括客户端接收到的服务器消息。这些日志记录了进入战局时服务器下发的玩家列表和载具信息。

关键点在于：

- `.clog` 文件是**经过 XOR 加密**的，普通文本编辑器无法直接读取。
- 社区已有工具（如 `wt-tools`）可以用密钥文件解密 `.clog`[[3]](https://github.com/klensy/wt-tools)，也有专门的 `clog_decomp.py` 脚本用于解密这些日志[[4]](https://github.com/cyberofficial/clog-decrypter)。
- 关键是可以在游戏**运行时实时尾读（tail）** `.clog` 文件，解密后从中提取出当局所有玩家的昵称和载具信息。这是目前社区中最主流的获取玩家列表的手段。

### 方法二：监听/解析网络数据包

一些更高级的实现会直接监听战雷客户端与服务器之间的网络通信。在进入对局时，服务器会向客户端推送一个包含所有参战玩家昵称、所属阵营、载具类型的数据包。通过抓包分析（类似 Wireshark 的方式）并解析协议，可以提取这些信息。这种方式更加实时，但技术门槛也更高，且游戏的通信协议不公开，需要逆向分析。

### 方法三：结合 8111 端口被动收集

如前所述，`/gamechat` 和 `/hudmsg` 端点会在聊天和战斗事件中暴露玩家名。虽然不完整，但可以作为辅助手段，尤其是 `/hudmsg` 中的击杀/伤害事件包含攻击者和受害者的名字。

## "TK毒瘤提醒"的典型工作流程

结合以上信息，这类工具的实现逻辑大致是：

1. **进入对局时**：通过实时解密 `.clog` 文件（或监听网络数据包），提取当局所有玩家的昵称列表。
2. **查询外部数据库**：将玩家名批量查询自建的数据库或第三方统计网站（如 StatShark、Thunderskill），获取每个玩家的 TK 记录、胜率、被举报次数等信息。有些工具维护了一个**社区共建的 TK 黑名单数据库**，专门收录恶意 TK 玩家。
3. **触发提醒**：如果检测到当局有在黑名单中的玩家，通过 Overlay 弹窗或语音提示警告用户小心该玩家。

## 关于合规性

论坛讨论中，社区成员对这类 overlay 是否给予"不公平优势"存在争议[[5]](https://forum.warthunder.com/t/statshark-in-game-overlay/256939)。一方面所有数据本来就是公开可查的（玩家资料页任何人都能看），另一方面自动化地在局内展示这些信息确实会影响玩家行为。Gaijin 目前的官方态度是允许使用 `localhost:8111` 数据的工具（如 WTRTI），但对于读取 `.clog` 文件或抓包获取玩家列表这种行为，并没有明确的官方表态——灰色地带。StatShark 近期也引发了类似的争议（有人质疑 StatShark 是如何实时追踪玩家所在的对局和使用的载具[[6]](https://forum.warthunder.com/t/how-can-statshark-track-what-match-you-are-in-and-what-vehicles-other-players-use/269977)）。

总结来说，**获取玩家列表的核心手段是实时解密 `.clog` 日志文件**，而不是通过 `localhost:8111` 端口。8111 端口的数据侧重于遥测和地图，缺少玩家身份信息。

---

## 📚 参考来源

1, 5. [Statshark in-game overlay?](https://forum.warthunder.com/t/statshark-in-game-overlay/256939)
2. [[Technical\] Client logs (.clog) | War Thunder Wiki](https://wiki.warthunder.com/306-technical-client-logs-clog)
3. [GitHub - klensy/wt-tools: War Thunder resource extraction tools](https://github.com/klensy/wt-tools)
4. [GitHub - cyberofficial/clog-decrypter: log file decryption tool for war thunder](https://github.com/cyberofficial/clog-decrypter)
6. [How can Statshark track what match you are in and what vehicles other players use? - General Discussion - War Thunder — official forum](https://forum.warthunder.com/t/how-can-statshark-track-what-match-you-are-in-and-what-vehicles-other-players-use/269977)


-----

> 有没有人讲解过怎么解析战雷的各种log文件？这些log文件的解析能带来哪些信息





🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_fetch



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...

根据搜索到的各类资料，以下是关于战雷各类日志/数据文件解析的全面整理。

## 一、战雷主要文件格式概览

战雷的数据生态涉及多种专有文件格式。游戏安装目录下的核心文件包括 `aces.vromfs.bin`、`char.vromfs.bin`、`gui.vromfs.bin`、`lang.vromfs.bin`、`mis.vromfs.bin` 等 vromfs 包文件，以及 `Replays/` 目录中的 `.wrpl` 回放文件和 `.game_logs/` 中的 `.clog` 客户端日志[[1]](https://github.com/klensy/wt-tools/wiki)。

社区中最完善的解析工具集是 **klensy/wt-tools**，它包含 `blk_unpack`、`clog_unpack`、`ddsx_unpack`、`dxp_unpack`、`vromfs_unpacker`、`wrpl_unpacker`、`blk_minify` 等一整套工具[[2]](https://github.com/klensy/wt-tools/commit/ca4218fae0e83047653ff20edcdf5b792776bd0d)。另有 **Keksilton/WtTools** 是用 C# 重写的版本，支持 `.vromfs.bin`、`.blk`、`.wrpl` 的解析，并且提供了一个 Web 界面[[3]](https://github.com/Keksilton/WtTools)。

---

## 二、各文件格式详解

### 1. `.clog` — 客户端日志

`.clog` 文件由 War Thunder 客户端生成，记录了用户在一个游戏会话中执行的所有操作，同时还记录客户端侧的计算和内置错误捕获信息[[4]](https://wiki.warthunder.com/306-technical-client-logs-clog)。游戏启动时开始记录，关闭时结束。

**加密方式**：文件使用 XOR 加密，普通文本编辑器无法直接读取。Gaijin 加密 clog 的原因从未官方说明，社区推测可能是因为日志中包含的游戏信息可能被外挂开发者利用，或者是为了保护玩家隐私（因为 clog 经常被公开张贴在论坛上）[[5]](https://steamcommunity.com/app/236390/discussions/4/2263565217517522424/)。

**解密工具**：
- **wt-tools** 的 `clog_unpack`：用 keyfile.bin 作为密钥解密 clog 为纯文本 log 文件[[6]](https://github.com/klensy/wt-tools)
- **clog-decrypter**（`clog_decomp.py`）：一个独立的 Python 脚本，不需要额外依赖，直接解密 `.clog` 文件[[7]](https://github.com/cyberofficial/clog-decrypter)

**解密后能获得什么信息**：

解密后的 clog 是一个大量的纯文本日志流，按时间戳记录了客户端的各种事件，典型内容包括：

- **进入对局时的匹配信息**：服务器地址、房间 ID、地图名称
- **玩家列表**：加入房间时服务器下发的所有玩家昵称、所属队伍、使用的载具型号——这是获取局内完整玩家列表的关键来源
- **载具生成/销毁事件**：谁在何时生成了什么载具
- **客户端计算日志**：伤害计算、弹道计算、命中判定等客户端侧数据
- **网络同步信息**：与服务器之间的数据包交互
- **错误和崩溃信息**：方便排查技术问题
- **系统信息**：GPU/CPU 型号、驱动版本、显示设置等

有开发者提到了实时 tail 读取 clog 的需求，但游戏运行时文件被占用，使用编译好的脚本只能解密游戏未锁定的 clog 文件，用原始 VBS 脚本可以 tail 但似乎有 20MB 上限[[8]](https://github.com/klensy/wt-tools/issues/35)。这说明**实时读取是有技术挑战的**，但并非不可能。

### 2. `.blk` — 游戏配置/数据文件

BLK 是战雷最核心的数据格式，几乎所有游戏配置都以这种二进制格式存储。`blk_unpack` 工具可以将 `.blk` 解包为 JSON 格式的 `.blkx` 文件，也可以导出为游戏可识别的格式[[9]](https://github.com/klensy/wt-tools)。

BLK 文件承载的数据内容极为丰富：飞机的损伤模型（DM）和飞行模型（FM）分别在 `gamedata/flightmodels/` 和 `gamedata/flightmodels/fm/` 中；坦克的 FM/DM 在 `gamedata/units/tankmodels/` 中；武器设置包括机炮、炸弹、火箭弹、鱼雷分别在 `gamedata/weapons/` 下的不同子目录[[10]](https://github.com/klensy/wt-tools/wiki)。

**能提取的信息**：所有载具的详细参数（装甲厚度、穿深、发动机参数、飞行模型系数等）、武器预设、任务配置文件等。这是 datamining（数据挖掘）社区的核心素材。

### 3. `.vromfs.bin` — 游戏资源打包文件

这是战雷的资源打包格式。`vromfs_unpacker` 可以解包这些文件，内部可以包含任何类型的数据[[11]](https://github.com/klensy/wt-tools)，解包后通常得到大量 `.blk` 文件和其他资源。

### 4. `.wrpl` — 客户端回放文件

客户端录制的本地回放文件。解包 wrpl 后可以得到 `wrplu.bin` 文件，用 zlib 解压后可以看到包含任务参数的可读字符串，如占领区位置、重生点等信息——基本上是 CDK 任务编辑器中 BLK 文件会包含的那些数据[[12]](https://github.com/klensy/wt-tools/issues/77)。

不过客户端回放有局限性。回放记录是从你自己客户端视角出发的，缺少部分服务器侧数据。

### 5. `.ddsx` / `.dxp.bin` — 贴图/纹理文件

游戏纹理的专有压缩格式。`ddsx_unpack` 可以将其解包为标准 `.dds` 贴图文件，但解包大多数纹理需要 `oo2core_6_win64.dll` 库[[13]](https://github.com/klensy/wt-tools)。

### 6. 服务器回放（Server Replay）

这不是本地文件，而是通过 War Thunder 官网访问的在线回放。服务器回放功能允许以战斗中任意玩家的视角观看服务器上所有战斗的回放[[14]](https://warthunder.com/zh/news/238-)，网页支持按战斗模式、载具类型筛选，也可以通过玩家昵称搜索[[15]](https://warthunder.com/zh/news/238-)。服务器回放包含完整的对局数据，包括所有玩家名、载具、事件等，是数据最完整的来源——但只能在对局结束后获取，不是实时的。

---

## 三、信息获取能力总结

| 数据来源 | 玩家列表 | 载具信息 | 实时性 | 难度 |
|---------|---------|---------|-------|------|
| `.clog` 解密 | ✅ 完整 | ✅ 完整 | ⚠️ 可实时但有挑战 | 中 |
| `localhost:8111` | ❌ 无昵称 | ⚠️ 仅图标类型 | ✅ 实时 | 低 |
| `/gamechat` + `/hudmsg` | ⚠️ 仅发言/参战者 | ❌ | ✅ 实时 | 低 |
| 服务器回放 | ✅ 完整 | ✅ 完整 | ❌ 仅赛后 | 低 |
| 网络抓包 | ✅ 完整 | ✅ 完整 | ✅ 实时 | 高 |

---

## 四、社区讨论现状

目前社区中关于这些文件的详细教程其实比较碎片化。**wt-tools** 的 GitHub wiki 是目前最系统的参考，讲解了文件目录结构和各工具用法。但关于 clog 解密后的内容结构（哪些行代表什么含义），并没有公开的系统性文档——这也符合 Gaijin 加密 clog 的初衷。社区对此的看法是，Gaijin 可能是为了防止外挂开发者利用日志中的游戏信息来更好地理解客户端[[16]](https://steamcommunity.com/app/236390/discussions/4/2263565217517522424/)。

StatShark 等站点如何实现实时局内追踪至今仍有一定神秘感，论坛上也有人直接质疑 StatShark 到底怎么能实时获取你所在的对局和其他玩家使用的载具[[17]](https://forum.warthunder.com/t/how-can-statshark-track-what-match-you-are-in-and-what-vehicles-other-players-use/269977)，得到的回答是"数字黑魔法"。这暗示其可能综合使用了 clog 实时读取、网络层分析等多种手段。

---

## 📚 参考来源

1, 10. [Home · klensy/wt-tools Wiki · GitHub](https://github.com/klensy/wt-tools/wiki)
2. [update_checker: check game version online and download yup file · klensy/wt-tools@ca4218f](https://github.com/klensy/wt-tools/commit/ca4218fae0e83047653ff20edcdf5b792776bd0d)
3. [GitHub - Keksilton/WtTools: Datamining tools for War Thunder](https://github.com/Keksilton/WtTools)
4. [[Technical\] Client logs (.clog) | War Thunder Wiki](https://wiki.warthunder.com/306-technical-client-logs-clog)
5, 16. [How to read crashlogs? :: War Thunder Technical Problems/Advice](https://steamcommunity.com/app/236390/discussions/4/2263565217517522424/)
6, 9, 11, 13. [GitHub - klensy/wt-tools: War Thunder resource extraction tools](https://github.com/klensy/wt-tools)
7. [GitHub - cyberofficial/clog-decrypter: log file decryption tool for war thunder](https://github.com/cyberofficial/clog-decrypter)
8. [Simple Question *.clog keyfile · Issue #35 · klensy/wt-tools](https://github.com/klensy/wt-tools/issues/35)
12. [wrpl unpacker doesn't work with replays that have a nuclear explosion · Issue #77 · klensy/wt-tools](https://github.com/klensy/wt-tools/issues/77)
14, 15. [[新闻\] 全新服务器回放服务 新闻-War Thuner](https://warthunder.com/zh/news/238-)
17. [How can Statshark track what match you are in and what vehicles other players use? - General Discussion - War Thunder — official forum](https://forum.warthunder.com/t/how-can-statshark-track-what-match-you-are-in-and-what-vehicles-other-players-use/269977)


-----

> 分析一下clog实时解密的可行性与方案，并分析是否会被BE反作弊识别为作弊，因为我想开发一个改善游戏环境的预防毒瘤一类的功能，但是需要实时解析防止被玩家滥用





🔧 **工具调用:** web_search



> 💭 思考中...



🔧 **工具调用:** web_search



> 💭 思考中...

以下是关于 clog 实时解密可行性、BattlEye 风险以及架构设计方案的系统性分析。

---

## 一、BattlEye 的工作原理与检测边界

先理解 BE 到底在"看"什么：

BattlEye 可以在用户态和内核态两个层面进行扫描，能够访问底层系统活动来检测试图隐藏自身或在底层修改数据的作弊行为。除了对文件的静态检查，它还使用启发式和行为分析方法来监控其他程序如何与游戏进程及其内存交互[[1]](https://en.wikipedia.org/wiki/BattlEye)。

具体来说，BE 的核心检测范围包括：

它会在游戏进程周围添加保护层，旨在尽早阻止常见攻击方法，如直接内存编辑、DLL 注入和附加外部工具。在游戏运行时，BE 执行动态检查，寻找异常行为、已知作弊模式和试图隐藏自身的工具[[2]](https://en.wikipedia.org/wiki/BattlEye)。

而 BattlEye 官方对"合法软件"的态度是：

一般来说，我们只会因为使用实际的作弊/外挂或旨在故意绕过 BE 保护的作弊组件而封禁。否则你不需要担心被封。例如，非作弊类 overlay 和视觉增强工具如 Reshade 或 SweetFX 通常是被支持的，除非游戏开发者另有要求。我们可能会因为使用某些特定程序（如宏工具）而踢出（不是封禁）你，但这不会自动把你标记为作弊者[[3]](https://support.gaijin.net/hc/en-us/articles/21638218281362-BattlEye-anti-cheat-troubleshooting)。

---

## 二、clog 实时读取的风险等级分析

### 读取 clog 文件 ≠ 操作游戏进程

这是最关键的区分。clog 文件是磁盘上的一个**普通文件**，不是游戏进程的内存。从 BE 检测维度来看：

| 行为 | BE 检测风险 | 原因 |
|------|-----------|------|
| **读取磁盘上的 .clog 文件** | 🟢 极低 | 与游戏进程无交互，等同于读任何普通文件 |
| **通过标准 API 打开文件句柄** | 🟢 极低 | 不涉及进程注入或内存操作 |
| **注入 DLL 到 aces.exe** | 🔴 极高 | 直接触发 BE 检测 |
| **ReadProcessMemory 读游戏内存** | 🔴 极高 | BE 核心监控对象 |
| **Hook 游戏函数** | 🔴 极高 | BE 核心检测项 |
| **HTTP 请求 localhost:8111** | 🟢 无风险 | 完全合法，WTRTI 就这么做 |

读取 `.clog` 文件本质上和你用记事本打开一个文本文件没有区别。你的程序运行在自己的进程空间内，通过标准文件 I/O API（`CreateFile` / `ReadFile` 或 Python 的 `open()`）读取磁盘文件。BE 关注的是谁在碰**游戏进程**，而不是谁在读**磁盘上的日志文件**。

### 潜在风险点

虽然读文件本身安全，但有几个边缘情况需要注意：

1. **文件锁定问题**：游戏运行时 `aces.exe` 对 clog 文件持有写锁。你需要用**共享读取模式**（`FILE_SHARE_READ`）打开文件，不能影响游戏的写入操作。如果你的程序导致游戏无法写入 clog，可能引发游戏崩溃或 BE 报错。

2. **程序签名/特征**：如果你的工具被打包器混淆、无签名、或恰好与某个已知作弊工具有相似的二进制特征，BE 可能会将其标记。保持代码干净、用标准工具链编译、不做任何反调试操作即可。

3. **不要触碰游戏目录中的文件**：只读 `.game_logs/` 目录下的 clog，不要写入或修改游戏安装目录中的任何文件。

---

## 三、实时解密技术方案

### 方案 A：文件尾读（File Tailing）— 推荐

这是最安全、最简单的方案：

```
原理：
游戏运行 → 持续写入 .clog 文件
          ↘
你的程序 → 用共享读取模式打开同一文件 → 定期读取新增字节 → XOR 解密 → 解析文本
```

**实现要点**：

- 以 `FILE_SHARE_READ | FILE_SHARE_WRITE` 模式打开 clog 文件
- 记录上次读取的文件偏移量，每次只读取新增部分
- 对新读取的字节执行 XOR 解密（clog 的加密就是简单的 XOR，密钥是固定的循环密钥）
- 逐行解析解密后的文本，用正则表达式或关键词匹配提取感兴趣的信息

**优势**：完全不接触游戏进程，纯粹的文件 I/O 操作，BE 风险最低。

**劣势**：有开发者反映过实时 tail 读取 clog 时存在约 20MB 上限的问题[[4]](https://github.com/klensy/wt-tools/issues/35)，可能需要处理文件缓冲和 flush 延迟。此外，游戏可能不是实时 flush 到磁盘的，可能有几秒到几十秒的延迟。

### 方案 B：监控文件变化 + 增量读取

```
FileSystemWatcher 监控 .game_logs/ 目录
         ↓ 文件变化事件
读取增量数据 → XOR 解密 → 解析
```

用操作系统的文件监控 API（Windows 的 `ReadDirectoryChangesW` 或 .NET 的 `FileSystemWatcher`）监听 clog 文件的写入事件，触发时读取增量数据。比轮询更高效。

### 方案 C：localhost:8111 + clog 混合方案

将 8111 端口的实时数据（遥测、地图对象等）与 clog 中的玩家列表信息结合：

```
clog 解密 → 提取玩家列表和载具信息（进房时一次性获取）
8111 API → 实时获取游戏状态、地图、聊天（持续轮询）
         ↓
合并数据 → 查询黑名单数据库 → 触发 overlay 警告
```

这是目前最实际的混合方案，既获得了完整玩家列表，又有实时游戏状态。

---

## 四、clog 中的玩家数据提取

根据社区逆向分析，clog 解密后在**进入对局时**会出现类似以下模式的日志行（格式可能随版本变化）：

- 匹配/房间创建信息（包含 session ID、服务器地址）
- 玩家加入事件（包含玩家昵称、用户 ID、队伍编号）
- 载具生成事件（包含玩家名、载具内部 ID）
- 击杀/伤害事件
- 聊天消息

你需要做的是：在 clog 的实时流中识别对局开始的标记，然后提取随后的玩家列表数据。具体的关键词和格式需要你自己解密几个 clog 样本来确认，因为这些内容没有公开的标准文档。

---

## 五、防止工具被滥用的设计建议

你提到想防止玩家滥用，这一点很关键。以下是一些架构层面的建议：

**1. 只暴露有限信息**
- 不显示具体统计数据（KD、胜率等），只显示"该玩家在黑名单中"的警告
- 不显示敌方玩家信息，只提醒己方队友中的潜在毒瘤

**2. 黑名单数据源控制**
- 使用社区维护的经过审核的 TK 黑名单，而不是开放让任何人随意添加
- 要求多人举报且有回放证据才能入库

**3. 不做 overlay 覆盖游戏画面**
- 考虑做成独立窗口或系统通知，而不是注入游戏画面的 overlay
- 这样既避免 BE 的潜在干扰，也降低被认为是"修改游戏"的风险

**4. 开源透明**
- 开源代码，让社区和 Gaijin 都能审查，证明工具不含作弊功能

---

## 六、法律/TOS 风险评估

BattlEye 在战雷中持续监控对游戏进程的任何干扰。该反作弊的主要目标是防止利用漏洞获取优势的不诚实玩家[[5]](https://wiki.warthunder.com/mechanics/anticheat)。

从 Gaijin 的 TOS 角度看，有几个层次：

- **localhost:8111 工具**：明确被允许（WTRTI、WTbgA 等先例）
- **读取本地磁盘文件**：灰色地带，但没有先例表明读 clog 会被封禁
- **overlay 显示额外信息**：如果不注入游戏进程（如 WTRTI 的做法），目前是被容忍的
- **显示其他玩家统计**：这是争议最大的部分，StatShark 的存在表明目前 Gaijin 没有主动打击这类行为

总体评估：一个**只读取磁盘日志文件、不接触游戏进程和内存、不注入任何代码**的工具，从 BattlEye 技术检测的角度来看被封禁的风险非常低。但 Gaijin 理论上可以在任何时候修改 TOS 来禁止此类工具，这是政策风险而非技术风险。最稳妥的做法是公开项目意图、保持代码透明，让社区和官方都能判断工具的性质。

---

## 📚 参考来源

1, 2. [BattlEye - Wikipedia](https://en.wikipedia.org/wiki/BattlEye)
3. [BattlEye anti-cheat troubleshooting – Gaijin Support](https://support.gaijin.net/hc/en-us/articles/21638218281362-BattlEye-anti-cheat-troubleshooting)
4. [Simple Question *.clog keyfile · Issue #35 · klensy/wt-tools](https://github.com/klensy/wt-tools/issues/35)
5. [Fighting Unfair Play and BattlEye Anti-Cheat | War Thunder Wiki](https://wiki.warthunder.com/mechanics/anticheat)