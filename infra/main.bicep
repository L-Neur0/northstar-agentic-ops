// main.bicep: entry point of the Discovery Agent's Azure environment (spec 25 §3.4, §3.6).
//
// Why it exists: azd deploys this template into the EXISTING resource group
//   rg-northstar-discovery (azd env AZURE_RESOURCE_GROUP), never a new one (D2).
// What it creates: the app identity, Log Analytics + App Insights, the container
//   registry (AcrPull for the identity), the Cosmos DB store (data-plane role for
//   the identity and the developer), the "Cognitive Services OpenAI User" role on
//   the existing AI account, and the Container Apps environment + container app.
//   Re-provisioning is a no-op: names come from a stable token, role assignment
//   names are guid(scope, principal, role), and the running image is kept (D7).
// What it must not do: create or change the hand-made AI account
//   northstar-discovery-ai or its deployments app-chat / eval-expert (D1);
//   output a secret. Never run `azd down` on this environment (D8).
// Acceptance criteria: AC-25.8 to AC-25.20, AC-25.29 (static half), AC-25.30.

targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('azd environment name (AZURE_ENV_NAME). Part of every resource name token.')
param environmentName string

@description('Region for new resources (AZURE_LOCATION). The resource group is in swedencentral.')
param location string = resourceGroup().location

@description('Name of the EXISTING AI Services account (made by hand, D1).')
param openAiAccountName string = 'northstar-discovery-ai'

@description('Model deployment used by the app.')
param appDeploymentName string = 'app-chat'

@description('Model deployment used by the evaluation runner.')
param evalDeploymentName string = 'eval-expert'

@description('Azure OpenAI data-plane API version (the model API, not an ARM API version).')
param openAiApiVersion string = '2025-04-01-preview'

@description('Object id of the developer (DEVELOPER_PRINCIPAL_ID), for local runs against Cosmos. Empty = no developer role. Not AZURE_PRINCIPAL_ID, which is the CI principal in CI (spec 25 §3.6).')
param developerPrincipalId string = ''

@minValue(0)
@maxValue(1)
@description('Minimum replicas (MIN_REPLICAS): 1 during the demo period, 0 afterwards (D5).')
param minReplicas int = 1

@description('Log Analytics daily cap in GB, as a decimal string.')
param logDailyCapGb string = '0.5'

@description('Daily token budget of the open link (DAILY_TOKEN_BUDGET).')
param dailyTokenBudget int = 2000000

@description('Set by azd (SERVICE_APP_RESOURCE_EXISTS): true once the container app exists (D7).')
param appExists bool = false

@secure()
@description('Workspace access code for specialists (WORKSPACE_CODE_SPECIALIST); optional when the workspace is open.')
param workspaceCodeSpecialist string = ''

@secure()
@description('Workspace access code for AI engineers (WORKSPACE_CODE_ENGINEER); optional when the workspace is open.')
param workspaceCodeEngineer string = ''

@description('Open demo workspace (WORKSPACE_OPEN): name-only login, delete switched off (spec 25 AC-25.30).')
param workspaceOpen bool = true

@secure()
@minLength(32)
@description('Secret that signs workspace tokens (WORKSPACE_TOKEN_SECRET), 32+ characters.')
param workspaceTokenSecret string

var token = uniqueString(subscription().id, resourceGroup().id, environmentName)
var tags = {
  project: 'northstar-discovery'
  'azd-env-name': environmentName
}
var appName = 'ca-discovery-${token}'

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    name: 'id-discovery-${token}'
    location: location
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    logAnalyticsName: 'log-discovery-${token}'
    appInsightsName: 'appi-discovery-${token}'
    location: location
    tags: tags
    logDailyCapGb: logDailyCapGb
  }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: {
    name: 'crdiscovery${token}'
    location: location
    tags: tags
    pullPrincipalId: identity.outputs.principalId
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    accountName: 'cosmos-discovery-${token}'
    location: location
    tags: tags
    dataContributorPrincipalIds: [
      identity.outputs.principalId
      developerPrincipalId
    ]
  }
}

module openai 'modules/openai.bicep' = {
  name: 'openai'
  params: {
    accountName: openAiAccountName
    principalId: identity.outputs.principalId
  }
}

// The image currently running, so a provision never rolls the app back (D7, AC-25.29).
module currentImage 'modules/current-image.bicep' = {
  name: 'current-image'
  params: {
    appName: appName
    appExists: appExists
  }
}

module containerApp 'modules/containerapp.bicep' = {
  name: 'containerapp'
  params: {
    environmentName: 'cae-discovery-${token}'
    appName: appName
    location: location
    tags: tags
    logAnalyticsName: monitoring.outputs.logAnalyticsName
    appInsightsName: monitoring.outputs.appInsightsName
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    registryLoginServer: registry.outputs.loginServer
    appExists: appExists
    currentImage: currentImage.outputs.image
    minReplicas: minReplicas
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    cosmosContainer: cosmos.outputs.containerName
    openAiEndpoint: openai.outputs.endpoint
    appDeploymentName: appDeploymentName
    evalDeploymentName: evalDeploymentName
    openAiApiVersion: openAiApiVersion
    dailyTokenBudget: dailyTokenBudget
    workspaceCodeSpecialist: workspaceCodeSpecialist
    workspaceCodeEngineer: workspaceCodeEngineer
    workspaceTokenSecret: workspaceTokenSecret
    workspaceOpen: workspaceOpen
  }
  // Reading registry.outputs makes the app wait for the registry module, so the
  // AcrPull assignment exists before the app references the registry.
}

// Outputs are written to the azd env (spec 25 §3.6). No secret, no connection string.
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output SERVICE_APP_NAME string = containerApp.outputs.name
output SERVICE_APP_URI string = containerApp.outputs.uri
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output COSMOS_CONTAINER string = cosmos.outputs.containerName
output AZURE_OPENAI_ENDPOINT string = openai.outputs.endpoint
output MANAGED_IDENTITY_CLIENT_ID string = identity.outputs.clientId
