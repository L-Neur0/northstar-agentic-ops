# Infrastructure

This folder is part of the [AI Use Case Discovery Agent](../README.md), and it describes the Azure resources as code, written in Bicep. They are deployed with the Azure Developer CLI (`azd`).

| Module | What it creates |
|---|---|
| `identity.bicep` | The managed identity that the app uses, so that no keys are needed |
| `openai.bicep` | A reference to the existing Azure OpenAI account, and the app's access to it (the account itself is created by hand) |
| `cosmos.bicep` | A serverless Cosmos DB, where sessions are stored |
| `registry.bicep` | The container registry that holds the app image |
| `containerapp.bicep` | The app itself, which runs as one container on Azure Container Apps |
| `current-image.bicep` | Reads the image that is running now, so that a new `azd provision` does not roll the app back |
| `monitoring.bicep` | Log Analytics and Application Insights |

```bash
azd provision --preview   # shows what would change, without changing anything
azd provision             # creates or updates the resources
azd deploy                # builds the image, pushes it, and rolls out a new revision
infra/scripts/smoke.sh <https-url>   # checks a deployed app
```

There are also local checks, none of which change anything in Azure: `make image-check` tests the container image, `make infra-lint` lints the Bicep files, and `make infra-test` runs the infrastructure tests.

When `MIN_REPLICAS=0`, the app scales to zero while nobody uses it. `WORKSPACE_OPEN=true` turns on an open demo workspace, where a name is enough to sign in; for real use, set it to `false` and configure workspace codes. Never run `azd down` on a shared environment, because it deletes the whole resource group.
