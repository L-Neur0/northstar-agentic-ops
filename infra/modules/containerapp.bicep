// containerapp.bicep: the one container that runs the Discovery Agent (spec 25 §3.5, D5-D7).
//
// Why it exists: the FastAPI app serves the API and the built React frontend from
//   one image; Container Apps runs it with HTTPS ingress and one replica, so the
//   in-process rate limits, daily budget and caches stay correct (D5, D6).
// What it creates: a Consumption Container Apps environment (logs to Log
//   Analytics) and the container app: user-assigned identity only, registry pull
//   with that identity (no password), external HTTPS ingress on port 8000,
//   0.5 vCPU / 1 GiB, min minReplicas / max 1 replica, the settings of spec 25
//   §3.5 as environment variables, and the three workspace values plus the App
//   Insights connection string as Container Apps secrets (secretRef).
//   Open workspace (amended 2026-11-20, AC-25.30): WORKSPACE_OPEN comes from the
//   workspaceOpen parameter; each workspace code (secret and variable) is added
//   only when it is not empty, because an open workspace needs no code.
//   First provision (appExists=false): the public placeholder image and no custom
//   probes (D7). Later provisions: the image passed in (the one running) and
//   startup / liveness / readiness probes on /api/health.
// What it must not do: set AZURE_OPENAI_API_KEY, LLM_CACHE_ENABLED or APP_VERSION
//   (the image carries its version); take AZURE_CLIENT_ID from anything but the
//   identity; put a secret in a plain env value or an output.
// Acceptance criteria: AC-25.15, AC-25.17, AC-25.18, AC-25.19, AC-25.20, AC-25.29, AC-25.30.

@description('Container Apps environment name, e.g. cae-discovery-<token>.')
param environmentName string

@description('Container app name, e.g. ca-discovery-<token>.')
param appName string

@description('Region of the environment and the app.')
param location string

@description('Tags for the environment. The app adds azd-service-name: app.')
param tags object

@description('Name of the Log Analytics workspace (monitoring module) that receives console logs.')
param logAnalyticsName string

@description('Name of the App Insights component (monitoring module); its connection string becomes a secret.')
param appInsightsName string

@description('Resource id of the user-assigned identity.')
param identityId string

@description('Client id of the user-assigned identity: the app\'s AZURE_CLIENT_ID.')
param identityClientId string

@description('Registry login server, e.g. crdiscovery<token>.azurecr.io.')
param registryLoginServer string

@description('True once the app exists (azd SERVICE_APP_RESOURCE_EXISTS): use currentImage and set probes.')
param appExists bool

@description('Image currently running (read by main.bicep from the existing app); ignored when appExists is false.')
param currentImage string

@minValue(0)
@maxValue(1)
@description('Minimum replicas: 1 during the demo period, 0 afterwards (D5).')
param minReplicas int

@description('Cosmos DB endpoint (cosmos module output).')
param cosmosEndpoint string

@description('Cosmos database name.')
param cosmosDatabase string

@description('Cosmos container name.')
param cosmosContainer string

@description('Azure OpenAI endpoint (existing account).')
param openAiEndpoint string

@description('App model deployment name.')
param appDeploymentName string

@description('Evaluation model deployment name.')
param evalDeploymentName string

@description('Azure OpenAI API version.')
param openAiApiVersion string

@description('Daily token budget of the open link.')
param dailyTokenBudget int

@secure()
@description('Workspace access code for specialists; empty = not set (open workspace).')
param workspaceCodeSpecialist string = ''

@secure()
@description('Workspace access code for AI engineers; empty = not set (open workspace).')
param workspaceCodeEngineer string = ''

@description('Open demo workspace: name-only login, delete switched off (WORKSPACE_OPEN).')
param workspaceOpen bool = true

@secure()
@minLength(32)
@description('Secret that signs workspace tokens.')
param workspaceTokenSecret string

var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var healthPath = '/api/health'
var port = 8000

// Every variable of spec 25 §3.5 that is always set (AC-25.19).
var baseEnv = [
  { name: 'DEPLOYMENT_STAGE', value: 'demo' }
  { name: 'STORE', value: 'cosmos' }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE', value: cosmosDatabase }
  { name: 'COSMOS_CONTAINER', value: cosmosContainer }
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
  { name: 'AZURE_OPENAI_DEPLOYMENT', value: appDeploymentName }
  { name: 'AZURE_OPENAI_EVAL_DEPLOYMENT', value: evalDeploymentName }
  { name: 'AZURE_OPENAI_API_VERSION', value: openAiApiVersion }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'DAILY_TOKEN_BUDGET', value: string(dailyTokenBudget) }
  { name: 'COMPANY_CONFIG_DIR', value: '/app/config/nig' }
  { name: 'FRONTEND_DIST', value: '/app/frontend/dist' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
  { name: 'WORKSPACE_TOKEN_SECRET', secretRef: 'workspace-token-secret' }
  { name: 'WORKSPACE_OPEN', value: workspaceOpen ? 'true' : 'false' }
]

// Each workspace code is a secret and a variable only when it is set (AC-25.30).
var codeSecrets = concat(
  empty(workspaceCodeSpecialist) ? [] : [{ name: 'workspace-code-specialist', value: workspaceCodeSpecialist }],
  empty(workspaceCodeEngineer) ? [] : [{ name: 'workspace-code-engineer', value: workspaceCodeEngineer }]
)
var codeEnv = concat(
  empty(workspaceCodeSpecialist) ? [] : [{ name: 'WORKSPACE_CODE_SPECIALIST', secretRef: 'workspace-code-specialist' }],
  empty(workspaceCodeEngineer) ? [] : [{ name: 'WORKSPACE_CODE_ENGINEER', secretRef: 'workspace-code-engineer' }]
)

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' existing = {
  name: logAnalyticsName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: union(tags, { 'azd-service-name': 'app' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: port
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryLoginServer
          identity: identityId
        }
      ]
      secrets: concat(
        [
          { name: 'workspace-token-secret', value: workspaceTokenSecret }
          { name: 'appinsights-connection-string', value: appInsights.properties.ConnectionString }
        ],
        codeSecrets
      )
    }
    template: {
      containers: [
        {
          name: 'app'
          image: appExists ? currentImage : placeholderImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(baseEnv, codeEnv)
          probes: appExists
            ? [
                {
                  type: 'Startup'
                  httpGet: { path: healthPath, port: port }
                  periodSeconds: 5
                  failureThreshold: 24
                }
                {
                  type: 'Liveness'
                  httpGet: { path: healthPath, port: port }
                  periodSeconds: 30
                  failureThreshold: 3
                }
                {
                  type: 'Readiness'
                  httpGet: { path: healthPath, port: port }
                  periodSeconds: 10
                  failureThreshold: 3
                }
              ]
            : []
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: 1
      }
    }
  }
}

output name string = app.name
output uri string = 'https://${app.properties.configuration.ingress.fqdn}'
