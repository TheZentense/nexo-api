"""Crea una clave local una sola vez y la guarda fuera de Git."""

import secrets
from pathlib import Path


def main():
    path = Path(__file__).resolve().parents[1] / ".local" / "jwt.key"
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(secrets.token_urlsafe(48))
    except FileExistsError:
        print("Existing local JWT key kept.")
    else:
        print("Local JWT key created. Keep .local/jwt.key private.")


if __name__ == "__main__":
    main()
