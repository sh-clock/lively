#!/usr/bin/env python3
"""sh1_yaml_check.py — fail fast if the workflow YAML is unparseable
(the S19 fix2/fix5 failure class: hand-edits broke the YAML scanner)."""
import sys
try:
    import yaml
except ImportError:
    print("PyYAML not installed — SKIPPED (non-fatal)"); sys.exit(0)
for f in (".github/workflows/sh1-app.yml",):
    try:
        yaml.safe_load(open(f))
        print("YAML OK:", f)
    except Exception as e:
        print("YAML FAIL:", f, e); sys.exit(1)
sys.exit(0)
