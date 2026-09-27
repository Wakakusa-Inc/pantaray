"""Prompt-visible contracts for ActionAgent tool definitions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast


@dataclass(frozen=True, slots=True)
class PromptArgSpec:
    """LLM向けに表示する引数の契約。"""

    name: str
    type_label: str
    required: bool
    description: str
    children: tuple[PromptArgSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptVariantSpec:
    """discriminator ごとの LLM 向け引数契約。"""

    discriminator_field: str
    discriminator_value: str
    common_args: tuple[PromptArgSpec, ...]
    variant_args: tuple[PromptArgSpec, ...]


@dataclass(frozen=True, slots=True)
class PromptContract:
    """LLM に提示するツール契約。"""

    description: str
    args: tuple[PromptArgSpec, ...] = ()
    variants: tuple[PromptVariantSpec, ...] = ()


type PromptReferenceMemberClassifier = Callable[[object], bool]


class PromptGuideSpec(Protocol):
    @property
    def what(self) -> str: ...

    @property
    def when(self) -> str: ...

    @property
    def pitfalls(self) -> str: ...


class PromptReferenceMember(Protocol):
    canonical_name: str
    prompt_type: str
    description: str
    required: bool
    llm_visible: bool
    llm_advanced: bool
    llm_order: int


class PromptFieldMember(Protocol):
    name: str
    required: bool
    prompt_type: str
    description: str
    llm_visible: bool
    llm_advanced: bool
    llm_order: int
    runtime_injected: bool
    prompt_name: str | None
    prompt_children: Sequence[PromptArgSpec]
    prompt_flatten_children: bool
    children: Sequence[object]


class PromptVariantInput(Protocol):
    @property
    def discriminator_field(self) -> str: ...

    @property
    def discriminator_value(self) -> str: ...

    @property
    def fields(self) -> Sequence[object]: ...


class PromptInputSpec(Protocol):
    @property
    def fields(self) -> Sequence[object]: ...

    @property
    def variants(self) -> Sequence[PromptVariantInput]: ...


class PromptToolSpec(Protocol):
    @property
    def guide(self) -> PromptGuideSpec: ...

    @property
    def input_spec(self) -> PromptInputSpec: ...


def build_description_from_guide(guide: PromptGuideSpec) -> str:
    """Guide から複数行の description 文を生成する。"""

    def section_text(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()

    sections = [
        ("Purpose", section_text(guide.what)),
        ("When", section_text(guide.when)),
        ("Avoid", section_text(guide.pitfalls)),
    ]
    parts = [f"{title}:\n{body}" for title, body in sections if body]
    return "\n\n".join(part for part in parts if part)


def build_prompt_contract(
    spec: PromptToolSpec,
    *,
    is_reference_member: PromptReferenceMemberClassifier,
) -> PromptContract:
    """ToolSpec から prompt-visible contract を生成する。"""

    if spec.input_spec.variants:
        variants = _build_prompt_variants(
            spec.input_spec,
            is_reference_member=is_reference_member,
        )
        return PromptContract(
            description=build_description_from_guide(spec.guide),
            variants=variants,
        )

    return PromptContract(
        description=build_description_from_guide(spec.guide),
        args=_build_prompt_args(
            spec.input_spec.fields,
            is_reference_member=is_reference_member,
        ),
    )


def _build_prompt_variants(
    input_spec: PromptInputSpec,
    *,
    is_reference_member: PromptReferenceMemberClassifier,
) -> tuple[PromptVariantSpec, ...]:
    shared_args = _build_prompt_args(
        input_spec.fields,
        is_reference_member=is_reference_member,
    )
    shared_arg_names = {arg.name for arg in shared_args}
    variant_specs: list[tuple[PromptVariantInput, tuple[PromptArgSpec, ...]]] = []
    for variant in input_spec.variants:
        variant_args = _build_prompt_args(
            variant.fields,
            is_reference_member=is_reference_member,
        )
        overlapping_names = shared_arg_names & {arg.name for arg in variant_args}
        if overlapping_names:
            overlapping = ", ".join(sorted(overlapping_names))
            raise ValueError(
                "Variant-specific prompt args must not overlap with shared prompt args: "
                f"{overlapping}"
            )
        variant_specs.append((variant, variant_args))

    common_variant_args, common_names = _partition_prompt_variant_args(variant_specs)

    prompt_variants: list[PromptVariantSpec] = []
    for variant, variant_args in variant_specs:
        discriminator_arg = PromptArgSpec(
            name=variant.discriminator_field,
            type_label=f"literal('{variant.discriminator_value}')",
            required=True,
            description=f"Must be '{variant.discriminator_value}'.",
        )
        prompt_variants.append(
            PromptVariantSpec(
                discriminator_field=variant.discriminator_field,
                discriminator_value=variant.discriminator_value,
                common_args=(discriminator_arg, *shared_args, *common_variant_args),
                variant_args=tuple(
                    arg for arg in variant_args if arg.name not in common_names
                ),
            )
        )
    return tuple(prompt_variants)


def _partition_prompt_variant_args(
    variants: Sequence[tuple[PromptVariantInput, tuple[PromptArgSpec, ...]]],
) -> tuple[tuple[PromptArgSpec, ...], set[str]]:
    """Partition variant args into prompt-visible common args and per-variant args.

    Commonization is name-based for candidate alignment, but it is intentionally strict:
    only args whose prompt-visible metadata fully matches across all variants are promoted
    into ``common_args``. Same-name args with different visible contracts remain variant-
    specific instead of being silently merged.
    """
    if not variants:
        return (), set()

    canonical_by_name: dict[str, PromptArgSpec] = {}
    shared_candidate_names: set[str] = set()
    first_variant_order: list[str] = []

    for index, (_, args) in enumerate(variants):
        seen_names_in_variant: set[str] = set()
        for arg in args:
            if arg.name in seen_names_in_variant:
                raise ValueError(
                    f"Duplicate prompt arg name '{arg.name}' in a single variant."
                )
            seen_names_in_variant.add(arg.name)
            if index == 0:
                canonical_by_name[arg.name] = arg
                shared_candidate_names.add(arg.name)
                first_variant_order.append(arg.name)

        if index == 0:
            continue

        args_by_name = {arg.name: arg for arg in args}
        shared_candidate_names &= set(args_by_name.keys())
        for name in tuple(shared_candidate_names):
            if canonical_by_name[name] != args_by_name[name]:
                shared_candidate_names.discard(name)

    variant_count = len(variants)
    if variant_count == 1:
        return (), set()

    common_names = shared_candidate_names
    common_args = tuple(
        canonical_by_name[name] for name in first_variant_order if name in common_names
    )
    return common_args, common_names


def _build_prompt_args(
    members: Sequence[object],
    *,
    is_reference_member: PromptReferenceMemberClassifier,
) -> tuple[PromptArgSpec, ...]:
    args_with_order: list[tuple[int, PromptArgSpec]] = []
    for member in members:
        args_with_order.extend(
            _build_prompt_args_for_member(
                member,
                is_reference_member=is_reference_member,
            )
        )
    args_with_order.sort(key=lambda item: item[0])
    return tuple(arg for _, arg in args_with_order)


def _build_prompt_args_for_member(
    member: object,
    *,
    is_reference_member: PromptReferenceMemberClassifier,
) -> list[tuple[int, PromptArgSpec]]:
    if is_reference_member(member):
        reference = cast(PromptReferenceMember, member)
        if not reference.llm_visible or reference.llm_advanced:
            return []
        return [
            (
                reference.llm_order,
                PromptArgSpec(
                    name=reference.canonical_name,
                    type_label=reference.prompt_type,
                    required=reference.required,
                    description=reference.description,
                ),
            )
        ]

    field = cast(PromptFieldMember, member)
    if field.runtime_injected or not field.llm_visible or field.llm_advanced:
        return []

    if field.prompt_flatten_children:
        return [
            (field.llm_order + index, child)
            for index, child in enumerate(
                _derive_child_prompt_args(
                    field,
                    is_reference_member=is_reference_member,
                )
            )
        ]

    return [
        (
            field.llm_order,
            PromptArgSpec(
                name=field.prompt_name or field.name,
                type_label=field.prompt_type,
                required=field.required,
                description=field.description,
                children=_derive_child_prompt_args(
                    field,
                    is_reference_member=is_reference_member,
                ),
            ),
        )
    ]


def _derive_child_prompt_args(
    member: PromptFieldMember,
    *,
    is_reference_member: PromptReferenceMemberClassifier,
) -> tuple[PromptArgSpec, ...]:
    if member.prompt_children:
        return tuple(member.prompt_children)
    if member.children:
        return _build_prompt_args(
            member.children,
            is_reference_member=is_reference_member,
        )
    return ()


def prompt_arg(
    name: str,
    type_label: str,
    *,
    required: bool,
    description: str,
    children: Sequence[PromptArgSpec] = (),
) -> PromptArgSpec:
    """PromptArgSpec の簡易ヘルパー。"""

    return PromptArgSpec(
        name=name,
        type_label=type_label,
        required=required,
        description=description,
        children=tuple(children),
    )


__all__ = [
    "PromptArgSpec",
    "PromptContract",
    "PromptReferenceMemberClassifier",
    "PromptVariantSpec",
    "build_description_from_guide",
    "build_prompt_contract",
    "prompt_arg",
]
