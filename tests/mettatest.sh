#!/bin/sh

run_test() {
    f="$1"
    echo "Running $f"

    full=$(sh "${PETTA_PATH}/run.sh" "${f}")
    error=$?
    output=$(echo "$full"  | grep "is " | grep " should ")
    echo "$output" | grep -q "❌"
    fail=$?
    echo "$output" | grep -q "✅"
    pass=$?
    if [ $error -ne 0 ] || [ $fail -eq 0 ] || [ $pass -ne 0 ]; then
        echo "Full output:"
        echo "$full"
        echo "FAILURE in $f:"
        echo "$output"
        return 1
    else
        echo "OK: $f"
        echo "$output"
        return 0
    fi
}

if [ -z "${PETTA_PATH}" ] || [ ! -r "${PETTA_PATH}/run.sh" ]; then
    echo "PETTA_PATH variable should contain the path to the PeTTa directory"
    exit 1
fi

basedir=$(realpath "$(dirname "$0")")
echo "Basedir $basedir"
cd "${basedir}/.." || exit 1

pids=""
pidfile="/tmp/metta_pid_map.$$"
: > "$pidfile"

for f in ./tests/*.metta; do
    run_test "$f" &
    pid=$!
    pids="$pids $pid"
    echo "$pid $f" >> "$pidfile"
done

status=0
for pid in $pids; do
    if ! wait "$pid"; then
        failed_file=$(grep "^$pid " "$pidfile" | cut -d' ' -f2-)
        echo ""
        echo "==============================="
        echo "Stopping tests due to failure:"
        echo "❌ Failed test: $failed_file"
        echo "==============================="
        kill "$pids" 2>/dev/null
        status=1
        break
    fi
done

rm -f "$pidfile"
exit $status
