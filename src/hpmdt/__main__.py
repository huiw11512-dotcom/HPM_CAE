from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("hpmdt.api.app:app", host="127.0.0.1", port=7869, reload=False)


if __name__ == "__main__":
    main()
