backup_vaults = {
  montreal = {
    backup_vault_id    = "dr-lab-vault-mtl"
    description        = "Montreal backup vault for DR lab"
    retention_days     = 1
    access_restriction = "WITHIN_PROJECT"
    location           = "northamerica-northeast1"
  }

  toronto = {
    backup_vault_id    = "dr-lab-vault-tor"
    description        = "Toronto backup vault for DR lab"
    retention_days     = 1
    access_restriction = "WITHIN_PROJECT"
    location           = "northamerica-northeast2"
  }
}

backup_plans = {
  mtl_prod = {
    backup_plan_id       = "dr-lab-mtl-prod"
    backup_plan_location = "northamerica-northeast1"
    backup_vault_key     = "toronto"
    retention_days       = 1
  }

  mtl_nonprod = {
    backup_plan_id       = "dr-lab-mtl-nonprod"
    backup_plan_location = "northamerica-northeast1"
    backup_vault_key     = "toronto"
    retention_days       = 1
  }

  tor_prod = {
    backup_plan_id       = "dr-lab-tor-prod"
    backup_plan_location = "northamerica-northeast2"
    backup_vault_key     = "montreal"
    retention_days       = 1
  }

  tor_nonprod = {
    backup_plan_id       = "dr-lab-tor-nonprod"
    backup_plan_location = "northamerica-northeast2"
    backup_vault_key     = "montreal"
    retention_days       = 1
  }
}