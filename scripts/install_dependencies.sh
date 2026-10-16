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
refuse_pip_options() {
    options="$(grep -n '^[[:space:]]*-' "$1" || :)"
    if [ -n "$options" ]; then
        echo "$1: a plugin lists requirements here, and nothing else." >&2
        echo "pip would apply these to the whole install, core's own packages included:" >&2
        echo "$options" >&2
        exit 1
    fi
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
