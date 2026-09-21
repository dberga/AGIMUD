#!/usr/bin/env bash
set -u

# --- Step 0: config ---
PREFIX="${1:-world}"
NUM_WORLDS="${2:-9}"
NUM_CHARACTERS="${3:-8}"
NUM_OBJECTS="${4:-15}"
NUM_EPOCHS="${5:-10000}"

echo "Prefix: $PREFIX | Worlds: $NUM_WORLDS | Characters: $NUM_CHARACTERS"

# --- Step 1: clean folders ---
for i in $(seq 1 "$NUM_WORLDS"); do
    folder="${PREFIX}${i}"
    if [ -d "$folder" ]; then
        echo "Removing $folder"
        rm -rf "$folder"
    fi
done

# --- Step 2 & 3: parallel per-world generation + run ---
pids=()
for i in $(seq 1 "$NUM_WORLDS"); do
    folder="${PREFIX}${i}"
    (
        echo "[$folder] generate..."
        python swm_generate.py --folder "$folder" --characters "$NUM_CHARACTERS" --objects "$NUM_OBJECTS" \
            || { echo "[$folder] generate FAILED"; exit 1; }

        echo "[$folder] run..."
        python swm_run.py --world "$folder" --max-epoch %NUM_EPOCHS% \
            || { echo "[$folder] run FAILED"; exit 1; }

        echo "[$folder] done"
    ) &
    pids+=($!)
done

# Wait for all parallel jobs
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done

if [ "$fail" -ne 0 ]; then
    echo "One or more worlds failed. Skipping analysis."
    exit 1
fi

# --- Step 4: analyze (single call, after all worlds done) ---
WORLDS=$(for i in $(seq 1 "$NUM_WORLDS"); do printf "%s%s," "$PREFIX" "$i"; done | sed 's/,$//')

echo "Analyzing worlds: $WORLDS"
python swm_analyze.py --worlds "$WORLDS" --out analysis_%PREFIX%