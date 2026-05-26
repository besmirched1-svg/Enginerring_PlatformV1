import logging
from fastapi import FastAPI
from app.api.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("engine.main")

app = FastAPI(
    title="OpenSCAD Autonomous Engineering Intelligence Platform",
    version="1.0.0"
)

# Include the optimization routes under the global context matrix
app.include_router(router)

@app.get("/health")
def health_check():
    return {"status": "healthy", "engine": "operational"}
