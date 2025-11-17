"""简单的端口监控测试脚本"""
import time
from serial.tools import list_ports

print("=" * 50)
print("端口监控测试")
print("=" * 50)
print("请插拔USB设备，观察端口变化...")
print("按 Ctrl+C 退出")
print("=" * 50)

old_ports = set()

try:
    while True:
        # 获取当前端口
        current_ports = set(port.device for port in list_ports.comports())
        
        # 检测新增端口
        new_ports = current_ports - old_ports
        if new_ports:
            print(f"\n✅ 检测到新端口: {list(new_ports)}")
            for port in new_ports:
                info = [p for p in list_ports.comports() if p.device == port]
                if info:
                    print(f"   - {port}: {info[0].description}")
        
        # 检测移除端口
        removed_ports = old_ports - current_ports
        if removed_ports:
            print(f"\n❌ 端口已移除: {list(removed_ports)}")
        
        # 更新端口列表
        old_ports = current_ports
        
        # 每隔1秒检查一次
        time.sleep(1)

except KeyboardInterrupt:
    print("\n\n测试结束")
    print(f"最后检测到的端口: {list(old_ports) if old_ports else '无'}")
