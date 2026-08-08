# Deploying grscraper

One image, three shapes:

| Shape | Command | Use it for |
|---|---|---|
| **Job / cron** | `grscraper sync` (default `CMD`) | Scheduled scrapes. The right default. |
| **HTTP service** | `grscraper serve` | Platforms that health-check a port, or on-demand triggering. |
| **Lambda** | `Dockerfile.lambda` | Event-driven, small batches only — see the caveats below. |

```bash
docker build -t grscraper .
docker run --rm -v grscraper-data:/data \
  -e GRS_TARGETS="acme coffee roasters" \
  -e GRS_SINKS="-" \
  grscraper sync
```

## Which image for which platform

There are exactly **two** Dockerfiles, and that is the complete set:

| Dockerfile | Image tag | Covers |
|---|---|---|
| `Dockerfile` | `:latest`, `:0.2.1` | Cloud Run **jobs** and **services**, Google Cloud Functions gen2, Kubernetes / CronJob, ECS + Fargate, Azure Container Apps & Container Instances, Fly.io, Render, Railway, Nomad, plain `docker run`, Compose |
| `Dockerfile.lambda` | `:lambda`, `:lambda-0.2.1` | AWS Lambda only |

Everything except Lambda consumes a standard OCI image, so one image serves them
all — the `sync` / `serve` argument picks the shape. Lambda is the sole exception
because it requires the Runtime Interface Client as the entrypoint rather than
your own process.

Both images are multi-arch on GHCR (`linux/amd64` + `linux/arm64`, with build
provenance attestations); the Lambda image is `amd64`, matching the default
function architecture.

## Published images

```
ghcr.io/piyush-gambhir/grscraper:latest
ghcr.io/piyush-gambhir/grscraper:0.2.1
ghcr.io/piyush-gambhir/grscraper:lambda-0.2.1
```

Also mirrored to Docker Hub when the publishing repo has `DOCKERHUB_USERNAME`
(variable) and `DOCKERHUB_TOKEN` (secret) configured:

```
docker.io/<dockerhub-user>/grscraper:latest
docker.io/<dockerhub-user>/grscraper:lambda
```

## Read this before you pick a platform

**Datacenter IPs get CAPTCHA'd far more than residential ones.** This is the
single biggest operational factor, and it is not a bug you can patch. A run
from a laptop may sail through where the same run from a cloud VM is blocked
within minutes. Concretely: scraping Google from GCP is the worst case, and
it's exactly what a naive Cloud Run deployment does.

If you hit blocks in the cloud, in escalating order of effort:

1. Raise the throttles hard — `GRS_THROTTLE_BUSINESS_MIN_MS=30000`,
   `GRS_THROTTLE_BUSINESS_MAX_MS=90000`. Slow is cheaper than blocked.
2. Give the job a stable egress IP (Cloud NAT, NAT Gateway) so a solved CAPTCHA
   has something to stick to, and persist `/data` so the browser profile
   survives.
3. Route through a residential proxy.
4. If you *own* the listing, stop scraping and use the Google Business Profile
   API instead — official, unblockable, and it carries real review timestamps
   rather than "2 months ago".

**Persist `/data` or lose your memory.** It holds the SQLite queue (dedupe and
resume state) and the Chromium profile (cookies, and any CAPTCHA you solved by
hand). Without it, every run starts from zero.

## State and volumes

| Path | Contents | If you don't persist it |
|---|---|---|
| `/data/scraper.db` | Queue, businesses, reviews | Re-scrapes everything; `reviews_added` is misleading |
| `/data/browser_profile/` | Cookies, CAPTCHA solves | Looks like a brand-new visitor every run |
| `/data/exports/` | Files from `export` | Nothing — `sync` doesn't use it |

## Configuration

Targets and delivery are the only things most deployments set.

| Variable | Default | Meaning |
|---|---|---|
| `GRS_TARGETS` | — | Newline/semicolon-separated targets; `value` or `value\|type` |
| `GRS_SINKS` | `-` | Comma-separated delivery URIs |
| `GRS_SINK_HTTP_TOKEN` | — | Bearer token for `http(s)` sinks |
| `GRS_SINK_HTTP_HEADERS` | — | Extra headers, JSON object |
| `GRS_SINK_HTTP_TIMEOUT_S` | `60` | Per-sink HTTP timeout |
| `GRS_SERVER_TOKEN` | — | If set, `POST /scrape` requires this bearer token |
| `GRS_DATA_DIR` | `/data` | Root for db, profile, exports |
| `PORT` | `8080` | `serve` bind port |

Throttles, retries and user agent are unchanged from the [README](../README.md).

### Sinks

| URI | Notes |
|---|---|
| `-` | stdout — pairs well with cloud log collection |
| `/path/out.json`, `file:///path/out.json` | local/volume file |
| `https://host/ingest` | POST, JSON body, optional bearer |
| `s3://bucket/key.json` | needs the `[s3]` extra |
| `gs://bucket/object.json` | needs the `[gcs]` extra |

Every sink is attempted even if an earlier one fails, so a dead webhook never
costs you the local copy. Any failure sets exit code 3.

### Exit codes

| Code | Meaning | Scheduler should |
|---|---|---|
| 0 | Clean | — |
| 1 | Unhandled error | Alert |
| 2 | CAPTCHA — run halted early | **Alert, do not auto-retry.** Retrying while blocked deepens the block. Back off for hours. |
| 3 | Scrape fine, a sink failed | Retry delivery, not the scrape |

## Cloud Run job (recommended for scheduled work)

A job, not a service: no port, no idle cost, and the scheduler owns retries.

```bash
PROJECT=your-project REGION=asia-south1 REPO=containers

gcloud artifacts repositories create $REPO \
  --repository-format=docker --location=$REGION 2>/dev/null

IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/grscraper:0.2.1
docker build -t $IMAGE . && docker push $IMAGE
```

`/data` needs to survive between executions, so back it with a bucket:

```bash
gcloud storage buckets create gs://$PROJECT-grscraper-state --location=$REGION

gcloud run jobs create grscraper-sync \
  --image=$IMAGE \
  --region=$REGION \
  --args=sync \
  --task-timeout=3600 \
  --max-retries=0 \
  --memory=2Gi --cpu=2 \
  --set-env-vars=GRS_TARGETS="acme coffee roasters",GRS_SINKS="gs://$PROJECT-grscraper-out/reviews.json" \
  --add-volume=name=state,type=cloud-storage,bucket=$PROJECT-grscraper-state \
  --add-volume-mount=volume=state,mount-path=/data
```

`--max-retries=0` is deliberate: exit code 2 means Google blocked you, and an
immediate retry makes that worse. Let the weekly schedule be the retry.

2Gi is not padding — Chromium with a long review list will OOM at 512Mi.

Weekly trigger:

```bash
gcloud scheduler jobs create http grscraper-weekly \
  --location=$REGION \
  --schedule="0 3 * * 1" \
  --time-zone="Asia/Kolkata" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/grscraper-sync:run" \
  --http-method=POST \
  --oauth-service-account-email=SCHEDULER_SA@$PROJECT.iam.gserviceaccount.com
```

Run it once by hand first — `gcloud run jobs execute grscraper-sync --region=$REGION --wait`.

## Cloud Run service

Only if you need on-demand triggering. Scraping is slow, so the request
timeout has to be raised and concurrency pinned to 1 (one SQLite file, one
browser profile — parallel scrapes corrupt both; the server also refuses
overlapping requests with a 409).

```bash
gcloud run deploy grscraper \
  --image=$IMAGE --region=$REGION \
  --args=serve \
  --timeout=3600 --concurrency=1 --min-instances=0 \
  --memory=2Gi --cpu=2 \
  --no-allow-unauthenticated \
  --set-env-vars=GRS_SERVER_TOKEN=... 
```

| Route | |
|---|---|
| `GET /healthz` | liveness; also reports `busy` |
| `POST /scrape` | body: `{"targets": [...], "sinks": [...], "limit": N, "inline_result": false}` |

## AWS Lambda

Workable, with two constraints that rule it out for large jobs:

- **15-minute hard ceiling.** Default throttle is 5–15s per business plus
  scroll time. A handful per invocation is realistic; a long queue is not.
  Pass `limit` and invoke repeatedly.
- **Ephemeral `/tmp`.** The queue and browser profile reset every invocation,
  which costs cross-run dedupe and CAPTCHA persistence. Mount EFS and point
  `GRS_DATA_DIR` at it to get them back.

```bash
docker build -f Dockerfile.lambda -t grscraper-lambda .
# push to ECR, then create the function from the image with:
#   memory 2048+, timeout 900, ephemeral storage 2048
```

```json
{ "targets": ["acme coffee roasters"], "sinks": ["s3://bucket/reviews.json"], "limit": 3 }
```

## Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: grscraper
spec:
  schedule: "0 3 * * 1"
  concurrencyPolicy: Forbid          # one scrape at a time; see above
  jobTemplate:
    spec:
      backoffLimit: 0                # exit 2 must not auto-retry
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: grscraper
              image: ghcr.io/piyush-gambhir/grscraper:0.2.1
              args: ["sync"]
              env:
                - name: GRS_TARGETS
                  value: "acme coffee roasters"
                - name: GRS_SINKS
                  value: "https://example.com/ingest"
                - name: GRS_SINK_HTTP_TOKEN
                  valueFrom:
                    secretKeyRef: { name: grscraper, key: token }
              resources:
                requests: { memory: 1Gi, cpu: "1" }
                limits:   { memory: 2Gi, cpu: "2" }
              volumeMounts:
                - { name: state, mountPath: /data }
          volumes:
            - name: state
              persistentVolumeClaim: { claimName: grscraper-state }
```

## Output

Every sink receives the same document, pinned by
[`schemas/scrape-result.v1.json`](../schemas/scrape-result.v1.json) and
described in [SCHEMA.md](SCHEMA.md).
