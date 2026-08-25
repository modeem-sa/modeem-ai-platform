# Server setup

## Content Manager model provider

The API Content Manager uses an OpenAI-compatible Chat Completions endpoint
server-side only. Browser clients must not receive or configure model keys.

In Replit-managed deployments, configure the platform-managed environment
variables `AI_INTEGRATIONS_OPENAI_BASE_URL` and
`AI_INTEGRATIONS_OPENAI_API_KEY`. These take precedence when present.

For a standard server, configure `OPENAI_API_KEY`. `OPENAI_BASE_URL` is
optional and defaults to `https://api.openai.com/v1`. Set it only for another
OpenAI-compatible endpoint. Optionally set `MODEEM_AI_MODEL`; it defaults to
`gpt-5.6-terra`, so a standard OpenAI server should set this to a model
available to that account.

Do not put any of these values in source control, frontend configuration, or
browser-exposed environment variables. If neither credential pair is set, the
document endpoint safely returns HTTP 503.