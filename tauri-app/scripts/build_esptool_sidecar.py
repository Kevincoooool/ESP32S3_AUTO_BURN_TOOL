"""Build esptool as a standalone console exe for Tauri externalBin sidecar."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def patch_dis_for_python3100() -> None:
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


def target_triple() -> str:
    try:
        out = subprocess.check_output(
            ["rustc", "--print", "host-tuple"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (OSError, subprocess.CalledProcessError):
        if sys.platform == "win32":
            return "x86_64-pc-windows-msvc"
        if sys.platform == "darwin":
            return "aarch64-apple-darwin"
        return "x86_64-unknown-linux-gnu"


def main() -> None:
    patch_dis_for_python3100()

    script_dir = Path(__file__).resolve().parent
    tauri_dir = script_dir.parent
    src_tauri = tauri_dir / "src-tauri"
    binaries_dir = src_tauri / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = tauri_dir / "dist-esptool"
    work_dir = tauri_dir / "build-esptool"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)

    from PyInstaller.__main__ import run

    entry = script_dir / "esptool_sidecar.py"
    run(
        [
            f"--name=esptool",
            "--onefile",
            "--console",
            f"--distpath={dist_dir}",
            f"--workpath={work_dir}",
            f"--specpath={work_dir}",
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
            "--hidden-import=serial",
            "--hidden-import=serial.tools",
            "--hidden-import=serial.tools.list_ports",
            "--collect-all=esptool",
            "--collect-all=rich_click",
            "--clean",
            "--noconfirm",
            str(entry),
        ]
    )

    ext = ".exe" if sys.platform == "win32" else ""
    built = dist_dir / f"esptool{ext}"
    if not built.exists():
        raise SystemExit(f"PyInstaller output not found: {built}")

    triple = target_triple()
    dest = binaries_dir / f"esptool-{triple}{ext}"
    shutil.copy2(built, dest)
    print(f"Sidecar ready: {dest}")

    version = subprocess.check_output(
        [str(dest), "version"],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()
    print(f"Verified: {version}")


if __name__ == "__main__":
    main()
