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
6. Use **Chat**, statistics, cache inspection, logs, simplified benchmarks. Quitting the App stops the engine it owns.

Choose **简体中文 / English** in the workspace header. The App remembers the language. Language switching preserves model identifiers, paths, logs and user conversations in their original form.

## Management workspace

The App has 12 sections. Model configuration opens in the library dialog. API ports, integrations and authentication share one page. Startup candidates must pass the current engine's MLX compatibility detection; detection is not proof of a successful weight load. Statistics use at most two decimals; cache telemetry shows its actual source and sample time.

| Section | Features |
| --- | --- |
| Overview | Start and stop; currently detected compatible local models; memory admission |
| Statistics & Usage | Aggregate and per-model usage, latency and exports |
| Cache | Live reported MLX memory, source/time, owned snapshots and safe cleanup |
| Model Library | Scan, compatibility checks, load/default actions and configuration dialog |
| Model Downloader | Supported catalog models; Hugging Face or third-party mirror; job controls |
| Engine Configuration | Concurrency, memory/cache and snapshots; model generation settings live in the dialog |
| Server & Directories | Host information, directory settings, local-disk discovery and registration |
| API & Integrations | Endpoints, ports, client examples, authentication and keys |
| Versions & Updates | Checks, candidate installation, manual upgrade, API verification and recovery |
| Logs | Compact filters, search and redacted export |
| Benchmark | Simple presets, measured throughput/latency, cancellation and results |
| Chat | Message list, bottom composer, collapsed settings, streaming, stop and export |

Discovery excludes network volumes, application packages and private application directories. Permission failures and scan limits are explicitly reported as partial results. The downloader does not offer unverified ModelScope mappings.

The primary engine upgrade action installs a candidate, checks compatibility before stopping, switches and verifies a real API request. External services block upgrades. Failure restores the previous model and its actual running parameters while preserving pending edits. Advanced candidate installation, activation and rollback remain available.

## Follow upstream safely

Architecture: **Swift AppKit / WKWebView → management layer / API gateway → version adapters → original TensorFold**.

- App and engine versions are independent. Upstream core code is not modified.
- Updates are checked automatically and installed manually. Candidate environments are pinned, checked for compatibility and tested before activation; failures restore the previous version.
- The management interface stays available while inference is stopped.
- Before loading large models, the manager checks system memory pressure, capacity budgets and existing inference services. A model switch stops the old process and verifies exit before loading the next one.
- Manager settings, statistics, logs and chat history are stored in the App's own data directory. The native bridge supplies the management token; it is never stored in the URL or browser storage.

## Model sources and compatibility

Model architecture, revision, quantization format, shards, tokenizer/template and MTP files must match the engine. `hf-mirror.com` is a third-party mirror. Unverified ModelScope mappings are not offered; similar repository names do not prove equivalence to official HF checkpoints.

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
