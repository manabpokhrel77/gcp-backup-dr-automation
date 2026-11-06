import json
import re
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "resolved.json"

TFVARS_PATH = "terraform/associations/in_scope.auto.tfvars.json"
OUTPUT_FILE = BASE_DIR / TFVARS_PATH

PROJECT_ID = "manab-test-project"

RESOURCE_PREFIX = "//compute.googleapis.com/"

VM_NAME_PATTERN = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")


def normalize_resource(resource):
    if not isinstance(resource, str):
        raise ValueError("VM resource must be a string")

    if not resource.startswith(RESOURCE_PREFIX):
        raise ValueError(f"Unexpected VM resource format: {resource}")

    normalized = resource.removeprefix(RESOURCE_PREFIX)

    parts = normalized.split("/")

    if (
        len(parts) != 6
        or parts[0] != "projects"
        or parts[1] != PROJECT_ID
        or parts[2] != "zones"
        or parts[4] != "instances"
    ):
        raise ValueError(f"Invalid Compute Engine resource: {resource}")

    return normalized


def load_existing_associations():
    """
    Read previously approved Terraform associations
    directly from the current Git commit.
    """

    result = subprocess.run(
        ["git", "show", f"HEAD:{TFVARS_PATH}"],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Unable to read existing Terraform associations from Git. "
            "Refusing to generate configuration."
        )

    existing = json.loads(result.stdout)

    associations = existing.get("vm_associations")

    if not isinstance(associations, dict):
        raise ValueError("Existing Terraform associations are invalid")

    return associations


def generate_discovered_associations(resolved):
    associations = {}

    for vm in resolved["associations"]:
        vm_name = vm["vm_name"]
        region = vm["region"]
        backup_plan = vm["backup_plan"]

        if not VM_NAME_PATTERN.fullmatch(vm_name):
            raise ValueError(f"Invalid VM name: {vm_name}")

        resource = normalize_resource(vm["vm_resource"])

        if vm_name in associations:
            raise ValueError(f"Duplicate VM name: {vm_name}")

        if not backup_plan.startswith(
            f"projects/{PROJECT_ID}/locations/{region}/backupPlans/"
        ):
            raise ValueError(
                f"Backup plan region mismatch for VM {vm_name}"
            )

        associations[vm_name] = {
            "location": region,
            "resource": resource,
            "backup_plan": backup_plan,
        }

    # An empty discovered set is valid.
    # Existing associations will still be preserved.

    return associations


def reconcile_associations(existing, discovered):
    """
    Additive-only reconciliation.

    Existing associations are never automatically
    removed or modified.
    """

    merged = existing.copy()

    added = []
    missing = []
    modified = []

    for vm_name, association in discovered.items():

        if vm_name not in existing:
            merged[vm_name] = association
            added.append(vm_name)

        elif existing[vm_name] != association:
            modified.append(vm_name)

    for vm_name in existing:
        if vm_name not in discovered:
            missing.append(vm_name)

    if modified:
        raise ValueError(
            f"Existing backup associations changed: {modified}. "
            "Manual review required."
        )

    return merged, added, missing


def main():
    with open(INPUT_FILE, encoding="utf-8") as file:
        resolved = json.load(file)

    if not isinstance(resolved.get("associations"), list):
        raise ValueError("Resolved associations must be a list")

    existing = load_existing_associations()

    discovered = generate_discovered_associations(resolved)

    merged, added, missing = reconcile_associations(
        existing,
        discovered,
    )

    # Prevent generating an empty Terraform configuration
    # when neither existing nor discovered associations exist.
    if not merged:
        raise ValueError(
            "No existing or discovered associations. "
            "Refusing to generate empty Terraform configuration."
        )

    output = {
        "vm_associations": dict(sorted(merged.items()))
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
        file.write("\n")

    print("\nBACKUP ASSOCIATION RECONCILIATION")
    print(f"Existing associations: {len(existing)}")
    print(f"Discovered eligible VMs: {len(discovered)}")
    print(f"New associations: {len(added)}")
    print(f"Missing VMs: {len(missing)}")
    print(f"Final associations: {len(merged)}")

    for vm_name in sorted(added):
        print(f"NEW: {vm_name}")

    for vm_name in sorted(missing):
        print(
            f"WARNING: {vm_name} was not discovered as eligible. "
            "Existing association preserved."
        )

    print(f"\nOutput: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()