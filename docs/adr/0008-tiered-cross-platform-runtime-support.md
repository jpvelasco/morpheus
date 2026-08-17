# ADR-0008: Tiered Cross-Platform Runtime Support

Status: Accepted

Date: 2026-08-11

## Context

The control plane can be portable, but inference engines, model formats, GPU
APIs, process supervision, and service managers differ materially across Linux,
Windows, and macOS. Docker Compose and vLLM are strong Linux paths but cannot be
treated as universal GPU abstractions. Claiming platform support merely because
FastAPI starts would contradict Morpheus's evidence-bounded support policy.

## Decision

Morpheus provides one portable control-plane contract and selects host,
telemetry, service, process, and runtime adapters from discovered capabilities.
Stable v0.2 requires one fully qualified native managed-inference path on each
of these targets:

- Ubuntu 26.04 LTS x86-64;
- Windows 11 x86-64;
- macOS 14 or later on Apple Silicon.

Native `llama.cpp`/`llama-server` with verified GGUF artifacts is the common
Tier 1 engine path. Linux NVIDIA additionally supports a qualified vLLM tier.
Ollama is an optional discovered adapter. Windows vLLM through WSL2 and Apple
Silicon vLLM-Metal/MLX begin as experimental. Intel Macs and other operating
system, architecture, accelerator, and engine combinations remain unvalidated
or unsupported until their complete evidence lanes pass.

Docker Compose remains one Linux runtime adapter. Native process supervision is
the portable baseline: Unix process groups on Linux/macOS and Windows Job
Objects on Windows. Services use per-user systemd, LaunchAgent, and Windows
per-user background registration respectively. Hardware evidence uses portable
system collectors plus vendor/platform adapters and records unavailable,
permission-denied, and unsupported data explicitly rather than converting it to
zero.

## Consequences

- A consistent Morpheus workflow does not imply an identical engine or model
  artifact on every platform.
- Model family, model format, quantization, engine build, OS, architecture,
  accelerator API, and validation tier are immutable deployment-plan inputs.
- Native path, ACL/reparse-point, process-tree, sleep/resume, service, installer,
  upgrade, rollback, and recovery behavior require OS-specific tests.
- ubuntu-1 and ubuntu-2 remain named Linux qualification machines, not the
  entire support definition.
- New platform claims require physical evidence for discovery, installation,
  serving, benchmark, lifecycle, access, and recovery.

## Alternatives Considered

### Use Docker for every managed runtime

Rejected because GPU container support and host integration are not equivalent
across the target operating systems, particularly on macOS.

### Require vLLM on every platform

Rejected because core vLLM is Linux-native; WSL2 and community Apple paths have
different operational and support characteristics.

### Call only the control plane cross-platform

Rejected because the v0.2 stable claim requires Morpheus to install, run,
benchmark, and recover a useful native inference path on every advertised OS.

## References

- [llama.cpp hardware backends](https://github.com/ggml-org/llama.cpp)
- [llama-server capabilities](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [vLLM GPU installation and platform requirements](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [Ollama Windows](https://docs.ollama.com/windows) and
  [Ollama macOS](https://docs.ollama.com/macos)
- [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/)
- [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Apple launch agents and daemons](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
