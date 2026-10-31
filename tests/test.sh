#!/bin/sh

set -eu

basedir=$(realpath "$(dirname "$0")")

${basedir}/mettatest.sh
${basedir}/pytest.sh
