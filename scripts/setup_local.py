"""Create missing local configuration without replacing existing database credentials."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / ".env"
    content = path.read_text(encoding="utf-8") if path.exists() else (ROOT / ".env.example").read_text(encoding="utf-8")
    lines = content.splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
    additions = {"AUTH_USERNAME": "owner", "AUTH_PASSWORD": secrets.token_urlsafe(32),
                 "ALLOWED_HOSTS": "localhost,127.0.0.1", "DEPLOYMENT_MODE": "local"}
    for key, value in additions.items():
        if not values.get(key):
            lines = [line for line in lines if not line.startswith(key + "=")]
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Local configuration ready. Sign-in credentials are in .env (AUTH_USERNAME / AUTH_PASSWORD). Keep this file private.")


if __name__ == "__main__":
    main()
