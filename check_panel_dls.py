#! /usr/bin/env python
"""
Check DLS irradiance at every reflectance panel capture in each flight.

A panel capture with any band <= 0 means the DLS pose model failed: the sun was
more than 90 deg off the sensor normal (aircraft canted while shooting the panel),
so the direct-beam term went negative. Any flight calibrated against such a capture
has a corrupted per-band correction factor.

Finds panels by trigger method (0 = manual), so it catches both pre- and post-flight
panels regardless of filename. One batched exiftool call per flight keeps it fast
over the network.

Usage:
    ./check_panel_dls.py /media/U/drones/_missions/20250702_wacNorth/images/flight2 [more dirs...]

Run inside the micasense conda env with PYTHONPATH set to the imageprocessing repo.
"""

import glob
import os
import re
import subprocess
import sys

import micasense.capture as capture


def panel_prefixes(flight_dir):
    """Path prefixes (minus _N.tif) for every manually-triggered capture."""
    band1 = sorted(glob.glob(os.path.join(flight_dir, "**", "IMG_*_1.tif"),
                             recursive=True))
    if not band1:
        return []

    # one exiftool call for all band-1 files; -T -TriggerMethod prints one value per line, in order
    out = subprocess.run(
        ["exiftool", "-T", "-TriggerMethod", *band1],
        capture_output=True, text=True).stdout.splitlines()

    prefixes = []
    for path, trig in zip(band1, out):
        if trig.strip() == "0":
            prefixes.append(re.sub(r"_1\.tif$", "", path))
    return prefixes


def check(flight_dir):
    label = flight_dir.rstrip("/").replace("/media/U/drones/_missions/", "")
    print(label, flush=True)

    if not os.path.isdir(flight_dir):
        print("    MISSING DIRECTORY\n", flush=True)
        return

    prefixes = panel_prefixes(flight_dir)
    if not prefixes:
        print("    no manually-triggered panel captures found\n", flush=True)
        return

    for prefix in prefixes:
        bands = sorted(glob.glob(prefix + "_*.tif"))
        name = os.path.basename(prefix)
        try:
            irr = capture.Capture.from_filelist(bands).dls_irradiance()
        except Exception as e:
            print(f"    {name}: FAILED ({e})", flush=True)
            continue
        vals = " ".join(f"{v:7.3f}" for v in irr)
        bad = "   <-- BAD POSE" if any(v <= 0 for v in irr) else ""
        print(f"    {name}: [{vals} ]{bad}", flush=True)
    print(flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for d in sys.argv[1:]:
        check(d)