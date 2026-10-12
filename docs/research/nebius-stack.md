# Nebius + NVIDIA stack for the Nebius x NVIDIA Global AI Hackathon

Researched 12 Oct 2026. Deadline: **30 Oct 2026, 10:00 PT**. Judging runs 1–15 Dec 2026. **[V]** means verified in an official Nebius, NVIDIA, Tavily or Devpost page. **[U]** means unverified: from a third-party source, inferred, or not documented.

**Bottom line:** do all inference on Token Factory with the OpenAI SDK, routing by cost: Nemotron 3.5 Lightning, then Super, then Ultra. That is the split the Best Apps track asks for. A runtime call to Token Factory counts as "runs on Nebius" [V], so the app can be hosted anywhere.

## 1. Token Factory API
- **Base URL and auth:** `https://api.tokenfactory.nebius.com/v1/`, header `Authorization: Bearer $NEBIUS_API_KEY` [V]. Avoid regional hosts such as `api.tokenfactory.us-central1.nebius.com`, because public serverless is "Global" and region URLs can break [V].
- **Endpoints** [V]: `/v1/chat/completions`, `/completions`, `/embeddings`, `/rerank`, `/responses`, `/models`. `/v1/models?verbose=true` returns context length, price and TPM/RPM per model.
- **Chat parameters** [V]: `stream` (SSE, with `stream_options.include_usage`); `tools` with `tool_choice` (`none`, `auto`, `required` or a named function); `response_format` (`json_object` or `json_schema` with `strict`); `reasoning_effort` (`none` to `max`); `extra_body`. `max_tokens` defaults to 8192.
- **Fast flavor:** append `-fast` to an ID for the same outputs at a different price and latency [V]. No `nvidia/*-fast` ID seen [U].
- **JSON mode:** shown per model by a "JSON mode" tag on the model card; no full list [V].

## 2. NVIDIA model IDs on Token Factory
| Model ID | Params (total/active) | Context | $/1M in / out | Status |
|---|---|---|---|---|
| `nvidia/Nemotron-3_5-Lightning` | 30B / 3B | 1M | 0.06 / 0.24 [U] | Featured in the cookbook [V]. Released 11 Aug 2026. Official replacement for retired Nano/Llama models. |
| `nvidia/nemotron-3-super-120b-a12b` | 120B / 12B | 256K | 0.30 / 0.90 [U] | Featured [V] |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | 550B / 55B | 1M | 1.00 / 3.00 [U] | Featured [V] |
| Nemotron-3-Nano-30B-A3B (ID [U]) | 30B / 3B | 262K | 0.06 / 0.24 [U] | "Not currently featured". Avoid. |
| `nvidia/Nemotron-3-Nano-Omni`, `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` | – | – | – | **Deprecated 31 Aug 2026** [V] |

- **Tool calling:** native for Lightning and Super per the NVIDIA model cards. Lightning's thinking is on by default and switched off with `chat_template_kwargs: {"enable_thinking": false}` [V, model card]. Whether Token Factory honours that flag or `reasoning_effort` is **[U]**: smoke-test on day 1.
- **Not found on Token Factory:** NVIDIA embedding, reranker or Nano VL models [U].
- **Prices:** the official price page needs a login, so the figures come from aggregators that agree with each other (Mastra, Artificial Analysis, Eden AI).

## 3. Rate limits and credits
- **Rate limits** [V]: baseline **60 RPM / 400K TPM**. Limits rise ×1.2 per 15-minute window while usage is at 80% or more, up to 20× base, and fall when usage is at 50% or less. The Batch API has higher limits.
- **Trial:** $1 for new accounts, valid 30 days. A billing account with a **bank card is mandatory** [V].
- **Hackathon promo:** $25 via the Devpost form, activation code **`NEBIUS-DEVPOST-GLOBAL26`** [V].
- **Builder Program:** another $25 for Token Factory plus $25 for Tavily. **Expires 90 days after issue**; personal emails get extra review [V].

## 4. Serverless Endpoints and Jobs (Nebius AI Cloud)
- **What they are** [V]: Endpoints are long-running containers with a managed HTTPS URL. Jobs run to completion and have no URL.
- **Endpoint deploy** [V]: `nebius ai endpoint create --image <img> --platform cpu-d3 --preset 4vcpu-16gb --container-port 80 --auth token --token $AUTH_TOKEN --subnet-id …`. The URL is in `status.public_endpoints`. CPU-only works (the quickstart runs `nginx:alpine`), so a FastAPI + static UI container fits. Turning auth off for a public UI is **[U]**.
- **Job deploy** [V]: `nebius ai create --type job --image … --platform … --preset … --timeout 1h`, then `nebius ai job logs`.
- **Pricing** [V]: Compute rates, billed per second; stopped endpoints are free. Genoa costs $0.015 per CPU-hour plus $0.0045 per GiB-hour, so 4 vCPU / 16 GB is about **$0.13/h ($3.2/day)**. That `cpu-d3` is Genoa is [U]. No free tier; AI Cloud credits are clearly offered only at in-person events.
- **Recommendation:** host the app free (Cloudflare, HF Spaces or Render). Use an Endpoint only if you get AI Cloud credits, and stop it when idle.

## 5. Embeddings and rerank
- **`Qwen/Qwen3-Embedding-8B`** (recommended): $0.01 per 1M tokens, 4096 dims [U, aggregators]. Supports the `dimensions` parameter [V].
- **`BAAI/bge-en-icl`:** 1536 dims. It is the docs example [V] but reportedly retired [U].
- **Rerank:** `/v1/rerank` with `Qwen/Qwen3-Reranker-8B` [V], over the top 50 hits before Q&A.
- Embeddings needn't be NVIDIA models; the chat calls meet the requirement.

## 6. Tavily
Tavily is a web search, extract and crawl API for agents. Nebius agreed to acquire it in Feb 2026, and Tavily engineers are judges.
- **Free tier:** 1,000 credits/month, no card. Basic search costs 1 credit, advanced costs 2 [V].
- **Bonus prize:** "Best Use of Tavily" ($3,000) needs a **functional runtime call to the Tavily API** [V].
- **Python:** `TavilyClient(api_key=…).search(q, max_results=3, include_answer=True)` [V].

## 7. Hackathon resources (Devpost, fetched directly)
- **Resources page:** links to dev.nebius.com, the Builders Program, Discord, and the promo form above. **No starter kit**; the closest is `nebius/token-factory-cookbook/models/nemotron`.
- **Tracks:** Coding/Agentic, **Best Apps and Agents** (TeamLoop fits here), Personal AI, Physical AI.
- **Submit:** public repo with an OSI license and README, demo URL, YouTube video under 3 minutes, Token Factory feedback.
- **Judging:** implementation, design, impact, idea quality.

## 8. Model routing and cost (5 devs, 10 working days)
| Job | Model | Settings | Volume assumption | Cost |
|---|---|---|---|---|
| Per-event summaries | Lightning | reasoning off, `json_schema` | 60 events per dev per day = 3,000 events × (1.5K in, 0.12K out) | **$0.36** |
| Progress estimation | Super | reasoning low, `json_schema` (pct, confidence, blockers) | 8 runs per dev per day = 400 runs × (8K in, 1.5K out) | **$1.50** |
| Lead Q&A | Super + tools (`search_summaries`, `get_timeline`, Tavily) | embed, rerank, answer | 15 questions/day = 150 × (12K in, 2K out) | **$0.81** (+$0.5 if 20% escalate to Ultra) |
| Daily digest | Ultra | reasoning on | 6 digests/day (1 team + 5 devs) = 60 × (40K in, 4K out) | **$3.12** |
| Embeddings | Qwen3-Embedding-8B | – | about 0.5M tokens | under $0.01 |

**Runtime is about $6; with 3× for dev, evals and retries, about $20.** That fits in the $50 of hackathon credits. About 150 Tavily searches stay well inside the free 1,000.

**Fallbacks:** Lightning → Super on malformed JSON; Ultra → Super on 429s or slow responses; a cached last digest if Token Factory is down. Back off on 429, and use the Batch API for backfills over 60 events.

## 9. Minimal working snippet
Compiled and run against a mocked HTTP transport (openai 3.28) to check the request shape. **Not run against the live API**: no key was available.
```python
# pip install openai tavily-python   |   env: NEBIUS_API_KEY, TAVILY_API_KEY
import json, os
from openai import OpenAI
from tavily import TavilyClient

nb = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=os.environ["NEBIUS_API_KEY"])
FAST, MID, BIG = ("nvidia/Nemotron-3_5-Lightning", "nvidia/nemotron-3-super-120b-a12b",
                  "nvidia/Nemotron-3-Ultra-550b-a55b")
SCHEMA = {"name": "event_summary", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["summary", "files", "status"],
    "properties": {"summary": {"type": "string"},
                   "files": {"type": "array", "items": {"type": "string"}},
                   "status": {"type": "string", "enum": ["progress", "blocked", "done"]}}}}

def summarize_event(raw):
    r = nb.chat.completions.create(
        model=FAST, max_tokens=400, temperature=0.2,
        reasoning_effort="none",  # if reasoning still appears: extra_body={"chat_template_kwargs": {"enable_thinking": False}}
        response_format={"type": "json_schema", "json_schema": SCHEMA},
        messages=[{"role": "system", "content": "Summarize this dev-session event in 1-2 sentences."},
                  {"role": "user", "content": raw}])
    return json.loads(r.choices[0].message.content)

def embed(texts):
    return [d.embedding for d in nb.embeddings.create(model="Qwen/Qwen3-Embedding-8B", input=texts).data]

def web_context(q):
    res = TavilyClient(api_key=os.environ["TAVILY_API_KEY"]).search(q, max_results=3, include_answer=True)
    return res.get("answer") or "\n".join(x["content"] for x in res["results"])

if __name__ == "__main__":
    print(summarize_event("commit a1b2: fix JWT refresh race in auth/session.py; 42 tests pass"))
```

## 10. Risks
1. **The demo must stay up until 15 Dec**, when judging ends. Builder credits expire after 90 days, the trial after 30, and the promo's expiry is unknown. Claim credits now and keep about $10 in reserve.
2. **Model IDs change.** Three NVIDIA models were retired on 31 Aug with no rerouting. Pin IDs from `/v1/models?verbose=true` on day 1 and keep them in config.
3. **Reasoning tokens** inflate cost and can leak into the JSON. Run a 5-call reasoning-off smoke test first.
4. **Session content goes to a "Global"-region public endpoint.** Say so in the README so teams can opt in.

## Sources
- Devpost overview, rules and resources: https://nebiusglobalaihackathon.devpost.com/ , /rules , /resources
- Token Factory docs:
  - Quickstart: https://docs.tokenfactory.nebius.com/quickstart.md
  - Model flavors: https://docs.tokenfactory.nebius.com/ai-models-inference/overview.md
  - Function calling: https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling.md
  - JSON output: https://docs.tokenfactory.nebius.com/ai-models-inference/json.md
  - Rate limits: https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits.md
  - Chat API spec: https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion.md
  - Embeddings: https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings.md
  - Rerank: https://docs.tokenfactory.nebius.com/api-reference/inference/rerank-documents.md
  - Models list: https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models.md
  - Billing: https://docs.tokenfactory.nebius.com/other-capabilities/billing-new.md
  - Public serverless: https://docs.tokenfactory.nebius.com/public-serverless.md
  - Aug 2026 deprecations: https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice.md
- Nemotron cookbook: https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md
- Nebius Nemotron page: https://nebius.com/services/token-factory/nemotron
- Nemotron 3 Super on Token Factory: https://nebius.com/blog/posts/nemotron3-super-now-available
- Lightning model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16
- Nebius Serverless AI docs:
  - Overview: https://docs.nebius.com/serverless/overview.md
  - Endpoints quickstart: https://docs.nebius.com/serverless/quickstart/endpoints.md
  - Jobs quickstart: https://docs.nebius.com/serverless/quickstart/jobs.md
  - Pricing and quotas: https://docs.nebius.com/serverless/pricing-quotas.md
  - Compute pricing: https://docs.nebius.com/compute/resources/pricing.md
- Builder Program terms: https://nebius.com/builders-terms-and-conditions
- Tavily docs:
  - API credits: https://docs.tavily.com/documentation/api-credits.md
  - Python SDK reference: https://docs.tavily.com/sdk/python/reference.md
- Tavily acquisition: https://nebius.com/newsroom/nebius-announces-agreement-to-acquire-tavily-to-add-agentic-search-to-its-ai-cloud-platform
- [U] pricing aggregators:
  - https://mastra.ai/models/providers/nebius
  - https://artificialanalysis.ai/models/nvidia-nemotron-3-super-120b-a12b/providers
  - https://www.edenai.co/models/nemotron-3-5-lightning
