import argparse
import json
import os
import re

def parse_and_merge_maps(maps_path, binary_path, sync_lib_patterns):
    """
    Read the process memory map file and extract executable code ranges
    for the main binary and specified libraries.

    Returns:
      dict[
      "loop_range": list of (start_hex, end_hex),
      "excluded": dict[
            path -> list of (start_hex, end_hex)
        ]
      ]
      where:
        - "loop_range" contains the executable code ranges for the main binary
        - "excluded" contains regions for the libraries that we should excluded 
            with their respective paths and ranges.
    """
    # regex to parse each line: start-end perms offset dev inode path
    line_re = re.compile(
        r"^([0-9A-Fa-f]+)-([0-9A-Fa-f]+)\s+"  # start-end
        r"(\S+)\s+"                           # perms
        r"\S+\s+\S+\s+\S+\s*"                  # offset, dev, inode
        r"(.*)$"                               # path (may be blank)
    )

    raw = {}
    with open(maps_path, "r") as f:
        for line in f:
            m = line_re.match(line)
            if not m:
                continue
            start_s, end_s, perms, path = m.groups()

            name = os.path.basename(path)
            # match exact binary path and permission, or any sync lib pattern
            if (path == binary_path and "x" in perms) or \
                    any(lib in name for lib in sync_lib_patterns):
                start = int(start_s, 16)
                end   = int(end_s,   16)
                raw.setdefault(path, []).append((start, end))

    # merge contiguous/overlapping ranges
    merged = {}
    for path, regions in raw.items():
        regions.sort(key=lambda x: x[0])
        merged_list = []
        for start, end in regions:
            if not merged_list:
                merged_list.append([start, end])
            else:
                last = merged_list[-1]
                if start <= last[1]:
                    # extend end if overlapping or contiguous
                    last[1] = max(last[1], end)
                else:
                    merged_list.append([start, end])
        if path == binary_path:
            merged["loop_range"] = (
                f"{merged_list[0][0]:016x}",
                f"{merged_list[0][1]:016x}"
            )
        else:
            if "excluded" not in merged:
                merged["excluded"] = {}
            merged["excluded"][path] = [
                (f"{r[0]:016x}", f"{r[1]:016x}") for r in merged_list
            ]

    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Extract and merge exec code ranges from a saved mmap dump"
    )
    parser.add_argument(
        "-m", "--maps-file", type=str, required=True,
        help="Path to the extracted process mmap file"
    )
    parser.add_argument(
        "-b", "--binary", type=str, required=True,
        help=(
            "Full path to your program's executable, "
            "i.e. /home/gem5/NPB3.4-OMP/bin/is.A.x"
        )
    )
    parser.add_argument(
        "-l", "--libs", nargs="+",
        default=["libgomp", "libomp", "pthread"],
        help="Substring patterns for threading runtimes (default: %(default)s)"
    )
    parser.add_argument(
        "-o", "--output", type=str, default="extracted_addr_ranges.json",
        help=(
            "Output file to save the address ranges " 
            "(default: extracted_addr_ranges.json)"
        )
    )
    args = parser.parse_args()

    if not os.path.isfile(args.maps_file):
        parser.error(f"Cannot read maps file: {args.maps_file}")

    merged = parse_and_merge_maps(args.maps_file, args.binary, args.libs)
    if not merged:
        print("No matching executable regions found.")
        return

    with open(args.output, "w") as f:
        json.dump(merged, f, indent=2)

if __name__ == "__main__":
    main()
