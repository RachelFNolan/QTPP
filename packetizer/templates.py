from __future__ import annotations

from dataclasses import dataclass

from .build_spec import (
    AggregateQuota,
    AllowedCountPatterns,
    CategoryCountRule,
    CategoryQuota,
    LeftoverBound,
    PacketBuildSpec,
)


@dataclass(frozen=True, slots=True)
class BuildTemplate:
    name: str
    tossup_capacity: int
    bonus_capacity: int
    quotas: tuple[CategoryQuota, ...]
    allowed_patterns: tuple[AllowedCountPatterns | CategoryCountRule, ...]
    leftover_bounds: tuple[LeftoverBound, ...] = (
        LeftoverBound("tossup"),
        LeftoverBound("bonus"),
    )

    def create_spec(
        self,
        packet_count: int,
        *,
        aggregate_quotas: tuple[AggregateQuota, ...] = (),
    ) -> PacketBuildSpec:
        return PacketBuildSpec(
            packet_count=packet_count,
            tossup_capacity=self.tossup_capacity,
            bonus_capacity=self.bonus_capacity,
            quotas=self.quotas,
            allowed_patterns=self.allowed_patterns,
            aggregate_quotas=aggregate_quotas,
            leftover_bounds=self.leftover_bounds,
        )
