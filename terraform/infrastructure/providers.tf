terraform {
  required_version = ">= 1.6.0"

  cloud {
    organization = "manab-devops-lab"

    workspaces {
      name = "gcp-backup-infrastructure-lab"
    }
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = "manab-test-project"
  region  = "northamerica-northeast1"
}