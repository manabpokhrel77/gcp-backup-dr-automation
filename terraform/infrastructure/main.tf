data "google_project" "current" {
  project_id = "manab-test-project"
}

output "gcp_project_number" {
  value = data.google_project.current.number
}

output "gcp_project_id" {
  value = data.google_project.current.project_id
}

resource "google_backup_dr_backup_vault" "vaults" {
  for_each = var.backup_vaults

  project  = "manab-test-project"
  location = each.value.location

  backup_vault_id = each.value.backup_vault_id
  description     = each.value.description

  backup_minimum_enforced_retention_duration = "${each.value.retention_days * 86400}s"

  access_restriction = each.value.access_restriction
}

resource "google_backup_dr_backup_plan" "plans" {
  for_each = var.backup_plans

  project        = "manab-test-project"
  location       = each.value.backup_plan_location
  backup_plan_id = each.value.backup_plan_id

  resource_type = "compute.googleapis.com/Instance"

  backup_vault = google_backup_dr_backup_vault.vaults[
    each.value.backup_vault_key
  ].id

  backup_rules {
    rule_id               = "daily-rule"
    backup_retention_days = each.value.retention_days

    standard_schedule {
      recurrence_type = "DAILY"
      time_zone       = "UTC"

      backup_window {
        start_hour_of_day = 23
        end_hour_of_day   = 24
      }
    }
  }
}