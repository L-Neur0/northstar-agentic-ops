// openai.bicep: access to the hand-made AI Services account (spec 25 §3.4, D1).
//
// Why it exists: the account northstar-discovery-ai and its deployments app-chat
//   and eval-expert were made by hand with quota already granted. The template
//   only READS the account (its endpoint) and lets the app identity call it.
// What it creates: one role assignment, "Cognitive Services OpenAI User", to the
//   app identity at the account's scope, named guid(account id, principal id,
//   role id) so re-provisioning is a no-op.
// What it must not do: declare the account or its deployments as resources to
//   create or update (`existing` only, so what-if shows no change on them); give
//   the developer a role here (their assignment exists already and a duplicate
//   with another name fails with RoleAssignmentExists); use or output a key.
// Acceptance criteria: AC-25.9, AC-25.13, AC-25.14.

@description('Name of the EXISTING AI Services account in this resource group.')
param accountName string

@description('Principal id of the app identity.')
param principalId string

// Built-in role "Cognitive Services OpenAI User".
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}

resource openAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, openAiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = account.properties.endpoint
