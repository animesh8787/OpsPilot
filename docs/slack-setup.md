# Slack app setup (about 3 minutes)

OpsPilot uses **Socket Mode**, so Slack connects to it over a websocket: no public URL or ngrok.

## 1. Create the app from the manifest

1. Go to <https://api.slack.com/apps> -> **Create New App** -> **From an app manifest**.
2. Pick your workspace, choose **YAML**, paste the manifest below, **Create**.

```yaml
display_information:
  name: OpsPilot
  description: AI incident triage
features:
  bot_user:
    display_name: OpsPilot
    always_online: true
  slash_commands:
    - command: /opsstatus
      description: Current health of each service
      should_escape: false
    - command: /incident
      description: List open incidents or summarize one
      usage_hint: list | summary <id>
      should_escape: false
    - command: /ask
      description: Ask OpsPilot about your services
      usage_hint: why is checkout slow?
      should_escape: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - chat:write.public
      - commands
settings:
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

Scopes: `chat:write` (post and update incident messages), `chat:write.public` (post to `#incidents`
without being invited), `commands` (slash commands). Interactivity is required for the buttons.

> `/status` is a built-in Slack command that apps cannot override, so OpsPilot's version is `/opsstatus`.

## 2. Get the two tokens

- **Bot token** (`xoxb-...`): *Install App* -> **Install to Workspace** -> copy *Bot User OAuth Token*.
- **App-level token** (`xapp-...`): *Basic Information* -> *App-Level Tokens* -> **Generate Token**
  with scope `connections:write`.

## 3. Configure and run

```bash
cp .env.example .env
# set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL=#incidents (and LLM_PROVIDER / ANTHROPIC_API_KEY)
docker compose up -d --build
docker compose logs opspilot | grep "socket mode"   # expect: slack socket mode connected
```

Create the `#incidents` channel first. `.env` is git-ignored; never commit tokens.

## Troubleshooting

- *No message appears*: the channel name must match `SLACK_CHANNEL`, and the logs should show
  `incident posted`. In dry-run mode (tokens unset) messages are only logged.
- *`dispatch_failed` on a slash command*: Socket Mode not connected; check both tokens.
- *Buttons do nothing*: interactivity must be enabled (it is in the manifest).
