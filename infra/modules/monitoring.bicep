// monitoring.bicep: logs and telemetry for the Discovery Agent (spec 25 §3.4, architecture §7).
//
// Why it exists: the Container Apps environment sends console logs to Log
//   Analytics, and the app sends request telemetry to App Insights (AC-25.25).
//   The daily cap keeps a log storm from becoming a cost runaway (§3.13).
// What it creates: a Log Analytics workspace (PerGB2018, 30 days, daily cap
//   logDailyCapGb) and a workspace-based App Insights component on it.
// What it must not do: output the App Insights connection string or a workspace
//   key (the container app module reads them itself as `existing` resources and
//   keeps them in Container Apps secrets / platform config, AC-25.20).
// Acceptance criteria: AC-25.16, AC-25.20.

@description('Log Analytics workspace name, e.g. log-discovery-<token>.')
param logAnalyticsName string

@description('App Insights component name, e.g. appi-discovery-<token>.')
param appInsightsName string

@description('Region of both resources.')
param location string

@description('Tags for both resources.')
param tags object

@description('Daily ingestion cap in GB, as a decimal string (Bicep has no float type), e.g. "0.5".')
param logDailyCapGb string

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: json(logDailyCapGb)
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

output logAnalyticsName string = workspace.name
output appInsightsName string = appInsights.name
