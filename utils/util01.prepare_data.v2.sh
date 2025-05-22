#!/bin/bash

set -u

echo
echo "CURRENT_DIR: ${CURRENT_DIR} Type: ${root_type} Hostname: $(hostname)"
echo "ORIGIN_1KGENOME_DIR: ${ORIGIN_1KGENOME_DIR} SIZE_37G_IN_BYTES: ${SIZE_37G_IN_BYTES}"
echo

# is_ready=1

if [ ! "${root_type}" = "beegfs" ] && [ ! "${root_type}" = "nfs" ]; then
    # If the storage type is local, we need to measure the data movement cost
    rm -rf "${CURRENT_DIR}"

    # Copy the data
    echo
    echo "Copying from ${ORIGIN_1KGENOME_DIR} ... (might take a while)"
    echo
    start_time=$(date +%s.%N)
    set -x
    cp -r "${ORIGIN_1KGENOME_DIR}" "${CURRENT_DIR}"
    set +x
    end_time=$(date +%s.%N)
    exe_time=$(echo "${end_time} - ${start_time}" | bc -l)
    echo
    echo "Copied data to ${CURRENT_DIR} (${exe_time} secs, Hostname: $(hostname))"
    echo
else
    # If the storage type is shared, create symlinks
    set -x
    mkdir -p "${CURRENT_DIR}"
    ln -s "${ORIGIN_1KGENOME_DIR}"/* "${CURRENT_DIR}"
    set +x
    echo
    echo "Create symlinks in ${CURRENT_DIR}"
    echo
fi

######################################
# if [ ! -d ${CURRENT_DIR} ]; then
#     is_ready=0
#     echo
#     echo "Not found ${CURRENT_DIR}"
#     echo
# else
#     number=$(du -sb "${CURRENT_DIR}" | grep -o -E '^[0-9]+([.][0-9]+)?')
#     if [ ${number} -lt ${SIZE_37G_IN_BYTES} ]; then
#         is_ready=0
#         echo
#         echo "Directory ${CURRENT_DIR} is found, but too small (${number} < ${SIZE_37G_IN_BYTES} Bytes). Removing it on ..."
#         echo
#         rm -rf "${CURRENT_DIR}"
#         echo
#         echo "Removed ${CURRENT_DIR}"
#         echo
#     else
#         echo
#         echo "Directory ${CURRENT_DIR} size is ${number} Bytes (>= ${SIZE_37G_IN_BYTES}), hopefully it's okay ... (Hostname: $(hostname))"
#         echo
#     fi
# fi

# if [ ${is_ready} -ne 1 ]; then
#     echo
#     echo "Copying from ${ORIGIN_1KGENOME_DIR} ... (might take a while)"
#     echo
#     start_time=$(date +%s.%N)
#     set -x
#     cp -r "${ORIGIN_1KGENOME_DIR}" "${CURRENT_DIR}"
#     set +x
#     end_time=$(date +%s.%N)
#     exe_time=$(echo "${end_time} - ${start_time}" | bc -l)
#     echo
#     echo "Copied data to ${CURRENT_DIR} (${exe_time} secs, Hostname: $(hostname))"
#     echo
# fi