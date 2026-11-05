"""Request-local ownership, including generators resumed on worker threads."""
from contextvars import ContextVar
from functools import wraps
from inspect import isgeneratorfunction

owner_conversation = ContextVar("project_owner_conversation", default=None)


def owned_request(function):
    def owner(kwargs):
        route = kwargs.get("route") or {}
        for key in ("object_memory", "retrieved_memory"):
            value = route.get(key) or {}
            if value.get("conversation_id"):
                return str(value["conversation_id"])
        return None

    if isgeneratorfunction(function):
        @wraps(function)
        def stream(*args, **kwargs):
            iterator = function(*args, **kwargs)
            try:
                while True:
                    token = owner_conversation.set(owner(kwargs))
                    try:
                        value = next(iterator)
                    except StopIteration:
                        return
                    finally:
                        owner_conversation.reset(token)
                    yield value
            finally:
                iterator.close()
        return stream

    @wraps(function)
    def call(*args, **kwargs):
        token = owner_conversation.set(owner(kwargs))
        try:
            return function(*args, **kwargs)
        finally:
            owner_conversation.reset(token)
    return call
