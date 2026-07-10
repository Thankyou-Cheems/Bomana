# 8111 对局录制 | Session Recording

This guide records one real War Thunder sortie for Bomana's offline replay
fixtures. The recorder reads only the four official loopback 8111 endpoints and
does not require administrator rights.

本指南用于录制一场真实 War Thunder 出击，作为 Bomana 离线回放的格式基线。录制器
只读取四个官方本机 8111 端点，不需要管理员权限。

## Before recording | 录制前

1. Open PowerShell in the Bomana source checkout.
2. Run `uv sync --python 3.14.5` if dependencies are not installed.
3. Start the recorder before entering battle. Bomana may run at the same time.

在 Bomana 源码目录打开 PowerShell；如果尚未安装依赖，先运行
`uv sync --python 3.14.5`。建议在进入战斗前启动录制器，Bomana 可以同时运行。

## Record one sortie | 录制一场出击

```powershell
uv run python tools/record_8111_session.py `
  --label "full-sortie-1" `
  --mode SB
```

Then enter a battle and cover as many of these transitions as practical:

- hangar/battle transition and spawn;
- takeoff, normal flight, turning, and opening/closing the map;
- bombing, overspeed, navigation, or zone changes when available;
- landing/refit or death and another spawn.

进入战斗后尽量覆盖：出生、起飞、正常飞行与转向、开关地图；条件允许时再覆盖投弹、
超速、导航或战区变化，以及着陆补给或死亡后再次出生。不必刻意录满 20 分钟。

Press `Ctrl+C` once after the sortie. The recorder writes a final summary and
moves the completed file to:

```text
recordings/8111_session_<UTC timestamp>.jsonl.gz
```

出击结束后按一次 `Ctrl+C`。正常收尾会写入 summary，并把完成文件放到上述目录。

## Useful options | 常用选项

| Option | Meaning |
| --- | --- |
| `--duration 1200` | Stop automatically after 20 real minutes; zero/default waits for `Ctrl+C` |
| `--interval 0.25` | Record high-frequency endpoints at 4 Hz |
| `--map-info-interval 30` | Match the App's map-info cache cadence |
| `--game-version "x.y"` | Add a manually supplied game-version label |
| `--output recordings/name.jsonl.gz` | Choose the local output filename |
| `--force` | Replace an existing output and its `.partial` file |

## File contents and privacy | 文件内容与隐私

Each gzip JSONL file contains:

- one `meta` record with recorder settings;
- synchronized `sample` records for `/indicators`, `/state`,
  `/map_obj.json`, and periodic `/map_info.json`;
- decoded payloads plus HTTP status, latency, byte size, content type, and body
  SHA-256;
- one `summary` record with duration, aircraft types, and endpoint statistics.

Every line follows
`docs/specs/schemas/8111-session-record.schema.json`; the recorder reads the
format version from this schema so code and fixtures cannot silently drift.

The recorder does not query or add the Windows username, hostname, account ID,
process information, memory, modules, packets, logs, or game files. It preserves
decoded official endpoint payloads, so captures may contain any labels and
gameplay telemetry returned there, including aircraft type and player/map
position. Keep the complete capture local or attach it directly for project
analysis; review it before publishing it publicly.

录制器不会主动查询或添加 Windows 用户名、主机名、账号 ID、进程信息、内存、模块、
网络包、日志或游戏文件。它会原样保留官方端点解码后的 payload，因此其中可能包含
端点返回的标签、机型、玩家位置和地图位置等对局遥测；完整文件应保留在本机或直接
作为项目分析附件，公开发布前请先检查。

If the terminal is killed instead of using `Ctrl+C`, a `.partial` file may
remain. Keep it for recovery, but do not use it as a golden replay fixture
because it may lack the final summary.

## Validate and fast-forward | 校验与快进

Run the completed capture through production `GameLogic` without opening War
Thunder or contacting port 8111:

```powershell
uv run python tools/replay_8111_session.py `
  recordings/8111_session_<UTC timestamp>.jsonl.gz `
  --speed max `
  --profile full-sortie
```

`--speed max` advances directly from frame to frame. A numeric value such as
`--speed 20` paces replay at 20x recorded time. The default report is written
beside the capture as `<name>.replay-report.json`; use `--report <path>` to
choose another local path.

回放开始前会校验每行 schema、记录顺序、时间单调性和 summary 统计；任何篡改或不完整
文件都会被拒绝。`full-sortie` 要求大厅失败、存活、两次起飞、着陆整备、投弹、跨越
15 分钟周期、临界超速和玩家对象消失全部出现，否则返回非零退出码。

The report intentionally omits map positions. A pass verifies deterministic
core behavior against captured 4 Hz input; it does not validate Tk rendering,
global hotkeys, or behavior between recorded frames.
