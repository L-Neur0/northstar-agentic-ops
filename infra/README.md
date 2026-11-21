# Infrastructure

Azure resources as code (Bicep), deployed with the Azure Developer CLI (`azd`).

| Module | Creates |
|---|---|
| `identity.bicep` | The managed identity the app uses (no keys) |
| `openai.bicep` | References the existing Azure OpenAI account and grants the app access (the account itself is created by hand) |
| `cosmos.bicep` | Cosmos DB (serverless) for sessions |
| `registry.bicep` | Container registry for the app image |
| `containerapp.bicep` | The app: one container on Azure Container Apps |
| `monitoring.bicep` | Log Analytics and Application Insights |

```bash
azd provision --preview   # what would change, without changing anything
azd provision             # create or update the resources
azd deploy                # build the image, push it, roll out a new revision
infra/scripts/smoke.sh <https-url>   # check a deployed app
```

`MIN_REPLICAS=0` scales to zero when idle. `WORKSPACE_OPEN=true` is an open demo workspace (name-only sign-in); set it to `false` and set workspace codes for real use. Never run `azd down` on a shared environment: it deletes the resource group.
