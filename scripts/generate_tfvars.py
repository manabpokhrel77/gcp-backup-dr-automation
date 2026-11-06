import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "resolved.json"

OUTPUT_FILE = (
    BASE_DIR
    / "terraform"
    / "associations"
    / "in_scope.auto.tfvars.json"
)

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


def generate_associations(resolved):
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

    if not associations:
        raise ValueError("No associations generated")

    return associations


def main():
    with open(INPUT_FILE, encoding="utf-8") as file:
        resolved = json.load(file)

    associations = generate_associations(resolved)

    output = {
        "vm_associations": dict(sorted(associations.items()))
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
        file.write("\n")

    print(f"Generated {len(associations)} Terraform associations")

    for vm_name, association in output["vm_associations"].items():
        print(f"{vm_name} -> {association['backup_plan']}")

    print(f"\nOutput: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()