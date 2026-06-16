from redis import Redis
from rq import Queue


def make_queue(redis_url: str = "redis://localhost:6379/0") -> Queue:
    return Queue("quant-trading", connection=Redis.from_url(redis_url))
