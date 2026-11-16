#!/bin/sh
# Install core's Python dependencies, and those of every plugin that declares any.
#
# A plugin is a directory under plugins/. One that ships a requirements.txt gets
# it installed without core naming the plugin; one that ships none costs nothing.
# That file lists requirements and nothing else — see refuse_pip_options.
#
# Everything reaches a single pip invocation. Separate invocations resolve
# separately, so a plugin pinning a version core also pins would replace core's
# copy in silence — core is not a pip distribution, so nothing records what it
# needed and no warning fires. Resolved together, a real conflict fails here
# rather than at import time, and pip check catches what resolution let through.
#
# Arguments are passed through to pip, so an image build can add its own:
#
#   ./scripts/install_dependencies.sh
#   ./scripts/install_dependencies.sh --no-cache-dir --break-system-packages
set -eu

repo="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

# Stop on a plugin file that carries pip options instead of requirements.
#
# pip applies an option it reads inside a requirements file to the whole
# invocation rather than to the file carrying it, and it overrides the same
# option given on the command line. One plugin shipping an --index-url line
# therefore decides where every package is fetched from, core's own pinned ones
# included, and the install still reports success. Sharing one invocation is
# what makes core's pins win, so there is nowhere to scope such an option to,
# and the file is refused instead.
#
# The file is read by pip's own code, the same that will read it for the
# install. pip decodes it by its byte order mark or a "# -*- coding: -*-"
# line, splits it at every character Python counts as a line break, joins
# lines ending in "\", drops comments, expands ${VARIABLES}, and then takes
# any word starting with "-" as the start of options. A check that copies any
# of those steps by hand can be fooled where the copy differs. This pip is the
# one that installs, so the two cannot disagree. A pip without these functions
# refuses every plugin file rather than letting one through unread.
refuse_pip_options() {
    python3 - "$1" <<'PY'
import sys

path = sys.argv[1]
try:
    from pip._internal.req.req_file import (
        break_args_options,
        get_file_content,
        preprocess,
    )
except ImportError as error:
    sys.exit(f"{path}: this pip cannot be used to check plugin files ({error}).")

try:
    _, content = get_file_content(path, None)
except Exception as error:
    sys.exit(f"{path}: pip cannot read this file: {error}")

options = [
    f"{number}:{line}"
    for number, line in preprocess(content)
    if break_args_options(line)[1].strip()
]
if options:
    print(f"{path}: a plugin lists requirements here, and nothing else.", file=sys.stderr)
    print("pip would apply these to the whole install, core's own packages included:", file=sys.stderr)
    print("\n".join(options), file=sys.stderr)
    sys.exit(1)
PY
}

set -- "$@" -r "$repo/requirements.txt"
for plugin_requirements in "$repo"/plugins/*/requirements.txt; do
    if [ -f "$plugin_requirements" ]; then
        refuse_pip_options "$plugin_requirements"
        set -- "$@" -r "$plugin_requirements"
    fi
done

python3 -m pip install "$@"
python3 -m pip check
