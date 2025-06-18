# Applying LoopPoint in gem5

## Introduction

Simulating an entire realistic workload can be infeasible.  
The state-of-the-art [LoopPoint](https://ieeexplore.ieee.org/document/9773236) method enables selective simulation of multi-threaded workloads using sampling, allowing us to estimate their runtime efficiently.  
LoopPoint was originally proposed and evaluated in a non-full-system environment, where the operating system is not involved.  
In full-system simulation, however, we must consider additional factors, such as Address Space Layout Randomization (ASLR), to correctly apply the methodology.

In this tutorial, we will demonstrate how to apply the LoopPoint methodology in a full-system environment with the gem5 simulator version 24.1.0.3.  

There are 3 main steps in using targeted sampling methodology:

1. program analysis and sample selection
2. locating the samples
4. running the samples

## Program Analysis

The LoopPoint methodology uses loops to define works and locate regions.
We use the address ranges of the program to identify reliable loops and exclude meaningless works, such as synchronization. 

First, we need to obtain the process's address map.  
This helps determine:
- which address ranges to consider for sample markers,  
- which to include in the basic block vector for identifying program phases, and  
- which to avoid to exclude useless work such as spin loops used for synchronization.

Then, we ensure that all markers come from the application’s own code.  
External libraries should still be captured in the basic block vector analysis, while useless work should be excluded from both.  
After getting the marker and basic block analysis, we will need to select the samples through k-means clustering as the LoopPoint paper shows.  
gem5 guarantees support the analysis of markers and basic block vectors with custom parameters, such as which to include or exclude, and for tracking the program counter once the marker has been identified.

After getting the results from the analysis, we will need to select the samples offline based on the results.

In this tutorial, we will use the workload `IS` from NPB class A in the gem5 resource with a simple ARM board with 2 cores and 2 threads to demonstrate how to perform the program analysis for the LoopPoint methodology in gem5.
We will project the basic block vectors to dim=15 using PCA and use k-means clustering with k=2 as our *demonstration* sample selection method.  
This setting fits this example's case because NPB benchmark `IS` with class A input is small enough to complete within seconds on real hardware, so it does not have enough regions to justify a larger value of k to achieve a meaningful speedup when applying the sampling methodology.
You can always change the selection method.

#### Some things to remember

1. Throughout all runs, the number of threads and cores needs to be the same for the workload.  
2. Throughout all runs, the size of the memory needs to be the same.  
3. Throughout all runs, there cannot be any software changes, including any command changes to the system or the workloads. Getting the process's address map is the only exception.

### Getting Process's Address Map

As mentioned before, first, we need to get the mmap of the process of the benchmark.  
In the example script [get_mmap.py](example/get_mmap.py), we change the `readfile_contents` of the workload to:  
1. disable ASLR
2. get the PID of the workload
3. wait until the workload starts properly  
4. write down the mmap of the workload  
5. use `m5 writefile` to write the mmap of the workload from the guest to the host

Depending on your host system, you might have access to KVM or not.  
With or without KVM shouldn't affect the mmap information you get if your simulation environment remains the same.  

In the example script [get_mmap.py](example/get_mmap.py), you can run it with

```bash
[gem5 binary] -re --outdir=kvm-get-mmap-m5out get_mmap.py --use-kvm
```
to 1) take a checkpoint before running the readfile_contents for future restoring and 2) get the process's address map stored in the m5out folder.

You can also run

```bash 
[gem5 binary] -re --outdir=atomic-get-mmap-m5out get_mmap.py
```
to do the same with ATOMIC CPU.

You can also run

```bash
[gem5 binary] -re --outdir=atomic-get-mmap-m5out get_mmap.py --use-checkpoint
```
to restore from the checkpoint taken before to test and see if there are any difference between the process's address map extracted with KVM and ATOMIC CPU.

After the above step, you should get a process's address map that looks like below:

```
00400000-00405000 r-xp 00000000 fe:02 144851                             /home/gem5/NPB3.4-OMP/bin/is.A.x
0041f000-00420000 r--p 0000f000 fe:02 144851                             /home/gem5/NPB3.4-OMP/bin/is.A.x
00420000-00421000 rw-p 00010000 fe:02 144851                             /home/gem5/NPB3.4-OMP/bin/is.A.x
00421000-04642000 rw-p 00000000 00:00 0                                  [heap]
7ff7570000-7ff7580000 ---p 00000000 00:00 0 
7ff7580000-7ff7d80000 rw-p 00000000 00:00 0 
7ff7d80000-7ff7d90000 rw-s 10010000 00:06 1031                           /dev/mem
7ff7d90000-7ff7f2a000 r-xp 00000000 fe:02 39860                          /usr/lib/aarch64-linux-gnu/libc.so.6
7ff7f2a000-7ff7f3d000 ---p 0019a000 fe:02 39860                          /usr/lib/aarch64-linux-gnu/libc.so.6
7ff7f3d000-7ff7f40000 r--p 0019d000 fe:02 39860                          /usr/lib/aarch64-linux-gnu/libc.so.6
7ff7f40000-7ff7f42000 rw-p 001a0000 fe:02 39860                          /usr/lib/aarch64-linux-gnu/libc.so.6
7ff7f42000-7ff7f4e000 rw-p 00000000 00:00 0 
7ff7f50000-7ff7f9f000 r-xp 00000000 fe:02 33439                          /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
7ff7f9f000-7ff7faf000 ---p 0004f000 fe:02 33439                          /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
7ff7faf000-7ff7fb0000 r--p 0004f000 fe:02 33439                          /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
7ff7fb0000-7ff7fb1000 rw-p 00050000 fe:02 33439                          /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
7ff7fbe000-7ff7fe5000 r-xp 00000000 fe:02 39857                          /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
7ff7fee000-7ff7ff2000 rw-p 00000000 00:00 0 
7ff7ff8000-7ff7ffa000 rw-p 00000000 00:00 0 
7ff7ffa000-7ff7ffb000 r--p 00000000 00:00 0                              [vvar]
7ff7ffb000-7ff7ffc000 r-xp 00000000 00:00 0                              [vdso]
7ff7ffc000-7ff7ffe000 r--p 0002e000 fe:02 39857                          /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
7ff7ffe000-7ff8000000 rw-p 00030000 fe:02 39857                          /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
7ffffdf000-8000000000 rw-p 00000000 00:00 0                              [stack]
```

In this example process's map, we care about two address ranges:
- the executable code range of our program: ```00400000-00405000```
- the openMP library address range ```7ff7f50000-7ff7fb1000```

For this example, we provided a python script, [extract_addr_range_from_mmap.py](example/extract_addr_range_from_mmap.py) to help us to extract these address ranges automatically.

With running the command:

```bash
python3 example/extract_addr_range_from_mmap.py -m example-output/atomic-get-mmap-output/process_map.txt -b /home/gem5/NPB3
.4-OMP/bin/is.A.x
```

You should be able to get a json file that looks like below:

```json
{
  "loop_range": [
    "0000000000400000",
    "0000000000405000"
  ],
  "excluded": {
    "/usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0": [
      [
        "0000007ff7f50000",
        "0000007ff7fb1000"
      ]
    ]
  }
}
```

### LoopPoint Analysis

[looppoint_analysis.py](example/looppoint_analysis.py) is an example script.
Starting from this step, the `readfile_contents` has to be the same.

There are some key things:
- The LoopPoint analysis module only works with ATOMIC CPU.
- The LoopPoint analysis module triggers an `SIMPOINT_BEGIN` exit event after the total simulated instructions match the region length.
- The LoopPoint analysis module does not automatically process the data and output in a format. The user has to dump and reset the counters.

This is by design to provide flexibility.
You can look at the [LooppointAnalysis.py](https://github.com/gem5/gem5/blob/v24.1.0.3/src/cpu/simple/probes/LooppointAnalysis.py) to see what information that you can input, output, and control.

The LoopPoint methodology suggests using `T` * 100 million instructions as using `T` number of threads as the region length.
So, in this example, we will be using 200 million instructions as our region length because we are using 2 threads for the workload.

First, we need to setup the system and workload.
As mentioned above in [Some things to remember](#Some-things-to-remember), some setup has to remind consistent.

Then, we will need to setup the LoopPoint analysis module.
Below is the copy of the part of the code that does this:

```Python
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
```

As shown above, we first need to get the loop range and the excluded ranges from our extracted address ranges.
Then, we make a LoopPointAnalysisManager that will be responsible to manage the trackers and collect data in among all trackers.
We need to have one tracker for each core.
Each tracker is only responsible to collect the information for that core and notify the manager.
The trackers can be turning on and off anytime during the simulation.
If your simulation starts at the place where you want to profile, then make sure that the `tracker.if_listening` is true when setting them up.
In this example here, we give an option to not turn them on at the beginning of the simulation because if we restore the simulation from the checkpoint we take in Section[Program Analysis](#program-analysis), then the simulation is not starting at the ROI of the workload. 
We should turn on the trackers when we reach to the ROI of the workload.

Below is the code of the handlers:

```Python
****
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
```

These are the handler for ROI begin and end. 
When ROI begin is reached, we take a checkpoint if `take_checkpoint` is set.
We can use this checkpoint for future simulations.
Then, we turn on all the trackers to start tracking the core's committed instructions.
When ROI end is reached, we stop all the trackers, collect the information for the last region, then exit the simulation.

As you saw above, we use the function `get_data()` to collect information from the LoopPoint analysis module.

```Python
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
```

As you see in `get_data()`, we need to collect the information and reset the counters by ourself.
The LoopPoint manager and trackers do not do these by their own.
This ensures we have full control of what they are collecting and hwo to format them.
In this example here, we will be collecting the `global_bbv`, `global_length`, `global_loop_counter`, `most_recent_loop`, and `most_recent_loop_count` for every region.
We only collect the `bb_inst_map` at the final region to avoid data redundant. 
We read and output the analysis data from the output file every region instead of recording them in an object to avoid heavy memory usage for bigger workloads.
The information we collect here are essential for performing the LoopPoint methodology, but you can also collect `local_bbv` using the trackers if you want to form your own basic block vectors differently.
Our `global_bbv` cumulative the counts of the basic block among all cores.

After running the example script with some commands like:
```bash
[gem5 binary] -re --outdir=looppoint-analysis-m5out looppoint_analysis.py -j extracted_addr_ranges.json -rc after_boot_checkpoint_store_cpt -sc is_A_workbegin_cpt -o looppoint_analysis_output.json
```
You should have an output json file that looks something like below:

```JSON
    ...
    "11": {
        "global_bbv": {
            "0x402ea4": 1,
            "0x401214": 1,
            "0x402c78": 1,
            "0x7ff7e4bcd8": 1,
            "0x7ff7ffb470": 1,
            "0x7ff7ffb44c": 1,
            "0x7ff7ffb3ac": 1,
            ...
            "0x400eac": 2,
            "0x401d04": 2,
            "0xffffffc01008397c": 15,
            "0x401d00": 2842707
        },
        "global_length": 98886766,
        "global_loop_counter": {
            "0x401208": 10,
            "0x401e64": 5110,
            "0x401f5c": 10240,
            "0x401e00": 10,
            "0x401f34": 5227530,
            "0x401d64": 10240,
            "0x401f60": 20,
            "0x402c10": 1,
            "0x401b68": 20,
            "0x401f58": 10240,
            "0x401d88": 20,
            "0x401ca0": 30690,
            "0x4011f4": 10,
            "0x401be8": 83886080,
            "0x401fc4": 10,
            "0x4025e8": 10,
            "0x402c44": 1,
            "0x401bf4": 20,
            "0x401b60": 20,
            "0x401ed0": 10230,
            "0x401d00": 83886080,
            "0x401b90": 20,
            "0x401cb4": 20440,
            "0x401d04": 20
        },
        "most_recent_loop": "0x402c44",
        "most_recent_loop_count": 1,
        "bb_inst_map": {
            "0x401214": 1,
            "0x402738": 9,
            "0x402714": 9,
            "0x4026cc": 9,
            "0x402684": 9,
            ...
            "0x7ff7ebbce8": 5,
            "0x7ff7ebbcfc": 4,
            "0x7ff7ebb240": 12,
            "0x555556f104": 18
        }
    }
}
```

Now, we can move on to offline representative region selection and marker calculation.


