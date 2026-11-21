import uvicorn

from .config import get_settings


def main() -> None:
    cfg = get_settings()
    uvicorn.run("formproof.app:app", host=cfg.host, port=cfg.port, log_level=cfg.log_level, proxy_headers=False)


if __name__ == "__main__":
    main()
