from __future__ import annotations

import uvicorn

from .app import GatewayConfig, create_app


def main() -> None:
    config = GatewayConfig()
    uvicorn.run(create_app(config), host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
