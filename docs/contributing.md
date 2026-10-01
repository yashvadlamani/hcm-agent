# Contributing and security

How to make a change to Clara and ship it, and how to handle secrets safely. New here? Start with [Setup](./setup.md).

## Workflow

```
main ──▶ your branch ──▶ pull request ──▶ CI + review ──▶ merge ──▶ automatic deploy
```

1. **Start from an up-to-date `main`:** `git checkout main && git pull`, then `git checkout -b short-descriptive-name`.
2. **Make one focused change.**
3. **Check it locally:** `ruff check .` and `pytest`. No keys, network or phone needed.
4. **Commit and push:** `git commit -m "Add Do-Not-Call check before placing calls"`, then `git push -u origin <branch>`.
5. **Open a pull request into `main`.** Fill in the template. CI must pass, and the code owner reviews it.
6. **Merge.** GitHub Actions deploys what changed. Delete the branch afterwards.

`main` is always deployable. Never commit to it directly.

| Branch | Purpose |
|---|---|
| `main` | The live version. Merging deploys to Azure |
| `twilio-main` | Frozen snapshot of the earlier Twilio version, kept for reference |
| Feature branches | One change each; deleted after merging |

## Standards

- **Commits:** start with an imperative verb and say what changes ("Add…", "Fix…"), with a first line under about 72 characters.
- **Code:** Python 3.10+, `ruff` with a line length of 120. Comments explain *why*, not *what*.
- **Settings:** add new ones to [`hcm_agent/config.py`](../hcm_agent/config.py) and [`config/.env.example`](../config/.env.example), and to the deploy scripts if Azure needs them.
- **Tests:** every behavior change comes with a test in [`tests/`](../tests/). Tests must not need keys, network access or a phone; use the existing stand-ins (`FakeACS` in `test_server.py`, the fake model clients in `test_llm.py`, the fake storage in `test_function_app.py`).
- **Docs:** update them in the same pull request:
  - **[Architecture](./architecture.md):** how calls or components work
  - **[Setup](./setup.md):** setup or deployment
  - **[Operations](./operations.md):** running Clara
  - **[Roadmap history](./roadmap.md#history):** user-visible changes

## Safety-critical files

Changes here need extra care, and a clinical or compliance reviewer before production:

- [`hcm_agent/agent/prompts.py`](../hcm_agent/agent/prompts.py): what Clara may and may not say
- [`hcm_agent/agent/guardrails.py`](../hcm_agent/agent/guardrails.py): reply and emergency checks
- [`hcm_agent/telephony/server.py`](../hcm_agent/telephony/server.py): emergency handling during calls
- [`hcm_agent/telephony/outbound.py`](../hcm_agent/telephony/outbound.py) and [`hcm_agent/azure_functions/function_app.py`](../hcm_agent/azure_functions/function_app.py): who may be called (allow-list and rate limit)

## Security

Clara is a **prototype**. It isn't HIPAA-compliant and must not be used with real patient data. See the [path to real patient calls](./roadmap.md#path-to-real-patient-calls).

### Handling secrets

- Secrets belong only in `.env`, which is git-ignored, and in Azure Key Vault, where the deploy scripts put them. **Never commit `.env`.**
- Review what's staged with `git diff --cached` before committing. GitHub push protection doesn't catch every key format.
- Don't paste keys into chats, tickets or docs. Treat any key shared that way as exposed.

### If a secret leaks

1. **Rotate it immediately** at the source: the Azure portal for Azure OpenAI and ACS keys (resource → **Keys** → regenerate), or the Anthropic Console for Claude. Removing a key from Git doesn't make it safe.
2. **Update `.env` and re-run the deploy scripts.** Key Vault and the apps pick up the new value.
3. **If it was committed,** remove it from history (for example with `git filter-repo`), force-push, and have everyone re-clone.
4. **Close the GitHub secret-scanning alert** once the old value is revoked.

### Current protections

| Area | Protection |
|---|---|
| Deployed secrets | Key Vault, read by each app through its own managed identity |
| Call events | Accepted only with the secret key in the callback URL |
| Who can be called | Allow-list, an hourly limit, and verified numbers on the trial number |
| Live dashboard | Password over HTTPS; local-only when no password is set; text never rendered as HTML |
| Call-request storage | Private container; each request processed once |

Known gaps before production are listed in the [roadmap](./roadmap.md#path-to-real-patient-calls). Report security problems to the repository owner directly, not in a public issue.
