// current-image.bicep: reads the image the container app is running now (spec 25 §3.5, D7).
//
// Why it exists: `azd deploy` sets the real image on the app; a later
//   `azd provision` must keep that image instead of resetting it to the
//   placeholder, or every provision would roll the app back (AC-25.29). The read
//   sits in its own nested deployment so it never clashes with the app resource
//   declared in containerapp.bicep.
// What it does: when appExists is true, reads the existing container app and
//   outputs its first container's image; otherwise outputs an empty string.
// What it must not do: create or change anything (existing reference only).
// Acceptance criteria: AC-25.18, AC-25.29.

@description('Name of the container app.')
param appName string

@description('True once the app exists (azd SERVICE_APP_RESOURCE_EXISTS).')
param appExists bool

resource app 'Microsoft.App/containerApps@2025-01-01' existing = if (appExists) {
  name: appName
}

output image string = appExists ? app!.properties.template!.containers![0].image! : ''
