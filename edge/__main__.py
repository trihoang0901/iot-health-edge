from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "edge.app:app",
        host=os.getenv("EDGE_HOST", "127.0.0.1"),
        port=int(os.getenv("EDGE_PORT", "8000")),
        workers=1,
    )


if __name__ == "__main__":
    main()
