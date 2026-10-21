# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Stand-in for the Unix-only pwd module, so SearXNG imports on Windows.

SearXNG only calls it to word an error message when Valkey (which Irene's
instance doesn't use) can't be reached."""
import getpass
from types import SimpleNamespace


def getpwuid(_uid):
    return SimpleNamespace(pw_name=getpass.getuser())
