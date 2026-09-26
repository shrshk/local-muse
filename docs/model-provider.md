# Model provider

## Interface

```python
class ModelProvider(Protocol):
    async def complete(self, req: CompletionRequest) -> CompletionResponse: ...
    def stream(self, req: CompletionRequest) -> AsyncIterator[Delta]: ...
    async def health(self) -> ProviderHealth: ...
```

| Provider | v1 |
|---|---|
| `OllamaProvider` | implemented (Phase 2) |
| `OpenAICompatibleProvider` | implemented if cheap (Ollama speaks the same API) |
| `AnthropicProvider` | interface only |
| `MLXProvider` | interface only (`mlx_lm.server`, benchmark later) |

Ollama runs llama.cpp with Metal on GGUF weights. It is **not** MLX.

## Configuration

```text
LOCAL_MUSE_MODE=offline            offline | hybrid | cloud (v1: offline)
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://host.docker.internal:11434
MODEL_NAME=qwen3.8:27b
MODEL_CONTEXT_TOKENS=32768
```

`hybrid` must be a config change: a router picks a provider per workload; call sites do not
change.

## Health

Phase 1 probe: `GET {MODEL_BASE_URL}/api/tags`.

| Result | Status |
|---|---|
| unreachable | offline |
| reachable, `MODEL_NAME` not pulled | degraded (detail says `ollama pull <name>`) |
| reachable, model present | online |

## Model choice

The spec assumed `qwen3:30b-a3b` (MoE, ~3B active per token). This Mac runs `qwen3.8:27b`
(dense, 27.3B, Q4_K_M; capabilities: completion, tools, thinking, vision; native context 256k).
Dense means every token touches all 27B weights, so expect several times lower tokens/s than an
A3B MoE on the same machine. Keep `MODEL_CONTEXT_TOKENS=32768` until the KV cost is measured.
Switching models is a `MODEL_NAME` change.

## Expectations

A 30B-class local model is unreliable at long multi-step tool loops. The loop tolerates
malformed output: one repair attempt with the validation error, then fail the step and let the
workflow decide. `call_model` runs on the `model-inference` queue at concurrency 1 with a
10-minute start-to-close timeout and 10 s heartbeats.

## Memory budget

64 GB unified memory:

```text
model weights + KV cache   ~17 GB + KV (qwen3.8:27b Q4_K_M; measure in Phase 2)
macOS + apps                ~8 GB
Docker Desktop VM           16 GB cap  (per-service limits in architecture.md)
```

If the model swaps, nothing else matters. Keep `MODEL_CONTEXT_TOKENS` at 32k unless measured.

## Host setup

```bash
brew install ollama
ollama serve              # or the Ollama.app
ollama pull qwen3.8:27b
```

Containers reach it at `host.docker.internal:11434`. Ollama binds `127.0.0.1` by default, which
Docker Desktop can still reach through `host.docker.internal`.
