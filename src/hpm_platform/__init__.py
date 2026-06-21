"""HPM 数字化电磁算法 CAE：归一化数值研究平台。"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

__version__ = "1.4.0"
