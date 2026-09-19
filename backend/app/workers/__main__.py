import asyncio

from app.workers.scheduler import run_all_workers


async def periodic_loop(interval_seconds: int = 3600):
    while True:
        try:
            await run_all_workers()
        except Exception as e:
            from app.core.logging import logger
            logger.error("worker_loop_error", error=str(e))
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    asyncio.run(periodic_loop())
