#!/usr/bin/python3
"""Launcher that is safe to run with the system Python.

The rice has a virtualenv early on PATH; GTK/PyGObject live in /usr/lib, so we
never trust `env python3` here.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from glassfiles.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
