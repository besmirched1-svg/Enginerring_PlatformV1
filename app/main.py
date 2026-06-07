import os
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from socketio import ASGIApp
from app.realtime.events import sio

# Configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
UPLOADS_DIR = os.path.join(BASE_DIR, "workspace", "uploads")

app = FastAPI()

# Mount Static Assets
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

@app.get("/")
async def get_dashboard():
    return FileResponse("dashboard.html")

@app.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    saved = []
    for file in files:
        path = os.path.join(UPLOADS_DIR, file.filename)
        with open(path, "wb") as buffer:
            buffer.write(await file.read())
        saved.append(file.filename)
    return {"status": "ok", "files": saved}

# Bridge for Socket.IO
socket_app = ASGIApp(sio, other_asgi_app=app)