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

### Troubleshooting Zoho SMTP authentication

Zoho accounts frequently reject basic username/password logins unless SMTP access has been explicitly enabled. If you see `SMTPAuthenticationError: (535, b'Authentication Failed')` in the Render logs when submitting the bootcamp form:

1. **Confirm the SMTP host and port.** For Zoho Mail use `smtp.zoho.com` (US) or `smtp.zoho.eu` (EU) on port `465` for SSL or port `587` for STARTTLS. Update the `SMTP_HOST` and `SMTP_PORT` environment variables to match the datacentre your mailbox lives in.
2. **Generate an app password.** Zoho requires an app-specific password when multi-factor authentication is enabled. Create one from the Zoho Mail Security settings and set the resulting value as `SMTP_PASSWORD`. Regular account passwords are rejected by SMTP.
3. **Enable IMAP/POP access.** From Zoho Mail settings → Mail Accounts → Email Forwarding and POP/IMAP, toggle on “Enable IMAP Access”. SMTP logins are blocked until this switch is enabled.
4. **Double-check the sender address.** Ensure `SMTP_FROM` and `SMTP_USERNAME` share the same domain (`aiforimpact.net`). Zoho blocks sending from mismatched domains.
5. **Retry and monitor logs.** After updating the environment variables, redeploy, submit a test request, and watch the Render logs for `Bootcamp cohort request email sent`. If authentication still fails, the logs will include Zoho’s rejection reason to help with support tickets.

Never commit the raw credentials to the repository—store them in the hosting platform’s secret manager instead.
