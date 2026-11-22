# Company configuration

This folder is part of the [AI Use Case Discovery Agent](../README.md). Everything that is specific to one company lives here, and never in the code. The `nig/` folder holds the configuration for the fictional NorthStar Infrastructure Group. If a second company used the tool, it would get its own folder, which you select with `COMPANY_CONFIG_DIR`. When the app starts, it checks every file and refuses to start if one of them has an error.

| File | What it sets |
|---|---|
| `organisation.yaml` | The company name, the product name and the regions |
| `taxonomy.yaml` | The nine operational clusters that a process can belong to |
| `solutions.yaml` | The catalogue of tools that the assessment may recommend, with the company's existing tools listed first |
| `readiness.yaml` | The readiness thresholds, the "to prepare" wording and the known IT applications |
| `rates.yaml` | Hourly rates (the euro value is parked for now, so the report shows hours only) |
| `steering.yaml` | The weights used to recommend which process to map first |
| `documents.yaml` | Which file types can be uploaded, and the size limits |
| `language.yaml` | The words that are read as yes, no or "accept" |
| `wording.yaml` | Optional changes to field labels and questions |
