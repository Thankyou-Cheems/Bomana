# 大厅对战区预估伤害与收益系数：公式闭合（2026-08-23）

## 范围

只读取 Datamine / 已安装 VROMFS 的静态文件和 GUI 脚本，没有附加游戏进程。
目标是让计算器在炸弹字段变化时只改输入、重跑提取器，而不是手抄大厅数字。

## 大厅 UI 实际显示什么

`gui.vromfs.bin_u/scripts/weaponry/weaponrytooltippkg.nut` 在空战 RB/SB 下调用：

- `getWeaponDamage(unit, preset, customWeaponTable)` → `wpcost.blk` 里每条武器的 `weaponDamage` 求和
- `getPresetRewardMul(unit, damage) * 10` → 「对战区收益系数」

中文键：`shop/estimated_damage_to_base_title`（对战区预估伤害）、
`shop/reward_multiplier_for_base`（对战区收益系数）。

`wpcost.weaponDamage` 是生成物，不是公式本身。公式输入在武器 BLK 和
`explosive.blkx`。

## 高爆 / 制导炸弹 / 多数火箭

```
tnte = explosiveMass * strengthEquivalent
base = lerp(explosiveTypeToSplashParams.explosiveMassToDamage, tnte)
pen  = lerp(explosiveTypeToSplashParams.explosiveMassToPenetration, tnte)
if pen < bombing_zone.armorThickness (25 mm):
    damage = base * (pen / 25) * restrainExplosionDamage (0.6)
else:
    damage = base
```

用 Mk 82 / Mk 83 / Mk 84 / GBU-39 校验，四舍五入后等于 hangar `weaponDamage`。
穿深不足 25 mm 的火箭（2024-07-23 过伤修复）走欠穿分支，不能再用 TNT×8。

`gameparams.bombingZoneHpToTntEquivalentTons=0.000125`（1 kg TNT = 8 HP）
不是大厅公式，也不能解释 1175.9 kg 摧毁高阶战区。

## 燃烧弹

显式 `splash` + `fireDamage`：

```
instant = splash.damage * (splash.penetration / 25) * 0.6
fire    = fireDamage.damage * fireDamage.lifeTime * napalmDamageMult(13)
damage  = instant + fire
```

Mk 77 mod 4：14500×20/25×0.6 + 10×30×13 = 10860，与 hangar 一致。
ZB-500：2 枚 hangar 伤害 ≈ 25886，刚好够高阶战区满血。

## 核弹

`yieldToExplosionParameters`：5 kt → 200000，30 kt → 1200000。

## 收益系数

`warpoints.blkx` `BombingRewardMultipliers`：

- `presetDmgMin=18000`、`presetDmgMax=97500`、`bombingRewardModifier=2`
- 伤害 ≥ 200000 走 piecewise 表
- 战斗机 ×0.8，金皮 ×1.2
- UI 再 ×10，显示一位小数

## 用户例外

| 挂载 | TNT 当量 | 公式伤害 | 高阶 90% 线 23310 | 满血 25900 |
| --- | ---: | ---: | --- | --- |
| 10×Mk 82 | 1175.85 kg | 24638 | 点燃 | 未满血，靠燃烧尾段 |
| 2×GBU-31 + 1×GBU-39 | 1183.67 kg | 23104 | 不够 | 不够 |
| 2×GBU-31 + 2×GBU-39 | 1210.12 kg | 24243 | 点燃 | 未满血 |

TNT 千克不能直接比大小：GBU-39 在曲线左端每千克伤害更高，但单枚绝对伤害只有
约 1139，补一枚才能过 90% 线。

## 更新约定

1. 炸弹字段变了：重跑 `tools/extract_strike_weapon_damage.py`。
2. 曲线/装甲/收益表变了：同一提取器会重写 `bombing_zone_splash.json`。
3. 不要把 `wpcost.weaponDamage` 抄进目录。它只适合做回归校验。
