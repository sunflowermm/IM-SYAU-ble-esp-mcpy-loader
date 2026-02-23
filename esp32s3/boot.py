"""
ESP32 设备启动文件 - 商用版
- 智能配网系统
- 健康状态监控
- 优雅的错误处理
"""
import gc
import sys
import time

# 内存优化
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

# 打印启动横幅
def print_banner():
    print("\n" + "=" * 60)
    print("XRK 智能设备系统".center(60))
    print("=" * 60)
    print("固件版本: v3.1.3".center(60))
    print("=" * 60 + "\n")

print_banner()

try:
    # 检测Boot按钮（GPIO 0）
    from machine import Pin
    boot_button = Pin(0, Pin.IN, Pin.PULL_UP)
    force_config = boot_button.value() == 0
    
    if force_config:
        print("⚙️  [配网] Boot按钮触发，进入配网模式\n")
    else:
        print("💡 [提示] 长按Boot按钮可强制配网\n")
        
except Exception as e:
    print("⚠️  [警告] 按钮检测失败: %s\n" % e)
    force_config = False

try:
    # 导入loader模块
    import loader
    
    # 判断是否需要配网
    need_config = force_config
    
    if not need_config:
        # 检查配置文件
        try:
            import os
            os.stat("/config.json")
            
            # 验证配置有效性
            config = loader.ConfigManager.load()
            if not loader.ConfigManager.validate(config):
                print("❌ [配置] 配置无效，启动配网模式\n")
                need_config = True
            else:
                print("✅ [配置] 配置有效\n")
                
        except OSError:
            print("📝 [配置] 首次使用，启动配网模式\n")
            need_config = True
    
    if need_config:
        # ======== 配网模式 ========
        print("=" * 60)
        print("配网模式".center(60))
        print("=" * 60)
        print("请使用手机或电脑连接WiFi热点进行配置\n".center(60))
        
        server = loader.ConfigServer()
        server.run()
        
    else:
        # ======== 正常运行模式 ========
        print("=" * 60)
        print("正常模式".center(60))
        print("=" * 60 + "\n")
        
        loader.main()
    
except KeyboardInterrupt:
    print("\n\n⏹️  [系统] 用户中断")
    
except ImportError as e:
    print("\n❌ [错误] 缺少必要文件")
    print("   详情: %s" % e)
    print("   请确保 loader.py 已正确上传\n")
    
except Exception as e:
    print("\n❌ [错误] 启动失败")
    print("   详情: %s\n" % e)
    
    if hasattr(sys, 'print_exception'):
        sys.print_exception(e)
    
    import machine
    print("\n🔄 10秒后自动重启...")
    for i in range(10, 0, -1):
        print("   %d..." % i)
        time.sleep(1)
    machine.reset()
    
finally:
    gc.collect()