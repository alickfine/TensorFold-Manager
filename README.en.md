# TensorFold Manager

[简体中文](README.md) | **English**

A standalone macOS App with an embedded Web workspace for [TensorFold](https://github.com/ashhart/TensorFold). The management layer is independent of the upstream inference engine, with selected management features inspired by oMLX.

**Apple Silicon alpha release.** Download the DMG and checksums from [GitHub Releases](https://github.com/alickfine/TensorFold-Manager/releases). Builds use ad hoc signing and are **not notarized by Apple**. See the [acceptance record](docs/acceptance.en.md) for verified behavior and limitations.

## Install and get started

1. Download `TensorFold-Manager-<version>-macOS-arm64.dmg`, open it and drag the App into Applications.
2. Open the App. Under **Versions & Updates**, install the main engine. This requires internet access; each engine version uses a separate environment pinned to an official commit.
3. Set existing model directories under **Server & Directories**, or download a supported checkpoint under **Model Downloader**. Third-party mirrors never receive provider credentials.
4. Scan the **Model Library**. Local variants that are not already recognized must pass the engine's CLI compatibility check.
5. Start a model from **Overview**. Memory pressure, insufficient capacity or a conflicting inference service can block startup with a reason. Compatible services can be reused; stopping an external service requires confirmation.
6. Use **Chat**, statistics, cache inspection, logs, benchmarks and reference-answer tests. Quitting the App stops the engine it owns.

Choose **简体中文 / English** in the workspace header. The App remembers the language. Language switching preserves model identifiers, paths, logs and user conversations in their original form.

## Management workspace

The App has 17 sections. Unsupported engine capabilities show a reason; missing metrics are reported as unavailable rather than fabricated.

| Section | Features |
| --- | --- |
| Overview | Start, stop and switch models; inspect active processes, memory, service endpoints and versions |
| Statistics & Usage | Aggregate and per-model requests, tokens, latency, failures, cancellations and exports |
| Cache | Inspect reported MLX/prompt cache metrics and perform supported cleanup operations |
| Model Library | Scan local directories, check compatibility, load models and select defaults |
| Model Downloader | Hugging Face, third-party mirror and ModelScope download jobs with revision and file verification |
| Model Configuration | Sampling, context, thinking, MTP/drafter settings and saved profiles |
| Quantization & Upload | Engine format preflight, separate converted outputs, preserved source weights and reviewed HF upload scope |
| Engine Configuration | Generation defaults, concurrency, memory/cache budgets and supported advanced options |
| Server & Directories | Host and process information, engine/gateway ports and model/data directories |
| API & Integrations | OpenAI-compatible gateway endpoints and client examples; explicit integration limitations |
| Authentication & Keys | Gateway API keys and separate download/upload provider credentials |
| Versions & Updates | App/engine versions, GitHub checks, isolated installation, activation and rollback |
| Logs | Filter, search and export runtime logs |
| Benchmark | Real inference throughput and latency measurements |
| Reference-answer Tests | Compare actual responses with supplied reference answers; not a general accuracy score |
| Chat | Multi-turn generation, sampling options, system prompt, cancellation and export |
| Capability Map | Distinguish upstream support, manager additions and unavailable oMLX-specific features |

Quantization requires the separate model-tools environment. Target formats are checked against the installed engine; converted weights go into a managed output directory. Source model weights remain read-only.

## Follow upstream safely

Architecture: **Swift AppKit / WKWebView → management layer / API gateway → version adapters → original TensorFold**.

- App and engine versions are independent. Upstream core code is not modified.
- Updates are checked automatically and installed manually. Candidate environments are pinned, checked for compatibility and tested before activation; failures restore the previous version.
- The management interface stays available while inference is stopped.
- Before loading large models, the manager checks system memory pressure, capacity budgets and existing inference services. A model switch stops the old process and verifies exit before loading the next one.
- Manager settings, statistics, logs and chat history are stored in the App's own data directory. The native bridge supplies the management token; it is never stored in the URL or browser storage.

## Model sources and compatibility

Model architecture, revision, quantization format, shards, tokenizer/template and MTP files must match the engine. `hf-mirror.com` is a third-party mirror. ModelScope repositories are downloaded through its official API and verified as file-tree snapshots; similar repository names do not prove equivalence to official HF checkpoints.

TensorFold currently rejects image, audio and video input. VLM, embeddings, reranking and diffusion are not advertised as supported endpoints. oMLX ANE, TurboQuant, GDN, SSD block caches and oQ kernels are not automatically portable. CUDA/EXL3 checkpoints are not treated as Apple Silicon models.

## Development

Use Python 3.12 and Node.js:

```sh
python3.12 -B -m unittest discover -s tests
node --test tests/*.test.mjs
swiftc macos/Bootstrap.swift macos/CredentialRequest.swift macos/tests/main.swift -o /tmp/tfm-native-tests
/tmp/tfm-native-tests
```

`scripts/build-app.py` packages the App with standalone Python 3.12.9 and uv 0.9.5. Tagged GitHub workflows test, build and publish the DMG and `SHA256SUMS.txt`. Ad hoc test signing is not a Developer ID distribution signature.

The historical [prototype](prototype/index.html) contains simulated metrics, downloads and chat. It is a design reference, not runtime evidence. The implemented App's acceptance evidence is maintained separately.
