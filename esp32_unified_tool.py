import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import serial.tools.list_ports
import threading
import time
import json
import os
import subprocess
import datetime
import sys

font_size = 12

# 添加自定义样式和主题
def set_modern_style(root):
    # 创建自定义样式
    style = ttk.Style()
    
    # 尝试使用Windows 10主题
    try:
        style.theme_use('vista')  # vista主题在Windows上接近Win10风格
    except:
        try:
            style.theme_use('winnative')
        except:
            pass  # 如果没有可用的主题，使用默认主题
    
    # 自定义按钮样式
    style.configure('TButton', font=('Microsoft YaHei UI', font_size))
    style.configure('Accent.TButton', font=('Microsoft YaHei UI', font_size))
    style.configure('Flash.TButton', background='#007ACC', foreground='white')
    style.configure('MAC.TButton', background='#28A745', foreground='white')
    
    # 自定义标签框样式
    style.configure('TLabelframe', font=('Microsoft YaHei UI', font_size))
    style.configure('TLabelframe.Label', font=('Microsoft YaHei UI', font_size, 'bold'))
    
    # 自定义标签样式
    style.configure('TLabel', font=('Microsoft YaHei UI', font_size))
    
    # 自定义输入框样式
    style.configure('TEntry', font=('Microsoft YaHei UI', font_size))
    
    # 自定义下拉框样式
    style.configure('TCombobox', font=('Microsoft YaHei UI', font_size))
    
    # 自定义复选框样式
    style.configure('TCheckbutton', font=('Microsoft YaHei UI', font_size))
    
    # 设置窗口默认字体
    root.option_add('*Font', ('Microsoft YaHei UI', font_size))
    
    # 设置窗口DPI感知
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

class LogRedirector:
    def __init__(self, callback):
        self.callback = callback

    def write(self, text):
        if text.strip():  # 只处理非空文本
            self.callback(text.strip())

    def flush(self):
        pass

class ESP32UnifiedTool:
    def __init__(self, root):
        self.root = root
        self.config_file = 'unified_config.json'
        self.root.title("ESP32 统一工具 - 刷固件 & 读取MAC地址")
        self.root.geometry("800x1000")
        
        # 检查并安装必要的依赖
        if not self.check_dependencies():
            self.root.withdraw()
            self.root.quit()
            return
            
        # 设置窗口图标
        try:
            self.root.iconbitmap("icon.ico")
        except:
            pass
        
        # 应用现代风格
        set_modern_style(root)
        
        # 初始化基本变量
        self.config = {
            'firmware_paths': [''] * 8, 
            'firmware_addresses': ['0x0'] * 8,
            'firmware_enables': [False] * 8,
            'port_enables': [True] * 8,
            'auto_mode': True,
            'auto_flash': True,
            'auto_read_mac': True
        }
        self.mac_addresses = {}
        self.current_log_file = self.generate_log_filename()
        
        # 创建UI
        self.create_ui()
        
        # 延迟加载配置和启动监控
        self.root.after(100, self.delayed_init)

    def delayed_init(self):
        """延迟初始化，提高启动速度"""
        # 加载配置
        self.load_config()
        
        # 初始化串口列表
        self.refresh_ports()
        
        # 启动串口监控
        self.port_monitor_thread = threading.Thread(target=self.monitor_ports, daemon=True)
        self.port_monitor_thread.start()
        
        # 重定向标准输出到日志框
        sys.stdout = LogRedirector(self.log)
        sys.stderr = LogRedirector(self.log)
        
        # 记录启动信息
        self.log(f"ESP32统一工具已启动，MAC地址记录将保存到: {self.current_log_file}")

    def generate_log_filename(self):
        """生成带时间戳的日志文件名"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"ESP32_MAC_Addresses_{timestamp}.txt"

    def check_dependencies(self):
        """检查必要的依赖"""
        try:
            import serial
            import subprocess
            return True
        except ImportError as e:
            messagebox.showerror("依赖错误", f"缺少必要的依赖: {str(e)}\n请安装所需的依赖后重试。")
            return False

    def create_ui(self):
        """创建统一的用户界面"""
        # 创建主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 创建模式选择框架
        mode_frame = ttk.LabelFrame(main_frame, text="模式设置")
        mode_frame.pack(fill="x", pady=(0, 10))
        
        # 自动模式设置
        self.auto_mode = tk.BooleanVar(value=True)
        auto_mode_cb = ttk.Checkbutton(
            mode_frame, 
            text="自动模式 (检测到ESP32设备时自动执行)", 
            variable=self.auto_mode,
            command=self.on_auto_mode_changed
        )
        auto_mode_cb.pack(anchor="w", padx=10, pady=5)
        
        # 自动模式详细设置框架
        self.auto_settings_frame = ttk.Frame(mode_frame)
        self.auto_settings_frame.pack(fill="x", padx=20, pady=5)
        
        self.auto_flash = tk.BooleanVar(value=True)
        auto_flash_cb = ttk.Checkbutton(
            self.auto_settings_frame, 
            text="自动刷固件", 
            variable=self.auto_flash
        )
        auto_flash_cb.pack(anchor="w", pady=2)
        
        self.auto_read_mac = tk.BooleanVar(value=True)
        auto_mac_cb = ttk.Checkbutton(
            self.auto_settings_frame, 
            text="自动读取MAC地址", 
            variable=self.auto_read_mac
        )
        auto_mac_cb.pack(anchor="w", pady=2)
        
        # 固件配置框架
        firmware_frame = ttk.LabelFrame(main_frame, text="固件配置")
        firmware_frame.pack(fill="x", pady=(0, 10))
        
        # 滚动区域
        canvas = tk.Canvas(firmware_frame, height=200)
        scrollbar = ttk.Scrollbar(firmware_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 创建固件配置项
        self.firmware_vars = []
        self.firmware_entries = []
        self.address_entries = []
        
        for i in range(8):
            row_frame = ttk.Frame(scrollable_frame)
            row_frame.pack(fill="x", padx=5, pady=2)
            
            # 启用复选框
            enable_var = tk.BooleanVar()
            self.firmware_vars.append(enable_var)
            enable_cb = ttk.Checkbutton(row_frame, text=f"固件{i+1}", variable=enable_var)
            enable_cb.pack(side="left")
            
            # 地址输入框
            ttk.Label(row_frame, text="地址:").pack(side="left", padx=(10, 5))
            address_entry = ttk.Entry(row_frame, width=10)
            address_entry.insert(0, "0x0")
            address_entry.pack(side="left", padx=(0, 10))
            self.address_entries.append(address_entry)
            
            # 文件路径输入框
            file_entry = ttk.Entry(row_frame, width=40)
            file_entry.pack(side="left", padx=(0, 5))
            self.firmware_entries.append(file_entry)
            
            # 浏览按钮
            browse_btn = ttk.Button(
                row_frame, 
                text="浏览", 
                command=lambda idx=i: self.browse_firmware(idx)
            )
            browse_btn.pack(side="right")
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 串口配置框架
        port_frame = ttk.LabelFrame(main_frame, text="串口配置")
        port_frame.pack(fill="x", pady=(0, 10))
        
        port_top_frame = ttk.Frame(port_frame)
        port_top_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(port_top_frame, text="刷新串口", command=self.refresh_ports).pack(side="left")
        ttk.Button(port_top_frame, text="全选", command=self.select_all_ports).pack(side="left", padx=(10, 0))
        ttk.Button(port_top_frame, text="全不选", command=self.deselect_all_ports).pack(side="left", padx=(5, 0))
        
        # 串口列表框架
        self.ports_frame = ttk.Frame(port_frame)
        self.ports_frame.pack(fill="x", padx=5, pady=5)
        
        # 手动操作按钮框架
        manual_frame = ttk.LabelFrame(main_frame, text="手动操作")
        manual_frame.pack(fill="x", pady=(0, 10))
        
        button_frame = ttk.Frame(manual_frame)
        button_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Button(
            button_frame, 
            text="手动刷固件", 
            command=self.manual_flash,
            style='Flash.TButton'
        ).pack(side="left", padx=(0, 10))
        
        ttk.Button(
            button_frame, 
            text="手动读取MAC", 
            command=self.manual_read_mac,
            style='MAC.TButton'
        ).pack(side="left")
        
        # MAC地址记录框架
        mac_frame = ttk.LabelFrame(main_frame, text="MAC地址记录")
        mac_frame.pack(fill="x", pady=(0, 10))
        
        # MAC地址列表
        mac_list_frame = ttk.Frame(mac_frame)
        mac_list_frame.pack(fill="x", padx=5, pady=5)
        
        # 创建Treeview来显示MAC地址
        columns = ("时间", "端口", "芯片类型", "MAC地址")
        self.mac_tree = ttk.Treeview(mac_list_frame, columns=columns, show="headings", height=6)
        
        for col in columns:
            self.mac_tree.heading(col, text=col)
            self.mac_tree.column(col, width=120)
        
        mac_scrollbar = ttk.Scrollbar(mac_list_frame, orient="vertical", command=self.mac_tree.yview)
        self.mac_tree.configure(yscrollcommand=mac_scrollbar.set)
        
        self.mac_tree.pack(side="left", fill="both", expand=True)
        mac_scrollbar.pack(side="right", fill="y")
        
        # MAC操作按钮
        mac_btn_frame = ttk.Frame(mac_frame)
        mac_btn_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(mac_btn_frame, text="清除记录", command=self.clear_mac_records).pack(side="left")
        ttk.Button(mac_btn_frame, text="导出记录", command=self.export_mac_records).pack(side="left", padx=(10, 0))
        
        # 日志框架
        log_frame = ttk.LabelFrame(main_frame, text="操作日志")
        log_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # 日志工具栏
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill="x", pady=5)
        
        ttk.Button(log_toolbar, text="清除日志", command=self.clear_log).pack(side="right", padx=5)
        
        # 日志文本框
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        log_scrollbar = ttk.Scrollbar(log_text_frame)
        log_scrollbar.pack(side="right", fill="y")
        
        self.log_text = tk.Text(
            log_text_frame,
            height=15,
            yscrollcommand=log_scrollbar.set,
            font=('Consolas', font_size),
            background='#f9f9f9',
            foreground='#333333',
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(fill="both", expand=True)
        
        log_scrollbar.config(command=self.log_text.yview)

    def on_auto_mode_changed(self):
        """自动模式变化时的处理"""
        if self.auto_mode.get():
            self.auto_settings_frame.pack(fill="x", padx=20, pady=5)
        else:
            self.auto_settings_frame.pack_forget()

    def monitor_ports(self):
        """监控串口变化"""
        old_ports = set()
        while True:
            try:
                current_ports = set(port.device for port in serial.tools.list_ports.comports())
                
                if current_ports != old_ports:
                    self.root.after(0, lambda: self.handle_port_changes(old_ports, current_ports))
                    old_ports = current_ports
                
                time.sleep(1.5)
            except Exception:
                time.sleep(1.5)
                continue

    def handle_port_changes(self, old_ports, current_ports):
        """处理串口变化"""
        # 处理新增的端口
        new_ports = current_ports - old_ports
        if new_ports:
            self.log(f"检测到新端口: {', '.join(new_ports)}")
            if self.auto_mode.get():
                self.log("自动模式已启用，开始自动操作...")
                # 延迟执行，等待设备初始化
                self.root.after(1000, lambda: self.handle_new_ports(new_ports))
            else:
                self.log("自动模式未启用，请手动操作")
        
        # 更新端口列表显示
        self.refresh_ports()

    def handle_new_ports(self, new_ports):
        """处理新连接的端口"""
        enabled_ports = self.get_enabled_ports()
        
        for port in new_ports:
            if port in enabled_ports:
                # 在新线程中处理设备
                threading.Thread(
                    target=self.process_device_auto,
                    args=(port,),
                    daemon=True
                ).start()

    def process_device_auto(self, port):
        """自动处理设备"""
        try:
            self.log(f"正在处理端口 {port}...")
            
            # 检测芯片类型
            chip_type = self.detect_chip(port)
            if not chip_type:
                self.log(f"端口 {port}: 无法检测芯片类型")
                return
            
            self.log(f"端口 {port}: 检测到芯片类型 {chip_type}")
            
            # 根据设置执行操作
            if self.auto_flash.get():
                self.flash_single_port(port, chip_type)
            
            if self.auto_read_mac.get():
                self.read_mac_single_port(port, chip_type)
                
        except Exception as e:
            self.log(f"端口 {port} 处理失败: {str(e)}")

    def flash_single_port(self, port, chip_type=None):
        """对单个端口刷固件"""
        try:
            if not chip_type:
                chip_type = self.detect_chip(port)
                
            self.log(f"开始刷固件到端口 {port} (芯片: {chip_type})")
            
            # 获取启用的固件
            firmwares = []
            for i, enable_var in enumerate(self.firmware_vars):
                if enable_var.get() and self.firmware_entries[i].get().strip():
                    firmware_path = self.firmware_entries[i].get().strip()
                    address = self.address_entries[i].get().strip()
                    if os.path.exists(firmware_path):
                        firmwares.append((address, firmware_path))
            
            if not firmwares:
                self.log(f"端口 {port}: 没有可用的固件文件")
                return
            
            # 构建esptool命令
            cmd = ["python", "-m", "esptool", "--port", port]
            
            # 添加芯片参数
            chip_params = self.get_chip_param(chip_type)
            if chip_params:
                cmd.extend(chip_params)
            
            cmd.extend(["--baud", "921600", "--before", "default_reset", "--after", "hard_reset", "write_flash"])
            
            for address, firmware_path in firmwares:
                cmd.extend([address, firmware_path])
            
            # 执行命令
            self.log(f"端口 {port}: 执行命令: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            for line in process.stdout:
                if line.strip():
                    self.log(f"[{port}] {line.strip()}")
            
            process.wait()
            
            if process.returncode == 0:
                self.log(f"端口 {port}: 固件刷写成功!")
            else:
                self.log(f"端口 {port}: 固件刷写失败!")
                
        except Exception as e:
            self.log(f"端口 {port} 刷固件时发生错误: {str(e)}")

    def read_mac_single_port(self, port, chip_type=None):
        """读取单个端口的MAC地址"""
        try:
            if not chip_type:
                chip_type = self.detect_chip(port)
                
            self.log(f"开始读取端口 {port} 的MAC地址 (芯片: {chip_type})")
            
            # 构建命令
            cmd = ["python", "-m", "esptool", "--port", port]
            
            # 添加芯片参数
            chip_params = self.get_chip_param(chip_type)
            if chip_params:
                cmd.extend(chip_params)
            
            cmd.extend(["read_mac"])
            
            # 执行命令
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            output = ""
            for line in process.stdout:
                output += line
                if line.strip():
                    self.log(f"[{port}] {line.strip()}")
            
            process.wait()
            
            # 解析MAC地址
            mac_address = self.parse_mac_from_output(output)
            
            if mac_address:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.log(f"端口 {port}: MAC地址读取成功: {mac_address}")
                
                # 更新MAC地址记录
                self.update_mac_record(port, chip_type, mac_address, timestamp)
                
                # 保存到文件
                self.save_mac_to_file(port, mac_address, chip_type, timestamp)
            else:
                self.log(f"端口 {port}: 无法解析MAC地址")
                
        except Exception as e:
            self.log(f"端口 {port} 读取MAC地址时发生错误: {str(e)}")

    def parse_mac_from_output(self, output):
        """从esptool输出中解析MAC地址"""
        import re
        # 查找MAC地址模式
        mac_pattern = r'MAC:\s*([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})'
        match = re.search(mac_pattern, output)
        if match:
            return match.group(1)
        return None

    def update_mac_record(self, port, chip_type, mac_address, timestamp):
        """更新MAC地址记录到界面"""
        # 在Treeview中添加记录
        self.mac_tree.insert('', 0, values=(timestamp, port, chip_type, mac_address))

    def save_mac_to_file(self, port, mac_address, chip_type, timestamp):
        """保存MAC地址到文件"""
        try:
            with open(self.current_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp}\t{port}\t{chip_type}\t{mac_address}\n")
        except Exception as e:
            self.log(f"保存MAC地址到文件失败: {str(e)}")

    def detect_chip(self, port):
        """检测芯片类型"""
        try:
            cmd = ["python", "-m", "esptool", "--port", port, "chip_id"]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            output = ""
            for line in process.stdout:
                output += line
            
            process.wait()
            
            # 解析芯片类型
            if "ESP32-S3" in output:
                return "ESP32-S3"
            elif "ESP32-S2" in output:
                return "ESP32-S2"
            elif "ESP32-C3" in output:
                return "ESP32-C3"
            elif "ESP32" in output:
                return "ESP32"
            
            return "ESP32"  # 默认
            
        except Exception:
            return "ESP32"  # 默认

    def get_chip_param(self, chip_type):
        """获取芯片参数"""
        chip_params = {
            "ESP32": ["--chip", "esp32"],
            "ESP32-S2": ["--chip", "esp32s2"],
            "ESP32-S3": ["--chip", "esp32s3"],
            "ESP32-C3": ["--chip", "esp32c3"],
        }
        return chip_params.get(chip_type, ["--chip", "esp32"])

    def manual_flash(self):
        """手动刷固件"""
        enabled_ports = self.get_enabled_ports()
        if not enabled_ports:
            messagebox.showwarning("警告", "请先选择要操作的串口")
            return
        
        # 检查是否有启用的固件
        has_firmware = any(var.get() and entry.get().strip() 
                          for var, entry in zip(self.firmware_vars, self.firmware_entries))
        
        if not has_firmware:
            messagebox.showwarning("警告", "请先配置并启用至少一个固件")
            return
        
        self.log("开始手动刷固件...")
        
        for port in enabled_ports:
            threading.Thread(
                target=self.flash_single_port,
                args=(port,),
                daemon=True
            ).start()

    def manual_read_mac(self):
        """手动读取MAC地址"""
        enabled_ports = self.get_enabled_ports()
        if not enabled_ports:
            messagebox.showwarning("警告", "请先选择要操作的串口")
            return
        
        self.log("开始手动读取MAC地址...")
        
        for port in enabled_ports:
            threading.Thread(
                target=self.read_mac_single_port,
                args=(port,),
                daemon=True
            ).start()

    def get_enabled_ports(self):
        """获取启用的串口列表"""
        enabled_ports = []
        for port_var, port_name in getattr(self, 'port_checkboxes', []):
            if port_var.get():
                enabled_ports.append(port_name)
        return enabled_ports

    def refresh_ports(self):
        """刷新串口列表"""
        # 清除现有的端口复选框
        for widget in self.ports_frame.winfo_children():
            widget.destroy()
        
        # 获取当前可用的串口
        ports = serial.tools.list_ports.comports()
        
        self.port_checkboxes = []
        
        if ports:
            for i, port in enumerate(ports):
                port_var = tk.BooleanVar()
                
                # 从配置中恢复状态
                if i < len(self.config.get('port_enables', [])):
                    port_var.set(self.config['port_enables'][i])
                else:
                    port_var.set(True)
                
                port_cb = ttk.Checkbutton(
                    self.ports_frame,
                    text=f"{port.device} - {port.description}",
                    variable=port_var
                )
                port_cb.pack(anchor="w", padx=5, pady=2)
                
                self.port_checkboxes.append((port_var, port.device))
        else:
            ttk.Label(self.ports_frame, text="没有检测到可用的串口").pack(padx=5, pady=5)

    def select_all_ports(self):
        """全选串口"""
        for port_var, _ in getattr(self, 'port_checkboxes', []):
            port_var.set(True)

    def deselect_all_ports(self):
        """全不选串口"""
        for port_var, _ in getattr(self, 'port_checkboxes', []):
            port_var.set(False)

    def browse_firmware(self, index):
        """浏览选择固件文件"""
        filename = filedialog.askopenfilename(
            title=f"选择固件文件 {index + 1}",
            filetypes=[("固件文件", "*.bin"), ("所有文件", "*.*")]
        )
        if filename:
            self.firmware_entries[index].delete(0, tk.END)
            self.firmware_entries[index].insert(0, filename)

    def clear_mac_records(self):
        """清除MAC地址记录"""
        for item in self.mac_tree.get_children():
            self.mac_tree.delete(item)

    def export_mac_records(self):
        """导出MAC地址记录"""
        filename = filedialog.asksaveasfilename(
            title="导出MAC地址记录",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("CSV文件", "*.csv"), ("所有文件", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write("时间\t端口\t芯片类型\tMAC地址\n")
                    for item in self.mac_tree.get_children():
                        values = self.mac_tree.item(item, 'values')
                        f.write(f"{values[0]}\t{values[1]}\t{values[2]}\t{values[3]}\n")
                
                messagebox.showinfo("成功", f"MAC地址记录已导出到: {filename}")
                
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {str(e)}")

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                
                # 恢复界面状态
                self.auto_mode.set(self.config.get('auto_mode', True))
                self.auto_flash.set(self.config.get('auto_flash', True))
                self.auto_read_mac.set(self.config.get('auto_read_mac', True))
                
                # 恢复固件配置
                for i, (enable_var, path_entry, addr_entry) in enumerate(
                    zip(self.firmware_vars, self.firmware_entries, self.address_entries)
                ):
                    if i < len(self.config.get('firmware_enables', [])):
                        enable_var.set(self.config['firmware_enables'][i])
                    if i < len(self.config.get('firmware_paths', [])):
                        path_entry.delete(0, tk.END)
                        path_entry.insert(0, self.config['firmware_paths'][i])
                    if i < len(self.config.get('firmware_addresses', [])):
                        addr_entry.delete(0, tk.END)
                        addr_entry.insert(0, self.config['firmware_addresses'][i])
                
                self.on_auto_mode_changed()
                
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")

    def save_config(self):
        """保存配置"""
        try:
            # 收集当前配置
            self.config['auto_mode'] = self.auto_mode.get()
            self.config['auto_flash'] = self.auto_flash.get()
            self.config['auto_read_mac'] = self.auto_read_mac.get()
            
            # 固件配置
            self.config['firmware_enables'] = [var.get() for var in self.firmware_vars]
            self.config['firmware_paths'] = [entry.get() for entry in self.firmware_entries]
            self.config['firmware_addresses'] = [entry.get() for entry in self.address_entries]
            
            # 串口配置
            self.config['port_enables'] = [var.get() for var, _ in getattr(self, 'port_checkboxes', [])]
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def log(self, message):
        """添加日志消息"""
        def _log():
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{timestamp}] {message}\n")
            self.log_text.see("end")
        
        if threading.current_thread() is threading.main_thread():
            _log()
        else:
            self.root.after(0, _log)

    def clear_log(self):
        """清除日志"""
        self.log_text.delete(1.0, tk.END)

    def on_closing(self):
        """关闭时保存配置"""
        self.save_config()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = ESP32UnifiedTool(root)
    
    # 绑定关闭事件
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    root.mainloop()

if __name__ == "__main__":
    main() 