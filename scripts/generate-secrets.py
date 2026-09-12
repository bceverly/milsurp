#!/usr/bin/env python3
"""Write fresh secrets into a config file that still has the sample's.

Split out of the postinst rather than inlined as a heredoc for two reasons:
lintian parses an embedded heredoc as shell and reports Python method calls as
bashisms, and a maintainer script that is only shell is far easier to read.

Only ever called on a config file this package has just created from the
sample -- never on one an administrator has edited.
"""

from __future__ import annotations

import pathlib
import re
import secrets
import sys

#: Everything that must differ between two installations. A deployment shipped
#: with the sample's placeholders would have a forgeable session token and a
#: password hash anyone could reproduce.
SECRETS = ("password_pepper", "jwt_secret")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: generate-secrets.py <config.yaml>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    for key in SECRETS:
        text = re.sub(
            rf"(^\s*{key}:\s*).*$",
            lambda m: f'{m.group(1)}"{secrets.token_urlsafe(48)}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
