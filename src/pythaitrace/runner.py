"""
PyThaiTrace v2.0 - Script Execution Engine (runner.py)
Pre-compilation checking, environment sanitization, and transparent script execution.
"""
from __future__ import annotations
import builtins
import os
import sys
import types
from typing import List, Optional

from pythaitrace.hooks import install_hooks, _dispatch_diagnostic, clean_traceback


def run_script(script_path: str, script_args: Optional[List[str]] = None) -> int:
    """
    Executes target script transparently with pre-compilation checking,
    runner frame stripping, and exit code preservation.

    Returns exit code (0 on success, N on sys.exit(N), 1 on error/SyntaxError, 130 on SIGINT).
    """
    if script_args is None:
        script_args = []

    abs_path = os.path.abspath(script_path)
    if not os.path.isfile(abs_path):
        if sys.stderr is not None and hasattr(sys.stderr, "write"):
            sys.stderr.write(f"Error: Script '{script_path}' not found.\n")
        if sys.stderr is not None and hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        return 1

    # 1. Install execution hooks
    install_hooks(target_script=abs_path)

    # 2. Ingest source code in binary mode (PEP 263 encoding resilience)
    try:
        with open(abs_path, "rb") as f:
            source_bytes = f.read()
    except Exception as read_err:
        if sys.stderr is not None and hasattr(sys.stderr, "write"):
            sys.stderr.write(f"Error reading '{script_path}': {read_err}\n")
        if sys.stderr is not None and hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        return 1

    # 3. Pre-execution Compilation Check
    try:
        code_obj = compile(source_bytes, abs_path, "exec")
    except SyntaxError as syn_err:
        # Strip runner frame from syntax error
        syn_err.__traceback__ = None
        sys.__excepthook__(type(syn_err), syn_err, None)
        if sys.stderr is not None and hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        _dispatch_diagnostic(syn_err)
        return 1

    # 4. Prepare execution environment
    script_dir = os.path.dirname(abs_path)
    sys.argv = [abs_path, *script_args]
    if sys.path:
        sys.path[0] = script_dir
    else:
        sys.path.insert(0, script_dir)

    # 5. Populate pristine __main__ module
    main_mod = types.ModuleType("__main__")
    main_mod.__file__ = abs_path
    main_mod.__name__ = "__main__"
    main_mod.__doc__ = None
    main_mod.__package__ = None
    main_mod.__loader__ = None
    main_mod.__spec__ = None
    main_mod.__annotations__ = {}
    main_mod.__builtins__ = builtins
    sys.modules["__main__"] = main_mod

    # 6. Execute compiled bytecode
    try:
        exec(code_obj, main_mod.__dict__)
        return 0
    except SystemExit as sys_exit:
        code = sys_exit.code
        if code is None:
            return 0
        elif isinstance(code, int):
            return code
        else:
            if sys.stderr is not None and hasattr(sys.stderr, "write"):
                sys.stderr.write(str(code) + "\n")
            if sys.stderr is not None and hasattr(sys.stderr, "flush"):
                sys.stderr.flush()
            return 1
    except KeyboardInterrupt:
        exc_type, exc_val, exc_tb = sys.exc_info()
        clean_tb = clean_traceback(exc_tb, abs_path)
        if exc_val is not None:
            try:
                exc_val.__traceback__ = clean_tb
            except Exception:
                pass
        sys.__excepthook__(exc_type, exc_val, clean_tb)
        return 130
    except BaseException:
        exc_type, exc_val, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_val, exc_tb)
        return 1


# Alias for interface compatibility with PROJECT.md
execute_script = run_script
