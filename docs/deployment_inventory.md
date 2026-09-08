# Deployment declarations

`--deployment-inventory FILE` accepts an optional local JSON file. Keep real inventory outside the packaged skill directory; the [example](deployment_inventory.example.json) is synthetic. Do not include prompts, API keys, credentials or other secrets.

```sh
python scripts/forge_dashboards.py --capability ../instance/capability_map.json --deployment-inventory ../instance/deployment_inventory.json --blueprints governance --locale fr
```

The root object contains exactly `{"schema_version": 1, "deployments": [...]}`. The file must be UTF-8, at most **1,048,576 bytes**, with at most **500 records**. Duplicate JSON keys, unknown fields, other versions and wrong types are rejected before pricing fallback, cache writes or Grafana access, including `--dry-run`.

| Record field | Required | Maximum characters | Meaning |
|---|---|---:|---|
| `deployment_id` | yes | 128 | Unique within this file |
| `datasource_uid` | yes | 128 | Must exist in the complete capability map |
| `model` | yes | 256 | Exact model string for capability-map observation matching |
| `serving_provider` | no | 128 | Declared service operator, separate from model-provider origin |
| `endpoint_host` | no | 253 | ASCII DNS hostname, including local names such as `ollama` |
| `processing_region` | no | 128 | Declared processing location, e.g. `FR` or `eu-west-3` |
| `storage_region` | no | 128 | Declared storage location |
| `evidence_ref` | no | 512 | Plain-text reference; never fetched or rendered as a link |
| `evidence_date` | no | 10 | Valid ISO calendar date `YYYY-MM-DD`, still a declaration |

Every supplied value must be a non-empty string without control, formatting-control or surrogate characters. CR/LF and tabs are rejected. Omit unknown optional fields rather than supplying null or empty text. DNS labels are 1–63 ASCII letters/digits/hyphens and cannot begin/end with a hyphen; an optional terminal dot is accepted. URL schemes, IP addresses, credentials, ports, paths and queries are rejected from `endpoint_host`. Use the ASCII/punycode hostname for internationalized DNS names.

`FILE` accepts relative paths or ordinary absolute local filesystem paths (including `C:/...` on Windows). UNC paths, Windows device names/namespaces, URLs, drive-relative paths such as `C:inventory.json`, and alternate data streams are rejected lexically before filesystem access. The final path must be a regular file; symbolic links, reparse points, directories, FIFOs and sockets are rejected before opening, with a second file-type check after opening. Store it in a trusted local directory: filesystem mount configuration and parent-directory indirection are not certified by this loader.

Multiple deployments for the same datasource/model are legitimate and remain separate rows. Validation uses the complete capability map before `--datasource` filtering, so one file can cover production and staging. Only selected records appear in the table. A model is `observed_in_capability_map` only on an exact match within that datasource; that observation verifies neither a deployment endpoint nor its location. Missing locations are `unknown`; provided locations are `declared`. Evidence references and dates never change that status.

The registry field and recording-rule label `region` keep their existing semantics and spelling: model-provider origin. They do not establish processing or storage location. The deployment table shows registry origin and declared processing/storage separately. It uses a Grafana text panel in HTML mode with escaped text cells and no links or remote content.

The manifest adds `deployment_inventory`: whether a file was supplied, selected scope, loaded/in-scope/excluded record counts, declared datasource UIDs in scope, declared/unknown field counts, `records_with_observed_model` and `independent_checks: not_performed`. Counts refer to deployment records, including replicas; they are not counts of distinct models. Endpoint hosts, evidence references/dates and the input path are omitted from the manifest. The generated governance dashboard contains those declarations, so treat its export according to your inventory's access policy.
