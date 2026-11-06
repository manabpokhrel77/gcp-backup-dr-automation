# Google Cloud Backup and DR — Python-Driven GitOps Automation

> **Project:** `manab-test-project` · **Repository:** [manabpokhrel77/gcp-backup-dr-automation](https://github.com/manabpokhrel77/gcp-backup-dr-automation) · **Lab record:** 6 November 2026
>
> **Scope:** Automated VM discovery, policy classification, Terraform association management, secure CI/CD, backup verification, and deletion-safety testing. **Restoration was not part of this day's exercise.**

## Contents

1. [Purpose and outcomes](#1-purpose-and-outcomes)
2. [Architecture](#2-architecture)
3. [Prerequisites and environment](#3-prerequisites-and-environment)
4. [Networking and initial VMs](#4-networking-and-initial-vms)
5. [Cloud Asset Inventory](#5-cloud-asset-inventory)
6. [Project-level Resource Manager tag](#6-project-level-resource-manager-tag)
7. [Python discovery, policy resolution, and safety](#7-python-discovery-policy-resolution-and-safety)
8. [Backup vaults and plans](#8-backup-vaults-and-plans)
9. [HCP Terraform infrastructure workspace and authentication](#9-hcp-terraform-infrastructure-workspace-and-authentication)
10. [HCP Terraform associations workspace](#10-hcp-terraform-associations-workspace)
11. [GitHub Actions WIF and CI/CD](#11-github-actions-wif-and-cicd)
12. [End-to-end onboarding of VM05](#12-end-to-end-onboarding-of-vm05)
13. [Backup execution and verification](#13-backup-execution-and-verification)
14. [VM05 deletion and preservation test](#14-vm05-deletion-and-preservation-test)
15. [Verification command reference](#15-verification-command-reference)
16. [Troubleshooting and lessons](#16-troubleshooting-and-lessons)
17. [Security, operational limitations, and cleanup](#17-security-operational-limitations-and-cleanup)
18. [Validation checklist and next steps](#18-validation-checklist-and-next-steps)

---

## 1. Purpose and outcomes

The objective is to automatically protect eligible Google Compute Engine instances with **Google Cloud Backup and DR**, using **Cloud Asset Inventory (CAI)** for discovery, **Python** for classification and additive-only reconciliation, **GitHub Actions** for scheduled automation, and **HCP Terraform** for reviewed infrastructure changes. The project is a hands-on, office-style backup automation lab—not an application deployment and not a restore exercise.

**Design requirements**

- Enable backup automation at the **project level** using an inherited Resource Manager tag (`backup-scope=enabled`).
- Classify VM backup policy by **region** and `environment` label (`production` or `nonproduction`).
- Exclude VMs explicitly labeled `backup-exclude=true`.
- Keep backup data in a vault in the **opposite Canadian region**.
- Generate Terraform association inputs automatically; **never silently remove or modify** existing association entries when discovery changes.
- Require a GitHub PR, merge, HCP Terraform plan, and **manual apply** for new associations.
- Use **Workload Identity Federation (WIF)** instead of long-lived service account keys.
- Verify actual backups, not just configured associations.

### Demonstrated outcomes

- Four initial VMs were created; VM03 was intentionally excluded.
- A fifth VM, VM05, was added to test discovery and onboarding.
- Four eligible VMs—VM01, VM02, VM04, VM05—had **ACTIVE** backup-plan associations and subsequently **ACTIVE** recovery points.
- VM05 was deleted; its association and recovery point still reported **ACTIVE** immediately afterward.
- The post-deletion GitHub Actions run result was **not supplied in the recorded outputs**; the expected no-change/no-PR behavior remains to be verified from that run.

## 2. Architecture

### 2.1 Google Cloud resources

```text
manab-test-project (project number 706329624933)
└── dr-lab-vpc (custom mode)
    ├── Montréal: northamerica-northeast1
    │   └── dr-subnet-mtl (10.10.1.0/24)
    │       ├── dr-test-vm01  production       → dr-lab-mtl-prod
    │       ├── dr-test-vm02  nonproduction    → dr-lab-mtl-nonprod
    │       └── dr-test-vm05  production       → dr-lab-mtl-prod [test VM; deleted]
    └── Toronto: northamerica-northeast2
        └── dr-subnet-tor (10.10.2.0/24)
            ├── dr-test-vm03  production       → EXCLUDED (backup-exclude=true)
            └── dr-test-vm04  production       → dr-lab-tor-prod

Montréal source VMs ──backup plans──> Toronto vault: dr-lab-vault-tor
Toronto source VMs ───backup plans──> Montréal vault: dr-lab-vault-mtl
```

> The original four-VM drawing in the lab notes represents the initial infrastructure. VM05 was added later and subsequently deleted. All test VMs used Debian 12, `e2-micro`, a 10-GB `pd-standard` boot disk, no external IP, and the appropriate custom subnet.

### 2.2 Discovery-to-GitOps control flow

```text
Project Resource Manager tag: backup-scope=enabled
                         │ (inherited by VMs)
                         ▼
                Cloud Asset Inventory
                         │
                         ▼
          GitHub Actions: backup-discovery.yml
                         │
                         ▼
               scripts/discover.py
                 → discovery.json
                         │
                         ▼
                scripts/resolve.py
                  → resolved.json
                  │            │
                  │            └── exclusions + effective tags
                  └── region + environment + policy mapping
                         │
                         ▼
            scripts/generate_tfvars.py
                         │
                         ▼
 terraform/associations/in_scope.auto.tfvars.json
                         │
                         ▼
             scripts/validate_changes.py
                         │
              changed? ───┴─── unchanged?
                 │                  │
              GitHub PR         No PR / no VCS
                 │              Terraform run expected
            Review + merge
                 │
          HCP Terraform VCS run
                 │
            Manual approval
                 │
          Backup plan associations
                 │
            Scheduled/on-demand backup
                 │
          Opposite-region backup vault
```

### 2.3 Organization-level conceptual model

The intended organizational pattern is: **IGM Organization → production and nonproduction projects → project-level `backup-scope=enabled` → eligible VMs**. This lab implements that pattern in **one demonstration project**, using `environment` labels to distinguish production and nonproduction instances. The project tag controls **eligibility**, not backup creation by itself.

## 3. Prerequisites and environment

- Google Cloud CLI (`gcloud`), authenticated to a project with billing enabled.
- Git, GitHub CLI (`gh`) for repository metadata where used, Python virtual environment, and Terraform CLI.
- Access to the GitHub repository and HCP Terraform organization `manab-devops-lab`.
- Permissions to create VPC resources, VMs, Resource Manager tags, Backup and DR resources, service accounts, IAM grants, WIF pools/providers, and HCP Terraform workspaces.
- Local terminal: **macOS zsh**; note shell-specific caveats in [Troubleshooting](#16-troubleshooting-and-lessons).

Set the shell variables:

```bash
export PROJECT_ID="manab-test-project"
export VPC="dr-lab-vpc"
export MTL_REGION="northamerica-northeast1"
export TOR_REGION="northamerica-northeast2"
export MTL_ZONE="northamerica-northeast1-a"
export TOR_ZONE="northamerica-northeast2-a"
gcloud config set project "$PROJECT_ID"
```

Verify billing and existing VMs:

```bash
gcloud billing projects describe "$PROJECT_ID"
gcloud compute instances list --project="$PROJECT_ID" --format="table(name,zone,status,labels)"
```

Enable the APIs used during the lab:

```bash
gcloud services enable compute.googleapis.com cloudasset.googleapis.com \
  cloudresourcemanager.googleapis.com backupdr.googleapis.com \
  iamcredentials.googleapis.com --project="$PROJECT_ID"
```

## 4. Networking and initial VMs

Create a custom-mode VPC and regional subnets:

```bash
gcloud compute networks create "$VPC" \
  --project="$PROJECT_ID" --subnet-mode=custom --bgp-routing-mode=regional

gcloud compute networks subnets create dr-subnet-mtl \
  --project="$PROJECT_ID" --network="$VPC" \
  --region="$MTL_REGION" --range="10.10.1.0/24"

gcloud compute networks subnets create dr-subnet-tor \
  --project="$PROJECT_ID" --network="$VPC" \
  --region="$TOR_REGION" --range="10.10.2.0/24"
```

The initial VM creation commands are shown below to preserve the exact configuration and labels. These are **historical setup commands**, not instructions to rerun against an existing lab.

```bash
gcloud compute instances create dr-test-vm01 \
  --project="$PROJECT_ID" --zone="$MTL_ZONE" --machine-type=e2-micro \
  --subnet=dr-subnet-mtl --no-address \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard \
  --labels=environment=production

gcloud compute instances create dr-test-vm02 \
  --project="$PROJECT_ID" --zone="$MTL_ZONE" --machine-type=e2-micro \
  --subnet=dr-subnet-mtl --no-address \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard \
  --labels=environment=nonproduction

gcloud compute instances create dr-test-vm03 \
  --project="$PROJECT_ID" --zone="$TOR_ZONE" --machine-type=e2-micro \
  --subnet=dr-subnet-tor --no-address \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard \
  --labels=environment=production,backup-exclude=true

gcloud compute instances create dr-test-vm04 \
  --project="$PROJECT_ID" --zone="$TOR_ZONE" --machine-type=e2-micro \
  --subnet=dr-subnet-tor --no-address \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard \
  --labels=environment=production
```

Observed original addresses: VM01 `10.10.1.2`, VM02 `10.10.1.3`, VM03 `10.10.2.2`, VM04 `10.10.2.3`; VM05 later used `10.10.1.4`. IP assignments are observations, not guaranteed for recreated VMs. The CLI warned that boot disks under 200 GB may have lower I/O performance; 10 GB was intentional for the lab.

Verify the VPC, subnets, and instances:

```bash
gcloud compute networks list --project="$PROJECT_ID"
gcloud compute networks describe "$VPC" --project="$PROJECT_ID"
gcloud compute networks subnets list --project="$PROJECT_ID" --network="$VPC"
gcloud compute instances list --project="$PROJECT_ID" \
  --format="table(name,zone,status,networkInterfaces[0].networkIP,labels)"
```

## 5. Cloud Asset Inventory

Cloud Asset Inventory provides a project-scoped list of Compute Engine instances, including their names, regions/zones, labels, state, and effective inherited tags. The original exploratory export was:

```bash
gcloud asset search-all-resources \
  --scope="projects/$PROJECT_ID" \
  --asset-types="compute.googleapis.com/Instance" \
  --read-mask="name,displayName,project,location,state,labels,effectiveTags" \
  --format=json > vm_inventory.json

python -m json.tool vm_inventory.json
```

This manual JSON export was an **exploratory step**. The CI/CD pipeline later performs discovery through `scripts/discover.py` and the Google Cloud APIs. `vm_inventory.json` is a local inspection artifact, not the authoritative Terraform input.

## 6. Project-level Resource Manager tag

The project-level tag is `backup-scope=enabled`. Resource Manager **tags** are different from Compute Engine **labels**: the inherited tag enables project participation, while VM labels select a policy or explicitly exclude a VM.

Retrieve the numeric project ID (corrected shell syntax):

```bash
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
  --format="value(projectNumber)")
echo "$PROJECT_NUMBER"
```

Create the tag key and value, then bind the value to the project:

```bash
gcloud resource-manager tags keys create backup-scope \
  --parent="projects/$PROJECT_NUMBER" \
  --description="Project eligible for automated backups"

gcloud resource-manager tags keys list \
  --parent="projects/$PROJECT_NUMBER" \
  --format="table(name,shortName,namespacedName)"

export TAG_KEY_ID=$(gcloud resource-manager tags keys list \
  --parent="projects/$PROJECT_NUMBER" \
  --filter="shortName=backup-scope" --format="value(name)")

gcloud resource-manager tags values create enabled \
  --parent="$TAG_KEY_ID" --description="Backup automation enabled"

export TAG_VALUE_ID=$(gcloud resource-manager tags values list \
  --parent="$TAG_KEY_ID" \
  --filter="shortName=enabled" --format="value(name)")

gcloud resource-manager tags bindings create \
  --tag-value="$TAG_VALUE_ID" \
  --parent="//cloudresourcemanager.googleapis.com/projects/$PROJECT_NUMBER"
```

After allowing time for propagation, inspect effective tags:

```bash
gcloud asset search-all-resources \
  --scope="projects/$PROJECT_ID" \
  --asset-types="compute.googleapis.com/Instance" \
  --read-mask="displayName,location,labels,effectiveTags" \
  --format=json
```

**Policy:** A VM must belong to a tagged eligible project, have a recognized environment and region, and not carry `backup-exclude=true`. An inherited tag alone does not attach a backup plan.

## 7. Python discovery, policy resolution, and safety

**Source of truth for implementation:** [Repository scripts](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/scripts), [configuration](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/config), and [association Terraform inputs](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/terraform/associations). **Python and Terraform source code are intentionally not duplicated here.**

### 7.1 Scripts and generated artifacts

| File | Purpose |
|---|---|
| `scripts/discover.py` | Discover VMs through Cloud Asset Inventory and read available Backup and DR plans. Writes `discovery.json`. |
| `scripts/resolve.py` | Interpret inherited tag, VM region, `environment`, exclusion label, and policy mapping. Writes `resolved.json`. |
| `scripts/generate_tfvars.py` | Convert eligible resolved VMs into `terraform/associations/in_scope.auto.tfvars.json`; preserve existing associations. |
| `scripts/validate_changes.py` | Reject destructive association changes or removals. |
| `scripts/requirements.txt` | Dependencies for the CI workflow, including Google Cloud Asset and Backup and DR client libraries. |
| `config/backup_policy_mapping.json` | Regional production/nonproduction backup-plan mapping from the original working notes; consult the repo for the current configuration filename and contents. |
| `scripts/exceptions.py` / `scripts/exception.py` | Exception-handling file names mentioned at different stages of the notes; consult the repository to identify the current one. |
| `vm_inventory.json` | Early manually exported CAI inventory for inspection. |

The initial local structure contained `config/`, `scripts/resolve.py`, `scripts/exception.py`, `terraform/infrastructure/`, and `vm_inventory.json`. Later notes proposed a larger layout with `tests/test_discover.py`, `tests/test_resolve.py`, `tests/test_generate_tfvars.py`, `config/backup_policy.yaml`, and two differently named workflow files. **Those later names were illustrative; do not assume every file exists.** The known implemented workflow is `.github/workflows/backup-discovery.yml`.

### 7.2 Additive-only reconciliation

The generator uses the committed Terraform input as a baseline (recorded implementation: `git show HEAD:terraform/associations/in_scope.auto.tfvars.json`). It adds new eligible VMs, but retains entries for VMs that disappear from CAI. The validator blocks removals or modifications.

| Discovery event | Intended automation behavior |
|---|---|
| New eligible VM | Add association to generated tfvars → PR. |
| Existing eligible VM | Leave existing entry unchanged. |
| Explicitly excluded VM | Do not onboard it. |
| Previously associated VM deleted | Keep its existing Terraform entry; no automatic removal. |
| Existing association modified or removed by generation | Validation fails. |

**Limit of this safety property:** Retaining an entry in Git does not prove the live association or backup remains valid. Those are verified separately with `gcloud`.

## 8. Backup vaults and plans

The lab uses two **ACTIVE** vaults and four **ACTIVE** backup plans:

| Backup plan | Plan/source region | Backup destination vault | Destination region |
|---|---|---|---|
| `dr-lab-mtl-prod` | `northamerica-northeast1` | `dr-lab-vault-tor` | `northamerica-northeast2` |
| `dr-lab-mtl-nonprod` | `northamerica-northeast1` | `dr-lab-vault-tor` | `northamerica-northeast2` |
| `dr-lab-tor-prod` | `northamerica-northeast2` | `dr-lab-vault-mtl` | `northamerica-northeast1` |
| `dr-lab-tor-nonprod` | `northamerica-northeast2` | `dr-lab-vault-mtl` | `northamerica-northeast1` |

Recorded rule: `daily-rule`, frequency **DAILY**, configured backup window **23:00–00:00 UTC**, **1-day** retention; vault minimum enforced retention also 1 day. The actual resources were reported ACTIVE. The lab intentionally uses short retention for quick testing; this is not a production retention recommendation.

Check existing plans and vaults before provisioning:

```bash
for REGION in "$MTL_REGION" "$TOR_REGION"; do
  gcloud backup-dr backup-plans list --project="$PROJECT_ID" \
    --location="$REGION" --format=json
  gcloud backup-dr backup-vaults list --project="$PROJECT_ID" \
    --location="$REGION" --format=json
done
```

Vaults/plans are managed in [terraform/infrastructure](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/terraform/infrastructure); associations are managed separately in [terraform/associations](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/terraform/associations).

## 9. HCP Terraform infrastructure workspace and authentication

### 9.1 Workspace

```text
HCP Terraform organization: manab-devops-lab
└── Default Project
    └── gcp-backup-infrastructure-lab
        ├── Working directory: terraform/infrastructure
        ├── Terraform state / variables / runs
        ├── Execution mode: Remote
        └── Manual approval before apply
```

Recorded settings:

| Setting | Value |
|---|---|
| VCS repository | `manabpokhrel77/gcp-backup-dr-automation` |
| Branch | `main` |
| Working directory | `terraform/infrastructure` |
| VCS trigger paths | `terraform/infrastructure/**` |
| Auto-apply for UI/API/VCS runs | Disabled |
| Auto-apply run triggers | Disabled |
| Automatic speculative plans | Enabled |
| Include submodules | Disabled |
| Execution mode | Remote |
| Terraform version selected in workspace | `1.17.1` (recorded setting) |
| Google provider | `hashicorp/google`, `~> 7.0` (recorded configuration) |
| Terraform required version | `>= 1.6.0` (recorded configuration) |

Connect GitHub through **HCP Terraform → Workspace → Settings → Version Control** and set the working directory and path-based triggers above. The normal flow is **feature branch → PR/speculative plan → review → merge → Terraform plan → manual approval → apply**.

### 9.2 HCP Terraform Workload Identity Federation

Create the Terraform service account and WIF pool:

```bash
gcloud iam service-accounts create terraform-backup-lab \
  --project="$PROJECT_ID" --display-name="Terraform Backup Lab"

gcloud iam workload-identity-pools create hcp-terraform-pool \
  --project="$PROJECT_ID" --location=global \
  --display-name="HCP Terraform Pool"

gcloud iam workload-identity-pools describe hcp-terraform-pool \
  --project="$PROJECT_ID" --location=global
```

The provider is named `hcp-terraform-provider`, uses OIDC issuer `https://app.terraform.io`, and maps the subject, HCP organization ID, and HCP workspace ID. Its condition restricts trusted identities to the intended HCP organization and the two workspace IDs. **Do not copy the original placeholder `org-REPLACE_WITH_YOUR_ORG_ID` or `WORKSPACE_ID` into a live command.**

Recorded HCP organization ID: `org-3ZSxvdB2F7bj9r6A`.

Recorded workspace IDs:

- Infrastructure: `ws-yzyDnJBo3jh35ZeX`.
- Associations: `ws-nxpkupK6notEEmTC`.

Example provider creation using the actual recorded IDs:

```bash
gcloud iam workload-identity-pools providers create-oidc hcp-terraform-provider \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool=hcp-terraform-pool \
  --display-name="HCP Terraform OIDC Provider" \
  --issuer-uri="https://app.terraform.io" \
  --attribute-mapping="google.subject=assertion.sub,attribute.terraform_organization_id=assertion.terraform_organization_id,attribute.terraform_workspace_id=assertion.terraform_workspace_id" \
  --attribute-condition="assertion.terraform_organization_id == 'org-3ZSxvdB2F7bj9r6A' && assertion.terraform_workspace_id in ['ws-yzyDnJBo3jh35ZeX', 'ws-nxpkupK6notEEmTC']"
```

This is a **setup reference**, not a command to rerun if the provider already exists. If the provider was initially restricted to one workspace, update it to include the second:

```bash
gcloud iam workload-identity-pools providers update-oidc hcp-terraform-provider \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool=hcp-terraform-pool \
  --attribute-condition="assertion.terraform_organization_id == 'org-3ZSxvdB2F7bj9r6A' && assertion.terraform_workspace_id in ['ws-yzyDnJBo3jh35ZeX', 'ws-nxpkupK6notEEmTC']"
```

Grant `roles/iam.workloadIdentityUser` on `terraform-backup-lab@manab-test-project.iam.gserviceaccount.com` to each **workspace-specific principalSet**:

```bash
for WORKSPACE_ID in ws-yzyDnJBo3jh35ZeX ws-nxpkupK6notEEmTC; do
  gcloud iam service-accounts add-iam-policy-binding \
    terraform-backup-lab@manab-test-project.iam.gserviceaccount.com \
    --project="$PROJECT_ID" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/706329624933/locations/global/workloadIdentityPools/hcp-terraform-pool/attribute.terraform_workspace_id/$WORKSPACE_ID"
done
```

Check organization policy if provider creation is blocked:

```bash
gcloud org-policies describe iam.workloadIdentityPoolProviders \
  --project="$PROJECT_ID" --effective --format=yaml

gcloud org-policies describe iam.workloadIdentityPoolProviders \
  --project="$PROJECT_ID" --format=yaml
```

If organization policy disallows the OIDC provider, involve an organization administrator; do not attempt to bypass policy.

### 9.3 HCP workspace environment variables

Configure these as **Environment variables**, not Terraform input variables, in each workspace:

| Variable | Meaning |
|---|---|
| `TFC_GCP_PROVIDER_AUTH` | `true` |
| `TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL` | `terraform-backup-lab@manab-test-project.iam.gserviceaccount.com` |
| `TFC_GCP_WORKLOAD_PROVIDER_NAME` | Full GCP WIF provider resource name (not a URL invented from the email) |
| `GOOGLE_PROJECT` | `manab-test-project` |

The lab granted the Terraform service account `roles/backupdr.admin` and later `roles/browser` to support resource management and reads. **These are lab permissions and should be reduced to the least privileges needed in production.**

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:terraform-backup-lab@manab-test-project.iam.gserviceaccount.com" \
  --role="roles/backupdr.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:terraform-backup-lab@manab-test-project.iam.gserviceaccount.com" \
  --role="roles/browser"

gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten="bindings[].members" \
  --filter="bindings.members:terraform-backup-lab@manab-test-project.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

Local Terraform checks performed during setup included `terraform login`, `terraform init`, and `terraform plan` from the relevant working directory. HCP Terraform executes actual remote plans/applies after VCS changes.

## 10. HCP Terraform associations workspace

Create a second workspace in the same HCP Terraform organization:

| Setting | Value |
|---|---|
| Workspace | `gcp-backup-associations-lab` |
| Workspace ID | `ws-nxpkupK6notEEmTC` |
| Repository / branch | `manabpokhrel77/gcp-backup-dr-automation` / `main` |
| Working directory | `terraform/associations` |
| Path trigger | `terraform/associations/**` |
| Execution mode | Remote |
| Auto-apply | Disabled |
| Authentication | Same HCP WIF provider and Terraform service account; workspace ID must be authorized |

The association Terraform configuration uses `google_backup_dr_backup_plan_association` with `for_each=var.vm_associations`, sourced from `terraform/associations/in_scope.auto.tfvars.json`. See the repository for the exact HCL rather than duplicating it here.

After applying the first association configuration, the observed results were:

| VM | Region | Plan | Status |
|---|---|---|---|
| `dr-test-vm01` | Montréal | `dr-lab-mtl-prod` | ACTIVE |
| `dr-test-vm02` | Montréal | `dr-lab-mtl-nonprod` | ACTIVE |
| `dr-test-vm04` | Toronto | `dr-lab-tor-prod` | ACTIVE |
| `dr-test-vm03` | Toronto | None (excluded) | Not associated |

Verify:

```bash
gcloud backup-dr backup-plan-associations list \
  --project="$PROJECT_ID" --location="$MTL_REGION"
gcloud backup-dr backup-plan-associations list \
  --project="$PROJECT_ID" --location="$TOR_REGION"
```

## 11. GitHub Actions WIF and CI/CD

### 11.1 GitHub identity and permissions

Create a separate read-only discovery service account:

```bash
gcloud iam service-accounts create github-backup-discovery \
  --project="$PROJECT_ID" \
  --display-name="GitHub Backup DR Discovery"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:github-backup-discovery@manab-test-project.iam.gserviceaccount.com" \
  --role="roles/cloudasset.viewer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:github-backup-discovery@manab-test-project.iam.gserviceaccount.com" \
  --role="roles/backupdr.viewer"
```

Verify project IAM:

```bash
gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten="bindings[].members" \
  --filter="bindings.members:github-backup-discovery@manab-test-project.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

Create the GitHub WIF pool and inspect the repository's immutable IDs:

```bash
gcloud iam workload-identity-pools create github-actions-pool \
  --project="$PROJECT_ID" --location=global \
  --display-name="GitHub Actions Pool"

gh api repos/manabpokhrel77/gcp-backup-dr-automation \
  --jq '{repository_id: .id, owner_id: .owner.id, full_name: .full_name}'
```

Recorded values: GitHub repository ID `1448543786`, owner ID `351683674`. The provider is `github-provider`, with issuer `https://token.actions.githubusercontent.com`. It maps OIDC subject, repository ID, owner ID, and Git ref; its condition restricts tokens to that repository, owner, and `refs/heads/main`.

```bash
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool=github-actions-pool \
  --display-name="GitHub Actions Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_id == '1448543786' && assertion.repository_owner_id == '351683674' && assertion.ref == 'refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding \
  github-backup-discovery@manab-test-project.iam.gserviceaccount.com \
  --project="$PROJECT_ID" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/706329624933/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository_id/1448543786"
```

Verify both:

```bash
gcloud iam workload-identity-pools providers describe github-provider \
  --project="$PROJECT_ID" --location=global \
  --workload-identity-pool=github-actions-pool \
  --format="yaml(name,attributeMapping,attributeCondition)"

gcloud iam service-accounts get-iam-policy \
  github-backup-discovery@manab-test-project.iam.gserviceaccount.com \
  --project="$PROJECT_ID" --format="yaml(bindings)"
```

### 11.2 Workflow behavior

**Workflow file:** [`.github/workflows/backup-discovery.yml`](https://github.com/manabpokhrel77/gcp-backup-dr-automation/blob/main/.github/workflows/backup-discovery.yml).

- Triggers: `workflow_dispatch` and daily schedule at **08:00 UTC**.
- Runtime: Python **3.12**.
- Auth: GitHub OIDC → `github-actions-pool/github-provider` → `github-backup-discovery` service account.
- Workflow permissions: `contents: write`, `id-token: write`, `pull-requests: write`.
- Dependencies installed from `scripts/requirements.txt`.
- Executes discovery → resolution → tfvars generation → destructive-change validation.
- Uses `peter-evans/create-pull-request@v7` and branch `automation/backup-dr-associations` when files change.
- No direct `terraform apply` in GitHub Actions; HCP Terraform runs after PR merge and manual approval.

**Important:** The daily schedule is not instantaneous onboarding. A new VM is discovered at the next scheduled run, or when the workflow is manually dispatched.

### 11.3 Repository and workflow notes

The initial GitHub workflow was committed and pushed on `main` (recorded commit `3ad34ee`); a later dependency fix was pushed (recorded commit `a70ac3c`). The missing `google.cloud.asset_v1` import was fixed by correcting workflow dependencies. The source files in the repository—not the earlier draft directory tree—are authoritative.

## 12. End-to-end onboarding of VM05

VM05 was deliberately created **after** the initial Terraform associations existed, to simulate a new production VM appearing in an eligible project.

```bash
gcloud compute instances create dr-test-vm05 \
  --project="$PROJECT_ID" \
  --zone="$MTL_ZONE" \
  --machine-type=e2-micro \
  --subnet=dr-subnet-mtl \
  --no-address \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --labels=environment=production
```

**Expected GitOps process:** trigger GitHub Actions manually → VM05 discovered → generated tfvars updated → PR → review/merge → HCP Terraform associations plan → manual apply → new association. The user recorded that the resulting VM05 association was ACTIVE; the complete intermediate PR/HCP logs were not reproduced in the conversation.

Observed association after onboarding:

```text
dr-test-vm05
  source region: northamerica-northeast1
  backup plan:   dr-lab-mtl-prod
  backup vault:  dr-lab-vault-tor (Toronto)
  state:         ACTIVE
```

With VM05 present, the intended discovery count was **5 total VMs, 4 eligible, 1 excluded**. VM03 remained excluded.

## 13. Backup execution and verification

### 13.1 Trigger immediate backups

The daily schedule had not yet executed, so the lab explicitly triggered **on-demand backups** through the existing associations. This validates that the associations can create recovery points; it does not itself validate the future scheduled trigger.

```bash
gcloud backup-dr backup-plan-associations trigger-backup dr-test-vm01 \
  --project="$PROJECT_ID" --location="$MTL_REGION" --backup-rule-id=daily-rule

gcloud backup-dr backup-plan-associations trigger-backup dr-test-vm02 \
  --project="$PROJECT_ID" --location="$MTL_REGION" --backup-rule-id=daily-rule

gcloud backup-dr backup-plan-associations trigger-backup dr-test-vm04 \
  --project="$PROJECT_ID" --location="$TOR_REGION" --backup-rule-id=daily-rule

gcloud backup-dr backup-plan-associations trigger-backup dr-test-vm05 \
  --project="$PROJECT_ID" --location="$MTL_REGION" --backup-rule-id=daily-rule
```

A repeated trigger for VM05 returned HTTP **409** (`unable to queue the operation`) while its first backup was already in progress; this did not indicate failure of the initial backup. Operations initially showed `done: false`, and recovery points temporarily showed `CREATING`; later the backup resources all reached `ACTIVE`.

### 13.2 Verified recovery points

**All four backup resources were confirmed ACTIVE** around 20:25–20:27 UTC on 6 November 2026:

| VM | Vault | Data source ID | Backup ID | Verified state |
|---|---|---|---|---|
| VM01 | `dr-lab-vault-tor` | `43b3122de83db88f8568b5edf39eea5ce83771bf` | `92b87724-e7bd-475c-abcf-5f47c75bd1a6` | ACTIVE |
| VM02 | `dr-lab-vault-tor` | `e0d8404d8ad00fd0af3feb75dcfafb3672073c07` | `b3207754-52e5-4072-bc0a-5b94aff776b2` | ACTIVE |
| VM05 | `dr-lab-vault-tor` | `bded5f7762e0f030222d8fc5323b20167e68096d` | `e34c6c1c-218b-42ad-a68f-16aa8701223f` | ACTIVE |
| VM04 | `dr-lab-vault-mtl` | `9ad8b3f4b36bfbdfe30f94f4dd83d3ad9e38f1ab` | `7d5e80d2-89b2-46d6-90fc-821e6d8b66b7` | ACTIVE |

VM03 has no backup association because of `backup-exclude=true`.

### 13.3 Describe a data source and recovery point

```bash
gcloud backup-dr data-sources describe \
  bded5f7762e0f030222d8fc5323b20167e68096d \
  --project="$PROJECT_ID" --location="$TOR_REGION" \
  --backup-vault=dr-lab-vault-tor \
  --format="yaml(name,backupCount,backupConfigInfo.lastBackupState,totalStoredBytes)"

gcloud backup-dr backups list \
  --project="$PROJECT_ID" --location="$TOR_REGION" \
  --backup-vault=dr-lab-vault-tor \
  --data-source=bded5f7762e0f030222d8fc5323b20167e68096d \
  --format="table(name,state,createTime,expireTime)"

gcloud backup-dr backups describe e34c6c1c-218b-42ad-a68f-16aa8701223f \
  --project="$PROJECT_ID" --location="$TOR_REGION" \
  --backup-vault=dr-lab-vault-tor \
  --data-source=bded5f7762e0f030222d8fc5323b20167e68096d \
  --format=yaml
```

The VM05 backup detail showed: `backupType: ON_DEMAND`, `state: ACTIVE`, `resourceSizeBytes: 10737418240` (10 GiB), Debian 12 boot disk, `e2-micro`, label `environment=production`, network `dr-lab-vpc`, subnet `dr-subnet-mtl`, and source VM instance numeric ID `755283775986043409`. It had `backupRetentionInheritance: INHERIT_VAULT_RETENTION` and an expiry of **2026-11-07T20:27:02.567083029Z**. `resourceSizeBytes` is the protected resource size, not necessarily the billed physical backup storage.

### 13.4 Check backup operations

The original operation IDs recorded in the lab:

```bash
for ENTRY in \
  "northamerica-northeast1:operation-1793996707471-65fa1687a2183-dc4c4d59-eda97c49" \
  "northamerica-northeast1:operation-1793996724770-65fa1698217b7-eda280bc-7fa1dd53" \
  "northamerica-northeast1:operation-1793996725366-65fa1698b2fcd-55132725-5400c25c" \
  "northamerica-northeast2:operation-1793996726039-65fa1699572d3-01fa7b4c-2bce274e"; do
  REGION="${ENTRY%%:*}"
  OPERATION="${ENTRY#*:}"
  echo "Checking operation: $OPERATION"
  gcloud backup-dr operations describe "$OPERATION" \
    --project="$PROJECT_ID" --location="$REGION" \
    --format="yaml(name,done,error,response)"
done
```

The later `ACTIVE` backup resources are the direct evidence of successful backup creation. A separate final `done: true` readout for every operation was not supplied.

## 14. VM05 deletion and preservation test

**Purpose:** Check that deleting a VM does not make the additive-only Python generator automatically delete its association configuration, and independently observe what happens to the GCP association and backup.

### 14.1 Test procedure

1. Confirm VM05's recovery point is `ACTIVE` and record its expiration.
2. Delete the original Compute Engine instance.
3. Trigger the actual GitHub Actions discovery workflow, rather than executing Python scripts manually.
4. Confirm the workflow does not remove the existing association from `in_scope.auto.tfvars.json`.
5. If there is no generated file change, expect **no PR and no new VCS-triggered HCP Terraform run**.
6. Independently inspect the GCP backup-plan association and recovery point.

Deletion performed:

```bash
gcloud compute instances delete dr-test-vm05 \
  --project="$PROJECT_ID" \
  --zone="$MTL_ZONE"
```

The CLI warned that auto-delete attached disks would also be deleted unless kept. The user confirmed deletion, and `gcloud` returned `Deleted [...] /instances/dr-test-vm05`.

### 14.2 Actual post-deletion observations

Association describe:

```bash
gcloud backup-dr backup-plan-associations describe dr-test-vm05 \
  --project="$PROJECT_ID" --location="$MTL_REGION" \
  --format="yaml(name,state,resource,dataSource)"
```

Observed fields:

```text
name: projects/manab-test-project/locations/northamerica-northeast1/backupPlanAssociations/dr-test-vm05
resource: projects/706329624933/zones/northamerica-northeast1-a/instances/755283775986043409
state: ACTIVE
dataSource: projects/706329624933/locations/northamerica-northeast2/backupVaults/dr-lab-vault-tor/dataSources/bded5f7762e0f030222d8fc5323b20167e68096d
```

Backup list and describe both still returned `ACTIVE` for recovery point `e34c6c1c-218b-42ad-a68f-16aa8701223f`. Its creation time was `2026-11-06T20:25:11.101011745Z`; its expiry was `2026-11-07T20:27:02.567083029Z` (**15:27:02 EST on November 7**). The recorded update time was `2026-11-06T20:27:11.644782594Z`.

**What is proven:** VM05 was deleted, and immediately afterward the association and backup were still visible as `ACTIVE`. **What is not proven:** the association can keep protecting a nonexistent VM, the recovery point remains after expiry, or a restore works. Restoration was **not in scope**.

### 14.3 Expected CI/CD outcome (not yet evidenced by run logs)

With VM05 deleted, the next discovery should see **four remaining VMs**: VM01, VM02, VM03, VM04. Three are eligible, one is excluded. The generator should retain the four existing association entries, including VM05, and validation should pass without changes. If no tracked file changes, `create-pull-request` should not open a new PR; HCP Terraform's path-based VCS trigger should not run from this workflow.

**Status:** Expected behavior documented; **post-deletion GitHub Actions logs/PR result were not provided**. Record the actual run URL, run conclusion, diff, PR outcome, and HCP run status after checking.

## 15. Verification command reference

### 15.1 All-in-one resource inventory

```bash
PROJECT_ID="manab-test-project"
MTL_REGION="northamerica-northeast1"
TOR_REGION="northamerica-northeast2"

echo "========== 1. COMPUTE ENGINE VMS =========="
gcloud compute instances list --project="$PROJECT_ID" \
  --format="table(name,zone,status,labels)"

echo "========== 2. BACKUP VAULTS =========="
for REGION in "$MTL_REGION" "$TOR_REGION"; do
  echo "Region: $REGION"
  gcloud backup-dr backup-vaults list \
    --project="$PROJECT_ID" --location="$REGION"
done

echo "========== 3. BACKUP PLANS =========="
for REGION in "$MTL_REGION" "$TOR_REGION"; do
  echo "Region: $REGION"
  gcloud backup-dr backup-plans list \
    --project="$PROJECT_ID" --location="$REGION" \
    --format="table(name,state,backupVault)"
done

echo "========== 4. BACKUP ASSOCIATIONS =========="
for REGION in "$MTL_REGION" "$TOR_REGION"; do
  echo "Region: $REGION"
  gcloud backup-dr backup-plan-associations list \
    --project="$PROJECT_ID" --location="$REGION"
done

echo "========== 5. DATA SOURCES =========="
for ENTRY in \
  "$TOR_REGION:dr-lab-vault-tor" \
  "$MTL_REGION:dr-lab-vault-mtl"; do
  REGION="${ENTRY%%:*}"
  VAULT="${ENTRY#*:}"
  echo "Vault: $VAULT ($REGION)"
  gcloud backup-dr data-sources list \
    --project="$PROJECT_ID" --location="$REGION" \
    --backup-vault="$VAULT" \
    --format="table(name,backupCount,state,backupConfigInfo.lastBackupState,totalStoredBytes)"
done

echo "========== 6. ACTUAL RECOVERY POINTS =========="
for ENTRY in \
  "$TOR_REGION:dr-lab-vault-tor" \
  "$MTL_REGION:dr-lab-vault-mtl"; do
  REGION="${ENTRY%%:*}"
  VAULT="${ENTRY#*:}"
  echo "========== $VAULT ($REGION) =========="
  gcloud backup-dr data-sources list \
    --project="$PROJECT_ID" --location="$REGION" \
    --backup-vault="$VAULT" --format="value(name)" |
  while IFS= read -r SOURCE; do
    [ -z "$SOURCE" ] && continue
    SOURCE_ID="${SOURCE##*/}"
    echo "Data source: $SOURCE_ID"
    gcloud backup-dr backups list \
      --project="$PROJECT_ID" --location="$REGION" \
      --backup-vault="$VAULT" --data-source="$SOURCE_ID" \
      --format="table(name,state,createTime,expireTime)"
  done
done
```

This consolidates the originally separate compute, vault, plan, association, data-source, and recovery-point checks. It deliberately uses `while IFS= read -r` for correct **zsh** handling of multiple data-source names.

### 15.2 Targeted VM05 checks

```bash
gcloud backup-dr backup-plan-associations describe dr-test-vm05 \
  --project="$PROJECT_ID" --location="$MTL_REGION" \
  --format="yaml(name,state,resource,dataSource)"

gcloud backup-dr backups list \
  --project="$PROJECT_ID" --location="$TOR_REGION" \
  --backup-vault=dr-lab-vault-tor \
  --data-source=bded5f7762e0f030222d8fc5323b20167e68096d \
  --format="table(name,state,createTime,expireTime)"
```

These commands describe the **historical lab state**; after retention expiration or cleanup they may legitimately return no recovery points or missing resources.

## 16. Troubleshooting and lessons

| Symptom / observation | Explanation / action |
|---|---|
| `gcloud compute instances create` fails without network selection | The project has no default VPC. Always specify the intended custom subnet (`--subnet=dr-subnet-mtl` or `dr-subnet-tor`). |
| 10-GB boot disk performance warning | Expected warning for small persistent disks; acceptable for lightweight lab VMs. |
| Effective Resource Manager tag not immediately visible in CAI | Allow time for propagation, then query `effectiveTags` again. |
| HCP Terraform cannot authenticate | Verify OIDC issuer, organization/workspace claim condition, workspace-specific SA IAM bindings, and HCP environment variables. |
| HCP Terraform cannot read resources | Confirm needed IAM permissions; the lab added `roles/browser` for reads. |
| Organization blocks WIF provider | Check effective `iam.workloadIdentityPoolProviders` organization policy; request admin approval. |
| GitHub workflow fails importing `google.cloud.asset_v1` | Correct `scripts/requirements.txt` and ensure the workflow installs it. A dependency fix was committed. |
| `zsh: command not found: #` when pasting comments | Interactive zsh may not treat pasted `#` lines as comments unless `setopt interactivecomments` is enabled. Use comment-free command blocks. |
| `for SOURCE in $DATA_SOURCES` doesn't process multiple lines | zsh does not perform Bash-style word splitting by default. Use `... | while IFS= read -r SOURCE`. |
| Backup operation initially `done: false` | Backup was still asynchronous; inspect recovery point state and retry after processing. |
| Backup initially `CREATING` | Wait for `ACTIVE`; don't treat plan association alone as proof of backup. |
| Re-triggering VM05 backup returns HTTP 409 | Another backup was already queued/running; the first backup later became ACTIVE. |
| Deleted VM still has an ACTIVE association | Observed immediately after deletion. Do not assume that ACTIVE association can back up a missing instance or that this status will persist forever. |
| No GitHub PR after VM deletion | Intended if additive-only generation produces no changed Terraform input; verify workflow success and Git diff before concluding. |

## 17. Security, operational limitations, and cleanup

### Security controls

- **No JSON service-account keys:** HCP Terraform and GitHub Actions use separate OIDC WIF trust paths.
- **Separate service accounts:** Terraform infrastructure manager (`terraform-backup-lab`) versus discovery reader (`github-backup-discovery`).
- **Restricted OIDC claims:** HCP organization/workspace IDs; GitHub repository ID, owner ID, and `main` ref.
- **Manual approval:** Association changes require PR review/merge and HCP Terraform apply approval.
- **Explicit exclusions:** `backup-exclude=true` prevents VM03 onboarding.
- **Deletion-safe desired state:** additive-only reconciliation and change validation.

### Limits of the lab

- One project stands in for a larger production/nonproduction organization.
- Short **1-day** backup retention is for testing, not an enterprise policy.
- GitHub cron runs **daily at 08:00 UTC**, not instantly when a VM appears.
- A backup plan association is not the same as a completed backup; both were checked.
- Git preservation of a deleted VM's association does not imply that the GCP resource remains indefinitely valid.
- **Restoration, workload recovery, RTO/RPO measurement, and failover were not discussed as implementation tasks today and were not tested.**
- Backup vault retention and deletion controls can create continuing costs even after a source VM is removed.
- The original lab used `roles/backupdr.admin` for Terraform. Replace broad grants with task-specific IAM roles in production.
- Review lifecycle behavior for stale associations; the additive-only design intentionally defers destructive cleanup to an explicit human-controlled process.

### Cleanup caution

Avoid manually deleting Terraform-managed vaults, plans, or associations while their HCP Terraform workspaces still expect them. Review state and dependencies first, then use reviewed Terraform changes. Check vault retention, existing recovery points, and billing before cleanup. VM05 has **already been deleted** in the recorded test; do not rerun its deletion command expecting the same initial state.

## 18. Validation checklist and next steps

| Verification | Recorded outcome |
|---|---|
| Project billing and API setup | Setup documented |
| Custom VPC + two regional subnets | Created |
| VM01/VM02/VM03/VM04 | Created |
| Project Resource Manager tag and inheritance | Configured and used in discovery |
| CAI VM discovery and Python policy resolution | Implemented |
| Exclusion of VM03 | Confirmed by association inventory |
| Two vaults and four plans | ACTIVE |
| HCP Terraform WIF and separate workspaces | Configured |
| GitHub Actions WIF, scheduled discovery, PR automation | Implemented |
| VM05 automatic association | ACTIVE association observed |
| Four eligible VM backups | All ACTIVE |
| VM05 deletion | Confirmed |
| VM05 association after deletion | ACTIVE at time of check |
| VM05 recovery point after deletion | ACTIVE at time of check |
| Post-deletion GitHub Actions run and no-change/no-PR behavior | **Awaiting recorded workflow evidence** |
| Restore test | **Out of scope for this day's work** |

**Immediate final documentation action:** Capture the GitHub Actions run link and conclusion after deleting VM05, note whether `in_scope.auto.tfvars.json` changed, whether a PR was opened, and whether HCP Terraform ran. This completes the **specific deletion-reconciliation verification** without expanding the project into restoration.

---

## Repository and documentation pointers

- **Repository:** [gcp-backup-dr-automation](https://github.com/manabpokhrel77/gcp-backup-dr-automation)
- **Python automation:** [`scripts/`](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/scripts)
- **Terraform infrastructure:** [`terraform/infrastructure/`](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/terraform/infrastructure)
- **Terraform associations:** [`terraform/associations/`](https://github.com/manabpokhrel77/gcp-backup-dr-automation/tree/main/terraform/associations)
- **GitHub Actions workflow:** [`.github/workflows/backup-discovery.yml`](https://github.com/manabpokhrel77/gcp-backup-dr-automation/blob/main/.github/workflows/backup-discovery.yml)
- **Official references:** [Cloud Asset Inventory](https://cloud.google.com/asset-inventory/docs/overview), [Resource Manager tags](https://cloud.google.com/resource-manager/docs/tags/tags-overview), [Backup and DR](https://cloud.google.com/backup-disaster-recovery/docs), [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation), [HCP Terraform](https://developer.hashicorp.com/terraform/cloud-docs), [GitHub Actions](https://docs.github.com/en/actions).

*This README records the implementation and command outputs shared during the 6 November 2026 lab. It distinguishes confirmed observations from expected workflow behavior. Refer to the repository for the current Python, Terraform, and YAML implementation.*
