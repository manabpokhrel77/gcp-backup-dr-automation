variable "backup_vaults" {
  description = "Map of backup vaults to create across GCP regions"

  type = map(object({
    backup_vault_id    = string
    description        = string
    retention_days     = number
    access_restriction = string
    location           = string
  }))
}

variable "backup_plans" {
  description = "Map of regional backup plans"

  type = map(object({
    backup_plan_id       = string
    backup_plan_location = string
    backup_vault_key     = string
    retention_days       = number
  }))
}