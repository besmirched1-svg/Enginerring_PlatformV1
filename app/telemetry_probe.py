import asyncio
from app.realtime.events import emit_optimizer_event

async def _startup_probe():
    try:
        await emit_optimizer_event("mutation", {
            "probe": True,
            "message": "optimizer telemetry channel online"
        })
    except Exception as e:
        print(f"[telemetry probe error] {e}")

def schedule_telemetry_probe(loop: asyncio.AbstractEventLoop):
    loop.create_task(_startup_probe())
