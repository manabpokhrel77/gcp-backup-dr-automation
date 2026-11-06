resource "google_backup_dr_backup_plan_association" "vm_associations" {
  for_each = var.vm_associations

  project = "manab-test-project"

  location = each.value.location

  backup_plan_association_id = each.key

  resource_type = "compute.googleapis.com/Instance"

  resource    = each.value.resource
  backup_plan = each.value.backup_plan
}