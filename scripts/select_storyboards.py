#!/usr/bin/env python3
import argparse
from pathlib import Path

from common import atomic_write_json, load_json

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--precheck", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
manifest = load_json(args.manifest)
approved = {item["image_id"] for item in load_json(args.precheck)["storyboard_precheck"] if item["pass"] and item["selected_for_seedance"]}
for item in manifest["storyboards"]:
    item["selected"] = item["image_id"] in approved
atomic_write_json(args.output, manifest)
print(args.output)
