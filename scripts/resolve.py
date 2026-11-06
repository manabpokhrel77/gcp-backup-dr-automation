import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DISCOVERY_FILE = BASE_DIR / "discovery.json"
OUTPUT_FILE = BASE_DIR / "resolved.json"

BACKUP_TAG = "manab-test-project/backup-scope/enabled"

PLAN_MAPPING = {
    ("northamerica-northeast1", "production"): "dr-lab-mtl-prod",
    ("northamerica-northeast1", "nonproduction"): "dr-lab-mtl-nonprod",
    ("northamerica-northeast2", "production"): "dr-lab-tor-prod",
    ("northamerica-northeast2", "nonproduction"): "dr-lab-tor-nonprod",
}


def get_region(zone):
    return zone.rsplit("-", 1)[0]


def has_backup_tag(vm):
    for group in vm.get("effective_tags", []):
        for tag in group.get("effective_tags", []):
            if tag.get("tag_value") == BACKUP_TAG:
                return True
    return False


def classify_vm(vm):
    name = vm.get("display_name")
    zone = vm.get("location")
    resource = vm.get("name")

    if not name or not zone or not resource:
        return "UNRESOLVED", "Missing VM information"

    labels = vm.get("labels", {})

    if not has_backup_tag(vm):
        return "OUT_OF_SCOPE", "Backup tag not enabled"

    if labels.get("backup-exclude", "").lower() == "true":
        return "EXCLUDED", "Explicit backup exclusion"

    region = get_region(zone)
    environment = labels.get("environment")

    if (region, environment) not in PLAN_MAPPING:
        return "UNRESOLVED", "Unsupported region or environment"

    return "INCLUDE", "Eligible for backup"


def resolve_plan(vm, plans):
    region = get_region(vm["location"])
    environment = vm["labels"]["environment"]

    expected_plan_id = PLAN_MAPPING[(region, environment)]

    matches = [
        plan
        for plan in plans
        if plan["location"] == region
        and plan["name"].split("/")[-1] == expected_plan_id
        and plan["state"] == "ACTIVE"
        and plan["resource_type"] == "compute.googleapis.com/Instance"
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one active backup plan for "
            f"{vm['display_name']}, found {len(matches)}"
        )

    return matches[0]["name"]


def main():
    with open(DISCOVERY_FILE, encoding="utf-8") as file:
        discovery = json.load(file)

    vms = discovery["vms"]
    plans = discovery["backup_plans"]

    if not isinstance(vms, list) or not vms:
        raise ValueError("VM inventory is empty or invalid")

    if not isinstance(plans, list) or not plans:
        raise ValueError("Backup plan inventory is empty or invalid")

    # Fail closed if tag information was not returned.
    if any("effective_tags" not in vm for vm in vms):
        raise ValueError("Incomplete effective tag discovery")

    included = []
    excluded = []
    out_of_scope = []
    unresolved = []

    for vm in vms:
        decision, reason = classify_vm(vm)
        name = vm.get("display_name", "unknown")

        print(f"VM: {name}")
        print(f"Decision: {decision}")
        print(f"Reason: {reason}")

        if decision == "INCLUDE":
            plan = resolve_plan(vm, plans)

            included.append({
                "vm_name": name,
                "vm_resource": vm["name"],
                "zone": vm["location"],
                "region": get_region(vm["location"]),
                "environment": vm["labels"]["environment"],
                "backup_plan": plan,
            })

            print(f"Backup plan: {plan}")

        elif decision == "EXCLUDED":
            excluded.append(name)

        elif decision == "OUT_OF_SCOPE":
            out_of_scope.append(name)

        else:
            unresolved.append(name)

        print("-" * 50)

    print("\nSUMMARY")
    print(f"Discovered: {len(vms)}")
    print(f"Included: {len(included)}")
    print(f"Excluded: {len(excluded)}")
    print(f"Out of scope: {len(out_of_scope)}")
    print(f"Unresolved: {len(unresolved)}")

    if unresolved:
        raise ValueError(
            f"Unresolved VMs detected: {unresolved}. "
            "Refusing to generate associations."
        )

    if not included:
        raise ValueError(
            "No eligible VMs found. Refusing to generate empty associations."
        )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump({"associations": included}, file, indent=2)

    print(f"\nSaved resolved associations to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()