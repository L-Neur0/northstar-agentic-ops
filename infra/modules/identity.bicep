// identity.bicep: the one user-assigned managed identity of the app (spec 25 §1, §3.4).
//
// Why it exists: the container app reaches the registry (pull), Cosmos DB (data
//   plane) and Azure OpenAI with this identity only; no key or password anywhere.
// What it creates: one Microsoft.ManagedIdentity/userAssignedIdentities resource.
//   Its client id becomes the app's AZURE_CLIENT_ID; its principal id gets the roles.
// What it must not do: assign roles itself (each module that owns a resource
//   assigns the role on it), or output anything secret (an identity has no secret).
// Acceptance criteria: AC-25.13, AC-25.19 (AZURE_CLIENT_ID from this resource).

@description('Identity name, e.g. id-discovery-<token>.')
param name string

@description('Region of the identity.')
param location string

@description('Tags for the identity.')
param tags object

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: name
  location: location
  tags: tags
}

output id string = identity.id
output name string = identity.name
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
