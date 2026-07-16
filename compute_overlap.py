#!/usr/bin/env python
"""
Estimate forward and side overlap for a UAV survey from image EXIF.

AGL height is derived as (mean GPS altitude - ground elevation). Pass --ground
with the site's mean terrain elevation (e.g. read off your DTM). GPS Altitude on
these MicaSense files is absolute (above ellipsoid/sea level), NOT height-above-
ground, so --ground is required for correct footprint on non-sea-level terrain.

Forward overlap: spacing between consecutive along-track triggers.
Side overlap:    perpendicular spacing between adjacent parallel flight lines,
                 found by projecting trigger positions onto the cross-track axis.

RedEdge-P default FOV 55.6 x 43.4 deg; override with --hfov/--vfov.
"""

import argparse
import glob
import math
import os
import subprocess
import sys


def get_metadata(flight_dir):
    band1 = sorted(glob.glob(os.path.join(flight_dir, "**", "IMG_*_1.tif"),
                             recursive=True))
    if not band1:
        return []
    tags = ["-GPSLatitude", "-GPSLongitude", "-GPSAltitude",
            "-DateTimeOriginal", "-TriggerMethod"]
    out = subprocess.run(["exiftool", "-T", "-n", *tags, *band1],
                         capture_output=True, text=True).stdout.splitlines()
    rows = []
    for path, line in zip(band1, out):
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        lat, lon, alt, dt, trig = parts[:5]
        try:
            lat, lon, alt = float(lat), float(lon), float(alt)
        except ValueError:
            continue
        rows.append({"path": path, "lat": lat, "lon": lon, "alt": alt,
                     "dt": dt, "trigger": trig.strip()})
    return rows


def to_local_xy(rows):
    lat0 = sum(r["lat"] for r in rows) / len(rows)
    lon0 = sum(r["lon"] for r in rows) / len(rows)
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    for r in rows:
        r["x"] = (r["lon"] - lon0) * m_lon
        r["y"] = (r["lat"] - lat0) * m_lat


def dominant_heading(rows, max_step):
    """Along-track bearing (mod pi) from close-spaced consecutive triggers."""
    vx = vy = 0.0
    for a, b in zip(rows, rows[1:]):
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        d = math.hypot(dx, dy)
        if d < 1e-6 or d > max_step:      # skip duplicates and turn jumps
            continue
        ang = math.atan2(dy, dx) % math.pi
        vx += math.cos(2 * ang); vy += math.sin(2 * ang)
    return 0.5 * math.atan2(vy, vx)


def cluster_lines(cross_vals, gap):
    """Split sorted cross-track coordinates into lines wherever they jump by >gap."""
    vals = sorted(cross_vals)
    lines = [[vals[0]]]
    for v in vals[1:]:
        if v - lines[-1][-1] > gap:
            lines.append([v])
        else:
            lines[-1].append(v)
    return [sum(l) / len(l) for l in lines]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flight_dir")
    ap.add_argument("--ground", type=float, required=True,
                    help="mean ground elevation (m) at this site, e.g. from DTM")
    ap.add_argument("--hfov", type=float, default=55.6)
    ap.add_argument("--vfov", type=float, default=43.4)
    args = ap.parse_args()

    rows = get_metadata(args.flight_dir)
    survey = [r for r in rows if r["trigger"] != "0"]
    if len(survey) < 3:
        print("Not enough survey captures found.")
        return
    to_local_xy(survey)

    mean_gps_alt = sum(r["alt"] for r in survey) / len(survey)
    mean_agl = mean_gps_alt - args.ground
    if mean_agl <= 0:
        print(f"WARNING: computed AGL {mean_agl:.1f} m <= 0. Check --ground value.")

    footprint_len = 2 * mean_agl * math.tan(math.radians(args.vfov) / 2)
    footprint_wid = 2 * mean_agl * math.tan(math.radians(args.hfov) / 2)

    # forward overlap: consecutive along-track gaps (smaller than one footprint)
    fwd_gaps = [math.hypot(b["x"]-a["x"], b["y"]-a["y"])
                for a, b in zip(survey, survey[1:])
                if math.hypot(b["x"]-a["x"], b["y"]-a["y"]) < footprint_len]
    mean_fwd = sum(fwd_gaps) / len(fwd_gaps) if fwd_gaps else float("nan")
    fwd_overlap = 1 - mean_fwd / footprint_len

    # side overlap: cluster onto cross-track axis
    heading = dominant_heading(survey, footprint_len)
    cross_axis = (-math.sin(heading), math.cos(heading))
    cross_vals = [r["x"]*cross_axis[0] + r["y"]*cross_axis[1] for r in survey]
    # a new line = cross jump greater than a third of footprint width
    centers = cluster_lines(cross_vals, footprint_wid / 3)
    if len(centers) >= 2:
        gaps = [centers[i+1]-centers[i] for i in range(len(centers)-1)]
        mean_line = sum(gaps) / len(gaps)
        side_overlap = 1 - mean_line / footprint_wid
    else:
        mean_line = float("nan"); side_overlap = float("nan")

    print(f"\n{os.path.basename(args.flight_dir.rstrip('/'))}  ({args.flight_dir.rstrip('/')})")
    print(f"  survey captures:       {len(survey)}")
    print(f"  mean GPS altitude:     {mean_gps_alt:7.1f} m (absolute)")
    print(f"  ground elevation:      {args.ground:7.1f} m")
    print(f"  --> mean AGL:          {mean_agl:6.1f} m   ({mean_agl*3.281:.0f} ft)")
    print(f"  heading (along-track): {math.degrees(heading)%180:5.1f} deg")
    print(f"  flight lines detected: {len(centers)}")
    print(f"  footprint (L x W):     {footprint_len:5.1f} x {footprint_wid:5.1f} m")
    print(f"  mean along-track gap:  {mean_fwd:5.2f} m")
    print(f"  --> forward overlap:   {fwd_overlap*100:5.1f} %")
    print(f"  mean line spacing:     {mean_line:5.2f} m")
    print(f"  --> side overlap:      {side_overlap*100:5.1f} %")
    print()


if __name__ == "__main__":
    main()