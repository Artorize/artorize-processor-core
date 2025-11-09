from __future__ import annotations

import logging
import sys
import uvicorn

from .app import GatewayConfig, create_app


def setup_logging() -> None:
    """
    Configure comprehensive logging for system service deployment.

    Logs are formatted with timestamp, level, logger name, and message.
    All logs go to stdout/stderr which are captured by systemd and
    written to /var/log/artorize/gateway.log and gateway-error.log
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Set uvicorn logging to INFO to capture server events
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


def check_python_version() -> None:
    """Verify Python 3.12.x is being used."""
    logger = logging.getLogger(__name__)
    version_info = sys.version_info
    major, minor = version_info.major, version_info.minor

    if major != 3 or minor != 12:
        error_msg = (
            f"ERROR: Python 3.12.x is required, but you are using Python {major}.{minor}.{version_info.micro}\n"
            f"The blockhash library is not compatible with Python 3.13+.\n"
            f"Please run with: py -3.12 -m artorize_gateway"
        )
        logger.error(error_msg)
        sys.exit(1)

    logger.info(f"Python {major}.{minor}.{version_info.micro} detected - version check passed")


def main() -> None:
    setup_logging()
    check_python_version()

    logger = logging.getLogger(__name__)
    logger.info("Starting Artorize Gateway server")

    config = GatewayConfig()
    logger.info(f"Server configuration: host=127.0.0.1, port=8765, workers={config.worker_concurrency}")

    uvicorn.run(create_app(config), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
