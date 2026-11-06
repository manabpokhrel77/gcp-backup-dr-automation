import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

INVENTORY_FILE = BASE_DIR / "vm_inventory.json"

BACKUP_TAG = "manab-test-project/backup-scope/enabled"

SUPPORTED_REGIONS = {
    "northamerica-northeast1",
    "northamerica-northeast2"
}


def load_inventory():
    with open(INVENTORY_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_region(zone):
    return zone.rsplit("-", 1)[0]


def has_backup_tag(vm):

    for group in vm.get("effectiveTags", []):

        for tag in group.get("effectiveTags", []):

            if tag.get("tagValue") == BACKUP_TAG:
                return True

    return False


def get_environment(vm):

    labels = vm.get("labels", {})

    return labels.get("environment", "unknown")


def is_excluded(vm):

    labels = vm.get("labels", {})

    return labels.get("backup-exclude", "").lower() == "true"


def classify_vm(vm):

    name = vm.get("displayName")
    zone = vm.get("location")
    resource_name = vm.get("name")

    if not name or not zone or not resource_name:
        return "UNRESOLVED", "Missing VM information"

    region = get_region(zone)

    if not has_backup_tag(vm):
        return "UNRESOLVED", "Backup scope tag missing"

    if is_excluded(vm):
        return "EXCLUDED", "Explicit backup exclusion"

    if region not in SUPPORTED_REGIONS:
        return "UNRESOLVED", "Unsupported region"

    environment = get_environment(vm)

    if environment not in {"production", "nonproduction"}:
        return "UNRESOLVED", "Unknown environment"

    return "INCLUDE", "Eligible for backup"


def main():

    inventory = load_inventory()

    if not isinstance(inventory, list) or not inventory:
        raise ValueError("Inventory is empty or invalid")

    included = []
    excluded = []
    unresolved = []

    print(f"\nDiscovered {len(inventory)} VMs\n")

    for vm in inventory:

        name = vm.get("displayName", "unknown")
        zone = vm.get("location", "")
        region = get_region(zone) if zone else "unknown"
        environment = get_environment(vm)

        decision, reason = classify_vm(vm)

        print(f"VM: {name}")
        print(f"Region: {region}")
        print(f"Environment: {environment}")
        print(f"Decision: {decision}")
        print(f"Reason: {reason}")
        print("-" * 45)

        if decision == "INCLUDE":
            included.append(vm)

        elif decision == "EXCLUDED":
            excluded.append(vm)

        else:
            unresolved.append(vm)

    print("\nSUMMARY")
    print(f"Discovered: {len(inventory)}")
    print(f"Included: {len(included)}")
    print(f"Excluded: {len(excluded)}")
    print(f"Unresolved: {len(unresolved)}")


if __name__ == "__main__":
    main()