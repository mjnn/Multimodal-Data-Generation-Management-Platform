"""示例脚本共用的小工具（一般不用单独运行本文件）。

作用
    1. 统一解析输入 bag 路径、输出目录
    2. 安全加载 .env（尽量兼容 utf-8 / gbk，避免编码错误直接崩溃）
    3. 读取 MODEL_BACKEND=api|mc
"""
from __future__ import annotations

import os
from pathlib import Path

# examples/ → piplinesdk/ → 仓库根目录
_EXAMPLES = Path(__file__).resolve().parent
SDK_ROOT = _EXAMPLES.parent
REPO_ROOT = SDK_ROOT.parent


def default_bag() -> Path:
    """返回要处理的 .bag 路径。

    优先使用环境变量 BAG_PATH；
    否则尝试仓库内一份样例路径（若你的仓库里没有该文件，请自行设置 BAG_PATH）。
    """
    env = os.environ.get("BAG_PATH", "").strip()
    if env:
        return Path(env)
    return (
        REPO_ROOT
        / "hmi"
        / "data"
        / "hmi_runtime"
        / "oss"
        / "rosbags"
        / "output"
        / "output.bag"
    )


def default_run_out(name: str) -> Path:
    """返回本次示例的输出目录。

    优先使用环境变量 RUN_OUT；
    否则写到 examples/_out/<name>/。
    """
    return Path(os.environ.get("RUN_OUT") or (_EXAMPLES / "_out" / name))


def safe_load_dotenv() -> Path | None:
    """加载 .env 到进程环境变量，失败时尽量换编码重试。

    查找顺序：
      1) piplinesdk/.env
      2) 仓库根目录 /.env

    返回实际加载成功的文件路径；都没有则返回 None。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        # 未安装 python-dotenv 时跳过；调用方可依赖系统已有环境变量
        return None

    for path in (SDK_ROOT / ".env", REPO_ROOT / ".env"):
        if not path.is_file():
            continue
        # 常见编码依次尝试
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                load_dotenv(path, encoding=enc, override=False)
                return path
            except UnicodeDecodeError:
                continue
            except TypeError:
                # 极老版本 dotenv 可能不支持 encoding= 参数：先转成 utf-8 临时文件再加载
                try:
                    text = path.read_text(encoding=enc)
                except UnicodeDecodeError:
                    continue
                tmp = _EXAMPLES / "_out" / f".env.decoded.{enc}"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(text, encoding="utf-8")
                load_dotenv(tmp, override=False)
                return path
    return None


def model_backend() -> str:
    """读取 MODEL_BACKEND，只允许 api 或 mc。

    api —— 阿里云百炼（DashScope）HTTP 接口，本机试用默认
    mc  —— 阿里云 MaxCompute / MaxFrame AI，进阶用法
    """
    raw = (os.environ.get("MODEL_BACKEND") or "api").strip().lower()
    if raw not in {"api", "mc"}:
        raise SystemExit(f"MODEL_BACKEND 只能是 api 或 mc，当前是: {raw!r}")
    return raw
