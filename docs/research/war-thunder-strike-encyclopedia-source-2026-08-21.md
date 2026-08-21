# War Thunder EC 打击百科：机场结构与摧毁当量来源核对

日期：2026-08-21
研究范围：仅离线静态客户端/Datamine、仓库已有 `ec_airfield_catalog.json`、官方 War Thunder Wiki/CDK；未启动、附加或读取游戏进程，未读取 8111 以外的运行时状态。

## 先区分附件与本次请求

用户附件 `C:\Users\cheb2\AppData\Local\Temp\codex-clipboard-e51a2ee5-70f0-4a40-98e4-845cb2bc2997.jpg` 是一张二手机场示意图。它没有可验证的版本、地图、坐标、尺寸或 Gaijin 字段，因此本文只把它当作待核对的视觉假设：

- 蓝色：跑道；红色：油库；黄色：机库；绿色：居民区。
- 图中数字 `0/4/9`、`1/5/10` 等没有证据表明是游戏原生模块 ID。
- 附件不作为 App 资源，不复制、不打包、不描摹；百科图应由下文的四模块数值几何原创生成 SVG/Canvas，并标注“版本锁定离线静态模型”，不能标作服务器命中框。

本次用户请求是：核对现代长跑道机场结构，并为 App 规划可由用户自行打开的机场结构与战区摧毁当量百科。附件本身不是产品指令，也不是第一方数据源。

## 结论摘要

1. **3200 m 长跑道模板与附件的拓扑关系基本一致。** 版本锁定的 3200 m 模板中，跑道外的 `storage`、`dwelling`、`parking` 全在跑道同一侧；沿模板 `airfield.start -> airfield.end` 的纵向顺序是“油库 → 居民区 → 停机/维修区”。若把附件中左下到右上的箭头方向看作模板的反向，则正好是“停机/维修区 → 居民区 → 油库”。
2. **不能把附件说成精确比例图。** 附件没有尺寸，且画出了灰色停机坪、连接道路和建筑细节；静态机场模块字段只给四条线段的 `start/end/width`，没有这些装饰几何的命中语义，也没有模块高度。
3. **当前 EC 不是只有“二战/现代”两个静态模板。** 客户端任务脚本按 `balance_level` 分成 `[0,3]`、`[4,7]`、`[8,11]`、`[12,16]`、`[17,20]`、`[21,50]` 六个耐久区间；机场几何还由多个 `unit_class` 和地图/rank 分支决定。官方 Wiki 只把 EC1--5 与 EC6+ 作为展示族，不能替代静态字段。
4. **可以发布的“摧毁当量”首先是任务 HP，不是 TNT 千克。** `ft_fields_template.blkx` 和 `bdt_bases_destroy_template.blkx` 明确给出机场模块/战区基地的内部 `hp` 参数；客户端炸弹则有 `mass`、`explosiveType`、`explosiveMass`。当前静态资料没有把机场/基地 HP 转换成 TNT 等效千克的官方公式，因此百科不得把 `hp` 直接标成“吨 TNT”，也不得从 `explosiveMass` 直接改名为 TNTe。
5. **百科可同时展示三种值，但必须分栏并标注证据等级：** `mission_hp`（客户端脚本耐久参数）、`raw_explosive_mass_kg`（炸弹配置字段）、`tnte_reference_kg`（官方 Wiki 装备文章给出的参考值，非任务脚本契约）。

## 来源锁

### 机场几何目录

仓库目录：[`bomana/data/ec_airfield_catalog.json`](../../bomana/data/ec_airfield_catalog.json)
文件 SHA-256：`1582B8D60EBAFEE84291D7DE666D814C542DF035382353FA4EA86D767FE009EA`
目录 `schema`：`wt_ec_airfield_template/v1`
`summary`：48 layouts、1,380 object-group placements、11 templates、4 unique module geometries、5 size-inclusive template geometries。

目录 provenance：

```json
{
  "client_version": "2.57.1.83",
  "mis_archive_sha256": "6334580315DD5D08E3C25ACC4C9E3FE52E0AD40246D36C603C40C144FF889BAE",
  "aces_archive_sha256": "09B65E1ABDB3C484D4EFF7984F77AA2F626853A4163C8FF166D50A9D89E733A9"
}
```

目录来源链是：

```text
mis.vromfs.bin EC map/rank layout
  -> object_groups[].tm + unit_class
  -> aces objectgroups/<unit_class>.blkx
  -> airfield/storage/parking/dwelling {start,end,width}
```

本记录继续保留 `bomb_zone.tm`、端点匹配和服务器命中边界的证据限制；公开发布不把这些静态矩形声明为服务器命中框。

### 当前 Datamine 交叉核对

本地 `D:\Dev\War-Thunder-Datamine` 为版本 `2.57.1.89`，Git commit `9f8cdbc99342ccc7aeb8d0e684eb1a409384053e`。当前 sparse checkout 没有把 `mis.vromfs.bin_u` 写到工作树，但 Git 对象中的原始文本可直接读取；没有因此修改 Datamine 工作树。

| 逻辑文件 | Git blob | 解码文本 SHA-256 | 用途 |
| --- | --- | --- | --- |
| `aces.vromfs.bin_u/gamedata/objectgroups/dynaf_pg_1line_3000_universal.blkx` | `31a03a181c5a71b4d5e708d829aa6cca4fb8064b` | `A11E795A31DB35055900AD4656147EECC542B09AF7080B2D61EE54689AD703BE` | 当前 3200 m 四模块几何 |
| `mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/ft_fields_template.blkx` | `b31bd03ce8ae34668b827159bcfe703676e276f1` | `6A60D0E438D50A8F1DCCE4123C92FDA740481A5082709960C8B6E86B68BB631E` | EC 模块 HP 区间与四模块绑定 |
| `mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/bdt_bases_destroy_template.blkx` | `c8d6dd2b22b907a24bd2d02448507586ec9d1033` | `D378921C875C7EF37BE78BD00B542C8DF352E7CCC14386EC3798B65B9F18B8E0` | EC `bombing_point`/基地 HP 区间 |

可审阅的 Datamine 原始文件链接：

- [`dynaf_pg_1line_3000_universal.blkx`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/aces.vromfs.bin_u/gamedata/objectgroups/dynaf_pg_1line_3000_universal.blkx)
- [`ft_fields_template.blkx`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/ft_fields_template.blkx)
- [`bdt_bases_destroy_template.blkx`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/bdt_bases_destroy_template.blkx)

### 官方资料

- [Enduring Confrontation](https://wiki.warthunder.com/gamemode/enduring_confrontation)：官方说明 EC 机场有跑道、油库、停机/维修区、生活区四个可分别受损区域；耐久随 EC rank 增长；只有炸弹落在所属区域才计入伤害；基地耐久取决于 battle rank。
- [Use of CCRP in Sim battles (Sim EC)](https://wiki.warthunder.com/mechanics/1067-use-of-ccrp-in-sim-battles-sim-ec)：官方 Wiki 的操作参考中给出高权重战区常见“一个基地约 6 枚 Mk.83”的经验性说明；这是用户级攻略参考，不是任务脚本的 HP/TNT 契约。
- [Ballistic Computer](https://wiki.warthunder.com/mechanics/177-ballistic-computer)：官方说明 `Switch mission bombing target` 会在 mini-base 或 airfield 之间选择任务投弹目标，可作为百科对 CCRP 目标概念的说明。
- [CDK mission creation: Factory Defense](https://wiki.warthunder.com/cdk/228-mission-creation-factory-defense) 与 [Custom units creation](https://wiki.warthunder.com/cdk/1212-custom-units-creation)：官方 CDK 资料证明机场/跑道使用 `start/end/width` 的米制几何概念；没有公开 EC 四模块相对偏移的完整 schema。

## 3200 m 长跑道几何

### 原始字段

`dynaf_pg_1line_3000_universal.blkx` 的 `size` 是 `[3500, 5000]`。四个模块字段为：

```json
{
  "airfield": {
    "start": [1700.0, 0.0, -208.5],
    "end": [-1500.0, 0.0, -208.5],
    "width": 120.0
  },
  "storage": {
    "start": [1700.0, 0.0, 200.0],
    "end": [1150.0, 0.0, 200.0],
    "width": 300.0
  },
  "parking": {
    "start": [-90.0, 0.0, 15.0],
    "end": [-930.0, 0.0, 15.0],
    "width": 230.0
  },
  "dwelling": {
    "start": [400.0, 0.0, 110.0],
    "end": [0.0, 0.0, 110.0],
    "width": 220.0
  }
}
```

三种 `dynaf_pg_1line_3000_{sand,snow,universal}` 与 `dynaf_universal_1line_3000_a` 的四模块数值几何相同；后者的顶层 `size` 为 `[3500,500]`，所以 size-inclusive fingerprint 仍应区分。

### 计算约定

只在本地 X/Z 平面计算，不把 `Y=0` 误当成服务器高度：

```text
runway_start = (1700, -208.5)
runway_end   = (-1500, -208.5)
d            = normalize(runway_end - runway_start) = (-1, 0)
s            = dot(point - runway_start, d) = 1700 - x
side_plus_z  = z - (-208.5) = z + 208.5
```

沿跑道的左法向（与既有几何推导一致）是 `n=(-d.z,d.x)=(0,-1)`。因此在这个局部图框中，`-Z` 是法向左侧，`+Z` 是法向右侧。为避免地图坐标轴语义漂移，产品应同时保存 `side_sign` 和原始 `local_z`，不要只保存一个未注明坐标约定的“左/右”。

### 相对跑道的数值结果

纵向范围以 `s=0` 的 runway start 为起点；侧向范围以跑道中心线为零，正值为 `+Z`。矩形边界由 `start/end/width` 推导，未添加高度。

| 模块 | 原始端点 | 长度 | 宽度 | 纵向范围 `s` | 中心 `s` | 中心侧向 `+Z` | 侧向边界 `+Z` | 相对跑道侧 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `airfield` 跑道 | `1700 -> -1500`，`z=-208.5` | 3200 m | 120 m | 0–3200 m | 1600 m | 0 m | -60–+60 m | 中心线 |
| `storage` 油库 | `1700 -> 1150`，`z=200` | 550 m | 300 m | 0–550 m | 275 m | +408.5 m | +258.5–+558.5 m | `+Z` 侧 |
| `dwelling` 居民区/生活区 | `400 -> 0`，`z=110` | 400 m | 220 m | 1300–1700 m | 1500 m | +318.5 m | +208.5–+428.5 m | `+Z` 侧 |
| `parking` 停机/维修区 | `-90 -> -930`，`z=15` | 840 m | 230 m | 1790–2630 m | 2210 m | +223.5 m | +108.5–+338.5 m | `+Z` 侧 |

关键间隔：`storage` 结束至 `dwelling` 开始约 750 m；`dwelling` 结束至 `parking` 开始约 90 m。相对跑道长度，三块辅助区的纵向长度约为 17.2%、12.5%、26.3%。

### 与附件的核对

| 对比项 | 3200 m 静态模板 | 附件表现 | 判断 |
| --- | --- | --- | --- |
| 辅助模块侧向 | `storage/dwelling/parking` 全在同一 `+Z` 侧 | 三个彩色功能区都位于主跑道同一侧 | 拓扑一致 |
| 纵向顺序 | start→end 为油库→居民区→停机/维修区 | 图面左下→右上约为停机/维修区→居民区→油库 | 反向读取后顺序一致 |
| 模块尺寸比例 | 550/400/840 m，宽 300/220/230 m | 黄色区最长、绿色区中等、红色区较短；宽度未标注 | 视觉上相容，不能做精度证明 |
| 语义 | `parking` 是停机/维修区，不保证等于所有建筑均为“机库” | 黄色标为机库 | 应在百科标“停机/维修区（含维修）”，可将“机库”作为用户俗称 |
| 连接道路/灰色停机坪 | 不在四模块 `start/end/width` 字段内 | 图中画出多条连接线和大面积灰色铺面 | 只能作为原创说明图装饰，不能当命中边界 |
| 数字编号 | 原生实例使用 `ft_t1/ft_t2_airfield_*` 等名称 | `0/4/9` 等无对应字段 | 不可当作原生模块 ID |
| 方向/镜像 | 每个 map placement 有旋转矩阵；端点应允许正反匹配 | 图中只给视觉方向 | 运行时应以 8111 跑道端点绑定后再旋转模板 |

所以，“现代长跑道机场大致由一条 3200 m 跑道、同侧的油库/生活区/停机维修区组成”这个百科结论可以发布；“附件就是当前所有现代机场的精确结构图”不能发布。

## EC 机场模块的耐久字段

### 机场四模块绑定

`ft_fields_template.blkx` 在开头通过 `missionGetBalanceLevel` 得到 `ft_balance_level`（约第 100 行），在机场属性中把：

- `airfield` 的 `hp_var` 绑定到 `ft_airfield_module_spawn_hp`；
- `storage`、`parking`、`dwelling` 的 `hp_var` 绑定到 `ft_airfield_module_hp`。

敌方机场被发现时，`missionSetBombingArea` 的 `hp` 使用变量 `ft_airfield_module_hp`，并同时挂接相应的 `airfield` 对象（T1 约第 6496--6502 行，T2 约第 7263--7269 行）。因此这是机场模块/任务区的静态耐久参数，而非 8111 字段。

### 由 `balance_level` 选择的机场参数

下表直接来自 `ft_matching_*_check` 的 `varSetReal`，不是根据图片或炸弹重量拟合。区间边界由条件的 `less/more` 得出。

| `balance_level` | 任务脚本触发器 | `ft_airfield_module_hp`：storage/parking/dwelling | `ft_airfield_module_spawn_hp`：airfield/runway | `ft_damage_restore_base_hp`：恢复基数 |
| ---: | --- | ---: | ---: | ---: |
| 0–3 | `ft_matching_0_3_check` | 12,000 | 24,000 | 300 |
| 4–7 | `ft_matching_4_7_check` | 34,000 | 68,000 | 850 |
| 8–11 | `ft_matching_8_11_check` | 48,000 | 96,000 | 1,200 |
| 12–16 | `ft_matching_12_16_check` | 100,000 | 200,000 | 2,500 |
| 17–20 | `ft_matching_17_20_check` | 120,000 | 240,000 | 3,000 |
| 21–50 | `ft_matching_21_50_check` | 160,000 | 280,000 | 4,000 |

原始证据锚点：[`ft_fields_template.blkx#L3792-L4173`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/ft_fields_template.blkx#L3792-L4173)。

注意：变量初始值约在第 12799--12800 行为 `8000/16000`，随后由匹配 routine 覆盖；百科必须显示“初始化默认值”和“按 balance_level 选定值”不是同一个字段状态。`ft_balance_level_forced` 还允许任务配置强制选择，故不能仅凭地图名称猜耐久档。

### 这不是 TNT 等效

这些数值的单位是任务内部 HP/耐久量。源文件没有 `kg`、`TNT`、`TNTe` 或把模块 HP 映射到炸弹爆炸质量的公式。官方 EC Wiki 只确认耐久随 rank 增长、炸弹必须落在所属区域，不给 HP 或 TNT 表。因此产品应显示：

```text
机场模块耐久（客户端 mission_hp）：12,000 / 34,000 / ... / 160,000
跑道模块初始化耐久（客户端 mission_hp）：24,000 / 68,000 / ... / 280,000
```

不要显示成“12,000 kg TNT”，也不要据此宣称一枚特定炸弹必然摧毁模块；命中区域、爆炸模型、任务脚本和版本都会影响结果。

## EC bombing_point/基地的耐久字段

### 基地目标与机场模块是两条独立链

`bdt_bases_destroy_template.blkx` 的基地生成逻辑在 T1/T2 对每个 `bombing_point` 调用 `missionSetBombingArea`，使用 `bdt_base_hp`（约第 949--956、1762--1769 行）。这与 `ft_fields_template.blkx` 的机场 `airfield` 绑定不同，百科数据模型不能把二者合并成一个“机场 HP”。

### 基地 HP 档位

| `bdt_balance_level` | `bomb_areas_*_check` | `bdt_base_hp`（planes） | `bdt_base_hp`（`bdt_mission_mode=heli` 后） |
| ---: | --- | ---: | ---: |
| 0–3 | `bomb_areas_0_3_check` | 4,000 | 400 |
| 4–7 | `bomb_areas_4_7_check` | 6,000 | 600 |
| 8–11 | `bomb_areas_8_11_check` | 10,000 | 1,000 |
| 12–16 | `bomb_areas_12_16_check` | 16,000 | 1,600 |
| 17–20 | `bomb_areas_17_20_check` | 22,000 | 2,200 |
| 21–50 | `bomb_areas_21_50_check` | 25,900 | 2,590 |

原始证据锚点：[`bdt_bases_destroy_template.blkx#L2763-L3205`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/bdt_bases_destroy_template.blkx#L2763-L3205)。基地 `missionSetBombingArea` 和 `bdt_mission_mode` 分支分别见 [`#L949-L956`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/bdt_bases_destroy_template.blkx#L949-L956) 与 [`#L3247-L3260`](https://github.com/gszabi99/War-Thunder-Datamine/blob/9f8cdbc99342ccc7aeb8d0e684eb1a409384053e/mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/bdt_bases_destroy_template.blkx#L3247-L3260)。

默认变量约在第 4957--4958 行为 `bdt_base_hp=2000`、`bdt_balance_level=0`；正常启动时由 `bomb_areas_*_check` 根据 balance level 覆盖。`heli` 分支把基地 HP 除以 10；这不是机场四模块分支。

## 炸弹“摧毁当量”可用的静态字段

### 当前客户端炸弹字段

炸弹配置通常有：

- `bomb.mass`：弹体总质量；
- `bomb.explosiveType`：爆炸物类型字符串；
- `bomb.explosiveMass`：客户端原始爆炸物质量；
- `hitPowerMult`、`nearHitPower`、`midHitPower`、`farHitPower`、`explosionPatchRadius` 等爆炸/命中参数。

这些字段可以作为 App 离线炸弹百科的真实静态输入，但 `explosiveMass` 不能自动改名为 TNT equivalent。不同 `explosiveType` 的能量折算由当前公开静态文件无法完整闭合；尤其 Mk 77 的类型是 `napalm`，其燃烧伤害链不能用普通炸弹的爆压字段替代。

### 版本锁定样例

| 炸弹文件 | `mass` kg | `explosiveType` | `explosiveMass` kg（原始客户端字段） | `explosionPatchRadius` | 官方 Wiki TNTe 参考 |
| --- | ---: | --- | ---: | --- | ---: |
| `us_500lb_mk_82_ldgp.blkx` | 240.9 | `comp_h6` | 87.1 | `[4,8]` | 117.6 kg |
| `us_1000lb_mk_83_ldgp.blkx` | 446.8 | `comp_h6` | 201.8 | `[4,12]` | 272.4 kg |
| `su_fab_500m_62t.blkx` | 508.3 | `tgaf_5` | 213.0 | `[4,12]` | 340.8 kg |
| `us_500lb_mk77_mod4.blkx` | 235.9 | `napalm` | 207.3 | `15` | 当前官方 Wiki 资料未找到可直接对应的 TNTe 值；显示“燃烧弹原始字段”，不要伪造 TNT |

本次核对的本地文件 SHA-256：

- `us_500lb_mk_82_ldgp.blkx`: `27499BFFCD47346C594811702E968E99634B7D9BBF6F4AB8D317B00539543803`
- `us_1000lb_mk_83_ldgp.blkx`: `F884A0BEBC63548C30CC1D6C7ADC29ABE5B183457C010DDBF4476FDBFA8007DB`
- `su_fab_500m_62t.blkx`: `CE23DE64513C53E3F63C5AE4F7803353DA787B37B5368DE140BC9FFEDB8FFFD8`
- `us_500lb_mk77_mod4.blkx`: `0F3C9593DC312BC95F57D11458859EB2F258B39C82542647AAE3ED7A18FDE5B1`

官方 Wiki 装备文章的 TNTe 表是另一类资料。例如 [Kfir C.10 文章](https://wiki.warthunder.com/6001-kfir-c-10_colombian-dorito)列出 Mk82=117.6 kg、Mk83=272.4 kg；[MiG-29 Sniper 文章](https://wiki.warthunder.com/3721-mig-29-sniper-soviet-origins-western-technology)列出 Mk82=117.6 kg、FAB-500M-62=340.8 kg、Mk83=272.4 kg、ZB-500=250 kg。这些是 Wiki 的 TNTe 参考值，不能用来反推 EC `mission_hp` 的换算系数。

官方 Wiki 的 Sim EC 操作文章说高权重战区常见“一座基地约 6 枚 Mk83”；这可以在百科中作为“实战参考”显示，但应标注 `wiki_reference / not_mission_contract`，不能写成 `bdt_base_hp=6×TNTe` 的公式。

## 不可声明的内容

在当前证据边界内，百科、投弹计算或 UI 不得声明：

- 机场模块的 `mission_hp` 等于 TNT 千克，或存在一个版本无关的“每公斤炸弹伤害”常数；
- `bomb.explosiveMass` 就是 TNTe，尤其不能对 `napalm`/Mk77 做普通高爆换算；
- 一枚指定炸弹在任意 EC rank、任意任务模式下必然摧毁机场模块或基地；
- `storage/parking/dwelling` 的平面矩形就是服务器 3D hitbox；四条 `start/end/width` 没有高度；
- 附件中的灰色停机坪、道路、建筑轮廓属于四模块伤害区；
- `0/4/9` 等附件编号是 8111 的机场 ID 或 Datamine 的模块 ID；
- EC 只有现代与二战两套布局；当前脚本至少有六个耐久档和多个静态几何族；
- 8111 的 `airfield` 线段本身提供模块 ID、模块 HP、模块状态或基地归属。

## 建议的百科数据模型

百科应是离线只读资料，与运行时 8111 目标绑定分开：

```json
{
  "schema": "strike_encyclopedia/v1",
  "airport_layouts": [
    {
      "layout_id": "ec-3200-four-module-v1",
      "scope": {
        "mode": "EC",
        "client_version": "2.57.1.83",
        "rank_ranges": [[20, 50]],
        "unit_classes": ["dynaf_pg_1line_3000_universal"]
      },
      "anchor": "runway_pose",
      "modules": [
        {"kind": "airfield", "start": [1700, 0, -208.5], "end": [-1500, 0, -208.5], "width_m": 120},
        {"kind": "storage", "start": [1700, 0, 200], "end": [1150, 0, 200], "width_m": 300},
        {"kind": "dwelling", "start": [400, 0, 110], "end": [0, 0, 110], "width_m": 220},
        {"kind": "parking", "start": [-90, 0, 15], "end": [-930, 0, 15], "width_m": 230}
      ],
      "claim": "offline_static_planar_geometry",
      "server_hitbox_validated": false,
      "source": {
        "catalog": "bomana/data/ec_airfield_catalog.json",
        "catalog_sha256": "1582B8D60EBAFEE84291D7DE666D814C542DF035382353FA4EA86D767FE009EA",
        "objectgroup_path": "aces.vromfs.bin_u/gamedata/objectgroups/dynaf_pg_1line_3000_universal.blkx",
        "objectgroup_sha256": "A11E795A31DB35055900AD4656147EECC542B09AF7080B2D61EE54689AD703BE"
      }
    }
  ],
  "ec_durability": [
    {
      "target_kind": "airport_module",
      "balance_level": [21, 50],
      "module_hp": 160000,
      "runway_spawn_hp": 280000,
      "repair_base_hp": 4000,
      "value_kind": "mission_hp",
      "source": "ft_fields_template.blkx"
    },
    {
      "target_kind": "bombing_point",
      "balance_level": [21, 50],
      "planes_hp": 25900,
      "heli_hp": 2590,
      "value_kind": "mission_hp",
      "source": "bdt_bases_destroy_template.blkx"
    }
  ],
  "weapon_profiles": [
    {
      "weapon_id": "us_1000lb_mk_83_ldgp",
      "mass_kg": 446.8,
      "explosive_type": "comp_h6",
      "raw_explosive_mass_kg": 201.8,
      "tnte_reference_kg": 272.4,
      "tnte_source_kind": "official_wiki_reference",
      "value_kind": "separate_from_mission_hp"
    }
  ]
}
```

建议 UI 分三层：

1. **机场结构图**：由四条数值线段生成原创 SVG/Canvas；显示跑道、油库、停机/维修区、居民区的相对顺序和尺寸比例，图下注明客户端版本、地图/rank 适用范围。
2. **战区耐久表**：按 `balance_level` 展示机场模块 HP、跑道 HP、基地 HP；标题写“客户端任务耐久参数”，不要写“摧毁所需 TNT”。
3. **炸弹参考表**：显示弹体质量、原始 `explosiveType/explosiveMass`，只有有官方 Wiki TNTe 资料的炸弹才显示另一个独立的“TNTe 参考”列；Mk77 显示 napalm/燃烧伤害提示，不显示伪造 TNT 数字。

图中如需显示动态 8111 目标，只把已匹配的跑道 pose 作为锚点，标注“当前局跑道绑定”；模块矩形仍应标“离线静态推导”，不标成服务器命中框。无法唯一匹配模板时百科仍可打开，但投弹模块提示必须 fail closed。

## 最终证据边界

本研究已经闭合：

- 3200 m 长跑道的四模块相对位置、纵向顺序、同侧关系和附件的拓扑一致性判断；
- EC 机场六个 `balance_level` 耐久档及跑道/辅助模块分工；
- EC bombing point 六个 `bdt_base_hp` 档位以及直升机模式的 `/10` 分支；
- 客户端炸弹原始质量/爆炸物字段与官方 Wiki TNTe 参考值的分层关系；
- App 百科应使用原创数值图、来源锁和 `native-unknown` 边界。

仍未闭合、必须保留为 `native-unknown` 的部分：

- 服务器对四模块的垂直命中范围、边界容差和爆炸归属；
- `mission_hp` 到炸弹 TNTe/爆压的原生换算公式；
- 8111 `map_obj.json` 是否在所有版本/模式都把 `airfield.sx/sy/ex/ey` 作为官方跑道 start/end 契约；
- 附件示意图数字编号与当前任务实例的任何稳定映射。
