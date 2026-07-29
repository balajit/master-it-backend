"""Status legend construction for learning experience mapper."""

from __future__ import annotations

from learning_platform.presentation.mappers.configuration import MappingConfiguration
from learning_platform.presentation.models import CardStatus, StatusLegend


def build_status_legend_from_config(
    config: MappingConfiguration,
) -> list[StatusLegend]:
    """Build status legend from configuration."""
    if not config.status_legend.show_legend:
        return []

    if config.status_legend.custom_legend is not None:
        return [
            StatusLegend(
                status=CardStatus(item.get("status", "not_started")),
                label=item.get("label", ""),
                description=item.get("description", ""),
                icon_name=item.get("icon_name", ""),
                color_hex=item.get("color_hex", ""),
            )
            for item in config.status_legend.custom_legend
        ]

    return [
        StatusLegend(
            status=CardStatus.NOT_STARTED,
            label="Not Started",
            description="You haven't begun this lesson yet",
            icon_name="circle-outline",
            color_hex="#E5E7EB",
        ),
        StatusLegend(
            status=CardStatus.IN_PROGRESS,
            label="In Progress",
            description="You're currently working on this",
            icon_name="circle-half",
            color_hex="#FCD34D",
        ),
        StatusLegend(
            status=CardStatus.COMPLETED,
            label="Completed",
            description="You've finished this lesson",
            icon_name="check-circle",
            color_hex="#34D399",
        ),
        StatusLegend(
            status=CardStatus.MASTERED,
            label="Mastered",
            description="You've demonstrated mastery",
            icon_name="star",
            color_hex="#10B981",
        ),
        StatusLegend(
            status=CardStatus.LOCKED,
            label="Locked",
            description="Complete prerequisites to unlock",
            icon_name="lock",
            color_hex="#9CA3AF",
        ),
        StatusLegend(
            status=CardStatus.PRACTICED,
            label="Practiced",
            description="You've practiced this material",
            icon_name="repeat",
            color_hex="#60A5FA",
        ),
        StatusLegend(
            status=CardStatus.ATTEMPTED,
            label="Attempted",
            description="You've attempted this assessment",
            icon_name="pencil",
            color_hex="#A78BFA",
        ),
    ]
