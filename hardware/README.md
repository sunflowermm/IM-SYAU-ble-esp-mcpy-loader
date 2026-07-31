# 硬件（KiCad）

与本仓固件配套的 **IM-SYAU 载板**。固件在仓库根 `esp32s3/`、`esp32c3mini/`；导览业务在独立 Core：`XRK-AGT/core/IM-SYAU-Core`。

| 路径 | 说明 |
|------|------|
| [`im-syau/`](im-syau/) | 主载板：约 54×68 mm · 4 层，插 ESP32-S3 DevKit；含原理图/PCB、Gerber、组装说明 |

## 约定

- 改 `.kicad_sch` / `.kicad_pcb` 前先关 KiCad GUI
- 锁文件 / `.history` / `.backups` / Freerouting 会话已在根 `.gitignore`
- 出厂文件：`im-syau/fab/gerber/` + `positions.csv`
