from typing import Any


def make_queue(redis_url: str = "redis://localhost:6379/0") -> Any:
    from redis import Redis
    from rq import Queue

    return Queue("quant-trading", connection=Redis.from_url(redis_url))
