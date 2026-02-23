# ESP32-C3 BLE广播脚本 - 带MAC地址显示
import bluetooth
import ubinascii

# 初始化BLE
ble = bluetooth.BLE()
ble.active(True)

# 获取MAC地址
mac_addr = ble.config('mac')[1]  # [1]是BLE的MAC地址，[0]是经典蓝牙的
mac_str = ubinascii.hexlify(mac_addr, ':').decode().upper()

# 设置设备名称
device_name = "ESP-C3-001"

# 构建广播数据
flags = b'\x02\x01\x06'  # 通用可发现模式
name_data = bytes([len(device_name) + 1, 0x09]) + device_name.encode()
adv_data = flags + name_data

# 设置广播间隔（微秒）
interval_us = 50000  # 50ms

# 开始广播
ble.gap_advertise(interval_us, adv_data=adv_data, connectable=False)

# 打印信息
print("=" * 50)
print("BLE广播已启动")
print(f"设备名称: {device_name}")
print(f"MAC地址: {mac_str}")
print("=" * 50)
print(f"请在S3扫描脚本中使用此MAC地址: {mac_str}")
print("提示：可以在S3脚本中添加过滤功能，只显示此MAC地址的设备")
