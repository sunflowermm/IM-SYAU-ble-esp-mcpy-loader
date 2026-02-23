# ==================== XRK 设备加载器 v3.2.0 - 完整版（含插件管理） ====================
import network
import ujson as json
import uasyncio as asyncio
import machine
import time
import os
import sys
import gc
import socket
import ubinascii
import urandom
import _thread
from machine import WDT, Pin

_device_loader = None

# ==================== 配置管理器 ====================
class ConfigManager:
    """配置管理器"""
    CONFIG_FILE = "/config.json"

    DEFAULT_CONFIG = {
        "device_id": "",
        "device_type": "ESP32-S3",
        "device_name": "ESP32智能设备",
        "firmware_version": "3.2.0",

        # WiFi配置
        "wifi_ssid": "",
        "wifi_password": "",
        "wifi_timeout": 30,
        "wifi_check_interval": 60,
        "wifi_max_retry": 10,
        "wifi_restart_threshold": 15,

        # 服务器配置
        "server_mode": "cloud",
        "server_host_local": "192.168.1.100",
        "server_host_cloud": "115.190.181.211",
        "server_port": 11451,
        "api_key": "",

        # 看门狗配置
        "watchdog_enabled": True,
        "watchdog_timeout": 30000,
        "watchdog_feed_interval": 5,

        # 心跳配置
        "heartbeat_interval": 30,
        "heartbeat_timeout": 90,

        # GC配置
        "gc_interval": 30,

        # 插件配置
        "plugin_dir": "/plugins",
        "plugin_auto_load": True,

        # WebSocket配置
        "ws_reconnect_max_attempts": 999,
        "ws_reconnect_base_delay": 2,
        "ws_reconnect_max_delay": 60,
        "ws_send_queue_size": 128,
        "ws_connection_timeout": 10,
        "ws_stable_time": 60,
        "ws_max_continuous_fails": 20,

        # 缓冲配置
        "event_buffer_size": 50,

        # 日志配置
        "log_level": "INFO",
        "log_to_server": True,
        "debug_mode": False
    }

    @classmethod
    def load(cls):
        try:
            with open(cls.CONFIG_FILE, 'r') as f:
                config = json.load(f)
            for key, value in cls.DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
        except OSError:
            return cls.DEFAULT_CONFIG.copy()
        except Exception as e:
            print("[配置] 加载失败: %s" % e)
            return cls.DEFAULT_CONFIG.copy()

    @classmethod
    def save(cls, config):
        try:
            with open(cls.CONFIG_FILE, 'w') as f:
                json.dump(config, f)
            return True
        except Exception as e:
            print("[配置] 保存失败: %s" % e)
            return False

    @classmethod
    def exists(cls):
        try:
            os.stat(cls.CONFIG_FILE)
            return True
        except OSError:
            return False

    @classmethod
    def validate(cls, config):
        """验证配置完整性"""
        required_fields = ["device_id", "wifi_ssid"]
        for field in required_fields:
            value = config.get(field, "")
            if not value or (isinstance(value, str) and len(value.strip()) == 0):
                return False
        
        device_id = config.get("device_id", "")
        if len(device_id) < 3:
            return False
            
        return True

    @classmethod
    def generate_ap_suffix(cls):
        mac = ubinascii.hexlify(machine.unique_id()).decode()
        return mac[-4:].upper()

# ==================== 配网服务器 ====================
class ConfigServer:
    """配网服务器 - 完整版，含服务器地址配置"""
    
    def __init__(self):
        self.ap = network.WLAN(network.AP_IF)
        self.server_socket = None
        self.running = False
        self.config = {}
        self.request_count = 0
        
    def start_ap(self):
        """启动AP热点"""
        try:
            suffix = ConfigManager.generate_ap_suffix()
            ap_name = "XRK-%s" % suffix
            
            print("📡 [AP] 正在启动热点...")
            self.ap.active(True)
            time.sleep(1)
            
            self.ap.config(essid=ap_name, authmode=network.AUTH_OPEN)
            self.ap.config(max_clients=4)
            
            time.sleep(2)
            
            if not self.ap.active():
                print("❌ [AP] 启动失败")
                return False
            
            print("\n" + "=" * 60)
            print("✅ WiFi热点已就绪".center(60))
            print("=" * 60)
            print("  📶 热点名称: %s" % ap_name)
            print("  🔓 热点密码: 无（开放网络）")
            print("  🌐 配置地址: http://192.168.4.1")
            print("=" * 60 + "\n")
            
            return True
            
        except Exception as e:
            print("❌ [AP] 启动异常: %s" % e)
            return False
        
    def stop_ap(self):
        """关闭AP"""
        if self.ap and self.ap.active():
            self.ap.active(False)
            print("📡 [AP] 已关闭")
    
    def get_config_page(self):
        """获取配置页面HTML - 完整版，含服务器地址"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>XRK设备配置</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 32px;
            max-width: 520px;
            width: 100%;
            animation: slideUp 0.5s ease-out;
            max-height: 90vh;
            overflow-y: auto;
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .header {
            text-align: center;
            margin-bottom: 28px;
        }
        .logo {
            width: 64px;
            height: 64px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 16px;
            margin: 0 auto 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
            color: white;
        }
        h1 {
            color: #333;
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .subtitle {
            color: #666;
            font-size: 14px;
        }
        .section {
            margin-bottom: 24px;
        }
        .section-title {
            font-size: 16px;
            font-weight: 600;
            color: #333;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #f0f0f0;
        }
        .form-group {
            margin-bottom: 16px;
        }
        label {
            display: block;
            margin-bottom: 6px;
            color: #333;
            font-weight: 500;
            font-size: 13px;
        }
        .required { color: #ff4757; margin-left: 2px; }
        input, select {
            width: 100%;
            padding: 11px 14px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.2s;
            background: #fafafa;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
            background: white;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        .server-mode-fields {
            margin-top: 12px;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border: 1px dashed #d0d0d0;
        }
        .server-mode-fields .form-group {
            margin-bottom: 12px;
        }
        .server-mode-fields .form-group:last-child {
            margin-bottom: 0;
        }
        button {
            width: 100%;
            padding: 13px;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 6px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        .btn-primary:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 16px rgba(102,126,234,0.3);
        }
        .btn-primary:active:not(:disabled) {
            transform: translateY(0);
        }
        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: #f0f0f0;
            color: #333;
            margin-bottom: 12px;
        }
        .btn-secondary:hover {
            background: #e0e0e0;
        }
        #wifi-list {
            max-height: 200px;
            overflow-y: auto;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            padding: 8px;
            margin-bottom: 12px;
            display: none;
            background: #fafafa;
        }
        .wifi-item {
            padding: 11px;
            margin: 4px 0;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: white;
        }
        .wifi-item:hover {
            background: #f5f5f5;
            transform: translateX(4px);
        }
        .wifi-item.selected {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        .wifi-name {
            font-weight: 500;
            display: flex;
            align-items: center;
            font-size: 14px;
        }
        .wifi-icon {
            margin-right: 8px;
        }
        .signal {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 4px;
            background: #e0e0e0;
            font-weight: 600;
        }
        .wifi-item.selected .signal {
            background: rgba(255,255,255,0.3);
        }
        #status {
            margin-top: 16px;
            padding: 12px 14px;
            border-radius: 8px;
            text-align: center;
            font-size: 13px;
            font-weight: 500;
            display: none;
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        .success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .info {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
        }
        .spinner {
            display: inline-block;
            width: 13px;
            height: 13px;
            border: 2px solid #ffffff;
            border-radius: 50%;
            border-top-color: transparent;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .empty-state {
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 13px;
        }
        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #f0f0f0;
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb {
            background: #667eea;
            border-radius: 3px;
        }
        .help-text {
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🌐</div>
            <h1>XRK 设备配置</h1>
            <p class="subtitle">请配置您的设备连接信息</p>
        </div>
        
        <form id="configForm">
            <div class="section">
                <div class="section-title">📱 设备信息</div>
                
                <div class="form-group">
                    <label>设备ID<span class="required">*</span></label>
                    <input type="text" name="device_id" required placeholder="输入唯一设备标识（至少3个字符）" autocomplete="off">
                    <div class="help-text">建议使用有意义的名称，如：office-light-01</div>
                </div>
                
                <div class="form-group">
                    <label>设备名称</label>
                    <input type="text" name="device_name" placeholder="例如：办公室灯光控制器" autocomplete="off">
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📶 WiFi配置</div>
                
                <button type="button" class="btn-secondary" onclick="scanWiFi()">
                    🔍 扫描WiFi网络
                </button>
                
                <div id="wifi-list"></div>
                
                <div class="form-group">
                    <label>WiFi名称 (SSID)<span class="required">*</span></label>
                    <input type="text" id="wifi_ssid" name="wifi_ssid" required placeholder="输入WiFi名称" autocomplete="off">
                </div>
                
                <div class="form-group">
                    <label>WiFi密码</label>
                    <input type="password" name="wifi_password" placeholder="留空表示开放网络" autocomplete="new-password">
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">🌐 服务器配置</div>
                
                <div class="form-group">
                    <label>服务器模式</label>
                    <select name="server_mode" id="server_mode" onchange="toggleServerFields()">
                        <option value="cloud">云端服务器</option>
                        <option value="local">本地服务器</option>
                    </select>
                </div>
                
                <div class="server-mode-fields" id="cloud-fields">
                    <div class="form-group">
                        <label>云端服务器地址</label>
                        <input type="text" name="server_host_cloud" value="115.190.181.211" placeholder="云端服务器IP或域名">
                    </div>
                </div>
                
                <div class="server-mode-fields" id="local-fields" style="display:none;">
                    <div class="form-group">
                        <label>本地服务器地址</label>
                        <input type="text" name="server_host_local" value="192.168.1.100" placeholder="本地服务器IP">
                    </div>
                </div>
                
                <div class="form-group">
                    <label>服务器端口</label>
                    <input type="number" name="server_port" value="11451" placeholder="默认：11451">
                </div>
                
                <div class="form-group">
                    <label>API密钥</label>
                    <input type="text" name="api_key" placeholder="可选，用于身份验证" autocomplete="off">
                </div>
            </div>
            
            <button type="submit" class="btn-primary" id="submitBtn">
                💾 保存配置并重启
            </button>
        </form>
        
        <div id="status"></div>
    </div>
    
    <script>
        let selectedSSID = '';
        let isScanning = false;
        let isSaving = false;
        
        function showStatus(msg, type) {
            const status = document.getElementById('status');
            status.innerHTML = msg;
            status.className = type;
            status.style.display = 'block';
        }
        
        function toggleServerFields() {
            const mode = document.getElementById('server_mode').value;
            const cloudFields = document.getElementById('cloud-fields');
            const localFields = document.getElementById('local-fields');
            
            if (mode === 'cloud') {
                cloudFields.style.display = 'block';
                localFields.style.display = 'none';
            } else {
                cloudFields.style.display = 'none';
                localFields.style.display = 'block';
            }
        }
        
        function scanWiFi() {
            if (isScanning) return;
            
            isScanning = true;
            const btn = event.target;
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="spinner"></span>扫描中...';
            btn.disabled = true;
            
            showStatus('正在扫描WiFi网络，请稍候...', 'info');
            
            fetch('/scan')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('wifi-list');
                    
                    if (data.networks && data.networks.length > 0) {
                        list.innerHTML = data.networks.map(n => {
                            const strength = n.rssi > -50 ? '信号强' : (n.rssi > -70 ? '信号中' : '信号弱');
                            return `<div class="wifi-item" onclick="selectWiFi('${n.ssid}')">
                                <span class="wifi-name">
                                    <span class="wifi-icon">📶</span>
                                    ${n.ssid}
                                </span>
                                <span class="signal">${strength}</span>
                            </div>`;
                        }).join('');
                        list.style.display = 'block';
                        showStatus('✓ 找到 ' + data.networks.length + ' 个网络，点击选择', 'success');
                    } else {
                        list.innerHTML = '<div class="empty-state">未找到WiFi网络</div>';
                        list.style.display = 'block';
                        showStatus('未找到WiFi网络，请重试', 'error');
                    }
                })
                .catch(e => {
                    showStatus('✗ 扫描失败：' + e.message, 'error');
                })
                .finally(() => {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                    isScanning = false;
                });
        }
        
        function selectWiFi(ssid) {
            selectedSSID = ssid;
            document.getElementById('wifi_ssid').value = ssid;
            document.querySelectorAll('.wifi-item').forEach(item => {
                const itemText = item.querySelector('.wifi-name').textContent.trim();
                item.classList.toggle('selected', itemText.includes(ssid));
            });
            showStatus('✓ 已选择：' + ssid, 'success');
        }
        
        document.getElementById('configForm').onsubmit = function(e) {
            e.preventDefault();
            
            if (isSaving) return;
            
            const formData = new FormData(e.target);
            const config = {};
            formData.forEach((value, key) => {
                config[key] = value.trim();
            });
            
            if (!config.device_id || config.device_id.length < 3) {
                showStatus('✗ 设备ID至少需要3个字符', 'error');
                return;
            }
            
            if (!config.wifi_ssid) {
                showStatus('✗ 请输入WiFi名称', 'error');
                return;
            }
            
            isSaving = true;
            const btn = document.getElementById('submitBtn');
            btn.innerHTML = '<span class="spinner"></span>保存中...';
            btn.disabled = true;
            
            showStatus('正在保存配置，请稍候...', 'info');
            
            fetch('/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(config)
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showStatus('✓ 配置保存成功！设备将在3秒后重启...', 'success');
                    setTimeout(() => {
                        showStatus('正在重启设备...', 'info');
                    }, 3000);
                } else {
                    throw new Error(data.error || '保存失败');
                }
            })
            .catch(e => {
                showStatus('✗ 保存失败：' + e.message, 'error');
                btn.innerHTML = '💾 保存配置并重启';
                btn.disabled = false;
                isSaving = false;
            });
        };
        
        document.querySelectorAll('input').forEach(input => {
            input.setAttribute('autocomplete', 'off');
        });
        
        toggleServerFields();
    </script>
</body>
</html>"""
    
    def scan_wifi(self):
        """扫描WiFi网络"""
        try:
            sta = network.WLAN(network.STA_IF)
            if not sta.active():
                sta.active(True)
                time.sleep(1)
                
            networks = sta.scan()
            
            result = []
            seen = set()
            
            for net in networks:
                try:
                    ssid = net[0].decode('utf-8')
                    if ssid and ssid not in seen and len(ssid.strip()) > 0:
                        seen.add(ssid)
                        result.append({
                            'ssid': ssid,
                            'rssi': net[3],
                            'authmode': net[4]
                        })
                except:
                    continue
            
            result.sort(key=lambda x: x['rssi'], reverse=True)
            return result[:20]
            
        except Exception as e:
            print("⚠️  [扫描] WiFi扫描失败: %s" % e)
            return []
    
    def handle_request(self, client):
        """处理HTTP请求"""
        try:
            request = client.recv(2048).decode('utf-8', 'ignore')
            
            if not request:
                return
            
            lines = request.split('\r\n')
            if not lines or len(lines[0].split()) < 2:
                return
                
            method, path = lines[0].split()[:2]
            
            if path not in ['/favicon.ico']:
                self.request_count += 1
                print("📨 [请求#%d] %s %s" % (self.request_count, method, path))
            
            if path == '/' or path.startswith('/?'):
                response = self.get_config_page()
                headers = (
                    'HTTP/1.1 200 OK\r\n'
                    'Content-Type: text/html; charset=utf-8\r\n'
                    'Connection: close\r\n'
                    'Cache-Control: no-cache\r\n\r\n'
                )
                client.send(headers.encode())
                client.send(response.encode('utf-8'))
                
            elif path == '/scan':
                networks = self.scan_wifi()
                print("   └─ 找到 %d 个网络" % len(networks))
                
                response = json.dumps({'networks': networks})
                headers = (
                    'HTTP/1.1 200 OK\r\n'
                    'Content-Type: application/json\r\n'
                    'Connection: close\r\n\r\n'
                )
                client.send(headers.encode())
                client.send(response.encode())
                
            elif path == '/save' and method == 'POST':
                body_start = request.find('\r\n\r\n') + 4
                body = request[body_start:]
                
                try:
                    config_data = json.loads(body)
                    
                    if not config_data.get('device_id') or len(config_data.get('device_id', '')) < 3:
                        raise ValueError("设备ID无效")
                    
                    if not config_data.get('wifi_ssid'):
                        raise ValueError("WiFi名称不能为空")
                    
                    config = ConfigManager.load()
                    
                    for key in ['device_id', 'device_name', 'wifi_ssid', 
                               'wifi_password', 'server_mode', 'server_host_cloud',
                               'server_host_local', 'server_port', 'api_key']:
                        if key in config_data:
                            val = config_data[key]
                            config[key] = val.strip() if isinstance(val, str) else val
                    
                    print("   └─ 设备ID: %s" % config.get('device_id'))
                    print("   └─ WiFi: %s" % config.get('wifi_ssid'))
                    print("   └─ 服务器: %s:%s" % (
                        config.get('server_host_cloud' if config.get('server_mode') == 'cloud' else 'server_host_local'),
                        config.get('server_port')
                    ))
                    
                    if ConfigManager.save(config):
                        print("✅ [配置] 保存成功")
                        
                        response = json.dumps({'success': True, 'message': '配置保存成功'})
                        headers = (
                            'HTTP/1.1 200 OK\r\n'
                            'Content-Type: application/json\r\n'
                            'Connection: close\r\n\r\n'
                        )
                        client.send(headers.encode())
                        client.send(response.encode())
                        
                        time.sleep(0.5)
                        self.running = False
                    else:
                        raise Exception("配置保存失败")
                        
                except Exception as e:
                    print("❌ [保存] 失败: %s" % e)
                    
                    response = json.dumps({'success': False, 'error': str(e)})
                    headers = (
                        'HTTP/1.1 400 Bad Request\r\n'
                        'Content-Type: application/json\r\n'
                        'Connection: close\r\n\r\n'
                    )
                    client.send(headers.encode())
                    client.send(response.encode())
                    
            elif path == '/favicon.ico':
                client.send(b'HTTP/1.1 404 Not Found\r\n\r\n')
            else:
                client.send(b'HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n')
            
        except Exception as e:
            print("⚠️  [请求] 处理失败: %s" % e)
        finally:
            try:
                client.close()
            except:
                pass
    
    def run(self):
        """运行配网服务器"""
        try:
            if not self.start_ap():
                print("❌ [配网] AP启动失败")
                return
            
            addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
            self.server_socket = socket.socket()
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(addr)
            self.server_socket.listen(3)
            
            print("🌐 [HTTP] 服务器就绪")
            print("⏳ [配网] 等待用户配置...\n")
            
            self.running = True
            timeout_count = 0
            
            while self.running:
                try:
                    self.server_socket.settimeout(2.0)
                    client, addr = self.server_socket.accept()
                    timeout_count = 0
                    self.handle_request(client)
                    
                except OSError as e:
                    if e.args[0] in (110, 116, 11):
                        timeout_count += 1
                        if timeout_count % 30 == 0:
                            print("💤 [配网] 等待连接中... (已等待 %d 秒)" % (timeout_count * 2))
                        continue
                    else:
                        print("⚠️  [Socket] 错误: %s" % e)
                        time.sleep(0.5)
                        
                except Exception as e:
                    print("⚠️  [配网] 异常: %s" % e)
                    time.sleep(0.5)
                    
        except Exception as e:
            print("❌ [配网] 服务器错误: %s" % e)
            if hasattr(sys, 'print_exception'):
                sys.print_exception(e)
            
        finally:
            print("\n🔄 [配网] 正在关闭...")
            
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
                    
            self.stop_ap()
            
            print("✅ [配网] 配置完成")
            print("🔄 [系统] 3秒后重启设备...\n")
            
            for i in range(3, 0, -1):
                print("   %d..." % i)
                time.sleep(1)
            
            machine.reset()

# ==================== 日志系统 ====================
class Logger:
    LEVELS = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}

    def __init__(self, name, level='INFO'):
        self.name = name
        self.level = self.LEVELS.get(level.upper(), 1)

    def _log(self, level, msg, data=None):
        if self.LEVELS.get(level, 0) >= self.level:
            timestamp = time.ticks_ms() // 1000
            symbol = {'DEBUG': '🔍', 'INFO': 'ℹ️', 'WARNING': '⚠️', 'ERROR': '❌', 'CRITICAL': '🚨'}.get(level, '•')
            print("%s [%s][%s] %s" % (symbol, self.name, level[0], msg))
            if data:
                print("   └─ %s" % str(data))

    def debug(self, msg, data=None): self._log('DEBUG', msg, data)
    def info(self, msg, data=None): self._log('INFO', msg, data)
    def warning(self, msg, data=None): self._log('WARNING', msg, data)
    def error(self, msg, data=None): self._log('ERROR', msg, data)
    def critical(self, msg, data=None): self._log('CRITICAL', msg, data)

# ==================== Unicode 工具 ====================
def encode_unicode(text):
    if not isinstance(text, str):
        return text
    out = []
    for ch in text:
        c = ord(ch)
        out.append('\\u%04x' % c if c > 127 else ch)
    return ''.join(out)

def encode_data(data):
    if isinstance(data, str):
        return encode_unicode(data)
    if isinstance(data, list):
        return [encode_data(x) for x in data]
    if isinstance(data, dict):
        return {k: encode_data(v) for k, v in data.items()}
    return data

def decode_unicode(text):
    if not isinstance(text, str):
        return text
    res, i, n = [], 0, len(text)
    while i < n:
        if i + 5 < n and text[i:i+2] == '\\u':
            try:
                code = int(text[i+2:i+6], 16)
                res.append(chr(code))
                i += 6
            except:
                res.append(text[i])
                i += 1
        else:
            res.append(text[i])
            i += 1
    return ''.join(res)

def decode_data(data):
    if isinstance(data, str):
        return decode_unicode(data)
    if isinstance(data, list):
        return [decode_data(x) for x in data]
    if isinstance(data, dict):
        return {k: decode_data(v) for k, v in data.items()}
    return data

# ==================== WebSocket 客户端 ====================
class SimpleWebSocket:
    """轻量级 WebSocket 客户端"""
    OPCODES = {'text': 0x1, 'binary': 0x2, 'close': 0x8, 'ping': 0x9, 'pong': 0xA}
    WRITE_CHUNK = 4096

    def __init__(self, url):
        self.url = url
        self.sock = None
        self.connected = False
        self.logger = Logger('WebSocket')
        self.last_activity = 0

    def connect(self, api_key=None):
        """建立连接"""
        try:
            is_wss = self.url.startswith('wss://')
            url = self.url[6:] if is_wss else self.url[5:]

            if '/' in url:
                host_port, path = url.split('/', 1)
                path = '/' + path
            else:
                host_port, path = url, '/'

            if ':' in host_port:
                host, port = host_port.split(':', 1)
                port = int(port)
            else:
                host, port = host_port, (443 if is_wss else 80)

            self.logger.info("连接 %s:%d%s" % (host, port, path))

            addr = socket.getaddrinfo(host, port)[0][-1]
            s = socket.socket()
            s.settimeout(10)
            s.connect(addr)

            try:
                import usocket
                if hasattr(usocket, 'IPPROTO_TCP') and hasattr(usocket, 'TCP_NODELAY'):
                    s.setsockopt(usocket.IPPROTO_TCP, usocket.TCP_NODELAY, 1)
            except:
                pass

            if is_wss:
                import ussl
                s = ussl.wrap_socket(s)

            self.sock = s
            key = ubinascii.b2a_base64(bytes(urandom.getrandbits(8) for _ in range(16)))[:-1].decode()

            headers = [
                "GET %s HTTP/1.1" % path,
                "Host: %s:%d" % (host, port),
                "Upgrade: websocket",
                "Connection: Upgrade",
                "Sec-WebSocket-Key: %s" % key,
                "Sec-WebSocket-Version: 13"
            ]

            if api_key:
                headers.append("X-API-Key: %s" % api_key)

            headers.extend(["", ""])
            self.sock.send("\r\n".join(headers).encode())

            resp = self._read_http_response()

            if resp and "101" in resp.split('\r\n')[0]:
                self.connected = True
                self.last_activity = time.ticks_ms()
                self.logger.info("握手成功")
                return True

            self.logger.error("握手失败")
            self.close()
            return False

        except Exception as e:
            self.logger.error("连接失败: %s" % e)
            self.close()
            return False

    def _read_http_response(self):
        try:
            r = b""
            self.sock.settimeout(5)
            for _ in range(50):
                try:
                    data = self.sock.recv(1024)
                    if data:
                        r += data
                        if b"\r\n\r\n" in r:
                            return r.decode('utf-8', 'ignore')
                    else:
                        break
                except OSError as e:
                    if len(e.args) > 0 and e.args[0] in (110, 116):
                        time.sleep_ms(100)
                        continue
                    else:
                        raise
            return r.decode('utf-8', 'ignore') if r else None
        except:
            return None

    def send(self, data):
        """发送数据"""
        if not self.connected or not self.sock:
            return False

        try:
            if isinstance(data, str):
                payload = data.encode()
                opcode = self.OPCODES['text']
            else:
                payload = data
                opcode = self.OPCODES['binary']

            ln = len(payload)

            if ln < 126:
                header = bytearray((0x80 | opcode, 0x80 | ln))
            elif ln < 65536:
                header = bytearray((0x80 | opcode, 0xFE, (ln >> 8) & 0xFF, ln & 0xFF))
            else:
                header = bytearray(2 + 8)
                header[0] = 0x80 | opcode
                header[1] = 0xFF
                for i in range(8):
                    header[2 + i] = (ln >> (8 * (7 - i))) & 0xFF

            mask = bytearray(urandom.getrandbits(8) for _ in range(4))
            self.sock.send(header)
            self.sock.send(mask)

            mv = memoryview(payload)
            idx = 0
            step = self.WRITE_CHUNK
            tmp = bytearray(step)

            while idx < ln:
                n = step if ln - idx >= step else (ln - idx)
                tmp[0:n] = mv[idx:idx + n]
                for i in range(n):
                    tmp[i] ^= mask[i & 3]
                self.sock.send(tmp[0:n])
                idx += n

            self.last_activity = time.ticks_ms()
            return True

        except Exception as e:
            self.logger.error("发送失败: %s" % e)
            self.connected = False
            return False

    def recv(self, timeout=0.1):
        """接收数据"""
        if not self.connected or not self.sock:
            return None

        try:
            self.sock.settimeout(timeout)
            header = self.sock.recv(2)

            if not header or len(header) < 2:
                return None

            opcode = header[0] & 0x0F
            masked = (header[1] & 0x80) != 0
            length = header[1] & 0x7F

            if length == 126:
                ext = self.sock.recv(2)
                if len(ext) < 2:
                    return None
                length = int.from_bytes(ext, 'big')
            elif length == 127:
                ext = self.sock.recv(8)
                if len(ext) < 8:
                    return None
                length = int.from_bytes(ext, 'big')

            mask = None
            if masked:
                mask = self.sock.recv(4)
                if len(mask) < 4:
                    return None

            data = b""
            rem = length
            while rem > 0:
                chunk = self.sock.recv(min(rem, 2048))
                if not chunk:
                    break
                data += chunk
                rem -= len(chunk)

            if masked and mask:
                data = bytes([data[i] ^ mask[i & 3] for i in range(len(data))])

            self.last_activity = time.ticks_ms()

            if opcode == self.OPCODES['close']:
                self.logger.warning("服务器关闭连接")
                self.connected = False
                return None
            elif opcode == self.OPCODES['ping']:
                self._send_pong(data)
                return None
            elif opcode == self.OPCODES['text']:
                return data.decode('utf-8')
            elif opcode == self.OPCODES['binary']:
                return data

            return None

        except OSError as e:
            if len(e.args) > 0 and e.args[0] in (110, 116):
                return None
            self.connected = False
        except Exception as e:
            self.logger.error("接收失败: %s" % e)
            self.connected = False

        return None

    def _send_pong(self, data=b""):
        """响应 ping"""
        if not self.connected:
            return
        try:
            ln = len(data)
            if ln < 126:
                header = bytes([0x80 | self.OPCODES['pong'], 0x80 | ln])
            else:
                header = bytes([0x80 | self.OPCODES['pong'], 0xFE]) + ln.to_bytes(2, 'big')
            mask = bytes(urandom.getrandbits(8) for _ in range(4))
            masked = bytes([data[i] ^ mask[i & 3] for i in range(ln)])
            self.sock.send(header + mask + masked)
        except:
            pass

    def is_alive(self):
        """检查连接是否活跃"""
        if not self.connected:
            return False
        idle_time = time.ticks_diff(time.ticks_ms(), self.last_activity) // 1000
        return idle_time < 120

    def close(self):
        """关闭连接"""
        if self.sock:
            try:
                if self.connected:
                    frame = bytes([0x88, 0x82]) + bytes(urandom.getrandbits(8) for _ in range(4)) + bytes([0x03, 0xE8])
                    self.sock.send(frame)
                self.sock.close()
            except:
                pass
            finally:
                self.sock = None
                self.connected = False
                gc.collect()

# ==================== 异步 WebSocket ====================
class AsyncWebSocket:
    """异步 WebSocket 封装"""

    def __init__(self, url, api_key=None, config=None):
        self.url = url
        self.api_key = api_key
        self.config = config or {}
        self.ws = None
        self.connected = False
        
        self.reconnect_count = 0
        self.continuous_fail_count = 0
        self.last_connect_time = 0
        self.last_success_time = 0
        self.reconnect_delay = self.config.get("ws_reconnect_base_delay", 2)
        self.max_reconnect_delay = self.config.get("ws_reconnect_max_delay", 60)
        self.max_continuous_fails = self.config.get("ws_max_continuous_fails", 20)
        self.stable_time = self.config.get("ws_stable_time", 60)
        
        self.logger = Logger('AsyncWS')

        self._send_q = []
        self._q_lock = _thread.allocate_lock()
        self._qmax = self.config.get("ws_send_queue_size", 128)
        self._writer_running = False
        self._writer_should_stop = False
        
        self.last_send_time = 0
        self.last_recv_time = 0
        self.send_fail_count = 0
        self.max_send_fails = 3

    def _q_put(self, item):
        with self._q_lock:
            if len(self._send_q) >= self._qmax:
                self._send_q.pop(0)
            self._send_q.append(item)

    def _q_get(self):
        with self._q_lock:
            if self._send_q:
                return self._send_q.pop(0)
            return None

    def _writer_loop(self):
        """发送线程"""
        while not self._writer_should_stop:
            if not self.connected or not self.ws:
                time.sleep_ms(50)
                continue

            item = self._q_get()
            if item is None:
                time.sleep_ms(5)
                continue

            try:
                if self.ws.send(item):
                    self.last_send_time = time.ticks_ms()
                    self.send_fail_count = 0
                else:
                    self.send_fail_count += 1
                    if self.send_fail_count >= self.max_send_fails:
                        self.logger.warning("连续发送失败，标记连接断开")
                        self.connected = False
                        
            except Exception as e:
                self.send_fail_count += 1
                if self.send_fail_count >= self.max_send_fails:
                    self.connected = False
                time.sleep_ms(100)

    def _ensure_writer(self):
        if not self._writer_running:
            try:
                self._writer_should_stop = False
                _thread.start_new_thread(self._writer_loop, ())
                self._writer_running = True
            except Exception as e:
                self.logger.error("启动发送线程失败: %s" % e)

    async def connect(self):
        """建立连接"""
        try:
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
                gc.collect()
                
            self.ws = SimpleWebSocket(self.url)
            if self.ws.connect(self.api_key):
                self.connected = True
                self.last_connect_time = time.ticks_ms()
                self.last_success_time = time.ticks_ms()
                self.last_recv_time = time.ticks_ms()
                self.last_send_time = time.ticks_ms()
                self.send_fail_count = 0
                self.continuous_fail_count = 0
                
                self._ensure_writer()
                
                return True
                
            return False
            
        except Exception as e:
            self.logger.error("连接异常: %s" % e)
            return False

    def check_connection_health(self):
        """检查连接健康状态"""
        if not self.connected or not self.ws:
            return False
            
        if not self.ws.is_alive():
            self.connected = False
            return False
            
        idle_time = time.ticks_diff(time.ticks_ms(), self.last_recv_time) // 1000
        heartbeat_timeout = self.config.get("heartbeat_timeout", 90)
        
        if idle_time > heartbeat_timeout:
            self.logger.warning("心跳超时 (%ds)" % idle_time)
            self.connected = False
            return False
            
        return True

    async def send_now(self, data):
        """立即发送"""
        if not self.connected or not self.ws:
            return False
        if isinstance(data, dict):
            data = encode_data(data)
            data = json.dumps(data)
        return self.ws.send(data)

    def enqueue(self, data):
        """队列发送"""
        if isinstance(data, dict):
            data = encode_data(data)
            data = json.dumps(data)
        self._q_put(data)

    async def receive(self, timeout=0.1):
        """接收数据"""
        if not self.connected or not self.ws:
            return None
        try:
            data = self.ws.recv(timeout)
            if data:
                self.last_recv_time = time.ticks_ms()
                try:
                    parsed = json.loads(data)
                    return decode_data(parsed)
                except Exception:
                    return data
            return None
        except:
            return None

    async def close(self):
        """关闭连接"""
        self._writer_should_stop = True
        if self.ws:
            self.ws.close()
        self.connected = False
        gc.collect()

    async def auto_reconnect(self):
        """智能自动重连"""
        if self.continuous_fail_count >= self.max_continuous_fails:
            self.logger.critical("WebSocket连续失败 %d 次，重启设备" % self.continuous_fail_count)
            await asyncio.sleep(3)
            machine.reset()
            
        if self.last_success_time > 0:
            stable_duration = time.ticks_diff(time.ticks_ms(), self.last_success_time) // 1000
            if stable_duration > self.stable_time:
                if self.reconnect_count > 0:
                    self.reconnect_count = 0
                    self.reconnect_delay = self.config.get("ws_reconnect_base_delay", 2)
        
        self.reconnect_count += 1
        self.continuous_fail_count += 1
        
        self.logger.info("重连 (第%d次)" % self.reconnect_count)
        
        if await self.connect():
            self.logger.info("重连成功")
            return True
            
        delay = min(self.reconnect_delay * (1.5 ** min(self.reconnect_count - 1, 5)), 
                   self.max_reconnect_delay)
        
        await asyncio.sleep(delay)
        return False

# ==================== WiFi 管理器 ====================
class WiFiManager:
    """WiFi 连接管理器"""
    
    def __init__(self, config):
        self.config = config
        self.logger = Logger('WiFi')
        self.wlan = network.WLAN(network.STA_IF)
        self.connected = False
        self.retry_count = 0
        self.continuous_fail_count = 0
        self.max_retry = config.get("wifi_max_retry", 10)
        self.restart_threshold = config.get("wifi_restart_threshold", 15)
        
    def connect(self):
        """连接WiFi"""
        self.wlan.active(True)
        
        if self.wlan.isconnected():
            self.connected = True
            self.continuous_fail_count = 0
            return self.wlan.ifconfig()
        
        ssid = self.config.get("wifi_ssid")
        password = self.config.get("wifi_password", "")
        timeout = self.config.get("wifi_timeout", 30)
        
        self.logger.info("连接: %s" % ssid)
        self.wlan.connect(ssid, password)
        
        elapsed = 0
        while elapsed < timeout:
            if self.wlan.isconnected():
                ifconfig = self.wlan.ifconfig()
                self.connected = True
                self.retry_count = 0
                self.continuous_fail_count = 0
                self.logger.info("连接成功 - IP: %s" % ifconfig[0])
                return ifconfig
            time.sleep(1)
            elapsed += 1
        
        self.connected = False
        self.continuous_fail_count += 1
        self.logger.error("连接超时 (连续失败: %d)" % self.continuous_fail_count)
        return None
        
    def is_connected(self):
        """检查WiFi连接状态"""
        try:
            return self.wlan.isconnected()
        except:
            return False
            
    async def auto_reconnect(self):
        """WiFi自动重连"""
        if self.is_connected():
            return True
            
        self.retry_count += 1
        
        if self.continuous_fail_count >= self.restart_threshold:
            self.logger.critical("WiFi连续失败 %d 次，重启设备" % self.continuous_fail_count)
            await asyncio.sleep(3)
            machine.reset()
        
        if self.retry_count > self.max_retry:
            self.logger.error("重连次数过多，等待30秒")
            await asyncio.sleep(30)
            self.retry_count = 0
        
        self.logger.warning("WiFi断开，重连中 (第%d次)" % self.retry_count)
        
        result = self.connect()
        if result:
            self.logger.info("WiFi重连成功")
            return True
        else:
            await asyncio.sleep(5)
            return False

# ==================== 插件管理器 ====================
class PluginManager:
    """插件管理器"""
    
    def __init__(self, loader, config):
        self.loader = loader
        self.config = config
        self.logger = Logger('PluginMgr')
        self.plugins = {}
        self.plugin_tasks = []
        
    async def load_plugins(self):
        """加载插件"""
        if not self.config.get("plugin_auto_load", True):
            self.logger.info("插件自动加载已禁用")
            return
        
        plugin_dir = self.config.get("plugin_dir", "/plugins")
        enabled_plugins = self.config.get("enabled_plugins", None)
        
        # 如果未显式配置 enabled_plugins，则默认加载插件目录下所有插件
        if not enabled_plugins:
            try:
                files = os.listdir(plugin_dir)
                enabled_plugins = []
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    # 忽略基础插件基类和隐藏文件
                    if name.startswith("_") or name.startswith("base"):
                        continue
                    enabled_plugins.append(name[:-3])
                if not enabled_plugins:
                    self.logger.warning("插件目录 %s 中未找到可加载的插件" % plugin_dir)
                    return
                self.logger.info("未配置启用的插件，默认启用目录下所有插件: %s" % str(enabled_plugins))
            except Exception as e:
                self.logger.error("扫描插件目录失败: %s" % e)
                return
        
        self.logger.info("=" * 50)
        self.logger.info("开始加载插件...")
        self.logger.info("  插件目录: %s" % plugin_dir)
        self.logger.info("  启用插件: %s" % str(enabled_plugins))
        self.logger.info("=" * 50)
        
        # 确保路径在sys.path中
        base_path = plugin_dir + '/base'
        if base_path not in sys.path:
            sys.path.append(base_path)
        if plugin_dir not in sys.path:
            sys.path.append(plugin_dir)
        
        success_count = 0
        fail_count = 0
        
        for plugin_name in enabled_plugins:
            try:
                if await self.load_plugin(plugin_name, plugin_dir):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                self.logger.error("加载插件 %s 失败: %s" % (plugin_name, e))
        
        self.logger.info("=" * 50)
        self.logger.info("插件加载完成:")
        self.logger.info("  成功: %d" % success_count)
        self.logger.info("  失败: %d" % fail_count)
        self.logger.info("  总计: %d" % len(self.plugins))
        self.logger.info("=" * 50)
    
    async def load_plugin(self, plugin_name, plugin_dir):
        """加载单个插件"""
        self.logger.info("加载插件: %s" % plugin_name)
        
        try:
            plugin_path = "%s/%s.py" % (plugin_dir, plugin_name)
            
            try:
                os.stat(plugin_path)
            except OSError:
                raise Exception("插件文件不存在: %s" % plugin_path)
            
            # 首字母大写（兼容MicroPython）
            if len(plugin_name) > 0:
                plugin_class_name = plugin_name[0].upper() + plugin_name[1:].lower()
            else:
                raise Exception("插件名称为空")
            
            self.logger.info("  插件类名: %s" % plugin_class_name)
            
            # 读取插件代码
            with open(plugin_path, 'r') as f:
                code = f.read()
            
            # 准备执行环境
            exec_globals = {
                '__name__': plugin_name,
                'asyncio': asyncio,
                'time': time,
                'gc': gc,
                'sys': sys,
                'os': os,
                'json': json
            }
            
            # 尝试导入插件可能需要的模块
            try:
                import bluetooth
                exec_globals['bluetooth'] = bluetooth
            except:
                pass
            
            try:
                import _thread
                exec_globals['_thread'] = _thread
            except:
                pass
            
            try:
                from micropython import const
                exec_globals['const'] = const
            except:
                pass
            
            # 导入plugin基类
            try:
                base_file = plugin_dir + '/base/plugin.py'
                with open(base_file, 'r') as f:
                    base_code = f.read()
                
                # 先在独立的命名空间执行基类代码
                base_globals = {
                    '__name__': 'plugin',
                    'asyncio': asyncio,
                    'time': time,
                    'gc': gc
                }
                exec(compile(base_code, base_file, 'exec'), base_globals)
                
                # 将Plugin类添加到插件的执行环境
                if 'Plugin' in base_globals:
                    exec_globals['Plugin'] = base_globals['Plugin']
                    self.logger.info("  Plugin基类已导入")
                
                if 'Logger' in base_globals:
                    exec_globals['Logger'] = base_globals['Logger']
                    self.logger.info("  Logger类已导入")
                
                self.logger.info("  基类加载成功")
            except Exception as e:
                self.logger.error("  基类加载失败: %s" % e)
                if hasattr(sys, 'print_exception'):
                    sys.print_exception(e)
                raise Exception("无法加载基类: %s" % e)
            
            # 执行插件代码
            exec(compile(code, plugin_path, 'exec'), exec_globals)
            self.logger.info("  插件代码执行成功")
            
            # 查找插件类
            if plugin_class_name not in exec_globals:
                # 尝试其他可能的类名
                possible_names = [
                    plugin_class_name,
                    plugin_name.upper(),
                    plugin_name.lower(),
                    plugin_name
                ]
                
                found = False
                for name in possible_names:
                    if name in exec_globals:
                        plugin_class_name = name
                        found = True
                        self.logger.info("  找到插件类: %s" % name)
                        break
                
                if not found:
                    self.logger.error("  可用的全局变量: %s" % str(list(exec_globals.keys())))
                    raise Exception("找不到插件类: %s" % plugin_class_name)
            
            PluginClass = exec_globals[plugin_class_name]
            self.logger.info("  创建插件实例...")
            
            plugin_instance = PluginClass(self.loader)
            self.logger.info("  插件实例创建成功")
            
            self.logger.info("  初始化插件...")
            init_success = await plugin_instance.init()
            
            if init_success:
                self.plugins[plugin_name] = plugin_instance
                self.logger.info("✓ 插件 %s 加载成功" % plugin_name)
                
                if hasattr(plugin_instance, 'run'):
                    task = asyncio.create_task(plugin_instance.safe_run())
                    self.plugin_tasks.append(task)
                    self.logger.info("  插件运行任务已启动")
                
                return True
            else:
                self.logger.error("✗ 插件 %s 初始化失败" % plugin_name)
                return False
                
        except Exception as e:
            self.logger.error("✗ 插件 %s 加载异常: %s" % (plugin_name, e))
            if hasattr(sys, 'print_exception'):
                sys.print_exception(e)
            return False
    
    async def handle_command(self, command, params):
        """分发命令到插件"""
        for plugin_name, plugin in self.plugins.items():
            try:
                result = await plugin.safe_handle_command(command, params)
                if result is not None:
                    return result
            except Exception as e:
                self.logger.error("插件 %s 处理命令失败: %s" % (plugin_name, e))
        
        return None
    
    async def cleanup(self):
        """清理插件"""
        self.logger.info("清理插件...")
        
        for task in self.plugin_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        for plugin_name, plugin in self.plugins.items():
            try:
                await plugin.cleanup()
            except Exception as e:
                self.logger.error("清理插件 %s 失败: %s" % (plugin_name, e))
        
        self.plugins.clear()
        self.plugin_tasks.clear()
        gc.collect()

# ==================== 设备加载器 ====================
class DeviceLoader:
    """设备加载器主类"""

    def __init__(self, config):
        self.config = config
        self.device_id = config.get("device_id")
        self.device_type = config.get("device_type")
        self.device_name = config.get("device_name")
        self.logger = Logger('Loader', level=config.get("log_level", "INFO"))

        self.running = True
        self.is_registered = False
        self.start_time = time.ticks_ms()

        self.capabilities = []
        self.metadata = {}
        self.event_buffer = []
        self.command_handlers = {}

        self.wdt = None
        self.ws = None
        self.wifi_manager = None
        self.plugin_manager = None
        self.ip_address = None
        self.tasks = []

        self.stats = {
            'messages_sent': 0,
            'messages_received': 0,
            'commands_executed': 0,
            'errors': 0,
            'reconnects': 0
        }

        global _device_loader
        _device_loader = self

    def setup_network(self, ip, gateway=None):
        """设置网络"""
        self.ip_address = ip
        host = (self.config.get("server_host_local") if self.config.get("server_mode") == "local" 
                else self.config.get("server_host_cloud"))
        port = self.config.get("server_port")
        self.ws_url = "ws://%s:%d/device" % (host, port)
        self.ws = AsyncWebSocket(self.ws_url, self.config.get("api_key"), self.config)

    def init_watchdog(self):
        """初始化看门狗"""
        if self.config.get("watchdog_enabled"):
            try:
                timeout = self.config.get("watchdog_timeout", 30000)
                self.wdt = WDT(timeout=timeout)
                self.logger.info("看门狗启动 (%dms)" % timeout)
            except Exception as e:
                self.logger.error("看门狗启动失败: %s" % e)

    def feed_watchdog(self):
        """喂狗"""
        if self.wdt:
            try:
                self.wdt.feed()
            except:
                pass

    def register_command(self, command, handler):
        """注册命令处理器"""
        self.command_handlers[command] = handler
        self.logger.debug("注册命令: %s" % command)

    async def send_log(self, level, message, data=None):
        """发送日志到服务器"""
        if not self.config.get("log_to_server"):
            return True

        log_data = {
            "device_id": self.device_id,
            "type": "log",
            "level": level,
            "message": message,
            "data": data or {},
            "timestamp": time.time()
        }

        if self.ws and self.ws.connected:
            self.ws.enqueue(log_data)
            return True
        else:
            buffer_size = self.config.get("event_buffer_size", 50)
            self.event_buffer.append(log_data)
            if len(self.event_buffer) > buffer_size:
                self.event_buffer.pop(0)
            return False

    async def send_data(self, data_type, data):
        """发送数据到服务器"""
        event = {
            "device_id": self.device_id,
            "type": "data",
            "data_type": data_type,
            "data": data,
            "timestamp": time.time()
        }

        self.stats['messages_sent'] += 1

        if self.ws and self.ws.connected:
            self.ws.enqueue(event)
            return True
        else:
            buffer_size = self.config.get("event_buffer_size", 50)
            self.event_buffer.append(event)
            if len(self.event_buffer) > buffer_size:
                self.event_buffer.pop(0)
            return False

    async def register_device(self):
        """注册设备"""
        self.logger.info("设备注册中...")

        self.collect_capabilities()

        reg_data = {
            "type": "register",
            "device_id": self.device_id,
            "device_type": self.device_type,
            "device_name": self.device_name,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
            "firmware_version": self.config.get("firmware_version"),
            "ip_address": self.ip_address
        }

        if not self.ws or not self.ws.connected:
            if not await self.ws.connect():
                return False

        if await self.ws.send_now(reg_data):
            timeout_ms = 5000
            start = time.ticks_ms()

            while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
                response = await self.ws.receive(0.1)

                if response and isinstance(response, dict):
                    if response.get("type") == "register_response":
                        if response.get("success"):
                            self.is_registered = True
                            self.logger.info("注册成功")
                            await self.send_log('info', '设备注册成功')
                            return True
                        else:
                            self.logger.error("注册被拒绝")
                            return False

                await asyncio.sleep_ms(100)

        return False

    def collect_capabilities(self):
        """收集设备能力"""
        self.capabilities = ["gpio", "sensor", "websocket"]
        
        if self.plugin_manager:
            for plugin_name, plugin in self.plugin_manager.plugins.items():
                if hasattr(plugin, 'capabilities'):
                    self.capabilities.extend(plugin.capabilities)
        
        self.metadata = {
            "platform": sys.platform,
            "heap_free": gc.mem_free(),
            "plugins": list(self.plugin_manager.plugins.keys()) if self.plugin_manager else []
        }

    async def websocket_task(self):
        """WebSocket主任务"""
        if not self.ws:
            return

        self.logger.info("WebSocket任务启动")
        last_heartbeat = time.ticks_ms()
        last_health_check = time.ticks_ms()
        heartbeat_interval = self.config.get("heartbeat_interval", 30) * 1000
        health_check_interval = 10000

        while self.running:
            try:
                if not self.ws.connected:
                    self.stats['reconnects'] += 1
                    await self.send_log('warning', 'WebSocket断开')
                    
                    if await self.ws.auto_reconnect():
                        await self.send_log('info', 'WebSocket重连成功')
                        if not self.is_registered:
                            await self.register_device()
                    else:
                        await asyncio.sleep(5)
                        continue

                if time.ticks_diff(time.ticks_ms(), last_health_check) > health_check_interval:
                    if not self.ws.check_connection_health():
                        self.ws.connected = False
                        continue
                    last_health_check = time.ticks_ms()

                msg = await self.ws.receive(0.1)

                if msg:
                    self.stats['messages_received'] += 1

                    if isinstance(msg, dict):
                        msg_type = msg.get("type")

                        if msg_type == "command":
                            command = msg.get("command")
                            result = await self.handle_command(command)
                            self.ws.enqueue({
                                "type": "command_result",
                                "command_id": command.get("id"),
                                "result": result
                            })

                        elif msg_type == "heartbeat_request":
                            self.ws.enqueue({
                                "type": "heartbeat",
                                "device_id": self.device_id,
                                "status": self.get_status()
                            })
                            last_heartbeat = time.ticks_ms()

                if time.ticks_diff(time.ticks_ms(), last_heartbeat) > heartbeat_interval:
                    self.ws.enqueue({
                        "type": "heartbeat",
                        "device_id": self.device_id,
                        "timestamp": time.time(),
                        "status": self.get_status()
                    })
                    last_heartbeat = time.ticks_ms()

                await self.flush_events()

            except Exception as e:
                self.logger.error("WebSocket错误: %s" % e)
                self.stats['errors'] += 1

            await asyncio.sleep_ms(100)

    async def network_monitor_task(self):
        """网络监控任务"""
        check_interval = self.config.get("wifi_check_interval", 60)
        
        while self.running:
            try:
                if not self.wifi_manager.is_connected():
                    await self.send_log('warning', 'WiFi断开')
                    
                    if await self.wifi_manager.auto_reconnect():
                        await self.send_log('info', 'WiFi重连成功')
                        if self.ws:
                            self.ws.connected = False
                        
            except Exception as e:
                self.logger.error("网络监控错误: %s" % e)
                
            await asyncio.sleep(check_interval)

    async def handle_command(self, command):
        """处理命令"""
        try:
            cmd_type = command.get("command")
            params = decode_data(command.get("parameters", {}))

            self.stats['commands_executed'] += 1

            if cmd_type in self.command_handlers:
                handler = self.command_handlers[cmd_type]
                return await handler(params)
            
            if self.plugin_manager:
                result = await self.plugin_manager.handle_command(cmd_type, params)
                if result is not None:
                    return result

            if cmd_type == "reboot":
                await self.send_log('info', '设备重启')
                await asyncio.sleep(1)
                machine.reset()

            elif cmd_type == "gc":
                free_before = gc.mem_free()
                gc.collect()
                free_after = gc.mem_free()
                return {
                    "success": True,
                    "free": free_after,
                    "freed": free_after - free_before
                }

            elif cmd_type == "stats":
                return {
                    "success": True,
                    "stats": self.stats,
                    "uptime": time.ticks_diff(time.ticks_ms(), self.start_time) // 1000,
                    "memory": gc.mem_free(),
                    "wifi_connected": self.wifi_manager.is_connected() if self.wifi_manager else False,
                    "ws_connected": self.ws.connected if self.ws else False,
                    "plugins": list(self.plugin_manager.plugins.keys()) if self.plugin_manager else []
                }

            return {"success": False, "error": "未知命令"}

        except Exception as e:
            self.stats['errors'] += 1
            return {"success": False, "error": str(e)}

    async def flush_events(self):
        """刷新事件缓冲"""
        if not self.event_buffer or not self.ws or not self.ws.connected:
            return

        cnt = 0
        while self.event_buffer and cnt < 5:
            ev = self.event_buffer.pop(0)
            self.ws.enqueue(ev)
            cnt += 1

    def get_status(self):
        """获取设备状态"""
        return {
            "heap_free": gc.mem_free(),
            "uptime": time.ticks_diff(time.ticks_ms(), self.start_time) // 1000,
            "stats": self.stats,
            "wifi_connected": self.wifi_manager.is_connected() if self.wifi_manager else False,
            "ws_reconnects": self.ws.reconnect_count if self.ws else 0,
            "wifi_fails": self.wifi_manager.continuous_fail_count if self.wifi_manager else 0,
            "plugins": list(self.plugin_manager.plugins.keys()) if self.plugin_manager else []
        }

    async def watchdog_task(self):
        """看门狗任务"""
        gc_counter = 0
        gc_interval = self.config.get("gc_interval", 30)
        feed_interval = self.config.get("watchdog_feed_interval", 5)

        while self.running:
            self.feed_watchdog()

            gc_counter += 1
            if gc_counter >= gc_interval:
                gc.collect()
                gc_counter = 0

            await asyncio.sleep(feed_interval)

    async def cleanup(self):
        """清理资源"""
        self.logger.info("清理资源")
        self.running = False

        if self.plugin_manager:
            await self.plugin_manager.cleanup()

        for t in self.tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        if self.ws:
            await self.ws.close()

        gc.collect()

    async def main(self):
        """主函数"""
        print("\n" + "=" * 60)
        print("设备加载器 v%s".center(60) % self.config.get("firmware_version"))
        print("=" * 60)
        print("  设备ID: %s" % self.device_id)
        print("  设备名称: %s" % self.device_name)
        print("  IP地址: %s" % self.ip_address)
        print("  可用内存: %d bytes" % gc.mem_free())
        print("=" * 60 + "\n")

        self.init_watchdog()

        self.plugin_manager = PluginManager(self, self.config)
        await self.plugin_manager.load_plugins()

        for retry in range(3):
            if retry > 0:
                delay = 2 ** retry
                await asyncio.sleep(delay)

            if await self.register_device():
                break
        else:
            self.logger.critical("注册失败，重启设备")
            await asyncio.sleep(5)
            machine.reset()

        self.tasks = []

        if self.ws:
            self.tasks.append(asyncio.create_task(self.websocket_task()))

        if self.wifi_manager:
            self.tasks.append(asyncio.create_task(self.network_monitor_task()))

        self.tasks.append(asyncio.create_task(self.watchdog_task()))

        print("=" * 60)
        print("系统运行中".center(60))
        print("=" * 60 + "\n")

        try:
            await asyncio.gather(*self.tasks)
        except KeyboardInterrupt:
            self.logger.info("用户停止")
        except Exception as e:
            self.logger.critical("致命错误: %s" % e)
            await asyncio.sleep(5)
            machine.reset()
        finally:
            await self.cleanup()

# ==================== 主入口 ====================
def main():
    """主入口函数"""
    try:
        config = ConfigManager.load()

        if not ConfigManager.validate(config):
            print("❌ [错误] 配置不完整")
            return

        wifi_manager = WiFiManager(config)
        result = wifi_manager.connect()

        if not result:
            print("❌ [错误] WiFi连接失败")
            return

        ip, netmask, gateway, dns = result

        loader = DeviceLoader(config)
        loader.wifi_manager = wifi_manager
        loader.setup_network(ip, gateway)

        asyncio.run(loader.main())

    except KeyboardInterrupt:
        print("\n⏹️  [系统] 用户中断")
    except Exception as e:
        print("❌ [错误] %s" % e)
        time.sleep(5)
        machine.reset()

if __name__ == "__main__":
    main()