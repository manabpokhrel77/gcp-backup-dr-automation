import json
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

TFVARS_PATH = "terraform/associations/in_scope.auto.tfvars.json"


def load_previous_configuration():
    result = subprocess.run(
        ["git", "show", f"HEAD:{TFVARS_PATH}"],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
        check=True,
    )

    data = json.loads(result.stdout)

    associations = data.get("vm_associations")

    if not isinstance(associations, dict):
        raise ValueError("Previous Terraform configuration is invalid")

    return associations


def load_generated_configuration():
    path = BASE_DIR / TFVARS_PATH

    with open(path, encoding="utf-8") as file:
        data = json.load(file)

    associations = data.get("vm_associations")

    if not isinstance(associations, dict):
        raise ValueError("Generated Terraform configuration is invalid")

    return associations


def main():
    previous = load_previous_configuration()
    current = load_generated_configuration()

    previous_vms = set(previous)
    current_vms = set(current)

    removed = previous_vms - current_vms

    modified = {
        vm
        for vm in previous_vms & current_vms
        if previous[vm] != current[vm]
    }

    added = current_vms - previous_vms

    print(f"New associations: {len(added)}")
    print(f"Modified associations: {len(modified)}")
    print(f"Removed associations: {len(removed)}")

    if removed:
        raise SystemExit(
            f"BLOCKED: Existing associations disappeared: {sorted(removed)}"
        )

    if modified:
        raise SystemExit(
            f"BLOCKED: Existing associations changed: {sorted(modified)}"
        )

    if not current:
        raise SystemExit(
            "BLOCKED: Generated Terraform associations are empty."
        )

    print("Validation passed: No destructive association changes.")


if __name__ == "__main__":
    main()