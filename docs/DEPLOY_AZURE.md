# Deploying Clara to Azure

This guide puts the Clara phone server on **Azure App Service**, so it runs in the cloud instead of on your laptop. You get a permanent public address like `https://clara-yourname.azurewebsites.net` that Twilio can reach during calls, and anyone with the password can open the live call view.

> ⚠️ **Test data only.** An Azure free trial is not covered by a Business Associate Agreement (BAA), so it is not HIPAA-compliant. Don't use it with real patients. See [Before production](./GETTING_STARTED.md#8-before-production).

**What gets created** (all in one resource group, `clara-rg`):

| Resource | Purpose |
|---|---|
| App Service plan `<app>-plan` (Linux, **Free F1** by default) | The server the app runs on |
| Web app `<app>` (Python 3.12) | The Clara server, with HTTPS at `https://<app>.azurewebsites.net` |

### Which tier?

| Tier | Cost | Behavior |
|---|---|---|
| **Free (F1)**, the default | $0 | Works on a new free-trial subscription. The app **sleeps after about 20 idle minutes** and takes up to a minute to wake. `clara-call` wakes it before dialing, so calls still work. Calls and the live view's history are cleared when it sleeps. There's also a daily CPU-time cap, which is plenty for demo calls. |
| **Basic (B1)** | About $13/month while on | Always On: never sleeps. **New free-trial subscriptions have no B1 quota** (deploying fails with *"Operation cannot be completed without additional quota"*). See [Moving to B1](#moving-to-b1-always-on) to request it. |

---

## 1. Install the Azure CLI and sign in (one time)

```powershell
winget install -e --id Microsoft.AzureCLI
```

Close and reopen PowerShell, then sign in. A browser window opens for your Azure account.

```powershell
az login
```

## 2. Add a password for the live view

On Azure, the live call view is on the public internet, so it needs a password. Generate one:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(16))"
```

Add it to your `.env`:

```
LIVE_VIEW_PASSWORD=<paste the generated value>
```

## 3. Pick an app name

The name becomes your address, so it must be unique across all of Azure. Use lowercase letters, numbers and hyphens, for example `clara-yv-demo`.

## 4. Deploy

From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\azure\deploy.ps1 -AppName clara-yv-demo
```

The script:
1. creates the resource group, plan and web app
2. stores the secrets from your `.env` in an Azure Key Vault, and the other settings in the app (the values are never printed)
3. sets the startup command, Always On and HTTPS-only
4. uploads the code

Expect 5–10 minutes the first time. Re-run the same command whenever you change `.env` settings. Code changes can deploy themselves from GitHub instead: see [Automatic deploys from GitHub](#automatic-deploys-from-github).

### Where the secrets live

On your laptop, Clara reads everything from `.env`, as before. In Azure, the secrets live in one Key Vault, named `clara-kv-<id>`, which the script creates in `clara-rg`:

| Secret setting | Key Vault secret |
|---|---|
| `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY` | `ANTHROPIC-API-KEY`, `AZURE-OPENAI-API-KEY` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | `TWILIO-ACCOUNT-SID`, `TWILIO-AUTH-TOKEN` |
| `PHONE_WEBHOOK_KEY`, `LIVE_VIEW_PASSWORD` | `PHONE-WEBHOOK-KEY`, `LIVE-VIEW-PASSWORD` |
| `CallRequestsStorage` (Function only) | `CallRequestsStorage` |

The web app and the Function app each have their own Azure identity (a managed identity) with read-only access to the vault. Their settings hold references like `@Microsoft.KeyVault(VaultName=…;SecretName=TWILIO-AUTH-TOKEN)` rather than the values. Non-secret settings, such as the phone number and the model endpoint, stay as plain app settings.

**Changing a key:** update it in `.env` and re-run the deploy script, or `deploy_function.ps1` for the Function's settings. The script saves the new value as a new version of the secret and makes the app reload it right away.

To check that the app can read every secret, open **Web app → Settings → Environment variables** in the portal. Each secret should show a green *Key vault reference* tick.

Optional arguments: `-Sku B1` (default `F1`), `-Location westus2` (default `eastus`) and `-ResourceGroup <name>` (default `clara-rg`). If you change `-Location`, also use a new `-ResourceGroup` name, because a resource group can't move regions.

## 5. Check it's running

1. Open `https://<app>.azurewebsites.net`. You should see **"Clara phone server is running."** The first load after a deploy can take a minute.
2. Open `https://<app>.azurewebsites.net/live` and sign in. The username can be anything; the password is your `LIVE_VIEW_PASSWORD`.

## 6. Place a test call

Point the call at your Azure address:

```powershell
clara-call --url https://<app>.azurewebsites.net --to +1XXXXXXXXXX --name <FirstName>
```

On the Free tier, if the app has been idle you'll see *"Waking the server…"* for up to a minute before the phone rings. That's expected.

Keep `/live` open to watch the call as it happens. The Twilio trial-account limits in the [Getting Started guide](./GETTING_STARTED.md#twilio-trial-account-limits) still apply.

## Placing calls by uploading a file

An Azure Function can place calls for you: upload a small JSON file to a storage container and Clara calls that number. The code lives in [`functions/`](../functions/) and reuses the same call logic as `clara-call`.

```
request.json ──upload──▶ storage container call-requests/incoming/
                              │  (Event Grid: new .json file)
                              ▼
                     Function app ──checks──▶ Twilio call to the Clara server
                              │
                              ▼
            call-requests/processed/ or call-requests/failed/ (the result)
```

### Set it up (one time)

1. In `.env`, set the numbers Clara may call. The function refuses everything else:

   ```
   ALLOWED_CALL_NUMBERS=+1XXXXXXXXXX
   MAX_CALLS_PER_HOUR=10
   ```

2. Deploy the storage account, the Function app (Flex Consumption, which has a monthly free grant) and the Event Grid trigger:

   ```powershell
   .\deploy\azure\deploy_function.ps1 -FunctionApp <function-app-name> -ClaraAppName <app> -PublishProfilePath .\publish-profile.xml
   ```

   Re-run it whenever you change these settings in `.env`. It's safe to repeat.

3. Optionally, let GitHub redeploy the function's code on every push: see [Automatic deploys from GitHub](#automatic-deploys-from-github).

### Place a call

Create `request.json`:

```json
{ "to": "+1XXXXXXXXXX", "name": "Yash", "risk_drivers": ["missed refills", "high A1C"] }
```

| Field | Required | Rules |
|---|---|---|
| `to` | Yes | Phone number with at least 10 digits, e.g. `"+17044305315"` or `"704-430-5315"`. Must be in `ALLOWED_CALL_NUMBERS` |
| `name` | No | Up to 60 characters; Clara greets with "Hi there" without it |
| `risk_drivers` | No | List of up to 5 strings, each at most 100 characters. Shapes what Clara asks about |

Upload it to `incoming/`, either in the Azure portal (**Storage account → Containers → call-requests**) or with:

```powershell
az storage blob upload --account-name <storage-account> --auth-mode key -c call-requests -n incoming/request.json -f request.json
```

The storage account's name is printed at the end of `deploy_function.ps1`. The phone rings within about a minute; the Clara server must be on. The request then moves to `processed/` (with the Twilio call SID) or `failed/` (with the reason).

The function places a call only when all of these hold:
- The file is valid JSON under 10 KB, with a phone number in `to`.
- The number is in `ALLOWED_CALL_NUMBERS`.
- Fewer than `MAX_CALLS_PER_HOUR` calls were placed in the last hour.

Each file is handled once, even if Azure delivers the event twice.

`incoming/` always contains a `README.txt` with these instructions. It keeps the folder visible between uploads, because blob storage only shows a folder while it holds a file. It never triggers a call, and the function puts it back if it's deleted.

## Automatic deploys from GitHub

Two GitHub Actions workflows redeploy code when it changes on `main`:

| Workflow | Deploys | Runs when a push to `main` changes |
|---|---|---|
| [deploy-server.yml](../.github/workflows/deploy-server.yml) | The Clara server (App Service). Lint and tests must pass first | `src/hcm_agent/`, `requirements.txt`, `deploy/azure/package.py` |
| [deploy-function.yml](../.github/workflows/deploy-function.yml) | The call-request function | `functions/`, `src/hcm_agent/`, `deploy/azure/package_function.py` |

Watch them in the repository's **Actions** tab. Either can also be run by hand: **Actions → the workflow → Run workflow**.

They deploy code only. Settings and secrets still come from `.env` through the deploy scripts, so re-run those when `.env` changes.

### Set up (one time)

Each workflow needs a publish profile, which lets GitHub deploy to that app. The deploy scripts can write one:

```powershell
.\deploy\azure\deploy.ps1 -AppName <app> -Location centralus -PublishProfilePath .\server-profile.xml
.\deploy\azure\deploy_function.ps1 -FunctionApp <function-app-name> -ClaraAppName <app> -PublishProfilePath .\function-profile.xml
```

In your GitHub repository, go to **Settings → Secrets and variables → Actions** and add:

| Name | Kind | Value |
|---|---|---|
| `AZURE_WEBAPP_PUBLISH_PROFILE` | Secret | The whole of `server-profile.xml` |
| `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` | Secret | The whole of `function-profile.xml` |
| `AZURE_WEBAPP_NAME` | Variable | Your app's name; not needed if it's `clara-hcm-agent-demo` |
| `AZURE_FUNCTIONAPP_NAME` | Variable | Your function app's name; not needed if it's `clara-hcm-agent-calls` |

Then delete both `.xml` files: they work like passwords. Without a secret, its workflow skips the deploy.

### Good to know

- **A server deploy restarts Clara and drops any call in progress.** Merge to `main` between test calls.
- **The Free tier's deploy service is slow.** A server deploy takes 5–15 minutes and is retried once if Azure times out. The workflow then waits for Clara to respond.
- **If the app is stopped** (`stop.ps1`), the code still deploys and runs the next time you start it. The workflow shows a warning instead of failing.
- **If a profile stops working** (for example, after you reset it in the portal), re-run the deploy script with `-PublishProfilePath` and update the secret.

---

## Turning it on and off

| To | Run |
|---|---|
| Turn off | `powershell -ExecutionPolicy Bypass -File .\deploy\azure\stop.ps1 -AppName <app>` |
| Turn back on (Free tier) | `powershell -ExecutionPolicy Bypass -File .\deploy\azure\start.ps1 -AppName <app>` |
| Turn back on (on B1) | `powershell -ExecutionPolicy Bypass -File .\deploy\azure\start.ps1 -AppName <app> -Sku B1` |

`stop.ps1` stops the app and makes sure the plan is on the Free tier. On F1 that's just a switch, since F1 costs nothing either way. On B1 the tier change matters: stopping the app alone, including with the **Stop** button in the Azure portal, doesn't stop billing, because the paid plan keeps charging.

Calls in progress and the live view's history are held in memory, so they're cleared whenever the app stops, restarts or (on F1) goes to sleep.

## Moving to B1 (Always On)

1. In the Azure portal, open **Quotas**, then **App Service**. Find **Basic B1 VMs** for your region and **request a new limit of 1**. Free-trial subscriptions may need to be upgraded to pay-as-you-go first. Upgrading keeps any remaining credit.
2. Once it's approved:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\deploy\azure\start.ps1 -AppName <app> -Sku B1
   ```
   This moves the plan to B1 and turns Always On on. Use `-Sku B1` with `start.ps1` from then on.

## Choosing the model: Claude or Azure OpenAI

Clara can generate replies with **Claude** (Anthropic's API) or with a model you deploy in **Azure AI Foundry** (Azure OpenAI). The `LLM_PROVIDER` setting in `.env` picks one. The prompts, emergency checks and guardrails are the same for both.

| `LLM_PROVIDER` | Settings it needs in `.env` |
|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY`, and optionally `ANTHROPIC_MODEL` (default `claude-opus-5`) |
| `azure_openai` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, and optionally `AZURE_OPENAI_REASONING_EFFORT` |

### Setting up Azure OpenAI

1. In **https://ai.azure.com**, create a project (resource group `clara-rg` keeps everything together).
2. Deploy a chat model under **Models + endpoints → Deploy model**, using deployment type **Global Standard**. Pick one your subscription has quota for; on a new trial that may only be `gpt-5-mini`. To check quota from the command line:
   ```powershell
   az cognitiveservices usage list -l <region> -o table
   ```
3. Copy these values into `.env`:
   ```
   LLM_PROVIDER=azure_openai
   AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
   AZURE_OPENAI_API_KEY=<key from the deployment page>
   AZURE_OPENAI_DEPLOYMENT=<your deployment name, not the model name>
   ```
   Use the **v1** endpoint (ending in `/openai/v1`). It doesn't need an API version.
4. Try it locally, then redeploy so Azure picks up the new settings:
   ```powershell
   clara-chat interactive
   powershell -ExecutionPolicy Bypass -File .\deploy\azure\deploy.ps1 -AppName <app> -Location <region>
   ```

**Reasoning effort:** gpt-5 family models are reasoning models and are slow at their default effort. Clara sends `reasoning_effort=minimal` by default, which keeps replies around 2 seconds. For a non-reasoning model such as `gpt-4o`, set `AZURE_OPENAI_REASONING_EFFORT=` (empty) in `.env`.

**To switch back to Claude:** set `LLM_PROVIDER=anthropic` and redeploy.

Azure OpenAI usage is billed to your Azure subscription. Check **Cost Management + Billing** to confirm it counts against your trial credit.

## Watching the server logs

```powershell
az webapp log tail --resource-group clara-rg --name <app>
```

You'll see the same output a local terminal shows: each patient turn, Clara's replies and any errors. Press `Ctrl+C` to stop watching.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy fails with "name already taken" or "not available" | Choose a different `-AppName` |
| Deploy fails with *"Operation cannot be completed without additional quota"* | Your subscription has no quota for that tier. Use the default `F1`, or request B1 quota (see [Moving to B1](#moving-to-b1-always-on)) |
| Deploy fails with "not available in this region" | Retry with `-Location westus2` or `-Location centralus`, and a new `-ResourceGroup` name |
| `clara-call` says the server didn't respond | The app is stopped (run `start.ps1`) or failed to start (check the logs) |
| `az` is not recognized | Reopen PowerShell after installing the Azure CLI |
| Running the script is blocked by execution policy | Use the `powershell -ExecutionPolicy Bypass -File …` form shown above |
| `/` shows an Azure "Application Error" page | Check the logs (above). Usually a missing setting: re-run the deploy script after fixing `.env` |
| A setting shows a red *Key vault reference* error in the portal | The app's identity can't read the vault yet (new access can take a few minutes). Re-run the deploy script |
| `/live` keeps asking for a password | Use the exact `LIVE_VIEW_PASSWORD` from the `.env` you deployed with |
| Call says *"We could not reach your TwiML server"* | Make sure the app is on (`start.ps1`), `/` loads, and `--url` matches your Azure address |
| A deploy workflow fails with an authentication error | The publish profile is out of date. Re-run the deploy script with `-PublishProfilePath` and update the GitHub secret |
| An uploaded request stays in `incoming/` | Check the function's logs: **Function app → call_request → Invocations**. Re-run `deploy_function.ps1` to recreate the trigger |
| The call gets "Sorry, this call session has expired" | The app restarted mid-call (for example, after a deploy). Place a new call |

## Removing everything

This deletes the app, the plan, the function, the storage account, the Key Vault and the resource group permanently. The vault stays recoverable for 7 days, and its name can't be reused until then:

```powershell
az group delete --name clara-rg
```

## Security notes for this setup

- Your keys are stored in Azure Key Vault. The apps read them with their own identities and have read-only access. `.env` stays on your laptop and isn't uploaded.
- The live view uses a single shared password over HTTPS. That's fine for a demo. For real use, replace it with company sign-in (Microsoft Entra ID).
- The call-requests container is private. Anyone who can write to it can make Clara call the numbers in `ALLOWED_CALL_NUMBERS`, so keep that list short.
- Twilio requests are checked using the secret key in the webhook address and your Account SID. On a paid Twilio account, make signature checking mandatory as well.
