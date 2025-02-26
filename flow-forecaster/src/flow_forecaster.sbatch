#!/bin/bash
#SBATCH --job-name=flow_forecaster
#SBATCH --partition=a100
#SBATCH --account=datamesh
#SBATCH --time=00:10:00
#SBATCH -N 2
#SBATCH -n 12

SHORTENED_PIPELINE=false
MD_RUNS=$((6 * $(basename `pwd`)))
ITER_COUNT=1 # TBD
SIM_LENGTH=$(python -c "print (round(1.20 / $MD_RUNS, 5))")

NODE_COUNT=1
GPU_PER_NODE=2
MD_START=0
MD_SLICE=$(($MD_RUNS/$NODE_COUNT))
#NODE_NAMES=`echo $SLURM_JOB_NODELIST|scontrol show hostnames`
NODE_NAMES=`hostname`
STAGE_IDX=0
STAGE_IDX_FORMAT=$(seq -f "stage%04g" $STAGE_IDX $STAGE_IDX)

EXPERIMENT_PATH=$(pwd)
DDMD_PATH=/people/leeh736/git/deepdrivemd
MOLECULES_PATH=/qfs/projects/oddite/leeh736/git/molecules

OPENMM () {

    task_id=$(seq -f "task%04g" $1 $1)
    gpu_idx=$(($1 % $GPU_PER_NODE))
    node_id=$2
    yaml_path=$3
    stage_name="molecular_dynamics"
    dest_path=$EXPERIMENT_PATH/${stage_name}_runs/$STAGE_IDX_FORMAT/$task_id

    if [ "$yaml_path" == "" ]
    then
        yaml_path=$DDMD_PATH/test/bba/${stage_name}_stage_test.yaml
    fi


    module load python/miniconda3.7 gcc/7.5.0
    source activate /people/leeh736/.conda/envs/openmm

    mkdir -p $dest_path
    cd $dest_path
    echo cd $dest_path

    sed -e "s/\$SIM_LENGTH/${SIM_LENGTH}/" -e "s/\$OUTPUT_PATH/${dest_path//\//\\/}/" -e "s/\$EXPERIMENT_PATH/${EXPERIMENT_PATH//\//\\/}/" -e "s/\$DDMD_PATH/${DDMD_PATH//\//\\/}/" -e "s/\$GPU_IDX/${gpu_idx}/" -e "s/\$STAGE_IDX/${STAGE_IDX}/" $yaml_path  > $dest_path/$(basename $yaml_path)
    yaml_path=$dest_path/$(basename $yaml_path)

    #PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH srun -w $node_id -n1 -N1 --exclusive python $DDMD_PATH/deepdrivemd/sim/openmm/run_openmm.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log &
    PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH strace -o strace.out -f ~/.conda/envs/openmm/bin/python $DDMD_PATH/deepdrivemd/sim/openmm/run_openmm.py -c $yaml_path &>  ${task_id}_${FUNCNAME[0]}.log 
}

AGGREGATE () {

    task_id=task0000
    stage_name="aggregate"
    STAGE_IDX=$(($STAGE_IDX - 1))
    STAGE_IDX_FORMAT=$(seq -f "stage%04g" $STAGE_IDX $STAGE_IDX)
    dest_path=$EXPERIMENT_PATH/molecular_dynamics_runs/$STAGE_IDX_FORMAT/$task_id
    yaml_path=$DDMD_PATH/test/bba/${stage_name}_stage_test.yaml


    module load python/miniconda3.7 gcc/7.5.0
    source activate /people/leeh736/.conda/envs/openmm 

    dest_path_2=$EXPERIMENT_PATH/aggregate_runs/$STAGE_IDX_FORMAT/$task_id
    mkdir -p $dest_path_2
    cd $dest_path_2
    echo cd $dest_path_2

    sed -e "s/\$SIM_LENGTH/${SIM_LENGTH}/" -e "s/\$OUTPUT_PATH/${dest_path//\//\\/}/" -e "s/\$EXPERIMENT_PATH/${EXPERIMENT_PATH//\//\\/}/" -e "s/\$STAGE_IDX/${STAGE_IDX}/" $yaml_path  > $dest_path/$(basename $yaml_path)
    yaml_path=$dest_path/$(basename $yaml_path)

    #{ time PYTHONPATH=$DDMD_PATH python $DDMD_PATH/deepdrivemd/aggregation/basic/aggregate.py -c $yaml_path ; } &> ${task_id}_${FUNCNAME[0]}.log 
    echo PYTHONPATH=$DDMD_PATH strace -o strace.out -f python $DDMD_PATH/deepdrivemd/aggregation/basic/aggregate.py -c $yaml_path  ${task_id}_${FUNCNAME[0]}.log 
    PYTHONPATH=$DDMD_PATH strace -o strace.out -f ~/.conda/envs/openmm/bin/python $DDMD_PATH/deepdrivemd/aggregation/basic/aggregate.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log 

}

TRAINING () {

    task_id=task0000
    stage_name="machine_learning"
    dest_path=$EXPERIMENT_PATH/${stage_name}_runs/$STAGE_IDX_FORMAT/$task_id
    stage_name="training"
    yaml_path=$DDMD_PATH/test/bba/${stage_name}_stage_test.yaml


    mkdir -p $EXPERIMENT_PATH/model_selection_runs/$STAGE_IDX_FORMAT/task0000/
    cp -p $DDMD_PATH/test/bba/stage0000_task0000.json $EXPERIMENT_PATH/model_selection_runs/$STAGE_IDX_FORMAT/task0000/${STAGE_IDX_FORMAT}_task0000.json

    module load python/miniconda3.7 gcc/7.5.0
    source activate /people/leeh736/.conda/envs/pytorch_sm80

    mkdir -p $dest_path
    cd $dest_path
    echo cd $dest_path

    sed -e "s/\$SIM_LENGTH/${SIM_LENGTH}/" -e "s/\$OUTPUT_PATH/${dest_path//\//\\/}/" -e "s/\$EXPERIMENT_PATH/${EXPERIMENT_PATH//\//\\/}/" -e "s/\$STAGE_IDX/${STAGE_IDX}/" $yaml_path  > $dest_path/$(basename $yaml_path)
    yaml_path=$dest_path/$(basename $yaml_path)

   echo PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH srun -n1 -N1 --exclusive python ~/git/deepdrivemd/deepdrivemd/models/aae/train.py -c $yaml_path ${task_id}_${FUNCNAME[0]}.log 
   if [ "$SHORTENED_PIPELINE" == true ]
   then
       PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH srun -n1 -N1 --exclusive python $DDMD_PATH/deepdrivemd/models/aae/train.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log &
   else
       #PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH srun -n1 -N1 --exclusive python $DDMD_PATH/deepdrivemd/models/aae/train.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log
       PYTHONPATH=$DDMD_PATH:$MOLECULES_PATH strace -o strace.out -f ~/.conda/envs/pytorch_sm80/bin/python $DDMD_PATH/deepdrivemd/models/aae/train.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log
   fi

}

INFERENCE () {

    task_id=task0000
    stage_name="inference"
    dest_path=$EXPERIMENT_PATH/${stage_name}_runs/$STAGE_IDX_FORMAT/$task_id
    yaml_path=$DDMD_PATH/test/bba/${stage_name}_stage_test.yaml
    pretrained_model=$DDMD_PATH/data/bba/epoch-130-20201203-150026.pt


    module load python/miniconda3.7 gcc/7.5.0
    source activate /people/leeh736/.conda/envs/pytorch_sm80

    mkdir -p $dest_path
    cd $dest_path
    echo cd $dest_path

    mkdir -p $EXPERIMENT_PATH/agent_runs/$STAGE_IDX_FORMAT/task0000/


    sed -e "s/\$SIM_LENGTH/${SIM_LENGTH}/" -e "s/\$OUTPUT_PATH/${dest_path//\//\\/}/" -e "s/\$EXPERIMENT_PATH/${EXPERIMENT_PATH//\//\\/}/" -e "s/\$STAGE_IDX/${STAGE_IDX}/" $yaml_path  > $dest_path/$(basename $yaml_path)
    yaml_path=$dest_path/$(basename $yaml_path)

    # latest model search
    model_checkpoint=$(find $EXPERIMENT_PATH/machine_learning_runs/*/*/checkpoint -type f -printf '%T@ %p\n' | sort -n | tail -1 | cut -f2- -d" ")
    if [ "$model_checkpoint" == "" ] && [ "$SHORTENED_PIPELINE" == true ]
    then
        model_checkpoint=$pretrained_model
    fi
    model_checkpoint=""
    STAGE_IDX_PREV=$((STAGE_IDX - 1))
    STAGE_IDX_FORMAT_PREV=$(seq -f "stage%04g" $STAGE_IDX_PREV $STAGE_IDX_PREV)
    sed -i -e "s/\$MODEL_CHECKPOINT/${model_checkpoint//\//\\/}/"  $EXPERIMENT_PATH/model_selection_runs/$STAGE_IDX_FORMAT_PREV/task0000/${STAGE_IDX_FORMAT_PREV}_task0000.json


   #OMP_NUM_THREADS=4 PYTHONPATH=$DDMD_PATH$MOLECULES_PATH  python $DDMD_PATH/deepdrivemd/agents/lof/lof.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log 
   OMP_NUM_THREADS=4 PYTHONPATH=$DDMD_PATH$MOLECULES_PATH strace -o strace.out -f ~/.conda/envs/pytorch_sm80/bin/python $DDMD_PATH/deepdrivemd/agents/lof/lof.py -c $yaml_path &> ${task_id}_${FUNCNAME[0]}.log 

}


STAGE_UPDATE() {

    STAGE_IDX=$(($STAGE_IDX + 1))
    tmp=$(seq -f "stage%04g" $STAGE_IDX $STAGE_IDX)
    echo $tmp
}
#


total_start_time=$(date +%s%3N)

for iter in $(seq $ITER_COUNT)
do

    start_time=$(date +%s%3N)

    # STAGE 1: OpenMM
    for node in $NODE_NAMES
    do
        while [ $MD_SLICE -gt 0 ] && [ $MD_START -lt $MD_RUNS ]
        do
            echo $node
            OPENMM $MD_START $node
            MD_START=$(($MD_START + 1))
            MD_SLICE=$(($MD_SLICE - 1))
        done
        MD_SLICE=$(($MD_RUNS/$NODE_COUNT))
    done

    MD_START=0

    wait

    duration=$(( $(date +%s%3N) - $start_time))
    echo "OpenMM done... $duration milliseconds elapsed."
    echo "stage1,$duration,base_nfs,${NODE_COUNT}nodes,small" >> $EXPERIMENT_PATH/stat.log

    STAGE_IDX_FORMAT="$(STAGE_UPDATE)"
    STAGE_IDX=$((STAGE_IDX + 1))
    echo $STAGE_IDX_FORMAT


    # STAGE 2: Aggregate
    if [ "$SHORTENED_PIPELINE" != true ]
    then

        start_time=$(date +%s%3N)

        AGGREGATE

        wait

        duration=$(($(date +%s%3N) - $start_time))
        echo "Aggregate done... $duration milliseconds elapsed."
        echo "stage2,$duration,base_nfs,${NODE_COUNT}nodes,small" >> $EXPERIMENT_PATH/stat.log
    fi


    STAGE_IDX_FORMAT="$(STAGE_UPDATE)"
    STAGE_IDX=$((STAGE_IDX + 1))
    echo $STAGE_IDX_FORMAT

    # STAGE 3: Training
    start_time=$(date +%s%3N)
    TRAINING

    STAGE_IDX_FORMAT="$(STAGE_UPDATE)"
    STAGE_IDX=$((STAGE_IDX + 1))
    echo $STAGE_IDX_FORMAT
    if [ "$SHORTENED_PIPELINE" != true ]
    then
        wait
        duration=$(( $(date +%s%3N) - $start_time))
        echo "Training done... $duration milliseconds elapsed."
        echo "stage3,$duration,base_nfs,${NODE_COUNT}nodes,small" >> $EXPERIMENT_PATH/stat.log
    fi


    # STAGE 4: Inference
    start_time=$(date +%s%3N)
    INFERENCE

    wait

    duration=$(( $(date +%s%3N) - $start_time))
    echo "Inference done... $duration milliseconds elapsed."
    echo "stage4,$duration,base_nfs,${NODE_COUNT}nodes,small" >> $EXPERIMENT_PATH/stat.log

    STAGE_IDX_FORMAT="$(STAGE_UPDATE)"
    STAGE_IDX=$((STAGE_IDX + 1))
    echo $STAGE_IDX_FORMAT

done

wait

total_duration=$(( $(date +%s%3N) - $total_start_time))
echo "All done... $total_duration milliseconds elapsed."
