# analysis_scripts

Post-processing for **FLEXPART-WRF backward runs**: turn `flxout_dNN.nc` into footprint
maps, source-contribution maps, time series and transport regimes.

Everything is read from the model output itself — the grid, the vertical levels, the
release times and the map projection all come from `header_dNN.nc` and the flxout global
attributes. There is nothing to edit inside the scripts.

## What you need

Both files that FLEXPART-WRF writes into the output directory:

```
flxout_d01_20220626_230000.nc     the concentrations
header_d01.nc                     the grid and the release list
```

The scripts find the header next to the output file by its domain number (`_d01_` →
`header_d01.nc`); pass `--header` if it lives somewhere else. Nested domains work the
same way — point at `flxout_d02_*.nc` and `header_d02.nc` is picked up.

```bash
pip install numpy xarray netCDF4 dask matplotlib cartopy pandas
pip install minisom scikit-learn      # only for som_regimes.py
```

## The scripts

| Script | What it does |
|---|---|
| `reduce_output.py` | sums the output steps into one footprint per release — do this first |
| `plot_footprint.py` | map of the mean source-receptor relationship over a time window |
| `plot_source_map.py` | map of where a measured concentration came from |
| `time_over.py` | per-release residence time over a **static** surface field (forest, a mask) |
| `ame_timeseries.py` | per-release exposure to a **time-varying** emission field |
| `som_regimes.py` | clusters the releases into transport regimes with a self-organising map |

Every script takes either a reduced file **or** a raw `flxout_dNN.nc` and gives the same
answer; the raw file is just slower, because the output steps are summed each time. The
one exception is `ame_timeseries.py`, which needs the raw file — its emissions change
hour by hour, so the output steps have to still be there. Run any of them with `--help`
for the full flag list.

## Running on Roihu

Do not run these on the login node — reducing a run or accumulating emissions reads
gigabytes and takes minutes to hours. `run_analysis.slurm` submits any one of them as a
batch job:

```bash
sbatch --account=project_XXXXXXX run_analysis.slurm <tool> [the script's own flags...]
```

The first argument picks the script; everything after it is handed to that script
unchanged, so every flag documented below works as written:

| tool | script |
|---|---|
| `reduce` | `reduce_output.py` |
| `footprint` | `plot_footprint.py` |
| `source-map` | `plot_source_map.py` |
| `time-over` | `time_over.py` |
| `ame` | `ame_timeseries.py` |
| `som` | `som_regimes.py` |

```bash
sbatch --account=project_XXXXXXX run_analysis.slurm \
    reduce flxout_d02_20220626_230000.nc -o footprints_d02.nc --chunk 100

sbatch --account=project_XXXXXXX run_analysis.slurm \
    footprint footprints_d01.nc --start 2022-05-28 --end 2022-05-29
```

Submit from the directory that holds `flxout`/`header` — relative paths and the output
files are resolved there. If that is not `analysis_scripts/` itself, say where the
scripts are:

```bash
sbatch --account=project_XXXXXXX \
    --export=ALL,AS_ROOT=/projappl/project_XXXXXXX/$USER/FLEXPART/analysis_scripts \
    /projappl/project_XXXXXXX/$USER/FLEXPART/analysis_scripts/run_analysis.slurm \
    footprint footprints_d01.nc
```

The defaults are 8 cores, 32 GB and 4 hours, which suits a reduction or a plot; give a
long `ame` over a raw `flxout` more of both on the command line:

```bash
sbatch --account=project_XXXXXXX --time=12:00:00 --mem=64G run_analysis.slurm \
    ame flxout_d01_20230430_230000.nc --emis EMISSION_MILAN.nc --var MONOT NOx SO2_a \
    --hours 72 -o AME_Milan.csv
```

The environment comes from the `python-data` module. `som_regimes.py` also needs
`minisom` and `scikit-learn`, which are not in it:

```bash
module load python-data
python3 -m venv --system-site-packages $HOME/fp_analysis_venv
source $HOME/fp_analysis_venv/bin/activate
pip install minisom scikit-learn
```

then submit with `--export=ALL,AS_VENV=$HOME/fp_analysis_venv`. The job checks every
import it needs before it starts work and names anything missing. It also checks the
Natural Earth cache the map plots draw from, and prints the one command that fills it —
run that once on the login node, which has the network, if the warning appears.

Run a tool's `--help` without queueing anything:

```bash
AS_ROOT=. bash run_analysis.slurm footprint --help
```

Logs are `fpanalysis_<jobid>.out` and `.err` in the submit directory.

## reduce_output.py

```bash
./reduce_output.py flxout_d02_20220626_230000.nc -o footprints_d02.nc --chunk 100
```

Sums `CONC` over `Time`, collapses `ageclass`, and copies in the grid (`XLONG`, `XLAT`
and the cell corners), the layer tops (`ztop`) and every global attribute. It also adds a
`release_time` coordinate — the moment each release's air is at the receptor — which is
what lets the other scripts select releases by date instead of by index.

`--chunk` is how many output steps are held in memory at once; lower it if the run is
short of RAM. `--species N` picks one of several species.

## plot_footprint.py

```bash
./plot_footprint.py footprints_d01.nc --start 2022-05-28 --end 2022-05-29
./plot_footprint.py footprints_d01.nc --below 1000 --vmin 1 --vmax 1000
```

The footprint averaged over the selected releases and integrated through height.

| Flag | Meaning |
|---|---|
| `--start` / `--end` | release arrivals to average; `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`. A bare `--end` date means the whole of that day. Default: every release |
| `--below METRES` | only the output layers whose top is below this height |
| `--vmin` / `--vmax` | colour limits; by default the scale spans four decades below the maximum |
| `--label`, `--title`, `--cmap`, `-o` | cosmetics |

## plot_source_map.py

```bash
./plot_source_map.py footprints_d01.nc --obs IZO_SO2_1min.txt --skiprows 4 \
    --value-col "So2 (ppb)" --time-format "%m/%d/%Y %H:%M" --save-nc src_so2.nc
```

Tags every release with the value measured at the receptor when its air arrived, spreads
that value over the output layers following the vertical profile of the footprint, and
averages over the releases that touched each cell.

The observation file is any text table with a date column and a value column. Column
names and the date layout are guessed if you do not say; if the guess is wrong the error
message tells you which flag to set.

| Flag | Meaning |
|---|---|
| `--obs FILE` | the measurements (required) |
| `--skiprows N` | preamble lines before the column names |
| `--sep` | column separator, default `,` (use `--sep '\s+'` for whitespace) |
| `--time-col` / `--value-col` | column names; default the first and second |
| `--time-format` | `strptime` layout, if pandas cannot work the dates out |
| `--save-nc FILE` | also write the map as NetCDF |

Measurements are averaged over each release interval, and releases with no measurement
are left out of both the sum and the count.

## time_over.py

```bash
./time_over.py footprints_d01.nc --field geo_em_with_TCD.nc --var TCD \
    --missing 255 --scale 0.01 --bbox -20 -12 26 32 -o time_over_forest.csv
```

Multiplies each release's column-integrated footprint by a static map on the same grid
and sums over the domain: one number per release, written as
`release_time,<var>` CSV.

The static field must be on the FLEXPART **output** grid (same `south_north` ×
`west_east`); the script says so plainly if it is not.

| Flag | Meaning |
|---|---|
| `--field FILE --var NAME` | the NetCDF and the variable to weight by (required) |
| `--missing V` | value meaning "no data", set to zero — `255` for WRF `geo_em` fields |
| `--scale F` | multiply the field, e.g. `0.01` to turn percent into a fraction |
| `--bbox LON0 LON1 LAT0 LAT1` | only sum inside this box |
| `--below METRES` | only the output layers below this height |

## ame_timeseries.py

```bash
./ame_timeseries.py flxout_d01_20230430_230000.nc --emis EMISSION_MILAN.nc \
    --var MONOT NOx SO2_a --emis-level 1 --hours 72 -o AME_Milan.csv
```

Accumulated mass exposure: for every release, walks back through the output steps and
multiplies the footprint at each step by the emission field **at that same hour**,
summing over the domain. That hour-by-hour pairing is the whole point — use
`time_over.py` when the field does not change in time.

Writes `release_time,<var1>,<var2>,...` CSV, one row per release.

| Flag | Meaning |
|---|---|
| `--emis FILE --var NAME [NAME ...]` | the emission file and the species to accumulate (required) |
| `--emis-level N` | model level of the emissions, for variables that have one (default: 0) |
| `--hours H` | length of the backward window, ending at the arrival (default: 72) |
| `--below METRES` | only the output layers below this height |

The emission file needs a readable time axis (`Times` in WRF or CHIMERE form, or a
`time` / `time_counter` coordinate) and must be on the FLEXPART output grid; `x`/`y`,
`lon`/`lat` and `west_east`/`south_north` are all recognised. Emission steps are matched
to output steps to within half an hour, and the script reports how many of them matched
before doing any work — check that line, it is the usual thing to get wrong.

## som_regimes.py

```bash
./som_regimes.py footprints_d01.nc --shape 3x2 --iterations 200000 --seed 123
```

Each release is one sample — its column-integrated footprint, standardised cell by cell.
Writes three files under `<prefix>_`:

- `_clusters.csv` — `release,release_time,regime` for every release
- `_neurons.png` — one map per neuron, on a shared colour scale
- `_dominant.nc` — the regime with the largest weight in each grid cell

`--shape COLSxROWS` sets the number of regimes (`3x2` = six). `--sigma`,
`--learning-rate`, `--topology` and `--seed` expose the MiniSom settings; `--verbose`
shows its training bar.

## Notes

- These scripts are for **backward** (receptor-oriented) runs: `CONC` must have a
  `releases` dimension. A forward run gets a clear error rather than a wrong answer.
- Times are UTC throughout, and a release is dated by when its air reaches the receptor
  (the end of the release), not by when the run started.
