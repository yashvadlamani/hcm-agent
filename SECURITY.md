# Security

Clara is a **prototype**. It isn't HIPAA-compliant and must not be used with real patient data. See [Before production](./docs/GETTING_STARTED.md#8-before-production) for what's needed first.

## Handling secrets

- Keys and passwords belong only in `.env`, which is listed in `.gitignore`, and, when deployed, in Azure Key Vault, where the deploy scripts put them (see [docs/DEPLOY_AZURE.md](docs/DEPLOY_AZURE.md#where-the-secrets-live)). **Never commit `.env`.**
- Before committing, check what's staged with `git diff --cached`. GitHub push protection blocks some key formats, but not all.
- Don't paste keys into chats, tickets or docs. Treat any key that has been shared that way as exposed.
- `.env.example` documents every setting without real values. Keep it in sync when you add one.

## If a secret leaks

1. **Rotate it immediately** at the provider (Anthropic Console, Twilio Console, Azure portal). Removing it from Git doesn't make it safe; anyone who cloned or viewed the repo may already have it.
2. Update `.env` and re-run the deploy scripts. They save the new value to Key Vault, and the apps reload it.
3. If it was committed, remove it from the history (for example with `git filter-repo`), force-push, and ask everyone with a clone to delete it and clone again.
4. Close the secret-scanning alert on GitHub once the old value is revoked.

## What the app protects today

- **Twilio webhooks** need a secret key in the URL (`PHONE_WEBHOOK_KEY`) and your Twilio Account SID. A Twilio signature is verified whenever one is sent (paid accounts sign every request).
- **The live call view** (`/live`) is local-only unless `LIVE_VIEW_PASSWORD` is set, and then it needs that password over HTTPS.
- All call text is shown as plain text in the live view, never as HTML.

## Reporting a problem

Contact the repository owner directly rather than opening a public issue.
