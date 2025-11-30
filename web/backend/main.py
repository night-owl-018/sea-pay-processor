import os
import subprocess
import asyncio
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

ROOT = Path(__file__).parent.parent
APP = ROOT.parent / "app.py"

INPUT = os.environ.get("SEA_PAY_INPUT", "/inputs")
OUTPUT = os.environ.get("SEA_PAY_OUTPUT", "/outputs")
TEMPLATE = os.environ.get("SEA_PAY_TEMPLATE", "/templates/NAVPERS_1070_613_TEMPLATE.pdf")


# -----------------------
# HOME PAGE
# -----------------------

@app.get("/")
def home():
    return HTMLResponse(open(ROOT / "frontend" / "index.html").read())


# -----------------------
# RUN JOB
# -----------------------

@app.post("/run")
def run_job():
    env = dict(os.environ)

    cmd = ["python", str(APP)]

    subprocess.Popen(cmd, env=env)
    return {"status": "RUNNING"}


# -----------------------
# WEBSOCKET LOG STREAM
# -----------------------

clients = []


@app.websocket("/logs")
async def logs(ws: WebSocket):
    await ws.accept()
    clients.append(ws)

    try:
        while True:
            await asyncio.sleep(1)
    except:
        clients.remove(ws)


# -----------------------
# LOG RELAY (TAIL STDOUT)
# -----------------------

async def tail_logs():
    process = await asyncio.create_subprocess_exec(
        "tail", "-F", "stdout.log",
        stdout=asyncio.subprocess.PIPE
    )

    async for line in process.stdout:
        for ws in clients:
            await ws.send_text(line.decode())


@app.on_event("startup")
async def start_tail():
    asyncio.create_task(tail_logs())


# -----------------------
# STATIC FILES
# -----------------------

app.mount("/", StaticFiles(directory=ROOT / "frontend"), name="ui")

