"""PyInstaller 打包入口：修复 Python 3.10.0 与 esptool 5.x 的兼容问题"""
import sys


def patch_dis_for_python3100():
    if sys.version_info[:3] != (3, 10, 0):
        return
    import dis

    def _unpack_opargs(code):
        extended_arg = 0
        for i in range(0, len(code), 2):
            op = code[i]
            if op >= dis.HAVE_ARGUMENT:
                arg = code[i + 1] | extended_arg
                extended_arg = (arg << 8) if op == dis.EXTENDED_ARG else 0
            else:
                arg = None
                extended_arg = 0
            yield (i, op, arg)

    dis._unpack_opargs = _unpack_opargs


def main():
    patch_dis_for_python3100()

    from PyInstaller.__main__ import run

    run([
        "--name=esp32_flasher",
        "--onefile",
        "--windowed",
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.filedialog",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=tkinter.messagebox",
        "--hidden-import=serial",
        "--hidden-import=serial.tools",
        "--hidden-import=serial.tools.list_ports",
        "--hidden-import=esptool",
        "--hidden-import=esptool.cmds",
        "--hidden-import=esptool.loader",
        "--hidden-import=esptool.util",
        "--hidden-import=esptool.targets",
        "--hidden-import=esptool.targets.esp32",
        "--hidden-import=esptool.targets.esp32s2",
        "--hidden-import=esptool.targets.esp32s3",
        "--hidden-import=esptool.targets.esp32c2",
        "--hidden-import=esptool.targets.esp32c3",
        "--hidden-import=esptool.targets.esp32c6",
        "--hidden-import=esptool.targets.esp32h2",
        "--hidden-import=esptool.targets.esp32p4",
        "--hidden-import=rich",
        "--hidden-import=rich_click",
        "--hidden-import=click",
        "--hidden-import=bitstring",
        "--hidden-import=reedsolo",
        "--hidden-import=yaml",
        "--hidden-import=intelhex",
        "--hidden-import=cryptography",
        "--collect-all=esptool",
        "--collect-all=serial",
        "--collect-all=rich_click",
        "--clean",
        "esp32_flasher.py",
    ])


if __name__ == "__main__":
    main()
