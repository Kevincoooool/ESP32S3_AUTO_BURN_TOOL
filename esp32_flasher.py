import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
import time
import json
import os
import locale
import subprocess
import sys
import io

# 导入serial模块
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    import serial
    import serial.tools.list_ports
    list_ports = serial.tools.list_ports

# 导入esptool模块（打包后也可用）
try:
    import esptool
except ImportError:
    esptool = None

font_size = 10

# 科技感配色方案 - 冷静蓝 + 深色文字
COLORS = {
    'primary': '#1d4ed8',        # 科技蓝（更深以提升对比）
    'primary_hover': '#1338a3',
    'primary_press': '#0f2f82',
    'success': '#12b76a',
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'bg_main': '#f8fafc',        # 主背景：浅冷灰蓝
    'bg_secondary': '#ffffff',   # 面板/输入背景
    'border': '#e2e8f0',         # 边框
    'text_primary': '#0f172a',   # 深色文字
    'text_secondary': '#475569'  # 次级文字
}

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
    
    # 统一背景
    style.configure('TFrame', background=COLORS['bg_main'])
    
    # 自定义按钮样式 - 现代科技感
    style.configure(
        'TButton',
        font=('Microsoft YaHei UI', font_size),
        padding=(6, 3),
        background=COLORS['bg_secondary'],
        foreground=COLORS['text_primary'],
        borderwidth=1,
        relief='flat'
    )
    style.map(
        'TButton',
        background=[
            ('!disabled', COLORS['bg_secondary']),
            ('active', '#e2e8f0'),
            ('pressed', COLORS['border'])
        ],
        foreground=[('disabled', COLORS['text_secondary'])]
    )
    
    # 强调按钮样式 - 蓝色主色
    style.configure(
        'Accent.TButton',
        font=('Microsoft YaHei UI', font_size + 1, 'bold'),
        padding=(12, 6),
        foreground=COLORS['primary']
    )
    style.map(
        'Accent.TButton',
        foreground=[
            ('disabled', COLORS['text_secondary']),
            ('pressed', COLORS['primary_press']),
            ('active', COLORS['primary_hover'])
        ]
    )
    
    # 自定义标签框样式
    style.configure(
        'TLabelframe',
        font=('Microsoft YaHei UI', font_size),
        borderwidth=1,
        relief='solid',
        background=COLORS['bg_main']
    )
    style.configure(
        'TLabelframe.Label',
        font=('Microsoft YaHei UI', font_size + 1, 'bold'),
        foreground=COLORS['text_primary'],
        background=COLORS['bg_main'],
        padding=(4, 0)
    )
    
    # 自定义标签样式
    style.configure(
        'TLabel',
        font=('Microsoft YaHei UI', font_size),
        foreground=COLORS['text_primary'],
        background=COLORS['bg_main']
    )
    
    # 自定义输入框样式
    style.configure(
        'TEntry',
        font=('Microsoft YaHei UI', font_size),
        foreground=COLORS['text_primary'],
        fieldbackground=COLORS['bg_secondary']
    )
    
    # 自定义下拉框样式
    # Treeview 扁平化美化
    style.configure("Treeview", 
        background="#ffffff",
        foreground=COLORS['text_primary'],
        rowheight=32,
        fieldbackground="#ffffff",
        borderwidth=0,
        font=('Microsoft YaHei UI', 9)
    )
    style.configure("Treeview.Heading",
        background=COLORS['bg_main'],
        foreground=COLORS['text_secondary'],
        font=('Microsoft YaHei UI', 10, 'bold'),
        borderwidth=0,
        relief='flat',
        padding=(0, 6)
    )
    style.map("Treeview", background=[('selected', COLORS['primary'])], foreground=[('selected', 'white')])

    style.configure(
        'TCombobox',
        font=('Microsoft YaHei UI', font_size),
        foreground=COLORS['text_primary'],
        fieldbackground=COLORS['bg_secondary']
    )
    
    # 自定义复选框样式
    style.configure(
        'TCheckbutton',
        font=('Microsoft YaHei UI', font_size),
        foreground=COLORS['text_primary'],
        background=COLORS['bg_main']
    )
    
    # 设置窗口默认字体
    root.option_add('*Font', ('Microsoft YaHei UI', font_size))
    
    # 设置窗口背景色
    root.configure(bg=COLORS['bg_main'])
    
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
    def __init__(self, port, on_close=None):
        self.window = tk.Toplevel()
        self.window.title(f"端口 {port} 烧录日志")
        self.window.geometry("700x500")  # 调整窗口大小
        self.window.configure(bg=COLORS['bg_main'])
        self._on_close = on_close
        
        # 设置窗口图标
        try:
            self.window.iconbitmap("icon.ico")  # 如果有图标文件的话
        except:
            pass
        
        # 创建主容器
        container = ttk.Frame(self.window, padding=10)
        container.pack(fill="both", expand=True)
        
        # 创建日志工具栏
        log_toolbar = ttk.Frame(container)
        log_toolbar.pack(fill="x", pady=(0, 10))
        
        # 工具栏标题
        toolbar_label = ttk.Label(
            log_toolbar, 
            text=f"端口: {port}",
            font=('Microsoft YaHei UI', font_size, 'bold')
        )
        toolbar_label.pack(side="left")
        
        # 添加清除日志按钮
        clear_button = ttk.Button(
            log_toolbar, 
            text="清除日志", 
            command=self.clear_log, 
            style='TButton'
        )
        clear_button.pack(side="right", padx=5)
        
        # 创建日志文本框架
        log_frame = ttk.Frame(container)
        log_frame.pack(fill="both", expand=True)
        
        # 创建滚动条和文本框
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        
        # 使用自定义字体和颜色
        self.log_text = tk.Text(
            log_frame, 
            height=20, 
            yscrollcommand=scrollbar.set,
            font=('Consolas', 10),
            background=COLORS['bg_secondary'],
            foreground=COLORS['text_primary'],
            borderwidth=1,
            relief="solid",
            padx=10,
            pady=10,
            wrap=tk.WORD
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        
        scrollbar.config(command=self.log_text.yview)
        
        # 关闭窗口时回调（用于停止烧录）
        try:
            self.window.protocol("WM_DELETE_WINDOW", self._handle_close)
        except Exception:
            pass

    def _handle_close(self):
        try:
            if callable(self._on_close):
                self._on_close()
        finally:
            try:
                self.window.destroy()
            except Exception:
                pass
        
    def log(self, message):
        try:
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        except Exception:
            pass
        
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        
    def destroy(self):
        self.window.destroy()

class ESP32Flasher:
    def __init__(self, root):
        self.root = root
        self.config_file = 'config.json'
        self.root.title("ESP32 烧录工具")
        self.root.geometry("1350x800")  # 调整为宽屏布局，包含统计面板
        
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
        self.flash_cancel_events = {}
        self.flash_processes = {}
        self.config = {'firmware_paths': [''] * 8, 'firmware_addresses': ['0x0'] * 8}  # 修改为8个
        self.port_enables = []  # 添加串口启用状态列表
        
        # 烧录统计数据
        self.flash_records = []  # 烧录记录列表
        self.flash_success_count = 0  # 成功次数
        self.flash_fail_count = 0  # 失败次数
        self.flash_total_count = 0  # 总次数
        
        # 创建UI
        self.create_ui()
        
        # 主窗口关闭时，停止烧录并退出
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.on_main_close)
        except Exception:
            pass
        
        # 延迟加载配置和启动监控
        self.root.after(100, self.delayed_init)

    def delayed_init(self):
        """延迟初始化，提高启动速度"""
        # 加载配置
        self.load_config()
        
        # 初始化串口列表
        self.refresh_ports()
        
        # 启动串口监控
        self.log("正在启动串口监控线程...")
        self.port_monitor_thread = threading.Thread(target=self.monitor_ports, daemon=True)
        self.port_monitor_thread.start()
        self.log("串口监控线程已启动，等待设备插入...")
        
        # 重定向标准输出到日志框
        import sys
        sys.stdout = LogRedirector(self.log)
        sys.stderr = LogRedirector(self.log)

    def monitor_ports(self):
        """优化串口监控逻辑"""
        old_ports = set()
        while True:
            try:
                current_ports = set(port.device for port in list_ports.comports())
                
                if current_ports != old_ports:
                    # 创建副本并使用默认参数捕获值，避免引用问题
                    old_ports_copy = old_ports.copy()
                    current_ports_copy = current_ports.copy()
                    self.root.after(0, lambda o=old_ports_copy, c=current_ports_copy: self.handle_port_changes(o, c))
                    old_ports = current_ports
                
                # 增加睡眠时间，减少CPU使用
                time.sleep(1.5)
            except Exception as e:
                # 记录异常，帮助调试
                try:
                    self.log(f"[错误] 端口监控异常: {str(e)}")
                except:
                    pass
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
            self.log(f"[调试] 检测到新端口: {list(new_ports)}")
            self.log(f"[调试] 自动烧录状态: {self.auto_flash.get()}")
            
            if self.auto_flash.get():
                self.log("自动烧录已启用，准备开始烧录...")
                # 转换为列表并创建副本，避免引用问题
                new_ports_list = list(new_ports)
                self.log(f"[调试] 将在1秒后处理端口: {new_ports_list}")
                # 添加短暂延迟，等待设备初始化
                self.root.after(1000, lambda ports=new_ports_list: self.handle_new_ports(ports))
            else:
                self.log("自动烧录未启用，请勾选'自动烧录'选项")
        
        # 更新端口列表
        self.refresh_ports()

    def handle_new_ports(self, new_ports):
        """处理新增端口"""
        self.log(f"[调试] 开始处理新端口: {new_ports}")
        selected_firmwares = []
        
        # 检查启用的固件
        self.log(f"[调试] 检查固件启用状态...")
        enabled_count = 0
        for i in range(8):
            if self.firmware_enables[i].get():
                enabled_count += 1
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                self.log(f"[调试] 固件 #{i+1} 已启用: {firmware}")
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
                    self.log(f"已选择固件 #{i+1}: {os.path.basename(firmware)} 地址: {address}")
                else:
                    self.log(f"警告: 固件 #{i+1} 已启用但路径无效: {firmware}")
        
        self.log(f"[调试] 共有 {enabled_count} 个固件被启用，{len(selected_firmwares)} 个有效")
        
        if not selected_firmwares:
            self.log("错误: 没有选择有效的固件，无法执行自动烧录")
            self.log("提示: 请勾选至少一个固件前的复选框，并确保固件路径有效")
            return
        
        # 对于自动烧录，直接使用所有新插入的端口
        # 不需要检查 combobox 的启用状态（那是手动烧录才需要的）
        enabled_ports = list(new_ports)
        
        if not enabled_ports:
            self.log("没有新端口可用于自动烧录")
            return
        
        self.log(f"开始为 {len(enabled_ports)} 个新端口烧录 {len(selected_firmwares)} 个固件")
        
        # 为每个新端口创建烧录线程
        for port in enabled_ports:
            self.log(f"[调试] 启动烧录线程: {port}")
            thread = threading.Thread(
                target=self.flash_process_multi,
                args=(port, selected_firmwares),
                daemon=True
            )
            thread.start()
            self.log(f"烧录线程已启动: {port}")

    def create_ui(self):
        # 创建左右分割主窗口
        self.root_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.root_paned.pack(fill="both", expand=True)

        # 创建主框架（左侧），添加内边距
        main_frame = ttk.Frame(self.root_paned, padding=15)
        self.root_paned.add(main_frame, weight=7)
        
        # === 历史记录面板（右侧） ===
        history_frame = ttk.Frame(self.root_paned, padding=15)
        self.root_paned.add(history_frame, weight=3)
        
        history_title = ttk.Label(history_frame, text="烧录记录", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['text_primary'])
        history_title.pack(anchor="w", pady=(0, 15))
        
        columns = ("time", "port", "mac", "chip", "status")
        self.history_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=20)
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("port", text="端口")
        self.history_tree.heading("mac", text="MAC地址")
        self.history_tree.heading("chip", text="芯片")
        self.history_tree.heading("status", text="状态")
        
        self.history_tree.column("time", width=70, anchor="center")
        self.history_tree.column("port", width=60, anchor="center")
        self.history_tree.column("mac", width=125, anchor="center")
        self.history_tree.column("chip", width=75, anchor="center")
        self.history_tree.column("status", width=50, anchor="center")
        
        history_scroll = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=history_scroll.set)
        
        self.history_tree.pack(side="left", fill="both", expand=True)
        history_scroll.pack(side="right", fill="y")
        
        self.history_tree.tag_configure('success', foreground=COLORS['success'], font=('Microsoft YaHei UI', 9))
        self.history_tree.tag_configure('fail', foreground=COLORS['danger'], font=('Microsoft YaHei UI', 9))

        # === 顶部区域 ===
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill="x", pady=(0, 15))
        
        title_label = ttk.Label(
            title_frame, text="ESP32 批量烧录工具",
            font=('Microsoft YaHei UI', 15, 'bold'), foreground=COLORS['primary']
        )
        title_label.pack(side="left")
        
        subtitle_label = ttk.Label(
            title_frame, text="支持多路串口并行烧录", font=('Microsoft YaHei UI', 10), foreground=COLORS['text_secondary']
        )
        subtitle_label.pack(side="left", padx=(15,0), pady=(4,0))
        
        stats_frame = ttk.Frame(title_frame)
        stats_frame.pack(side="right", fill="y")
        
        ttk.Label(stats_frame, text="成功:", font=('Microsoft YaHei UI', 10)).pack(side="left", padx=(0, 4))
        self.success_label = ttk.Label(stats_frame, text="0", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['success'])
        self.success_label.pack(side="left", padx=(0, 12))
        
        ttk.Label(stats_frame, text="失败:", font=('Microsoft YaHei UI', 10)).pack(side="left", padx=(0, 4))
        self.fail_label = ttk.Label(stats_frame, text="0", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['danger'])
        self.fail_label.pack(side="left", padx=(0, 12))
        
        self.export_button = ttk.Button(stats_frame, text="导出", command=self.export_records)
        self.export_button.pack(side="left", padx=(8, 4))
        
        self.clear_records_button = ttk.Button(stats_frame, text="清空", width=6, command=self.clear_records)
        self.clear_records_button.pack(side="left")
        
        self.paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        self.paned_window.pack(fill="both", expand=True, pady=(5, 0))
        
        config_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(config_frame, weight=5)
        
        columns_frame = ttk.Frame(config_frame)
        columns_frame.pack(fill="both", expand=True)
        
        left_column = ttk.Frame(columns_frame)
        left_column.pack(side="left", fill="both", expand=True, padx=(0, 12))
        
        right_column = ttk.Frame(columns_frame)
        right_column.pack(side="left", fill="both", expand=True, padx=(12, 0))
        
        # --- 串口设置 ---
        self.port_frame = ttk.Frame(left_column)
        self.port_frame.pack(fill="both", expand=True)
        ttk.Label(self.port_frame, text="串口配置", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['text_primary']).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        
        self.port_comboboxes = []
        self.port_labels = []
        self.port_erase_buttons = []
        self.port_enables = []

        for i in range(8):
            r = i + 1
            self.port_frame.rowconfigure(r, weight=1)
            enable_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(self.port_frame, variable=enable_var, command=self.save_config).grid(row=r, column=0, padx=2, pady=3)
            self.port_enables.append(enable_var)

            lbl = ttk.Label(self.port_frame, text=f"COM {i+1}:", font=('Microsoft YaHei UI', 10), foreground=COLORS['text_primary'])
            lbl.grid(row=r, column=1, padx=4, pady=3, sticky="w")
            self.port_labels.append(lbl)

            cb = ttk.Combobox(self.port_frame, width=16)
            cb.grid(row=r, column=2, padx=4, pady=3, sticky="ew")
            self.port_frame.columnconfigure(2, weight=1)
            self.port_comboboxes.append(cb)

            btn = ttk.Button(self.port_frame, text="擦除", width=6, command=lambda idx=i: self.erase_single_port(idx))
            btn.grid(row=r, column=3, padx=2, pady=3)
            self.port_erase_buttons.append(btn)
        
        self.refresh_button = ttk.Button(self.port_frame, text="刷新列表", command=self.refresh_ports)
        self.refresh_button.grid(row=9, column=0, columnspan=4, pady=12)
        
        # --- 固件设置 ---
        self.firmware_frame = ttk.Frame(right_column)
        self.firmware_frame.pack(fill="both", expand=True)
        ttk.Label(self.firmware_frame, text="固件配置", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['text_primary']).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        
        self.firmware_paths = []
        self.firmware_entries = []
        self.firmware_addresses = []
        self.firmware_enables = []
        
        for i in range(8):
            r = i + 1
            self.firmware_frame.rowconfigure(r, weight=1)
            
            enable_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(self.firmware_frame, variable=enable_var, command=self.save_config).grid(row=r, column=0, padx=2, pady=3)
            self.firmware_enables.append(enable_var)
            
            ttk.Label(self.firmware_frame, text=f"#{i+1}", foreground=COLORS['primary'], font=('', 10, 'bold')).grid(row=r, column=1, padx=2, pady=3)
            
            addr_entry = ttk.Entry(self.firmware_frame, width=9)
            addr_entry.insert(0, "0x0")
            addr_entry.grid(row=r, column=2, padx=4, pady=3)
            self.firmware_addresses.append(addr_entry)
            
            path_var = tk.StringVar()
            entry = ttk.Entry(self.firmware_frame, textvariable=path_var)
            entry.grid(row=r, column=3, padx=4, pady=3, sticky="ew")
            self.firmware_frame.columnconfigure(3, weight=1)
            path_var.trace_add("write", lambda n, idx, m, e=entry: self.root.after(10, lambda: e.xview_moveto(1.0)))
            self.firmware_paths.append(path_var)
            self.firmware_entries.append(entry)
            
            ttk.Button(self.firmware_frame, text="浏览", width=5, command=lambda idx=i: self.browse_firmware(idx)).grid(row=r, column=4, padx=2, pady=3)
        
        # --- 核心烧录参数 ---
        self.address_frame = ttk.Frame(config_frame)
        self.address_frame.pack(fill="x", pady=(18, 5))
        ttk.Label(self.address_frame, text="烧录配置", font=('Microsoft YaHei UI', 11, 'bold'), foreground=COLORS['text_primary']).pack(anchor="w", pady=(0, 8))
        
        settings_frame = ttk.Frame(self.address_frame)
        settings_frame.pack(fill="x")
        
        ttk.Label(settings_frame, text="波特率:").pack(side="left", padx=(0, 4))
        self.baud_rates = ['115200', '230400', '460800', '921600', '1500000', '2000000', '4000000']
        self.baud_combobox = ttk.Combobox(settings_frame, width=10, values=self.baud_rates, state='readonly')
        self.baud_combobox.set('4000000')
        self.baud_combobox.bind('<<ComboboxSelected>>', lambda e: self.save_config())
        self.baud_combobox.pack(side="left", padx=(0, 15))

        ttk.Label(settings_frame, text="模式(Mode):").pack(side="left", padx=(0, 4))
        self.flash_mode_vars = ['keep', 'dio', 'dout', 'qio', 'qout']
        self.flash_mode_cb = ttk.Combobox(settings_frame, width=6, values=self.flash_mode_vars, state='readonly')
        self.flash_mode_cb.set('keep')
        self.flash_mode_cb.bind('<<ComboboxSelected>>', lambda e: self.save_config())
        self.flash_mode_cb.pack(side="left", padx=(0, 15))
        
        ttk.Label(settings_frame, text="频率(Freq):").pack(side="left", padx=(0, 4))
        self.flash_freq_vars = ['keep', '40m', '80m', '120m']
        self.flash_freq_cb = ttk.Combobox(settings_frame, width=6, values=self.flash_freq_vars, state='readonly')
        self.flash_freq_cb.set('keep')
        self.flash_freq_cb.bind('<<ComboboxSelected>>', lambda e: self.save_config())
        self.flash_freq_cb.pack(side="left", padx=(0, 15))
        
        self.erase_flash = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings_frame, text="烧录前擦除", variable=self.erase_flash, command=self.save_config).pack(side="left", padx=(0, 15))
        
        self.auto_flash = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings_frame, text="自动烧录", variable=self.auto_flash, command=self.save_config).pack(side="left", padx=(0, 15))
        
        self.flash_button = tk.Button(
            settings_frame, text="开始烧录", command=self.start_flash,
            bg=COLORS['primary'], fg='white', font=('Microsoft YaHei UI', 11, 'bold'),
            relief='flat', padx=24, pady=5, cursor='hand2', activebackground=COLORS['primary_hover'], activeforeground='white'
        )
        self.flash_button.pack(side="right")
        
        # --- 终端运行日志 ---
        self.log_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(self.log_frame, weight=3)
        
        log_toolbar = ttk.Frame(self.log_frame)
        log_toolbar.pack(fill="x", pady=(5, 5))
        
        self.log_status = ttk.Label(log_toolbar, text="就绪", font=('Microsoft YaHei UI', 10), foreground=COLORS['primary'])
        self.log_status.pack(side="left")
        
        ttk.Button(log_toolbar, text="清空日志", command=self.clear_log, width=10).pack(side="right")
        
        log_text_frame = ttk.Frame(self.log_frame)
        log_text_frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(log_text_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.log_text = tk.Text(
            log_text_frame, 
            height=6,
            yscrollcommand=scrollbar.set,
            font=('Consolas', 10),
            background='#0f172a',
            foreground='#e2e8f0',
            borderwidth=0,
            padx=12,
            pady=12,
            wrap=tk.WORD,
            insertbackground='white'
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill="x", pady=(8, 0))
        ttk.Separator(status_frame, orient='horizontal').pack(fill="x", pady=(0, 6))
        self.status_label = ttk.Label(status_frame, text="版本: v1.0 | 就绪", font=('Microsoft YaHei UI', 9), foreground=COLORS['text_secondary'])
        self.status_label.pack(side="left")
        
        self.refresh_ports()
    def erase_single_port(self, port_index):
        """擦除单个端口的Flash"""
        # 获取选中的端口
        port = self.port_comboboxes[port_index].get()
        if not port:
            messagebox.showwarning("警告", f"端口 {port_index + 1} 未选择串口")
            return

        # 确认擦除操作
        if not messagebox.askyesno("确认", f"确定要擦除端口 {port} 的Flash吗？"):
            return

        self.log(f"🗑️ 开始擦除端口 {port} 的Flash...")

        # 创建或获取日志窗口
        if port not in self.log_windows:
            self.log_windows[port] = LogWindow(port)
        log_window = self.log_windows[port]
        log_window.log(f"开始擦除 {port} 的Flash...")

        # 在新线程中执行擦除
        thread = threading.Thread(
            target=self._erase_flash_thread,
            args=(port, log_window),
            daemon=True
        )
        thread.start()

    def _erase_flash_thread(self, port, log_window):
        """擦除Flash的线程函数"""
        try:
            erase_cmd = [
                "python", "-m", "esptool",
                "--port", port,
                "--baud", self.baud_combobox.get(),
                "erase-flash"
            ]

            log_window.log(f"执行命令: {' '.join(erase_cmd)}")

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            erase_process = subprocess.Popen(
                " ".join(erase_cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                startupinfo=startupinfo,
                shell=True
            )

            for line in erase_process.stdout:
                log_window.log(line.strip())
            erase_process.wait()

            if erase_process.returncode != 0:
                log_window.log(f"❌ 擦除Flash失败，返回码: {erase_process.returncode}")
                self.root.after(0, lambda: messagebox.showerror("错误", f"端口 {port} 擦除Flash失败"))
            else:
                log_window.log("✅ Flash擦除完成!")
                self.root.after(0, lambda: self.log(f"✅ 端口 {port} Flash擦除完成"))

        except Exception as e:
            log_window.log(f"❌ 擦除异常: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"擦除失败: {str(e)}"))

    def refresh_ports(self):
        ports = [port.device for port in list_ports.comports()]
        
        # 清空所有下拉框
        for combobox in self.port_comboboxes:
            combobox.set('')
            combobox['values'] = []
        
        # 为每个检测到的端口设置对应的下拉框
        for i, port in enumerate(ports[:8]):  # 修改为8个端口
            self.port_comboboxes[i]['values'] = [port]
            self.port_comboboxes[i].set(port)

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    # 加载多个固件路径
                    if 'firmware_paths' in self.config:
                        for i, path in enumerate(self.config['firmware_paths']):
                            if i < len(self.firmware_paths):
                                if os.path.exists(path):
                                    self.firmware_paths[i].set(path)
                                    self.root.after(100, lambda idx=i: self.firmware_entries[idx].xview_moveto(1.0))
                                else:
                                    self.firmware_paths[i].set('')
                    # 加载固件地址
                    if 'firmware_addresses' in self.config:
                        for i, addr in enumerate(self.config['firmware_addresses']):
                            if i < len(self.firmware_addresses):
                                self.firmware_addresses[i].delete(0, tk.END)
                                self.firmware_addresses[i].insert(0, addr or '0x0')
                    # 加载固件启用状态
                    if 'firmware_enables' in self.config:
                        for i, enabled in enumerate(self.config['firmware_enables']):
                            if i < len(self.firmware_enables):
                                self.firmware_enables[i].set(enabled)
                    # 加载串口启用状态
                    if 'port_enables' in self.config:
                        for i, enabled in enumerate(self.config['port_enables']):
                            if i < len(self.port_enables):
                                self.port_enables[i].set(enabled)
                    # 加载自动烧录设置
                    if 'auto_flash' in self.config:
                        self.auto_flash.set(self.config['auto_flash'])
                    # 加载波特率设置
                    if 'baudrate' in self.config:
                        self.baud_combobox.set(str(self.config['baudrate']))
                    # 加载擦除Flash设置
                    if 'erase_flash' in self.config:
                        self.erase_flash.set(self.config['erase_flash'])
                    # 加载Flash模式和频率
                    if 'flash_mode' in self.config:
                        self.flash_mode_cb.set(self.config['flash_mode'])
                    if 'flash_freq' in self.config:
                        self.flash_freq_cb.set(self.config['flash_freq'])
            else:
                self.config = {
                    'firmware_paths': [''] * 8,
                    'firmware_addresses': ['0x0'] * 8,
                    'firmware_enables': [False] * 8,
                    'port_enables': [True] * 8,
                    'auto_flash': False,
                    'baudrate': 921600,
                    'erase_flash': False,
                    'flash_mode': 'keep',
                    'flash_freq': 'keep'
                }
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
            self.config = {
                'firmware_paths': [''] * 8,
                'firmware_addresses': ['0x0'] * 8,
                'firmware_enables': [False] * 8,
                'port_enables': [True] * 8,
                'auto_flash': False,
                'baudrate': 921600,
                'erase_flash': False,
                'flash_mode': 'keep',
                'flash_freq': 'keep'
            }

    def save_config(self):
        try:
            self.config['firmware_paths'] = [path.get() for path in self.firmware_paths]
            self.config['firmware_addresses'] = [addr.get() for addr in self.firmware_addresses]
            self.config['firmware_enables'] = [enable.get() for enable in self.firmware_enables]
            self.config['port_enables'] = [enable.get() for enable in self.port_enables]
            self.config['auto_flash'] = self.auto_flash.get()
            self.config['baudrate'] = int(self.baud_combobox.get())
            self.config['erase_flash'] = self.erase_flash.get()
            self.config['flash_mode'] = self.flash_mode_cb.get()
            self.config['flash_freq'] = self.flash_freq_cb.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def browse_firmware(self, index):
        initial_dir = os.path.dirname(self.firmware_paths[index].get()) or os.getcwd()
        filename = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("二进制文件", "*.bin"), ("所有文件", "*.*")]
        )
        if filename:
            self.firmware_paths[index].set(filename)
            # 使用延迟确保在文本更新后滚动到尾部
            self.root.after(50, lambda: self.firmware_entries[index].xview_moveto(1.0))
            self.save_config()

    def start_flash(self):
        # 获取启用的串口
        selected_ports = []
        for i, cb in enumerate(self.port_comboboxes):
            if cb.get() and self.port_enables[i].get():  # 只选择启用的串口
                selected_ports.append(cb.get())
        
        if not selected_ports:
            self.log("错误: 请选择并启用至少一个串口")
            return
        
        # 获取选中的固件和地址
        selected_firmwares = []
        for i in range(8):  # 修改为8个
            if self.firmware_enables[i].get():
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
        
        if not selected_firmwares:
            self.log("错误: 请选择至少一个固件")
            return
        
        # 为每个选中的端口创建烧录线程
        for port in selected_ports:
            thread = threading.Thread(
                target=self.flash_process_multi,
                args=(port, selected_firmwares),
                daemon=True
            )
            thread.start()

    def _run_esptool(self, args, log_window, port=None, cancel_event=None):
        captured_lines = []

        cmd = [sys.executable, "-m", "esptool"] + list(args)
        creationflags = 0
        if os.name == "nt":
            try:
                creationflags = subprocess.CREATE_NO_WINDOW
            except Exception:
                creationflags = 0

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags
        )

        if port:
            self.flash_processes[port] = proc

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("cancelled")

                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.01)
                    continue

                text_line = line.rstrip("\r\n")
                captured_lines.append(text_line)
                try:
                    log_window.window.after(0, lambda t=text_line: log_window.log(t))
                except Exception:
                    pass

            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"esptool exited with code {rc}")
        finally:
            if port:
                try:
                    if self.flash_processes.get(port) is proc:
                        del self.flash_processes[port]
                except Exception:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

        return "\n".join(captured_lines)

    def _release_port(self, port):
        try:
            s = serial.Serial(port=port, baudrate=115200, timeout=0)
            try:
                s.dtr = False
                s.rts = False
            except Exception:
                pass
            s.close()
        except Exception:
            pass

    def flash_process_multi(self, port, firmwares):
        cancel_event = threading.Event()
        self.flash_cancel_events[port] = cancel_event
        log_window = LogWindow(port, on_close=lambda p=port: self.stop_flash(p))
        self.log_windows[port] = log_window
        log_window.window.lift()
        log_window.window.focus_force()

        log_window.log(f"开始为端口 {port} 烧录固件...")
        self.log(f"开始为端口 {port} 烧录固件...")

        chip_type = None
        mac_address = "Unknown"

        try:
            import re

            if cancel_event.is_set():
                raise Exception("cancelled")

            log_window.log("检测芯片类型...")
            output = self._run_esptool(["--port", port, "read-mac"], log_window, port=port, cancel_event=cancel_event)

            output_upper = output.upper()
            if "ESP32-S3" in output_upper or "ESP32S3" in output_upper:
                chip_type = "ESP32-S3"
            elif "ESP32-S2" in output_upper or "ESP32S2" in output_upper:
                chip_type = "ESP32-S2"
            elif "ESP32-C3" in output_upper or "ESP32C3" in output_upper:
                chip_type = "ESP32-C3"
            elif "ESP32-C6" in output_upper or "ESP32C6" in output_upper:
                chip_type = "ESP32-C6"
            elif "ESP32-H2" in output_upper or "ESP32H2" in output_upper:
                chip_type = "ESP32-H2"
            elif "ESP32-P4" in output_upper or "ESP32P4" in output_upper:
                chip_type = "ESP32-P4"
            elif "ESP32-C2" in output_upper or "ESP32C2" in output_upper:
                chip_type = "ESP32-C2"
            elif "ESP32" in output_upper:
                chip_type = "ESP32"

            if not chip_type:
                log_window.log("警告: 未能自动识别芯片类型，将使用通用参数")
                chip_type = "ESP32"

            log_window.log(f"检测到芯片类型: {chip_type}")

            mac_match = re.search(
                r'MAC:\s*([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})',
                output
            )
            if mac_match:
                mac_address = mac_match.group(1)
                log_window.log(f"MAC地址: {mac_address}")

            chip_param = self.get_chip_param(chip_type)
            if not chip_param:
                log_window.log(f"不支持的芯片类型: {chip_type}")
                self.add_flash_record(port, chip_type, mac_address, False, "不支持的芯片类型")
                return

            if self.erase_flash.get():
                log_window.log("正在擦除Flash...")
                self._run_esptool([
                    "--port", port,
                    "--baud", self.baud_combobox.get(),
                    "erase_flash"
                ], log_window, port=port, cancel_event=cancel_event)
                log_window.log("Flash擦除完成!")

            for firmware, address in firmwares:
                if cancel_event.is_set():
                    raise Exception("cancelled")
                flash_args = [
                    "--port", port,
                    "--baud", self.baud_combobox.get(),
                    "--before", "default_reset",
                    "--after", "hard_reset"
                ]
                if self.flash_mode_cb.get() != 'keep':
                    flash_args.extend(["--flash_mode", self.flash_mode_cb.get()])
                if self.flash_freq_cb.get() != 'keep':
                    flash_args.extend(["--flash_freq", self.flash_freq_cb.get()])
                
                flash_args.extend(["write_flash", address, firmware])

                log_window.log(f"执行命令: esptool {' '.join(flash_args)}")
                self._run_esptool(flash_args, log_window, port=port, cancel_event=cancel_event)
                log_window.log(f"端口 {port} 固件 {firmware} 烧录完成!")

            log_window.log(f"端口 {port} 所有固件烧录完成!")
            self.add_flash_record(port, chip_type, mac_address, True, "")
            
            log_window.log("\n✅ 烧录成功！为方便操作，此弹窗将在 3 秒后自动优雅关闭...")
            self.root.after(3000, lambda p=port: self.close_log_window(p))

        except Exception as e:
            error_msg = str(e)
            if "cancelled" in error_msg.lower() or error_msg == "cancelled":
                try:
                    log_window.log(f"端口 {port} 已停止烧录")
                except Exception:
                    pass
                self.log(f"端口 {port} 已停止烧录")
                self._release_port(port)
            else:
                log_window.log(f"端口 {port} 烧录错误: {error_msg}")
                self.log(f"错误: {error_msg}")
                self.add_flash_record(port, chip_type if chip_type else "Unknown", mac_address, False, error_msg)

        finally:
            # 清理取消标志
            try:
                if port in self.flash_cancel_events:
                    del self.flash_cancel_events[port]
            except Exception:
                pass
            try:
                if port in self.flash_processes:
                    del self.flash_processes[port]
            except Exception:
                pass

    def close_log_window(self, port):
        """安全地关闭日志窗口"""
        if port in self.log_windows:
            try:
                self.log_windows[port].destroy()
                del self.log_windows[port]
            except Exception as e:
                self.log(f"关闭日志窗口失败: {str(e)}")

    def stop_flash(self, port=None):
        """停止烧录（port=None 表示停止所有端口）"""
        if port is None:
            for p in list(self.flash_cancel_events.keys()):
                try:
                    self.flash_cancel_events[p].set()
                except Exception:
                    pass
                try:
                    proc = self.flash_processes.get(p)
                    if proc and proc.poll() is None:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            proc.terminate()
                except Exception:
                    pass
                try:
                    self._release_port(p)
                except Exception:
                    pass
            return

        try:
            if port in self.flash_cancel_events:
                self.flash_cancel_events[port].set()
        except Exception:
            pass

        try:
            proc = self.flash_processes.get(port)
            if proc and proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    proc.terminate()
        except Exception:
            pass

        try:
            self._release_port(port)
        except Exception:
            pass

    def on_main_close(self):
        """主窗口关闭：停止所有烧录并关闭所有日志窗口"""
        try:
            self.stop_flash(None)
        except Exception:
            pass

        for port in list(self.log_windows.keys()):
            try:
                self.close_log_window(port)
            except Exception:
                pass

        try:
            self.root.destroy()
        except Exception:
            pass

    def log(self, message):
        """线程安全的日志记录方法，支持彩色日志"""
        def _log():
            try:
                # 配置日志标签颜色
                if not hasattr(self, '_log_tags_configured'):
                    self.log_text.tag_config("info", foreground="#e2e8f0")
                    self.log_text.tag_config("success", foreground="#34d399", font=('Consolas', 10, 'bold'))
                    self.log_text.tag_config("error", foreground="#f87171", font=('Consolas', 10, 'bold'))
                    self.log_text.tag_config("warning", foreground="#fbbf24")
                    self._log_tags_configured = True
                
                # 添加时间戳
                timestamp = time.strftime("%H:%M:%S")
                formatted_msg = f"[{timestamp}] {message}\n"
                
                # 根据消息内容选择标签
                tag = "info"
                if "错误" in message or "失败" in message or "Error" in message:
                    tag = "error"
                    self.update_status("错误")
                elif "警告" in message or "Warning" in message:
                    tag = "warning"
                elif "成功" in message or "完成" in message:
                    tag = "success"
                    self.update_status("完成")
                elif "开始" in message:
                    self.update_status("烧录中...")
                
                self.log_text.insert("end", formatted_msg, tag)
                self.log_text.see("end")
            except Exception:
                pass
        
        # 检查是否在主线程
        try:
            self.root.after(0, _log)
        except Exception:
            # 如果after失败，直接调用（可能在主线程中）
            _log()
    
    def update_status(self, message):
        """更新状态栏信息"""
        def _update():
            try:
                if hasattr(self, 'status_label'):
                    self.status_label.config(text=f"版本: v1.0 | {message}")
                if hasattr(self, 'log_status'):
                    self.log_status.config(text=message)
            except:
                pass
        
        try:
            self.root.after(0, _update)
        except:
            _update()

    def clear_log(self):
        """清除日志内容"""
        self.log_text.delete(1.0, tk.END)
        self.update_status("就绪")

    def get_chip_param(self, chip_type):
        """将检测到的芯片类型转换为对应的参数"""
        chip_map = {
            'ESP32': 'esp32',
            'ESP32-S2': 'esp32s2',
            'ESP32-S3': 'esp32s3',
            'ESP32-C2': 'esp32c2',
            'ESP32-C3': 'esp32c3',
            'ESP32-C6': 'esp32c6',
            'ESP32-H2': 'esp32h2',
            'ESP32-P4': 'esp32p4'
        }
        return chip_map.get(chip_type, 'esp32')  # 默认返回 esp32
    
    def add_flash_record(self, port, chip_type, mac_address, success, error_msg=""):
        """添加烧录记录"""
        import datetime
        time_full = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        time_short = datetime.datetime.now().strftime('%H:%M:%S')
        record = {
            'time': time_full,
            'port': port,
            'chip_type': chip_type,
            'mac_address': mac_address,
            'success': success,
            'error_msg': error_msg
        }
        self.flash_records.append(record)
        
        # 更新右侧历史列表
        status_text = "成功" if success else "失败"
        tag = 'success' if success else 'fail'
        
        def _update_tree():
            try:
                self.history_tree.insert("", 0, values=(time_short, port, mac_address, chip_type, status_text), tags=(tag,))
            except Exception:
                pass
                
        try:
            self.root.after(0, _update_tree)
        except Exception:
            _update_tree()
            
        # 更新统计
        self.flash_total_count += 1
        if success:
            self.flash_success_count += 1
        else:
            self.flash_fail_count += 1
        
        # 更新显示
        self.update_stats()
        
        # 记录到日志
        status = "成功" if success else "失败"
        self.log(f"记录: {port} {chip_type} {mac_address} - {status}")
    
    def update_stats(self):
        """更新统计显示"""
        def _update():
            try:
                self.success_label.config(text=str(self.flash_success_count))
                self.fail_label.config(text=str(self.flash_fail_count))
                self.total_label.config(text=str(self.flash_total_count))
            except:
                pass
        
        try:
            self.root.after(0, _update)
        except:
            _update()
    
    def export_records(self):
        """导出烧录记录到CSV文件"""
        if not self.flash_records:
            messagebox.showinfo("提示", "暂无烧录记录")
            return
        
        try:
            import datetime
            import csv
            from tkinter import filedialog
            
            # 默认文件名
            default_filename = f"烧录记录_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # 选择保存位置
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                initialfile=default_filename,
                filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")]
            )
            
            if not filename:
                return
            
            # 写入CSV文件
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 写入表头
                writer.writerow(['烧录时间', '端口', '芯片型号', 'MAC地址', '状态', '错误信息'])
                # 写入数据
                for record in self.flash_records:
                    status = "成功" if record['success'] else "失败"
                    writer.writerow([
                        record['time'],
                        record['port'],
                        record['chip_type'],
                        record['mac_address'],
                        status,
                        record.get('error_msg', '')
                    ])
            
            self.log(f"记录已导出到: {filename}")
            messagebox.showinfo("成功", f"已导出 {len(self.flash_records)} 条记录到:\n{filename}")
            
        except Exception as e:
            self.log(f"导出记录失败: {str(e)}")
            messagebox.showerror("错误", f"导出记录失败:\n{str(e)}")
    
    def clear_records(self):
        """清空烧录记录"""
        if not self.flash_records:
            messagebox.showinfo("提示", "暂无烧录记录")
            return
        
        if messagebox.askyesno("确认", f"确定要清空所有 {len(self.flash_records)} 条烧录记录吗？"):
            self.flash_records.clear()
            self.flash_success_count = 0
            self.flash_fail_count = 0
            self.flash_total_count = 0
            self.update_stats()
            
            # 清空历史列表
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
                
            self.log("已清空所有烧录记录")

    def check_dependencies(self):
        """检查必要的依赖"""
        try:
            import serial
            import esptool
            return True
        except ImportError as e:
            messagebox.showerror("依赖错误", f"缺少必要的依赖: {str(e)}\n请安装所需的依赖后重试。")
            return False

if __name__ == "__main__":
    root = tk.Tk()
    app = ESP32Flasher(root)
    root.mainloop()