from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.components.boards.arm_board import ArmBoard
from m5.objects.ArmSystem import ArmDefaultRelease
from m5.objects.RealView import (
    VExpress_GEM5_V1
)

from gem5.simulate.simulator import Simulator
from gem5.resources.resource import obtain_resource
from gem5.simulate.exit_event import ExitEvent
from gem5.utils.requires import requires

import argparse
from pathlib import Path

import m5

# Parse command line arguments
parser = argparse.ArgumentParser(
    description=(
        "Run a simple gem5 simulation to obtain the memory map of a process."
    )
)
parser.add_argument(
    "--use-kvm", action="store_true", 
    help="Use KVM for the simulation."
)
parser.add_argument(
    "--use-checkpoint", action="store_true", 
    help="Use checkpointing to store the state of the simulation."
)
parser.add_argument(
    "-sc", "--checkpoint-store-path", type=str, 
    default="after_boot_checkpoint_store_cpt",
    help=(
        "Path to the directory where the checkpoint will be stored. "
        "This is use as the store path for the checkpoint when "
        "--use-checkpoint is not set. Otherwise, it is used as the "
        "restoring checkpoint path."
    )
)
args = parser.parse_args()

requires(isa_required=ISA.ARM)

use_kvm = args.use_kvm
use_checkpoint = args.use_checkpoint
checkpoint_store_path = Path(Path().cwd()/args.checkpoint_store_path)
addr_mode = " "
if use_kvm:
    print("Using KVM for the simulation.")
    requires(kvm_required=True)
    if use_checkpoint:
        raise Exception(
            "Restoring a checkpoint is not supported with KVM in this example."
            " Please run without --use-checkpoint."
        )
else:
    print("Not using KVM, running in full system mode.")

# ================ System configuration starts ================

num_threads = 2

release = ArmDefaultRelease().for_kvm()
platform = VExpress_GEM5_V1()
processor = SimpleProcessor(
    cpu_type=CPUTypes.KVM if use_kvm else CPUTypes.ATOMIC,
    isa=ISA.ARM,
    num_cores=num_threads
)

# Create a simple board with a processor and memory.
board = ArmBoard(
    clk_freq="2GHz",
    processor=processor,
    cache_hierarchy=NoCache(),
    memory=SingleChannelDDR3_1600("2GiB"),
    platform=platform,
    release=release
)

# ================ System configuration ends ================

# ================ Workload configuration starts ================

workload = obtain_resource(
    "arm-ubuntu-24.04-npb-is-a", 
    resource_version="1.0.0"
)

if use_checkpoint:
    print(f"Using checkpoint store path: {checkpoint_store_path}")
    workload.set_parameter("checkpoint", checkpoint_store_path)

if use_kvm:
    addr_mode = " --addr=0x10010000 "
else:
    addr_mode = " "

workload.set_parameter("readfile_contents",
rf"""#!/bin/bash
# Set the number of threads to use
export OMP_NUM_THREADS={num_threads}
# Set the OMP scheduler to static as suggested by the LoopPoint paper
export OMP_SCHEDULE="static"

# Disable ASLR to ensure consistent memory addresses
echo 12345 | sudo -S bash -c '
  echo 0 > /proc/sys/kernel/randomize_va_space
  echo -n "ASLR setting: "
  cat /proc/sys/kernel/randomize_va_space
'

# Run the benchmark
BENCHMARK_CMD='/home/gem5/NPB3.4-OMP/bin/is.A.x'
PID=$(echo 12345 | sudo -S bash -c "
  $BENCHMARK_CMD > /tmp/cg_stdout.log 2>&1 &
  echo \$!
")

echo "Started benchmark with PID: $PID"

# Wait for the benchmark to initialize
sleep 0.05

# Pause the benchmark
echo 12345 | sudo -S kill -SIGSTOP $PID

# Collect the memory map of the process
echo 12345 | sudo -S cat /proc/$PID/maps > process_map.txt

# Write the memory map to host
m5{addr_mode}writefile process_map.txt
# Exit the simulation
m5{addr_mode}exit
""")


board.set_workload(workload)

# ================ Workload configuration ends ================

# ================ Exit event handler starts ================

# The disk image we are using in this script will trigger two exit events
# before reading the `readfile_contents` script. The first exit event is 
# triggered after booting up the kernel, and the second exit event is triggered
# before reading the `readfile_contents` script.
# In this example, we will ignore the first exit event and take a checkpoint
# at the second exit event if `--use-checkpoint` is not set.
# For more information about the disk image, please refer to the gem5 resource
# documentation:
# https://resources.gem5.org/resources/arm-ubuntu-24.04-npb-is-a?database=gem5-resources&version=1.0.0

def exit_event_handler():
    # This is a generator function that will be called when an exit event 
    # is triggered. It will yield False to indicate that the simulation
    # should continue running.
    global checkpoint_store_path
    global use_checkpoint
    if not use_checkpoint:
        print("Ignore bootup exit event.")
        yield False
        print("Before reading the readfile_contents, taking a checkpoint.")
        print("Checkpoint store path:", checkpoint_store_path.as_posix())
        checkpoint_store_path.mkdir(parents=True, exist_ok=True)
        m5.checkpoint(checkpoint_store_path.as_posix())
        yield False
    # This m5 exit is triggered by the `m5 exit` command in the 
    # readfile_contents script.
    yield True

# ================ Exit event handler ends ================

# ================ Setup simulator starts ================

simulator = Simulator(
    board=board,
    on_exit_event={
        # Register the exit event handler to handle exit events.
        ExitEvent.EXIT: exit_event_handler()
    }
)

# ================ Setup simulator ends ================

# Run the simulation
simulator.run()

# After this point, there should be a file named 'process_map.txt' in the gem5 
# output directory, containing the memory map of the process.
print("Simulation completed.")
