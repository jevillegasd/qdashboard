#!/bin/bash
#Add a partition parameter to the action card or run:
#   bash run.sh 2qcrc7b qblox02_tests
#
#watch 'squeue | grep -v sim'

export QIBOLAB_PLATFORMS=~/qibolab_platforms_qrc

export PYTHON_ENV=$(python -c "import sys; print(sys.prefix)")



if [ -n "$VIRTUAL_ENV" ]
then
    export python_env_path=$PYTHON_ENV
else
    export python_env_path=~/.env/qwork
    source $python_env_path/bin/activate
fi

echo "[info] Checking if shyaml is installed"
pip list | grep -F shyaml >/dev/null || echo '[error] Activate a python enviornment with shyaml installed' | return 0

WORK_DIR=${PWD}
WORK_DIR_NAME=${WORK_DIR##*/}exit

static_qibolab_version=0.1.9

# Set the default partition if not specified
[ -n "$DEFAULT_PARTITION" ] || export DEFAULT_PARTITION="qblox20_tests"


if [ $# -eq 3 ]
then
    slurm_job_parition=$2
    slurm_job_name=$1
    qq_option=$3
else
    slurm_job_parition=
    if [ $# -eq 2 ]
    then
        qq_option=$2
        slurm_job_name=$1
        
    else
        if [ $# -eq 1 ]
        then
            slurm_job_name=$1
            qq_option=
        else
            echo "You must specifiy a job name."
            return 0
        fi
    fi
fi
export runcard="$WORK_DIR/actions_${slurm_job_name}.yml"
# Test if the runcard exists



if [ -f $runcard ]
then
    echo "[info] Loading runcard configuration"
    echo "[info] $runcard"
    [ -n "$slurm_job_parition" ] || slurm_job_parition=$(cat ${runcard} | shyaml get-value partition)
    platform=$(cat ${runcard} | shyaml get-value platform)
    qqoption=$(cat ${runcard} | shyaml get-value qqoption)
    environment=$(cat ${runcard} | shyaml get-value environment)
    reportname=$(cat ${runcard} | shyaml get-value reportname) || echo "[info] No report name specified in the action card, using 'latest'."   
else
    echo "[error] The runcard ${runcard} file cannot be found, exiting."
    return 0
fi

if [ -n "$platform" ]
then
    export QIBO_PLATFORM=${platform}
else
    echo "[error] No platform specified in the runcard, exiting."
    return 0
fi
echo "[info] Using platform $platform"

# Load defaults 
[ -n "$slurm_job_parition" ] || slurm_job_parition=$DEFAULT_PARTITION
[ -n "$qqoption" ] || qqoption=--no-update
[ -n "$reportname" ] || reportname=latest
[ -n "$environment" ] || environment=qwork

# Activate the environment specified in the runcard
if [ -n "$environment" ]
then
    deactivate || echo "[info] No python environment active"
    source ~/.env/$environment/bin/activate
else
    environment=qwork
    deactivate || echo "[info] No python environment is active"
    source ~/.env/$environment/bin/activate
fi

# Check the version of qibo tools being used
python_version(){
    if [ -n "$1" ]
    then
        local ret_val=$(python -c "import $1;print($1.__version__)")
        echo "$ret_val"
    else
        echo "not found"
    fi
}
package="qibolab"
version="$(python_version $package)"
vercomp(){ # Compare package versions
    echo "$1" "$2" | python3 -c "import re, sys; arr = lambda x: list(map(int, re.split('[^0-9]+', x))); x, y = map(arr, sys.stdin.read().split()); exit(not x <= y)"; 
}
echo  "[info] Using environment $environment with $package=$version"

if vercomp $version $static_qibolab_version  
then
    export QIBOLAB_PLATFORMS=${QIBOLAB_PLATFORMS}/${platform}
    echo "[info] The runcard is using $package $version <= $static_qibolab_version."
    echo "[info] Copying parameters from json file."
    python -c "from tools import *; json_to_yaml('$QIBOLAB_PLATFORMS/parameters.json','$QIBOLAB_PLATFORMS/parameters.yml');"
else
    if vercomp $version "0.1.9"
    then
        export QIBOLAB_PLATFORMS=${QIBOLAB_PLATFORMS}/${platform} 
        echo "[info] Pointing QIBOLAB_PLATFORMS to $QIBOLAB_PLATFORMS."
    else
    :
    fi
fi



# The first experiemnt ID is used to set the report outer folder
id=$(cat ${runcard} | shyaml get-value actions.0.main)
if [ -z "$id" ]
then
    id=$(cat ${runcard} | shyaml get-value actions.0.id)
fi

if [ -z "$id" ]
then
    id="unspecified"
else
    id="${id// /_}"
    id="${id//-/_}"
fi

# Update the target qubits, to be used in the export folder

exec 2> /dev/null   # Avoid shymal from printing error messages when no parameters are found
#targets=$(cat ${runcard} | shyaml get-value actions.0.targets)
targets=$(cat ${runcard} | shyaml get-value targets)
if [ -n "$targets" ]
then
    :
else
    targets=$(cat ${runcard} | shyaml get-value targets)
fi
if [ -n "$targets" ]
then
    :
else
    targets=$(cat ${runcard} | shyaml get-value qubits)
fi

targets="${targets//[[:space:]]/}"
targets="${targets//-/_}"

exec 2>&1   # Reactivate the error printing


export directory=(~/projects/${platform}/q${targets}/${id})
# Check if the directory exists, otherwise create it
if [ ! -d ${directory} ]
then
    mkdir -p ${directory}
fi

# # Add a consecutive number to the report name based on the number of files in the directory
# nof=$(ls ${directory} | wc -l)
# export directory=(${directory}test_${nof}/)
export directory=(${directory}/${reportname})

# Check if a report directpory already exists and if so, back it up
if [ -d ${directory} ]
then
    echo "[info] Directory ${directory} already exists, copying to ${directory}_backup"
    rm -rf ${directory}_backup
    cp -r ${directory} ${directory}_backup
    # echo "[info] Removing the existing directory"
    rm -rf ${directory}
fi

## Submit Job
echo "[info] Submitting a $id on partition $slurm_job_parition"
echo "[info] Using QPU platform $platform."
echo "[info] Data saved in: $directory/"
echo "$directory/" > ~/.latest

## Option to use qq auto, or acquire + fit + report independently
# qq acquire ${runcard} -o ${directory} ${qq_option}
# qq fit ${directory}
# qq report ${directory}

# #SBATCH --error=logs/error_%j.txt
sbatch -v <<EOT
#!/bin/bash
#SBATCH --job-name=${platform}
#SBATCH --partition=${slurm_job_parition}
#SBATCH --output=~/logs/slurm_output.txt
#SBATCH --time=01:00:00

export QIBO_PLATFORM=${platform}
qq run $runcard -o $directory -f $qq_option
# qq acquire $runcard -o $directory -f $qq_option
# qq fit $directory -f $qq_option
# qq report $directory
exit 0
EOT

deactivate
source $python_env_path/bin/activate

export last=$directory/