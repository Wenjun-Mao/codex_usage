"""ID-correlated native OOPIF replies with one bounded asynchronous lifetime."""
import asyncio
import json
import time


class NativeCDP:
    def __init__(self, session, session_id, deadline):
        self.session, self.session_id, self.deadline = session, session_id, deadline
        self.sequence, self.pending, self.waiters, self.closed = 0, {}, {}, False
        session.on("Target.receivedMessageFromTarget", self._received)
        session.on("Target.detachedFromTarget", self._detached)
        session.on("close", self._closed)

    def _received(self, event):
        if event.get("sessionId") != self.session_id:
            return
        message = json.loads(event["message"])
        future = self.pending.get(message.get("id"))
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(RuntimeError(f"Native iframe CDP: {message['error']}"))
        else:
            future.set_result(message.get("result", {}))

    def _detached(self, event):
        if event.get("sessionId") == self.session_id:
            self._closed()

    def _closed(self, *_):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        for task in self.waiters.values():
            task.cancel()

    async def send(self, method, params=None):
        if self.closed:
            raise RuntimeError("Native iframe CDP session is closed")
        stop = min(self.deadline, time.monotonic() + 5)
        remaining = stop - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Native iframe CDP {method} deadline expired")
        self.sequence += 1
        identity = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        acknowledgment = asyncio.create_task(self.session.send("Target.sendMessageToTarget", {
            "sessionId": self.session_id,
            "message": json.dumps({"id": identity, "method": method, "params": params or {}})}))
        self.waiters[identity] = acknowledgment
        if self.closed:
            acknowledgment.cancel()
        try:
            async with asyncio.timeout(remaining):
                await acknowledgment
                # A stored reply cannot bypass a deadline after a slow outer ACK.
                if time.monotonic() >= stop:
                    raise TimeoutError(f"Native iframe CDP {method} deadline expired")
                result = await future
                if time.monotonic() >= stop:
                    raise TimeoutError(f"Native iframe CDP {method} deadline expired")
                return result
        except TimeoutError as error:
            raise TimeoutError(f"Native iframe CDP {method} did not respond by its deadline") from error
        finally:
            self.pending.pop(identity, None)
            self.waiters.pop(identity, None)
            if not acknowledgment.done():
                acknowledgment.cancel()
                await asyncio.gather(acknowledgment, return_exceptions=True)
            elif not acknowledgment.cancelled():
                acknowledgment.exception()
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def close(self):
        was_closed = self.closed
        self._closed()
        try:
            if not was_closed:
                async with asyncio.timeout(5):
                    await self.session.send("Target.detachFromTarget", {"sessionId": self.session_id})
        finally:
            async with asyncio.timeout(5):
                await self.session.detach()
