import os
import sys
import uvicorn
from web.app import app

if __name__ == "__main__":
    port_env = os.getenv("PORT", "8000")
    try:
        port = int(port_env)
    except ValueError:
        port = 8000
        
    print(f"\n==========================================")
    print(f"--> Starting FXDiary on 0.0.0.0:{port}...")
    print(f"==========================================\n")
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, log_level="info")
