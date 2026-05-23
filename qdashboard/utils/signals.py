"""Signal handling utilities."""

import signal


class SignalDisabler:
    """Context manager that temporarily disables signal handler registration.

    Some libraries (e.g. qibolab, qibocal) install signal handlers during
    import or initialisation which can conflict with the asyncio event loop
    running inside Uvicorn. Wrapping those calls with this context manager
    suppresses the ``signal.signal()`` calls without affecting the rest of
    the signal machinery.
    """

    def __enter__(self):
        self._orig = signal.signal
        signal.signal = lambda sig, handler: None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.signal = self._orig
