# Google Sheets (retired)

The unified **`google_sheets`** Cloud Run worker is retired. Sheet upload
verticals are split into dedicated workers:

| System | App | Cloud Run (target) |
|--------|-----|--------------------|
| Alumni Google Sheet | [`hr_alumni/`](../hr_alumni/) | `hr-alumni-{dev,prod}` |
| Contact Us Google Sheet | [`bizdev_contacts/`](../bizdev_contacts/) | `bizdev-contacts-{dev,prod}` |

Legacy `google_sheets_attempts` rows and `google_sheets_*` schema prefixes remain
in Postgres for historical rows; new work uses `hr_alumni_*` and
`bizdev_contacts_*` attempt tables (see [`db/migrations/`](../../db/migrations/)).

Deploy via `infra/cloudbuild/hr-alumni-*.yaml` and
`infra/cloudbuild/bizdev-contacts-*.yaml` (replacing retired
`google-sheets-*.yaml`).
