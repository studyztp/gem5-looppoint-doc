# Applying LoopPoint in gem5

## Introduction

Simulating an entire realistic workload can be infeasible.  
The state-of-the-art [LoopPoint](https://ieeexplore.ieee.org/document/9773236) method enables selective simulation of multi-threaded workloads using sampling, allowing us to estimate their runtime efficiently.  
LoopPoint was originally proposed and evaluated in a non-full-system environment, where the operating system is not involved.  
In full-system simulation, however, we must consider additional factors, such as Address Space Layout Randomization (ASLR), to correctly apply the methodology.

In this tutorial, we will demonstrate how to apply the LoopPoint methodology in a full-system environment with the gem5 simulator.  

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
We will project the basic block vectors to dim=15 using PCA and use k-means clustering with k=10 as our *demonstration* sample selection method.  
This setting fits this example's case because NPB benchmark `IS` with class A input is small enough to complete within seconds on real hardware, so it does not have enough regions to justify a larger value of k to achieve a meaningful speedup when applying the sampling methodology.
You can always change the selection method.

Some things to remember:
1. Throughout all runs, the number of threads and cores need to be the same for the workload.  
2. Throughout all runs, the size of the memory needs to be the same.  
3. Throughout all runs, there cannot be any software changes, including any command changes to the system or the workloads. The process of getting the process's address map is the only exception.

### Getting Process's Address Map

As mentioned before, first, we need to get the mmap of the process of the benchmark.  
In the example script [get_mmap.py](example/get_mmap.py), we change the `readfile_contents` of the workload to:  
1. disable ASLR
2. get the PID of the workload
3. wait until the workload starts properly  
4. pause the workload and write down the mmap of the workload  
5. use `m5 writefile` to write the mmap of the workload from the guest to the host

Depending on your host system, you might have access to KVM or not.  
With or without KVM shouldn't affect the mmap information you get if your simulation environment remains the same.  

In the example script [get_mmap.py](example/get_mmap.py), you can run it with

```bash
[gem5 binary] -re kvm-get-mmap-m5out get_mmap.py --use-kvm
```
to 1) take a checkpoint before running the readfile_contents for future restoring and 2) get the process's address map stored in the m5out folder.

You can also run

```bash 
[gem5 binary] -re atomic-get-mmap-m5out get_mmap.py
```
to do the same with ATOMIC CPU.

You can also run

```bash
[gem5 binary] -re atomic-get-mmap-m5out get_mmap.py --use-checkpoint
```
to restore from the checkpoint taken before to test and see if there are any difference between the process's address map extracted with KVM and ATOMIC CPU.

After the above step, you should get a process's address map that looks like below:

```
00400000-00405000 r-xp 00000000 fe:02 146904                             /home/gem5/NPB3.4-OMP/bin/is.A.x
0041f000-00420000 r--p 0000f000 fe:02 146904                             /home/gem5/NPB3.4-OMP/bin/is.A.x
00420000-00421000 rw-p 00010000 fe:02 146904                             /home/gem5/NPB3.4-OMP/bin/is.A.x
00421000-04621000 rw-p 00000000 00:00 0 
04621000-04642000 rw-p 00000000 00:00 0                                  [heap]
fffff7400000-fffff7410000 ---p 00000000 00:00 0 
fffff7410000-fffff7c10000 rw-p 00000000 00:00 0 
fffff7d70000-fffff7d80000 rw-s 00000000 00:05 151                        /dev/gem5_bridge
fffff7d80000-fffff7f1a000 r-xp 00000000 fe:02 39868                      /usr/lib/aarch64-linux-gnu/libc.so.6
fffff7f1a000-fffff7f2d000 ---p 0019a000 fe:02 39868                      /usr/lib/aarch64-linux-gnu/libc.so.6
fffff7f2d000-fffff7f30000 r--p 0019d000 fe:02 39868                      /usr/lib/aarch64-linux-gnu/libc.so.6
fffff7f30000-fffff7f32000 rw-p 001a0000 fe:02 39868                      /usr/lib/aarch64-linux-gnu/libc.so.6
fffff7f32000-fffff7f3e000 rw-p 00000000 00:00 0 
fffff7f40000-fffff7f91000 r-xp 00000000 fe:02 11830                      /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
fffff7f91000-fffff7faf000 ---p 00051000 fe:02 11830                      /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
fffff7faf000-fffff7fb0000 r--p 0005f000 fe:02 11830                      /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
fffff7fb0000-fffff7fb1000 rw-p 00060000 fe:02 11830                      /usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0
fffff7fbe000-fffff7fe5000 r-xp 00000000 fe:02 39865                      /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
fffff7fed000-fffff7ff1000 rw-p 00000000 00:00 0 
fffff7ff7000-fffff7ff9000 rw-p 00000000 00:00 0 
fffff7ff9000-fffff7ffb000 r--p 00000000 00:00 0                          [vvar]
fffff7ffb000-fffff7ffc000 r-xp 00000000 00:00 0                          [vdso]
fffff7ffc000-fffff7ffe000 r--p 0002e000 fe:02 39865                      /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
fffff7ffe000-fffff8000000 rw-p 00030000 fe:02 39865                      /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
fffffffdf000-1000000000000 rw-p 00000000 00:00 0                         [stack]
```

In this example process's map, we care about two address ranges:
- the executable code range of our program: ```00400000-00405000```
- the openMP library address range ```fffff7f40000-fffff7fb1000```

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
    [
      "0000000000400000",
      "0000000000405000"
    ]
  ],
  "excluded": {
    "/usr/lib/aarch64-linux-gnu/libgomp.so.1.0.0": [
      [
        "0000fffff7f40000",
        "0000fffff7fb1000"
      ]
    ]
  }
}
```

### LoopPoint Analysis


