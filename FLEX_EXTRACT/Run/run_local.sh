#!/bin/bash
#
# @Author: Anne Philipp
#
# @Date: October, 4 2018
#
# @Description: 
#    This script defines the available command-line parameters
#    for running flex_extract and combines them for the execution  
#    of the Python program. It also does some checks to 
#    guarantee necessary parameters were set and consistent.
#
# @Licence:
#    (C) Copyright 2014-2020.
#
#    SPDX-License-Identifier: CC-BY-4.0
#
#    This work is licensed under the Creative Commons Attribution 4.0
#    International License. To view a copy of this license, visit
#    http://creativecommons.org/licenses/by/4.0/ or send a letter to
#    Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# -----------------------------------------------------------------
# AVAILABLE COMMANDLINE ARGUMENTS TO SET
# 
# THE USER HAS TO SPECIFY THESE PARAMETERS:

QUEUE=None
START_DATE=None
END_DATE=None
DATE_CHUNK=None
JOB_CHUNK=3
BASETIME=None
STEP=None
LEVELIST=None
AREA=None
# Roihu: put both on /scratch, never in /projappl — a fortnight of hourly ERA5 on 137
# levels is tens of GB, and the intermediate files are larger still. INPUTDIR is the
# working directory (fort.*, flux*, OG_OROLSM*, the *_1/*_2 precipitation sub-steps);
# OUTPUTDIR is where the finished EA* files land. Pointing both at the same directory
# works and is what INAR has always done, but then the working files sit next to the
# output — run/generate_available.py in FLEXPART_v11 knows to skip them.
INPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
OUTPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
PP_ID=None
JOB_TEMPLATE=None
# INAR: the CONTROL file can be overridden from the environment, which is how
# run_flex_extract.slurm and submit_chain.sh hand each chunk its own copy.
CONTROLFILE="${FE_CONTROLFILE:-CONTROL_EA5}"
DEBUG=0
REQUEST=2
PUBLIC=1

# -----------------------------------------------------------------
#
# AFTER THIS LINE THE USER DOES NOT HAVE TO CHANGE ANYTHING !!!
#
# -----------------------------------------------------------------

# PATH TO SUBMISSION SCRIPT
pyscript=../Source/Python/submit.py

# INITIALIZE EMPTY PARAMETERLIST
parameterlist=""

# CHECK IF ON ECMWF SERVER; 
if [[ $HOST == *"ecgb"* ]] || [[ $HOST == *"cca"* ]] || [[ $HOST == *"ccb"* ]]; then
# LOAD PYTHON3 MODULE
  module load python3
fi 

# CHECK FOR MORE PARAMETER 
if [ -n "$START_DATE" ]; then
  parameterlist+=" --start_date=$START_DATE"
fi
if [ -n "$END_DATE" ]; then
  parameterlist+=" --end_date=$END_DATE"
fi
if [ -n "$DATE_CHUNK" ]; then
  parameterlist+=" --date_chunk=$DATE_CHUNK"
fi
if [ -n "$JOB_CHUNK" ]; then
  parameterlist+=" --job_chunk=$JOB_CHUNK"
fi
if [ -n "$BASETIME" ]; then
  parameterlist+=" --basetime=$BASETIME"
fi
if [ -n "$STEP" ]; then
  parameterlist+=" --step=$STEP"
fi
if [ -n "$LEVELIST" ]; then
  parameterlist+=" --levelist=$LEVELIST"
fi
if [ -n "$AREA" ]; then
  parameterlist+=" --area=$AREA"
fi
if [ -n "$INPUTDIR" ]; then
  parameterlist+=" --inputdir=$INPUTDIR"
fi
if [ -n "$OUTPUTDIR" ]; then
  parameterlist+=" --outputdir=$OUTPUTDIR"
fi
if [ -n "$PP_ID" ]; then
  parameterlist+=" --ppid=$PP_ID"
fi
if [ -n "$JOB_TEMPLATE" ]; then
  parameterlist+=" --job_template=$JOB_TEMPLATE"
fi
if [ -n "$QUEUE" ]; then
  parameterlist+=" --queue=$QUEUE"
fi
if [ -n "$CONTROLFILE" ]; then
  parameterlist+=" --controlfile=$CONTROLFILE"
fi
if [ -n "$DEBUG" ]; then
  parameterlist+=" --debug=$DEBUG"
fi
if [ -n "$REQUEST" ]; then
  parameterlist+=" --request=$REQUEST"
fi
if [ -n "$PUBLIC" ]; then
  parameterlist+=" --public=$PUBLIC"
fi

# -----------------------------------------------------------------
# CALL SCRIPT WITH DETERMINED COMMANDLINE ARGUMENTS

$pyscript $parameterlist

