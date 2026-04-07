# Strava Setup Guide

This guide explains how to obtain and configure the Strava values used by this project:

- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_WEBHOOK_VERIFY_TOKEN`
- `STRAVA_WEBHOOK_CALLBACK_URL`
- `STRAVA_REDIRECT_URI`

The steps below are based on Strava's official developer documentation and app settings pages.

Official references:

- [Getting Started](https://developers.strava.com/docs/getting-started/)
- [Authentication](https://developers.strava.com/docs/authentication)
- [Webhooks](https://developers.strava.com/docs/webhooks/)

## 1. Create a Strava developer application

1. Sign in to your Strava account.
2. Open the Strava API settings page:

   [https://www.strava.com/settings/api](https://www.strava.com/settings/api)

3. Create a new API application if you do not already have one.
4. Fill in the basic app metadata:
   - application name
   - category
   - website
   - authorization callback domain

### Important note about the app name

Strava's brand guidelines say you should not make your app look like an official Strava product. Use a neutral project/app name rather than something that suggests Strava owns it.

## 2. Get the Strava Client ID and Client Secret

After your app exists, stay on the Strava API settings page:

[https://www.strava.com/settings/api](https://www.strava.com/settings/api)

You will see:

- `Client ID`
- `Client Secret`

Copy them into your local `.env` file as:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
```

### What these values are

- `STRAVA_CLIENT_ID`: the public identifier of your Strava app
- `STRAVA_CLIENT_SECRET`: the secret used by your backend to exchange OAuth codes and refresh tokens

Keep the client secret private. It should never be committed to Git.

## 3. Choose the Strava Redirect URI

This is the OAuth callback used when you connect your Strava account to the app.

In local development, the callback path is:

```text
/auth/strava/callback
```

So your full redirect URI should look like one of these:

- local:
  - `http://127.0.0.1:8000/auth/strava/callback`
- Vercel:
  - `https://your-project.vercel.app/api/auth/strava/callback`
- public server:
  - `https://your-domain.com/auth/strava/callback`
- tunnel:
  - `https://your-ngrok-subdomain.ngrok.app/auth/strava/callback`

Set it in `.env`:

```env
STRAVA_REDIRECT_URI=http://127.0.0.1:8000/auth/strava/callback
```

### Matching the Strava app setting

In the Strava app page, the `Authorization Callback Domain` must match the domain used by `STRAVA_REDIRECT_URI`.

Examples:

- if `STRAVA_REDIRECT_URI=http://127.0.0.1:8000/auth/strava/callback`
  then the callback domain should be `127.0.0.1`
- if `STRAVA_REDIRECT_URI=https://my-sync.example.com/auth/strava/callback`
  then the callback domain should be `my-sync.example.com`

## 4. Create the webhook verify token

`STRAVA_WEBHOOK_VERIFY_TOKEN` is not given by Strava.

You create it yourself.

It is a shared secret string that:

- you send to Strava when creating the webhook subscription
- Strava sends back to your verification endpoint
- your app checks to confirm the request is really for your subscription

Choose a long random string, for example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then place it in `.env`:

```env
STRAVA_WEBHOOK_VERIFY_TOKEN=your_random_verify_token
```

## 5. Decide the webhook callback URL

`STRAVA_WEBHOOK_CALLBACK_URL` is the public URL that Strava will call for webhook verification and activity events.

In local development, the webhook endpoint path is:

```text
/webhooks/strava
```

So the callback URL should look like:

- local with tunnel:
  - `https://your-ngrok-subdomain.ngrok.app/webhooks/strava`
- Vercel:
  - `https://your-project.vercel.app/api/webhooks/strava`
- public server:
  - `https://your-domain.com/webhooks/strava`

Set it in `.env`:

```env
STRAVA_WEBHOOK_CALLBACK_URL=https://your-public-domain/webhooks/strava
```

## 6. Important constraint: webhook URLs must be publicly reachable

Strava must be able to reach your webhook callback URL over the public internet.

This means:

- `http://127.0.0.1:8000/webhooks/strava` will not work directly for Strava
- `http://localhost:8000/webhooks/strava` will not work directly for Strava
- you need either:
  - a real public domain, or
  - a tunnel such as ngrok or Cloudflare Tunnel

If you are only running locally with no public URL, this project can still work using manual backfill and the local scheduler, but Strava webhooks will not be deliverable.

## 7. Recommended setup for local development

If you want webhook support during local development:

1. Start the app locally:

   ```bash
   uv run strava-sync serve
   ```

2. Expose it with a tunnel tool.

For example with ngrok:

```bash
ngrok http 8000
```

Then use the public HTTPS forwarding URL from ngrok.

Example:

- app base URL:
  - `https://abc123.ngrok.app`
- redirect URI:
  - `https://abc123.ngrok.app/auth/strava/callback`
- webhook callback URL:
  - `https://abc123.ngrok.app/webhooks/strava`

## 7b. Recommended setup for Vercel

For a Vercel deployment, use:

- app base URL:
  - `https://your-project.vercel.app/api`
- redirect URI:
  - `https://your-project.vercel.app/api/auth/strava/callback`
- webhook callback URL:
  - `https://your-project.vercel.app/api/webhooks/strava`

## 8. Create the webhook subscription in Strava

After your app is running and your callback URL is reachable, create the webhook subscription with Strava.

Strava says webhook subscriptions are created by calling:

```text
POST https://www.strava.com/api/v3/push_subscriptions
```

Use form data with:

- `client_id`
- `client_secret`
- `callback_url`
- `verify_token`

Example:

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id="$STRAVA_CLIENT_ID" \
  -F client_secret="$STRAVA_CLIENT_SECRET" \
  -F callback_url="$STRAVA_WEBHOOK_CALLBACK_URL" \
  -F verify_token="$STRAVA_WEBHOOK_VERIFY_TOKEN"
```

### What happens next

Strava will immediately send a verification `GET` request to your callback URL.

This app handles that at:

```text
GET /webhooks/strava
```

Your service must respond quickly and echo the `hub.challenge` value in the JSON body. This project already implements that.

## 9. Example `.env` block

For local development with a tunnel:

```env
APP_BASE_URL=https://abc123.ngrok.app

STRAVA_CLIENT_ID=123456
STRAVA_CLIENT_SECRET=your_client_secret_here
STRAVA_WEBHOOK_VERIFY_TOKEN=your_random_verify_token_here
STRAVA_WEBHOOK_CALLBACK_URL=https://abc123.ngrok.app/webhooks/strava
STRAVA_REDIRECT_URI=https://abc123.ngrok.app/auth/strava/callback
STRAVA_SCOPES=read,activity:read_all,profile:read_all
```

For local development without webhook delivery:

```env
APP_BASE_URL=http://127.0.0.1:8000

STRAVA_CLIENT_ID=123456
STRAVA_CLIENT_SECRET=your_client_secret_here
STRAVA_WEBHOOK_VERIFY_TOKEN=local_only_verify_token
STRAVA_WEBHOOK_CALLBACK_URL=
STRAVA_REDIRECT_URI=http://127.0.0.1:8000/auth/strava/callback
STRAVA_SCOPES=read,activity:read_all,profile:read_all
```

In that second case, OAuth can still work locally if your Strava callback domain matches your local redirect setup, but webhook delivery itself will not work unless Strava can reach the URL publicly.

## 10. How to test your setup

### Test the local app

Start the app:

```bash
uv run strava-sync serve
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### Test webhook verification manually

If your app is running, you can simulate Strava's verification request:

```bash
curl "http://127.0.0.1:8000/webhooks/strava?hub.verify_token=test-token&hub.challenge=abc123&hub.mode=subscribe"
```

Expected response shape:

```json
{"hub.challenge":"abc123"}
```

To test with your real configured token:

```bash
curl "http://127.0.0.1:8000/webhooks/strava?hub.verify_token=$STRAVA_WEBHOOK_VERIFY_TOKEN&hub.challenge=abc123&hub.mode=subscribe"
```

## 11. Where each value comes from

Quick summary:

- `STRAVA_CLIENT_ID`
  - comes from your Strava app page
- `STRAVA_CLIENT_SECRET`
  - comes from your Strava app page
- `STRAVA_WEBHOOK_VERIFY_TOKEN`
  - you generate this yourself
- `STRAVA_WEBHOOK_CALLBACK_URL`
  - you choose this based on the public URL where your app is reachable
- `STRAVA_REDIRECT_URI`
  - you choose this based on the URL where your app handles OAuth callback
