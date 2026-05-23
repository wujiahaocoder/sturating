"""学生成绩评级系统 — 启动器 (源码版, 23:27 稳定基线)

双击运行 -> 启动 Streamlit 服务器 -> 打开浏览器 -> 关闭窗口停止服务

不依赖 PyInstaller，直接 python launcher.py 或双击 .bat
"""

import os, sys, subprocess, webbrowser, time, platform

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app.py")
PORT = 8501


def main():
    print("=" * 60)
    print("  学生成绩评级系统 — 23:27 稳定版")
    print("=" * 60)
    print(f"  数据目录: {BASE_DIR}")
    print(f"  端口:      {PORT}")
    print(f"  数据库:    student_rating.db")
    print(f"  Python:    {sys.executable}")
    sys.stdout.flush()

    cmd = [
        sys.executable, "-m", "streamlit", "run", APP_PATH,
        "--server.port", str(PORT),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--server.maxUploadSize", "200",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]

    kw = {}
    if platform.system() == "Windows":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kw,
    )

    print("  正在启动服务器...")
    print(f"  http://localhost:{PORT}")
    print("  (Ctrl+C 或关闭窗口停止)")
    print("=" * 60)
    sys.stdout.flush()

    deadline = time.time() + 60
    while time.time() < deadline:
        ret = proc.poll()
        if ret is not None:
            output = ""
            try:
                out = proc.stdout.read()
                if out:
                    output = out
            except Exception:
                pass
            print(f"\n[错误] 进程异常退出 (code {ret})")
            print(output)
            input("按 Enter 退出...")
            return
        time.sleep(1)

    webbrowser.open(f"http://localhost:{PORT}")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    print("\n  已停止。")


if __name__ == "__main__":
    main()
