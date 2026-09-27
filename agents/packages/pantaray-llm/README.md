# pantaray-llm

Provider-neutral contracts shared by the Pantaray local runtime and the
Pantaray Cloud proxy: LLM tool-use and Action-turn request/response types,
media descriptors, the proxy error contract, and inference purpose IDs.

This package must not depend on the local runtime, the cloud service, or any
provider SDK. It is a uv workspace member of `agents/`.
