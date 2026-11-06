#!/usr/bin/env python3
"""Export approved, tagged, running GCE VMs as Terraform JSON.

Requirements: pip install google-cloud-asset
Authentication: Application Default Credentials (prefer WIF in CI).

Scope is the intersection of:
  1. Effective Resource Manager tag on the VM (inherited project tags count).
  2. Explicit approved VM allowlist.
  3. RUNNING status (optional via --include-stopped).

This tool does NOT determine existing backup coverage or select backup plans.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from google.cloud import asset_v1

INSTANCE_RE = re.compile(r"^//compute\.googleapis\.com/projects/([^/]+)/zones/([^/]+)/instances/([^/]+)$")


def load_approved(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Approval file must be a non-empty JSON array")
    approved = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Every approval entry must be an object")
        fields = ("project_id", "zone", "vm_name", "backup_plan")
        if any(not isinstance(entry.get(f), str) or not entry[f].strip() for f in fields):
            raise ValueError(f"Each approval requires nonempty {', '.join(fields)}")
        key = (entry["project_id"], entry["zone"], entry["vm_name"])
        if key in approved:
            raise ValueError(f"Duplicate approved VM: {key}")
        approved[key] = entry["backup_plan"]
    return approved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True, help="Numeric GCP organization ID")
    parser.add_argument("--tag-key", required=True, help="Namespaced tag key, e.g. 123456789012/backup-scope")
    parser.add_argument("--tag-value", required=True, help="Namespaced tag value, e.g. 123456789012/backup-scope/enabled")
    parser.add_argument("--approved", required=True, type=Path, help="Reviewed VM + backup plan allowlist JSON")
    parser.add_argument("--output", default="in_scope.auto.tfvars.json", type=Path)
    parser.add_argument("--include-stopped", action="store_true")
    args = parser.parse_args()

    approved = load_approved(args.approved)
    client = asset_v1.AssetServiceClient()
    request = asset_v1.SearchAllResourcesRequest(
        scope=f"organizations/{args.org_id}",
        asset_types=["compute.googleapis.com/Instance"],
        read_mask="name,display_name,project,location,state,effective_tags",
        page_size=500,
    )

    selected = {}
    seen = set()
    # Search is read-only. Never generate a partial Terraform input on an API error.
    for vm in client.search_all_resources(request=request):
        match = INSTANCE_RE.fullmatch(vm.name)
        if not match:
            raise ValueError(f"Unexpected Compute Engine asset name: {vm.name}")
        project_id, zone, vm_name = match.groups()
        key = (project_id, zone, vm_name)
        if key not in approved:
            continue
        seen.add(key)
        tagged = any(
            t.namespaced_tag_key == args.tag_key and t.namespaced_tag_value == args.tag_value
            for t in vm.effective_tags
        )
        if not tagged:
            raise ValueError(f"Approved VM lacks required effective tag: {key}")
        if not args.include_stopped and vm.state != "RUNNING":
            raise ValueError(f"Approved VM is not RUNNING ({vm.state}): {key}")
        # Stable for_each key: project/zone/name. Terraform associations need a plan ID.
        resource_key = "/".join(key)
        selected[resource_key] = {
            "project_id": project_id,
            "zone": zone,
            "vm_name": vm_name,
            "instance": vm.name,
            "backup_plan": approved[key],
        }

    missing = set(approved) - seen
    if missing:
        raise ValueError(f"Approved VMs not found in CAI: {sorted(missing)}")
    if len(selected) != len(approved):
        raise ValueError("VM discovery count mismatch; refusing to export")

    output = {"backup_vms": dict(sorted(selected.items()))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"Exported {len(selected)} approved VMs to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
