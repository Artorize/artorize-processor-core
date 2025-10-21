from __future__ import annotations

import sys
import uvicorn

from .app import GatewayConfig, create_app


def check_python_version() -> None:
    """Verify Python 3.12.x is being used."""
    version_info = sys.version_info
    major, minor = version_info.major, version_info.minor

    if major != 3 or minor != 12:
        error_msg = (
            f"ERROR: Python 3.12.x is required, but you are using Python {major}.{minor}.{version_info.micro}\n"
            f"The blockhash library is not compatible with Python 3.13+.\n"
            f"Please run with: py -3.12 -m artorize_gateway"
        )
        print(error_msg, file=sys.stderr)
        sys.exit(1)

    print(f"✓ Python {major}.{minor}.{version_info.micro} detected - version check passed")


def main() -> None:
    check_python_version()
    config = GatewayConfig()
    uvicorn.run(create_app(config), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
