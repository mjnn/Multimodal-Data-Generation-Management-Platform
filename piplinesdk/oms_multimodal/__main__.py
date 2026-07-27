"""允许 ``python -m oms_multimodal`` 调用 CLI（无需 PATH 中的 oms-multimodal.exe）。"""
from oms_multimodal.cli import main

if __name__ == "__main__":
    main()
