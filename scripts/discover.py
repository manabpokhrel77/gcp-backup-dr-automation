import json
import os
from pathlib import Path

from google.cloud import asset_v1
from google.cloud import backupdr_v1
from google.api_core.exceptions import GoogleAPICallError


PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "manab-test-project")

REGIONS = (
    "northamerica-northeast1",
    "northamerica-northeast2",
)

BASE_DIR = Path(__file__).resolve().parent.parent


def discover_vms():
    client = asset_v1.AssetServiceClient()

    request = asset_v1.SearchAllResourcesRequest(
        scope=f"projects/{PROJECT_ID}",
        asset_types=["compute.googleapis.com/Instance"],
        read_mask="name,displayName,project,location,state,labels,effectiveTags",
        page_size=500,
    )

    results = client.search_all_resources(request=request)

    vms = []

    for vm in results:
        vms.append(
            asset_v1.ResourceSearchResult.to_dict(vm)
        )

    return vms


def discover_backup_plans():
    client = backupdr_v1.BackupDRClient()

    plans = []

    for region in REGIONS:
        parent = f"projects/{PROJECT_ID}/locations/{region}"

        request = backupdr_v1.ListBackupPlansRequest(
            parent=parent
        )

        for plan in client.list_backup_plans(request=request):
            plans.append(
                {
                    "name": plan.name,
                    "state": backupdr_v1.BackupPlan.State(plan.state).name,
                    "resource_type": plan.resource_type,
                    "backup_vault": plan.backup_vault,
                    "location": region,
                }
            )

    return plans


def main():
    try:
        vms = discover_vms()
        plans = discover_backup_plans()

        if not vms:
            raise RuntimeError(
                "No VMs discovered. Refusing to continue."
            )

        if not plans:
            raise RuntimeError(
                "No backup plans discovered. Refusing to continue."
            )

        output = {
            "project": PROJECT_ID,
            "vms": vms,
            "backup_plans": plans,
        }

        output_file = BASE_DIR / "discovery.json"

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(output, file, indent=2)

        print(f"Discovered {len(vms)} VMs")
        print(f"Discovered {len(plans)} backup plans")
        print(f"Saved discovery results to {output_file}")

    except (GoogleAPICallError, RuntimeError) as error:
        raise SystemExit(
            f"Discovery failed: {error}"
        )


if __name__ == "__main__":
    main()