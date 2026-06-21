from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("hpmdt.api.app:app", host="127.0.0.1", port=7869, reload=False)
