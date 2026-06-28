#!/usr/bin/env python3
import argparse
from pathlib import Path

from common import atomic_write_json, load_json
from dry_run_fixture import build_audio

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--plan", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
atomic_write_json(args.output, build_audio(load_json(args.config), load_json(args.plan)))
print(args.output)
