#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Entry point for DevServer Commander."""

import sys

from ui.main_window import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
