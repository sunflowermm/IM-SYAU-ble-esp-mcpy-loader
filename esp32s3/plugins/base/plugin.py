import gc
import time
import uasyncio as asyncio

class Logger:
    """日志系统"""
    LEVELS = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
    
    def __init__(self, name, level='INFO'):
        self.name = name
        self.level = self.LEVELS.get(level.upper(), 1)
    
    def _log(self, level, msg, data=None):
        if self.LEVELS.get(level, 0) >= self.level:
            print("[%s][%s] %s" % (self.name, level, msg))
            if data:
                print("  └─ %s" % str(data))
    
    def debug(self, msg, data=None):
        self._log('DEBUG', msg, data)
    
    def info(self, msg, data=None):
        self._log('INFO', msg, data)
    
    def warning(self, msg, data=None):
        self._log('WARNING', msg, data)
    
    def error(self, msg, data=None):
        self._log('ERROR', msg, data)
    
    def critical(self, msg, data=None):
        self._log('CRITICAL', msg, data)

class Plugin:
    """插件基类"""
    
    def __init__(self, loader, name, enabled=True):
        self.loader = loader
        self.name = name
        self.enabled = enabled
        self.capabilities = []
        self.logger = Logger(name)
        self.running = True
        
        self.error_count = 0
        self.max_errors = 5
        
        self.run_in_thread = False
        
        self.stats = {
            'init_time': 0,
            'run_count': 0,
            'command_count': 0,
            'error_count': 0
        }
    
    async def init(self):
        """初始化插件"""
        self.logger.info("初始化")
        start = time.ticks_ms()
        
        try:
            result = await self._do_init()
            
            self.stats['init_time'] = time.ticks_diff(time.ticks_ms(), start)
            self.logger.info("初始化完成 (耗时: %dms)" % self.stats['init_time'])
            
            return result
        except Exception as e:
            self.logger.error("初始化失败: %s" % e)
            self._handle_error(e)
            return False
    
    async def _do_init(self):
        """实际初始化逻辑（子类实现）"""
        return True
    
    async def run(self):
        """插件主循环（子类可选实现）"""
        pass
    
    def thread_run(self):
        """线程运行方法（子类可选实现）"""
        pass
    
    async def safe_run(self):
        """安全运行"""
        if not self.enabled:
            return
        
        try:
            self.stats['run_count'] += 1
            await self.run()
            
            if self.stats['run_count'] % 10 == 0:
                gc.collect()
                
        except Exception as e:
            self.logger.error("运行错误: %s" % e)
            self._handle_error(e)
            
            if self.error_count >= self.max_errors:
                self.enabled = False
                self.logger.critical("插件禁用")
    
    async def handle_command(self, command, params):
        """处理命令（子类可选实现）"""
        return None
    
    async def safe_handle_command(self, command, params):
        """安全命令处理"""
        if not self.enabled:
            return {"success": False, "error": "插件已禁用"}
        
        try:
            self.stats['command_count'] += 1
            self.logger.info("命令: %s" % command)
            
            result = await self.handle_command(command, params)
            
            if result is not None:
                return result
            
            return None
            
        except Exception as e:
            self.logger.error("命令失败: %s" % e)
            self._handle_error(e)
            return {"success": False, "error": str(e)}
        finally:
            gc.collect()
    
    def _handle_error(self, error):
        """错误处理"""
        self.error_count += 1
        self.stats['error_count'] += 1
        
        if hasattr(self.loader, 'config') and self.loader.config.get('debug_mode'):
            import sys
            sys.print_exception(error)
    
    async def send_log(self, level, message, data=None):
        """发送日志 - 修复返回值"""
        if self.loader:
            try:
                return await self.loader.send_log(level, "[%s] %s" % (self.name, message), data)
            except Exception as e:
                self.logger.error("发送日志失败: %s" % e)
                return False
        return False
    
    async def send_data(self, data_type, data):
        """发送数据 - 修复返回值"""
        if self.loader:
            try:
                return await self.loader.send_data(data_type, data)
            except Exception as e:
                self.logger.error("发送数据失败: %s" % e)
                return False
        return False
    
    async def send_event(self, event_type, event_data):
        """发送事件"""
        return await self.send_data("event", {
            "plugin": self.name,
            "event_type": event_type,
            "data": event_data,
            "timestamp": time.time()
        })
    
    def get_stats(self):
        """获取统计"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "error_count": self.error_count,
            "stats": self.stats
        }
    
    async def cleanup(self):
        """清理资源"""
        self.running = False
        self.logger.info("清理")
        self.stats.clear()
        gc.collect()