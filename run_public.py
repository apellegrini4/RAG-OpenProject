import os
import sys
import threading
import time

import uvicorn
from dotenv import load_dotenv
from pyngrok import conf, ngrok

load_dotenv()

HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))
AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN")
DOMAIN = os.getenv("NGROK_DOMAIN") or None


def start_api():
    uvicorn.run("api:app", host=HOST, port=PORT, log_level="info")


def main():
    if not AUTHTOKEN:
        sys.exit("NGROK_AUTHTOKEN non impostato in .env")

    conf.get_default().auth_token = AUTHTOKEN

    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()
    time.sleep(2)

    tunnel = ngrok.connect(addr=PORT, domain=DOMAIN) if DOMAIN else ngrok.connect(addr=PORT)

    print(f"middleware: {tunnel.public_url}")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        ngrok.disconnect(tunnel.public_url)
        ngrok.kill()


if __name__ == "__main__":
    main()
