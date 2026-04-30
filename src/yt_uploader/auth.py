import argparse
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time OAuth flow for YouTube upload. Run on a machine with a browser, "
        "then copy the resulting token.json to the mini PC."
    )
    parser.add_argument("client_secret", help="Path to client_secret.json downloaded from Google Cloud")
    parser.add_argument("token_out", help="Where to write token.json")
    parser.add_argument("--port", type=int, default=0, help="Local port for OAuth callback (0 = random)")
    args = parser.parse_args()

    client_secret = Path(args.client_secret)
    if not client_secret.exists():
        print(f"client_secret not found at {client_secret}", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(
        port=args.port,
        prompt="consent",
        access_type="offline",
        open_browser=True,
    )

    token_out = Path(args.token_out)
    token_out.parent.mkdir(parents=True, exist_ok=True)
    token_out.write_text(creds.to_json())
    token_out.chmod(0o600)
    print(f"Token saved to {token_out}")
    print("Copy this file to the mini PC at the path configured in config.toml.")


if __name__ == "__main__":
    main()
