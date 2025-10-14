# Main AI For Impact Portal

## SMTP configuration

Outgoing registration and subscription emails require the following environment variables to be set in production and staging deployments:

- `EMAIL_BACKEND` — set to `smtp` to enable SMTP delivery.
- `SMTP_HOST` — hostname of the SMTP server.
- `SMTP_PORT` — port of the SMTP server.
- `SMTP_USERNAME` — username used to authenticate with the SMTP server.
- `SMTP_PASSWORD` — password or app-specific token used to authenticate.
- `SMTP_FROM` — display name and address used in the From header.

Provide these values securely (for example via deployment environment variables or your secret manager). Both the registration notification emails and the subscription welcome emails rely on the same credentials, so updating them in one place keeps the services aligned.

After updating the credentials, trigger a test registration or newsletter subscription in staging/production to verify that the welcome email is delivered successfully.
