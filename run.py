import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    
    print(f"🚀 Blog-Writer AI Workflow System")
    print(f"   URL: http://{host}:{port}")
    print(f"   Docs: http://{host}:{port}/docs")
    print(f"   Press Ctrl+C to stop")
    print()
    
    uvicorn.run(
        "blog_writer.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
    