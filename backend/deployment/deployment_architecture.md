# Architecture Blueprint: Google Cloud Run Deployment Setup

This document highlights the automated deployment specifications for both the FastAPI backend and Next.js frontend to **Google Cloud Run**, featuring built-in CI/CD pipelines, secret resolutions, and setup commands.

---

## 1. Secrets & Environment Specifications
The architecture resolves secrets from **Google Secret Manager** at container startup to prevent plaintext storage inside config files.

| Secret/Variable Name | Target Component | Scope / Description | Type |
| :--- | :--- | :--- | :--- |
| `COPILOT_HMAC_KEY` | Backend | Verification key for session tokens and signatures | Secret Manager |
| `COPILOT_PII_SALT` | Backend | Pseudonymization salt for user IDs | Secret Manager |
| `GEMINI_API_KEY` | Backend | Gemini model invocation API Key (optional if using IAM/Vertex AI) | Secret Manager |
| `LOGS_BUCKET_NAME` | Backend | Cloud Storage Bucket for pipeline audit logs | Env Var |
| `ALLOW_ORIGINS` | Backend | CORS Allowed domain lists (e.g. frontend URL) | Env Var |
| `NEXT_PUBLIC_API_URL`| Frontend | URL endpoint pointing to Cloud Run backend backend service | Build Arg/Env Var |

---

## 2. Cloud Build Configuration (Multi-Service Deployment)
Save the following config as `cloudbuild.yaml` in the root of the project workspace to deploy both services using Cloud Build:

```yaml
steps:
  # 1. Build and Tag Backend Container
  - name: 'gcr.io/cloud-builders/docker'
    args: [
      'build',
      '-t', 'gcr.io/$PROJECT_ID/copilot-backend:$COMMIT_SHA',
      '-f', './backend/Dockerfile',
      './backend'
    ]
    id: 'build-backend'

  # 2. Build and Tag Frontend Container
  - name: 'gcr.io/cloud-builders/docker'
    args: [
      'build',
      '-t', 'gcr.io/$PROJECT_ID/copilot-frontend:$COMMIT_SHA',
      '-f', './frontend/Dockerfile',
      './frontend'
    ]
    id: 'build-frontend'
    waitFor: ['-']

  # 3. Push Backend to GCR
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/copilot-backend:$COMMIT_SHA']
    id: 'push-backend'
    waitFor: ['build-backend']

  # 4. Push Frontend to GCR
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/copilot-frontend:$COMMIT_SHA']
    id: 'push-frontend'
    waitFor: ['build-frontend']

  # 5. Deploy Backend to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'copilot-backend'
      - '--image=gcr.io/$PROJECT_ID/copilot-backend:$COMMIT_SHA'
      - '--region=us-central1'
      - '--platform=managed'
      - '--allow-unauthenticated'
      - '--update-env-vars=LOGS_BUCKET_NAME=$_LOGS_BUCKET_NAME'
      - '--update-secrets=COPILOT_HMAC_KEY=copilot-hmac-key:latest,COPILOT_PII_SALT=copilot-pii-salt:latest'
    id: 'deploy-backend'
    waitFor: ['push-backend']

  # 6. Deploy Frontend to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'copilot-frontend'
      - '--image=gcr.io/$PROJECT_ID/copilot-frontend:$COMMIT_SHA'
      - '--region=us-central1'
      - '--platform=managed'
      - '--allow-unauthenticated'
    id: 'deploy-frontend'
    waitFor: ['push-frontend']

images:
  - 'gcr.io/$PROJECT_ID/copilot-backend:$COMMIT_SHA'
  - 'gcr.io/$PROJECT_ID/copilot-frontend:$COMMIT_SHA'
```

---

## 3. Step-by-Step Production Deployment Instructions

### Step A: Initialize Secrets in Secret Manager
Run these commands to provision the secret vaults:
```bash
# 1. Enable Secret Manager
gcloud services enable secretmanager.googleapis.com

# 2. Create the Session HMAC secret key
echo "YOUR_HMAC_SESSION_SECRET_KEY" | \
  gcloud secrets create copilot-hmac-key --data-file=-

# 3. Create the PII Salt secret key
echo "YOUR_PII_SALT_PHRASE_KEY" | \
  gcloud secrets create copilot-pii-salt --data-file=-
```

### Step B: Grant Runtime Access to Service Account
Grant the default compute service account permission to read the secrets at container startup:
```bash
# Get Project Number
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Grant Secret Manager Secret Accessor role to the default Cloud Run Service account
gcloud secrets add-iam-policy-binding copilot-hmac-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding copilot-pii-salt \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Step C: Trigger CI/CD Trigger or Manual Build
Submit the build file to compile, push, and release both services under Google Cloud Run:
```bash
gcloud builds submit --config=cloudbuild.yaml --substitutions=_LOGS_BUCKET_NAME="your-audit-logs-bucket"
```
