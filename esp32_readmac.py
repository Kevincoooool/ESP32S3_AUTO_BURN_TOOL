import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports
import threading
import time
import json
import os
import subprocess
import datetime

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

class LogWindow:
    def __init__(self, port):
        self.window = tk.Toplevel()
        self.window.title(f"端口 {port} MAC地址读取日志")
        self.window.geometry("600x450")  # 调整窗口大小
        
        # 设置窗口图标
        try:
            self.window.iconbitmap("icon.ico")  # 如果有图标文件的话
        except:
            pass
        
        # 创建日志工具栏
        log_toolbar = ttk.Frame(self.window)
        log_toolbar.pack(fill="x", pady=(5, 5))
        
        # 添加清除日志按钮
        clear_button = ttk.Button(log_toolbar, text="清除日志", command=self.clear_log, style='Accent.TButton')
        clear_button.pack(side="right", padx=5)
        
        # 创建滚动条和文本框
        scrollbar = ttk.Scrollbar(self.window)
        scrollbar.pack(side="right", fill="y")
        
        # 使用自定义字体和颜色
        self.log_text = tk.Text(
            self.window, 
            height=20, 
            yscrollcommand=scrollbar.set,
            font=('Consolas', font_size),
            background='#f9f9f9',
            foreground='#333333',
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        scrollbar.config(command=self.log_text.yview)
        
    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        
    def destroy(self):
        self.window.destroy()

class ESP32MACReader:
    def __init__(self, root):
        self.root = root
        self.config_file = 'mac_reader_config.json'
        self.root.title("ESP32 MAC地址读取工具")
        self.root.geometry("700x900")  # 调整主窗口大小
        
        # 检查并安装必要的依赖
        if not self.check_dependencies():
            self.root.withdraw()  # 隐藏主窗口
            self.root.quit()  # 退出程序
            return
            
        # 设置窗口图标
        try:
            self.root.iconbitmap("icon.ico")  # 如果有图标文件的话
        except:
            pass
        
        # 应用现代风格
        set_modern_style(root)
        
        # 初始化基本变量
        self.log_windows = {}
        self.config = {}
        self.port_enables = []
        self.mac_addresses = {}  # 存储读取到的MAC地址
        self.current_log_file = self.generate_log_filename()  # 生成当前日志文件名
        
        # 创建UI
        self.create_ui()
        
        # 延迟加载配置和启动监控
        self.root.after(100, self.delayed_init)
    
    def generate_log_filename(self):
        """生成带时间戳的日志文件名"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"MAC_Addresses_{timestamp}.txt"
    
    def check_dependencies(self):
        """检查必要的依赖"""
        try:
            import serial
            import subprocess
            return True
        except ImportError as e:
            tk.messagebox.showerror("依赖错误", f"缺少必要的依赖: {str(e)}\n请安装所需的依赖后重试。")
            return False

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
        import sys
        sys.stdout = LogRedirector(self.log)
        sys.stderr = LogRedirector(self.log)
        
        # 记录启动信息
        self.log(f"MAC地址读取工具已启动，结果将保存到: {self.current_log_file}")

    def monitor_ports(self):
        """优化串口监控逻辑"""
        old_ports = set()
        while True:
            try:
                current_ports = set(port.device for port in serial.tools.list_ports.comports())
                
                if current_ports != old_ports:
                    # 使用一个函数处理所有端口变化
                    self.root.after(0, lambda: self.handle_port_changes(old_ports, current_ports))
                    old_ports = current_ports
                
                # 增加睡眠时间，减少CPU使用
                time.sleep(1.5)
            except Exception as e:
                self.log(f"监控端口异常: {str(e)}")
                time.sleep(1.5)
                continue

    def handle_port_changes(self, old_ports, current_ports):
        """统一处理端口变化"""
        # 处理移除的端口
        for port in (old_ports - current_ports):
            if port in self.log_windows:
                self.close_log_window(port)
        
        # 处理新增的端口
        new_ports = current_ports - old_ports
        if new_ports:
            self.log(f"检测到新端口: {new_ports}")
            if self.auto_read.get():
                self.log("自动读取已启用，开始读取MAC地址...")
                # 添加短暂延迟，等待设备初始化
                self.root.after(1000, lambda: self.handle_new_ports(new_ports))
            else:
                self.log("自动读取未启用")
        
        # 更新端口列表
        self.refresh_ports()

    def handle_new_ports(self, new_ports):
        """处理新增端口"""
        self.log(f"处理新端口: {new_ports}")
        
        # 过滤出启用的端口
        enabled_ports = []
        for port in new_ports:
            # 查找端口在comboboxes中的索引
            for i, cb in enumerate(self.port_comboboxes):
                if cb.get() == port and self.port_enables[i].get():
                    enabled_ports.append(port)
                    break
        
        if not enabled_ports:
            self.log("没有启用的端口可用于自动读取MAC地址")
            return
        
        self.log(f"开始为 {len(enabled_ports)} 个启用的端口读取MAC地址")
        
        # 为每个启用的端口创建读取线程
        for port in enabled_ports:
            thread = threading.Thread(
                target=self.read_mac_process,
                args=(port,),
                daemon=True
            )
            thread.start()

    def create_ui(self):
        # 创建主框架，添加内边距
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        # 串口选择
        self.port_frame = ttk.LabelFrame(main_frame, text="串口设置", padding=10)
        self.port_frame.pack(fill="x", pady=5)
        
        # 创建左右布局框架
        port_left_frame = ttk.Frame(self.port_frame)
        port_left_frame.pack(side="left", fill="both", expand=True)
        
        port_right_frame = ttk.Frame(self.port_frame)
        port_right_frame.pack(side="right", fill="both", expand=True)
        
        # 创建8个串口选择组
        self.port_comboboxes = []
        self.port_labels = []
        
        # 创建左侧串口1-4
        for i in range(4):
            frame = ttk.Frame(port_left_frame)
            frame.pack(fill="x", pady=4)  # 增加垂直间距
            
            # 添加启用复选框
            enable_var = tk.BooleanVar(value=True)  # 默认启用
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.port_enables.append(enable_var)
            
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
            
        # 创建右侧串口5-8
        for i in range(4, 8):
            frame = ttk.Frame(port_right_frame)
            frame.pack(fill="x", pady=4)  # 增加垂直间距
            
            # 添加启用复选框
            enable_var = tk.BooleanVar(value=True)  # 默认启用
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.port_enables.append(enable_var)
            
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
        
        # 刷新按钮放在底部中间，使用强调样式
        self.refresh_button = ttk.Button(
            self.port_frame, 
            text="刷新", 
            command=self.refresh_ports,
            style='Accent.TButton'
        )
        self.refresh_button.pack(pady=8)  # 增加垂直间距
        
        # 读取设置
        self.settings_frame = ttk.LabelFrame(main_frame, text="读取设置", padding=10)
        self.settings_frame.pack(fill="x", pady=8)  # 增加垂直间距
        
        # 自动读取选项
        self.auto_read = tk.BooleanVar(value=True)  # 默认启用自动读取
        self.auto_read_check = ttk.Checkbutton(
            self.settings_frame, 
            text="自动读取MAC地址", 
            variable=self.auto_read,
            command=lambda: self.save_config()
        )
        self.auto_read_check.pack(side="left", padx=15)  # 增加水平间距
        
        # 当前日志文件显示
        self.log_file_frame = ttk.Frame(self.settings_frame)
        self.log_file_frame.pack(side="right", fill="x", expand=True)
        
        self.log_file_label = ttk.Label(self.log_file_frame, text="当前日志文件:")
        self.log_file_label.pack(side="left", padx=5)
        
        self.log_file_path = ttk.Label(self.log_file_frame, text=self.current_log_file)
        self.log_file_path.pack(side="left", padx=5)
        
        # 读取按钮，使用强调样式
        self.read_button = ttk.Button(
            main_frame, 
            text="开始读取MAC地址", 
            command=self.start_read,
            style='Accent.TButton'
        )
        self.read_button.pack(pady=12)  # 增加垂直间距
        
        # MAC地址显示区域
        self.mac_frame = ttk.LabelFrame(main_frame, text="MAC地址列表", padding=10)
        self.mac_frame.pack(fill="x", pady=8)  # 增加垂直间距
        
        # 创建MAC地址列表
        self.mac_list = ttk.Treeview(
            self.mac_frame,
            columns=("端口", "MAC地址", "芯片类型", "时间"),
            show="headings",
            height=10
        )
        
        # 设置列宽和标题
        self.mac_list.column("端口", width=100)
        self.mac_list.column("MAC地址", width=200)
        self.mac_list.column("芯片类型", width=100)
        self.mac_list.column("时间", width=150)
        
        self.mac_list.heading("端口", text="端口")
        self.mac_list.heading("MAC地址", text="MAC地址")
        self.mac_list.heading("芯片类型", text="芯片类型")
        self.mac_list.heading("时间", text="时间")
        
        # 添加滚动条
        mac_scrollbar = ttk.Scrollbar(self.mac_frame, orient="vertical", command=self.mac_list.yview)
        self.mac_list.configure(yscrollcommand=mac_scrollbar.set)
        
        self.mac_list.pack(side="left", fill="both", expand=True)
        mac_scrollbar.pack(side="right", fill="y")
        
        # 日志显示
        self.log_frame = ttk.LabelFrame(main_frame, text="日志", padding=10)
        self.log_frame.pack(fill="both", expand=True, pady=8)  # 增加垂直间距
        
        # 创建日志工具栏
        log_toolbar = ttk.Frame(self.log_frame)
        log_toolbar.pack(fill="x", pady=(0, 5))
        
        # 添加清除日志按钮
        clear_button = ttk.Button(
            log_toolbar, 
            text="清除日志", 
            command=self.clear_log,
            style='Accent.TButton'
        )
        clear_button.pack(side="right")
        
        # 创建滚动条
        scrollbar = ttk.Scrollbar(self.log_frame)
        scrollbar.pack(side="right", fill="y")
        
        # 创建文本框并关联滚动条，使用更现代的样式
        self.log_text = tk.Text(
            self.log_frame, 
            height=10,  # 增加高度
            yscrollcommand=scrollbar.set,
            font=('Consolas', font_size),  # 使用等宽字体
            background='#f9f9f9',  # 浅灰色背景
            foreground='#333333',  # 深灰色文字
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        
        # 设置滚动条的命令
        scrollbar.config(command=self.log_text.yview)

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        
        # 清空所有下拉框
        for combobox in self.port_comboboxes:
            combobox.set('')
            combobox['values'] = []
        
        # 为每个检测到的端口设置对应的下拉框
        for i, port in enumerate(ports[:8]):  # 最多8个端口
            self.port_comboboxes[i]['values'] = [port]
            self.port_comboboxes[i].set(port)

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    # 加载串口启用状态
                    if 'port_enables' in self.config:
                        for i, enabled in enumerate(self.config['port_enables']):
                            if i < len(self.port_enables):
                                self.port_enables[i].set(enabled)
                    # 加载自动读取设置
                    if 'auto_read' in self.config:
                        self.auto_read.set(self.config['auto_read'])
            else:
                self.config = {
                    'port_enables': [True] * 8,  # 默认全部启用
                    'auto_read': True  # 默认启用自动读取
                }
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
            self.config = {
                'port_enables': [True] * 8,  # 默认全部启用
                'auto_read': True  # 默认启用自动读取
            }

    def save_config(self):
        try:
            self.config['port_enables'] = [enable.get() for enable in self.port_enables]
            self.config['auto_read'] = self.auto_read.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f)
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def start_read(self):
        # 获取启用的串口
        selected_ports = []
        for i, cb in enumerate(self.port_comboboxes):
            if cb.get() and self.port_enables[i].get():  # 只选择启用的串口
                selected_ports.append(cb.get())
        
        if not selected_ports:
            self.log("错误: 请选择并启用至少一个串口")
            return
        
        # 为每个选中的端口创建读取线程
        for port in selected_ports:
            thread = threading.Thread(
                target=self.read_mac_process,
                args=(port,),
                daemon=True
            )
            thread.start()

    def read_mac_process(self, port):
        # 创建新的日志窗口
        log_window = LogWindow(port)
        self.log_windows[port] = log_window
        # 确保日志窗口显示在前台
        log_window.window.lift()
        log_window.window.focus_force()
        
        # 记录开始信息
        log_window.log(f"开始从端口 {port} 读取MAC地址...")
        self.log(f"开始从端口 {port} 读取MAC地址...")
        
        try:
            # 检测芯片类型
            log_window.log(f"检测芯片类型...")
            
            # 使用子进程执行芯片检测
            import subprocess
            cmd = ["python", "-m", "esptool", "--port", port, "chip_id"]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                startupinfo=startupinfo
            )

            output = ""
            for line in process.stdout:
                log_window.log(line.strip())
                output += line
            process.wait()
            
            # 从输出中解析芯片类型
            chip_type = None
            if "Chip is ESP32-S3" in output:
                chip_type = "ESP32-S3"
            elif "Chip is ESP32-S2" in output:
                chip_type = "ESP32-S2"
            elif "Chip is ESP32-C3" in output:
                chip_type = "ESP32-C3"
            elif "Chip is ESP32-C6" in output:
                chip_type = "ESP32-C6"
            elif "Chip is ESP32-P4" in output:
                chip_type = "ESP32-P4"
            elif "Chip is ESP32" in output:
                chip_type = "ESP32"
            
            if not chip_type:
                log_window.log("未能识别芯片类型")
                return
            
            log_window.log(f"检测到芯片类型: {chip_type}")
            
            # 读取MAC地址
            log_window.log("读取MAC地址...")
            cmd = ["python", "-m", "esptool", "--port", port, "read_mac"]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                startupinfo=startupinfo
            )

            mac_output = ""
            for line in process.stdout:
                log_window.log(line.strip())
                mac_output += line
            process.wait()
            
            # 从输出中提取MAC地址
            mac_address = None
            for line in mac_output.split('\n'):
                if "MAC:" in line:
                    mac_address = line.split("MAC:")[1].strip()
                    break
            
            if not mac_address:
                log_window.log("未能读取MAC地址")
                return
            # 检查MAC地址是否已存在
            if os.path.exists(self.current_log_file):
                with open(self.current_log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if mac_address in line:
                            log_window.log(f"MAC地址 {mac_address} 已存在，跳过记录")
                            self.log(f"MAC地址 {mac_address} 已存在，跳过记录")
                            # 延迟2秒后关闭窗口
                            self.root.after(2000, lambda: self.close_log_window(port))
                            return
        
            # 记录时间
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 更新MAC地址列表
            self.root.after(0, lambda: self.update_mac_list(port, mac_address, chip_type, timestamp))
            
            # 保存到文件
            self.save_mac_to_file(port, mac_address, chip_type, timestamp)
            
            log_window.log(f"成功读取MAC地址: {mac_address}")
            self.log(f"端口 {port} 成功读取MAC地址: {mac_address}")
            # 延迟2秒后关闭窗口，让用户有时间看到结果
            self.root.after(2000, lambda: self.close_log_window(port))
                
        except Exception as e:
            error_msg = f"读取MAC地址失败: {str(e)}"
            log_window.log(error_msg)
            self.log(error_msg)

    def update_mac_list(self, port, mac_address, chip_type, timestamp):
        # 将MAC地址添加到列表中
        self.mac_list.insert("", "end", values=(port, mac_address, chip_type, timestamp))
        # 保存到内存中
        self.mac_addresses[port] = {
            "mac": mac_address,
            "chip_type": chip_type,
            "timestamp": timestamp
        }

    def save_mac_to_file(self, port, mac_address, chip_type, timestamp):
        try:
            # 检查文件是否存在
            if os.path.exists(self.current_log_file):
                # 读取现有文件内容，检查MAC地址是否已存在
                with open(self.current_log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if mac_address in line:
                            self.log(f"MAC地址 {mac_address} 已存在，跳过保存")
                            return
            
            # MAC地址不存在，追加保存
            with open(self.current_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp}\t{port}\t{chip_type}\t{mac_address}\n")
                self.log(f"MAC地址 {mac_address} 已保存到文件")
        except Exception as e:
            self.log(f"保存MAC地址到文件失败: {str(e)}")

    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        
    def close_log_window(self, port):
        if port in self.log_windows:
            self.log_windows[port].destroy()
            del self.log_windows[port]

def main():
    root = tk.Tk()
    app = ESP32MACReader(root)
    root.mainloop()

if __name__ == "__main__":
    main()