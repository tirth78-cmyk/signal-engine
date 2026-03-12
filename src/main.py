"""
Signal Engine entry point.
"""

import uvicorn
from config.settings import settings


def main():
    """Run the Signal Engine API server."""
    uvicorn.run(
        "src.api.app:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
