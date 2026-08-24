#!/bin/bash
#=====================================================================================
# submit_chain.sh — retrieve a long period as a chain of Slurm jobs.
#
#   bash submit_chain.sh                                   # defaults below
#   bash submit_chain.sh Control/CONTROL_EA5.VolcanoSA 15  # CONTROL file, days per job
#
# Reads START_DATE / END_DATE from a base CONTROL file, splits the period into chunks
# of CHUNK_DAYS days, writes one CONTROL copy per chunk under Control/, and submits one
# job per chunk. Each job is chained to the previous one with --dependency=afterany, so
# Slurm runs them strictly back-to-back: the next chunk starts when the previous one
# finishes, whether it succeeded or not.
#
# Why: a single retrieval of a whole year of hourly ERA5 does not finish inside the
# 36 h wall-time limit — most of the time is spent waiting in the CDS queue, not
# computing — and a job killed at the limit leaves a half-written output directory.
# Chunking also means a failed fortnight can be re-run on its own.
#
# The chunk CONTROL files it writes (CONTROL_<stem>.<YYYYMMDD>) are generated, not
# source: they are git-ignored, and the ones from the 2018 Sabancaya run are kept in
# ../local_reference/volcano_sabancaya/ as a record.
#
# Run this ONCE on a Roihu login node. Give your project with --account, or export
# SBATCH_ACCOUNT=project_XXXXXXX first.
#=====================================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — command line first, then these defaults
# ---------------------------------------------------------------------------
BASE_CONTROL="${1:-${FE_BASE_CONTROL:-Control/CONTROL_EA5}}"
CHUNK_DAYS="${2:-${FE_CHUNK_DAYS:-15}}"
JOB_SCRIPT="${FE_JOB_SCRIPT:-run_flex_extract.slurm}"
LOGDIR="${FE_LOGDIR:-logs}"

[ -f "$BASE_CONTROL" ] || { echo "ERROR: base CONTROL file not found: $BASE_CONTROL" >&2; exit 1; }
[ -f "$JOB_SCRIPT" ]   || { echo "ERROR: job script not found: $JOB_SCRIPT" >&2; exit 1; }
[[ "$CHUNK_DAYS" =~ ^[0-9]+$ ]] && [ "$CHUNK_DAYS" -ge 1 ] || {
  echo "ERROR: CHUNK_DAYS must be a positive integer, got '$CHUNK_DAYS'" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Read START_DATE / END_DATE from the base CONTROL file
# ---------------------------------------------------------------------------
START=$(awk '$1=="START_DATE"{print $2; exit}' "$BASE_CONTROL")
END=$(awk '$1=="END_DATE"{print $2; exit}' "$BASE_CONTROL")

if [[ -z "$START" || -z "$END" ]]; then
    echo "ERROR: could not read START_DATE/END_DATE from $BASE_CONTROL." >&2
    echo "       A CONTROL file without END_DATE retrieves a single day; add one," >&2
    echo "       or submit it directly with 'sbatch $JOB_SCRIPT <controlfile>'." >&2
    exit 1
fi
if (( START > END )); then
    echo "ERROR: START_DATE ($START) is after END_DATE ($END)" >&2
    exit 1
fi

# The chunk copies are named after the base file, so two different campaigns do not
# overwrite each other's chunks.
STEM="$(basename "$BASE_CONTROL")"
mkdir -p "$LOGDIR"

echo "Base CONTROL : $BASE_CONTROL"
echo "Period       : $START -> $END"
echo "Chunk        : $CHUNK_DAYS day(s) per job"
echo "Job script   : $JOB_SCRIPT"
echo "------------------------------------------------------------"

# ---------------------------------------------------------------------------
# Build the dependency chain, one sbatch per chunk
# ---------------------------------------------------------------------------
prev=""                 # previous chunk's job id ("" for the first)
cur="$START"
nchunks=0

while (( cur <= END )); do
    # chunk end = min(cur + CHUNK_DAYS-1, END); END_DATE is inclusive in flex_extract
    cend=$(date -u -d "$cur + $((CHUNK_DAYS - 1)) days" +%Y%m%d)
    if (( cend > END )); then
        cend="$END"
    fi

    # submit.py resolves the controlfile by BASENAME relative to Control/, so the job
    # gets the basename, not the path.
    ctrlname="${STEM}.${cur}"
    ctrl="Control/$ctrlname"
    cp "$BASE_CONTROL" "$ctrl"
    sed -i -E "s/^START_DATE[[:space:]].*/START_DATE $cur/"  "$ctrl"
    if grep -q '^END_DATE' "$ctrl"; then
        sed -i -E "s/^END_DATE[[:space:]].*/END_DATE   $cend/" "$ctrl"
    else
        sed -i -E "/^START_DATE/a END_DATE   $cend" "$ctrl"
    fi

    if [[ -z "$prev" ]]; then
        dep=()
    else
        dep=(--dependency="afterany:$prev")
    fi

    jid=$(sbatch --parsable "${dep[@]}" \
                 --job-name="fe_$cur" \
                 --output="$LOGDIR/${STEM}_$cur.out" \
                 --error="$LOGDIR/${STEM}_$cur.err" \
                 "$JOB_SCRIPT" "$ctrlname")

    printf 'submitted %s..%s  job %s  (dep on %s)\n' "$cur" "$cend" "$jid" "${prev:-none}"

    prev="$jid"
    nchunks=$((nchunks + 1))
    cur=$(date -u -d "$cend + 1 day" +%Y%m%d)
done

echo "------------------------------------------------------------"
echo "Submitted $nchunks chained job(s). Monitor with: squeue --me"
echo "Logs in $LOGDIR/. To stop the chain: scancel <first job id> (the dependants"
echo "then run immediately with 'afterany', so scancel them too)."
