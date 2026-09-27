#!/usr/bin/env python3
"""Prepare a local embedding model directory for development.

Downloads a model from Hugging Face, exports and quantises it to ONNX, and
writes the model file, the tokenizer and the manifest the local runtime reads.
Point `LOCAL_EMBEDDING_MODEL_DIR` at the printed directory. In a release the
desktop app materialises the same three files; nothing here runs in the app.

The model is never committed: the output directory is under `agents/.cache/`.

torch and optimum are only needed here, so this runs in its own environment:

    uv run --no-project --no-config --script scripts/dev/prepare_embedding_model.py \
        --repo-id cl-nagoya/ruri-v3-30m \
        --revision 24899e5de370b56d179604a007c0d727bf144504 \
        --slug ruri-v3-30m-int8 \
        --pooling mean --max-tokens 512 \
        --query-prefix '検索クエリ: ' --document-prefix '検索文書: '

A model that publishes its own ONNX graph skips the export:

    ... --repo-id hotchpotch/bekko-embedding-v1-a25m \
        --onnx-file onnx/model_qint8_arm64_not_recommended.onnx --no-quantize

Every model-specific value becomes a manifest field, so swapping the bundled
model means running this with different arguments and shipping the result.

When the graph is taken from the repository unchanged (`--onnx-file` together
with `--no-quantize`), the bundled files are byte-identical to the upstream
ones, so this also prints the contents of
`frontend/electron/embedding_model_release.json`: swapping the bundled model is
then a matter of running this and replacing that file with the output.
"""

# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "huggingface-hub",
#     "numpy",
#     "onnx==1.22.0",
#     "onnxruntime==1.29.0",
#     "optimum==2.1.0",
#     "optimum-onnx[onnxruntime]==0.1.0",
#     "pydantic==2.13.4",
#     "sentencepiece==0.2.2",
#     "torch==2.14.0",
#     "transformers==4.57.6",
# ]
# ///

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy

AGENTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENTS_ROOT / "src"))

from pantaray_agents.local_runtime.embedding_local.manifest import (  # noqa: E402
    LOCAL_EMBEDDING_MANIFEST_FILENAME,
    LocalEmbeddingManifest,
    LocalEmbeddingPooling,
    artifact_revision_digest,
    file_sha256,
    worst_case_chunk_text,
)
from pantaray_agents.local_runtime.embedding_local.runner import (  # noqa: E402
    open_local_embedding_model,
    pool_hidden_states,
)

MODEL_FILENAME = "model.onnx"
TOKENIZER_FILENAME = "tokenizer.json"
DEFAULT_CACHE_ROOT = AGENTS_ROOT / ".cache" / "embedding_model"
# The file the desktop build reads to fetch and verify the bundled model.
RELEASE_PIN_PATH = "frontend/electron/embedding_model_release.json"
# Long enough that the tokenizer truncates it at the window under test, whatever
# the tokenizer's characters-per-token ratio is.
_PROBE_UNIT = "記憶の検索 memory search "


def _download(*, repo_id: str, revision: str, filename: str, destination: Path) -> None:
    from huggingface_hub import hf_hub_download

    shutil.copyfile(
        hf_hub_download(repo_id=repo_id, filename=filename, revision=revision),
        destination,
    )


def _export_onnx(*, repo_id: str, revision: str, destination: Path) -> None:
    from optimum.exporters.onnx import main_export

    with tempfile.TemporaryDirectory() as raw:
        main_export(
            model_name_or_path=repo_id,
            output=raw,
            task="feature-extraction",
            revision=revision,
        )
        shutil.copyfile(Path(raw) / MODEL_FILENAME, destination)


def _quantize(source: Path, destination: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(source, destination, weight_type=QuantType.QUInt8)


def _refuse_second_quantisation(graph_path: Path) -> None:
    """Stop before quantising a graph the repository already quantised.

    `--onnx-file` reaches both the full-precision and the int8 graph a
    repository publishes, and quantising the int8 one again produces an
    artifact that passes every later check while embedding worse than either.
    """
    import onnx

    graph = onnx.load(str(graph_path), load_external_data=False)
    quantised_types = {onnx.TensorProto.INT8, onnx.TensorProto.UINT8}
    if any(tensor.data_type in quantised_types for tensor in graph.graph.initializer):
        raise SystemExit(
            "the downloaded graph is already quantised; pass --no-quantize to "
            "bundle it as published, or point --onnx-file at the "
            "full-precision graph"
        )


def _measure_chunk_length(
    *,
    model_dir: Path,
    max_tokens: int,
    prefixes: tuple[str, str],
) -> int:
    """The longest chunk that still fits the window, in characters.

    Memory fragments are split by character count, so this is what keeps the
    tail of a chunk from being truncated away before it reaches the index.
    """
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(model_dir / TOKENIZER_FILENAME))

    def fits(length: int) -> bool:
        chunk = worst_case_chunk_text(length)
        return all(
            len(tokenizer.encode(prefix + chunk).ids) <= max_tokens
            for prefix in prefixes
        )

    low, high = 1, max_tokens
    if not fits(low):
        raise SystemExit(f"not even one character fits a window of {max_tokens}")
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


def _probe_dimensions(
    *,
    model_dir: Path,
    max_tokens: int,
    pooling: LocalEmbeddingPooling,
) -> int:
    """Run the graph at the full window and report the vector width.

    This is what makes `--max-tokens` a checked claim: a graph that cannot take
    the requested window fails here instead of truncating memory chunks in the
    field.
    """
    import onnxruntime
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(model_dir / TOKENIZER_FILENAME))
    tokenizer.enable_truncation(max_length=max_tokens)
    encoding = tokenizer.encode(_PROBE_UNIT * max_tokens)
    if len(encoding.ids) != max_tokens:
        raise SystemExit(
            f"the tokenizer produced {len(encoding.ids)} ids for a window of "
            f"{max_tokens}; the probe text is too short"
        )
    session = onnxruntime.InferenceSession(
        str(model_dir / MODEL_FILENAME),
        providers=["CPUExecutionProvider"],
    )
    input_ids = numpy.asarray([encoding.ids], dtype=numpy.int64)
    attention_mask = numpy.asarray([encoding.attention_mask], dtype=numpy.int64)
    names = {entry.name for entry in session.get_inputs()}
    feeds = {"input_ids": input_ids}
    if "attention_mask" in names:
        feeds["attention_mask"] = attention_mask
    if "token_type_ids" in names:
        feeds["token_type_ids"] = numpy.zeros_like(input_ids)
    pooled = pool_hidden_states(
        session.run(None, feeds)[0],
        attention_mask,
        pooling=pooling,
    )
    return int(pooled.shape[1])


def prepare(arguments: argparse.Namespace) -> tuple[Path, LocalEmbeddingManifest]:
    model_dir = Path(arguments.output_dir or DEFAULT_CACHE_ROOT / arguments.slug)
    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.mkdir(parents=True)
    model_path = model_dir / MODEL_FILENAME

    _download(
        repo_id=arguments.repo_id,
        revision=arguments.revision,
        filename=arguments.tokenizer_file,
        destination=model_dir / TOKENIZER_FILENAME,
    )
    with tempfile.TemporaryDirectory() as staging:
        graph_path = Path(staging) / MODEL_FILENAME
        if arguments.onnx_file is None:
            print("exporting ONNX with optimum", flush=True)
            _export_onnx(
                repo_id=arguments.repo_id,
                revision=arguments.revision,
                destination=graph_path,
            )
        else:
            print(f"downloading {arguments.onnx_file}", flush=True)
            _download(
                repo_id=arguments.repo_id,
                revision=arguments.revision,
                filename=arguments.onnx_file,
                destination=graph_path,
            )
        if arguments.quantize:
            _refuse_second_quantisation(graph_path)
            print("quantising to int8", flush=True)
            _quantize(graph_path, model_path)
        else:
            shutil.copyfile(graph_path, model_path)

    dimensions = _probe_dimensions(
        model_dir=model_dir,
        max_tokens=arguments.max_tokens,
        pooling=arguments.pooling,
    )
    max_text_chars = _measure_chunk_length(
        model_dir=model_dir,
        max_tokens=arguments.max_tokens,
        prefixes=(arguments.query_prefix, arguments.document_prefix),
    )
    identity = {
        "model_id": arguments.repo_id,
        "source_revision": arguments.revision,
        "model_slug": arguments.slug,
        "model_file": MODEL_FILENAME,
        "model_sha256": file_sha256(model_path),
        "tokenizer_file": TOKENIZER_FILENAME,
        "tokenizer_sha256": file_sha256(model_dir / TOKENIZER_FILENAME),
        "dimensions": dimensions,
        "max_tokens": arguments.max_tokens,
        "max_text_chars": max_text_chars,
        "pooling": arguments.pooling,
        "query_prefix": arguments.query_prefix,
        "document_prefix": arguments.document_prefix,
    }
    manifest = LocalEmbeddingManifest(
        artifact_revision=artifact_revision_digest(**identity),
        **identity,
    )
    (model_dir / LOCAL_EMBEDDING_MANIFEST_FILENAME).write_text(
        json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    # The runtime's own loader is the acceptance check for what was written.
    open_local_embedding_model(model_dir=model_dir, manifest=manifest)
    return model_dir, manifest


def _print_release_pin(
    *,
    arguments: argparse.Namespace,
    manifest: LocalEmbeddingManifest,
    model_dir: Path,
) -> None:
    """Print what the desktop build needs to fetch exactly these files.

    The build downloads the pinned files from the model repository, so the pin
    only holds when the prepared files are the repository's own bytes. An
    exported or locally quantised graph exists nowhere else, and saying so is
    what keeps the desktop build from pinning bytes it cannot fetch.
    """
    if arguments.onnx_file is None or arguments.quantize:
        print(
            f"\n{RELEASE_PIN_PATH} not printed: the graph was produced here "
            "rather than taken from the model repository, so the desktop build "
            "cannot fetch it. Publish the prepared artifact somewhere the build "
            "can pin before bundling this model."
        )
        return
    pin = {
        "modelId": manifest.model_id,
        "sourceRevision": manifest.source_revision,
        "files": [
            {
                "sourcePath": source_path,
                "installName": install_name,
                "sha256": digest,
                "bytes": (model_dir / install_name).stat().st_size,
            }
            for source_path, install_name, digest in (
                (arguments.onnx_file, manifest.model_file, manifest.model_sha256),
                (
                    arguments.tokenizer_file,
                    manifest.tokenizer_file,
                    manifest.tokenizer_sha256,
                ),
            )
        ],
        "manifest": manifest.model_dump(),
    }
    print(f"\nreplace {RELEASE_PIN_PATH} with:\n")
    print(json.dumps(pin, ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo-id", required=True, help="Hugging Face repository")
    parser.add_argument("--revision", required=True, help="pinned commit of that repo")
    parser.add_argument(
        "--slug",
        required=True,
        help="identifier for this artifact inside the profile id, e.g. ruri-v3-30m-int8",
    )
    parser.add_argument("--pooling", required=True, choices=("mean", "cls"))
    parser.add_argument(
        "--max-tokens",
        required=True,
        type=int,
        help="token window the profile embeds at; it also decides the chunk length",
    )
    parser.add_argument("--query-prefix", default="")
    parser.add_argument("--document-prefix", default="")
    parser.add_argument(
        "--onnx-file",
        help="path of an official ONNX graph in the repo; exported when omitted",
    )
    parser.add_argument("--tokenizer-file", default=TOKENIZER_FILENAME)
    parser.add_argument(
        "--no-quantize",
        dest="quantize",
        action="store_false",
        help="keep the exported precision instead of dynamic int8 quantisation",
    )
    parser.add_argument("--output-dir", help=f"default: {DEFAULT_CACHE_ROOT}/<slug>")
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    model_dir, manifest = prepare(arguments)
    print(
        f"\nprepared {manifest.model_id} "
        f"({manifest.dimensions} dimensions, "
        f"{manifest.max_text_chars} characters per chunk, "
        f"{(model_dir / MODEL_FILENAME).stat().st_size / 1_000_000:.1f} MB graph)\n"
        f"LOCAL_EMBEDDING_MODEL_DIR={model_dir}"
    )
    _print_release_pin(arguments=arguments, manifest=manifest, model_dir=model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
