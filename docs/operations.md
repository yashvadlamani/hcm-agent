# Operations

Running Clara day to day: the environment, health checks, turning it on and off, logs, keys, phone numbers, costs and troubleshooting. Deploying is covered in [Setup](./setup.md).

## Environment

| Item | Value |
|---|---|
| Resource group | `clara-rg` (Central US; Azure OpenAI in East US 2) |
| Clara server | `clara-hcm-agent-demo`, at `https://clara-hcm-agent-demo.azurewebsites.net` |
| Live dashboard | `…/live`. The password is the Key Vault secret `LIVE-VIEW-PASSWORD` |
| Call-request function | `clara-hcm-agent-calls` |
| Call-request storage | Container `call-requests`, with folders `incoming/`, `processed/` and `failed/` |
| Phone calls | Azure Communication Services `clara-acs-<id>`, trial number |
| Model | Azure OpenAI deployment `clara-chat` (`gpt-5-mini`) |
| Secrets | Key Vault `clara-kv-<id>` |
| Hosting tier | App Service Free (F1) |

## Health check

1. **Server:** `https://<app>.azurewebsites.net` says *"Clara phone server is running."* The first load after idle can take a minute.
2. **Secrets:** **Web app → Settings → Environment variables** shows a green *Key vault reference* tick for every secret.
3. **Deploys:** the README badges, or the **Actions** tab, are green.
4. **End to end:** upload a request for a number that isn't on the allow-list. It should land in `failed/` within seconds, and no call is placed.

## Turning Clara on and off

| To | Run |
|---|---|
| Turn off | `powershell -ExecutionPolicy Bypass -File .\hcm_agent\deploy\stop.ps1 -AppName <app>` |
| Turn on | `powershell -ExecutionPolicy Bypass -File .\hcm_agent\deploy\start.ps1 -AppName <app>` (add `-Sku B1` on Basic) |

`stop.ps1` also moves the plan to the Free tier, because a stopped app on a paid plan is still billed. Calls in progress and the dashboard's history are held in memory, so they clear whenever the app stops, restarts or sleeps.

**Always on (B1):** in the portal, open **Quotas → App Service** and request a limit of 1 for **Basic B1 VMs**. A free trial may need upgrading to pay-as-you-go first; upgrading keeps any remaining credit. Once approved, run `start.ps1 -AppName <app> -Sku B1`.

## Logs

```powershell
az webapp log tail --resource-group clara-rg --name <app>
```

The server log shows every call event (`ACS CallConnected`, `RecognizeCompleted`…), each turn, Clara's replies with timings, and the full transcript when a call ends. For the function, open **Function app → call_request → Invocations**.

## Keys and secrets

To change or rotate a key:
1. Regenerate it at the source:
   - **Azure OpenAI or ACS:** resource → **Keys** → regenerate
   - **Claude:** Anthropic Console
   - **`PHONE_WEBHOOK_KEY` or `LIVE_VIEW_PASSWORD`:** generate a new random value
2. Update `.env`.
3. Re-run `deploy.ps1`, and `deploy_function.ps1` if the function uses that key. The apps pick up the new value right away.

If a key may have leaked, follow the [security steps](./contributing.md#if-a-secret-leaks).

## Phone numbers

| | Trial number (current) | Purchased number |
|---|---|---|
| Cost | Free | A small monthly fee plus per-minute charges |
| Who it can call | Up to 3 verified US numbers | Anyone |
| Limits | 60 outbound minutes, 5-minute calls, expires after 30 days | None |
| Requires | A US billing address | A pay-as-you-go subscription |

- **Trial usage, or verifying another test phone:** ACS → **Phone numbers** → the number → **Trial details**.
- **Switching to a purchased number:** ACS → **Phone numbers → Get**, with outbound calling enabled. Set `ACS_PHONE_NUMBER` and re-run both deploy scripts. Keep `ALLOWED_CALL_NUMBERS` limited until patient eligibility checks exist (see the [roadmap](./roadmap.md)).

## Costs

| Resource | Cost today |
|---|---|
| App Service F1 | Free |
| Function app (Flex Consumption) | The monthly free grant covers test use |
| Storage, Event Grid, Key Vault | A few cents a month |
| ACS trial number | Free (per-minute charges after the trial) |
| Azure OpenAI and Speech | Pay per use, a few cents per test call |

Check **Cost Management + Billing** in the portal.

## Removing everything

```powershell
az group delete --name clara-rg
```

This permanently deletes every resource, including the ACS resource (which releases the phone number) and the Key Vault. The vault stays recoverable for 7 days.

## Troubleshooting

Start with the server log (see [Logs](#logs)).

### Calls

| Symptom | Likely cause | Fix |
|---|---|---|
| Placing a call fails right away | The number isn't verified, or the trial is out of days or minutes | ACS → **Phone numbers** → the number → **Trial details** |
| The phone rings but Clara never speaks | The server didn't receive ACS's events: it's off, starting, or the URL is wrong | Check that `/` loads; run `start.ps1`. The log should show `ACS CallConnected` |
| Clara speaks but never hears you (`RecognizeFailed` in the log) | ACS can't reach the speech service | Check `ACS_COGNITIVE_SERVICES_ENDPOINT`, and that the ACS identity has **Cognitive Services User** on the AI resource |
| *"I'm having trouble connecting right now"* | The model request failed | Check the `AZURE_OPENAI_*` settings (or `ANTHROPIC_API_KEY`), re-run `deploy.ps1`, and check the log |
| Clara goes silent mid-call | The server restarted (for example, a deploy) | Call again; don't merge to `main` during test calls |
| The call ends after exactly 5 minutes | Trial number limit | Keep test calls short, or buy a number |
| `clara-call` says the server didn't respond | The app is stopped or failed to start | Run `start.ps1`, then check the log |

### Call-request uploads

| Symptom | Fix |
|---|---|
| The file lands in `failed/` | Read the reason in the file. Usually the number isn't in `ALLOWED_CALL_NUMBERS` |
| The file stays in `incoming/` | Check **Function app → call_request → Invocations**; re-run `deploy_function.ps1` to recreate the trigger |
| Nothing happens | The file must be in `incoming/` and end in `.json` |

### Deploying

| Symptom | Fix |
|---|---|
| "Name already taken" | Choose a different `-AppName` |
| *"Operation cannot be completed without additional quota"* | Use the default `F1` tier, or request B1 quota |
| The code upload times out (HTTP 504) on the Free tier | The script retries automatically, and Azure often finishes anyway. Check that `/` loads |
| `/` shows "Application Error" | Usually a missing setting: check the log, fix `.env`, re-run `deploy.ps1` |
| A red *Key vault reference* error | New access takes a few minutes; re-run `deploy.ps1` |
| A GitHub deploy fails with an authentication error | Re-run the deploy script with `-PublishProfilePath` and update the GitHub secret |
| `az login` is blocked by "security defaults" | Use `az login` (browser sign-in) rather than `--use-device-code` |
| A script is blocked by execution policy | Use `powershell -ExecutionPolicy Bypass -File …` |

### Live dashboard

| Symptom | Fix |
|---|---|
| It keeps asking for a password | Use the exact `LIVE_VIEW_PASSWORD` you deployed with; the username can be anything |
| A call stays "in progress" | The server missed the end of the call; it clears on the next restart |
| History disappeared | Normal: history is in memory and clears when the server restarts or sleeps |
