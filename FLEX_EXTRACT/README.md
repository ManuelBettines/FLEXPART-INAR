# flex_extract 7.1.3 on Roihu 

Setup-and-run guide for **flex_extract**, which retrieves meteorological fields from
ECMWF and converts them into the GRIB files **FLEXPART v11** reads. It is a
pre-processing step, not a model: run it first, then point FLEXPART at its output
([`../FLEXPART_v11/`](../FLEXPART_v11/)).

---

## 1. What this is

flex_extract does two things:

1. **Retrieves** the fields FLEXPART needs — winds, temperature, humidity, surface
   fields, fluxes — from the Copernicus Climate Data Store (ERA5) or from ECMWF's MARS
   archive (operational data, member-state accounts only).
2. **Converts** them: it computes the vertical velocity in ECMWF's native hybrid
   coordinate with the Fortran program `calc_etadot`, disaggregates the accumulated
   precipitation, and concatenates everything into one GRIB file per time step, named
   `<PREFIX><YYMMDDHH>` (e.g. `EA18010100`).

That second step is why this is not simply a download script, and why it has to be
compiled.

**This is not the offical repository of flex_extract**, and it is adapted to work on Roihu. 
Original authors: Anne Tipka (formerly Philipp), Leopold Haimberger and Petra Seibert. You can find the offical documentation in `Documentation/html/index.html`, or at
<https://www.flexpart.eu/flex_extract/>.

### Repository layout

```
FLEX_EXTRACT/
├── setup_roihu.sh         one-command install (this is what you run)
├── roihu_env.sh           modules + virtualenv; sourced by setup AND run scripts
├── Run/
│   ├── Control/           the CONTROL files: one per retrieval configuration
│   ├── run_local.sh       upstream launcher; INPUTDIR/OUTPUTDIR live here
│   ├── run_flex_extract.slurm   submit one retrieval
│   └── submit_chain.sh    split a long period into chained jobs
├── Source/
│   ├── Python/            the retrieval and conversion driver
│   └── Fortran/           calc_etadot, and makefile_roihu
├── Templates/             job and namelist templates
└── Documentation/         upstream HTML documentation
```

---

## 2. Installing

Log in, clone the repository and move into the FLEX_EXTRACT folder:

```bash
# Login to Roihu
ssh -A -X <username>@roihu-cpu.csc.fi

# Clone the repository to your project folder
cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART

# Move to the FLEX_EXTRACT folder
cd FLEXPART/FLEX_EXTRACT
```

Everything below happens from inside that folder. Before running the installer, sort
out the access keys and the python environment — this is the part that takes days, not
minutes, so do it before you need the data.

### 2.1 ERA5 through the CDS

1. Register at <https://cds.climate.copernicus.eu/> and log in.
2. Accept the licence for **ERA5 complete** and **ERA5 single levels** in the web
   interface. Each dataset has to be accepted once; a retrieval against an unaccepted
   licence fails with an HTTP 403 that says nothing useful.
3. Put your API key in `~/.cdsapirc`, then `chmod 600 ~/.cdsapirc`:

   ```
   url: https://cds.climate.copernicus.eu/api
   key: <your-key>
   ```

Retrievals are **queued at ECMWF**. A fortnight of hourly ERA5 on 137 levels can sit in
the queue for hours before a byte arrives, so this might take a lot of time depending on how long of a period you want to retrieve.

### 2.2 The python environment

flex_extract needs `cdsapi`, `ecmwf-api-client`, `genshi`, `numpy` and the **ecCodes
python bindings**. Build the virtualenv once:

```bash
source ./roihu_env.sh    
python3 -m venv $HOME/flex_extract_venv
source $HOME/flex_extract_venv/bin/activate
pip install --upgrade pip
pip install cdsapi ecmwf-api-client genshi numpy eccodes
```

### 2.3 Building

```bash
./setup_roihu.sh
```

The script sources [`roihu_env.sh`](roihu_env.sh), checks the python side and the API
keys, and compiles `calc_etadot`. At the end you should get:

```
==============================================================================
 INSTALL SUMMARY
==============================================================================
 calc_etadot : OK   .../Source/Fortran/calc_etadot -> .../calc_etadot_fast.out

 Next: edit Run/Control/<your CONTROL file>, then
         cd Run && sbatch --account=project_XXXXXXX run_flex_extract.slurm
==============================================================================
```

---

## 3. Preparing a retrieval: the CONTROL file

Everything about a retrieval is in one CONTROL file under `Run/Control/`. Start from
`CONTROL_EA5` (ERA5, regional).

```bash
cp Run/Control/CONTROL_EA Run/Control/CONTROL_EA.MyCase
```

```
START_DATE 20180101           # start date of the retrival 
END_DATE   20180131	      # end date of the retrival
DTIME 1                       # output every 1 h
TYPE AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN AN
TIME 00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23
STEP 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
ACCTYPE FC                  
ACCTIME 06/18
ACCMAXSTEP 12
CLASS EA                   
STREAM OPER
GRID 0.25                     # output resolution, degrees
LEFT -136.                    # the domain left border longitude
LOWER -57.		      # the domain lower border latitude
UPPER 13.		      # the domain upper border latitude
RIGHT 0.		      # the domain right border longitude
LEVELIST 1/to/137         
RESOL 159                    
ETA 1                        
CWC 1                       
PREFIX EA                  
RRINT 1                      
ECTRANS 1
```

Only the flags with a comment should be changed. I did not tested retrieving data with different flags.


### Where the output goes

`INPUTDIR` and `OUTPUTDIR` are set in [`Run/run_local.sh`](Run/run_local.sh), not in the
CONTROL file. Put both on `/scratch`:

```bash
INPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
OUTPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
```

`INPUTDIR` is the working directory and `OUTPUTDIR` is where the finished `EA*` files
land. Pointing both at the same directory (the directory where you want to store the retrived data) works just fine.

---

## 4. Submitting

### One period

```bash
cd Run
# Modify XXXXXXX with your actual project number
sbatch --account=project_XXXXXXX run_flex_extract.slurm CONTROL_EA5.MyCase
```

The argument is the **basename** of a file in `Run/Control/`. Without an argument, the
`CONTROLFILE` set in `run_local.sh` is used. The script creates `INPUTDIR` and `OUTPUTDIR`, and then runs the unmodified upstream
`run_local.sh`.

### A long period, as a chain

```bash
cd Run
export SBATCH_ACCOUNT=project_XXXXXXX
bash submit_chain.sh Control/CONTROL_EA5.VolcanoSA 15
```

That reads `START_DATE`/`END_DATE` from the base CONTROL file, splits the period into
15-day chunks, writes one CONTROL copy per chunk
(`CONTROL_EA5.VolcanoSA.20180104`, ...) and submits one job per chunk, each depending on
the previous one with `--dependency=afterany`. Slurm then runs them strictly
back-to-back, and no single job has to finish a year's retrieval inside the 36 h
wall-time limit.

Monitor with `squeue --me`; logs land in `Run/logs/`.

When the retrival is done you should get the following message:
```
FLEX_EXTRACT IS DONE!
```
If so you can move to [`FLEXPART_v11/`](../FLEXPART_v11/).

---

## 5. Troubleshooting

When running the first time you might get the following message: `**run_local.sh: line 128: ../Source/Python/submit.py: Permission denied**`
If so, run the following command (and relaunch the download):
```bash
chmod 777 ../Source/Python/submit.py
```

Anything else: manuel.bettineschi@helsinki.fi

---

## License

Upstream flex_extract is © 2014–2020 Anne Philipp, Leopold Haimberger and Petra Seibert,
licensed **CC-BY-4.0** (`LICENSE.md`); the Fortran sources under `Source/Fortran/` carry
`SPDX-License-Identifier: GPL-2.0`.

The Roihu setup code and other original code added by this repository's author are released under **CC0 1.0 Universal (CC0-1.0)**. To the extent permitted by law, these contributions may be copied, modified, distributed, and used for any purpose without permission or attribution.
