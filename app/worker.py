import os
import time
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    print("Worker connected to Redis at", REDIS_HOST, REDIS_PORT)

    while True:
        # placeholder loop – later we’ll hook this into your SCAD job queue
        time.sleep(5)
        print("Worker heartbeat: alive")

if __name__ == "__main__":
    main()
