// cosmos.bicep: the session store of the Discovery Agent (spec 15 §3.7, spec 25 §3.4).
//
// Why it exists: spec 15's Cosmos store reads and writes items only; it never
//   creates a database or container. This module owns them.
// What it creates: a Cosmos DB for NoSQL account (serverless, keys off, one
//   region, Continuous7Days backup), database `discovery`, container `sessions`
//   (partition key /ownerId, defaultTtl -1), and one "Cosmos DB Built-in Data
//   Contributor" data-plane role assignment per principal id passed in.
// What it must not do: enable key (local) auth, set throughput (serverless),
//   output a key or connection string, or touch any other resource.
// Acceptance criteria: AC-25.11, AC-25.12, AC-25.14.

@description('Cosmos DB account name.')
param accountName string

@description('Region of the account (single region). Spec 25 Q5: another EU region if swedencentral has no serverless capacity.')
param location string

@description('Tags for every resource in this module.')
param tags object

@description('Database name. Must match the app setting COSMOS_DATABASE.')
param databaseName string = 'discovery'

@description('Container name. Must match the app setting COSMOS_CONTAINER.')
param containerName string = 'sessions'

@description('Object ids that get the data-plane role at account scope (the developer now; the app identity once spec 25 adds it). Empty strings are skipped.')
param dataContributorPrincipalIds array = []

// Built-in "Cosmos DB Built-in Data Contributor" (data plane, not Azure RBAC).
var dataContributorRoleId = '00000000-0000-0000-0000-000000000002'
var principalIds = filter(dataContributorPrincipalIds, id => !empty(id))

resource account 'Microsoft.DocumentDB/databaseAccounts@2025-10-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
    ]
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Enabled' // prototype; private endpoints are a production item
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-10-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-10-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: ['/ownerId']
        kind: 'Hash'
      }
      defaultTtl: -1 // TTL on; only items that carry `ttl` expire (spec 15 §3.3)
    }
  }
}

resource dataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-10-15' = [
  for principalId in principalIds: {
    parent: account
    name: guid(account.id, principalId, dataContributorRoleId)
    properties: {
      roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleId}'
      principalId: principalId
      scope: account.id
    }
  }
]

output endpoint string = account.properties.documentEndpoint
output accountName string = account.name
output databaseName string = database.name
output containerName string = container.name
