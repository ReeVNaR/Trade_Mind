import os
import uvicorn
from api.main import app

if __name__ == "__main__":
    # Render provides PORT environment variable
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=False)
