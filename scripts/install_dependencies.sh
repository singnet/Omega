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
# pip reads an option anywhere a word on the line starts with "-", so one after
# a requirement counts too ("foo==1.0 --hash=..."). It also drops a leading
# UTF-8 byte order mark before reading the file, so the check drops it as well,
# and it decodes UTF-16 and UTF-32 files that grep cannot read, so those are
# refused outright. A comment is removed first, the way pip removes it.
refuse_pip_options() {
    case "$(head -c 4 "$1" | od -An -tx1 | tr -d ' \n')" in
        fffe*|feff*|0000feff*)
            echo "$1: save this file as UTF-8; it is UTF-16 or UTF-32." >&2
            exit 1
            ;;
    esac
    bom="$(printf '\357\273\277')"
    options="$(LC_ALL=C sed -e "1s/^$bom//" -e 's/^#.*//' -e 's/[[:space:]]#.*//' "$1" \
        | grep -n -e '^[[:space:]]*-' -e '[[:space:]]-' || :)"
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
