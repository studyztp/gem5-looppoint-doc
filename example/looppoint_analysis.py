from pathlib import Path
import argparse

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
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.simulate.exit_event import ExitEvent
from gem5.utils.requires import requires
from gem5.isas import ISA

from m5.objects import LooppointAnalysis, LooppointAnalysisManager, AddrRange

import json
import m5

parser = argparse.ArgumentParser(
    description=(
        "Run a simulation with LoopPoint Analysis to analyze loop execution"
        " and basic block execution in a program."
    )
)

parser.add_argument(
    "-j", "--extracted-addr-ranges-json-file-path", 
    type=str, required=True,
    help="Path to the JSON file containing extracted address ranges."
)
parser.add_argument(
    "--start-tracking", action="store_true",
    help=(
        "If set, the simulation will start tracking loops and basic blocks "
        "from the beginning. If not set, it will only analyze the workload "
        "after the first workbegin event."
    )
)
parser.add_argument(
    "-rc", "--restore-checkpoint-path",
    type=str, default=None,
    help=(
        "Path to the checkpoint to restore from. "
        "If provided, the simulation will start from this checkpoint."
    )
)
parser.add_argument(
    "-sc", "--checkpoint-store-path", 
    type=str, default=None,
    help=(
        "Path to store the checkpoint after the simulation."
        " If not provided, no checkpoint will be stored."
    )
)
parser.add_argument(
    "-r", "--region-length",
    type=int, default=200_000_000,
    help=(
        "Length of the region to analyze in bytes. "
        "Default is 200 million instructions as we are using 2 threads and the"
        " LoopPoint paper suggests 100 million instructions per thread."
    )
)
parser.add_argument(
    "-o", "--output-json-file-path",
    type=str, default="loop_point_analysis_output.json",
    help=(
        "Path to the output JSON file where the LoopPoint Analysis results "
        "will be saved. Default is 'loop_point_analysis_output.json'."
    )
)
    
args = parser.parse_args()

requires(isa_required=ISA.ARM)

extracted_addr_ranges_json_file_path = Path(args.extracted_addr_ranges_json_file_path)
if not extracted_addr_ranges_json_file_path.is_file():
    raise FileNotFoundError(
        "Cannot read extracted address ranges JSON file: "
        f"{extracted_addr_ranges_json_file_path}"
    )
start_tracking = args.start_tracking
take_checkpoint = args.checkpoint_store_path is not None
use_checkpoint = args.restore_checkpoint_path is not None
restore_checkpoint_path = Path(args.restore_checkpoint_path) if args.restore_checkpoint_path else None
checkpoint_store_path = Path(args.checkpoint_store_path) if args.checkpoint_store_path else None
region_length = args.region_length

output_file = Path(args.output_json_file_path)
with open(output_file, "w") as f:
    # Initialize the output file with an empty JSON object
    json.dump({}, f)

# ================ System configuration starts ================
num_threads = 2

release = ArmDefaultRelease().for_kvm()
platform = VExpress_GEM5_V1()
processor = SimpleProcessor(
    # We have to use ATOMIC CPU type here because KVM cannot collect the
    # information needed for LoopPoint Analysis.
    cpu_type=CPUTypes.ATOMIC,
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
    print(
        f"Using checkpoint restore path: {restore_checkpoint_path.as_posix()}"
    )
    workload.set_parameter("checkpoint", restore_checkpoint_path)

workload.set_parameter("readfile_contents",
f"""#!/bin/bash
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
sudo /home/gem5/NPB3.4-OMP/bin/is.A.x 

# Exit the simulation
m5 exit

""")

board.set_workload(workload)

# ================ Workload configuration ends ================

# ================ Setup LoopPoint Analysis probes starts ================

# get the loop ranges and basic block ranges from the JSON file
with open(extracted_addr_ranges_json_file_path, 'r') as f:
    extracted_ranges = json.load(f)

loop_range = extracted_ranges["loop_range"]
loop_range = AddrRange(start=int(loop_range[0],16), end=int(loop_range[1],16))
excluded_ranges = []

for lib_path, addr_ranges in extracted_ranges["excluded"].items():
    for addr_range in addr_ranges:
        excluded_ranges.append(
            AddrRange(start=int(addr_range[0], 16), end=int(addr_range[1], 16))
        )

manager = LooppointAnalysisManager()
manager.region_length = region_length

all_trackers = []

for core in board.get_processor().get_cores():
    tracker = LooppointAnalysis()
    tracker.looppoint_analysis_manager = manager
    tracker.bb_valid_addr_range = AddrRange(0, 0)
    tracker.marker_valid_addr_range = loop_range
    tracker.bb_excluded_addr_ranges = excluded_ranges
    if not start_tracking:
        tracker.if_listening = False
    core.core.probe_listener = tracker
    all_trackers.append(tracker)

# ================ Setup LoopPoint Analysis probes ends ================

# ================ Exit event handler starts ================

region_id = 0

def to_hex_map(the_map):
    new_map = {}
    for key, value in the_map.items():
        new_map[hex(key)] = value
    return new_map

def get_data(dump_bb_inst_map):
    global region_id
    global manager
    global all_trackers

    global_bbv = manager.getGlobalBBV()
    global_bbv = to_hex_map(global_bbv)

    loop_counter = to_hex_map(manager.getBackwardBranchCounter())
    most_recent_loop = hex(manager.getMostRecentBackwardBranchPC())

    region_info = {
        "global_bbv" : global_bbv,
        "global_length" : manager.getGlobalInstCounter(),
        "global_loop_counter" : loop_counter,
        "most_recent_loop" : most_recent_loop,
        "most_recent_loop_count" : manager.getMostRecentBackwardBranchCount()
    }
    if dump_bb_inst_map:
        region_info["bb_inst_map"] = to_hex_map(manager.getBBInstMap())

    for tracker in all_trackers:
        tracker.clearLocalBBV()

    manager.clearGlobalBBV()
    manager.clearGlobalInstCounter()
    with open(output_file, "r") as f:
        data = json.load(f)
    data[region_id] = region_info
    with open(output_file, "w") as f:
        json.dump(data, f, indent=4)
    region_id += 1
    return region_id

def simpoint_handler():
    while True:
        current_region_id = get_data(False)
        print(f"Region {current_region_id-1} finished")
        yield False

def workbegin_handler():
    global checkpoint_store_path
    global use_checkpoint
    global take_checkpoint
    if take_checkpoint:
        print("Checkpoint store path:", 
                checkpoint_store_path.as_posix())
        checkpoint_store_path.mkdir(parents=True, exist_ok=True)
        m5.checkpoint(checkpoint_store_path.as_posix())
    print("Starting LoopPoint Analysis trackers.")
    global all_trackers
    for tracker in all_trackers:
        tracker.startListening()
    print("LoopPoint Analysis trackers started.")
    yield False

def workend_handler():
    global all_trackers
    print("Stopping LoopPoint Analysis trackers.")
    for tracker in all_trackers:
        tracker.stopListening()
    print("get to the end of the workload")
    current_region_id = get_data(True)
    print(f"Region {current_region_id-1} finished")
    yield True

# ================ Exit event handler ends ================

# ================ Setup simulator starts ================

simulator = Simulator(
    board=board,
    on_exit_event={
        ExitEvent.SIMPOINT_BEGIN:simpoint_handler(),
        ExitEvent.WORKBEGIN: workbegin_handler(),
        ExitEvent.WORKEND: workend_handler()
    }
)

# ================ Setup simulator ends ================

simulator.run()

print("Simulation completed.")

