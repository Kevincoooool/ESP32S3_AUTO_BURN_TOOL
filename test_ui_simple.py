"""简单UI测试 - 验证按钮和窗口显示"""
import tkinter as tk
from tkinter import ttk

# 配色
COLORS = {
    'primary': '#2563eb',
    'bg_main': '#f8fafc',
    'bg_secondary': '#ffffff',
    'text_primary': '#1e293b',
}

def test_ui():
    root = tk.Tk()
    root.title("UI显示测试")
    root.geometry("600x500")
    root.configure(bg=COLORS['bg_main'])
    
    # 创建样式
    style = ttk.Style()
    try:
        style.theme_use('vista')
    except:
        try:
            style.theme_use('winnative')
        except:
            pass
    
    # 简化的按钮样式
    style.configure('TButton', 
        font=('Microsoft YaHei UI', 11),
        padding=(15, 8)
    )
    
    style.configure('Accent.TButton', 
        font=('Microsoft YaHei UI', 11, 'bold'),
        padding=(15, 10)
    )
    
    # 简化的标签框样式
    style.configure('TLabelframe', 
        font=('Microsoft YaHei UI', 11)
    )
    style.configure('TLabelframe.Label', 
        font=('Microsoft YaHei UI', 11, 'bold')
    )
    
    # 主框架
    main_frame = ttk.Frame(root, padding=15)
    main_frame.pack(fill="both", expand=True)
    
    # 标题
    title = ttk.Label(
        main_frame,
        text="UI 显示测试",
        font=('Microsoft YaHei UI', 16, 'bold')
    )
    title.pack(pady=10)
    
    # 按钮测试区域
    button_frame = ttk.LabelFrame(main_frame, text="按钮测试", padding=10)
    button_frame.pack(fill="x", pady=10)
    
    # 普通按钮
    btn1 = ttk.Button(
        button_frame,
        text="普通按钮 (TButton)",
        command=lambda: print("普通按钮被点击")
    )
    btn1.pack(pady=5)
    
    # 强调按钮
    btn2 = ttk.Button(
        button_frame,
        text="强调按钮 (Accent.TButton)",
        style='Accent.TButton',
        command=lambda: print("强调按钮被点击")
    )
    btn2.pack(pady=5)
    
    # 标准按钮
    btn3 = tk.Button(
        button_frame,
        text="标准 tk.Button (作为对比)",
        command=lambda: print("tk按钮被点击"),
        font=('Microsoft YaHei UI', 11),
        padx=15,
        pady=8
    )
    btn3.pack(pady=5)
    
    # 日志窗口测试
    log_frame = ttk.LabelFrame(main_frame, text="日志窗口测试", padding=10)
    log_frame.pack(fill="both", expand=True, pady=10)
    
    # 工具栏
    toolbar = ttk.Frame(log_frame)
    toolbar.pack(fill="x", pady=(0, 5))
    
    status_label = ttk.Label(toolbar, text="状态: 就绪")
    status_label.pack(side="left")
    
    clear_btn = ttk.Button(toolbar, text="清除", command=lambda: log_text.delete(1.0, tk.END))
    clear_btn.pack(side="right")
    
    # 文本框
    text_frame = ttk.Frame(log_frame)
    text_frame.pack(fill="both", expand=True)
    
    scrollbar = ttk.Scrollbar(text_frame)
    scrollbar.pack(side="right", fill="y")
    
    log_text = tk.Text(
        text_frame,
        height=10,
        yscrollcommand=scrollbar.set,
        font=('Consolas', 10),
        background=COLORS['bg_secondary'],
        foreground=COLORS['text_primary'],
        padx=10,
        pady=10
    )
    log_text.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=log_text.yview)
    
    # 添加测试日志
    log_text.insert("end", "✅ 如果你能看到这条消息，说明日志窗口正常显示\n")
    log_text.insert("end", "✅ 如果上面的按钮都能看到，说明按钮显示正常\n")
    log_text.insert("end", "\n请测试点击按钮，查看控制台输出\n")
    
    # 状态栏
    status_frame = ttk.Frame(main_frame)
    status_frame.pack(fill="x", pady=(5, 0))
    
    separator = ttk.Separator(status_frame, orient='horizontal')
    separator.pack(fill="x", pady=(0, 5))
    
    status_info = ttk.Label(
        status_frame,
        text="测试版本: v1.0 | 所有组件应该都能正常显示",
        font=('Microsoft YaHei UI', 9)
    )
    status_info.pack(side="left")
    
    root.mainloop()

if __name__ == "__main__":
    print("=" * 50)
    print("UI 显示测试程序")
    print("=" * 50)
    print("如果窗口打开后：")
    print("1. 能看到3个按钮（2个ttk按钮 + 1个tk按钮）")
    print("2. 能看到日志窗口和其中的文字")
    print("3. 能点击按钮并在控制台看到输出")
    print("说明UI显示正常！")
    print("=" * 50)
    test_ui()
