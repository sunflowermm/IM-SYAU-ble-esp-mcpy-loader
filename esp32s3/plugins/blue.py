# -*- coding: utf-8 -*-
"""
蓝牙信标扫描插件 v3.0 - 批量上报优化版
修复:
1. 修复上报失败问题
2. 批量大小提升到50
3. 优化上报逻辑
4. 添加上报调试日志
5. 改进扫描参数
"""

import bluetooth
import uasyncio as asyncio
import time
import gc
import sys
from micropython import const

sys.path.append('/plugins/base')
from plugin import Plugin

# BLE事件常量
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)


class BlueConfig:
    """蓝牙扫描配置"""
    # 扫描参数
    SCAN_DURATION = 2000         # 2秒扫描
    SCAN_INTERVAL = 2.5          # 2.5秒一次
    REPORT_INTERVAL = 3.0        # 3秒上报
    
    # 数据采集
    SAMPLES_PER_REPORT = 3
    HISTORY_SIZE = 5
    OFFLINE_TIMEOUT = 10.0
    
    # 设备管理
    MAX_DEVICES = 100            # 增加到100
    DEVICE_NAME_PREFIX = None    # None=扫描所有设备
    
    # 批处理（关键优化）
    BATCH_SIZE = 50              # 每批50个设备
    BATCH_DELAY = 0.05           # 批次间50ms
    
    # 内存管理
    MEMORY_THRESHOLD = 20000
    CRITICAL_MEMORY = 10000
    GC_INTERVAL = 20
    
    # 错误处理
    MAX_CONSECUTIVE_ERRORS = 3
    ERROR_COOLDOWN = 3
    
    # 调试选项
    DEBUG_SCAN = True
    DEBUG_REPORT = True          # 上报调试


class Blue(Plugin):
    """优化的BLE信标扫描插件"""
    
    def __init__(self, loader):
        super().__init__(loader, "Blue", enabled=True)
        
        self.capabilities = [
            "ble_beacon",
            "rssi_tracking", 
            "fast_update",
            "multi_beacon"
        ]
        
        # 硬件
        self.ble = None
        self.scanning = False
        
        # 设备追踪
        self.devices = {}
        self.devices_lock = None
        
        # 状态控制
        self.running = True
        self.consecutive_errors = 0
        
        # 扫描统计
        self.scan_stats = {
            'total_scans': 0,
            'devices_found_per_scan': [],
            'last_scan_devices': 0
        }
        
        # 统计数据
        self.plugin_stats = {
            'scans_completed': 0,
            'devices_tracked': 0,
            'reports_sent': 0,
            'reports_failed': 0,
            'samples_collected': 0,
            'memory_cleanups': 0,
            'errors_caught': 0,
            'last_report_time': 0
        }
        
        # 异步任务
        self._scan_task = None
        self._report_task = None
        self._gc_task = None
        
        self.logger.info("初始化配置完成")
    
    async def _do_init(self):
        """初始化插件"""
        try:
            self.logger.info("========== BLE扫描器初始化 ==========")
            
            # 内存检查
            gc.collect()
            free_mem = gc.mem_free()
            self.logger.info("可用内存: %d bytes" % free_mem)
            
            if free_mem < BlueConfig.MEMORY_THRESHOLD:
                self.logger.error("内存不足")
                return False
            
            # 激活蓝牙
            self.ble = bluetooth.BLE()
            self.ble.active(True)
            self.ble.irq(self._irq_handler)
            
            # 初始化锁
            import _thread
            self.devices_lock = _thread.allocate_lock()
            
            self.logger.info("蓝牙已激活")
            self.logger.info("扫描配置:")
            self.logger.info("  - 扫描时长: %dms" % BlueConfig.SCAN_DURATION)
            self.logger.info("  - 扫描间隔: %.1fs" % BlueConfig.SCAN_INTERVAL)
            self.logger.info("  - 上报间隔: %.1fs" % BlueConfig.REPORT_INTERVAL)
            self.logger.info("  - 批量大小: %d设备/批" % BlueConfig.BATCH_SIZE)
            
            if BlueConfig.DEVICE_NAME_PREFIX:
                self.logger.info("  - 目标前缀: %s" % BlueConfig.DEVICE_NAME_PREFIX)
            else:
                self.logger.info("  - 扫描模式: 全部设备")
            
            # 启动异步任务
            self._scan_task = asyncio.create_task(self._scan_loop())
            self._report_task = asyncio.create_task(self._report_loop())
            self._gc_task = asyncio.create_task(self._gc_loop())
            
            # 注册命令
            self.loader.register_command('blue_status', self._cmd_status)
            self.loader.register_command('blue_devices', self._cmd_devices)
            self.loader.register_command('blue_clear', self._cmd_clear)
            
            await self.send_log('info', 'BLE扫描器启动', {
                'batch_size': BlueConfig.BATCH_SIZE,
                'report_interval': BlueConfig.REPORT_INTERVAL
            })
            
            self.logger.info("========== 初始化完成 ==========")
            return True
            
        except Exception as e:
            self.logger.error("初始化失败: %s" % e)
            return False
    
    def _irq_handler(self, event, data):
        """BLE中断处理器"""
        try:
            if event == _IRQ_SCAN_RESULT:
                if gc.mem_free() < BlueConfig.CRITICAL_MEMORY:
                    return
                
                try:
                    addr_type, addr, adv_type, rssi, adv_data = data
                    mac = ':'.join(['%02X' % b for b in addr])
                    
                    # 解析设备名称
                    name = self._decode_name_robust(adv_data)
                    
                    # 过滤逻辑
                    if BlueConfig.DEVICE_NAME_PREFIX:
                        if name and name.startswith(BlueConfig.DEVICE_NAME_PREFIX):
                            self._update_device_fast(mac, name, rssi)
                    else:
                        # 扫描所有有名称的设备
                        if name:
                            self._update_device_fast(mac, name, rssi)
                            
                except Exception as e:
                    if BlueConfig.DEBUG_SCAN:
                        self.logger.error("处理扫描结果失败: %s" % e)
                    
            elif event == _IRQ_SCAN_DONE:
                self.scanning = False
                self.plugin_stats['scans_completed'] += 1
                
                # 记录统计
                scan_count = 0
                with self.devices_lock:
                    scan_count = len(self.devices)
                
                self.scan_stats['last_scan_devices'] = scan_count
                self.scan_stats['devices_found_per_scan'].append(scan_count)
                if len(self.scan_stats['devices_found_per_scan']) > 10:
                    self.scan_stats['devices_found_per_scan'].pop(0)
                
                if BlueConfig.DEBUG_SCAN:
                    self.logger.info("扫描完成: 发现 %d 个设备" % scan_count)
                
        except Exception as e:
            if BlueConfig.DEBUG_SCAN:
                self.logger.error("IRQ处理失败: %s" % e)
            self.scanning = False
    
    def _decode_name_robust(self, adv_data):
        """强化版设备名称解析"""
        if not adv_data or len(adv_data) < 3:
            return None
        
        try:
            i = 0
            while i < len(adv_data) - 1:
                try:
                    length = adv_data[i]
                    if length == 0 or i + length >= len(adv_data):
                        break
                    
                    ad_type = adv_data[i + 1]
                    
                    if ad_type in (0x08, 0x09):
                        payload = adv_data[i + 2:i + 1 + length]
                        
                        # 尝试UTF-8
                        try:
                            name = payload.decode('utf-8')
                            if name and len(name) > 0:
                                return name[:30]
                        except:
                            pass
                        
                        # 尝试ASCII
                        try:
                            name = payload.decode('ascii')
                            if name and len(name) > 0:
                                return name[:30]
                        except:
                            pass
                        
                        # 尝试Latin-1
                        try:
                            name = payload.decode('latin-1')
                            if name and len(name) > 0:
                                return name[:30]
                        except:
                            pass
                        
                        # 强制转换可打印字符
                        try:
                            result = ''
                            for b in payload:
                                if 32 <= b < 127:
                                    result += chr(b)
                                else:
                                    result += '?'
                            if result and len(result) > 0:
                                return result[:30]
                        except:
                            pass
                        
                        # 返回HEX
                        try:
                            hex_str = ''.join(['%02X' % b for b in payload])
                            return "HEX:" + hex_str[:20]
                        except:
                            pass
                    
                    i += 1 + length
                    
                except Exception:
                    break
                    
        except Exception as e:
            if BlueConfig.DEBUG_SCAN:
                self.logger.error("解析名称失败: %s" % e)
        
        return None
    
    def _update_device_fast(self, mac, name, rssi):
        """快速更新设备信息"""
        try:
            now = time.time()
            
            with self.devices_lock:
                if mac not in self.devices:
                    if len(self.devices) >= BlueConfig.MAX_DEVICES:
                        self._remove_oldest_offline()
                        if len(self.devices) >= BlueConfig.MAX_DEVICES:
                            return
                    
                    self.devices[mac] = {
                        'name': name,
                        'rssi_history': [],
                        'rssi_samples': [],
                        'last_seen': now,
                        'first_seen': now,
                        'online': True,
                        'sample_count': 0
                    }
                    self.plugin_stats['devices_tracked'] += 1
                    
                    if BlueConfig.DEBUG_SCAN:
                        self.logger.info("新设备: %s [%s]" % (name, mac[-8:]))
                
                device = self.devices[mac]
                device['rssi_samples'].append(rssi)
                device['last_seen'] = now
                device['online'] = True
                device['sample_count'] += 1
                self.plugin_stats['samples_collected'] += 1
                
                # 限制采样数量
                if len(device['rssi_samples']) > BlueConfig.SAMPLES_PER_REPORT * 3:
                    device['rssi_samples'] = device['rssi_samples'][-BlueConfig.SAMPLES_PER_REPORT:]
        except:
            pass
    
    def _remove_oldest_offline(self):
        """移除最旧的离线设备"""
        try:
            offline = [
                (mac, dev) for mac, dev in self.devices.items()
                if not dev['online']
            ]
            
            if offline:
                offline.sort(key=lambda x: x[1]['last_seen'])
                del self.devices[offline[0][0]]
        except:
            pass
    
    async def _scan_loop(self):
        """扫描循环"""
        self.logger.info("扫描任务启动")
        await asyncio.sleep(2)
        
        while self.running:
            try:
                if gc.mem_free() < BlueConfig.CRITICAL_MEMORY:
                    self.logger.warning("内存不足，暂停扫描")
                    await asyncio.sleep(5)
                    gc.collect()
                    continue
                
                if not self.scanning:
                    self.scanning = True
                    self.consecutive_errors = 0
                    
                    if BlueConfig.DEBUG_SCAN:
                        self.logger.info("开始扫描...")
                    
                    try:
                        self.ble.gap_scan(
                            BlueConfig.SCAN_DURATION,
                            30000,
                            30000,
                            False
                        )
                    except Exception as e:
                        self.logger.error("启动扫描失败: %s" % e)
                        self.scanning = False
                        await asyncio.sleep(2)
                        continue
                    
                    # 等待扫描完成
                    scan_start = time.ticks_ms()
                    timeout = BlueConfig.SCAN_DURATION + 500
                    
                    while self.scanning and time.ticks_diff(time.ticks_ms(), scan_start) < timeout:
                        await asyncio.sleep_ms(50)
                    
                    # 强制停止
                    if self.scanning:
                        try:
                            self.ble.gap_scan(None)
                        except:
                            pass
                        self.scanning = False
                    
                    # 检查离线设备
                    self._check_offline_fast()
                
                await asyncio.sleep(BlueConfig.SCAN_INTERVAL)
                
            except Exception as e:
                self.consecutive_errors += 1
                self.logger.error("扫描错误: %s" % e)
                self.scanning = False
                
                if self.consecutive_errors >= BlueConfig.MAX_CONSECUTIVE_ERRORS:
                    self.logger.error("连续错误过多，冷却中...")
                    await asyncio.sleep(BlueConfig.ERROR_COOLDOWN)
                    self.consecutive_errors = 0
                else:
                    await asyncio.sleep(1)
    
    def _check_offline_fast(self):
        """检查离线设备"""
        try:
            now = time.time()
            offline_count = 0
            
            with self.devices_lock:
                for device in self.devices.values():
                    if now - device['last_seen'] > BlueConfig.OFFLINE_TIMEOUT:
                        if device['online']:
                            device['online'] = False
                            offline_count += 1
            
            if offline_count > 0 and BlueConfig.DEBUG_SCAN:
                self.logger.info("%d 个设备离线" % offline_count)
        except:
            pass
    
    async def _report_loop(self):
        """上报循环"""
        self.logger.info("上报任务启动（间隔=%.1fs）" % BlueConfig.REPORT_INTERVAL)
        await asyncio.sleep(5)
        
        while self.running:
            try:
                if gc.mem_free() < BlueConfig.MEMORY_THRESHOLD:
                    gc.collect()
                
                await self._process_and_report()
                await asyncio.sleep(BlueConfig.REPORT_INTERVAL)
                
            except Exception as e:
                self.logger.error("上报失败: %s" % e)
                await asyncio.sleep(BlueConfig.REPORT_INTERVAL)
    
    async def _process_and_report(self):
        """处理并上报数据"""
        if not self.devices:
            if BlueConfig.DEBUG_REPORT:
                self.logger.info("无设备数据，跳过上报")
            return
        
        try:
            online_devices = []
            
            with self.devices_lock:
                for mac, device in self.devices.items():
                    if device['online'] and device['rssi_samples']:
                        samples = device['rssi_samples']
                        avg_rssi = sum(samples) / len(samples)
                        
                        device['rssi_history'].append(avg_rssi)
                        if len(device['rssi_history']) > BlueConfig.HISTORY_SIZE:
                            device['rssi_history'] = device['rssi_history'][-BlueConfig.HISTORY_SIZE:]
                        
                        beacon_data = {
                            'mac': mac,
                            'name': device['name'],
                            'online': True,
                            'rssi': {
                                'current': round(avg_rssi, 1),
                                'average': round(avg_rssi, 1),
                                'samples': len(samples),
                                'min': min(samples),
                                'max': max(samples),
                                'history_avg': round(
                                    sum(device['rssi_history']) / len(device['rssi_history']), 1
                                )
                            },
                            'last_seen': int(time.time() - device['last_seen']),
                            'sample_count': device['sample_count']
                        }
                        
                        online_devices.append(beacon_data)
                        device['rssi_samples'] = []
            
            if not online_devices:
                if BlueConfig.DEBUG_REPORT:
                    self.logger.info("无在线设备，跳过上报")
                return
            
            # 分批上报（50个/批）
            batch_count = (len(online_devices) + BlueConfig.BATCH_SIZE - 1) // BlueConfig.BATCH_SIZE
            
            if BlueConfig.DEBUG_REPORT:
                self.logger.info("准备上报: %d设备, %d批" % (len(online_devices), batch_count))
            
            for batch_idx in range(batch_count):
                if gc.mem_free() < BlueConfig.CRITICAL_MEMORY:
                    gc.collect()
                    if gc.mem_free() < BlueConfig.CRITICAL_MEMORY:
                        break
                
                start = batch_idx * BlueConfig.BATCH_SIZE
                end = min(start + BlueConfig.BATCH_SIZE, len(online_devices))
                batch = online_devices[start:end]
                
                report = {
                    'timestamp': time.time(),
                    'batch': batch_idx + 1,
                    'total_batches': batch_count,
                    'update_interval': BlueConfig.REPORT_INTERVAL,
                    'beacons': batch
                }
                
                # 关键：使用正确的事件名称
                if BlueConfig.DEBUG_REPORT:
                    self.logger.info("发送批次 %d/%d: %d设备" % (
                        batch_idx + 1, batch_count, len(batch)
                    ))
                
                success = await self.send_data('ble_beacon_batch', report)
                
                if success:
                    self.plugin_stats['reports_sent'] += 1
                    self.plugin_stats['last_report_time'] = time.time()
                    
                    self.logger.info("✓ 上报成功: 批%d/%d (%d设备)" % (
                        batch_idx + 1, batch_count, len(batch)
                    ))
                else:
                    self.plugin_stats['reports_failed'] += 1
                    self.logger.warning("✗ 上报失败: 批%d/%d" % (batch_idx + 1, batch_count))
                
                if batch_idx < batch_count - 1:
                    await asyncio.sleep(BlueConfig.BATCH_DELAY)
                    
        except Exception as e:
            self.plugin_stats['reports_failed'] += 1
            self.logger.error("处理失败: %s" % e)
    
    async def _gc_loop(self):
        """GC循环"""
        while self.running:
            try:
                await asyncio.sleep(BlueConfig.GC_INTERVAL)
                
                free_before = gc.mem_free()
                gc.collect()
                free_after = gc.mem_free()
                
                if free_after - free_before > 1000:
                    self.plugin_stats['memory_cleanups'] += 1
                
                if free_after < BlueConfig.CRITICAL_MEMORY:
                    with self.devices_lock:
                        offline_macs = [
                            mac for mac, dev in self.devices.items()
                            if not dev['online']
                        ]
                        for mac in offline_macs:
                            del self.devices[mac]
                        
                        if offline_macs:
                            self.logger.warning("紧急清理: %d设备" % len(offline_macs))
                    gc.collect()
                    
            except:
                await asyncio.sleep(BlueConfig.GC_INTERVAL)
    
    # ==================== 命令处理 ====================
    
    async def _cmd_status(self, params):
        """查询状态"""
        try:
            with self.devices_lock:
                device_count = len(self.devices)
                online_count = sum(1 for d in self.devices.values() if d['online'])
            
            gc.collect()
            
            avg_devices = 0
            if self.scan_stats['devices_found_per_scan']:
                avg_devices = sum(self.scan_stats['devices_found_per_scan']) / len(self.scan_stats['devices_found_per_scan'])
            
            return {
                "success": True,
                "status": {
                    "active": self.ble.active() if self.ble else False,
                    "scanning": self.scanning,
                    "devices": device_count,
                    "online": online_count,
                    "memory_free": gc.mem_free(),
                    "stats": self.plugin_stats,
                    "scan_stats": {
                        "total_scans": self.plugin_stats['scans_completed'],
                        "last_scan_devices": self.scan_stats['last_scan_devices'],
                        "avg_devices_per_scan": round(avg_devices, 1)
                    }
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _cmd_devices(self, params):
        """获取设备列表"""
        try:
            devices_list = []
            
            with self.devices_lock:
                for mac, device in self.devices.items():
                    if device['online']:
                        avg_rssi = 0
                        if device['rssi_history']:
                            avg_rssi = sum(device['rssi_history']) / len(device['rssi_history'])
                        
                        devices_list.append({
                            'mac': mac,
                            'name': device['name'],
                            'rssi': round(avg_rssi, 1),
                            'samples': len(device['rssi_history']),
                            'last_seen': int(time.time() - device['last_seen'])
                        })
            
            return {
                "success": True,
                "count": len(devices_list),
                "devices": devices_list
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _cmd_clear(self, params):
        """清理离线设备"""
        try:
            removed = 0
            
            with self.devices_lock:
                offline_macs = [
                    mac for mac, dev in self.devices.items()
                    if not dev['online']
                ]
                for mac in offline_macs:
                    del self.devices[mac]
                    removed += 1
            
            gc.collect()
            
            return {
                "success": True,
                "removed": removed,
                "memory_free": gc.mem_free()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def handle_command(self, command, params):
        """命令路由"""
        handlers = {
            "blue_status": self._cmd_status,
            "blue_devices": self._cmd_devices,
            "blue_clear": self._cmd_clear
        }
        
        handler = handlers.get(command)
        if handler:
            return await handler(params)
        
        return None
    
    async def run(self):
        """插件主循环"""
        while self.running:
            await asyncio.sleep(30)
    
    async def cleanup(self):
        """清理资源"""
        self.logger.info("开始清理")
        self.running = False
        
        for task in [self._scan_task, self._report_task, self._gc_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except:
                    pass
        
        if self.scanning and self.ble:
            try:
                self.ble.gap_scan(None)
            except:
                pass
        
        if self.ble:
            try:
                self.ble.active(False)
                self.logger.info("蓝牙已关闭")
            except:
                pass
        
        if self.devices_lock:
            with self.devices_lock:
                self.devices.clear()
        
        gc.collect()
        await super().cleanup()
        
        self.logger.info("清理完成")