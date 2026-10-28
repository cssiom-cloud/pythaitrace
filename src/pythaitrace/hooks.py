"""
PyThaiTrace v2.0 - Exception Hooks & Failsafe Shield (hooks.py)
Unified hook coordination across main thread, worker threads, and asyncio event loops.
"""
from __future__ import annotations
import os
import sys
import threading
from typing import Any, Optional

_HOOK_LOCK = threading.RLock()
_TARGET_SCRIPT: Optional[str] = None


def clean_traceback(tb: Any, target_script: Optional[str] = None) -> Any:
    """
    Strips internal pythaitrace runner frames from the top of the traceback,
    ensuring authentic error output starting from user code.
    """
    if tb is None:
        return None
    curr = tb
    if target_script:
        try:
            target_abs = os.path.normcase(os.path.abspath(target_script))
        except Exception:
            target_abs = ""
        while curr is not None:
            try:
                frame = getattr(curr, "tb_frame", None)
                code = getattr(frame, "f_code", None)
                raw_fn = getattr(code, "co_filename", None)
                if raw_fn:
                    fn = os.path.normcase(os.path.abspath(raw_fn))
                    if fn == target_abs:
                        return curr
            except Exception:
                pass
            curr = curr.tb_next
        # Fallback if target_script not matched (e.g. dynamic code or mismatch)
        curr = tb
        while curr is not None:
            frame = getattr(curr, "tb_frame", None)
            code = getattr(frame, "f_code", None)
            fn = getattr(code, "co_filename", "") or ""
            if isinstance(fn, str) and fn and "pythaitrace" in fn and ("runner.py" in fn or "hooks.py" in fn or "cli.py" in fn):
                curr = curr.tb_next
            else:
                return curr
        return tb
    else:
        # Strip internal pythaitrace runner and hook frames
        while curr is not None:
            frame = getattr(curr, "tb_frame", None)
            code = getattr(frame, "f_code", None)
            fn = getattr(code, "co_filename", "") or ""
            if isinstance(fn, str) and fn and "pythaitrace" in fn and ("runner.py" in fn or "hooks.py" in fn or "cli.py" in fn):
                curr = curr.tb_next
            else:
                return curr
        return tb


def configure_streams() -> None:
    """Ensure standard IO streams use UTF-8 and replace unencodable characters."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                try:
                    stream.reconfigure(errors="replace")
                except Exception:
                    pass


def _dispatch_diagnostic(exc: BaseException, thread_name: Optional[str] = None) -> None:
    """
    Encapsulated Failsafe Shield for PyThaiTrace Diagnostic Pipeline.
    Guarantees zero-crash execution: any internal failure is silently trapped.
    """
    try:
        from pythaitrace.normalizer import normalize_exception
        from pythaitrace.matcher import MatcherEngine
        from pythaitrace.renderer import ResponsiveRenderer

        norm_tb = normalize_exception(exc)
        engine = MatcherEngine()
        card = engine.match(norm_tb, exc=exc)
        renderer = ResponsiveRenderer()
        renderer.render(card)
    except BaseException as failsafe_err:
        if os.environ.get("PYTHAITRACE_DEBUG") == "1":
            if sys.stderr is not None and hasattr(sys.stderr, "write"):
                sys.stderr.write(f"\n[PyThaiTrace Internal Error: {failsafe_err}]\n")
            if sys.stderr is not None and hasattr(sys.stderr, "flush"):
                sys.stderr.flush()


def main_excepthook(exc_type: type, exc_value: BaseException, exc_tb: Any) -> None:
    """
    sys.excepthook interceptor for unhandled main-thread exceptions.
    Prints authentic English traceback to stderr first, then renders Thai card.
    Bypasses on KeyboardInterrupt and SystemExit.
    """
    if exc_type is not None and isinstance(exc_type, type) and issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    with _HOOK_LOCK:
        clean_tb = clean_traceback(exc_tb, _TARGET_SCRIPT)
        if exc_value is not None:
            try:
                exc_value.__traceback__ = clean_tb
            except Exception:
                pass

            # Clean cause/context chain tracebacks as well
            curr_exc: Optional[BaseException] = exc_value
            visited = set()
            while curr_exc is not None and id(curr_exc) not in visited:
                visited.add(id(curr_exc))
                tb_attr = getattr(curr_exc, "__traceback__", None)
                if tb_attr is not None:
                    try:
                        curr_exc.__traceback__ = clean_traceback(tb_attr, _TARGET_SCRIPT)
                    except Exception:
                        pass
                curr_exc = getattr(curr_exc, "__cause__", None) or getattr(curr_exc, "__context__", None)

        # 1. Print authentic native English traceback
        sys.__excepthook__(exc_type, exc_value, clean_tb)
        if sys.stderr is not None and hasattr(sys.stderr, "flush"):
            sys.stderr.flush()

        # 2. Render Thai diagnostic card via failsafe shield
        if exc_value is not None:
            _dispatch_diagnostic(exc_value)


def thread_excepthook(args: threading.ExceptHookArgs) -> None:
    """
    threading.excepthook interceptor for unhandled worker thread exceptions.
    Thread-safe locking ensures no interleaved stderr output.
    """
    if args.exc_type is not None and isinstance(args.exc_type, type) and issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        threading.__excepthook__(args)
        return

    with _HOOK_LOCK:
        # 1. Authentic thread exception output
        threading.__excepthook__(args)
        if sys.stderr is not None and hasattr(sys.stderr, "flush"):
            sys.stderr.flush()

        # 2. Render Thai diagnostic card
        exc = args.exc_value
        if exc is None and args.exc_type is not None:
            try:
                exc = args.exc_type()
            except Exception:
                exc = None
        if exc is not None:
            thread_name = args.thread.name if args.thread else None
            _dispatch_diagnostic(exc, thread_name=thread_name)


def install_asyncio_hook(loop: Any = None) -> None:
    """
    Attaches exception handler directly to asyncio event loop without
    using deprecated loop policies.
    """
    import asyncio
    if loop is None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    def asyncio_handler(loop_obj: Any, context: dict) -> None:
        with _HOOK_LOCK:
            loop_obj.default_exception_handler(context)
            if sys.stderr is not None and hasattr(sys.stderr, "flush"):
                sys.stderr.flush()
            exc = context.get("exception")
            if exc is not None:
                _dispatch_diagnostic(exc)

    loop.set_exception_handler(asyncio_handler)


def install_hooks(target_script: Optional[str] = None) -> None:
    """
    Installs sys.excepthook and threading.excepthook, sets UTF-8 stream encoding,
    and configures the target script path for frame stripping.
    """
    global _TARGET_SCRIPT
    _TARGET_SCRIPT = target_script
    configure_streams()
    sys.excepthook = main_excepthook
    threading.excepthook = thread_excepthook
