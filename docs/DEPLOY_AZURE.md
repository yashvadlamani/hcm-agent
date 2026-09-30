# Deploying Clara to Azure

This guide puts the Clara phone server on **Azure App Service**, so it runs in the cloud instead of on your laptop. You get a permanent public address like `https://clara-yourname.azurewebsites.net`, so **ngrok is no longer needed**, and anyone with the password can open the live call view.

> ⚠️ **Test data only.** An Azure free trial is not covered by a Business Associate Agreement (BAA), so it is not HIPAA-compliant. Don't use it with real patients. See [Before production](./GETTING_STARTED.md#8-before-production).

**What gets created** (all in one resource group, `clara-rg`):

| Resource | Purpose |
|---|---|
| App Service plan `<app>-plan` (Linux, **Free F1** by default) | The server the app runs on |
| Web app `<app>` (Python 3.12) | The Clara server, with HTTPS at `https://<app>.azurewebsites.net` |

### Which tier?

| Tier | Cost | Behavior |
|---|---|---|
| **Free (F1)**, the default | $0 | Works on a new free-trial subscription. The app **sleeps after about 20 idle minutes** and takes up to a minute to wake. `place_call` wakes it before dialing, so calls still work. Calls and the live view's history are cleared when it sleeps. There's also a daily CPU-time cap, which is plenty for demo calls. |
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
2. copies the settings Clara needs from your `.env` into Azure (the values are never printed)
3. sets the startup command, Always On and HTTPS-only
4. uploads the code

Expect 5–10 minutes the first time. Re-run the same command whenever you change code or `.env` settings.

Optional arguments: `-Sku B1` (default `F1`), `-Location westus2` (default `eastus`) and `-ResourceGroup <name>` (default `clara-rg`). If you change `-Location`, also use a new `-ResourceGroup` name, because a resource group can't move regions.

## 5. Check it's running

1. Open `https://<app>.azurewebsites.net`. You should see **"Clara phone server is running."** The first load after a deploy can take a minute.
2. Open `https://<app>.azurewebsites.net/live` and sign in. The username can be anything; the password is your `LIVE_VIEW_PASSWORD`.

## 6. Place a test call

No ngrok needed. Point the call at your Azure address:

```powershell
python -m hcm_agent.place_call --url https://<app>.azurewebsites.net --to +1XXXXXXXXXX --name <FirstName>
```

On the Free tier, if the app has been idle you'll see *"Waking the server…"* for up to a minute before the phone rings. That's expected.

Keep `/live` open to watch the call as it happens. The Twilio trial-account limits in the [Getting Started guide](./GETTING_STARTED.md#twilio-trial-account-limits) still apply.

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
   python -m hcm_agent.chat_demo interactive
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
| `place_call` says the server didn't respond | The app is stopped (run `start.ps1`) or failed to start (check the logs) |
| `az` is not recognized | Reopen PowerShell after installing the Azure CLI |
| Running the script is blocked by execution policy | Use the `powershell -ExecutionPolicy Bypass -File …` form shown above |
| `/` shows an Azure "Application Error" page | Check the logs (above). Usually a missing setting: re-run the deploy script after fixing `.env` |
| `/live` keeps asking for a password | Use the exact `LIVE_VIEW_PASSWORD` from the `.env` you deployed with |
| Call says *"We could not reach your TwiML server"* | Make sure the app is on (`start.ps1`), `/` loads, and `--url` matches your Azure address |
| The call gets "Sorry, this call session has expired" | The app restarted mid-call (for example, after a deploy). Place a new call |

## Removing everything

This deletes the app, the plan and the resource group permanently:

```powershell
az group delete --name clara-rg
```

## Security notes for this setup

- Your keys are stored as App Service settings, encrypted by Azure. `.env` stays on your laptop and isn't uploaded.
- The live view uses a single shared password over HTTPS. That's fine for a demo. For real use, replace it with company sign-in (Microsoft Entra ID).
- Twilio requests are checked using the secret key in the webhook address and your Account SID. On a paid Twilio account, make signature checking mandatory as well.
