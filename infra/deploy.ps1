<#
================================================================================
 AP Automation Platform — Azure Container Apps provisioning script
================================================================================
 Provisions the FULL production stack and deploys all services:

   Azure Container Registry      (image storage)
   Azure Database for PostgreSQL (Flexible Server)
   Azure Cache for Redis         (Celery broker / result backend)
   Azure Storage + File Share    (shared /app/uploads for api + worker)
   Container Apps Environment     hosting:
        invoice-backend   (FastAPI, public ingress, runs DB migrations)
        invoice-worker    (Celery worker)
        invoice-beat      (Celery beat scheduler)
        invoice-frontend  (nginx + React, public ingress)

 PREREQUISITES
   1. Azure CLI installed:   winget install Microsoft.AzureCLI   (then reopen shell)
   2. az login              (and `az account set --subscription <id>` if needed)
   3. Run this from the REPO ROOT:   ./infra/deploy.ps1

 NOTE: Redis + Postgres provisioning take ~10-20 min. The script is mostly
 idempotent — re-running skips/uodates existing resources, but review errors.
================================================================================
#>

# ---- EDIT THESE ---------------------------------------------------------------
$LOCATION   = "eastus"
$RG         = "invoice-p2p-rg"
$ENVNAME    = "invoice-p2p-env"

# These names must be GLOBALLY UNIQUE. Change the suffix if creation fails.
$ACR        = "invoicep2pacr"          # 5-50 alphanumeric, lowercase
$PG         = "invoice-p2p-pg-001"     # postgres server name
$REDIS      = "invoice-p2p-redis-001"  # redis cache name
$STG        = "invoicep2pstor001"      # storage acct: 3-24 lowercase alphanumeric

# Database credentials
$PGADMIN    = "apadmin"
$PGPASS     = "Ch4nge-Me-Str0ng!"      # CHANGE THIS
$PGDB       = "ap_platform"

# App secrets
$OPENAI_API_KEY = $env:OPENAI_API_KEY   # export OPENAI_API_KEY before running, or hardcode
$SECRET_KEY     = "change-this-to-a-32char-plus-random-secret-value"

# Image tags
$IMG_BACKEND  = "invoice-backend:latest"
$IMG_FRONTEND = "invoice-frontend:latest"
# -------------------------------------------------------------------------------

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Die($m)  { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

if (-not $OPENAI_API_KEY) { Die "OPENAI_API_KEY is empty. Run: `$env:OPENAI_API_KEY='sk-...'` first." }

Step "Registering providers & container app extension"
az extension add --name containerapp --upgrade --only-show-errors | Out-Null
az provider register -n Microsoft.App --wait
az provider register -n Microsoft.OperationalInsights --wait
az provider register -n Microsoft.DBforPostgreSQL --wait
az provider register -n Microsoft.Cache --wait

Step "Resource group: $RG"
az group create -n $RG -l $LOCATION --only-show-errors | Out-Null

Step "Container Registry: $ACR"
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true --only-show-errors | Out-Null
$ACR_SERVER = "$ACR.azurecr.io"
$ACR_USER   = (az acr credential show -n $ACR --query username -o tsv)
$ACR_PASS   = (az acr credential show -n $ACR --query "passwords[0].value" -o tsv)

Step "PostgreSQL Flexible Server: $PG  (this takes several minutes)"
az postgres flexible-server create -g $RG -n $PG -l $LOCATION `
    --admin-user $PGADMIN --admin-password $PGPASS `
    --sku-name Standard_B1ms --tier Burstable --storage-size 32 --version 16 `
    --public-access 0.0.0.0 --yes --only-show-errors | Out-Null
az postgres flexible-server db create -g $RG -s $PG -d $PGDB --only-show-errors | Out-Null
# Allow non-SSL so asyncpg/pg8000 connect without extra SSL config (harden later).
az postgres flexible-server parameter set -g $RG -s $PG --name require_secure_transport --value OFF --only-show-errors | Out-Null
$PG_HOST = "$PG.postgres.database.azure.com"

Step "Azure Cache for Redis: $REDIS  (this takes ~15-20 minutes)"
az redis create -n $REDIS -g $RG -l $LOCATION --sku Basic --vm-size c0 --enable-non-ssl-port --minimum-tls-version 1.2 --only-show-errors | Out-Null
$REDIS_HOST = "$REDIS.redis.cache.windows.net"
$REDIS_KEY  = (az redis list-keys -n $REDIS -g $RG --query primaryKey -o tsv)

Step "Storage account + file share (shared uploads): $STG"
az storage account create -n $STG -g $RG -l $LOCATION --sku Standard_LRS --only-show-errors | Out-Null
$STG_KEY = (az storage account keys list -n $STG -g $RG --query "[0].value" -o tsv)
az storage share-rm create --resource-group $RG --storage-account $STG --name uploads --quota 50 --only-show-errors | Out-Null

Step "Container Apps environment: $ENVNAME"
az containerapp env create -n $ENVNAME -g $RG -l $LOCATION --only-show-errors | Out-Null
$ENV_ID     = (az containerapp env show -n $ENVNAME -g $RG --query id -o tsv)
$ENV_DOMAIN = (az containerapp env show -n $ENVNAME -g $RG --query properties.defaultDomain -o tsv)

az containerapp env storage set -g $RG -n $ENVNAME --storage-name uploadsmount `
    --azure-file-account-name $STG --azure-file-account-key $STG_KEY `
    --azure-file-share-name uploads --access-mode ReadWrite --only-show-errors | Out-Null

# Connection strings (non-SSL Redis on 6379; non-SSL Postgres)
$DATABASE_URL      = "postgresql+asyncpg://${PGADMIN}:${PGPASS}@${PG_HOST}:5432/${PGDB}"
$SYNC_DATABASE_URL = "postgresql://${PGADMIN}:${PGPASS}@${PG_HOST}:5432/${PGDB}"
$REDIS_URL         = "redis://:${REDIS_KEY}@${REDIS_HOST}:6379/0"
$CELERY_BROKER     = "redis://:${REDIS_KEY}@${REDIS_HOST}:6379/0"
$CELERY_BACKEND    = "redis://:${REDIS_KEY}@${REDIS_HOST}:6379/1"

# Predict the backend public URL (deterministic from env domain)
$BACKEND_URL  = "https://invoice-backend.$ENV_DOMAIN"
$FRONTEND_URL = "https://invoice-frontend.$ENV_DOMAIN"

Step "Building backend image in ACR (no local Docker needed)"
az acr build -r $ACR -t $IMG_BACKEND -f backend/Dockerfile . | Out-Null

Step "Building frontend image in ACR (baking VITE_API_URL=$BACKEND_URL)"
az acr build -r $ACR -t $IMG_FRONTEND -f frontend/Dockerfile ./frontend --build-arg VITE_API_URL=$BACKEND_URL | Out-Null

# ---- Generate Container App YAML specs ---------------------------------------
$tmp = $env:TEMP

$backendYaml = @"
location: $LOCATION
name: invoice-backend
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 8000
      transport: auto
      allowInsecure: false
    registries:
      - server: $ACR_SERVER
        username: $ACR_USER
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASS"
      - name: database-url
        value: "$DATABASE_URL"
      - name: sync-database-url
        value: "$SYNC_DATABASE_URL"
      - name: redis-url
        value: "$REDIS_URL"
      - name: celery-broker
        value: "$CELERY_BROKER"
      - name: celery-backend
        value: "$CELERY_BACKEND"
      - name: openai-key
        value: "$OPENAI_API_KEY"
      - name: secret-key
        value: "$SECRET_KEY"
  template:
    volumes:
      - name: uploads
        storageType: AzureFile
        storageName: uploadsmount
    containers:
      - name: backend
        image: $ACR_SERVER/$IMG_BACKEND
        resources:
          cpu: 1.0
          memory: 2.0Gi
        env:
          - name: ENVIRONMENT
            value: production
          - name: RUN_MIGRATIONS
            value: "true"
          - name: UPLOAD_DIR
            value: /app/uploads
          - name: ALLOWED_ORIGINS
            value: "$FRONTEND_URL"
          - name: OPENAI_MODEL
            value: gpt-4o
          - name: OPENAI_VISION_MODEL
            value: gpt-4o
          - name: DATABASE_URL
            secretRef: database-url
          - name: SYNC_DATABASE_URL
            secretRef: sync-database-url
          - name: REDIS_URL
            secretRef: redis-url
          - name: CELERY_BROKER_URL
            secretRef: celery-broker
          - name: CELERY_RESULT_BACKEND
            secretRef: celery-backend
          - name: OPENAI_API_KEY
            secretRef: openai-key
          - name: SECRET_KEY
            secretRef: secret-key
        volumeMounts:
          - volumeName: uploads
            mountPath: /app/uploads
    scale:
      minReplicas: 1
      maxReplicas: 3
"@
$backendYaml | Out-File "$tmp\ca-backend.yaml" -Encoding utf8

$workerYaml = @"
location: $LOCATION
name: invoice-worker
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    registries:
      - server: $ACR_SERVER
        username: $ACR_USER
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASS"
      - name: database-url
        value: "$DATABASE_URL"
      - name: sync-database-url
        value: "$SYNC_DATABASE_URL"
      - name: redis-url
        value: "$REDIS_URL"
      - name: celery-broker
        value: "$CELERY_BROKER"
      - name: celery-backend
        value: "$CELERY_BACKEND"
      - name: openai-key
        value: "$OPENAI_API_KEY"
      - name: secret-key
        value: "$SECRET_KEY"
  template:
    volumes:
      - name: uploads
        storageType: AzureFile
        storageName: uploadsmount
    containers:
      - name: worker
        image: $ACR_SERVER/$IMG_BACKEND
        command: ["celery"]
        args: ["-A", "app.core.celery_app.celery_app", "worker", "--loglevel=info", "-Q", "pipeline,default", "--concurrency=4"]
        resources:
          cpu: 1.0
          memory: 2.0Gi
        env:
          - name: ENVIRONMENT
            value: production
          - name: UPLOAD_DIR
            value: /app/uploads
          - name: DATABASE_URL
            secretRef: database-url
          - name: SYNC_DATABASE_URL
            secretRef: sync-database-url
          - name: REDIS_URL
            secretRef: redis-url
          - name: CELERY_BROKER_URL
            secretRef: celery-broker
          - name: CELERY_RESULT_BACKEND
            secretRef: celery-backend
          - name: OPENAI_API_KEY
            secretRef: openai-key
          - name: SECRET_KEY
            secretRef: secret-key
        volumeMounts:
          - volumeName: uploads
            mountPath: /app/uploads
    scale:
      minReplicas: 1
      maxReplicas: 5
"@
$workerYaml | Out-File "$tmp\ca-worker.yaml" -Encoding utf8

$beatYaml = @"
location: $LOCATION
name: invoice-beat
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    registries:
      - server: $ACR_SERVER
        username: $ACR_USER
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASS"
      - name: sync-database-url
        value: "$SYNC_DATABASE_URL"
      - name: redis-url
        value: "$REDIS_URL"
      - name: celery-broker
        value: "$CELERY_BROKER"
      - name: celery-backend
        value: "$CELERY_BACKEND"
      - name: openai-key
        value: "$OPENAI_API_KEY"
      - name: secret-key
        value: "$SECRET_KEY"
  template:
    containers:
      - name: beat
        image: $ACR_SERVER/$IMG_BACKEND
        command: ["celery"]
        args: ["-A", "app.core.celery_app.celery_app", "beat", "--loglevel=info"]
        resources:
          cpu: 0.5
          memory: 1.0Gi
        env:
          - name: ENVIRONMENT
            value: production
          - name: SYNC_DATABASE_URL
            secretRef: sync-database-url
          - name: REDIS_URL
            secretRef: redis-url
          - name: CELERY_BROKER_URL
            secretRef: celery-broker
          - name: CELERY_RESULT_BACKEND
            secretRef: celery-backend
          - name: OPENAI_API_KEY
            secretRef: openai-key
          - name: SECRET_KEY
            secretRef: secret-key
    scale:
      minReplicas: 1
      maxReplicas: 1
"@
$beatYaml | Out-File "$tmp\ca-beat.yaml" -Encoding utf8

$frontendYaml = @"
location: $LOCATION
name: invoice-frontend
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 80
      transport: auto
      allowInsecure: false
    registries:
      - server: $ACR_SERVER
        username: $ACR_USER
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASS"
  template:
    containers:
      - name: frontend
        image: $ACR_SERVER/$IMG_FRONTEND
        resources:
          cpu: 0.5
          memory: 1.0Gi
    scale:
      minReplicas: 1
      maxReplicas: 3
"@
$frontendYaml | Out-File "$tmp\ca-frontend.yaml" -Encoding utf8

Step "Deploying container apps (backend, worker, beat, frontend)"
az containerapp create -g $RG --yaml "$tmp\ca-backend.yaml"  --only-show-errors | Out-Null
az containerapp create -g $RG --yaml "$tmp\ca-worker.yaml"   --only-show-errors | Out-Null
az containerapp create -g $RG --yaml "$tmp\ca-beat.yaml"     --only-show-errors | Out-Null
az containerapp create -g $RG --yaml "$tmp\ca-frontend.yaml" --only-show-errors | Out-Null

Write-Host "`n================================================================" -ForegroundColor Green
Write-Host " DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Frontend : $FRONTEND_URL"
Write-Host "  Backend  : $BACKEND_URL"
Write-Host "  API docs : $BACKEND_URL/api/docs"
Write-Host ""
Write-Host "  Migrations run automatically on backend startup (RUN_MIGRATIONS=true)."
Write-Host "  Seed the database once it's up:" -ForegroundColor Yellow
Write-Host "    az containerapp exec -g $RG -n invoice-backend --command `"python seed/seed.py`""
Write-Host ""
Write-Host "  Default login after seeding: admin@company.com / password123" -ForegroundColor Yellow
