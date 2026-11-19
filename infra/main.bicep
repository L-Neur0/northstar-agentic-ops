// main.bicep: entry point of the Discovery Agent's Azure environment (spec 25 §3.4, §3.6).
//
// Why it exists: azd deploys this template into the EXISTING resource group
//   rg-northstar-discovery (azd env AZURE_RESOURCE_GROUP), never a new one (D2).
// What it creates (block 1, spec 15 §3.7): the Cosmos DB store through
//   modules/cosmos.bicep, with the data-plane role for the developer.
// What it must not do: create or change the hand-made AI account
//   northstar-discovery-ai or its deployments app-chat / eval-expert (D1);
//   output a secret. Never run `azd down` on this environment (D8).
// Acceptance criteria: AC-25.8, AC-25.9, AC-25.10, AC-25.11, AC-25.12, AC-25.14.

targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('azd environment name (AZURE_ENV_NAME). Part of every resource name token.')
param environmentName string

@description('Region for new resources (AZURE_LOCATION). The resource group is in swedencentral.')
param location string = resourceGroup().location

@description('Object id of the developer (DEVELOPER_PRINCIPAL_ID), for local runs against Cosmos. Empty = no developer role. Not AZURE_PRINCIPAL_ID, which is the CI principal in CI (spec 25 §3.6).')
param developerPrincipalId string = ''

// TODO(spec 25 §3.6): add openAiAccountName, appDeploymentName, evalDeploymentName,
// openAiApiVersion, minReplicas, logDailyCapGb, dailyTokenBudget, appExists and the
// three @secure() workspace parameters when the container app is added.

var token = uniqueString(subscription().id, resourceGroup().id, environmentName)
var tags = {
  project: 'northstar-discovery'
  'azd-env-name': environmentName
}

// TODO(spec 25 §3.4): modules/identity.bicep, monitoring.bicep, registry.bicep,
// openai.bicep (existing account + OpenAI User for the identity), containerapp.bicep.

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    accountName: 'cosmos-discovery-${token}'
    location: location
    tags: tags
    // TODO(spec 25 §3.4): prepend the identity module's principalId here.
    dataContributorPrincipalIds: [
      developerPrincipalId
    ]
  }
}

// Outputs are written to the azd env (spec 25 §3.6). No secret, no connection string.
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output COSMOS_CONTAINER string = cosmos.outputs.containerName
