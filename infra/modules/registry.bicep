// registry.bicep: the private image registry of the Discovery Agent (spec 25 §3.4, D4).
//
// Why it exists: azd pushes the image built by Docker (developer machine or CI
//   runner) here, and the container app pulls it with its managed identity.
// What it creates: an Azure Container Registry (Basic, admin user off, anonymous
//   pull off) and one AcrPull role assignment to the app identity, named
//   guid(registry id, principal id, role id) so re-provisioning is a no-op.
// What it must not do: enable the admin user or any password, or give the
//   developer or CI principal a role here (azd pushes with the caller's own rights).
// Acceptance criteria: AC-25.13, AC-25.14, AC-25.15.

@description('Registry name (alphanumeric only), e.g. crdiscovery<token>.')
param name string

@description('Region of the registry.')
param location string

@description('Tags for the registry.')
param tags object

@description('Principal id of the app identity that pulls images.')
param pullPrincipalId string

// Built-in role "AcrPull".
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled' // prototype; private endpoints are a production item
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, pullPrincipalId, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: pullPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output name string = registry.name
output loginServer string = registry.properties.loginServer
