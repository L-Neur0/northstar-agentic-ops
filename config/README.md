# Company configuration

Everything specific to one company lives here, never in code. `nig/` is the configuration for the fictional NorthStar Infrastructure Group; a second company would be a second folder (`COMPANY_CONFIG_DIR`). The app validates every file at start-up and refuses to start on an error.

| File | What it sets |
|---|---|
| `organisation.yaml` | Company and product name, regions |
| `taxonomy.yaml` | The nine operational clusters a process is filed under |
| `solutions.yaml` | The tool catalogue the assessment may recommend (existing internal tools first) |
| `readiness.yaml` | Readiness thresholds, "to prepare" wording, the known IT applications |
| `rates.yaml` | Hourly rates (value method parked: hours only for now) |
| `steering.yaml` | Weights used to recommend which process to map first |
| `documents.yaml` | Allowed upload types and size limits |
| `language.yaml` | Words read as yes, no or "accept" |
| `wording.yaml` | Optional overrides of field labels and questions |
