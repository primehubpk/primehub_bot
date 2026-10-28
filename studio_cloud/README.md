# PrimeHub Film Studio Cloud Preview
Source is isolated at studio_cloud/ on feature/film-studio-cloud-20261028 of primehubpk/primehub_bot. The default main branch and the deployed Salaar app have NOT been modified.

Important: This runs on Render free CPU only. It creates a film storyboard and renders short title-card MP4 ANIMATICS via FFmpeg; NOT original AI-generated footage. The studio's generative GPU model and permanent storage remain unconnected. This service is a technical beta; do not enter sensitive client details.

Endpoints:
- GET /healthz -- public liveness only
- GET / -- HTTP Basic protected studio UI
- GET /api/projects -- protected ephemeral projects
- POST /api/projects -- protected and same-origin
- PATCH /api/projects/<id> -- protected and same-origin
- POST /api/projects/<id>/render -- protected, same-origin and CPU FFmpeg
- GET /api/projects/<id>/video -- protected MP4

Render Docker setup: context studio_cloud, Dockerfile studio_cloud/Dockerfile. Required env STUDIO_PASSWORD must contain 20+ random characters; never put in repository. Only free plan; no GPUs, paid service, external LLM APIs or auto-publishing.
Data resides on /tmp ephemeral storage and may vanish at restart, redeploy or idle spin-down. Export project JSON. Free CPU cannot deliver a photorealistic Google Flow equivalent; connect a separately authorized GPU inference model and persistent object storage later.
