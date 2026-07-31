# IM-SYAU 载板（插整块 S3 开发板）

**约 54×68 mm · 4 层**。左排母插 DevKit，右列充电/开关。开发板自带 3.3 V LDO，载板不再放 AMS1117。

## 组装

1. 打板贴片本载板（4 层）  
2. 焊两排 **2.54 mm 1×22 排母**（或把开发板排针直接焊进孔）  
3. 插入 **ESP32-S3 N16R8**（DevKitC-1 兼容，排距 22.86 mm）  
4. 烧录用开发板上的 **USB**；本板 **J1** 只负责充电  

**插向（按乐鑫 DevKitC-1）**：开发板 **USB 朝 pin22（板底）**；正面朝上时 **有丝印 5V 的那一侧进 J3**（`J3.21=5V`，`J3.22=GND`）。杂牌板务必按丝印核对，勿盲插。

部分克隆板从排针灌 5 V 前需短路板上的 **5V 二极管焊盘 / N-OUT**，否则 5 V 脚灌不进去——先万用表确认。

**不要**同时用载板 `J1` 充电供电 + 开发板 USB 长时间并联（可能顶牛）；调试烧录时建议 `SW2` 断开载板 5 V。

## 开关

| 开关 | 作用 |
|---|---|
| **SW1 PWR_CUT** | 切断整机（插 USB 仍可充电池） |
| **SW2 ESP_CUT** | 切断送给开发板的 5 V |

## 购物

| 已有 | 还要买 |
|---|---|
| ESP32-S3 N16R8 核心板 | `1×22 排母 2.54mm` ×2 |
| | `TP4056` / `SS34`×2 / `USB-C 16P` / `JST-PH 2.0` / 拨码开关×2 / `0805` 阻容 LED / 保险丝 |
| | 电池：`3.7V LiPo 带保护 JST-PH` |

## 再生

在本目录（`hardware/im-syau/`）执行：

```text
python tools\build_one.py
%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe tools\finish_one.py
```

Gerber：`fab/gerber/`

本板与仓库根目录固件同属 **IM-SYAU-ble-esp-mcpy-loader**；导览后端 / 前端是独立项目 **IM-SYAU-Core**（`XRK-AGT/core/IM-SYAU-Core`），勿与本仓合并。
