"""Run a read-only media probe with bounded output and elapsed time."""

import os
import selectors
import subprocess
import time

from app.importing.filesystem import InspectionError


def probe_output(command, fd, deadline, *, label, seconds=20, max_output=1024 * 1024):
    expires = min(deadline, time.monotonic() + seconds)
    if expires <= time.monotonic():
        raise InspectionError(f"{label} metadata probe timed out")
    output = bytearray()
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        pass_fds=(fd,),
    ) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = expires - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise InspectionError(f"{label} metadata probe timed out")
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        break
                    output.extend(block)
                    if len(output) > max_output:
                        raise InspectionError(f"{label} metadata exceeds the supported size")
            code = process.wait(timeout=max(0.01, expires - time.monotonic()))
            if code:
                raise InspectionError(
                    f"File is not readable as its declared {label.lower()} format"
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return bytes(output)
