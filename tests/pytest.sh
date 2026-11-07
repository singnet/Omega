#!/bin/sh

basedir=$(realpath "$(dirname "$0")")
echo "Basedir $basedir"
cd "${basedir}/.." || exit 1

pytest ./tests
