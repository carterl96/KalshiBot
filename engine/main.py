"""Entry point: run the FastAPI engine with uvicorn.

    python -m engine.main      # or: uvicorn engine.api.server:app
"""

from __future__ import annotations

import logging

import uvicorn

from engine.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    uvicorn.run(
        "engine.api.server:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
